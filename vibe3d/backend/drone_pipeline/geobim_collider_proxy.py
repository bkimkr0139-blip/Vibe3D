"""GeoBIM Collider Proxy Generator — Blender headless mesh decimation.

Section 3.2: Generate low-poly collider meshes for Raycast/NavMesh/Physics.
  - Import OBJ → remove small fragments → Decimate (Collapse) → export FBX
  - Target: 20k~100k triangles per tile
  - Output naming: tile_<x>_<y>_COLLIDER.fbx
"""

import logging
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

from .geobim_models import ColliderProxyResult

logger = logging.getLogger("vibe3d.geobim.collider")

DEFAULT_COLLIDER_PARAMS = {
    "target_triangles": 50000,      # target triangle count per tile
    "decimate_ratio": 0.03,         # fallback ratio if target calc fails
    "min_fragment_area": 1.0,       # m² — remove loose parts below this
    "export_format": "fbx",         # fbx or glb
    "blender_path": "blender",      # path to blender executable
}

# Blender Python script template
_BLENDER_SCRIPT = '''
import bpy
import sys
import json

argv = sys.argv
argv = argv[argv.index("--") + 1:]
params = json.loads(argv[0])

obj_path = params["obj_path"]
out_path = params["out_path"]
decimate_ratio = params["decimate_ratio"]
min_area = params["min_fragment_area"]

# Clear scene
bpy.ops.wm.read_factory_settings(use_empty=True)

# Import OBJ
bpy.ops.wm.obj_import(filepath=obj_path)

# Join all mesh objects
meshes = [o for o in bpy.data.objects if o.type == 'MESH']
if not meshes:
    print("ERROR: No mesh objects found")
    sys.exit(1)

# Select all meshes
bpy.ops.object.select_all(action='DESELECT')
for m in meshes:
    m.select_set(True)
bpy.context.view_layer.objects.active = meshes[0]

# Join
if len(meshes) > 1:
    bpy.ops.object.join()

obj = bpy.context.active_object
original_tris = sum(len(p.vertices) - 2 for p in obj.data.polygons)

# Remove small fragments (loose parts)
bpy.ops.object.mode_set(mode='EDIT')
bpy.ops.mesh.select_all(action='DESELECT')
bpy.ops.mesh.select_loose()
bpy.ops.mesh.delete(type='VERT')
bpy.ops.object.mode_set(mode='OBJECT')

# Separate loose parts and remove small ones
bpy.ops.object.mode_set(mode='EDIT')
bpy.ops.mesh.separate(type='LOOSE')
bpy.ops.object.mode_set(mode='OBJECT')

# Filter by bounding box volume
keep = []
for o in bpy.data.objects:
    if o.type != 'MESH':
        continue
    dims = o.dimensions
    area = dims.x * dims.z  # XZ footprint area
    if area >= min_area:
        keep.append(o)
    else:
        bpy.data.objects.remove(o, do_unlink=True)

# Re-join
if keep:
    bpy.ops.object.select_all(action='DESELECT')
    for o in keep:
        o.select_set(True)
    bpy.context.view_layer.objects.active = keep[0]
    if len(keep) > 1:
        bpy.ops.object.join()

    obj = bpy.context.active_object

    # Decimate
    mod = obj.modifiers.new(name="Decimate", type='DECIMATE')
    mod.decimate_type = 'COLLAPSE'
    mod.ratio = decimate_ratio
    bpy.ops.object.modifier_apply(modifier=mod.name)

    proxy_tris = sum(len(p.vertices) - 2 for p in obj.data.polygons)

    # Export
    if out_path.endswith('.fbx'):
        bpy.ops.export_scene.fbx(filepath=out_path, use_selection=True)
    else:
        bpy.ops.export_scene.gltf(filepath=out_path, export_format='GLB', use_selection=True)

    result = {"original_triangles": original_tris, "proxy_triangles": proxy_tris, "success": True}
else:
    result = {"original_triangles": original_tris, "proxy_triangles": 0, "success": False, "error": "No meshes after filtering"}

print("RESULT:" + json.dumps(result))
'''


class ColliderProxyGenerator:
    """Generates low-poly collider proxies using Blender headless."""

    def __init__(self, params: Optional[dict] = None):
        self.params = {**DEFAULT_COLLIDER_PARAMS, **(params or {})}
        self._blender_available: Optional[bool] = None

    def check_blender(self) -> bool:
        """Check if Blender is available."""
        if self._blender_available is not None:
            return self._blender_available
        try:
            result = subprocess.run(
                [self.params["blender_path"], "--version"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10,
            )
            self._blender_available = result.returncode == 0
            if self._blender_available:
                logger.info(f"Blender found: {result.stdout.strip().split(chr(10))[0]}")
        except (FileNotFoundError, subprocess.TimeoutExpired):
            self._blender_available = False
            logger.warning("Blender not found — collider proxy generation disabled")
        return self._blender_available

    def generate_proxy(self, obj_path: str, output_dir: str) -> ColliderProxyResult:
        """Generate a collider proxy for a single OBJ tile."""
        t0 = time.time()
        obj_p = Path(obj_path)
        tile_name = obj_p.stem

        ext = self.params["export_format"]
        out_name = f"{tile_name}_COLLIDER.{ext}"
        out_path = Path(output_dir) / out_name
        out_path.parent.mkdir(parents=True, exist_ok=True)

        result = ColliderProxyResult(
            tile_name=tile_name,
            input_path=str(obj_p),
            output_path=str(out_path),
        )

        if not self.check_blender():
            # Fallback: copy OBJ as-is (no decimation)
            result.error = "Blender not available — fallback copy"
            result.success = False
            result.processing_time_s = time.time() - t0
            return result

        # Write Blender script to temp file
        script_path = Path(tempfile.gettempdir()) / "geobim_collider_script.py"
        script_path.write_text(_BLENDER_SCRIPT)

        params_json = {
            "obj_path": str(obj_p).replace("\\", "/"),
            "out_path": str(out_path).replace("\\", "/"),
            "decimate_ratio": self.params["decimate_ratio"],
            "min_fragment_area": self.params["min_fragment_area"],
        }

        try:
            proc = subprocess.run(
                [
                    self.params["blender_path"],
                    "--background",
                    "--python", str(script_path),
                    "--", __import__("json").dumps(params_json),
                ],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
            )

            # Parse result from Blender output
            stdout = proc.stdout or ""
            for line in stdout.splitlines():
                if line.startswith("RESULT:"):
                    import json
                    data = json.loads(line[7:])
                    result.original_triangles = data.get("original_triangles", 0)
                    result.proxy_triangles = data.get("proxy_triangles", 0)
                    result.success = data.get("success", False)
                    result.error = data.get("error")
                    if result.original_triangles > 0:
                        result.reduction_ratio = result.proxy_triangles / result.original_triangles
                    break
            else:
                result.error = f"No RESULT output. stderr: {proc.stderr[:500]}"

        except subprocess.TimeoutExpired:
            result.error = "Blender process timed out (300s)"
        except Exception as e:
            result.error = str(e)

        result.processing_time_s = time.time() - t0
        logger.info(
            f"Collider proxy {tile_name}: "
            f"{'OK' if result.success else 'FAIL'} "
            f"({result.original_triangles}→{result.proxy_triangles} tris, "
            f"{result.processing_time_s:.1f}s)"
        )
        return result

    def generate_all(self, tile_folder: str, output_dir: str,
                     progress_callback=None) -> list[ColliderProxyResult]:
        """Generate collider proxies for all OBJ tiles in a folder."""
        folder = Path(tile_folder)
        obj_files = sorted(folder.glob("*.obj"))
        if not obj_files:
            obj_files = sorted(folder.rglob("*.obj"))

        results = []
        for i, obj_path in enumerate(obj_files):
            result = self.generate_proxy(str(obj_path), output_dir)
            results.append(result)
            if progress_callback:
                progress_callback(i + 1, len(obj_files), result)

        return results


# ── Singleton ───────────────────────────────────────────────

_generator: Optional[ColliderProxyGenerator] = None


def get_generator() -> ColliderProxyGenerator:
    global _generator
    if _generator is None:
        _generator = ColliderProxyGenerator()
    return _generator
