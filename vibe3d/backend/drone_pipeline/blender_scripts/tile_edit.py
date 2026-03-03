"""
tile_edit.py — Blender headless script for tile mesh editing.
Runs inside Blender: blender --background --python tile_edit.py -- '{"preset":...}'
No project imports — standalone script using bpy API.
"""

import sys
import os
import json
import math
import time

try:
    import bpy
    import bmesh
    from mathutils import Vector
except ImportError:
    print("RESULT:" + json.dumps({"success": False, "error": "Not running inside Blender"}))
    sys.exit(1)


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

def clear_scene():
    """Remove all objects from Blender scene."""
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    for c in bpy.data.collections:
        bpy.data.collections.remove(c)


def get_mesh_stats(obj):
    """Return triangle/vertex counts for a mesh object."""
    if obj is None or obj.type != 'MESH':
        return {"triangles": 0, "vertices": 0}
    mesh = obj.data
    mesh.calc_loop_triangles()
    return {
        "triangles": len(mesh.loop_triangles),
        "vertices": len(mesh.vertices),
        "materials": len(mesh.materials),
    }


def get_all_mesh_stats():
    """Aggregate stats across all mesh objects in scene."""
    total_tris = 0
    total_verts = 0
    total_mats = 0
    for obj in bpy.data.objects:
        if obj.type == 'MESH':
            s = get_mesh_stats(obj)
            total_tris += s["triangles"]
            total_verts += s["vertices"]
            total_mats += s["materials"]
    return {"triangles": total_tris, "vertices": total_verts, "materials": total_mats}


def join_all_meshes():
    """Join all mesh objects into a single object."""
    meshes = [o for o in bpy.data.objects if o.type == 'MESH']
    if len(meshes) <= 1:
        return meshes[0] if meshes else None

    bpy.ops.object.select_all(action='DESELECT')
    for o in meshes:
        o.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    bpy.ops.object.join()
    return bpy.context.active_object


# ═══════════════════════════════════════════════════════════════
# Import
# ═══════════════════════════════════════════════════════════════

def import_tile(path):
    """Import OBJ or FBX tile into an empty scene."""
    clear_scene()
    ext = os.path.splitext(path)[1].lower()
    if ext == ".obj":
        bpy.ops.wm.obj_import(filepath=path)
    elif ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=path)
    elif ext == ".glb" or ext == ".gltf":
        bpy.ops.import_scene.gltf(filepath=path)
    else:
        raise ValueError(f"Unsupported format: {ext}")

    # Ensure we're in object mode
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')

    return get_all_mesh_stats()


# ═══════════════════════════════════════════════════════════════
# Cleanup — remove noise / small fragments
# ═══════════════════════════════════════════════════════════════

def cleanup_noise(min_fragment_area=0.5, remove_degenerate=True):
    """Separate loose parts, delete fragments below area threshold."""
    removed_count = 0

    for obj in list(bpy.data.objects):
        if obj.type != 'MESH':
            continue

        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)

        # Separate by loose parts
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        if remove_degenerate:
            bpy.ops.mesh.dissolve_degenerate(threshold=0.0001)
            bpy.ops.mesh.delete_loose(use_verts=True, use_edges=True, use_faces=False)
        bpy.ops.object.mode_set(mode='OBJECT')

        # Separate loose parts into individual objects
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        try:
            bpy.ops.mesh.separate(type='LOOSE')
        except RuntimeError:
            pass  # May fail if only one part

    # Now evaluate all mesh objects by bounding box volume / surface area
    to_delete = []
    for obj in list(bpy.data.objects):
        if obj.type != 'MESH':
            continue
        dims = obj.dimensions
        approx_area = dims.x * dims.z  # top-down footprint area
        if approx_area < min_fragment_area and len(obj.data.vertices) < 100:
            to_delete.append(obj)

    for obj in to_delete:
        bpy.data.objects.remove(obj, do_unlink=True)
        removed_count += 1

    # Re-join remaining parts
    join_all_meshes()

    return {"removed_fragments": removed_count}


# ═══════════════════════════════════════════════════════════════
# Tile boundary preservation
# ═══════════════════════════════════════════════════════════════

def detect_boundary_vertices(obj, tolerance=0.1):
    """Find vertices at tile edges (min/max X or Z within tolerance).
    Returns a vertex group named 'TileBoundary'."""
    if obj is None or obj.type != 'MESH':
        return 0

    mesh = obj.data
    verts = mesh.vertices

    if len(verts) == 0:
        return 0

    # Find bounding box
    xs = [v.co.x for v in verts]
    zs = [v.co.z for v in verts]
    min_x, max_x = min(xs), max(xs)
    min_z, max_z = min(zs), max(zs)

    # Create vertex group
    vg = obj.vertex_groups.new(name="TileBoundary")

    boundary_indices = []
    for v in verts:
        on_edge = (
            abs(v.co.x - min_x) < tolerance or
            abs(v.co.x - max_x) < tolerance or
            abs(v.co.z - min_z) < tolerance or
            abs(v.co.z - max_z) < tolerance
        )
        if on_edge:
            boundary_indices.append(v.index)

    if boundary_indices:
        vg.add(boundary_indices, 1.0, 'REPLACE')

    return len(boundary_indices)


# ═══════════════════════════════════════════════════════════════
# Decimate
# ═══════════════════════════════════════════════════════════════

def decimate_to_target(target_triangles, preserve_boundaries=True):
    """Apply Decimate modifier to reach target triangle count."""
    obj = join_all_meshes()
    if obj is None:
        return {"triangles": 0}

    obj.data.calc_loop_triangles()
    current_tris = len(obj.data.loop_triangles)

    if current_tris <= target_triangles:
        return {"triangles": current_tris, "ratio": 1.0, "skipped": True}

    ratio = target_triangles / max(current_tris, 1)

    # Pin boundary vertices if requested
    boundary_count = 0
    if preserve_boundaries:
        boundary_count = detect_boundary_vertices(obj)
        snapshot_boundary_vertices(obj)  # save for seam risk check

    bpy.context.view_layer.objects.active = obj
    mod = obj.modifiers.new(name="Decimate", type='DECIMATE')
    mod.decimate_type = 'COLLAPSE'
    mod.ratio = max(ratio, 0.01)

    if preserve_boundaries and boundary_count > 0:
        mod.vertex_group = "TileBoundary"
        mod.invert_vertex_group = True  # protect boundary verts

    bpy.ops.object.modifier_apply(modifier=mod.name)

    obj.data.calc_loop_triangles()
    result_tris = len(obj.data.loop_triangles)

    return {
        "triangles": result_tris,
        "ratio": round(ratio, 4),
        "boundary_verts_pinned": boundary_count,
    }


# ═══════════════════════════════════════════════════════════════
# Generate LODs
# ═══════════════════════════════════════════════════════════════

def generate_lods(ratios=None):
    """Generate LOD variants by progressive decimation from original."""
    if ratios is None:
        ratios = [1.0, 0.4, 0.15]

    obj = join_all_meshes()
    if obj is None:
        return {"lods": []}

    obj.name = "tile_LOD0"
    obj.data.calc_loop_triangles()
    base_tris = len(obj.data.loop_triangles)

    lod_stats = [{"level": 0, "triangles": base_tris, "ratio": 1.0}]

    for i, ratio in enumerate(ratios[1:], start=1):
        # Duplicate original for each LOD level
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.duplicate()
        lod_obj = bpy.context.active_object
        lod_obj.name = f"tile_LOD{i}"

        # Apply decimate
        mod = lod_obj.modifiers.new(name="Decimate", type='DECIMATE')
        mod.decimate_type = 'COLLAPSE'
        mod.ratio = max(ratio, 0.01)
        bpy.ops.object.modifier_apply(modifier=mod.name)

        lod_obj.data.calc_loop_triangles()
        lod_tris = len(lod_obj.data.loop_triangles)

        lod_stats.append({
            "level": i,
            "triangles": lod_tris,
            "ratio": round(ratio, 4),
        })

    return {"lods": lod_stats}


# ═══════════════════════════════════════════════════════════════
# Collider Proxy
# ═══════════════════════════════════════════════════════════════

def generate_collider_proxy(target_triangles=50000, min_fragment_area=1.0):
    """Create simplified collider proxy mesh from LOD0."""
    # Find LOD0 or main object
    src_obj = bpy.data.objects.get("tile_LOD0")
    if src_obj is None:
        for o in bpy.data.objects:
            if o.type == 'MESH':
                src_obj = o
                break
    if src_obj is None:
        return {"triangles": 0}

    # Duplicate for collider
    bpy.ops.object.select_all(action='DESELECT')
    src_obj.select_set(True)
    bpy.context.view_layer.objects.active = src_obj
    bpy.ops.object.duplicate()
    col_obj = bpy.context.active_object
    col_obj.name = "tile_COLLIDER"

    # Remove materials (not needed for collider)
    col_obj.data.materials.clear()

    col_obj.data.calc_loop_triangles()
    current_tris = len(col_obj.data.loop_triangles)

    if current_tris > target_triangles:
        ratio = target_triangles / max(current_tris, 1)
        mod = col_obj.modifiers.new(name="Decimate", type='DECIMATE')
        mod.decimate_type = 'COLLAPSE'
        mod.ratio = max(ratio, 0.01)

        # Pin boundaries
        boundary_count = detect_boundary_vertices(col_obj)
        if boundary_count > 0:
            mod.vertex_group = "TileBoundary"
            mod.invert_vertex_group = True

        bpy.ops.object.modifier_apply(modifier=mod.name)

    col_obj.data.calc_loop_triangles()
    result_tris = len(col_obj.data.loop_triangles)

    return {"triangles": result_tris}


# ═══════════════════════════════════════════════════════════════
# Export
# ═══════════════════════════════════════════════════════════════

def export_results(output_dir, export_format="fbx"):
    """Export each named object (tile_LOD0, tile_LOD1, tile_LOD2, tile_COLLIDER)
    as individual files."""
    os.makedirs(output_dir, exist_ok=True)

    exported_files = {}
    total_size = 0

    for obj in bpy.data.objects:
        if obj.type != 'MESH':
            continue
        if not obj.name.startswith("tile_"):
            continue

        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj

        filename = f"{obj.name}.{export_format}"
        filepath = os.path.join(output_dir, filename)

        if export_format == "fbx":
            bpy.ops.export_scene.fbx(
                filepath=filepath,
                use_selection=True,
                apply_scale_options='FBX_SCALE_ALL',
                axis_forward='-Z',
                axis_up='Y',
                mesh_smooth_type='FACE',
            )
        elif export_format == "obj":
            bpy.ops.wm.obj_export(
                filepath=filepath,
                export_selected_objects=True,
                forward_axis='NEGATIVE_Z',
                up_axis='Y',
            )
        elif export_format == "glb":
            bpy.ops.export_scene.gltf(
                filepath=filepath,
                use_selection=True,
                export_format='GLB',
            )

        if os.path.exists(filepath):
            fsize = os.path.getsize(filepath)
            total_size += fsize
            # Determine file type from name
            key = obj.name.replace("tile_", "")  # LOD0, LOD1, LOD2, COLLIDER
            exported_files[key] = {"filename": filename, "size_bytes": fsize}

    return {"files": exported_files, "total_size_bytes": total_size}


# ═══════════════════════════════════════════════════════════════
# Tile seam risk check
# ═══════════════════════════════════════════════════════════════

_boundary_snapshot = {}  # saved before decimation for comparison


def snapshot_boundary_vertices(obj=None):
    """Save boundary vertex positions before editing for later seam risk check.
    Call this AFTER detect_boundary_vertices() but BEFORE decimation."""
    global _boundary_snapshot
    _boundary_snapshot = {}

    if obj is None:
        for o in bpy.data.objects:
            if o.type == 'MESH':
                obj = o
                break
    if obj is None or obj.type != 'MESH':
        return

    vg = obj.vertex_groups.get("TileBoundary")
    if vg is None:
        return

    vg_idx = vg.index
    mesh = obj.data
    positions = {}
    for v in mesh.vertices:
        for g in v.groups:
            if g.group == vg_idx and g.weight > 0.5:
                positions[v.index] = (v.co.x, v.co.y, v.co.z)
                break

    _boundary_snapshot = positions


def check_seam_risk(tolerance=0.3):
    """Check if boundary vertices were displaced beyond tolerance.

    Compares current boundary vertex positions against the pre-edit snapshot.
    If no snapshot exists, samples boundary vertices and checks for gaps/holes
    at tile edges.

    Returns:
        dict with seam_risk (bool), max_displacement, avg_displacement,
        displaced_count, boundary_vertex_count.
    """
    global _boundary_snapshot

    obj = bpy.data.objects.get("tile_LOD0")
    if obj is None:
        return {"seam_risk": False, "reason": "no_LOD0_object"}

    vg = obj.vertex_groups.get("TileBoundary")
    if vg is None:
        return {"seam_risk": False, "reason": "no_boundary_group"}

    vg_idx = vg.index
    mesh = obj.data

    # Collect current boundary vertex positions
    current = {}
    for v in mesh.vertices:
        for g in v.groups:
            if g.group == vg_idx and g.weight > 0.5:
                current[v.index] = (v.co.x, v.co.y, v.co.z)
                break

    boundary_count = len(current)

    # If we have a pre-edit snapshot, compute displacement
    if _boundary_snapshot:
        displacements = []
        max_disp = 0.0

        # Match vertices by proximity (indices may change after decimation)
        snap_positions = list(_boundary_snapshot.values())
        for cur_pos in current.values():
            # Find closest snapshot vertex
            min_dist = float('inf')
            for snap_pos in snap_positions:
                dx = cur_pos[0] - snap_pos[0]
                dy = cur_pos[1] - snap_pos[1]
                dz = cur_pos[2] - snap_pos[2]
                dist = (dx*dx + dy*dy + dz*dz) ** 0.5
                if dist < min_dist:
                    min_dist = dist
            displacements.append(min_dist)
            if min_dist > max_disp:
                max_disp = min_dist

        avg_disp = sum(displacements) / max(1, len(displacements))
        displaced = sum(1 for d in displacements if d > tolerance)

        return {
            "seam_risk": max_disp > tolerance,
            "max_displacement": round(max_disp, 4),
            "avg_displacement": round(avg_disp, 4),
            "displaced_count": displaced,
            "boundary_vertex_count": boundary_count,
            "snapshot_vertex_count": len(_boundary_snapshot),
            "tolerance": tolerance,
        }
    else:
        # No snapshot — do edge continuity check instead
        # Sample boundary at tile edges and check for height gaps
        xs = [p[0] for p in current.values()]
        zs = [p[2] for p in current.values()]
        if not xs:
            return {"seam_risk": False, "reason": "no_boundary_vertices"}

        min_x, max_x = min(xs), max(xs)
        min_z, max_z = min(zs), max(zs)

        # Check each edge for height variance (large variance = potential seam)
        edge_tol = (max_x - min_x) * 0.01  # 1% of tile width
        edges = {
            "min_x": [p[1] for p in current.values() if abs(p[0] - min_x) < edge_tol],
            "max_x": [p[1] for p in current.values() if abs(p[0] - max_x) < edge_tol],
            "min_z": [p[1] for p in current.values() if abs(p[2] - min_z) < edge_tol],
            "max_z": [p[1] for p in current.values() if abs(p[2] - max_z) < edge_tol],
        }

        max_height_var = 0.0
        for name, heights in edges.items():
            if len(heights) >= 2:
                var = max(heights) - min(heights)
                if var > max_height_var:
                    max_height_var = var

        return {
            "seam_risk": max_height_var > tolerance * 5,
            "max_edge_height_variance": round(max_height_var, 4),
            "boundary_vertex_count": boundary_count,
            "tolerance": tolerance,
        }


# ═══════════════════════════════════════════════════════════════
# Preset orchestration
# ═══════════════════════════════════════════════════════════════

def run_preset(preset, params, input_path, output_dir):
    """Route to the appropriate sequence of operations based on preset."""
    results = {"preset": preset, "stages": {}}

    # Stage 1: Import
    import_stats = import_tile(input_path)
    results["input_stats"] = import_stats
    results["stages"]["import"] = {"status": "ok"}

    if preset == "clean_noise":
        # Import → Cleanup → Export
        cleanup_result = cleanup_noise(
            min_fragment_area=params.get("min_fragment_area", 0.5),
            remove_degenerate=params.get("remove_degenerate", True),
        )
        results["stages"]["cleanup"] = cleanup_result
        # Rename main object for export
        for o in bpy.data.objects:
            if o.type == 'MESH':
                o.name = "tile_LOD0"
                break

    elif preset == "decimate_to_target":
        # Import → Cleanup → Decimate → Export
        cleanup_noise(min_fragment_area=0.1)
        dec_result = decimate_to_target(
            target_triangles=params.get("target_triangles", 100000),
            preserve_boundaries=params.get("preserve_boundaries", True),
        )
        results["stages"]["decimate"] = dec_result
        # Rename for export
        for o in bpy.data.objects:
            if o.type == 'MESH':
                o.name = "tile_LOD0"
                break

    elif preset == "generate_lods":
        # Import → Cleanup → LODs → Export
        cleanup_noise(min_fragment_area=0.1)
        join_all_meshes()
        lod_result = generate_lods(
            ratios=params.get("lod_ratios", [1.0, 0.4, 0.15]),
        )
        results["stages"]["lods"] = lod_result

    elif preset == "generate_collider_proxy":
        # Import → Cleanup → Collider → Export
        cleanup_noise(min_fragment_area=params.get("min_fragment_area", 1.0))
        join_all_meshes()
        for o in bpy.data.objects:
            if o.type == 'MESH':
                o.name = "tile_LOD0"
                break
        col_result = generate_collider_proxy(
            target_triangles=params.get("target_triangles", 50000),
        )
        results["stages"]["collider"] = col_result

    elif preset == "pack_for_unity":
        # Import → Cleanup → Decimate LOD0 → LODs → Collider → Export
        cleanup_noise(
            min_fragment_area=params.get("min_fragment_area", 0.5),
        )
        results["stages"]["cleanup"] = {"status": "ok"}

        target_lod0 = params.get("target_triangles_lod0", 600000)
        dec_result = decimate_to_target(
            target_triangles=target_lod0,
            preserve_boundaries=params.get("preserve_boundaries", True),
        )
        results["stages"]["decimate"] = dec_result

        lod_result = generate_lods(
            ratios=params.get("lod_ratios", [1.0, 0.35, 0.10]),
        )
        results["stages"]["lods"] = lod_result

        col_result = generate_collider_proxy(
            target_triangles=params.get("collider_target_triangles", 50000),
        )
        results["stages"]["collider"] = col_result

    else:
        results["error"] = f"Unknown preset: {preset}"
        results["success"] = False
        return results

    # Export all tile_* objects
    export_result = export_results(
        output_dir,
        export_format=params.get("export_format", "fbx"),
    )
    results["stages"]["export"] = export_result

    # Collect final stats
    results["output_stats"] = get_all_mesh_stats()
    results["quality_flags"] = check_seam_risk()
    results["success"] = True

    return results


# ═══════════════════════════════════════════════════════════════
# Main entry point
# ═══════════════════════════════════════════════════════════════

def main():
    # Parse params from argv after "--"
    argv = sys.argv
    params_json = "{}"
    if "--" in argv:
        idx = argv.index("--")
        if idx + 1 < len(argv):
            params_json = argv[idx + 1]

    try:
        params = json.loads(params_json)
    except json.JSONDecodeError as e:
        print("RESULT:" + json.dumps({"success": False, "error": f"Invalid JSON params: {e}"}))
        sys.exit(1)

    preset = params.get("preset", "pack_for_unity")
    input_path = params.get("input_path", "")
    output_dir = params.get("output_dir", "/tmp/tile_edit_out")
    edit_params = params.get("params", {})

    if not input_path or not os.path.exists(input_path):
        print("RESULT:" + json.dumps({
            "success": False,
            "error": f"Input file not found: {input_path}",
        }))
        sys.exit(1)

    t0 = time.time()
    try:
        result = run_preset(preset, edit_params, input_path, output_dir)
        result["duration_s"] = round(time.time() - t0, 2)
    except Exception as e:
        result = {
            "success": False,
            "error": str(e),
            "duration_s": round(time.time() - t0, 2),
        }

    print("RESULT:" + json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
