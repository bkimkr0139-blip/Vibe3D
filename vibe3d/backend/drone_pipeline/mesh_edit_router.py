# mesh_edit_router.py
# FastAPI router for tile mesh edit operations (6 endpoints).

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from .mesh_edit_manager import get_manager
from .mesh_edit_models import DEFAULT_PARAMS, EditPreset

logger = logging.getLogger("vibe3d.mesh_edit.router")

router = APIRouter(prefix="/api/mesh/edit", tags=["mesh-edit"])


# ── Request models ────────────────────────────────────────────

class EditStartRequest(BaseModel):
    tile_id: str
    preset: str = "pack_for_unity"
    project_dir: str = ""
    params: Optional[dict] = None


class EditApplyRequest(BaseModel):
    copy_to_unity: bool = False


# ── Routes ────────────────────────────────────────────────────

@router.post("/start")
async def start_edit_job(req: EditStartRequest):
    """Start a tile mesh edit job.

    Returns job_id for tracking progress via /status and /preview.
    """
    # Validate preset
    valid_presets = [e.value for e in EditPreset]
    if req.preset not in valid_presets:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid preset '{req.preset}'. Valid: {valid_presets}",
        )

    if not req.tile_id:
        raise HTTPException(status_code=400, detail="tile_id is required")

    manager = get_manager()
    job_id = manager.start_job(
        tile_id=req.tile_id,
        preset=req.preset,
        project_dir=req.project_dir,
        params=req.params,
    )

    return {
        "job_id": job_id,
        "tile_id": req.tile_id,
        "preset": req.preset,
        "message": f"Edit job started for {req.tile_id} with preset '{req.preset}'",
    }


@router.get("/status/{edit_job_id}")
async def get_edit_status(edit_job_id: str):
    """Get current status of an edit job (stage, progress, stats)."""
    manager = get_manager()
    status = manager.get_job_status(edit_job_id)
    if status is None:
        raise HTTPException(status_code=404, detail=f"Job {edit_job_id} not found")
    return status


@router.get("/preview/{edit_job_id}")
async def get_edit_preview(edit_job_id: str):
    """Get before/after comparison for a completed edit job."""
    manager = get_manager()
    preview = manager.get_preview(edit_job_id)
    if preview is None:
        raise HTTPException(status_code=404, detail=f"Job {edit_job_id} not found")
    return preview


@router.post("/apply/{edit_job_id}")
async def apply_edit_job(edit_job_id: str, req: EditApplyRequest = EditApplyRequest()):
    """Apply a preview-ready edit job — updates active_versions.json."""
    manager = get_manager()
    result = manager.apply_job(edit_job_id)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/cancel/{edit_job_id}")
async def cancel_edit_job(edit_job_id: str):
    """Cancel a running or pending edit job."""
    manager = get_manager()
    result = manager.cancel_job(edit_job_id)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/history")
async def get_edit_history(
    tile_id: Optional[str] = Query(None, description="Filter by tile ID"),
    limit: int = Query(50, ge=1, le=500),
):
    """Get edit job history, optionally filtered by tile_id."""
    manager = get_manager()
    return manager.get_history(tile_id=tile_id, limit=limit)


@router.get("/presets")
async def get_presets():
    """List available edit presets with their default parameters."""
    return {
        "presets": [
            {
                "value": e.value,
                "label": e.value.replace("_", " ").title(),
                "params": DEFAULT_PARAMS.get(e.value, {}),
            }
            for e in EditPreset
        ],
    }


@router.get("/check-blender")
async def check_blender():
    """Check if Blender is available for mesh editing."""
    manager = get_manager()
    return manager.check_blender()


# ── Rollback / Version management ─────────────────────────────

@router.post("/rollback/{tile_id}/{version}")
async def rollback_version(
    tile_id: str, version: int,
    project_dir: str = Query("", description="Project directory path"),
):
    """Rollback a tile to a specific version. version=0 reverts to raw."""
    manager = get_manager()
    result = manager.rollback_version(tile_id, version, project_dir)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/versions/{tile_id}")
async def get_tile_versions(tile_id: str):
    """Get all edit versions for a specific tile."""
    manager = get_manager()
    return manager.get_tile_versions(tile_id)


@router.get("/compare/{tile_id}")
async def compare_versions(
    tile_id: str,
    v1: int = Query(0, description="First version (0=earliest)"),
    v2: int = Query(0, description="Second version (0=latest)"),
):
    """Compare stats between two versions of a tile."""
    manager = get_manager()
    result = manager.compare_versions(tile_id, v1, v2)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


# ── Tile validation & reports ──────────────────────────────────

@router.get("/validate/{tile_id}")
async def validate_tile(
    tile_id: str,
    project_dir: str = Query("", description="Project directory path"),
):
    """Validate a tile file for issues (missing textures, size, naming)."""
    manager = get_manager()
    return manager.validate_tile(tile_id, project_dir)


@router.get("/report")
async def get_quality_report(
    project_dir: str = Query("", description="Project directory path"),
):
    """Generate a quality report across all tile edit jobs."""
    manager = get_manager()
    return manager.generate_report(project_dir)
