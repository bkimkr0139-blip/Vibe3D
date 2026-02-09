"""Fermentation REST API routes."""

from uuid import UUID

from fastapi import APIRouter, HTTPException

from backend.api.models.fermentation_schemas import (
    FermentationCreate,
    FermentationResponse,
    FermentationState,
    FermentationControl,
)
from backend.services.fermentation_manager import FermentationManager

router = APIRouter()
manager = FermentationManager()


@router.post("/start", response_model=FermentationResponse)
async def start_fermentation(params: FermentationCreate):
    """Start a new fermentation simulation."""
    result = await manager.create_simulation(
        mode=params.mode,
        realtime_factor=params.realtime_factor,
        media_type=params.media_type,
    )
    return result


@router.get("/{simulation_id}/state")
async def get_fermentation_state(simulation_id: UUID):
    """Get the current state of a fermentation simulation."""
    state = await manager.get_state(simulation_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Simulation not found")
    return state


@router.post("/{simulation_id}/control")
async def apply_control(simulation_id: UUID, control: FermentationControl):
    """Apply manual control inputs to a fermentor."""
    success = await manager.apply_control(
        simulation_id,
        vessel_name="KF-7KL",
        controls=control.model_dump(exclude_none=True),
    )
    if not success:
        raise HTTPException(status_code=404, detail="Simulation not found")
    return {"status": "ok", "applied": control.model_dump(exclude_none=True)}


@router.post("/{simulation_id}/control/{vessel_name}")
async def apply_vessel_control(simulation_id: UUID, vessel_name: str,
                               control: FermentationControl):
    """Apply manual control inputs to a specific vessel."""
    success = await manager.apply_control(
        simulation_id,
        vessel_name=vessel_name,
        controls=control.model_dump(exclude_none=True),
    )
    if not success:
        raise HTTPException(status_code=404, detail="Simulation or vessel not found")
    return {"status": "ok", "vessel": vessel_name, "applied": control.model_dump(exclude_none=True)}


@router.post("/{simulation_id}/stop")
async def stop_fermentation(simulation_id: UUID):
    """Stop a running fermentation simulation."""
    success = await manager.stop_simulation(simulation_id)
    if not success:
        raise HTTPException(status_code=404, detail="Simulation not found")
    return {"status": "stopped", "simulation_id": str(simulation_id)}
