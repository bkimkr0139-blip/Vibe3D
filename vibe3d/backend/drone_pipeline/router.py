"""FastAPI router for the Drone2Twin pipeline.

All endpoints prefixed with /api/drone/.
"""

import asyncio
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .models import PipelineStage
from .pipeline_orchestrator import PipelineOrchestrator
from .. import config

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/drone", tags=["drone"])

# Singleton orchestrator — initialized on import
_orchestrator = PipelineOrchestrator()


def get_orchestrator() -> PipelineOrchestrator:
    """Get the singleton orchestrator (allows main.py to inject dependencies)."""
    return _orchestrator


# ── Request models ───────────────────────────────────────────


class CreateProjectReq(BaseModel):
    name: str
    input_option: str = "vendor_pack"   # "vendor_pack", "raw_images", or "obj_folder"
    preset: str = "preview"             # "preview" or "production"
    base_dir: str = ""                  # optional custom directory


class RunPipelineReq(BaseModel):
    project_id: str


class RunStageReq(BaseModel):
    project_id: str
    stage: str  # PipelineStage value


class IngestAnalyzeReq(BaseModel):
    project_id: Optional[str] = None
    pack_dir: Optional[str] = None      # direct path (alternative to project_id)


class OptimizeReq(BaseModel):
    project_id: str


class UnityImportReq(BaseModel):
    project_id: str


class WebGLBuildReq(BaseModel):
    project_id: str


class DeployReq(BaseModel):
    project_id: str
    version: Optional[str] = None


# ── Project management ───────────────────────────────────────


@router.post("/project/create")
async def create_project(req: CreateProjectReq):
    """Create a new Drone2Twin project with standard folder structure."""
    try:
        project = _orchestrator.create_project(
            name=req.name,
            input_option=req.input_option,
            preset=req.preset,
            base_dir=req.base_dir,
        )
        return {
            "status": "created",
            "project": project.to_dict(),
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/project/{project_id}")
async def get_project(project_id: str):
    """Get project details."""
    project = _orchestrator.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
    return {"project": project.to_dict()}


@router.get("/projects")
async def list_projects():
    """List all projects."""
    return {"projects": _orchestrator.list_projects()}


@router.delete("/project/{project_id}")
async def delete_project(project_id: str):
    """Delete a project (metadata only)."""
    if _orchestrator.delete_project(project_id):
        return {"status": "deleted", "project_id": project_id}
    raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")


# ── Pipeline execution ───────────────────────────────────────


@router.post("/pipeline/run")
async def run_pipeline(req: RunPipelineReq):
    """Run full pipeline (async background task)."""
    project = _orchestrator.get_project(req.project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project '{req.project_id}' not found")

    # Run in background
    asyncio.create_task(_orchestrator.run_pipeline(req.project_id))

    return {
        "status": "started",
        "project_id": req.project_id,
        "input_option": project.input_option.value,
        "preset": project.preset.value,
        "message": f"Pipeline started for '{project.name}'",
    }


@router.get("/pipeline/status/{project_id}")
async def pipeline_status(project_id: str):
    """Get current pipeline status."""
    project = _orchestrator.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")

    return {
        "project_id": project_id,
        "name": project.name,
        "stage": project.stage.value,
        "input_option": project.input_option.value,
        "preset": project.preset.value,
        "artifacts": project.artifacts,
        "error": project.error,
    }


# ── Individual stage execution ───────────────────────────────


@router.post("/ingest/analyze")
async def ingest_analyze(req: IngestAnalyzeReq):
    """Run Ingest QA analysis."""
    if req.project_id:
        project = _orchestrator.get_project(req.project_id)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project '{req.project_id}' not found")
        result = await _orchestrator.run_stage(req.project_id, PipelineStage.INGEST_QA)
        return {
            "status": "completed",
            "project_id": req.project_id,
            "qa_report": result.qa_report.to_dict() if result.qa_report else None,
        }
    elif req.pack_dir:
        # Direct analysis without project
        from .ingest_qa import IngestQAEngine
        engine = IngestQAEngine()
        report = engine.analyze_pack(req.pack_dir)
        return {
            "status": "completed",
            "qa_report": report.to_dict(),
        }
    else:
        raise HTTPException(status_code=400, detail="Provide project_id or pack_dir")


@router.post("/recon/run")
async def run_reconstruction(req: RunStageReq):
    """Run reconstruction stage (Option B only)."""
    project = _orchestrator.get_project(req.project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project '{req.project_id}' not found")

    asyncio.create_task(
        _orchestrator.run_stage(req.project_id, PipelineStage.RECONSTRUCTION)
    )
    return {
        "status": "started",
        "project_id": req.project_id,
        "stage": "reconstruction",
    }


@router.post("/optimize/run")
async def run_optimization(req: OptimizeReq):
    """Run mesh optimization stage."""
    project = _orchestrator.get_project(req.project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project '{req.project_id}' not found")

    asyncio.create_task(
        _orchestrator.run_stage(req.project_id, PipelineStage.OPTIMIZATION)
    )
    return {
        "status": "started",
        "project_id": req.project_id,
        "stage": "optimization",
    }


@router.post("/unity/import")
async def run_unity_import(req: UnityImportReq):
    """Run Unity import + tiling stage."""
    project = _orchestrator.get_project(req.project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project '{req.project_id}' not found")

    asyncio.create_task(
        _orchestrator.run_stage(req.project_id, PipelineStage.UNITY_IMPORT)
    )
    return {
        "status": "started",
        "project_id": req.project_id,
        "stage": "unity_import",
    }


@router.post("/webgl/build")
async def run_webgl_build(req: WebGLBuildReq):
    """Run WebGL build stage."""
    project = _orchestrator.get_project(req.project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project '{req.project_id}' not found")

    asyncio.create_task(
        _orchestrator.run_stage(req.project_id, PipelineStage.WEBGL_BUILD)
    )
    return {
        "status": "started",
        "project_id": req.project_id,
        "stage": "webgl_build",
    }


@router.post("/deploy")
async def run_deploy(req: DeployReq):
    """Deploy WebGL build to production."""
    project = _orchestrator.get_project(req.project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project '{req.project_id}' not found")

    asyncio.create_task(
        _orchestrator.run_stage(req.project_id, PipelineStage.DEPLOY)
    )
    return {
        "status": "started",
        "project_id": req.project_id,
        "stage": "deploy",
    }


# ── OBJ Folder Scan ─────────────────────────────────────────


class OBJFolderScanReq(BaseModel):
    folder_path: str


@router.post("/obj-folder/scan")
async def scan_obj_folder(req: OBJFolderScanReq):
    """Scan an OBJ tile folder and return tile info without creating a project."""
    from .obj_folder_scanner import OBJFolderScanner

    scanner = OBJFolderScanner()
    tiles = scanner.scan(req.folder_path)
    warnings = scanner.validate_tiles(tiles)
    grid = scanner.get_grid_info(tiles)

    return {
        "tile_count": len(tiles),
        "total_size_mb": round(sum(t.size_mb for t in tiles), 1),
        "tiles": [t.to_dict() for t in tiles],
        "warnings": warnings,
        "grid": grid,
    }


# ── Reports ──────────────────────────────────────────────────


@router.get("/reports/{project_id}")
async def get_reports(project_id: str):
    """Get all reports for a project."""
    project = _orchestrator.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")

    return {
        "project_id": project_id,
        "reports": _orchestrator.get_reports(project_id),
    }


# ── City Tiles LOD ────────────────────────────────────────────


@router.get("/citytiles-lod")
async def list_citytiles_lod():
    """LOD metadata for all CityTiles (progressive web viewer loading)."""
    from .lod_server import discover_lod_metadata
    return discover_lod_metadata()


@router.get("/citytiles/{tile_name}/LOD/{filename}")
async def serve_citytile_lod_file(tile_name: str, filename: str):
    """Serve a LOD OBJ file with 24-hour cache."""
    from .lod_server import get_lod_file_path

    file_path = get_lod_file_path(tile_name, filename)
    if file_path is None:
        raise HTTPException(status_code=404, detail=f"LOD file not found: {tile_name}/LOD/{filename}")

    return FileResponse(
        path=str(file_path),
        media_type="text/plain",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "public, max-age=86400",
        },
    )


# ── City Tiles 3D Viewer ─────────────────────────────────────


def _get_citytiles_dir() -> Path:
    """Get the CityTiles asset directory."""
    return Path(config.UNITY_PROJECT_PATH) / "Assets" / "CityTiles"


@router.get("/citytiles")
async def list_citytiles():
    """List all CityTiles with metadata for 3D viewer."""
    import re

    tiles_dir = _get_citytiles_dir()
    if not tiles_dir.is_dir():
        return {"tiles": [], "message": "CityTiles directory not found"}

    tile_re = re.compile(r"Tile-(\d+)-(\d+)")
    tiles = []

    for folder in sorted(tiles_dir.iterdir()):
        if not folder.is_dir():
            continue
        m = tile_re.search(folder.name)
        if not m:
            continue

        row, col = int(m.group(1)), int(m.group(2))

        # Find OBJ file
        obj_files = list(folder.glob("*.obj"))
        if not obj_files:
            continue

        obj_file = obj_files[0]
        mtl_file = obj_file.with_suffix(".mtl")

        # Find textures
        tex_files = list(folder.glob("*.jpg")) + list(folder.glob("*.png"))

        tile_info = {
            "name": folder.name,
            "row": row,
            "col": col,
            "obj_file": obj_file.name,
            "mtl_file": mtl_file.name if mtl_file.exists() else None,
            "textures": [t.name for t in tex_files],
            "size_mb": round(obj_file.stat().st_size / (1024 * 1024), 1),
            "obj_url": f"/api/drone/citytiles/{folder.name}/{obj_file.name}",
            "mtl_url": f"/api/drone/citytiles/{folder.name}/{mtl_file.name}" if mtl_file.exists() else None,
        }
        tiles.append(tile_info)

    # Group by row
    rows = {}
    for t in tiles:
        rows.setdefault(t["row"], []).append(t)

    return {
        "tile_count": len(tiles),
        "total_size_mb": round(sum(t["size_mb"] for t in tiles), 1),
        "rows": {str(r): sorted(ts, key=lambda x: x["col"]) for r, ts in sorted(rows.items())},
        "tiles": tiles,
    }


@router.get("/citytiles/{tile_name}/{filename}")
async def serve_citytile_file(tile_name: str, filename: str):
    """Serve an OBJ, MTL, or texture file from CityTiles."""
    tiles_dir = _get_citytiles_dir()
    file_path = tiles_dir / tile_name / filename

    if not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {tile_name}/{filename}")

    # Determine content type
    suffix = file_path.suffix.lower()
    media_types = {
        ".obj": "text/plain",
        ".mtl": "text/plain",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
    }
    media_type = media_types.get(suffix, "application/octet-stream")

    return FileResponse(
        path=str(file_path),
        media_type=media_type,
        headers={"Access-Control-Allow-Origin": "*"},
    )
