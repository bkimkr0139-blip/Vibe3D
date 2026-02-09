"""Workflow template manager for Vibe3D Unity Accelerator.

Manages parameterized workflow templates that can be saved, loaded,
and executed. Templates define reusable step sequences (e.g., place
equipment, add sensors, create piping) with parameter placeholders
that are filled in at execution time.
"""

import copy
import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Base directory for vibe3d
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
WORKFLOWS_FILE = DATA_DIR / "workflows.json"


# ── Data Models ────────────────────────────────────────────────


@dataclass
class WorkflowStep:
    """A single parameterized step in a workflow template."""

    prompt: str
    param_name: str
    param_type: str  # "text" | "position" | "material" | "number" | "select"
    options: Optional[list[str]] = None
    default_value: str = ""


@dataclass
class WorkflowTemplate:
    """A reusable workflow template with parameterized steps."""

    id: str
    name: str
    description: str
    steps: list[WorkflowStep]
    plan_template: dict
    created_at: str = ""


# ── Helper: fill plan template ─────────────────────────────────


def fill_plan_template(plan_template: dict, params: dict) -> dict:
    """Replace {param_name} placeholders in a plan template with actual values.

    Handles nested dicts and lists recursively. String values containing
    ``{param_name}`` patterns are substituted with the corresponding value
    from *params*.

    Args:
        plan_template: The plan template dict (not mutated).
        params: Mapping of parameter names to their values.

    Returns:
        A new dict with all placeholders resolved.
    """
    return _fill_value(copy.deepcopy(plan_template), params)


def _fill_value(value: Any, params: dict) -> Any:
    """Recursively replace placeholders in *value*."""
    if isinstance(value, str):
        # Full-match replacement: if the entire string is a placeholder,
        # replace with the raw param value (preserves non-string types).
        for pname, pval in params.items():
            if value == f"{{{pname}}}":
                return pval
        # Partial replacement: substitute all occurrences inside the string.
        for pname, pval in params.items():
            value = value.replace(f"{{{pname}}}", str(pval))
        return value

    if isinstance(value, dict):
        return {k: _fill_value(v, params) for k, v in value.items()}

    if isinstance(value, list):
        return [_fill_value(item, params) for item in value]

    return value


# ── Built-in Templates ─────────────────────────────────────────


def _builtin_templates() -> list[WorkflowTemplate]:
    """Return the four default workflow templates."""

    # 1. Equipment Placement (설비 배치)
    equip_placement = WorkflowTemplate(
        id=str(uuid.uuid4()),
        name="설비 배치",
        description="장비를 지정 위치에 배치하고 재질을 적용합니다.",
        steps=[
            WorkflowStep(
                prompt="장비 이름을 입력하세요",
                param_name="name",
                param_type="text",
                default_value="Equipment_0",
            ),
            WorkflowStep(
                prompt="배치 위치 (x, y, z)",
                param_name="position",
                param_type="position",
                default_value="0,0,0",
            ),
            WorkflowStep(
                prompt="재질을 선택하세요",
                param_name="material",
                param_type="select",
                options=["stainless", "steel", "copper", "concrete"],
                default_value="stainless",
            ),
        ],
        plan_template={
            "project": "My project",
            "scene": "bio-plants",
            "description": "설비 배치: {name}",
            "actions": [
                {
                    "type": "create_primitive",
                    "shape": "Cylinder",
                    "name": "{name}",
                    "position": "{position}",
                    "scale": {"x": 1, "y": 2, "z": 1},
                },
                {
                    "type": "apply_material",
                    "target": "{name}",
                    "color": "{material}",
                },
            ],
        },
        created_at=datetime.now(timezone.utc).isoformat(),
    )

    # 2. Add Sensor (센서 추가)
    add_sensor = WorkflowTemplate(
        id=str(uuid.uuid4()),
        name="센서 추가",
        description="장비 근처에 센서 마커를 생성합니다.",
        steps=[
            WorkflowStep(
                prompt="센서 이름을 입력하세요",
                param_name="sensor_name",
                param_type="text",
                default_value="Sensor_0",
            ),
            WorkflowStep(
                prompt="대상 장비 이름",
                param_name="target_equipment",
                param_type="text",
                default_value="Equipment_0",
            ),
            WorkflowStep(
                prompt="센서 유형을 선택하세요",
                param_name="sensor_type",
                param_type="select",
                options=["pH", "DO", "Temp", "Pressure"],
                default_value="pH",
            ),
        ],
        plan_template={
            "project": "My project",
            "scene": "bio-plants",
            "description": "센서 추가: {sensor_name} ({sensor_type}) -> {target_equipment}",
            "actions": [
                {
                    "type": "create_empty",
                    "name": "{sensor_name}",
                    "parent": "{target_equipment}",
                    "position": {"x": 0, "y": 0, "z": 0},
                },
                {
                    "type": "modify_object",
                    "target": "{sensor_name}",
                    "search_method": "by_name",
                    "position": {"x": 0.5, "y": 1.0, "z": 0},
                },
            ],
        },
        created_at=datetime.now(timezone.utc).isoformat(),
    )

    # 3. Create Piping (배관 생성)
    create_piping = WorkflowTemplate(
        id=str(uuid.uuid4()),
        name="배관 생성",
        description="두 장비 사이에 배관을 생성합니다.",
        steps=[
            WorkflowStep(
                prompt="출발 장비 이름",
                param_name="from_equipment",
                param_type="text",
                default_value="Equipment_A",
            ),
            WorkflowStep(
                prompt="도착 장비 이름",
                param_name="to_equipment",
                param_type="text",
                default_value="Equipment_B",
            ),
            WorkflowStep(
                prompt="배관 직경 (m)",
                param_name="pipe_diameter",
                param_type="number",
                default_value="0.1",
            ),
            WorkflowStep(
                prompt="배관 색상을 선택하세요",
                param_name="color",
                param_type="select",
                options=["biogas_yellow", "steam_white", "cooling_blue"],
                default_value="steam_white",
            ),
        ],
        plan_template={
            "project": "My project",
            "scene": "bio-plants",
            "description": "배관 생성: {from_equipment} -> {to_equipment}",
            "actions": [
                {
                    "type": "create_primitive",
                    "shape": "Cylinder",
                    "name": "Pipe_{from_equipment}_to_{to_equipment}",
                    "position": {"x": 0, "y": 1, "z": 0},
                    "rotation": {"x": 0, "y": 0, "z": 90},
                    "scale": {"x": "{pipe_diameter}", "y": 1, "z": "{pipe_diameter}"},
                },
                {
                    "type": "apply_material",
                    "target": "Pipe_{from_equipment}_to_{to_equipment}",
                    "color": "{color}",
                },
            ],
        },
        created_at=datetime.now(timezone.utc).isoformat(),
    )

    # 4. Fermentation Vessel Full Build (발효설비 풀 빌드)
    full_build = WorkflowTemplate(
        id=str(uuid.uuid4()),
        name="발효설비 풀 빌드",
        description="발효 용기, 공급 라인, 센서 마커를 한 번에 생성합니다.",
        steps=[
            WorkflowStep(
                prompt="용기 유형을 선택하세요",
                param_name="vessel_type",
                param_type="select",
                options=["70L", "700L", "7KL"],
                default_value="700L",
            ),
            WorkflowStep(
                prompt="배치 위치 (x, y, z)",
                param_name="position",
                param_type="position",
                default_value="0,0,0",
            ),
        ],
        plan_template={
            "project": "My project",
            "scene": "bio-plants",
            "description": "발효설비 풀 빌드: Fermentor_{vessel_type}",
            "actions": [
                {
                    "type": "create_primitive",
                    "shape": "Cylinder",
                    "name": "Fermentor_{vessel_type}",
                    "position": "{position}",
                    "scale": {"x": 1, "y": 2, "z": 1},
                },
                {
                    "type": "create_primitive",
                    "shape": "Cylinder",
                    "name": "FeedLine_{vessel_type}",
                    "parent": "Fermentor_{vessel_type}",
                    "position": {"x": -0.6, "y": 1.5, "z": 0},
                    "rotation": {"x": 0, "y": 0, "z": 45},
                    "scale": {"x": 0.05, "y": 0.5, "z": 0.05},
                },
                {
                    "type": "create_empty",
                    "name": "Sensor_pH_{vessel_type}",
                    "parent": "Fermentor_{vessel_type}",
                    "position": {"x": 0.5, "y": 1.0, "z": 0},
                },
                {
                    "type": "create_empty",
                    "name": "Sensor_DO_{vessel_type}",
                    "parent": "Fermentor_{vessel_type}",
                    "position": {"x": 0.5, "y": 0.5, "z": 0},
                },
                {
                    "type": "create_empty",
                    "name": "Sensor_Temp_{vessel_type}",
                    "parent": "Fermentor_{vessel_type}",
                    "position": {"x": -0.5, "y": 0.8, "z": 0},
                },
            ],
        },
        created_at=datetime.now(timezone.utc).isoformat(),
    )

    return [equip_placement, add_sensor, create_piping, full_build]


# ── WorkflowManager (Singleton) ───────────────────────────────


class WorkflowManager:
    """Singleton manager for workflow templates.

    Stores templates in a JSON file at ``vibe3d/data/workflows.json``.
    On first initialisation (when the file does not exist) the four
    built-in templates are written automatically.
    """

    _instance: Optional["WorkflowManager"] = None

    def __new__(cls) -> "WorkflowManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialised = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialised:
            return
        self._initialised = True
        self._templates: dict[str, WorkflowTemplate] = {}
        self._ensure_data_dir()
        self._load()

    # ── Persistence helpers ────────────────────────────────────

    @staticmethod
    def _ensure_data_dir() -> None:
        """Create the data directory if it does not exist."""
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        logger.debug("Data directory ensured: %s", DATA_DIR)

    def _load(self) -> None:
        """Load templates from disk, or seed with built-ins."""
        if not WORKFLOWS_FILE.exists():
            logger.info("Workflows file not found — seeding built-in templates")
            for tpl in _builtin_templates():
                self._templates[tpl.id] = tpl
            self._save()
            return

        try:
            with open(WORKFLOWS_FILE, "r", encoding="utf-8") as fh:
                data = json.load(fh)

            for entry in data:
                steps = [WorkflowStep(**s) for s in entry.pop("steps", [])]
                tpl = WorkflowTemplate(**entry, steps=steps)
                self._templates[tpl.id] = tpl

            logger.info("Loaded %d workflow templates from %s", len(self._templates), WORKFLOWS_FILE)
        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            logger.error("Failed to parse workflows file (%s) — re-seeding: %s", WORKFLOWS_FILE, exc)
            self._templates.clear()
            for tpl in _builtin_templates():
                self._templates[tpl.id] = tpl
            self._save()

    def _save(self) -> None:
        """Persist all templates to disk."""
        data = [asdict(tpl) for tpl in self._templates.values()]
        self._ensure_data_dir()
        with open(WORKFLOWS_FILE, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        logger.debug("Saved %d workflow templates to %s", len(data), WORKFLOWS_FILE)

    # ── CRUD ───────────────────────────────────────────────────

    def create(
        self,
        name: str,
        description: str,
        steps: list[WorkflowStep],
        plan_template: dict,
    ) -> WorkflowTemplate:
        """Create a new workflow template and persist it.

        Args:
            name: Human-readable template name.
            description: Short description of what the template does.
            steps: Ordered list of parameterized steps.
            plan_template: Unity action plan with ``{param}`` placeholders.

        Returns:
            The newly created ``WorkflowTemplate``.
        """
        tpl = WorkflowTemplate(
            id=str(uuid.uuid4()),
            name=name,
            description=description,
            steps=steps,
            plan_template=plan_template,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self._templates[tpl.id] = tpl
        self._save()
        logger.info("Created workflow template '%s' (id=%s)", name, tpl.id)
        return tpl

    def get(self, workflow_id: str) -> Optional[WorkflowTemplate]:
        """Return a single template by ID, or ``None``."""
        return self._templates.get(workflow_id)

    def list_all(self) -> list[WorkflowTemplate]:
        """Return all stored templates."""
        return list(self._templates.values())

    def update(self, workflow_id: str, **kwargs: Any) -> Optional[WorkflowTemplate]:
        """Update fields on an existing template.

        Supported keyword arguments correspond to ``WorkflowTemplate``
        attributes (``name``, ``description``, ``steps``, ``plan_template``).

        Returns:
            The updated template, or ``None`` if *workflow_id* was not found.
        """
        tpl = self._templates.get(workflow_id)
        if tpl is None:
            logger.warning("Cannot update — workflow '%s' not found", workflow_id)
            return None

        for key, value in kwargs.items():
            if hasattr(tpl, key) and key not in ("id", "created_at"):
                setattr(tpl, key, value)

        self._save()
        logger.info("Updated workflow template '%s' (id=%s)", tpl.name, tpl.id)
        return tpl

    def delete(self, workflow_id: str) -> bool:
        """Delete a template by ID.

        Returns:
            ``True`` if deleted, ``False`` if the ID was not found.
        """
        if workflow_id not in self._templates:
            logger.warning("Cannot delete — workflow '%s' not found", workflow_id)
            return False

        name = self._templates[workflow_id].name
        del self._templates[workflow_id]
        self._save()
        logger.info("Deleted workflow template '%s' (id=%s)", name, workflow_id)
        return True

    # ── Execution ──────────────────────────────────────────────

    def execute(self, workflow_id: str, params: dict) -> dict:
        """Fill a template's plan with the given parameters and return the plan.

        Args:
            workflow_id: ID of the workflow template to execute.
            params: Mapping of parameter names to their concrete values.

        Returns:
            A fully resolved Unity action plan ``dict``.

        Raises:
            ValueError: If the workflow ID is not found.
        """
        tpl = self._templates.get(workflow_id)
        if tpl is None:
            raise ValueError(f"Workflow template '{workflow_id}' not found")

        plan = fill_plan_template(tpl.plan_template, params)
        logger.info(
            "Executed workflow '%s' with params %s — %d actions",
            tpl.name,
            list(params.keys()),
            len(plan.get("actions", [])),
        )
        return plan
