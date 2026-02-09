"""Simulation lifecycle endpoints.

Start, stop, pause, and query biomass/biogas plant simulations.
"""

from uuid import UUID

from fastapi import APIRouter, HTTPException

from backend.api.models.schemas import (
    SimulationCreate,
    SimulationResponse,
    SimulationState,
    DigesterState,
    EngineState,
    BoilerState,
    PlantOverview,
)
from backend.services.simulation_manager import SimulationManager

router = APIRouter()
manager = SimulationManager()


@router.post("/start", response_model=SimulationResponse)
async def start_simulation(params: SimulationCreate):
    """Start a new biomass/biogas plant simulation."""
    try:
        sim = await manager.create_simulation(
            plant_type=params.plant_type,
            realtime_factor=params.realtime_factor,
            feedstock_type=params.feedstock_type,
            scenario_id=params.scenario_id,
        )
        return SimulationResponse(
            id=sim.id,
            status=sim.status,
            plant_type=sim.plant_type,
            created_at=sim.created_at,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=429, detail=str(e))


@router.get("/{simulation_id}/state", response_model=SimulationState)
async def get_simulation_state(simulation_id: UUID):
    """Get current state of a running simulation."""
    state = await manager.get_state(simulation_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Simulation not found")

    # Build typed response — map physics engine field names to schema field names
    digester = None
    if state.get("digester"):
        ds = state["digester"]
        digester = DigesterState(
            temperature=ds["temperature"],
            ph=ds["ph"],
            biogas_flow_rate=ds["biogas_flow_rate"],
            methane_content=ds["methane_content"],
            co2_content=ds["co2_content"],
            h2s_content=ds.get("h2s_ppm", 0.0),
            volatile_solids=ds["volatile_solids"],
            hydraulic_retention_time=ds["hydraulic_retention_time"],
            organic_loading_rate=ds["organic_loading_rate"],
        )

    engine = None
    if state.get("engine"):
        es = state["engine"]
        engine = EngineState(
            rpm=es["rpm"],
            power_output=es["power_output"],
            exhaust_temp=es["exhaust_temp"],
            fuel_flow=es["fuel_flow"],
            air_fuel_ratio=es["air_fuel_ratio"],
            electrical_efficiency=es["electrical_efficiency"],
            thermal_efficiency=es["thermal_efficiency"],
        )

    boiler = None
    if state.get("boiler"):
        bs = state["boiler"]
        boiler = BoilerState(
            steam_pressure=bs["steam_pressure"],
            steam_temperature=bs["steam_temperature"],
            feedwater_temp=bs["feedwater_temp"],
            fuel_feed_rate=bs["fuel_feed_rate"],
            combustion_temp=bs["combustion_temp"],
            flue_gas_temp=bs["flue_gas_temp"],
            steam_flow=bs["steam_flow"],
            boiler_efficiency=bs["boiler_efficiency"],
        )

    plant = PlantOverview(**state["plant"])

    return SimulationState(
        simulation_id=simulation_id,
        status=state["status"],
        simulation_time=state["simulation_time"],
        digester=digester,
        engine=engine,
        boiler=boiler,
        plant=plant,
    )


@router.post("/{simulation_id}/pause")
async def pause_simulation(simulation_id: UUID):
    """Pause a running simulation."""
    success = await manager.pause_simulation(simulation_id)
    if not success:
        raise HTTPException(status_code=404, detail="Simulation not found or not running")
    return {"status": "paused", "simulation_id": str(simulation_id)}


@router.post("/{simulation_id}/resume")
async def resume_simulation(simulation_id: UUID):
    """Resume a paused simulation."""
    success = await manager.resume_simulation(simulation_id)
    if not success:
        raise HTTPException(status_code=404, detail="Simulation not found or not paused")
    return {"status": "running", "simulation_id": str(simulation_id)}


@router.post("/{simulation_id}/stop")
async def stop_simulation(simulation_id: UUID):
    """Stop and clean up a simulation."""
    success = await manager.stop_simulation(simulation_id)
    if not success:
        raise HTTPException(status_code=404, detail="Simulation not found")
    return {"status": "stopped", "simulation_id": str(simulation_id)}


@router.get("/list")
async def list_simulations():
    """List all simulations."""
    return {
        "simulations": manager.all_simulations,
        "active_count": manager.active_count,
    }
