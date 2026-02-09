"""Vibe3D Component Library — Industrial Equipment Template System.

Provides parameterized templates for common industrial equipment
(vessels, valves, pumps, heat exchangers, probes, pipes, PRV, etc.)
that can be instantiated into Unity MCP action plans.
"""

import math
import logging
from typing import Optional

logger = logging.getLogger("vibe3d.components")

# ── JIS Pipe Sizes → Unity radius ────────────────────────────────

PIPE_SIZES = {
    "8A": 0.007, "10A": 0.009, "15A": 0.012,
    "20A": 0.015, "25A": 0.018, "40A": 0.025,
    "50A": 0.032, "65A": 0.040, "80A": 0.045,
    "100A": 0.057,
}

# ── Medium colors ────────────────────────────────────────────────

MEDIUM_COLORS = {
    "steam": {"r": 1.0, "g": 0.3, "b": 0.3, "a": 1.0},
    "cws": {"r": 0.25, "g": 0.41, "b": 0.88, "a": 1.0},
    "air": {"r": 1.0, "g": 0.84, "b": 0.0, "a": 1.0},
    "drain": {"r": 0.4, "g": 0.25, "b": 0.15, "a": 1.0},
    "seed": {"r": 0.2, "g": 0.7, "b": 0.2, "a": 1.0},
    "feed": {"r": 0.3, "g": 0.5, "b": 1.0, "a": 1.0},
    "broth": {"r": 0.6, "g": 0.4, "b": 0.2, "a": 1.0},
    "exhaust": {"r": 0.6, "g": 0.6, "b": 0.6, "a": 1.0},
    "nitrogen": {"r": 0.5, "g": 0.5, "b": 0.9, "a": 1.0},
    "water": {"r": 0.2, "g": 0.5, "b": 0.9, "a": 1.0},
}

# ── Probe/sensor colors ─────────────────────────────────────────

PROBE_COLORS = {
    "pH": {"r": 1.0, "g": 1.0, "b": 0.0, "a": 1.0},
    "DO": {"r": 0.0, "g": 0.8, "b": 0.0, "a": 1.0},
    "Level": {"r": 0.0, "g": 0.5, "b": 1.0, "a": 1.0},
    "Temp": {"r": 1.0, "g": 0.4, "b": 0.0, "a": 1.0},
    "Pressure": {"r": 0.8, "g": 0.0, "b": 0.0, "a": 1.0},
}

# ── Standard colors ─────────────────────────────────────────────

STAINLESS = {"r": 0.82, "g": 0.82, "b": 0.82, "a": 1.0}
DARK_STEEL = {"r": 0.5, "g": 0.5, "b": 0.5, "a": 1.0}
FLANGE_GRAY = {"r": 0.65, "g": 0.65, "b": 0.65, "a": 1.0}


# ── Component Templates ─────────────────────────────────────────

COMPONENT_TEMPLATES = {
    "vessel_fermenter": {
        "label": "발효조 (Fermenter)",
        "category": "Vessel",
        "icon": "cylinder",
        "description": "산업 표준 발효 용기 — 본체 + 접시형 헤드 + 플랜지 + 맨홀 + 사이트글라스",
        "params": {
            "name": {"label": "이름", "type": "text", "default": "KF-Tank"},
            "diameter": {"label": "직경 (m)", "type": "number", "default": 1.0, "min": 0.2, "max": 5.0},
            "height": {"label": "높이 (m)", "type": "number", "default": 1.5, "min": 0.5, "max": 8.0},
            "x": {"label": "X 위치", "type": "number", "default": 0},
            "y": {"label": "Y 위치", "type": "number", "default": 0},
            "z": {"label": "Z 위치", "type": "number", "default": 0},
            "has_jacket": {"label": "재킷 여부", "type": "bool", "default": False},
            "has_agitator": {"label": "교반기 여부", "type": "bool", "default": True},
        },
    },
    "vessel_feed_tank": {
        "label": "피드 탱크 (Feed Tank)",
        "category": "Vessel",
        "icon": "cylinder",
        "description": "원료 저장 탱크 — 본체 + 헤드 + 플랜지",
        "params": {
            "name": {"label": "이름", "type": "text", "default": "FeedTank"},
            "diameter": {"label": "직경 (m)", "type": "number", "default": 0.5, "min": 0.1, "max": 3.0},
            "height": {"label": "높이 (m)", "type": "number", "default": 0.8, "min": 0.3, "max": 4.0},
            "x": {"label": "X 위치", "type": "number", "default": 0},
            "y": {"label": "Y 위치", "type": "number", "default": 0},
            "z": {"label": "Z 위치", "type": "number", "default": 0},
        },
    },
    "valve_manual": {
        "label": "수동 밸브 (Ball/Gate)",
        "category": "Equipment",
        "icon": "valve",
        "description": "수동 볼밸브/게이트밸브 — 본체 + 스템 + 핸드휠 + 플랜지",
        "params": {
            "name": {"label": "이름", "type": "text", "default": "Valve"},
            "x": {"label": "X 위치", "type": "number", "default": 0},
            "y": {"label": "Y 위치", "type": "number", "default": 0},
            "z": {"label": "Z 위치", "type": "number", "default": 0},
            "medium": {"label": "매체", "type": "select", "default": "steam",
                       "options": list(MEDIUM_COLORS.keys())},
            "pipe_size": {"label": "파이프 사이즈", "type": "select", "default": "15A",
                         "options": list(PIPE_SIZES.keys())},
        },
    },
    "pump_centrifugal": {
        "label": "원심 펌프 (Centrifugal)",
        "category": "Equipment",
        "icon": "pump",
        "description": "원심 펌프 — 케이싱 + 모터 + 커플링 + 베이스",
        "params": {
            "name": {"label": "이름", "type": "text", "default": "Pump"},
            "x": {"label": "X 위치", "type": "number", "default": 0},
            "y": {"label": "Y 위치", "type": "number", "default": 0},
            "z": {"label": "Z 위치", "type": "number", "default": 0},
        },
    },
    "hx_shell_tube": {
        "label": "열교환기 Shell & Tube",
        "category": "Equipment",
        "icon": "hx",
        "description": "쉘앤튜브 열교환기 — 쉘 + 튜브시트 + 노즐 + 새들",
        "params": {
            "name": {"label": "이름", "type": "text", "default": "HX"},
            "x": {"label": "X 위치", "type": "number", "default": 0},
            "y": {"label": "Y 위치", "type": "number", "default": 0},
            "z": {"label": "Z 위치", "type": "number", "default": 0},
            "length": {"label": "길이 (m)", "type": "number", "default": 0.6, "min": 0.2, "max": 3.0},
        },
    },
    "prv_safety": {
        "label": "안전 릴리프 밸브 (PRV)",
        "category": "Equipment",
        "icon": "prv",
        "description": "압력 안전 밸브 — 본체 + 보넷 + 스프링캡 + 플랜지",
        "params": {
            "name": {"label": "이름", "type": "text", "default": "PRV"},
            "x": {"label": "X 위치", "type": "number", "default": 0},
            "y": {"label": "Y 위치", "type": "number", "default": 0},
            "z": {"label": "Z 위치", "type": "number", "default": 0},
        },
    },
    "probe_sensor": {
        "label": "프로브/센서",
        "category": "Instrument",
        "icon": "probe",
        "description": "pH/DO/Level/Temp/Pressure 센서",
        "params": {
            "name": {"label": "이름", "type": "text", "default": "Probe"},
            "sensor_type": {"label": "센서 유형", "type": "select", "default": "pH",
                           "options": list(PROBE_COLORS.keys())},
            "x": {"label": "X 위치", "type": "number", "default": 0},
            "y": {"label": "Y 위치", "type": "number", "default": 0},
            "z": {"label": "Z 위치", "type": "number", "default": 0},
        },
    },
    "pipe_run": {
        "label": "파이프 런 (Pipe Run)",
        "category": "Piping",
        "icon": "pipe",
        "description": "수평 파이프 + 엘보",
        "params": {
            "name": {"label": "이름", "type": "text", "default": "Pipe"},
            "medium": {"label": "매체", "type": "select", "default": "cws",
                       "options": list(MEDIUM_COLORS.keys())},
            "pipe_size": {"label": "사이즈", "type": "select", "default": "20A",
                         "options": list(PIPE_SIZES.keys())},
            "start_x": {"label": "시작 X", "type": "number", "default": 0},
            "start_y": {"label": "시작 Y", "type": "number", "default": 2},
            "start_z": {"label": "시작 Z", "type": "number", "default": 0},
            "end_x": {"label": "끝 X", "type": "number", "default": 3},
            "end_y": {"label": "끝 Y", "type": "number", "default": 2},
            "end_z": {"label": "끝 Z", "type": "number", "default": 0},
        },
    },
    "steam_trap": {
        "label": "스팀 트랩",
        "category": "Equipment",
        "icon": "trap",
        "description": "스팀 트랩 — 본체 + 입구/출구 연결",
        "params": {
            "name": {"label": "이름", "type": "text", "default": "SteamTrap"},
            "x": {"label": "X 위치", "type": "number", "default": 0},
            "y": {"label": "Y 위치", "type": "number", "default": 0},
            "z": {"label": "Z 위치", "type": "number", "default": 0},
        },
    },
}


class ComponentLibrary:
    """Industrial component template library."""

    def get_categories(self) -> list[dict]:
        """Get component categories with their templates."""
        categories = {}
        for tid, tpl in COMPONENT_TEMPLATES.items():
            cat = tpl["category"]
            if cat not in categories:
                categories[cat] = {
                    "name": cat,
                    "label": self._category_label(cat),
                    "icon": self._category_icon(cat),
                    "templates": [],
                }
            categories[cat]["templates"].append({
                "id": tid,
                "name": tpl["label"],
                "icon": tpl.get("icon", "cube"),
                "description": tpl["description"],
                "params": tpl["params"],
            })
        return list(categories.values())

    def get_template(self, template_id: str) -> Optional[dict]:
        """Get a specific template by ID."""
        tpl = COMPONENT_TEMPLATES.get(template_id)
        if not tpl:
            return None
        return {
            "id": template_id,
            "label": tpl["label"],
            "category": tpl["category"],
            "icon": tpl.get("icon", "cube"),
            "description": tpl["description"],
            "params": tpl["params"],
        }

    def instantiate(self, template_id: str, params: dict) -> Optional[dict]:
        """Generate an action plan from a template with given parameters.

        Args:
            template_id: Template identifier
            params: Parameter values

        Returns:
            Plan dict with actions, or None if template not found
        """
        tpl = COMPONENT_TEMPLATES.get(template_id)
        if not tpl:
            return None

        # Apply default values for missing params
        resolved = {}
        for key, spec in tpl["params"].items():
            if key in params:
                val = params[key]
                if spec["type"] == "number":
                    val = float(val) if val != "" else spec["default"]
                elif spec["type"] == "bool":
                    val = val if isinstance(val, bool) else str(val).lower() in ("true", "1", "yes")
                resolved[key] = val
            else:
                resolved[key] = spec["default"]

        # Dispatch to builder
        builders = {
            "vessel_fermenter": self._build_fermenter,
            "vessel_feed_tank": self._build_feed_tank,
            "valve_manual": self._build_valve,
            "pump_centrifugal": self._build_pump,
            "hx_shell_tube": self._build_hx,
            "prv_safety": self._build_prv,
            "probe_sensor": self._build_probe,
            "pipe_run": self._build_pipe_run,
            "steam_trap": self._build_steam_trap,
        }

        builder = builders.get(template_id)
        if not builder:
            return None

        actions = builder(resolved)
        return {
            "actions": actions,
            "plan_description": f"{tpl['label']}: {resolved.get('name', template_id)}",
        }

    # ── Builders ─────────────────────────────────────────────────

    def _build_fermenter(self, p: dict) -> list:
        name = p["name"]
        d = float(p["diameter"])
        h = float(p["height"])
        x, y, z = float(p["x"]), float(p["y"]), float(p["z"])
        parent = "BioFacility/Vessels"

        actions = [
            # Body
            {"type": "create_primitive", "name": name, "shape": "Cylinder",
             "position": {"x": x, "y": y + h / 2, "z": z},
             "scale": {"x": d, "y": h / 2, "z": d},
             "parent": parent, "color": STAINLESS},
            # Top head
            {"type": "create_primitive", "name": f"DishHead_Top_{name}", "shape": "Sphere",
             "position": {"x": 0, "y": h / 2, "z": 0},
             "scale": {"x": d, "y": d * 0.3, "z": d},
             "parent": f"{parent}/{name}", "color": STAINLESS},
            # Bottom head
            {"type": "create_primitive", "name": f"DishHead_Bot_{name}", "shape": "Sphere",
             "position": {"x": 0, "y": -h / 2, "z": 0},
             "scale": {"x": d, "y": d * 0.3, "z": d},
             "parent": f"{parent}/{name}", "color": STAINLESS},
            # Top flange
            {"type": "create_primitive", "name": f"Flange_Top_{name}", "shape": "Cylinder",
             "position": {"x": 0, "y": h / 2 + d * 0.1, "z": 0},
             "scale": {"x": d * 1.15, "y": 0.02, "z": d * 1.15},
             "parent": f"{parent}/{name}", "color": FLANGE_GRAY},
            # Manhole
            {"type": "create_primitive", "name": f"Manway_{name}", "shape": "Cylinder",
             "position": {"x": d / 2 + 0.01, "y": h / 4, "z": 0},
             "scale": {"x": 0.1, "y": 0.05, "z": 0.1},
             "rotation": {"x": 0, "y": 0, "z": 90},
             "parent": f"{parent}/{name}", "color": DARK_STEEL},
            # Sight glass
            {"type": "create_primitive", "name": f"SightGlass_{name}", "shape": "Cylinder",
             "position": {"x": d / 2 + 0.01, "y": 0, "z": 0},
             "scale": {"x": 0.05, "y": 0.08, "z": 0.05},
             "rotation": {"x": 0, "y": 0, "z": 90},
             "parent": f"{parent}/{name}",
             "color": {"r": 0.4, "g": 0.6, "b": 0.8, "a": 0.7}},
        ]

        # Jacket
        if p.get("has_jacket"):
            actions.append({
                "type": "create_primitive", "name": f"Jacket_{name}", "shape": "Cylinder",
                "position": {"x": 0, "y": 0, "z": 0},
                "scale": {"x": d * 1.1, "y": h * 0.4, "z": d * 1.1},
                "parent": f"{parent}/{name}",
                "color": {"r": 0.75, "g": 0.75, "b": 0.8, "a": 1.0},
            })

        # Skirt (for larger vessels)
        if d >= 1.0:
            skirt_h = 0.3
            actions.append({
                "type": "create_primitive", "name": f"Skirt_{name}", "shape": "Cylinder",
                "position": {"x": 0, "y": -h / 2 - skirt_h / 2, "z": 0},
                "scale": {"x": d * 0.95, "y": skirt_h / 2, "z": d * 0.95},
                "parent": f"{parent}/{name}", "color": DARK_STEEL,
            })

        # Agitator
        if p.get("has_agitator"):
            actions.extend([
                {"type": "create_primitive", "name": f"Shaft_{name}", "shape": "Cylinder",
                 "position": {"x": 0, "y": h / 4, "z": 0},
                 "scale": {"x": 0.02, "y": h * 0.6, "z": 0.02},
                 "parent": f"{parent}/{name}", "color": DARK_STEEL},
                {"type": "create_primitive", "name": f"Impeller_{name}", "shape": "Cylinder",
                 "position": {"x": 0, "y": -h / 6, "z": 0},
                 "scale": {"x": d * 0.35, "y": 0.01, "z": d * 0.35},
                 "parent": f"{parent}/{name}", "color": DARK_STEEL},
            ])

        return actions

    def _build_feed_tank(self, p: dict) -> list:
        name = p["name"]
        d = float(p["diameter"])
        h = float(p["height"])
        x, y, z = float(p["x"]), float(p["y"]), float(p["z"])
        parent = "BioFacility/Vessels"

        return [
            {"type": "create_primitive", "name": name, "shape": "Cylinder",
             "position": {"x": x, "y": y + h / 2, "z": z},
             "scale": {"x": d, "y": h / 2, "z": d},
             "parent": parent, "color": STAINLESS},
            {"type": "create_primitive", "name": f"Top_{name}", "shape": "Sphere",
             "position": {"x": 0, "y": h / 2, "z": 0},
             "scale": {"x": d, "y": d * 0.25, "z": d},
             "parent": f"{parent}/{name}", "color": STAINLESS},
            {"type": "create_primitive", "name": f"Bot_{name}", "shape": "Sphere",
             "position": {"x": 0, "y": -h / 2, "z": 0},
             "scale": {"x": d, "y": d * 0.25, "z": d},
             "parent": f"{parent}/{name}", "color": STAINLESS},
        ]

    def _build_valve(self, p: dict) -> list:
        name = p["name"]
        x, y, z = float(p["x"]), float(p["y"]), float(p["z"])
        medium = p.get("medium", "steam")
        color = MEDIUM_COLORS.get(medium, MEDIUM_COLORS["steam"])
        parent = "BioFacility/Piping"

        return [
            {"type": "create_primitive", "name": name, "shape": "Cube",
             "position": {"x": x, "y": y, "z": z},
             "scale": {"x": 0.06, "y": 0.04, "z": 0.06},
             "parent": parent, "color": color},
            {"type": "create_primitive", "name": f"Stem_{name}", "shape": "Cylinder",
             "position": {"x": 0, "y": 0.06, "z": 0},
             "scale": {"x": 0.008, "y": 0.03, "z": 0.008},
             "parent": f"{parent}/{name}", "color": DARK_STEEL},
            {"type": "create_primitive", "name": f"HW_{name}", "shape": "Sphere",
             "position": {"x": 0, "y": 0.1, "z": 0},
             "scale": {"x": 0.04, "y": 0.01, "z": 0.04},
             "parent": f"{parent}/{name}", "color": color},
            {"type": "create_primitive", "name": f"FL1_{name}", "shape": "Cylinder",
             "position": {"x": -0.04, "y": 0, "z": 0},
             "scale": {"x": 0.035, "y": 0.005, "z": 0.035},
             "rotation": {"x": 0, "y": 0, "z": 90},
             "parent": f"{parent}/{name}", "color": FLANGE_GRAY},
            {"type": "create_primitive", "name": f"FL2_{name}", "shape": "Cylinder",
             "position": {"x": 0.04, "y": 0, "z": 0},
             "scale": {"x": 0.035, "y": 0.005, "z": 0.035},
             "rotation": {"x": 0, "y": 0, "z": 90},
             "parent": f"{parent}/{name}", "color": FLANGE_GRAY},
        ]

    def _build_pump(self, p: dict) -> list:
        name = p["name"]
        x, y, z = float(p["x"]), float(p["y"]), float(p["z"])
        parent = "BioFacility/Utilities"

        return [
            {"type": "create_primitive", "name": name, "shape": "Cylinder",
             "position": {"x": x, "y": y, "z": z},
             "scale": {"x": 0.08, "y": 0.05, "z": 0.08},
             "parent": parent, "color": {"r": 0.2, "g": 0.5, "b": 0.8, "a": 1.0}},
            {"type": "create_primitive", "name": f"Motor_{name}", "shape": "Cylinder",
             "position": {"x": -0.15, "y": 0, "z": 0},
             "scale": {"x": 0.06, "y": 0.08, "z": 0.06},
             "rotation": {"x": 0, "y": 0, "z": 90},
             "parent": f"{parent}/{name}",
             "color": {"r": 0.2, "g": 0.6, "b": 0.2, "a": 1.0}},
            {"type": "create_primitive", "name": f"Coupling_{name}", "shape": "Cylinder",
             "position": {"x": -0.07, "y": 0, "z": 0},
             "scale": {"x": 0.03, "y": 0.02, "z": 0.03},
             "rotation": {"x": 0, "y": 0, "z": 90},
             "parent": f"{parent}/{name}", "color": DARK_STEEL},
            {"type": "create_primitive", "name": f"Base_{name}", "shape": "Cube",
             "position": {"x": -0.08, "y": -0.06, "z": 0},
             "scale": {"x": 0.35, "y": 0.02, "z": 0.15},
             "parent": f"{parent}/{name}",
             "color": {"r": 0.35, "g": 0.35, "b": 0.35, "a": 1.0}},
        ]

    def _build_hx(self, p: dict) -> list:
        name = p["name"]
        x, y, z = float(p["x"]), float(p["y"]), float(p["z"])
        length = float(p.get("length", 0.6))
        parent = "BioFacility/Utilities"

        return [
            {"type": "create_primitive", "name": name, "shape": "Cylinder",
             "position": {"x": x, "y": y, "z": z},
             "scale": {"x": 0.08, "y": length / 2, "z": 0.08},
             "rotation": {"x": 0, "y": 0, "z": 90},
             "parent": parent, "color": STAINLESS},
            {"type": "create_primitive", "name": f"TSheet_F_{name}", "shape": "Cylinder",
             "position": {"x": -length / 2, "y": 0, "z": 0},
             "scale": {"x": 0.09, "y": 0.008, "z": 0.09},
             "rotation": {"x": 0, "y": 0, "z": 90},
             "parent": f"{parent}/{name}", "color": FLANGE_GRAY},
            {"type": "create_primitive", "name": f"TSheet_R_{name}", "shape": "Cylinder",
             "position": {"x": length / 2, "y": 0, "z": 0},
             "scale": {"x": 0.09, "y": 0.008, "z": 0.09},
             "rotation": {"x": 0, "y": 0, "z": 90},
             "parent": f"{parent}/{name}", "color": FLANGE_GRAY},
            {"type": "create_primitive", "name": f"Noz_In_{name}", "shape": "Cylinder",
             "position": {"x": -length / 4, "y": 0.09, "z": 0},
             "scale": {"x": 0.02, "y": 0.03, "z": 0.02},
             "parent": f"{parent}/{name}", "color": DARK_STEEL},
            {"type": "create_primitive", "name": f"Noz_Out_{name}", "shape": "Cylinder",
             "position": {"x": length / 4, "y": 0.09, "z": 0},
             "scale": {"x": 0.02, "y": 0.03, "z": 0.02},
             "parent": f"{parent}/{name}", "color": DARK_STEEL},
            {"type": "create_primitive", "name": f"Saddle_F_{name}", "shape": "Cube",
             "position": {"x": -length / 3, "y": -0.07, "z": 0},
             "scale": {"x": 0.02, "y": 0.04, "z": 0.12},
             "parent": f"{parent}/{name}", "color": DARK_STEEL},
            {"type": "create_primitive", "name": f"Saddle_R_{name}", "shape": "Cube",
             "position": {"x": length / 3, "y": -0.07, "z": 0},
             "scale": {"x": 0.02, "y": 0.04, "z": 0.12},
             "parent": f"{parent}/{name}", "color": DARK_STEEL},
        ]

    def _build_prv(self, p: dict) -> list:
        name = p["name"]
        x, y, z = float(p["x"]), float(p["y"]), float(p["z"])
        parent = "BioFacility/Piping"

        return [
            {"type": "create_primitive", "name": name, "shape": "Cylinder",
             "position": {"x": x, "y": y, "z": z},
             "scale": {"x": 0.03, "y": 0.03, "z": 0.03},
             "parent": parent, "color": {"r": 0.8, "g": 0.0, "b": 0.0, "a": 1.0}},
            {"type": "create_primitive", "name": f"Bonnet_{name}", "shape": "Cylinder",
             "position": {"x": 0, "y": 0.05, "z": 0},
             "scale": {"x": 0.025, "y": 0.02, "z": 0.025},
             "parent": f"{parent}/{name}",
             "color": {"r": 1.0, "g": 0.0, "b": 0.0, "a": 1.0}},
            {"type": "create_primitive", "name": f"SpringCap_{name}", "shape": "Cylinder",
             "position": {"x": 0, "y": 0.09, "z": 0},
             "scale": {"x": 0.02, "y": 0.015, "z": 0.02},
             "parent": f"{parent}/{name}",
             "color": {"r": 0.9, "g": 0.0, "b": 0.0, "a": 1.0}},
            {"type": "create_primitive", "name": f"Flange_{name}", "shape": "Cylinder",
             "position": {"x": 0, "y": -0.03, "z": 0},
             "scale": {"x": 0.04, "y": 0.005, "z": 0.04},
             "parent": f"{parent}/{name}", "color": FLANGE_GRAY},
        ]

    def _build_probe(self, p: dict) -> list:
        name = p["name"]
        sensor_type = p.get("sensor_type", "pH")
        x, y, z = float(p["x"]), float(p["y"]), float(p["z"])
        color = PROBE_COLORS.get(sensor_type, PROBE_COLORS["pH"])
        parent = "BioFacility/Vessels"

        return [
            {"type": "create_primitive", "name": name, "shape": "Cylinder",
             "position": {"x": x, "y": y, "z": z},
             "scale": {"x": 0.015, "y": 0.06, "z": 0.015},
             "parent": parent, "color": color},
            {"type": "create_primitive", "name": f"Head_{name}", "shape": "Sphere",
             "position": {"x": 0, "y": 0.07, "z": 0},
             "scale": {"x": 0.02, "y": 0.02, "z": 0.02},
             "parent": f"{parent}/{name}", "color": color},
        ]

    def _build_pipe_run(self, p: dict) -> list:
        name = p["name"]
        medium = p.get("medium", "cws")
        pipe_size = p.get("pipe_size", "20A")
        color = MEDIUM_COLORS.get(medium, MEDIUM_COLORS["cws"])
        radius = PIPE_SIZES.get(pipe_size, 0.015)
        parent = "BioFacility/Piping"

        sx, sy, sz = float(p["start_x"]), float(p["start_y"]), float(p["start_z"])
        ex, ey, ez = float(p["end_x"]), float(p["end_y"]), float(p["end_z"])

        # Calculate midpoint and length for horizontal run
        mx = (sx + ex) / 2
        my = (sy + ey) / 2
        mz = (sz + ez) / 2
        length = math.sqrt((ex - sx) ** 2 + (ey - sy) ** 2 + (ez - sz) ** 2)

        # Simple horizontal pipe
        actions = [
            {"type": "create_primitive", "name": f"{name}_Run", "shape": "Cylinder",
             "position": {"x": mx, "y": my, "z": mz},
             "scale": {"x": radius, "y": length / 2, "z": radius},
             "rotation": {"x": 0, "y": 0, "z": 90},
             "parent": parent, "color": color},
        ]

        # Start elbow
        actions.append({
            "type": "create_primitive", "name": f"{name}_Elbow_S", "shape": "Sphere",
            "position": {"x": sx, "y": sy, "z": sz},
            "scale": {"x": radius * 2.5, "y": radius * 2.5, "z": radius * 2.5},
            "parent": parent, "color": color,
        })

        # End elbow
        actions.append({
            "type": "create_primitive", "name": f"{name}_Elbow_E", "shape": "Sphere",
            "position": {"x": ex, "y": ey, "z": ez},
            "scale": {"x": radius * 2.5, "y": radius * 2.5, "z": radius * 2.5},
            "parent": parent, "color": color,
        })

        return actions

    def _build_steam_trap(self, p: dict) -> list:
        name = p["name"]
        x, y, z = float(p["x"]), float(p["y"]), float(p["z"])
        parent = "BioFacility/Piping"

        return [
            {"type": "create_primitive", "name": name, "shape": "Cube",
             "position": {"x": x, "y": y, "z": z},
             "scale": {"x": 0.06, "y": 0.04, "z": 0.04},
             "parent": parent, "color": DARK_STEEL},
            {"type": "create_primitive", "name": f"In_{name}", "shape": "Cylinder",
             "position": {"x": -0.05, "y": 0, "z": 0},
             "scale": {"x": 0.015, "y": 0.02, "z": 0.015},
             "rotation": {"x": 0, "y": 0, "z": 90},
             "parent": f"{parent}/{name}", "color": DARK_STEEL},
            {"type": "create_primitive", "name": f"Out_{name}", "shape": "Cylinder",
             "position": {"x": 0.05, "y": 0, "z": 0},
             "scale": {"x": 0.015, "y": 0.02, "z": 0.015},
             "rotation": {"x": 0, "y": 0, "z": 90},
             "parent": f"{parent}/{name}", "color": DARK_STEEL},
        ]

    # ── Utility ──────────────────────────────────────────────────

    def _category_label(self, cat: str) -> str:
        labels = {
            "Vessel": "용기/탱크",
            "Equipment": "장비",
            "Instrument": "계측기기",
            "Piping": "배관",
        }
        return labels.get(cat, cat)

    def _category_icon(self, cat: str) -> str:
        icons = {
            "Vessel": "cylinder",
            "Equipment": "gear",
            "Instrument": "gauge",
            "Piping": "pipe",
        }
        return icons.get(cat, "cube")
