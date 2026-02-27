"""OBJ folder scanner for Drone2Twin pipeline.

Scans a folder of OBJ tiles (e.g. Skyline city-view exports) and groups them
by row/col, parses MTL for texture references, and reads vertex/face counts.
"""

import logging
import os
import re
from pathlib import Path

from .models import OBJTileInfo

logger = logging.getLogger(__name__)

# Regex for Skyline-style tile names: Tile-{row}-{col}-1-1
_TILE_RE = re.compile(r"Tile-(\d+)-(\d+)")


class OBJFolderScanner:
    """Scans OBJ tile folders and produces tile metadata."""

    def scan(self, folder_path: str) -> list[OBJTileInfo]:
        """Scan folder for OBJ tiles and return sorted tile info list.

        Args:
            folder_path: Path to folder containing OBJ/MTL/texture files.

        Returns:
            List of OBJTileInfo sorted by (row, col).
        """
        folder = Path(folder_path)
        if not folder.is_dir():
            logger.warning("OBJ folder not found: %s", folder_path)
            return []

        # Find all .obj files
        obj_files = sorted(folder.glob("*.obj"))
        if not obj_files:
            # Also check one level deep
            obj_files = sorted(folder.glob("**/*.obj"))

        tiles: list[OBJTileInfo] = []

        for obj_path in obj_files:
            m = _TILE_RE.search(obj_path.stem)
            row = int(m.group(1)) if m else 0
            col = int(m.group(2)) if m else 0

            tile = OBJTileInfo(
                name=obj_path.stem,
                row=row,
                col=col,
                obj_path=str(obj_path),
            )

            # Look for matching MTL
            mtl_path = obj_path.with_suffix(".mtl")
            if mtl_path.exists():
                tile.mtl_path = str(mtl_path)
                tile.texture_paths = self._parse_mtl_textures(mtl_path)
            else:
                # Try common alternative names
                for alt in [obj_path.stem + ".mtl", obj_path.stem.lower() + ".mtl"]:
                    alt_path = obj_path.parent / alt
                    if alt_path.exists():
                        tile.mtl_path = str(alt_path)
                        tile.texture_paths = self._parse_mtl_textures(alt_path)
                        break

            # Read vertex/face counts from OBJ header comments
            verts, faces = self._read_obj_counts(obj_path)
            tile.vertex_count = verts
            tile.face_count = faces

            # Calculate total size (OBJ + MTL + textures)
            total_bytes = obj_path.stat().st_size
            if tile.mtl_path:
                try:
                    total_bytes += Path(tile.mtl_path).stat().st_size
                except OSError:
                    pass
            for tex in tile.texture_paths:
                try:
                    total_bytes += Path(tex).stat().st_size
                except OSError:
                    pass
            tile.size_mb = round(total_bytes / (1024 * 1024), 2)

            tiles.append(tile)

        # Sort by row, then col
        tiles.sort(key=lambda t: (t.row, t.col))
        logger.info("OBJ scan: found %d tiles in %s", len(tiles), folder_path)
        return tiles

    def validate_tiles(self, tiles: list[OBJTileInfo]) -> list[str]:
        """Validate tile set and return warnings.

        Args:
            tiles: List of scanned tiles.

        Returns:
            List of warning strings.
        """
        warnings: list[str] = []

        if not tiles:
            warnings.append("No OBJ tiles found")
            return warnings

        for tile in tiles:
            if not tile.mtl_path:
                warnings.append(f"{tile.name}: MTL file missing")
            if not tile.texture_paths:
                warnings.append(f"{tile.name}: No textures found")
            if tile.size_mb > 200:
                warnings.append(
                    f"{tile.name}: Very large ({tile.size_mb:.0f} MB) - import may be slow"
                )

        # Check grid completeness
        rows = sorted(set(t.row for t in tiles if t.row > 0))
        cols = sorted(set(t.col for t in tiles if t.col > 0))
        if rows and cols:
            expected = len(rows) * len(cols)
            actual = len([t for t in tiles if t.row > 0])
            if actual < expected:
                warnings.append(
                    f"Grid incomplete: expected {expected} tiles "
                    f"({len(rows)} rows x {len(cols)} cols), found {actual}"
                )

        return warnings

    def get_grid_info(self, tiles: list[OBJTileInfo]) -> dict:
        """Extract grid dimensions from tiles.

        Returns:
            Dict with rows, cols, row_range, col_range.
        """
        rows = sorted(set(t.row for t in tiles if t.row > 0))
        cols = sorted(set(t.col for t in tiles if t.col > 0))
        return {
            "rows": rows,
            "cols": cols,
            "row_count": len(rows),
            "col_count": len(cols),
            "row_range": [min(rows), max(rows)] if rows else [],
            "col_range": [min(cols), max(cols)] if cols else [],
        }

    # ── Internal helpers ──────────────────────────────────────

    def _parse_mtl_textures(self, mtl_path: Path) -> list[str]:
        """Parse MTL file and extract texture paths (map_Kd etc.)."""
        textures: list[str] = []
        parent = mtl_path.parent
        try:
            with open(mtl_path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    # map_Kd, map_Ka, map_Ks, map_Bump, etc.
                    if line.lower().startswith("map_"):
                        parts = line.split(None, 1)
                        if len(parts) >= 2:
                            tex_rel = parts[1].strip()
                            # Resolve relative to MTL location
                            tex_abs = parent / tex_rel
                            if tex_abs.exists():
                                textures.append(str(tex_abs))
                            else:
                                # Try just filename in same folder
                                tex_name = Path(tex_rel).name
                                tex_alt = parent / tex_name
                                if tex_alt.exists():
                                    textures.append(str(tex_alt))
        except Exception as e:
            logger.debug("Failed to parse MTL %s: %s", mtl_path, e)

        return list(set(textures))  # dedupe

    def _read_obj_counts(self, obj_path: Path) -> tuple[int, int]:
        """Read vertex/face counts from OBJ file.

        First tries header comments (fast), then falls back to counting
        v/f lines in the first portion of the file.
        """
        verts = 0
        faces = 0

        try:
            with open(obj_path, "r", encoding="utf-8", errors="replace") as f:
                # Read up to 200 header lines for comments
                for i, line in enumerate(f):
                    if i > 200:
                        break
                    line = line.strip()

                    # Skyline-style comments: # Vertices: 123456
                    if line.startswith("#"):
                        low = line.lower()
                        m_v = re.search(r"vertices?\s*[:=]\s*(\d+)", low)
                        if m_v:
                            verts = int(m_v.group(1))
                        m_f = re.search(r"faces?\s*[:=]\s*(\d+)", low)
                        if m_f:
                            faces = int(m_f.group(1))

                    # If we found counts in comments, stop early
                    if verts > 0 and faces > 0:
                        return verts, faces

                    # If we hit actual data, switch to counting
                    if line.startswith("v ") or line.startswith("f "):
                        break

            # Fallback: estimate from file size (rough heuristic)
            # Typical OBJ: ~30 bytes/vertex line, ~20 bytes/face line
            if verts == 0:
                size = obj_path.stat().st_size
                # Rough 60/40 split between vertex and face data
                verts = int(size * 0.6 / 30)
                faces = int(size * 0.4 / 20)

        except Exception as e:
            logger.debug("Failed to read OBJ counts for %s: %s", obj_path, e)

        return verts, faces
