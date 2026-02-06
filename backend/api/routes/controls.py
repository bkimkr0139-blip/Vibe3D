"""Manual control interface endpoints.

Allows operators to adjust plant parameters during simulation.
"""

from uuid import UUID

from fastapi import APIRouter, HTTPException

from backend.api.models.schemas import ControlAdjustment

router = APIRouter()


@router.post("/{simulation_id}/adjust")
async def adjust_control(simulation_id: UUID, adjustment: ControlAdjustment):
    """Apply a manual control adjustment to the simulation.

    Controllable parameters:
    - digester_feed_rate: Feedstock input rate (kg/h)
    - digester_temperature: Digester heating setpoint (C)
    - engine_load_setpoint: Engine load target (%)
    - boiler_fuel_feed: Biomass fuel feed rate (kg/h)
    - steam_valve_position: Steam control valve (%)
    """
    raise HTTPException(status_code=501, detail="Not implemented yet")


@router.get("/{simulation_id}/parameters")
async def get_controllable_parameters(simulation_id: UUID):
    """List all controllable parameters and their current values."""
    raise HTTPException(status_code=501, detail="Not implemented yet")
