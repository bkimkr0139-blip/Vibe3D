"""Tile data validation utility.

Validates tile files before editing:
- Filename convention (tile_{row}_{col} or Tile-{row}-{col})
- Missing textures / broken MTL links
- Coordinate system sanity (bounds check)
- Polygon/vertex budget assessment
- Recommended presets based on data profile
"""

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Supported tile name patterns
_TILE_PATTERNS = [
    re.compile(r"^tile[_-](\d+)[_-](\d+)", re.IGNORECASE),
    re.compile(r"^Tile-(\d+)-(\d+)"),
]


@dataclass
class ValidationIssue:
    severity: str  # "error", "warning", "info"
    code: str
    message: str
    file: str = ""


@dataclass
class TileProfile:
    tile_id: str
    file_path: str
    vertices: int = 0
    faces: int = 0
    materials: int = 0
    textures_referenced: list = field(default_factory=list)
    textures_found: list = field(default_factory=list)
    textures_missing: list = field(default_factory=list)
    file_size_mb: float = 0.0
    bounds_min: list = field(default_factory=lambda: [0, 0, 0])
    bounds_max: list = field(default_factory=lambda: [0, 0, 0])
    row: int = 0
    col: int = 0


@dataclass
class ValidationResult:
    folder: str
    tile_count: int = 0
    total_faces: int = 0
    total_vertices: int = 0
    total_size_mb: float = 0.0
    avg_faces_per_tile: int = 0
    issues: list = field(default_factory=list)
    tiles: list = field(default_factory=list)
    recommended_preset: str = ""
    recommended_params: dict = field(default_factory=dict)
    estimated_memory_mb: float = 0.0


def parse_tile_id(filename: str) -> tuple:
    """Extract (tile_id, row, col) from filename."""
    stem = Path(filename).stem
    for pat in _TILE_PATTERNS:
        m = pat.search(stem)
        if m:
            row, col = int(m.group(1)), int(m.group(2))
            return f"tile_{row:04d}_{col:04d}", row, col
    return stem, 0, 0


def count_obj_stats(obj_path: Path) -> tuple:
    """Fast vertex/face count from OBJ file without full parse.

    Returns (vertices, faces, materials_referenced, bounds_min, bounds_max).
    """
    vertices = 0
    faces = 0
    materials = set()
    xs, ys, zs = [], [], []

    try:
        with open(obj_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if line.startswith("v "):
                    vertices += 1
                    parts = line.split()
                    if len(parts) >= 4:
                        try:
                            x, y, z = float(parts[1]), float(parts[2]), float(parts[3])
                            xs.append(x)
                            ys.append(y)
                            zs.append(z)
                        except ValueError:
                            pass
                elif line.startswith("f "):
                    faces += 1
                elif line.startswith("usemtl "):
                    materials.add(line.strip().split(None, 1)[1] if len(line.strip().split(None, 1)) > 1 else "")
    except Exception as e:
        logger.warning("Failed to read OBJ %s: %s", obj_path, e)

    bounds_min = [min(xs) if xs else 0, min(ys) if ys else 0, min(zs) if zs else 0]
    bounds_max = [max(xs) if xs else 0, max(ys) if ys else 0, max(zs) if zs else 0]

    return vertices, faces, len(materials), bounds_min, bounds_max


def parse_mtl_textures(mtl_path: Path) -> list:
    """Extract texture filenames from MTL file."""
    textures = []
    texture_keys = {"map_Kd", "map_Ks", "map_Ka", "map_Bump", "bump", "map_d", "map_Ns"}
    try:
        with open(mtl_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                parts = line.strip().split(None, 1)
                if len(parts) == 2 and parts[0] in texture_keys:
                    textures.append(parts[1].strip())
    except Exception as e:
        logger.warning("Failed to read MTL %s: %s", mtl_path, e)
    return textures


def find_mtl_for_obj(obj_path: Path) -> Optional[Path]:
    """Find MTL file referenced by OBJ or co-located."""
    # Check mtllib directive in OBJ
    try:
        with open(obj_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if line.startswith("mtllib "):
                    mtl_name = line.strip().split(None, 1)[1].strip()
                    mtl_path = obj_path.parent / mtl_name
                    if mtl_path.exists():
                        return mtl_path
                if line.startswith("v "):
                    break  # stop after header
    except Exception:
        pass

    # Fallback: same name with .mtl extension
    mtl_path = obj_path.with_suffix(".mtl")
    if mtl_path.exists():
        return mtl_path

    return None


def validate_folder(folder_path: str) -> ValidationResult:
    """Validate a folder of OBJ tiles.

    Returns comprehensive validation result with issues, profiles, and recommendations.
    """
    folder = Path(folder_path)
    result = ValidationResult(folder=folder_path)

    if not folder.is_dir():
        result.issues.append(ValidationIssue(
            severity="error", code="FOLDER_NOT_FOUND",
            message=f"Folder does not exist: {folder_path}",
        ))
        return result

    # Find OBJ files
    obj_files = sorted(folder.glob("*.obj"))
    if not obj_files:
        obj_files = sorted(folder.glob("**/*.obj"))

    if not obj_files:
        result.issues.append(ValidationIssue(
            severity="error", code="NO_OBJ_FILES",
            message="No .obj files found in folder",
        ))
        return result

    # Validate each tile
    seen_ids = {}
    for obj_path in obj_files:
        tile_id, row, col = parse_tile_id(obj_path.name)

        # Check naming convention
        valid_name = any(pat.search(obj_path.stem) for pat in _TILE_PATTERNS)
        if not valid_name:
            result.issues.append(ValidationIssue(
                severity="warning", code="NAMING_CONVENTION",
                message=f"File '{obj_path.name}' doesn't follow tile naming convention (tile_ROW_COL or Tile-ROW-COL)",
                file=str(obj_path),
            ))

        # Check duplicates
        if tile_id in seen_ids:
            result.issues.append(ValidationIssue(
                severity="error", code="DUPLICATE_TILE_ID",
                message=f"Duplicate tile_id '{tile_id}': {obj_path.name} and {seen_ids[tile_id]}",
                file=str(obj_path),
            ))
        seen_ids[tile_id] = obj_path.name

        # Count stats
        verts, faces, mat_count, bounds_min, bounds_max = count_obj_stats(obj_path)
        file_size_mb = obj_path.stat().st_size / (1024 * 1024)

        # Find and validate textures
        mtl_path = find_mtl_for_obj(obj_path)
        textures_ref = []
        textures_found = []
        textures_missing = []

        if mtl_path:
            textures_ref = parse_mtl_textures(mtl_path)
            for tex in textures_ref:
                tex_path = mtl_path.parent / tex
                if tex_path.exists():
                    textures_found.append(tex)
                else:
                    textures_missing.append(tex)
                    result.issues.append(ValidationIssue(
                        severity="warning", code="MISSING_TEXTURE",
                        message=f"Texture '{tex}' referenced in MTL but not found",
                        file=str(mtl_path),
                    ))
        else:
            result.issues.append(ValidationIssue(
                severity="info", code="NO_MTL",
                message=f"No MTL file found for {obj_path.name}",
                file=str(obj_path),
            ))

        # Size warnings
        if faces > 2_000_000:
            result.issues.append(ValidationIssue(
                severity="warning", code="HIGH_POLYCOUNT",
                message=f"Tile {tile_id} has {faces:,} faces (>2M), consider decimation",
                file=str(obj_path),
            ))
        if file_size_mb > 200:
            result.issues.append(ValidationIssue(
                severity="warning", code="LARGE_FILE",
                message=f"Tile {tile_id} is {file_size_mb:.1f} MB (>200 MB)",
                file=str(obj_path),
            ))

        # Zero-vertex check
        if verts == 0:
            result.issues.append(ValidationIssue(
                severity="error", code="EMPTY_TILE",
                message=f"Tile {tile_id} has 0 vertices (empty or corrupt)",
                file=str(obj_path),
            ))

        profile = TileProfile(
            tile_id=tile_id,
            file_path=str(obj_path),
            vertices=verts,
            faces=faces,
            materials=mat_count,
            textures_referenced=textures_ref,
            textures_found=textures_found,
            textures_missing=textures_missing,
            file_size_mb=round(file_size_mb, 2),
            bounds_min=bounds_min,
            bounds_max=bounds_max,
            row=row,
            col=col,
        )
        result.tiles.append(profile)
        result.total_faces += faces
        result.total_vertices += verts
        result.total_size_mb += file_size_mb

    result.tile_count = len(result.tiles)
    result.total_size_mb = round(result.total_size_mb, 2)
    result.avg_faces_per_tile = result.total_faces // max(1, result.tile_count)

    # Estimate runtime memory (rough: ~80 bytes/vertex + textures)
    result.estimated_memory_mb = round(result.total_vertices * 80 / (1024 * 1024) + result.total_size_mb * 0.3, 1)

    # Generate recommendations
    result.recommended_preset, result.recommended_params = _recommend_preset(result)

    return result


def _recommend_preset(result: ValidationResult) -> tuple:
    """Recommend an editing preset based on data profile."""
    avg = result.avg_faces_per_tile

    if avg > 1_500_000:
        return "pack_for_unity", {
            "target_triangles_lod0": 600_000,
            "lod_ratios": [1.0, 0.35, 0.1],
            "collider_target_triangles": 50_000,
            "mode": "performance",
            "reason": f"High polygon density ({avg:,} avg faces/tile). Aggressive decimation + LOD recommended.",
        }
    elif avg > 500_000:
        return "pack_for_unity", {
            "target_triangles_lod0": 800_000,
            "lod_ratios": [1.0, 0.4, 0.15],
            "collider_target_triangles": 80_000,
            "mode": "balanced",
            "reason": f"Moderate polygon density ({avg:,} avg faces/tile). Balanced preset recommended.",
        }
    elif avg > 100_000:
        return "generate_lods", {
            "lod_ratios": [1.0, 0.4, 0.15],
            "mode": "quality",
            "reason": f"Acceptable polygon density ({avg:,} avg faces/tile). LOD generation sufficient.",
        }
    else:
        return "clean_noise", {
            "min_fragment_area": 0.5,
            "mode": "quality",
            "reason": f"Low polygon density ({avg:,} avg faces/tile). Light cleanup only.",
        }


def validate_tile_file(tile_path: str) -> dict:
    """Validate a single tile file and return issues dict."""
    path = Path(tile_path)
    issues = []

    if not path.exists():
        return {"valid": False, "issues": [{"severity": "error", "code": "FILE_NOT_FOUND", "message": f"File not found: {tile_path}"}]}

    verts, faces, mats, bmin, bmax = count_obj_stats(path)

    if verts == 0:
        issues.append({"severity": "error", "code": "EMPTY_TILE", "message": "Tile has 0 vertices"})

    mtl = find_mtl_for_obj(path)
    if mtl:
        textures = parse_mtl_textures(mtl)
        for tex in textures:
            if not (mtl.parent / tex).exists():
                issues.append({"severity": "warning", "code": "MISSING_TEXTURE", "message": f"Missing texture: {tex}"})

    file_size = path.stat().st_size / (1024 * 1024)
    if file_size > 200:
        issues.append({"severity": "warning", "code": "LARGE_FILE", "message": f"File is {file_size:.1f} MB"})

    return {
        "valid": len([i for i in issues if i["severity"] == "error"]) == 0,
        "vertices": verts,
        "faces": faces,
        "materials": mats,
        "file_size_mb": round(file_size, 2),
        "issues": issues,
    }
