"""Re-center OBJ tile vertex coordinates to Unity-friendly values.

Reads OBJ files from source folder, calculates the centroid of the first tile,
then subtracts that offset from all vertex positions. Writes re-centered OBJ files
directly to Unity's Assets/CityTiles/ folder structure.

Usage:
    python recenter_obj_tiles.py
"""

import os
import re
import shutil
import time
from pathlib import Path

# ── Configuration ──
SOURCE_DIR = Path(r"C:\Users\User\works\obj")
UNITY_CITYTILES = Path(r"C:\UnityProjects\My project\Assets\CityTiles")

TILE_RE = re.compile(r"Tile-(\d+)-(\d+)")


def find_centroid(obj_path: Path, max_vertices: int = 5000) -> tuple[float, float, float]:
    """Read first N vertices from OBJ and compute centroid."""
    sx, sy, sz = 0.0, 0.0, 0.0
    count = 0

    with open(obj_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.startswith("v "):
                parts = line.split()
                if len(parts) >= 4:
                    sx += float(parts[1])
                    sy += float(parts[2])
                    sz += float(parts[3])
                    count += 1
                    if count >= max_vertices:
                        break

    if count == 0:
        return 0.0, 0.0, 0.0

    return sx / count, sy / count, sz / count


def recenter_obj(src: Path, dst: Path, offset: tuple[float, float, float],
                  swap_yz: bool = True):
    """Rewrite OBJ file with vertex offset and optional Y↔Z swap.

    OBJ from Skyline photogrammetry:
        X = Easting, Y = Northing (horizontal), Z = Elevation (vertical)
    Unity coordinate system:
        X = Right, Y = Up (vertical), Z = Forward (horizontal)

    With swap_yz=True:
        OBJ(X,Y,Z) → Unity(X, Z_elev, Y_north)
        This maps Elevation→Up, Northing→Forward
    """
    ox, oy, oz = offset
    vertices_processed = 0

    with open(src, "r", encoding="utf-8", errors="replace") as fin, \
         open(dst, "w", encoding="utf-8", newline="\n") as fout:
        for line in fin:
            if line.startswith("v "):
                parts = line.split()
                if len(parts) >= 4:
                    x = float(parts[1]) - ox
                    y = float(parts[2]) - oy
                    z = float(parts[3]) - oz
                    if swap_yz:
                        # X stays, Y(northing)→Z(forward), Z(elev)→Y(up)
                        new_line = f"v {x:.8f} {z:.8f} {y:.8f}"
                    else:
                        new_line = f"v {x:.8f} {y:.8f} {z:.8f}"
                    # Keep extra components (w) if present
                    extra = " ".join(parts[4:])
                    if extra:
                        new_line += " " + extra
                    fout.write(new_line + "\n")
                    vertices_processed += 1
                else:
                    fout.write(line)
            elif line.startswith("vn "):
                # Swap normals too
                if swap_yz:
                    parts = line.split()
                    if len(parts) >= 4:
                        nx, ny, nz = float(parts[1]), float(parts[2]), float(parts[3])
                        fout.write(f"vn {nx:.8f} {nz:.8f} {ny:.8f}\n")
                    else:
                        fout.write(line)
                else:
                    fout.write(line)
            elif line.startswith("vt "):
                # Texture coords don't need changes
                fout.write(line)
            else:
                fout.write(line)

    return vertices_processed


def main():
    # Find all OBJ files
    obj_files = sorted(SOURCE_DIR.glob("*.obj"))
    if not obj_files:
        print(f"No OBJ files found in {SOURCE_DIR}")
        return

    print(f"Found {len(obj_files)} OBJ tiles in {SOURCE_DIR}")

    # ── Calculate global centroid from first tile ──
    print(f"\nCalculating centroid from {obj_files[0].name}...")
    cx, cy, cz = find_centroid(obj_files[0])
    print(f"  Centroid: X={cx:.2f}  Y={cy:.2f}  Z={cz:.2f}")
    print(f"  Offset to apply: ({-cx:.2f}, {-cy:.2f}, {-cz:.2f})")

    # ── Process each tile ──
    total_vertices = 0
    t0 = time.time()

    for i, obj_path in enumerate(obj_files):
        tile_name = obj_path.stem
        print(f"\n[{i+1}/{len(obj_files)}] Processing {tile_name}...")

        # Output directory
        out_dir = UNITY_CITYTILES / tile_name
        out_dir.mkdir(parents=True, exist_ok=True)

        # Re-center OBJ
        out_obj = out_dir / obj_path.name
        verts = recenter_obj(obj_path, out_obj, (cx, cy, cz))
        total_vertices += verts
        size_mb = out_obj.stat().st_size / (1024 * 1024)
        print(f"  OBJ: {verts:,} vertices → {out_obj.name} ({size_mb:.1f} MB)")

        # Copy MTL (no changes needed)
        mtl_path = obj_path.with_suffix(".mtl")
        if mtl_path.exists():
            shutil.copy2(mtl_path, out_dir / mtl_path.name)
            print(f"  MTL: {mtl_path.name}")

        # Copy textures (find matching diffuse JPGs)
        for tex in SOURCE_DIR.glob(f"{tile_name}*.jpg"):
            shutil.copy2(tex, out_dir / tex.name)
            print(f"  TEX: {tex.name}")

        # Delete Unity .meta files for the OBJ so Unity reimports
        meta_file = out_dir / f"{obj_path.name}.meta"
        if meta_file.exists():
            meta_file.unlink()
            print(f"  Deleted .meta for reimport")

    elapsed = time.time() - t0
    print(f"\n{'='*60}")
    print(f"Done! {len(obj_files)} tiles, {total_vertices:,} vertices re-centered")
    print(f"Offset applied: X={-cx:.2f}  Y={-cy:.2f}  Z={-cz:.2f}")
    print(f"Time: {elapsed:.1f}s")
    print(f"\nUnity will reimport the OBJ files on next refresh.")
    print(f"Then run: Vibe3D > Place City Tiles")


if __name__ == "__main__":
    main()
