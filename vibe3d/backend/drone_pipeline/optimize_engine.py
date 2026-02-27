"""Mesh optimization engine for Drone2Twin pipeline.

Uses Blender CLI (headless) for mesh decimation, hole filling, noise removal,
texture resizing, and GLB export. Falls back to stub mode (file copy + metadata)
when Blender is not installed.
"""

import asyncio
import json
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Callable, Optional

from .. import config
from .models import OptimizeReport, Preset

logger = logging.getLogger(__name__)

# ── LOD presets ──────────────────────────────────────────────

LOD_PRESETS = {
    Preset.PREVIEW: {
        "lod0": 100_000,   # target face count
        "lod1": 30_000,
        "lod2": 10_000,
        "texture_max": 2048,
    },
    Preset.PRODUCTION: {
        "lod0": 300_000,
        "lod1": 80_000,
        "lod2": 20_000,
        "texture_max": 4096,
    },
}

MESH_IMPORT_EXTENSIONS = {".glb", ".gltf", ".fbx", ".obj", ".ply", ".stl", ".dae"}

# ── Blender Python script template ──────────────────────────

BLENDER_OPTIMIZE_SCRIPT = r'''
"""Blender headless mesh optimization script.

Usage: blender --background --python this_script.py -- <input_mesh> <output_dir> <preset_json>
"""
import bpy
import bmesh
import json
import os
import sys
import time

start_time = time.time()

# Parse arguments after '--'
argv = sys.argv[sys.argv.index("--") + 1:]
input_path = argv[0]
output_dir = argv[1]
preset = json.loads(argv[2])

os.makedirs(output_dir, exist_ok=True)

# ── 1. Clear default scene & import mesh ─────────────────
bpy.ops.wm.read_homefile(use_empty=True)

ext = os.path.splitext(input_path)[1].lower()
if ext in (".glb", ".gltf"):
    bpy.ops.import_scene.gltf(filepath=input_path)
elif ext == ".fbx":
    bpy.ops.import_scene.fbx(filepath=input_path)
elif ext == ".obj":
    bpy.ops.wm.obj_import(filepath=input_path)
elif ext in (".ply", ".stl"):
    if ext == ".ply":
        bpy.ops.wm.ply_import(filepath=input_path)
    else:
        bpy.ops.import_mesh.stl(filepath=input_path)
else:
    print(f"ERROR: Unsupported format {ext}")
    sys.exit(1)

# ── 2. Join all mesh objects ─────────────────────────────
mesh_objects = [obj for obj in bpy.data.objects if obj.type == 'MESH']
if not mesh_objects:
    print("ERROR: No mesh objects found after import")
    sys.exit(1)

# Select all mesh objects
bpy.ops.object.select_all(action='DESELECT')
for obj in mesh_objects:
    obj.select_set(True)
bpy.context.view_layer.objects.active = mesh_objects[0]

if len(mesh_objects) > 1:
    bpy.ops.object.join()

active = bpy.context.active_object
original_faces = len(active.data.polygons)
print(f"Input: {original_faces} faces")

# ── 3. Remove noise (small disconnected pieces) ─────────
bm = bmesh.new()
bm.from_mesh(active.data)
bm.verts.ensure_lookup_table()

# Find connected components, remove those with < 100 vertices
# Using linked flat faces as a simple heuristic
removed_verts = 0
islands = []
visited = set()

for v in bm.verts:
    if v.index in visited:
        continue
    island = set()
    stack = [v]
    while stack:
        cv = stack.pop()
        if cv.index in visited:
            continue
        visited.add(cv.index)
        island.add(cv.index)
        for e in cv.link_edges:
            ov = e.other_vert(cv)
            if ov.index not in visited:
                stack.append(ov)
    islands.append(island)

# Remove small islands
noise_threshold = max(100, original_faces // 1000)
for island in islands:
    if len(island) < noise_threshold:
        for vi in island:
            bm.verts.ensure_lookup_table()
            try:
                bm.verts.remove(bm.verts[vi])
            except (IndexError, ReferenceError):
                pass
            removed_verts += 1

bm.to_mesh(active.data)
bm.free()
active.data.update()
print(f"Noise removal: removed {removed_verts} vertices from {len(islands)} islands")

# ── 4. Fill holes ────────────────────────────────────────
bpy.ops.object.mode_set(mode='EDIT')
bpy.ops.mesh.select_all(action='DESELECT')
bpy.ops.mesh.select_non_manifold()
bpy.ops.mesh.fill_holes(sides=8)
bpy.ops.object.mode_set(mode='OBJECT')

# ── 5. Decimate & export LODs ────────────────────────────
report = {
    "input_polycount": original_faces,
    "output_polycounts": {},
    "output_files": [],
    "texture_sizes": [],
    "decimation_ratio": 0.0,
    "warnings": [],
    "blender_available": True,
    "elapsed_seconds": 0.0,
}

current_faces = len(active.data.polygons)

for lod_name in ("lod0", "lod1", "lod2"):
    target = preset[lod_name]
    ratio = min(1.0, target / max(current_faces, 1))

    # Duplicate for this LOD
    bpy.ops.object.select_all(action='DESELECT')
    active.select_set(True)
    bpy.context.view_layer.objects.active = active
    bpy.ops.object.duplicate()
    lod_obj = bpy.context.active_object
    lod_obj.name = f"mesh_{lod_name}"

    if ratio < 1.0:
        mod = lod_obj.modifiers.new(name="Decimate", type='DECIMATE')
        mod.ratio = ratio
        bpy.ops.object.modifier_apply(modifier="Decimate")

    lod_faces = len(lod_obj.data.polygons)
    report["output_polycounts"][lod_name] = lod_faces

    # Export
    out_path = os.path.join(output_dir, f"mesh_{lod_name}.glb")
    bpy.ops.object.select_all(action='DESELECT')
    lod_obj.select_set(True)
    bpy.ops.export_scene.gltf(
        filepath=out_path,
        use_selection=True,
        export_format='GLB',
    )
    report["output_files"].append(out_path)
    print(f"{lod_name}: {lod_faces} faces → {out_path}")

    # Remove duplicate
    bpy.data.objects.remove(lod_obj, do_unlink=True)

# Decimation ratio (LOD0 vs original)
lod0_count = report["output_polycounts"].get("lod0", current_faces)
report["decimation_ratio"] = round(lod0_count / max(original_faces, 1), 3)

# ── 6. Resize textures ──────────────────────────────────
tex_max = preset.get("texture_max", 2048)
for img in bpy.data.images:
    if img.size[0] > tex_max or img.size[1] > tex_max:
        scale = tex_max / max(img.size[0], img.size[1])
        new_w = int(img.size[0] * scale)
        new_h = int(img.size[1] * scale)
        img.scale(new_w, new_h)
        report["texture_sizes"].append(f"{new_w}x{new_h}")
    else:
        report["texture_sizes"].append(f"{img.size[0]}x{img.size[1]}")

# ── 7. Write report ─────────────────────────────────────
report["elapsed_seconds"] = round(time.time() - start_time, 1)
report_path = os.path.join(output_dir, "optimize_report.json")
with open(report_path, "w") as f:
    json.dump(report, f, indent=2)

print(f"Optimization complete in {report['elapsed_seconds']}s")
print(f"Report: {report_path}")
'''


class BlenderOptimizeEngine:
    """Mesh optimization using Blender CLI (headless)."""

    def __init__(self):
        self._blender_path = config.BLENDER_PATH

    @property
    def is_available(self) -> bool:
        """Check if Blender is installed and accessible."""
        return bool(shutil.which(self._blender_path))

    async def optimize(
        self,
        input_mesh: str,
        output_dir: str,
        preset: Preset,
        *,
        progress_cb: Optional[Callable] = None,
    ) -> OptimizeReport:
        """Optimize mesh with LOD generation.

        If Blender is not installed, runs in stub mode:
        copies input file and generates metadata-only report.
        """
        start_time = time.time()
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)

        if not self.is_available:
            return await self._stub_optimize(input_mesh, output_dir, preset, start_time)

        return await self._blender_optimize(input_mesh, output_dir, preset, progress_cb, start_time)

    # ── Stub mode (no Blender) ───────────────────────────────

    async def _stub_optimize(
        self,
        input_mesh: str,
        output_dir: str,
        preset: Preset,
        start_time: float,
    ) -> OptimizeReport:
        """Stub mode: copy files + generate metadata report."""
        logger.warning("Blender not available — running in stub mode (file copy only)")

        inp = Path(input_mesh)
        out = Path(output_dir)

        # Copy input as LOD0
        lod0_name = f"mesh_lod0{inp.suffix}"
        lod0_path = out / lod0_name
        await asyncio.to_thread(shutil.copy2, str(inp), str(lod0_path))

        # Estimate polycount from file size (rough: ~200K faces per MB for GLB)
        size_mb = inp.stat().st_size / (1024 * 1024)
        estimated_faces = int(size_mb * 200_000)

        report = OptimizeReport(
            input_polycount=estimated_faces,
            output_polycounts={"lod0": estimated_faces},
            output_files=[str(lod0_path)],
            blender_available=False,
            elapsed_seconds=round(time.time() - start_time, 1),
            warnings=[
                f"Blender not installed (path: '{self._blender_path}'). "
                "Running in stub mode — input file copied as LOD0 without optimization. "
                "Install Blender and set BLENDER_PATH in .env for full LOD generation.",
                "LOD1/LOD2 not generated — Unity-side SimplifyMesh can be used as fallback.",
            ],
        )

        # Save report
        report_path = out / "optimize_report.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)

        logger.info("Stub optimize complete: %s → %s (%.1f MB)", inp.name, lod0_path, size_mb)
        return report

    # ── Full Blender optimization ────────────────────────────

    async def _blender_optimize(
        self,
        input_mesh: str,
        output_dir: str,
        preset: Preset,
        progress_cb: Optional[Callable],
        start_time: float,
    ) -> OptimizeReport:
        """Run full Blender optimization pipeline."""
        import tempfile

        lod_preset = LOD_PRESETS[preset]
        preset_json = json.dumps(lod_preset)

        # Write Blender script to temp file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8",
        ) as f:
            f.write(BLENDER_OPTIMIZE_SCRIPT)
            script_path = f.name

        try:
            if progress_cb:
                await progress_cb("optimization", 0.1)

            logger.info("Running Blender optimization: %s → %s (preset: %s)", input_mesh, output_dir, preset.value)

            proc = await asyncio.create_subprocess_exec(
                self._blender_path, "--background", "--python", script_path,
                "--", input_mesh, output_dir, preset_json,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=1800)  # 30min timeout

            if proc.returncode != 0:
                err_msg = stderr.decode("utf-8", errors="replace")[:500]
                logger.error("Blender failed (rc=%d): %s", proc.returncode, err_msg)
                return OptimizeReport(
                    blender_available=True,
                    elapsed_seconds=round(time.time() - start_time, 1),
                    warnings=[f"Blender exited with code {proc.returncode}: {err_msg}"],
                )

            if progress_cb:
                await progress_cb("optimization", 0.9)

            # Read report generated by Blender script
            report_path = Path(output_dir) / "optimize_report.json"
            if report_path.exists():
                with open(report_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                report = OptimizeReport(**data)
            else:
                report = OptimizeReport(
                    blender_available=True,
                    elapsed_seconds=round(time.time() - start_time, 1),
                    warnings=["Blender completed but no report file generated"],
                )

            if progress_cb:
                await progress_cb("optimization", 1.0)

            logger.info("Blender optimization complete in %.1fs", report.elapsed_seconds)
            return report

        finally:
            # Clean up temp script
            try:
                os.unlink(script_path)
            except OSError:
                pass
