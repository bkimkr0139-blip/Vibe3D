"""Error analysis engine for Vibe3D Unity Accelerator.

Classifies MCP execution errors and suggests corrective actions.
Uses only the Python standard library.
"""

import copy
import difflib
import json
import logging
import math
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── Error categories ────────────────────────────────────────

class ErrorCategory(str, Enum):
    E1_PARSE_FAIL = "E1_PARSE_FAIL"
    E2_OBJECT_NOT_FOUND = "E2_OBJECT_NOT_FOUND"
    E3_MCP_DISCONNECTED = "E3_MCP_DISCONNECTED"
    E4_POSITION_CONFLICT = "E4_POSITION_CONFLICT"
    E5_SCHEMA_ERROR = "E5_SCHEMA_ERROR"
    E6_BATCH_LIMIT = "E6_BATCH_LIMIT"


# ── Analysis result ─────────────────────────────────────────

@dataclass
class ErrorAnalysis:
    category: ErrorCategory
    root_cause: str
    suggestions: list[dict[str, str]] = field(default_factory=list)
    auto_fixable: bool = False


# ── Known action types (for E1 fuzzy matching) ──────────────

KNOWN_ACTION_TYPES = [
    "create_primitive",
    "create_empty",
    "modify_object",
    "delete_object",
    "apply_material",
    "create_light",
    "duplicate_object",
    "set_parent",
    "screenshot",
    "save_scene",
]

KNOWN_SHAPES = ["Cube", "Sphere", "Cylinder", "Capsule", "Plane"]

# ── Batch size limit (matches PlanExecutor.MAX_BATCH) ───────

MAX_BATCH = 25

# ── Classification patterns ─────────────────────────────────

_PARSE_PATTERNS = [
    re.compile(r"(?i)json(?:decode)?error"),
    re.compile(r"(?i)unexpected token"),
    re.compile(r"(?i)invalid (?:json|syntax)"),
    re.compile(r"(?i)expecting (?:value|property)"),
    re.compile(r"(?i)unterminated string"),
]

_NOT_FOUND_PATTERNS = [
    re.compile(r"(?i)object\s+.*not\s+found"),
    re.compile(r"(?i)gameobject\s+.*not\s+found"),
    re.compile(r"(?i)target\s+.*(?:does not exist|not found|missing)"),
    re.compile(r"(?i)could\s+not\s+find"),
    re.compile(r"(?i)no\s+(?:game)?object\s+(?:named|with\s+name)"),
]

_DISCONNECT_PATTERNS = [
    re.compile(r"(?i)connect(?:ion)?\s+(?:refused|reset|timed?\s*out|closed|failed)"),
    re.compile(r"(?i)mcp\s+(?:server\s+)?(?:unreachable|down|disconnected)"),
    re.compile(r"(?i)sse\s+(?:connection\s+)?(?:lost|closed|failed)"),
    re.compile(r"(?i)errno\s+(?:111|104|10061)"),
    re.compile(r"(?i)(?:read|write)\s+timeout"),
]

_POSITION_PATTERNS = [
    re.compile(r"(?i)position\s+conflict"),
    re.compile(r"(?i)overlapping\s+(?:objects?|positions?)"),
    re.compile(r"(?i)collision\s+detected"),
    re.compile(r"(?i)same\s+position"),
]

_SCHEMA_PATTERNS = [
    re.compile(r"(?i)schema\s+(?:validation\s+)?(?:error|failed)"),
    re.compile(r"(?i)required\s+(?:property|field)\s+.*missing"),
    re.compile(r"(?i)invalid\s+(?:type|value|property)"),
    re.compile(r"(?i)is\s+not\s+valid\s+under"),
    re.compile(r"(?i)\[.*\]\s+.+(?:is not|should be|must be)"),
    re.compile(r"(?i)(?:color|position|scale|rotation)\s+.*(?:range|invalid|out\s+of)"),
    re.compile(r"(?i)(?:range|value)\s+.*(?:invalid|must\s+be|should\s+be)"),
]

_BATCH_PATTERNS = [
    re.compile(r"(?i)batch\s+(?:size\s+)?(?:limit|exceeded|too\s+(?:large|many))"),
    re.compile(r"(?i)too\s+many\s+(?:actions|commands|calls)"),
    re.compile(r"(?i)max(?:imum)?\s+(?:batch|actions)\s+(?:exceeded|reached)"),
]


# ── Core classification ─────────────────────────────────────

def _classify(error_str: str) -> ErrorCategory:
    """Classify an error string into a category."""
    checks = [
        (_DISCONNECT_PATTERNS, ErrorCategory.E3_MCP_DISCONNECTED),
        (_BATCH_PATTERNS, ErrorCategory.E6_BATCH_LIMIT),
        (_NOT_FOUND_PATTERNS, ErrorCategory.E2_OBJECT_NOT_FOUND),
        (_SCHEMA_PATTERNS, ErrorCategory.E5_SCHEMA_ERROR),
        (_POSITION_PATTERNS, ErrorCategory.E4_POSITION_CONFLICT),
        (_PARSE_PATTERNS, ErrorCategory.E1_PARSE_FAIL),
    ]
    for patterns, category in checks:
        for pat in patterns:
            if pat.search(error_str):
                return category

    # Fallback: default to parse-fail for truly unrecognisable errors
    return ErrorCategory.E1_PARSE_FAIL


def _extract_object_name(error_str: str) -> Optional[str]:
    """Try to pull the referenced object name out of the error message."""
    # Patterns like: 'Object "FooBar" not found', target 'Tank_A' not found
    for pat in [
        re.compile(r"""(?:object|target|gameobject)\s+['"]([^'"]+)['"]""", re.I),
        re.compile(r"""['"]([^'"]+)['"]\s+(?:not found|does not exist)""", re.I),
        re.compile(r"""(?:named|name)\s+['"]?(\S+?)['"]?\s+(?:not found|does not)""", re.I),
    ]:
        m = pat.search(error_str)
        if m:
            return m.group(1)
    return None


def _extract_invalid_action(error_str: str) -> Optional[str]:
    """Extract an unrecognised action type from a parse/schema error."""
    m = re.search(r"""(?:unknown|invalid|unrecognised)\s+(?:action\s+type|action|type)\s*[:=]?\s*['"]?(\w+)""", error_str, re.I)
    if m:
        return m.group(1)
    return None


# ── Per-category analysis helpers ────────────────────────────

def _analyze_parse_fail(
    error_str: str,
    plan: Optional[dict],
    scene_objects: list[str],
) -> ErrorAnalysis:
    """E1 -- Parse / unrecognised-command errors."""
    suggestions: list[dict[str, str]] = []
    auto_fixable = False

    bad_action = _extract_invalid_action(error_str)
    if bad_action:
        matches = difflib.get_close_matches(bad_action, KNOWN_ACTION_TYPES, n=3, cutoff=0.5)
        if matches:
            auto_fixable = True
            for m in matches:
                suggestions.append({
                    "label": f"Replace '{bad_action}' with '{m}'",
                    "fix_plan": f"change action type to '{m}'",
                })
        else:
            suggestions.append({
                "label": "Check action type spelling",
                "fix_plan": f"valid types: {', '.join(KNOWN_ACTION_TYPES)}",
            })
    else:
        suggestions.append({
            "label": "Verify JSON syntax of the plan",
            "fix_plan": "re-parse or regenerate the plan as valid JSON",
        })
        suggestions.append({
            "label": "Use known action types",
            "fix_plan": f"valid types: {', '.join(KNOWN_ACTION_TYPES)}",
        })

    return ErrorAnalysis(
        category=ErrorCategory.E1_PARSE_FAIL,
        root_cause=f"Failed to parse command or plan: {error_str[:200]}",
        suggestions=suggestions,
        auto_fixable=auto_fixable,
    )


def _analyze_object_not_found(
    error_str: str,
    plan: Optional[dict],
    scene_objects: list[str],
) -> ErrorAnalysis:
    """E2 -- Target object not found in scene."""
    suggestions: list[dict[str, str]] = []
    auto_fixable = False
    missing = _extract_object_name(error_str) or "unknown"

    if scene_objects:
        close = difflib.get_close_matches(missing, scene_objects, n=3, cutoff=0.4)
        if close:
            auto_fixable = True
            for name in close:
                suggestions.append({
                    "label": f"Did you mean '{name}'?",
                    "fix_plan": f"replace target '{missing}' with '{name}'",
                })
        else:
            suggestions.append({
                "label": f"No similar objects found for '{missing}'",
                "fix_plan": "verify the object exists or create it first",
            })
    else:
        suggestions.append({
            "label": "Scene object list unavailable",
            "fix_plan": "refresh scene hierarchy and retry",
        })

    return ErrorAnalysis(
        category=ErrorCategory.E2_OBJECT_NOT_FOUND,
        root_cause=f"Object '{missing}' not found in scene",
        suggestions=suggestions,
        auto_fixable=auto_fixable,
    )


def _analyze_mcp_disconnected(
    error_str: str,
    plan: Optional[dict],
    scene_objects: list[str],
) -> ErrorAnalysis:
    """E3 -- MCP server unreachable."""
    return ErrorAnalysis(
        category=ErrorCategory.E3_MCP_DISCONNECTED,
        root_cause="MCP server connection failed or timed out",
        suggestions=[
            {
                "label": "Check MCP server is running",
                "fix_plan": "verify Unity MCP plugin is active and listening",
            },
            {
                "label": "Check network / firewall",
                "fix_plan": "ensure MCP_SERVER_URL is reachable from this host",
            },
            {
                "label": "Retry after delay",
                "fix_plan": "wait 5 seconds and resubmit the plan",
            },
        ],
        auto_fixable=False,
    )


def _analyze_position_conflict(
    error_str: str,
    plan: Optional[dict],
    scene_objects: list[str],
) -> ErrorAnalysis:
    """E4 -- Two objects placed at the same coordinates."""
    suggestions: list[dict[str, str]] = [
        {
            "label": "Offset conflicting objects",
            "fix_plan": "add a small position delta to one of the overlapping objects",
        },
        {
            "label": "Review plan positions",
            "fix_plan": "check for duplicate position values in the action list",
        },
    ]

    auto_fixable = False
    if plan:
        actions = plan.get("actions", [])
        positions: dict[str, list[int]] = {}
        for idx, action in enumerate(actions):
            pos = action.get("position")
            if pos:
                key = f"{pos.get('x', 0)},{pos.get('y', 0)},{pos.get('z', 0)}"
                positions.setdefault(key, []).append(idx)
        dupes = {k: v for k, v in positions.items() if len(v) > 1}
        if dupes:
            auto_fixable = True
            for coord, indices in dupes.items():
                suggestions.append({
                    "label": f"Actions at ({coord}) overlap: indices {indices}",
                    "fix_plan": "auto-offset subsequent objects by +1 on x-axis",
                })

    return ErrorAnalysis(
        category=ErrorCategory.E4_POSITION_CONFLICT,
        root_cause="Position conflict detected between objects",
        suggestions=suggestions,
        auto_fixable=auto_fixable,
    )


def _analyze_schema_error(
    error_str: str,
    plan: Optional[dict],
    scene_objects: list[str],
) -> ErrorAnalysis:
    """E5 -- Schema validation failure with auto-correction attempts."""
    suggestions: list[dict[str, str]] = []
    auto_fixable = False

    # Missing position -- default to origin
    if re.search(r"(?i)position.*(?:required|missing)", error_str):
        auto_fixable = True
        suggestions.append({
            "label": "Add default position {x:0, y:0, z:0}",
            "fix_plan": "inject default position into actions missing it",
        })

    # Color out of 0-1 range (e.g. someone passed 0-255 values)
    if re.search(r"(?i)color.*(?:range|invalid|must be)", error_str):
        auto_fixable = True
        suggestions.append({
            "label": "Normalise color to 0-1 range",
            "fix_plan": "divide color components >1 by 255",
        })

    # Missing required field (generic)
    missing_field_match = re.search(
        r"""(?:required|missing)\s+(?:property|field)\s*[:=]?\s*['"]?(\w+)""", error_str, re.I
    )
    if missing_field_match:
        fname = missing_field_match.group(1)
        suggestions.append({
            "label": f"Add missing field '{fname}'",
            "fix_plan": f"supply a sensible default for '{fname}'",
        })

    if not suggestions:
        suggestions.append({
            "label": "Review plan against unity_plan.schema.json",
            "fix_plan": "validate the plan with plan_validator and fix reported errors",
        })

    return ErrorAnalysis(
        category=ErrorCategory.E5_SCHEMA_ERROR,
        root_cause=f"Plan schema validation failed: {error_str[:200]}",
        suggestions=suggestions,
        auto_fixable=auto_fixable,
    )


def _analyze_batch_limit(
    error_str: str,
    plan: Optional[dict],
    scene_objects: list[str],
) -> ErrorAnalysis:
    """E6 -- Too many actions for a single MCP batch."""
    total = 0
    if plan:
        total = len(plan.get("actions", []))

    return ErrorAnalysis(
        category=ErrorCategory.E6_BATCH_LIMIT,
        root_cause=f"Plan has {total} actions, exceeding batch limit of {MAX_BATCH}",
        suggestions=[
            {
                "label": f"Auto-split into batches of {MAX_BATCH}",
                "fix_plan": f"split {total} actions into {math.ceil(total / MAX_BATCH)} batches",
            },
        ],
        auto_fixable=True,
    )


# ── Public API: analyze ─────────────────────────────────────

_CATEGORY_HANDLERS = {
    ErrorCategory.E1_PARSE_FAIL: _analyze_parse_fail,
    ErrorCategory.E2_OBJECT_NOT_FOUND: _analyze_object_not_found,
    ErrorCategory.E3_MCP_DISCONNECTED: _analyze_mcp_disconnected,
    ErrorCategory.E4_POSITION_CONFLICT: _analyze_position_conflict,
    ErrorCategory.E5_SCHEMA_ERROR: _analyze_schema_error,
    ErrorCategory.E6_BATCH_LIMIT: _analyze_batch_limit,
}


def analyze(
    error_str: str,
    plan: Optional[dict] = None,
    scene_objects: Optional[list[str]] = None,
) -> ErrorAnalysis:
    """Classify *error_str* and return a structured analysis.

    Args:
        error_str: The raw error message from MCP execution.
        plan: The plan dict that was being executed (if available).
        scene_objects: Names of objects currently in the Unity scene.

    Returns:
        An ``ErrorAnalysis`` with category, root cause, suggestions,
        and whether the error can be auto-fixed.
    """
    if scene_objects is None:
        scene_objects = []

    category = _classify(error_str)
    handler = _CATEGORY_HANDLERS[category]
    analysis = handler(error_str, plan, scene_objects)

    logger.info(
        "Error classified as %s (auto_fixable=%s): %s",
        analysis.category.value,
        analysis.auto_fixable,
        analysis.root_cause,
    )
    return analysis


# ── Public API: generate_fix_plan ────────────────────────────

def generate_fix_plan(analysis: ErrorAnalysis, plan: Optional[dict] = None) -> dict[str, Any]:
    """Create a corrected plan based on the analysis.

    Returns a dict with:
        - ``fixed`` (bool): whether a fix was produced
        - ``plan`` (dict | None): the corrected plan (or None)
        - ``batches`` (list[dict] | None): split batches for E6
        - ``description`` (str): human-readable summary
    """
    if plan is None or not analysis.auto_fixable:
        return {
            "fixed": False,
            "plan": None,
            "batches": None,
            "description": "No automatic fix available; review suggestions manually.",
        }

    fixed_plan = copy.deepcopy(plan)
    actions = fixed_plan.get("actions", [])
    description_parts: list[str] = []

    # ── E1: replace bad action type with best match ──────────
    if analysis.category == ErrorCategory.E1_PARSE_FAIL:
        for action in actions:
            atype = action.get("type", "")
            if atype not in KNOWN_ACTION_TYPES:
                matches = difflib.get_close_matches(atype, KNOWN_ACTION_TYPES, n=1, cutoff=0.5)
                if matches:
                    action["type"] = matches[0]
                    description_parts.append(f"corrected action type '{atype}' -> '{matches[0]}'")
        if description_parts:
            return {
                "fixed": True,
                "plan": fixed_plan,
                "batches": None,
                "description": "; ".join(description_parts),
            }

    # ── E2: replace missing target with closest scene object ─
    if analysis.category == ErrorCategory.E2_OBJECT_NOT_FOUND:
        for suggestion in analysis.suggestions:
            fix = suggestion.get("fix_plan", "")
            m = re.match(r"replace target '(.+?)' with '(.+?)'", fix)
            if m:
                old_name, new_name = m.group(1), m.group(2)
                for action in actions:
                    if action.get("target") == old_name:
                        action["target"] = new_name
                        description_parts.append(f"target '{old_name}' -> '{new_name}'")
                # Use only the first (best) suggestion
                break
        if description_parts:
            return {
                "fixed": True,
                "plan": fixed_plan,
                "batches": None,
                "description": "; ".join(description_parts),
            }

    # ── E4: offset overlapping positions ─────────────────────
    if analysis.category == ErrorCategory.E4_POSITION_CONFLICT:
        seen_positions: dict[str, int] = {}
        for action in actions:
            pos = action.get("position")
            if pos is None:
                continue
            key = f"{pos.get('x', 0)},{pos.get('y', 0)},{pos.get('z', 0)}"
            count = seen_positions.get(key, 0)
            if count > 0:
                pos["x"] = pos.get("x", 0) + count * 1.0
                description_parts.append(
                    f"offset action '{action.get('name', action.get('target', '?'))}' x+={count}"
                )
            seen_positions[key] = count + 1
        if description_parts:
            return {
                "fixed": True,
                "plan": fixed_plan,
                "batches": None,
                "description": "; ".join(description_parts),
            }

    # ── E5: auto-correct schema issues ───────────────────────
    if analysis.category == ErrorCategory.E5_SCHEMA_ERROR:
        for action in actions:
            atype = action.get("type", "")

            # Inject default position where required
            if atype in ("create_primitive", "create_empty", "create_light", "modify_object"):
                if "position" not in action:
                    action["position"] = {"x": 0, "y": 0, "z": 0}
                    description_parts.append(
                        f"added default position to '{action.get('name', action.get('target', '?'))}'"
                    )

            # Normalise color components from 0-255 to 0-1
            color = action.get("color")
            if color and isinstance(color, dict):
                needs_norm = any(
                    isinstance(v, (int, float)) and v > 1.0
                    for k, v in color.items()
                    if k in ("r", "g", "b", "a")
                )
                if needs_norm:
                    for ch in ("r", "g", "b"):
                        if ch in color and isinstance(color[ch], (int, float)) and color[ch] > 1.0:
                            color[ch] = round(color[ch] / 255.0, 4)
                    # Clamp alpha to 1.0 max
                    if "a" in color and isinstance(color["a"], (int, float)) and color["a"] > 1.0:
                        color["a"] = round(min(color["a"] / 255.0, 1.0), 4)
                    description_parts.append(
                        f"normalised color for '{action.get('target', action.get('name', '?'))}'"
                    )

        if description_parts:
            return {
                "fixed": True,
                "plan": fixed_plan,
                "batches": None,
                "description": "; ".join(description_parts),
            }

    # ── E6: split into batches ───────────────────────────────
    if analysis.category == ErrorCategory.E6_BATCH_LIMIT and len(actions) > MAX_BATCH:
        batches: list[dict] = []
        for i in range(0, len(actions), MAX_BATCH):
            batch_plan = copy.deepcopy(fixed_plan)
            batch_plan["actions"] = actions[i : i + MAX_BATCH]
            batch_plan["description"] = (
                f"{fixed_plan.get('description', '')} [batch {i // MAX_BATCH + 1}]"
            )
            batches.append(batch_plan)
        return {
            "fixed": True,
            "plan": None,
            "batches": batches,
            "description": f"split {len(actions)} actions into {len(batches)} batches of <={MAX_BATCH}",
        }

    # Nothing matched -- shouldn't happen for auto_fixable, but be safe
    return {
        "fixed": False,
        "plan": None,
        "batches": None,
        "description": "Auto-fix flagged but no correction applied; review suggestions.",
    }
