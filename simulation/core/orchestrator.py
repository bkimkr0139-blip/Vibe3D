"""SimPy-based simulation orchestrator.

Coordinates the execution of all physics sub-models at each time step,
handles time acceleration, and manages the simulation lifecycle.
"""

import time
from enum import Enum

import simpy

from simulation.physics.anaerobic_digester import AnaerobicDigester
from simulation.physics.biogas_engine import BiogasEngine
from simulation.physics.biomass_boiler import BiomassBoiler
from simulation.physics.steam_cycle import SteamTurbine


class PlantMode(str, Enum):
    BIOGAS_ENGINE = "biogas_engine"
    BIOMASS_BOILER = "biomass_boiler"
    COMBINED = "combined"


class SimulationOrchestrator:
    """Orchestrates all physics engines in a SimPy environment."""

    def __init__(
        self,
        mode: PlantMode = PlantMode.BIOGAS_ENGINE,
        dt: float = 1.0,
        realtime_factor: float = 1.0,
    ):
        self.mode = mode
        self.dt = dt
        self.realtime_factor = realtime_factor
        self.env = simpy.Environment()
        self._running = False

        # Initialize physics engines based on mode
        self.digester = None
        self.engine = None
        self.boiler = None
        self.steam_turbine = None
        self._state = {}

        if mode in (PlantMode.BIOGAS_ENGINE, PlantMode.COMBINED):
            self.digester = AnaerobicDigester()
            self.engine = BiogasEngine()

        if mode in (PlantMode.BIOMASS_BOILER, PlantMode.COMBINED):
            self.boiler = BiomassBoiler()
            self.steam_turbine = SteamTurbine()

    def _simulation_loop(self, env: simpy.Environment):
        """Main simulation loop process."""
        while self._running:
            wall_start = time.monotonic()

            state = {}

            # 1. Digester produces biogas
            if self.digester:
                digester_state = self.digester.step(self.dt)
                state["digester"] = digester_state

                # 2. Engine consumes biogas
                if self.engine:
                    engine_state = self.engine.step(
                        self.dt,
                        load_setpoint=80.0,  # TODO: from control system
                        biogas_ch4=digester_state["methane_content"],
                    )
                    state["engine"] = engine_state

            # 3. Biomass boiler
            if self.boiler:
                boiler_state = self.boiler.step(
                    self.dt,
                    load_setpoint=80.0,  # TODO: from control system
                )
                state["boiler"] = boiler_state

                # 4. Steam turbine
                if self.steam_turbine and boiler_state["steam_flow"] > 0:
                    st_state = self.steam_turbine.step(
                        self.dt,
                        inlet_steam_flow=boiler_state["steam_flow"],
                        inlet_pressure=boiler_state["steam_pressure"],
                        inlet_temp=boiler_state["steam_temperature"],
                    )
                    state["steam_turbine"] = st_state

            # 5. Plant totals
            total_power = 0.0
            total_thermal = 0.0
            if self.engine and "engine" in state:
                total_power += state["engine"]["power_output"]
                total_thermal += state["engine"]["thermal_output"]
            if self.steam_turbine and "steam_turbine" in state:
                total_power += state["steam_turbine"]["power_output"]

            state["plant"] = {
                "total_power_output": round(total_power, 1),
                "total_thermal_output": round(total_thermal, 1),
                "simulation_time": env.now,
            }

            self._state = state

            # Real-time pacing
            wall_elapsed = time.monotonic() - wall_start
            sim_dt = self.dt / max(self.realtime_factor, 0.1)
            sleep_time = max(sim_dt - wall_elapsed, 0)
            yield env.timeout(self.dt)

    def start(self):
        """Start the simulation."""
        self._running = True
        self.env.process(self._simulation_loop(self.env))

    def stop(self):
        """Stop the simulation."""
        self._running = False

    @property
    def current_state(self) -> dict:
        return self._state
