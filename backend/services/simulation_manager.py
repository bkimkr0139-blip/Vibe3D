"""Simulation lifecycle manager.

Handles creation, execution, and cleanup of plant simulations.
Uses asyncio background tasks to run physics engines at the configured real-time factor.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from backend.api.models.schemas import SimulationStatus, PlantType
from backend.core.config import settings
from simulation.physics.anaerobic_digester import AnaerobicDigester
from simulation.physics.biogas_engine import BiogasEngine
from simulation.physics.biomass_boiler import BiomassBoiler
from simulation.physics.steam_cycle import SteamTurbine
from simulation.physics.feedstock import FEEDSTOCK_DB

logger = logging.getLogger(__name__)

# Physics time step (seconds)
PHYSICS_DT = 1.0


class SimulationInstance:
    """A single running simulation with its physics engines."""

    def __init__(
        self,
        sim_id: uuid.UUID,
        plant_type: PlantType,
        realtime_factor: float = 1.0,
        feedstock_type: str = "mixed_waste",
        scenario_id: str | None = None,
    ):
        self.id = sim_id
        self.plant_type = plant_type
        self.realtime_factor = realtime_factor
        self.feedstock_type = feedstock_type
        self.scenario_id = scenario_id
        self.status = SimulationStatus.PENDING
        self.created_at = datetime.now(timezone.utc)
        self.simulation_time = 0.0
        self._task: asyncio.Task | None = None

        # Initialize physics engines based on plant type
        self.digester: AnaerobicDigester | None = None
        self.engine: BiogasEngine | None = None
        self.boiler: BiomassBoiler | None = None
        self.turbine: SteamTurbine | None = None

        # Control setpoints
        self.engine_load = 80.0  # % default load
        self.boiler_load = 80.0  # % default load
        self.feed_rate: float | None = None  # m3/h, None = auto

        self._init_engines()

    def _init_engines(self):
        if self.plant_type in (PlantType.BIOGAS_ENGINE, PlantType.COMBINED):
            feedstock = FEEDSTOCK_DB.get(self.feedstock_type, FEEDSTOCK_DB["mixed_waste"])
            self.digester = AnaerobicDigester({
                "feed_vs_concentration": feedstock.get("total_solids", 0.15) * feedstock.get("volatile_solids_ratio", 0.82) * 1000,
            })
            self.engine = BiogasEngine()

        if self.plant_type in (PlantType.BIOMASS_BOILER, PlantType.COMBINED):
            self.boiler = BiomassBoiler()
            self.turbine = SteamTurbine()

    def step(self, dt: float):
        """Advance all physics engines by dt seconds."""
        # Digester + Engine chain
        if self.digester:
            self.digester.step(dt, feed_rate=self.feed_rate)

        if self.engine and self.digester:
            ch4 = self.digester.get_state().get("methane_content", 60.0)
            self.engine.step(dt, load_setpoint=self.engine_load, biogas_ch4=ch4)

        # Boiler + Turbine chain
        if self.boiler:
            self.boiler.step(dt, load_setpoint=self.boiler_load)

        if self.turbine and self.boiler:
            bs = self.boiler.get_state()
            self.turbine.step(
                dt,
                inlet_steam_flow=bs["steam_flow"],
                inlet_pressure=bs["steam_pressure"],
                inlet_temp=bs["steam_temperature"],
            )

        self.simulation_time += dt

    def get_state(self) -> dict[str, Any]:
        """Collect state from all engines."""
        state: dict[str, Any] = {
            "simulation_id": str(self.id),
            "status": self.status.value,
            "simulation_time": round(self.simulation_time, 2),
        }

        # Digester state
        if self.digester:
            ds = self.digester.get_state()
            state["digester"] = ds

        # Engine state
        if self.engine:
            es = self.engine.get_state()
            state["engine"] = es

        # Boiler state
        if self.boiler:
            bs = self.boiler.get_state()
            state["boiler"] = bs

        # Plant overview
        total_power = 0.0
        total_thermal = 0.0
        if self.engine:
            es = self.engine.get_state()
            total_power += es.get("power_output", 0.0)
            total_thermal += es.get("thermal_output", 0.0)
        if self.turbine:
            ts = self.turbine.get_state()
            total_power += ts.get("power_output", 0.0)

        state["plant"] = {
            "total_power_output": round(total_power, 1),
            "total_thermal_output": round(total_thermal, 1),
            "overall_efficiency": round(
                (total_power + total_thermal) / max(total_power * 2.5, 1.0) * 100, 1
            ),
            "co2_emissions": 0.0,
            "nox_emissions": 0.0,
        }

        return state

    async def run_loop(self):
        """Main simulation loop — runs as an asyncio background task."""
        self.status = SimulationStatus.RUNNING
        logger.info("Simulation %s started (plant=%s, rt_factor=%.1f)",
                     self.id, self.plant_type.value, self.realtime_factor)
        try:
            while self.status == SimulationStatus.RUNNING:
                self.step(PHYSICS_DT)
                # Sleep to maintain real-time factor
                await asyncio.sleep(PHYSICS_DT / self.realtime_factor)
        except asyncio.CancelledError:
            logger.info("Simulation %s cancelled", self.id)
        except Exception as e:
            logger.exception("Simulation %s failed: %s", self.id, e)
            self.status = SimulationStatus.FAILED
        finally:
            if self.status == SimulationStatus.RUNNING:
                self.status = SimulationStatus.STOPPED


class SimulationManager:
    """Singleton manager for all active simulations."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._simulations: dict[uuid.UUID, SimulationInstance] = {}
        return cls._instance

    async def create_simulation(
        self,
        plant_type: PlantType,
        realtime_factor: float = 1.0,
        feedstock_type: str = "mixed_waste",
        scenario_id: str | None = None,
    ) -> SimulationInstance:
        """Create and start a new simulation instance."""
        if self.active_count >= settings.MAX_CONCURRENT_SIMULATIONS:
            raise RuntimeError(
                f"Max concurrent simulations ({settings.MAX_CONCURRENT_SIMULATIONS}) reached"
            )

        realtime_factor = min(realtime_factor, settings.MAX_REALTIME_FACTOR)
        sim_id = uuid.uuid4()
        sim = SimulationInstance(
            sim_id=sim_id,
            plant_type=plant_type,
            realtime_factor=realtime_factor,
            feedstock_type=feedstock_type,
            scenario_id=scenario_id,
        )
        self._simulations[sim_id] = sim

        # Start background task
        sim.status = SimulationStatus.RUNNING
        sim._task = asyncio.create_task(sim.run_loop())
        return sim

    async def get_state(self, simulation_id: uuid.UUID) -> dict | None:
        """Get current state of a simulation."""
        sim = self._simulations.get(simulation_id)
        if sim is None:
            return None
        return sim.get_state()

    async def pause_simulation(self, simulation_id: uuid.UUID) -> bool:
        """Pause a running simulation."""
        sim = self._simulations.get(simulation_id)
        if sim is None or sim.status != SimulationStatus.RUNNING:
            return False
        sim.status = SimulationStatus.PAUSED
        if sim._task:
            sim._task.cancel()
            try:
                await sim._task
            except asyncio.CancelledError:
                pass
        return True

    async def resume_simulation(self, simulation_id: uuid.UUID) -> bool:
        """Resume a paused simulation."""
        sim = self._simulations.get(simulation_id)
        if sim is None or sim.status != SimulationStatus.PAUSED:
            return False
        sim._task = asyncio.create_task(sim.run_loop())
        return True

    async def stop_simulation(self, simulation_id: uuid.UUID) -> bool:
        """Stop a running simulation and clean up resources."""
        sim = self._simulations.get(simulation_id)
        if sim is None:
            return False
        sim.status = SimulationStatus.STOPPED
        if sim._task:
            sim._task.cancel()
            try:
                await sim._task
            except asyncio.CancelledError:
                pass
        return True

    def get_simulation(self, simulation_id: uuid.UUID) -> SimulationInstance | None:
        return self._simulations.get(simulation_id)

    @property
    def active_count(self) -> int:
        return sum(
            1 for s in self._simulations.values()
            if s.status == SimulationStatus.RUNNING
        )

    @property
    def all_simulations(self) -> list[dict]:
        return [
            {
                "id": str(s.id),
                "status": s.status.value,
                "plant_type": s.plant_type.value,
                "simulation_time": round(s.simulation_time, 2),
                "created_at": s.created_at.isoformat(),
            }
            for s in self._simulations.values()
        ]
