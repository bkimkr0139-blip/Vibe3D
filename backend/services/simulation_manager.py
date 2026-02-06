"""Simulation lifecycle manager.

Handles creation, execution, and cleanup of plant simulations.
"""

import uuid
from datetime import datetime, timezone
from enum import Enum

from backend.api.models.schemas import SimulationStatus, PlantType


class SimulationManager:
    """Singleton manager for all active simulations."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._simulations = {}
        return cls._instance

    async def create_simulation(
        self,
        plant_type: PlantType,
        realtime_factor: float = 1.0,
        scenario_id: str | None = None,
    ) -> dict:
        """Create and start a new simulation instance."""
        sim_id = uuid.uuid4()
        sim = {
            "id": sim_id,
            "status": SimulationStatus.PENDING,
            "plant_type": plant_type,
            "realtime_factor": realtime_factor,
            "scenario_id": scenario_id,
            "created_at": datetime.now(timezone.utc),
            "simulation_time": 0.0,
        }
        self._simulations[sim_id] = sim
        # TODO: Initialize physics engines based on plant_type
        # TODO: Start SimPy orchestrator
        sim["status"] = SimulationStatus.RUNNING
        return sim

    async def get_state(self, simulation_id: uuid.UUID) -> dict | None:
        """Get current state of a simulation."""
        return self._simulations.get(simulation_id)

    async def stop_simulation(self, simulation_id: uuid.UUID) -> bool:
        """Stop a running simulation and clean up resources."""
        sim = self._simulations.get(simulation_id)
        if sim is None:
            return False
        sim["status"] = SimulationStatus.STOPPED
        # TODO: Clean up physics engines and data recorders
        return True

    @property
    def active_count(self) -> int:
        return sum(
            1 for s in self._simulations.values()
            if s["status"] == SimulationStatus.RUNNING
        )
