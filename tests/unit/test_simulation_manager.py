"""Tests for the simulation manager and routes."""

import asyncio
import pytest

from backend.api.models.schemas import PlantType, SimulationStatus
from backend.services.simulation_manager import SimulationManager, SimulationInstance


class TestSimulationInstance:
    """Test simulation instance with physics engines."""

    def test_biogas_engine_init(self):
        import uuid
        sim = SimulationInstance(
            sim_id=uuid.uuid4(),
            plant_type=PlantType.BIOGAS_ENGINE,
        )
        assert sim.digester is not None
        assert sim.engine is not None
        assert sim.boiler is None
        assert sim.turbine is None
        assert sim.status == SimulationStatus.PENDING

    def test_biomass_boiler_init(self):
        import uuid
        sim = SimulationInstance(
            sim_id=uuid.uuid4(),
            plant_type=PlantType.BIOMASS_BOILER,
        )
        assert sim.digester is None
        assert sim.engine is None
        assert sim.boiler is not None
        assert sim.turbine is not None

    def test_combined_init(self):
        import uuid
        sim = SimulationInstance(
            sim_id=uuid.uuid4(),
            plant_type=PlantType.COMBINED,
        )
        assert sim.digester is not None
        assert sim.engine is not None
        assert sim.boiler is not None
        assert sim.turbine is not None

    def test_step_advances_time(self):
        import uuid
        sim = SimulationInstance(
            sim_id=uuid.uuid4(),
            plant_type=PlantType.BIOGAS_ENGINE,
        )
        assert sim.simulation_time == 0.0
        sim.step(1.0)
        assert sim.simulation_time == 1.0
        sim.step(5.0)
        assert sim.simulation_time == 6.0

    def test_get_state_biogas(self):
        import uuid
        sim = SimulationInstance(
            sim_id=uuid.uuid4(),
            plant_type=PlantType.BIOGAS_ENGINE,
        )
        # Run a few steps to get meaningful state
        for _ in range(10):
            sim.step(1.0)

        state = sim.get_state()
        assert "digester" in state
        assert "engine" in state
        assert "plant" in state
        assert state["simulation_time"] == 10.0

        # Digester state should have expected fields
        ds = state["digester"]
        assert "temperature" in ds
        assert "ph" in ds
        assert "biogas_flow_rate" in ds
        assert "methane_content" in ds

        # Plant overview
        plant = state["plant"]
        assert "total_power_output" in plant
        assert "total_thermal_output" in plant

    def test_get_state_biomass(self):
        import uuid
        sim = SimulationInstance(
            sim_id=uuid.uuid4(),
            plant_type=PlantType.BIOMASS_BOILER,
        )
        for _ in range(10):
            sim.step(1.0)

        state = sim.get_state()
        assert "boiler" in state
        assert state.get("digester") is None
        assert state.get("engine") is None

        bs = state["boiler"]
        assert "steam_pressure" in bs
        assert "steam_flow" in bs

    def test_get_state_combined(self):
        import uuid
        sim = SimulationInstance(
            sim_id=uuid.uuid4(),
            plant_type=PlantType.COMBINED,
        )
        for _ in range(10):
            sim.step(1.0)

        state = sim.get_state()
        assert "digester" in state
        assert "engine" in state
        assert "boiler" in state
        assert "plant" in state


def _run(coro):
    """Helper to run async code in tests without pytest-asyncio."""
    return asyncio.get_event_loop().run_until_complete(coro)


class TestSimulationManager:
    """Test simulation manager lifecycle."""

    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """Reset the singleton between tests."""
        SimulationManager._instance = None
        yield
        SimulationManager._instance = None

    def test_create_simulation(self):
        async def run():
            mgr = SimulationManager()
            sim = await mgr.create_simulation(PlantType.BIOGAS_ENGINE, realtime_factor=100.0)
            assert sim is not None
            assert sim.status == SimulationStatus.RUNNING
            assert mgr.active_count == 1
            await mgr.stop_simulation(sim.id)
            await asyncio.sleep(0.1)
        asyncio.run(run())

    def test_get_state(self):
        async def run():
            mgr = SimulationManager()
            sim = await mgr.create_simulation(PlantType.BIOGAS_ENGINE, realtime_factor=100.0)
            await asyncio.sleep(0.2)
            state = await mgr.get_state(sim.id)
            assert state is not None
            assert state["simulation_time"] > 0
            await mgr.stop_simulation(sim.id)
            await asyncio.sleep(0.1)
        asyncio.run(run())

    def test_stop_simulation(self):
        async def run():
            mgr = SimulationManager()
            sim = await mgr.create_simulation(PlantType.BIOGAS_ENGINE, realtime_factor=100.0)
            await asyncio.sleep(0.05)  # Let task start
            assert mgr.active_count == 1
            result = await mgr.stop_simulation(sim.id)
            assert result is True
            await asyncio.sleep(0.1)
            assert mgr.active_count == 0
        asyncio.run(run())

    def test_pause_resume(self):
        async def run():
            mgr = SimulationManager()
            sim = await mgr.create_simulation(PlantType.BIOGAS_ENGINE, realtime_factor=100.0)
            await asyncio.sleep(0.1)
            # Pause
            result = await mgr.pause_simulation(sim.id)
            assert result is True
            assert sim.status == SimulationStatus.PAUSED
            await asyncio.sleep(0.1)
            paused_time = sim.simulation_time
            await asyncio.sleep(0.2)
            assert sim.simulation_time == paused_time
            # Resume
            result = await mgr.resume_simulation(sim.id)
            assert result is True
            await asyncio.sleep(0.2)
            assert sim.simulation_time > paused_time
            await mgr.stop_simulation(sim.id)
            await asyncio.sleep(0.1)
        asyncio.run(run())

    def test_not_found(self):
        async def run():
            import uuid
            mgr = SimulationManager()
            state = await mgr.get_state(uuid.uuid4())
            assert state is None
        asyncio.run(run())

    def test_list_simulations(self):
        async def run():
            mgr = SimulationManager()
            sim = await mgr.create_simulation(PlantType.BIOGAS_ENGINE, realtime_factor=100.0)
            sims = mgr.all_simulations
            assert len(sims) == 1
            assert sims[0]["plant_type"] == "biogas_engine"
            await mgr.stop_simulation(sim.id)
            await asyncio.sleep(0.1)
        asyncio.run(run())
