"""Simulation lifecycle endpoints.

Start, stop, pause, and query biomass/biogas plant simulations.
"""

from uuid import UUID

from fastapi import APIRouter, HTTPException

from backend.api.models.schemas import (
    SimulationCreate,
    SimulationResponse,
    SimulationState,
)

router = APIRouter()


@router.post("/start", response_model=SimulationResponse)
async def start_simulation(params: SimulationCreate):
    """Start a new biomass/biogas plant simulation."""
    # TODO: Implement via SimulationManager
    raise HTTPException(status_code=501, detail="Not implemented yet")


@router.get("/{simulation_id}/state", response_model=SimulationState)
async def get_simulation_state(simulation_id: UUID):
    """Get current state of a running simulation."""
    raise HTTPException(status_code=501, detail="Not implemented yet")


@router.post("/{simulation_id}/pause")
async def pause_simulation(simulation_id: UUID):
    """Pause a running simulation."""
    raise HTTPException(status_code=501, detail="Not implemented yet")


@router.post("/{simulation_id}/resume")
async def resume_simulation(simulation_id: UUID):
    """Resume a paused simulation."""
    raise HTTPException(status_code=501, detail="Not implemented yet")


@router.post("/{simulation_id}/stop")
async def stop_simulation(simulation_id: UUID):
    """Stop and clean up a simulation."""
    raise HTTPException(status_code=501, detail="Not implemented yet")
