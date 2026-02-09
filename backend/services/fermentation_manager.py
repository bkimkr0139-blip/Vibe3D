"""Fermentation simulation lifecycle manager.

Singleton manager that creates, runs, and manages fermentation simulations.
"""

import uuid
from datetime import datetime, timezone

from backend.api.models.fermentation_schemas import FermentationStatus, FermentationMode
from fermentation.core.orchestrator import (
    FermentationOrchestrator,
    FermentationMode as OrchestratorMode,
)


class FermentationManager:
    """Singleton manager for fermentation simulations."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._simulations = {}
        return cls._instance

    async def create_simulation(
        self,
        mode: FermentationMode = FermentationMode.SINGLE_7KL,
        realtime_factor: float = 1.0,
        media_type: str = "glucose_minimal",
    ) -> dict:
        """Create and start a new fermentation simulation."""
        sim_id = uuid.uuid4()

        # Map API mode to orchestrator mode
        orch_mode = OrchestratorMode(mode.value)
        orchestrator = FermentationOrchestrator(
            mode=orch_mode,
            dt=1.0,
            realtime_factor=realtime_factor,
        )
        orchestrator.start()

        sim = {
            "id": sim_id,
            "status": FermentationStatus.RUNNING,
            "mode": mode,
            "realtime_factor": realtime_factor,
            "media_type": media_type,
            "created_at": datetime.now(timezone.utc),
            "simulation_time": 0.0,
            "orchestrator": orchestrator,
        }
        self._simulations[sim_id] = sim
        return {
            "id": sim_id,
            "status": FermentationStatus.RUNNING,
            "mode": mode,
            "created_at": sim["created_at"],
        }

    async def get_state(self, simulation_id: uuid.UUID) -> dict | None:
        """Get the current state of a fermentation simulation."""
        sim = self._simulations.get(simulation_id)
        if sim is None:
            return None

        orchestrator: FermentationOrchestrator = sim["orchestrator"]

        # Advance simulation by one step
        if sim["status"] == FermentationStatus.RUNNING:
            orchestrator.run(1.0)  # advance 1 second

        state = orchestrator.current_state
        return {
            "simulation_id": simulation_id,
            "status": sim["status"].value,
            "simulation_time": state.get("simulation_time", 0),
            "mode": sim["mode"].value,
            "fermentors": state.get("fermentors", {}),
            "sensors": state.get("sensors", {}),
            "dosing": state.get("dosing", {}),
            "feed_tanks": state.get("feed_tanks", {}),
            "broth_tank": state.get("broth_tank"),
        }

    async def apply_control(
        self,
        simulation_id: uuid.UUID,
        vessel_name: str,
        controls: dict,
    ) -> bool:
        """Apply control inputs to a vessel in a simulation."""
        sim = self._simulations.get(simulation_id)
        if sim is None:
            return False

        orchestrator: FermentationOrchestrator = sim["orchestrator"]
        orchestrator.apply_control(vessel_name, controls)
        return True

    async def stop_simulation(self, simulation_id: uuid.UUID) -> bool:
        """Stop a running fermentation simulation."""
        sim = self._simulations.get(simulation_id)
        if sim is None:
            return False
        sim["orchestrator"].stop()
        sim["status"] = FermentationStatus.STOPPED
        return True

    @property
    def active_count(self) -> int:
        return sum(
            1 for s in self._simulations.values()
            if s["status"] == FermentationStatus.RUNNING
        )
