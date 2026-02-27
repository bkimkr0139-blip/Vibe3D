"""LOD file discovery and metadata for CityTile web viewer.

Scans the CityTiles/{tile}/LOD/ directories for exported OBJ LOD files
and provides metadata (file sizes, URLs) to the frontend for progressive loading.
"""

import logging
import re
from pathlib import Path
from typing import Optional

from .. import config

logger = logging.getLogger(__name__)

# LOD level labels
LOD_LEVELS = ("LOD0", "LOD1", "LOD2")


def get_citytiles_dir() -> Path:
    """Get the CityTiles asset directory."""
    return Path(config.UNITY_PROJECT_PATH) / "Assets" / "CityTiles"


def discover_lod_metadata() -> dict:
    """Scan CityTiles for LOD files and return metadata.

    Returns:
        {
            "tiles": [
                {
                    "name": "Tile-37-26-1-1",
                    "row": 37, "col": 26,
                    "lod_levels": {
                        "lod0": {"url": "...", "size_mb": 105.2},
                        "lod1": {"url": "...", "size_mb": 42.1},
                        "lod2": {"url": "...", "size_mb": 15.8},
                    }
                }, ...
            ],
            "has_lods": true,
            "total_lod2_mb": 210.5,
            "total_lod0_mb": 1400.0,
        }
    """
    tiles_dir = get_citytiles_dir()
    if not tiles_dir.is_dir():
        return {"tiles": [], "has_lods": False, "total_lod2_mb": 0, "total_lod0_mb": 0}

    tile_re = re.compile(r"Tile-(\d+)-(\d+)")
    tiles = []
    total_lod0 = 0.0
    total_lod2 = 0.0
    has_any_lods = False

    for folder in sorted(tiles_dir.iterdir()):
        if not folder.is_dir():
            continue
        m = tile_re.search(folder.name)
        if not m:
            continue

        row, col = int(m.group(1)), int(m.group(2))

        # Find original OBJ (LOD0)
        obj_files = list(folder.glob("*.obj"))
        if not obj_files:
            continue

        obj_file = obj_files[0]
        lod0_size = obj_file.stat().st_size / (1024 * 1024)
        total_lod0 += lod0_size

        # Find MTL
        mtl_file = obj_file.with_suffix(".mtl")
        mtl_url = f"/api/drone/citytiles/{folder.name}/{mtl_file.name}" if mtl_file.exists() else None

        # Find textures
        tex_files = list(folder.glob("*.jpg")) + list(folder.glob("*.png"))

        lod_levels = {
            "lod0": {
                "url": f"/api/drone/citytiles/{folder.name}/{obj_file.name}",
                "size_mb": round(lod0_size, 1),
            },
        }

        # Check for LOD subfolder
        lod_dir = folder / "LOD"
        if lod_dir.is_dir():
            for lod_file in sorted(lod_dir.glob("*_LOD*.obj")):
                fname = lod_file.name
                size_mb = lod_file.stat().st_size / (1024 * 1024)

                if "_LOD1" in fname:
                    lod_levels["lod1"] = {
                        "url": f"/api/drone/citytiles/{folder.name}/LOD/{fname}",
                        "size_mb": round(size_mb, 1),
                    }
                    has_any_lods = True
                elif "_LOD2" in fname:
                    lod_levels["lod2"] = {
                        "url": f"/api/drone/citytiles/{folder.name}/LOD/{fname}",
                        "size_mb": round(size_mb, 1),
                    }
                    total_lod2 += size_mb
                    has_any_lods = True

        tile_info = {
            "name": folder.name,
            "row": row,
            "col": col,
            "lod_levels": lod_levels,
            "mtl_url": mtl_url,
            "textures": [t.name for t in tex_files],
        }
        tiles.append(tile_info)

    return {
        "tiles": tiles,
        "has_lods": has_any_lods,
        "tile_count": len(tiles),
        "total_lod0_mb": round(total_lod0, 1),
        "total_lod2_mb": round(total_lod2, 1),
    }


def get_lod_file_path(tile_name: str, filename: str) -> Optional[Path]:
    """Get the full filesystem path for a LOD file.

    Args:
        tile_name: e.g. "Tile-37-26-1-1"
        filename: e.g. "mesh_LOD1.obj"

    Returns:
        Path if file exists, None otherwise.
    """
    tiles_dir = get_citytiles_dir()
    file_path = tiles_dir / tile_name / "LOD" / filename

    if file_path.is_file():
        return file_path
    return None
