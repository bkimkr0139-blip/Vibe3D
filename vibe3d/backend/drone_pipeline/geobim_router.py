"""GeoBIM API router — building extraction, pipeline, collider, export endpoints.

All endpoints are prefixed with /api/drone/geobim.
"""

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .geobim_collider_proxy import get_generator
from .geobim_db import get_db
from .geobim_export import get_exporter
from .geobim_extractor import get_extractor
from .geobim_models import ExtractionStatus
from .geobim_pipeline import get_pipeline
from .geobim_simulation import get_pathfinder, get_visibility

logger = logging.getLogger("vibe3d.geobim.router")

router = APIRouter(prefix="/api/drone/geobim", tags=["GeoBIM"])

# ── Request models ──────────────────────────────────────────


class ExtractRequest(BaseModel):
    tile_folder: str
    params: Optional[dict] = None


class PipelineRequest(BaseModel):
    tile_folder: str
    export_folder: str
    skip_collider: bool = False
    params: Optional[dict] = None


class ColliderRequest(BaseModel):
    tile_folder: str
    output_dir: str
    params: Optional[dict] = None


class ExportRequest(BaseModel):
    output_dir: str
    collider_dir: Optional[str] = None


class MeasurementExportRequest(BaseModel):
    measurements: list[dict]
    output_path: str
    format: str = "json"  # "json" or "csv"


class PathfindRequest(BaseModel):
    start: list[float]    # [x, z]
    end: list[float]      # [x, z]
    resolution: float = 1.0
    agent_radius: float = 0.5


class VisibilityRequest(BaseModel):
    sensors: list[dict]   # [{position:[x,y,z], hfov, yaw, max_distance, ...}]
    region: Optional[dict] = None  # {min_x, min_z, max_x, max_z}
    grid_resolution: float = 2.0


class ReviewDecisionRequest(BaseModel):
    building_id: str
    decision: str   # 'building', 'not_building', 'skip'
    notes: str = ""


class AccessibilityRequest(BaseModel):
    start: list[float]       # [x, z]
    max_time: float = 300.0  # seconds
    speed: float = 1.4       # m/s walking speed
    resolution: float = 1.0


class CoverageReportRequest(BaseModel):
    sensors: list[dict]
    building_ids: Optional[list[str]] = None  # None = all buildings
    grid_resolution: float = 2.0


# ══════════════════════════════════════════════════════════════
# Building Extraction
# ══════════════════════════════════════════════════════════════


@router.post("/extract")
async def extract_buildings(req: ExtractRequest):
    """Start building extraction from OBJ tiles (runs in background)."""
    extractor = get_extractor()
    if extractor.report.status == ExtractionStatus.RUNNING:
        return {
            "status": "already_running",
            "tiles_processed": extractor.report.tiles_processed,
            "tile_count": extractor.report.tile_count,
        }

    if req.params:
        extractor.params.update(req.params)

    db = get_db()
    db.clear_all()

    async def _run():
        try:
            report = await asyncio.to_thread(extractor.extract_all, req.tile_folder)
            db.save_buildings(report.buildings)
            db.save_report(report)
        except Exception as e:
            logger.error(f"Extraction failed: {e}")
            extractor._report.status = ExtractionStatus.FAILED
            extractor._report.error = str(e)

    asyncio.create_task(_run())
    return {"status": "started", "tile_folder": req.tile_folder}


@router.get("/status")
async def extraction_status():
    """Get current extraction progress."""
    extractor = get_extractor()
    r = extractor.report
    return {
        "status": r.status.value,
        "tile_count": r.tile_count,
        "tiles_processed": r.tiles_processed,
        "building_count": r.building_count,
        "processing_time_s": round(r.processing_time_s, 2),
        "error": r.error,
    }


@router.get("/buildings")
async def list_buildings(
    tile_name: Optional[str] = Query(None),
    min_height: Optional[float] = Query(None),
    min_confidence: Optional[float] = Query(None),
    limit: int = Query(500, ge=1, le=2000),
):
    """List extracted buildings with optional filters."""
    db = get_db()
    buildings = db.get_buildings(
        tile_name=tile_name, min_height=min_height,
        min_confidence=min_confidence, limit=limit,
    )
    return {"count": len(buildings), "buildings": [b.to_dict() for b in buildings]}


@router.get("/buildings/{building_id}")
async def get_building(building_id: str):
    """Get detailed info for a single building."""
    db = get_db()
    b = db.get_building(building_id)
    if not b:
        raise HTTPException(status_code=404, detail="Building not found")
    return b.to_dict()


@router.get("/footprints")
async def get_footprints():
    """Return all footprints (lightweight, for 3D overlay rendering)."""
    db = get_db()
    return {"count": len(fp := db.get_footprints()), "footprints": fp}


@router.get("/summary")
async def get_summary():
    """Return aggregate statistics."""
    db = get_db()
    summary = db.get_summary()
    report = db.get_latest_report()
    if report:
        summary["last_extraction"] = {
            "status": report["status"],
            "processing_time_s": report["processing_time_s"],
            "ground_plane_z": report["ground_plane_z"],
        }
    return summary


@router.get("/spatial")
async def spatial_query(
    x: float = Query(...), z: float = Query(...),
    radius: float = Query(10.0, ge=1.0, le=500.0),
):
    """Find buildings near a point (XZ plane coordinates)."""
    db = get_db()
    buildings = db.spatial_query(x, z, radius)
    return {"count": len(buildings), "buildings": [b.to_dict() for b in buildings]}


# ══════════════════════════════════════════════════════════════
# Full Pipeline (00-40)
# ══════════════════════════════════════════════════════════════


@router.post("/pipeline/run")
async def run_pipeline(req: PipelineRequest):
    """Run the full GeoBIM pipeline (00→40) in background."""
    pipeline = get_pipeline()
    if pipeline.state.is_running:
        return {"status": "already_running", **pipeline.state.to_dict()}

    if req.params:
        get_extractor().params.update(req.params)

    async def _run():
        await asyncio.to_thread(
            pipeline.run_full, req.tile_folder, req.export_folder, req.skip_collider
        )

    asyncio.create_task(_run())
    return {"status": "started", "tile_folder": req.tile_folder, "export_folder": req.export_folder}


@router.get("/pipeline/status")
async def pipeline_status():
    """Get pipeline progress."""
    return get_pipeline().state.to_dict()


# ══════════════════════════════════════════════════════════════
# Collider Proxy
# ══════════════════════════════════════════════════════════════


@router.post("/collider/generate")
async def generate_colliders(req: ColliderRequest):
    """Generate collider proxies via Blender headless."""
    gen = get_generator()
    if not gen.check_blender():
        raise HTTPException(status_code=503, detail="Blender not available")

    if req.params:
        gen.params.update(req.params)

    async def _run():
        await asyncio.to_thread(gen.generate_all, req.tile_folder, req.output_dir)

    asyncio.create_task(_run())
    return {"status": "started", "output_dir": req.output_dir}


@router.get("/collider/check-blender")
async def check_blender():
    """Check if Blender is available for collider generation."""
    return {"available": get_generator().check_blender()}


@router.get("/collider/list")
async def list_colliders():
    """List generated collider proxies."""
    return {"proxies": get_db().get_collider_proxies()}


# ══════════════════════════════════════════════════════════════
# Export
# ══════════════════════════════════════════════════════════════


@router.post("/export")
async def export_data(req: ExportRequest):
    """Export GeoBIM data (JSONL + SQLite + colliders) to folder."""
    exporter = get_exporter()
    result = await asyncio.to_thread(exporter.export_all, req.output_dir, req.collider_dir)
    return result


@router.get("/export/jsonl")
async def export_jsonl():
    """Download buildings.jsonl directly."""
    db = get_db()
    buildings = db.get_buildings(limit=10000)
    lines = [b.to_jsonl() for b in buildings]
    from fastapi.responses import JSONResponse
    return JSONResponse(content={"buildings": lines})


@router.post("/export/measurements")
async def export_measurements(req: MeasurementExportRequest):
    """Export measurement results to JSON or CSV."""
    exporter = get_exporter()
    path = await asyncio.to_thread(
        exporter.export_measurements, req.measurements, req.output_path, req.format
    )
    return {"success": True, "path": path, "count": len(req.measurements)}


# ══════════════════════════════════════════════════════════════
# Simulation: NavMesh Pathfinding (Section 4.7)
# ══════════════════════════════════════════════════════════════


@router.post("/pathfind")
async def pathfind(req: PathfindRequest):
    """A* pathfinding between two points, avoiding building footprints."""
    pf = get_pathfinder(resolution=req.resolution)
    pf.agent_radius = req.agent_radius
    pf.invalidate()  # rebuild grid with current buildings
    result = await asyncio.to_thread(pf.find_path, req.start, req.end)
    return result.to_dict()


@router.post("/pathfind/reset")
async def pathfind_reset():
    """Force rebuild of pathfinding grid."""
    get_pathfinder().invalidate()
    return {"status": "ok"}


# ══════════════════════════════════════════════════════════════
# Simulation: Visibility / Blind-Spot Analysis (Section 4.8)
# ══════════════════════════════════════════════════════════════


@router.post("/visibility")
async def visibility_analysis(req: VisibilityRequest):
    """Sensor visibility / blind-spot analysis via 2D ray marching."""
    analyzer = get_visibility()
    result = await asyncio.to_thread(
        analyzer.analyze, req.sensors, req.region, req.grid_resolution,
    )
    return result.to_dict()


# ══════════════════════════════════════════════════════════════
# HITL Review Queue (Section 3.3.3)
# ══════════════════════════════════════════════════════════════


@router.post("/review/populate")
async def populate_review_queue(threshold: float = Query(0.5, ge=0.0, le=1.0)):
    """Populate review queue with low-confidence buildings."""
    db = get_db()
    count = db.populate_review_queue(threshold)
    return {"status": "ok", "count": count, "threshold": threshold}


@router.get("/review/queue")
async def get_review_queue(
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
):
    """Get buildings in the review queue."""
    db = get_db()
    items = db.get_review_queue(status=status, limit=limit)
    return {"count": len(items), "items": items}


@router.post("/review/decide")
async def review_decide(req: ReviewDecisionRequest):
    """Submit a review decision for a building."""
    # Map user-friendly labels to DB status values
    decision_map = {"confirm": "building", "reject": "not_building", "skip": "skip"}
    db_decision = decision_map.get(req.decision, req.decision)
    db = get_db()
    ok = db.review_building(req.building_id, db_decision, req.notes)
    if not ok:
        raise HTTPException(status_code=404, detail="Building not in review queue")
    return {"status": "ok", "building_id": req.building_id, "decision": req.decision}


@router.get("/review/stats")
async def review_stats():
    """Get review queue statistics."""
    db = get_db()
    return db.get_review_stats()


# ══════════════════════════════════════════════════════════════
# Accessibility Analysis (Section 4.7 — reachable area/time)
# ══════════════════════════════════════════════════════════════


@router.post("/accessibility")
async def accessibility_analysis(req: AccessibilityRequest):
    """Flood-fill reachable area from a start point within max_time."""
    pf = get_pathfinder(resolution=req.resolution)
    pf.invalidate()
    result = await asyncio.to_thread(
        pf.flood_fill, req.start, req.max_time, req.speed
    )
    return result


# ══════════════════════════════════════════════════════════════
# Per-Building Coverage Report (Section 4.8)
# ══════════════════════════════════════════════════════════════


@router.post("/visibility/coverage-report")
async def coverage_report(req: CoverageReportRequest):
    """Per-building blind-spot coverage aggregation."""
    analyzer = get_visibility()
    result = await asyncio.to_thread(
        analyzer.building_coverage_report,
        req.sensors, req.building_ids, req.grid_resolution,
    )
    return result
