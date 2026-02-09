"""Predictive action suggestion engine for the Vibe3D Unity Accelerator.

Analyzes command history and scene context to suggest next likely actions.
Provides digital-twin-aware suggestions based on fermentation simulation state.
"""

import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── Fermentation color maps (mirrored from fermentation_bridge) ─────────────

PH_COLORS = {
    "critical_low": {"r": 0.9, "g": 0.1, "b": 0.1, "a": 1.0},   # pH < 5.5
    "low":          {"r": 0.9, "g": 0.5, "b": 0.1, "a": 1.0},    # pH 5.5-6.5
    "normal":       {"r": 0.15, "g": 0.65, "b": 0.15, "a": 1.0}, # pH 6.5-7.5
}

TEMP_COLORS = {
    "hot":    {"r": 0.9, "g": 0.1, "b": 0.1, "a": 1.0},    # T > 45
    "warm":   {"r": 0.9, "g": 0.5, "b": 0.1, "a": 1.0},    # T 40-45
    "normal": {"r": 0.15, "g": 0.65, "b": 0.15, "a": 1.0},  # T 30-40
    "cold":   {"r": 0.2, "g": 0.4, "b": 0.9, "a": 1.0},     # T < 30
}


# ── Data classes ────────────────────────────────────────────────────────────

@dataclass
class Suggestion:
    """A single predicted action suggestion."""
    label: str
    command: str
    confidence: float  # 0.0 to 1.0
    category: str      # e.g. "workflow", "twin", "history", "template"


@dataclass
class WorkflowStep:
    """A single step within a workflow template."""
    prompt: str
    param_type: str  # "text", "position", "material", "number"
    options: Optional[list[str]] = None


@dataclass
class WorkflowTemplate:
    """A reusable multi-step workflow template."""
    name: str
    steps: list[WorkflowStep]
    plan_template: dict = field(default_factory=dict)


# ── Workflow pattern definitions ────────────────────────────────────────────

# Maps a command keyword/type to a list of likely follow-up commands.
# Each entry: (label, command_template, base_confidence, category)
WORKFLOW_PATTERNS: dict[str, list[tuple[str, str, float, str]]] = {
    # After creating a floor -> lights, walls, equipment
    "floor": [
        ("Add lights", "조명 4개 높이 5m", 0.85, "workflow"),
        ("Add wall", "벽 10m 높이 3m", 0.75, "workflow"),
        ("Place equipment", "실린더 이름 Tank_A (0, 1, 0)", 0.70, "workflow"),
        ("Apply floor material", "Floor 색상 concrete 변경", 0.65, "workflow"),
    ],
    # After creating an object -> color/material, rename, position, duplicate
    "create": [
        ("Change color/material", "{target} 색상 스테인리스 변경", 0.80, "workflow"),
        ("Rename object", "{target} 이름을 변경", 0.65, "workflow"),
        ("Adjust position", "이동 {target} 을 (0, 0, 0)", 0.70, "workflow"),
        ("Duplicate object", "복제 {target}", 0.60, "workflow"),
    ],
    # After placing equipment -> sensor, pipe connections
    "equipment": [
        ("Add sensor", "구 이름 Sensor_Temp (0, 2, 0)", 0.80, "workflow"),
        ("Connect pipe", "캡슐 이름 Pipe_01 (0, 1, 0)", 0.75, "workflow"),
        ("Apply material", "{target} 색상 steel 변경", 0.70, "workflow"),
        ("Duplicate equipment", "복제 {target}", 0.55, "workflow"),
    ],
    # After screenshot -> save scene
    "screenshot": [
        ("Save scene", "씬 저장", 0.90, "workflow"),
        ("Take another screenshot", "스크린샷", 0.40, "workflow"),
    ],
    # After color/material change
    "material": [
        ("Adjust position", "이동 {target} 을 (0, 0, 0)", 0.55, "workflow"),
        ("Duplicate styled object", "복제 {target}", 0.50, "workflow"),
        ("Screenshot result", "스크린샷", 0.45, "workflow"),
    ],
    # After delete
    "delete": [
        ("Undo / recreate", "큐브 이름 {target}", 0.50, "workflow"),
        ("Save scene", "씬 저장", 0.60, "workflow"),
    ],
}

# Keywords that map a command string to a workflow pattern key
_COMMAND_CLASSIFIERS: list[tuple[str, list[str]]] = [
    ("floor",      ["바닥", "floor"]),
    ("screenshot", ["스크린샷", "screenshot", "캡처", "capture"]),
    ("delete",     ["삭제", "지워", "제거", "delete", "remove"]),
    ("material",   ["색", "색상", "color", "material", "머티리얼"]),
    ("equipment",  ["탱크", "tank", "설비", "equipment", "실린더", "cylinder"]),
    ("create",     ["큐브", "cube", "구", "sphere", "캡슐", "capsule", "박스", "box",
                    "create", "생성", "만들", "조명", "light", "벽", "wall"]),
]


# ── Built-in workflow templates (Korean) ────────────────────────────────────

BUILTIN_TEMPLATES: list[WorkflowTemplate] = [
    WorkflowTemplate(
        name="설비 배치 표준",
        steps=[
            WorkflowStep(
                prompt="설비 이름을 입력하세요",
                param_type="text",
                options=["Tank_A", "Tank_B", "Reactor_01", "Fermenter_01"],
            ),
            WorkflowStep(
                prompt="설비 위치를 입력하세요 (x, y, z)",
                param_type="position",
            ),
            WorkflowStep(
                prompt="재질을 선택하세요",
                param_type="material",
                options=["stainless", "steel", "concrete", "copper"],
            ),
        ],
        plan_template={
            "project": "My project",
            "scene": "bio-plants",
            "description": "설비 배치 표준 워크플로우",
            "actions": [
                {"type": "create_primitive", "shape": "Cylinder",
                 "name": "{step_0}", "position": "{step_1}"},
                {"type": "apply_material", "target": "{step_0}",
                 "color": "{step_2}"},
            ],
        },
    ),
    WorkflowTemplate(
        name="센서 추가",
        steps=[
            WorkflowStep(
                prompt="센서 종류를 선택하세요",
                param_type="text",
                options=["Temperature", "pH", "DO", "Pressure", "Level"],
            ),
            WorkflowStep(
                prompt="부착할 설비 이름을 입력하세요",
                param_type="text",
            ),
            WorkflowStep(
                prompt="센서 위치 오프셋 (x, y, z)",
                param_type="position",
            ),
        ],
        plan_template={
            "project": "My project",
            "scene": "bio-plants",
            "description": "센서 추가 워크플로우",
            "actions": [
                {"type": "create_primitive", "shape": "Sphere",
                 "name": "Sensor_{step_0}", "parent": "{step_1}",
                 "position": "{step_2}",
                 "scale": {"x": 0.15, "y": 0.15, "z": 0.15}},
                {"type": "apply_material", "target": "Sensor_{step_0}",
                 "color": {"r": 0.2, "g": 0.6, "b": 0.9, "a": 1.0}},
            ],
        },
    ),
    WorkflowTemplate(
        name="배관 연결",
        steps=[
            WorkflowStep(
                prompt="시작 설비 이름을 입력하세요",
                param_type="text",
            ),
            WorkflowStep(
                prompt="끝 설비 이름을 입력하세요",
                param_type="text",
            ),
            WorkflowStep(
                prompt="배관 지름 (미터 단위)",
                param_type="number",
                options=["0.05", "0.1", "0.15", "0.2"],
            ),
        ],
        plan_template={
            "project": "My project",
            "scene": "bio-plants",
            "description": "배관 연결 워크플로우",
            "actions": [
                {"type": "create_primitive", "shape": "Capsule",
                 "name": "Pipe_{step_0}_to_{step_1}",
                 "position": {"x": 0, "y": 1, "z": 0},
                 "scale": {"x": "{step_2}", "y": 1, "z": "{step_2}"}},
                {"type": "apply_material",
                 "target": "Pipe_{step_0}_to_{step_1}",
                 "color": {"r": 0.75, "g": 0.75, "b": 0.78, "a": 1.0}},
            ],
        },
    ),
]


# ── Helper functions ────────────────────────────────────────────────────────

def _classify_command(command: str) -> str:
    """Classify a command string into a workflow pattern key."""
    cmd_lower = command.lower()
    for pattern_key, keywords in _COMMAND_CLASSIFIERS:
        for kw in keywords:
            if kw in cmd_lower:
                return pattern_key
    return "create"  # default fallback


def _extract_target(command: str) -> Optional[str]:
    """Try to extract the object target name from a command string."""
    import re
    # Match common patterns: "이름 TargetName", "name:TargetName", object name after action
    patterns = [
        r"이름[을를]?\s*([\w가-힣]+)",
        r"name[:\s]+([\w]+)",
        r"(?:삭제|지워|제거|delete|remove)\s+(?:해줘\s+)?([\w가-힣]+)",
        r"(?:복제|복사|duplicate|copy)\s+(?:해줘\s+)?([\w가-힣]+)",
        r"(?:이동|옮기|move)\s+(?:해줘\s+)?([\w가-힣]+)",
        r"([\w가-힣]+)\s*(?:을|를|의)?\s*(?:색|색상|color)",
    ]
    for pattern in patterns:
        match = re.search(pattern, command, re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Clamp a value to [lo, hi]."""
    return max(lo, min(hi, value))


# ── Main engine ─────────────────────────────────────────────────────────────

class SuggestionEngine:
    """Predictive action suggestion engine (singleton).

    Analyzes command history sequences, workflow patterns, and digital twin
    state to suggest the most likely next actions for the user.
    """

    _instance: Optional["SuggestionEngine"] = None
    _lock = threading.Lock()

    MAX_SUGGESTIONS = 5

    def __new__(cls) -> "SuggestionEngine":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._history_patterns: dict[str, dict[str, int]] = {}
        self._workflow_templates: list[WorkflowTemplate] = list(BUILTIN_TEMPLATES)
        logger.info("SuggestionEngine initialized (singleton)")

    # ── History learning ────────────────────────────────────────────────

    def record_command(self, command: str) -> None:
        """Record a command to build transition frequency data.

        Tracks how often pattern_key_A is followed by pattern_key_B to
        improve suggestion confidence over time.
        """
        cmd_class = _classify_command(command)
        # This is called externally after every command execution.
        # The actual transition tracking is done in get_suggestions
        # by examining the provided history list.
        logger.debug("Recorded command class: %s", cmd_class)

    def _build_transition_counts(self, history: list[str]) -> dict[str, dict[str, int]]:
        """Build transition frequency counts from a command history list."""
        transitions: dict[str, dict[str, int]] = {}
        for i in range(len(history) - 1):
            src = _classify_command(history[i])
            dst = _classify_command(history[i + 1])
            if src not in transitions:
                transitions[src] = {}
            transitions[src][dst] = transitions[src].get(dst, 0) + 1
        return transitions

    # ── Core suggestion logic ───────────────────────────────────────────

    def get_suggestions(
        self,
        last_command: str,
        history: Optional[list[str]] = None,
        scene_context: Optional[dict[str, Any]] = None,
    ) -> list[Suggestion]:
        """Generate next-action suggestions based on context.

        Args:
            last_command: The most recently executed command string.
            history: Full command history list (oldest first).
            scene_context: Optional dict describing current scene objects.

        Returns:
            Up to MAX_SUGGESTIONS Suggestion objects sorted by confidence descending.
        """
        if history is None:
            history = []

        suggestions: list[Suggestion] = []
        cmd_class = _classify_command(last_command)
        target = _extract_target(last_command)

        # Resolve target from scene_context if not extracted from command
        # NEVER use literal "Object" as fallback — it doesn't exist in Unity
        if not target and scene_context:
            objects = scene_context.get("objects", {})
            if isinstance(objects, dict):
                # Pick a relevant scene object (skip system objects)
                skip = {"Main Camera", "Directional Light", "EventSystem"}
                candidates = [n for n in objects if n not in skip]
                if candidates:
                    target = candidates[-1]  # Most recently added object

        logger.debug(
            "Generating suggestions: cmd_class=%s, target=%s, history_len=%d",
            cmd_class, target or "(none)", len(history),
        )

        # 1. Workflow-pattern-based suggestions
        pattern_suggestions = WORKFLOW_PATTERNS.get(cmd_class, [])
        for label, cmd_template, base_conf, category in pattern_suggestions:
            if "{target}" in cmd_template:
                # Skip target-specific suggestions if we have no valid target
                if not target:
                    continue
                command_str = cmd_template.replace("{target}", target)
            else:
                command_str = cmd_template
            suggestions.append(Suggestion(
                label=label,
                command=command_str,
                confidence=_clamp(base_conf),
                category=category,
            ))

        # 2. History-based confidence boost
        if len(history) >= 2:
            transitions = self._build_transition_counts(history)
            src_transitions = transitions.get(cmd_class, {})
            total = sum(src_transitions.values()) if src_transitions else 0
            if total > 0:
                for suggestion in suggestions:
                    suggestion_class = _classify_command(suggestion.command)
                    freq = src_transitions.get(suggestion_class, 0)
                    # Boost confidence by up to 0.15 based on historical frequency
                    history_boost = 0.15 * (freq / total)
                    suggestion.confidence = _clamp(suggestion.confidence + history_boost)
                    if history_boost > 0:
                        suggestion.category = "history"
                        logger.debug(
                            "History boost +%.3f for '%s' (freq=%d/%d)",
                            history_boost, suggestion.label, freq, total,
                        )

        # 3. Scene-context-aware adjustments
        if scene_context:
            object_count = scene_context.get("object_count", 0)
            has_lights = scene_context.get("has_lights", False)
            has_floor = scene_context.get("has_floor", False)

            # If no floor yet, boost floor creation
            if not has_floor and cmd_class != "floor":
                suggestions.append(Suggestion(
                    label="Create floor first",
                    command="10 x 10 바닥",
                    confidence=0.70,
                    category="workflow",
                ))

            # If no lights and objects exist, suggest adding lights
            if not has_lights and object_count > 0:
                suggestions.append(Suggestion(
                    label="Add lighting",
                    command="조명 4개 높이 5m",
                    confidence=0.65,
                    category="workflow",
                ))

            # If many objects, suggest save
            if object_count > 10:
                suggestions.append(Suggestion(
                    label="Save your work",
                    command="씬 저장",
                    confidence=0.50,
                    category="workflow",
                ))

        # Sort by confidence descending and limit
        suggestions.sort(key=lambda s: s.confidence, reverse=True)

        # Deduplicate by command string (keep highest confidence)
        seen_commands: set[str] = set()
        unique: list[Suggestion] = []
        for s in suggestions:
            if s.command not in seen_commands:
                seen_commands.add(s.command)
                unique.append(s)

        result = unique[: self.MAX_SUGGESTIONS]
        logger.info(
            "Generated %d suggestions for '%s' (class=%s)",
            len(result), last_command[:50], cmd_class,
        )
        return result

    # ── Digital twin suggestions ────────────────────────────────────────

    def get_twin_suggestions(self, state: dict[str, Any]) -> list[Suggestion]:
        """Generate suggestions based on fermentation digital twin state.

        Inspects vessel parameters (pH, volume, temperature) and suggests
        corresponding visual updates in the Unity scene.

        Args:
            state: Fermentation simulation state dict with structure:
                   {"vessels": {"KF-7KL": {"ph": 5.2, "volume": 6500,
                    "max_volume": 7000, "temperature": 46.0}, ...}}

        Returns:
            Up to MAX_SUGGESTIONS Suggestion objects for twin-related actions.
        """
        suggestions: list[Suggestion] = []
        vessels = state.get("vessels", {})

        if not vessels:
            logger.debug("No vessel data in twin state, skipping twin suggestions")
            return suggestions

        for vessel_id, vessel_state in vessels.items():
            obj_name = vessel_id  # Will be resolved by fermentation bridge mapping

            # pH < 5.5 -> suggest red color change (critical alert)
            ph = vessel_state.get("ph")
            if ph is not None and ph < 5.5:
                color = PH_COLORS["critical_low"]
                suggestions.append(Suggestion(
                    label=f"pH alert: {vessel_id} pH={ph:.1f} - apply red warning",
                    command=f"{obj_name} 색상 red 변경",
                    confidence=_clamp(0.95 - (ph / 10.0)),  # lower pH = higher confidence
                    category="twin",
                ))

            # Volume > 90% capacity -> suggest fill level update
            volume = vessel_state.get("volume")
            max_volume = vessel_state.get("max_volume")
            if volume is not None and max_volume and max_volume > 0:
                fill_pct = volume / max_volume
                if fill_pct > 0.90:
                    suggestions.append(Suggestion(
                        label=f"Volume alert: {vessel_id} at {fill_pct:.0%} - update fill level",
                        command=f"스케일 {obj_name}_Level 을 (1, {fill_pct:.2f}, 1)",
                        confidence=_clamp(0.70 + (fill_pct - 0.90) * 3.0),
                        category="twin",
                    ))

            # Temperature > 45 -> suggest cooling highlight
            temp = vessel_state.get("temperature")
            if temp is not None and temp > 45.0:
                color = TEMP_COLORS["hot"]
                suggestions.append(Suggestion(
                    label=f"Temp alert: {vessel_id} T={temp:.1f}C - highlight overheating",
                    command=f"{obj_name} 색상 red 변경",
                    confidence=_clamp(0.75 + (temp - 45.0) * 0.02),
                    category="twin",
                ))

        # Sort by confidence descending and limit
        suggestions.sort(key=lambda s: s.confidence, reverse=True)
        result = suggestions[: self.MAX_SUGGESTIONS]
        logger.info("Generated %d twin suggestions from %d vessels", len(result), len(vessels))
        return result

    # ── Workflow template management ────────────────────────────────────

    def get_workflow_templates(self) -> list[WorkflowTemplate]:
        """Return all available workflow templates."""
        return list(self._workflow_templates)

    def get_template_by_name(self, name: str) -> Optional[WorkflowTemplate]:
        """Look up a workflow template by name."""
        for template in self._workflow_templates:
            if template.name == name:
                return template
        return None

    def register_template(self, template: WorkflowTemplate) -> None:
        """Register a new workflow template.

        If a template with the same name already exists, it is replaced.
        """
        for i, existing in enumerate(self._workflow_templates):
            if existing.name == template.name:
                self._workflow_templates[i] = template
                logger.info("Replaced workflow template: %s", template.name)
                return
        self._workflow_templates.append(template)
        logger.info("Registered new workflow template: %s", template.name)
