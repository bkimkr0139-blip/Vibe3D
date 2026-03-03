"""Project / Data Wizard router.

Provides endpoints for:
- Scanning OBJ tile folders (validation, stats, texture checks)
- Recommending edit presets based on data profile
- Generating project summary reports
"""

import asyncio
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from .tile_validator import validate_folder, validate_tile_file, ValidationResult

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/wizard", tags=["wizard"])


# ── Request/Response Models ────────────────────────────────

class ScanRequest(BaseModel):
    folder_path: str
    deep_scan: bool = False  # if True, count vertices (slower)


class ScanSummary(BaseModel):
    folder: str
    tile_count: int
    total_faces: int
    total_vertices: int
    total_size_mb: float
    avg_faces_per_tile: int
    estimated_memory_mb: float
    recommended_preset: str
    recommended_params: dict
    issues_by_severity: dict  # {error: N, warning: N, info: N}
    tiles: list
    issues: list


# ── Endpoints ──────────────────────────────────────────────

@router.post("/scan")
async def scan_folder(req: ScanRequest):
    """Scan an OBJ tile folder and return validation results + recommendations.

    This is the primary wizard endpoint:
    1) Validates all tiles (naming, textures, size)
    2) Collects polygon/vertex/size statistics
    3) Recommends optimal edit preset
    4) Estimates memory requirements
    """
    folder = Path(req.folder_path)
    if not folder.is_dir():
        raise HTTPException(404, f"Folder not found: {req.folder_path}")

    # Run in thread to avoid blocking (file I/O can be slow)
    result: ValidationResult = await asyncio.to_thread(validate_folder, req.folder_path)

    # Count issues by severity
    severity_counts = {"error": 0, "warning": 0, "info": 0}
    for issue in result.issues:
        sev = issue.severity if hasattr(issue, "severity") else "info"
        severity_counts[sev] = severity_counts.get(sev, 0) + 1

    # Convert to serializable format
    tiles_data = []
    for t in result.tiles:
        tiles_data.append({
            "tile_id": t.tile_id,
            "row": t.row,
            "col": t.col,
            "vertices": t.vertices,
            "faces": t.faces,
            "materials": t.materials,
            "textures_found": len(t.textures_found),
            "textures_missing": len(t.textures_missing),
            "file_size_mb": t.file_size_mb,
            "bounds_min": t.bounds_min,
            "bounds_max": t.bounds_max,
        })

    issues_data = []
    for i in result.issues:
        issues_data.append({
            "severity": i.severity,
            "code": i.code,
            "message": i.message,
            "file": i.file,
        })

    return {
        "folder": result.folder,
        "tile_count": result.tile_count,
        "total_faces": result.total_faces,
        "total_vertices": result.total_vertices,
        "total_size_mb": result.total_size_mb,
        "avg_faces_per_tile": result.avg_faces_per_tile,
        "estimated_memory_mb": result.estimated_memory_mb,
        "recommended_preset": result.recommended_preset,
        "recommended_params": result.recommended_params,
        "issues_by_severity": severity_counts,
        "tiles": tiles_data,
        "issues": issues_data,
    }


@router.get("/recommend")
async def recommend_preset(
    total_faces: int = Query(0, description="Total faces across all tiles"),
    tile_count: int = Query(1, description="Number of tiles"),
    target: str = Query("balanced", description="Optimization target: performance, balanced, quality"),
):
    """Get preset recommendation based on data profile."""
    avg = total_faces // max(1, tile_count)

    if target == "performance" or avg > 1_500_000:
        return {
            "preset": "pack_for_unity",
            "params": {
                "target_triangles_lod0": 400_000,
                "lod_ratios": [1.0, 0.3, 0.08],
                "collider_target_triangles": 30_000,
            },
            "mode": "performance",
            "reason": f"Aggressive decimation for {avg:,} avg faces/tile",
        }
    elif target == "quality" or avg < 200_000:
        return {
            "preset": "generate_lods",
            "params": {
                "lod_ratios": [1.0, 0.5, 0.2],
            },
            "mode": "quality",
            "reason": f"Light processing, preserving detail ({avg:,} avg faces/tile)",
        }
    else:
        return {
            "preset": "pack_for_unity",
            "params": {
                "target_triangles_lod0": 800_000,
                "lod_ratios": [1.0, 0.4, 0.15],
                "collider_target_triangles": 80_000,
            },
            "mode": "balanced",
            "reason": f"Balanced quality/performance for {avg:,} avg faces/tile",
        }


@router.get("/validate-tile")
async def validate_single_tile(
    path: str = Query(..., description="Path to OBJ tile file"),
):
    """Validate a single tile file (textures, size, content)."""
    result = await asyncio.to_thread(validate_tile_file, path)
    return result


@router.get("/presets-info")
async def presets_info():
    """Return detailed info about all available editing presets with use cases."""
    return {
        "presets": [
            {
                "id": "clean_noise",
                "name": "Clean Noise",
                "description": "Remove small fragments and floating debris. Reduces physics overhead and false occlusion.",
                "use_cases": ["Noisy photogrammetry data", "Tree/vehicle removal prep", "Pre-decimation cleanup"],
                "estimated_time": "30s-2min per tile",
                "risk": "low",
            },
            {
                "id": "decimate_to_target",
                "name": "Decimate to Target",
                "description": "Reduce polygon count to target while preserving tile boundaries.",
                "use_cases": ["High-poly tiles (>1M faces)", "Performance optimization", "Streaming budget compliance"],
                "estimated_time": "1-5min per tile",
                "risk": "medium",
            },
            {
                "id": "generate_lods",
                "name": "Generate LODs",
                "description": "Create LOD0/LOD1/LOD2 at configurable ratios for distance-based streaming.",
                "use_cases": ["Large scenes", "Camera distance optimization", "GPU memory management"],
                "estimated_time": "2-8min per tile",
                "risk": "low",
            },
            {
                "id": "generate_collider_proxy",
                "name": "Generate Collider Proxy",
                "description": "Create simplified mesh for Raycast/NavMesh/Visibility. Prioritizes ground continuity.",
                "use_cases": ["Measurement accuracy", "NavMesh baking", "Visibility analysis"],
                "estimated_time": "1-3min per tile",
                "risk": "low",
            },
            {
                "id": "pack_for_unity",
                "name": "Pack for Unity",
                "description": "Full pipeline: Clean → Decimate → LODs → Collider → Package with manifest.",
                "use_cases": ["New project setup", "Bulk tile processing", "One-click optimization"],
                "estimated_time": "5-15min per tile",
                "risk": "medium",
            },
        ],
        "modes": [
            {"id": "performance", "name": "Performance Priority", "description": "Aggressive decimation, smaller LODs. Best for weak GPUs."},
            {"id": "balanced", "name": "Balanced", "description": "Good visual quality with reasonable performance. Recommended for most projects."},
            {"id": "quality", "name": "Quality Priority", "description": "Minimal decimation, higher LOD ratios. Best for close-up inspection."},
        ],
    }
