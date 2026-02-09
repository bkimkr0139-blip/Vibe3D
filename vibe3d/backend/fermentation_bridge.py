"""Fermentation ↔ Unity bridge.

Connects the fermentation simulation to Unity 3D visualization via MCP.
Maps simulation state to visual properties (color, scale, text) on Unity objects.
"""

import asyncio
import logging
from typing import Any

from ..mcp_client.client import UnityMCPClient

logger = logging.getLogger(__name__)

# Color mapping for fermentation state visualization
PH_COLORS = {
    "critical_low":  {"r": 0.9, "g": 0.1, "b": 0.1, "a": 1.0},   # pH < 5.5 — red
    "low":           {"r": 0.9, "g": 0.5, "b": 0.1, "a": 1.0},   # pH 5.5-6.5 — orange
    "normal":        {"r": 0.15, "g": 0.65, "b": 0.15, "a": 1.0}, # pH 6.5-7.5 — green
    "high":          {"r": 0.9, "g": 0.5, "b": 0.1, "a": 1.0},   # pH 7.5-8.5 — orange
    "critical_high": {"r": 0.9, "g": 0.1, "b": 0.1, "a": 1.0},   # pH > 8.5 — red
}

DO_COLORS = {
    "critical_low":  {"r": 0.9, "g": 0.1, "b": 0.1, "a": 1.0},   # DO < 1 mg/L
    "low":           {"r": 0.9, "g": 0.7, "b": 0.1, "a": 1.0},   # DO 1-2 mg/L
    "normal":        {"r": 0.2, "g": 0.6, "b": 0.9, "a": 1.0},   # DO 2-6 mg/L — blue
    "high":          {"r": 0.2, "g": 0.9, "b": 0.9, "a": 1.0},   # DO > 6 mg/L
}

TEMP_COLORS = {
    "cold":    {"r": 0.2, "g": 0.4, "b": 0.9, "a": 1.0},   # T < 30°C
    "normal":  {"r": 0.15, "g": 0.65, "b": 0.15, "a": 1.0}, # T 30-40°C — green
    "warm":    {"r": 0.9, "g": 0.5, "b": 0.1, "a": 1.0},    # T 40-45°C
    "hot":     {"r": 0.9, "g": 0.1, "b": 0.1, "a": 1.0},    # T > 45°C
}

# Unity object naming convention for fermentation equipment
VESSEL_OBJECT_MAP = {
    "KF-7KL": "Fermentor_7KL",
    "KF-700L": "Fermentor_700L",
    "KF-70L": "Fermentor_70L",
    "KF-4KL-FD": "FeedTank_4KL",
    "KF-500L-FD": "FeedTank_500L",
    "KF-70L-FD": "FeedTank_70L",
    "KF-7000L": "BrothTank_7KL",
}


def _classify_ph(ph: float) -> str:
    if ph < 5.5:
        return "critical_low"
    if ph < 6.5:
        return "low"
    if ph <= 7.5:
        return "normal"
    if ph <= 8.5:
        return "high"
    return "critical_high"


def _classify_do(do_mg_l: float) -> str:
    if do_mg_l < 1.0:
        return "critical_low"
    if do_mg_l < 2.0:
        return "low"
    if do_mg_l <= 6.0:
        return "normal"
    return "high"


def _classify_temp(temp_c: float) -> str:
    if temp_c < 30.0:
        return "cold"
    if temp_c <= 40.0:
        return "normal"
    if temp_c <= 45.0:
        return "warm"
    return "hot"


class FermentationBridge:
    """Bridges fermentation simulation state to Unity 3D visualization."""

    def __init__(self, mcp_client: UnityMCPClient):
        self.mcp = mcp_client
        self._running = False
        self._task: asyncio.Task | None = None

    async def setup_scene(self):
        """Create Unity objects for fermentation equipment if they don't exist."""
        commands = []
        for vessel_id, obj_name in VESSEL_OBJECT_MAP.items():
            commands.append({
                "toolName": "manage_gameobject",
                "parameters": {
                    "action": "find",
                    "searchPattern": obj_name,
                    "searchType": "by_name",
                },
            })

        # Check which objects already exist
        try:
            result = self.mcp.batch_execute(commands)
            logger.info("Fermentation scene check: %s", result)
        except Exception as e:
            logger.warning("Scene check failed (Unity may not have fermentation objects): %s", e)

    async def update_vessel_visuals(self, state: dict[str, Any]):
        """Update Unity object visuals based on simulation state.

        Args:
            state: The full simulation state dict from FermentationOrchestrator.current_state
        """
        if not state:
            return

        commands = []

        # Process each vessel in the state
        vessels = state.get("vessels", {})
        for vessel_id, vessel_state in vessels.items():
            obj_name = VESSEL_OBJECT_MAP.get(vessel_id)
            if not obj_name:
                continue

            # pH-based color on fermentor body
            ph = vessel_state.get("ph")
            if ph is not None:
                ph_class = _classify_ph(ph)
                color = PH_COLORS.get(ph_class, PH_COLORS["normal"])
                commands.append({
                    "toolName": "manage_material",
                    "parameters": {
                        "action": "set_renderer_color",
                        "objectName": obj_name,
                        "r": color["r"],
                        "g": color["g"],
                        "b": color["b"],
                        "a": color["a"],
                    },
                })

            # Volume → Y-scale on liquid level indicator
            volume = vessel_state.get("volume")
            max_volume = vessel_state.get("max_volume")
            if volume is not None and max_volume and max_volume > 0:
                fill_ratio = min(volume / max_volume, 1.0)
                level_obj = f"{obj_name}_Level"
                commands.append({
                    "toolName": "manage_gameobject",
                    "parameters": {
                        "action": "modify",
                        "objectName": level_obj,
                        "searchType": "by_name",
                        "scaleY": fill_ratio,
                    },
                })

        # Batch send all updates
        if commands:
            try:
                result = self.mcp.batch_execute(commands)
                logger.debug("Fermentation visual update: %d commands sent", len(commands))
                return result
            except Exception as e:
                logger.error("Failed to update fermentation visuals: %s", e)

    async def start_sync_loop(self, get_state_fn, interval: float = 1.0):
        """Start a background loop that syncs simulation state to Unity.

        Args:
            get_state_fn: Callable that returns the current simulation state dict
            interval: Update interval in seconds
        """
        self._running = True
        logger.info("Fermentation bridge sync started (interval=%.1fs)", interval)
        try:
            while self._running:
                state = get_state_fn()
                if state:
                    await self.update_vessel_visuals(state)
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.exception("Fermentation bridge sync error: %s", e)
        finally:
            self._running = False
            logger.info("Fermentation bridge sync stopped")

    def start(self, get_state_fn, interval: float = 1.0):
        """Start sync as a background asyncio task."""
        self._task = asyncio.create_task(
            self.start_sync_loop(get_state_fn, interval)
        )

    def stop(self):
        """Stop the sync loop."""
        self._running = False
        if self._task:
            self._task.cancel()

    def build_status_plan(self, state: dict[str, Any]) -> dict:
        """Generate a Vibe3D action plan from current fermentation state.

        This can be used with the /api/execute endpoint to manually update visuals.
        """
        plan = {
            "project": "My project",
            "scene": "bio-plants",
            "description": "Update fermentation vessel visuals from simulation state",
            "actions": [],
        }

        vessels = state.get("vessels", {})
        for vessel_id, vessel_state in vessels.items():
            obj_name = VESSEL_OBJECT_MAP.get(vessel_id)
            if not obj_name:
                continue

            ph = vessel_state.get("ph")
            if ph is not None:
                ph_class = _classify_ph(ph)
                color = PH_COLORS.get(ph_class, PH_COLORS["normal"])
                plan["actions"].append({
                    "type": "apply_material",
                    "target": obj_name,
                    "color": color,
                })

        return plan

    # ── Extended Digital Twin Visualization ──────────────────

    async def update_flow_visuals(self, state: dict[str, Any]):
        """Update pipe flow indicators based on valve/pump states.

        Creates arrow-like indicators on pipes showing flow direction and rate.
        """
        if not state:
            return

        commands = []
        flows = state.get("flows", {})
        for pipe_id, flow_state in flows.items():
            flow_rate = flow_state.get("flow_rate", 0)
            if flow_rate <= 0:
                continue

            arrow_name = f"{pipe_id}_FlowArrow"
            # Scale arrow speed/size based on flow rate
            scale_factor = min(flow_rate / 10.0, 2.0)  # Normalize

            # Determine flow color by fluid type
            fluid_type = flow_state.get("fluid_type", "media")
            color_map = {
                "media": {"r": 0.55, "g": 0.35, "b": 0.17, "a": 1.0},    # brown
                "alkali": {"r": 0.2, "g": 0.4, "b": 0.9, "a": 1.0},       # blue
                "acid": {"r": 0.9, "g": 0.15, "b": 0.15, "a": 1.0},       # red
                "steam": {"r": 0.95, "g": 0.95, "b": 0.95, "a": 0.7},     # white
                "cooling": {"r": 0.25, "g": 0.5, "b": 0.9, "a": 1.0},     # blue
            }
            color = color_map.get(fluid_type, color_map["media"])

            commands.append({
                "toolName": "manage_material",
                "parameters": {
                    "action": "set_renderer_color",
                    "objectName": arrow_name,
                    "r": color["r"], "g": color["g"],
                    "b": color["b"], "a": color["a"],
                },
            })

        if commands:
            try:
                self.mcp.batch_execute(commands)
            except Exception as e:
                logger.debug("Flow visual update failed: %s", e)

    async def update_sensor_displays(self, state: dict[str, Any]):
        """Update 3D text displays near sensors with current values."""
        if not state:
            return

        commands = []
        sensors = state.get("sensors", {})
        for sensor_id, sensor_state in sensors.items():
            value = sensor_state.get("value")
            unit = sensor_state.get("unit", "")
            alarm = sensor_state.get("alarm", False)

            display_name = f"{sensor_id}_Display"

            # Color based on alarm state
            if alarm:
                color = {"r": 0.9, "g": 0.1, "b": 0.1, "a": 1.0}
            else:
                color = {"r": 0.2, "g": 0.9, "b": 0.2, "a": 1.0}

            commands.append({
                "toolName": "manage_material",
                "parameters": {
                    "action": "set_renderer_color",
                    "objectName": display_name,
                    "r": color["r"], "g": color["g"],
                    "b": color["b"], "a": color["a"],
                },
            })

        if commands:
            try:
                self.mcp.batch_execute(commands)
            except Exception as e:
                logger.debug("Sensor display update failed: %s", e)

    async def update_event_effects(self, events: list[dict[str, Any]]):
        """Apply visual effects for simulation events.

        Event types: ph_anomaly, alkali_dose, recovery, alarm
        """
        if not events:
            return

        commands = []
        for event in events:
            event_type = event.get("type", "")
            vessel_id = event.get("vessel_id", "")
            obj_name = VESSEL_OBJECT_MAP.get(vessel_id)
            if not obj_name:
                continue

            if event_type == "ph_anomaly":
                # Red glow on vessel
                commands.append({
                    "toolName": "manage_material",
                    "parameters": {
                        "action": "set_renderer_color",
                        "objectName": f"{obj_name}_Glow",
                        "r": 0.9, "g": 0.1, "b": 0.1, "a": 0.5,
                    },
                })
            elif event_type == "alkali_dose":
                # Blue highlight on dosing line
                commands.append({
                    "toolName": "manage_material",
                    "parameters": {
                        "action": "set_renderer_color",
                        "objectName": f"{obj_name}_DosingLine",
                        "r": 0.2, "g": 0.4, "b": 0.9, "a": 1.0,
                    },
                })
            elif event_type == "recovery":
                # Green on vessel
                commands.append({
                    "toolName": "manage_material",
                    "parameters": {
                        "action": "set_renderer_color",
                        "objectName": obj_name,
                        "r": 0.15, "g": 0.65, "b": 0.15, "a": 1.0,
                    },
                })

        if commands:
            try:
                self.mcp.batch_execute(commands)
            except Exception as e:
                logger.debug("Event effect update failed: %s", e)

    def build_suggestion_plan(self, state: dict[str, Any]) -> list[dict]:
        """Generate suggestion plans based on current fermentation state.

        Returns list of {label, description, plan} dicts.
        """
        suggestions = []
        vessels = state.get("vessels", {})

        for vessel_id, vessel_state in vessels.items():
            obj_name = VESSEL_OBJECT_MAP.get(vessel_id)
            if not obj_name:
                continue

            # pH critical → suggest color change
            ph = vessel_state.get("ph")
            if ph is not None and ph < 5.5:
                suggestions.append({
                    "label": f"{vessel_id} pH 경고 색상 적용",
                    "description": f"pH {ph:.1f} — 발효조를 빨간색으로 변경",
                    "plan": {
                        "project": "My project",
                        "scene": "bio-plants",
                        "description": f"pH alert color for {vessel_id}",
                        "actions": [{
                            "type": "apply_material",
                            "target": obj_name,
                            "color": PH_COLORS["critical_low"],
                        }],
                    },
                })

            # Volume > 90% → suggest fill level update
            volume = vessel_state.get("volume")
            max_volume = vessel_state.get("max_volume")
            if volume and max_volume and volume / max_volume > 0.9:
                fill = volume / max_volume
                suggestions.append({
                    "label": f"{vessel_id} 액면 경고 ({fill:.0%})",
                    "description": f"볼륨 {volume:.0f}L / {max_volume:.0f}L",
                    "plan": {
                        "project": "My project",
                        "scene": "bio-plants",
                        "description": f"Fill level update for {vessel_id}",
                        "actions": [{
                            "type": "modify_object",
                            "target": f"{obj_name}_Level",
                            "search_method": "by_name",
                            "scale": {"x": 1, "y": fill, "z": 1},
                        }],
                    },
                })

            # Temperature > 45 → suggest cooling highlight
            temp = vessel_state.get("temperature")
            if temp is not None and temp > 45.0:
                suggestions.append({
                    "label": f"{vessel_id} 고온 경고 ({temp:.1f}°C)",
                    "description": "냉각수 배관 파란색 하이라이트",
                    "plan": {
                        "project": "My project",
                        "scene": "bio-plants",
                        "description": f"Cooling highlight for {vessel_id}",
                        "actions": [{
                            "type": "apply_material",
                            "target": f"{obj_name}_CoolingPipe",
                            "color": {"r": 0.25, "g": 0.5, "b": 0.9, "a": 1.0},
                        }],
                    },
                })

        return suggestions

    def get_twin_status(self) -> dict:
        """Get current bridge status."""
        return {
            "running": self._running,
            "vessel_count": len(VESSEL_OBJECT_MAP),
            "vessels": list(VESSEL_OBJECT_MAP.keys()),
        }
