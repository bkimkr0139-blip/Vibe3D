"""Base scenario class for fermentation simulations."""

from enum import Enum
from typing import Any


class ScenarioPhase(str, Enum):
    IDLE = "idle"
    SETUP = "setup"
    INOCULATION = "inoculation"
    GROWTH = "growth"
    ANOMALY = "anomaly"
    DETECTION = "detection"
    CORRECTION = "correction"
    RECOVERY = "recovery"
    COMPLETED = "completed"


class BaseScenario:
    """
    Abstract base for fermentation scenarios.

    Subclasses implement `evaluate()` which is called each simulation step
    to drive scenario phase transitions and inject events.
    """

    name: str = "base"
    description: str = "Base scenario"

    def __init__(self):
        self.phase = ScenarioPhase.IDLE
        self.phase_start_time = 0.0
        self.events: list[dict] = []
        self._time = 0.0

    @property
    def is_complete(self) -> bool:
        return self.phase == ScenarioPhase.COMPLETED

    def phase_elapsed(self) -> float:
        """Seconds elapsed in current phase."""
        return self._time - self.phase_start_time

    def transition(self, new_phase: ScenarioPhase, message: str = ""):
        """Transition to a new scenario phase."""
        old = self.phase
        self.phase = new_phase
        self.phase_start_time = self._time
        event = {
            "time": self._time,
            "from_phase": old.value,
            "to_phase": new_phase.value,
            "message": message,
        }
        self.events.append(event)

    def evaluate(self, state: dict, dt: float) -> dict[str, Any]:
        """
        Called each simulation step.

        Args:
            state: current orchestrator state dict
            dt: time step in seconds

        Returns:
            dict with optional keys:
              "controls": {vessel_name: {control_key: value}}
              "alerts": [AnomalyAlert-like dicts]
              "inject_fault": {vessel: {sensor: fault_spec}}
        """
        self._time += dt
        return {}

    def get_state(self) -> dict:
        return {
            "name": self.name,
            "phase": self.phase.value,
            "phase_elapsed_s": round(self.phase_elapsed(), 2),
            "time": round(self._time, 2),
            "events": self.events[-10:],  # last 10 events
            "is_complete": self.is_complete,
        }
