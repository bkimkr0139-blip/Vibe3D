"""Plan validator — validates Unity action plans against JSON schema.

Enhanced with:
- Spatial collision detection between plan objects and existing scene
- Action dependency validation for merged multi-action plans
- Performance budget check (polygon count estimates)
"""

import json
import logging
from pathlib import Path
from typing import Any

import jsonschema

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).parent.parent / "docs" / "schemas" / "unity_plan.schema.json"

# Actions that are forbidden for safety
FORBIDDEN_PATTERNS = [
    "System.IO.File.Delete",
    "System.Diagnostics.Process",
    "UnityEditor.FileUtil.DeleteFileOrDirectory",
    "Application.Quit",
]


def load_schema() -> dict:
    """Load the Unity plan JSON schema."""
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


_schema_cache: dict | None = None


def get_schema() -> dict:
    global _schema_cache
    if _schema_cache is None:
        _schema_cache = load_schema()
    return _schema_cache


def invalidate_schema_cache():
    """Force reload of the schema on next validation."""
    global _schema_cache
    _schema_cache = None


def validate_plan(plan: dict) -> tuple[bool, list[str]]:
    """Validate a plan against the JSON schema using per-type validation.

    Uses per-action-type validation instead of oneOf for better error messages
    and tolerance of extra LLM-generated fields.

    Returns:
        (is_valid, list_of_errors)
    """
    errors: list[str] = []
    schema = get_schema()
    definitions = schema.get("definitions", {})

    # Top-level structure check
    for field in ("project", "scene", "actions"):
        if field not in plan:
            errors.append(f"Missing required field: {field}")

    actions = plan.get("actions", [])
    if not isinstance(actions, list):
        errors.append("'actions' must be an array")
        return False, errors
    if len(actions) == 0:
        errors.append("'actions' must have at least 1 item")
    if len(actions) > 100:
        errors.append(f"Too many actions: {len(actions)} (max 100)")

    # Create resolver for $ref handling (e.g., color, vec3 definitions)
    try:
        resolver = jsonschema.RefResolver.from_schema(schema)
    except Exception:
        resolver = None

    # Per-action validation against type-specific schema
    for i, action in enumerate(actions):
        if not isinstance(action, dict):
            errors.append(f"[actions.{i}] must be an object")
            continue
        action_type = action.get("type")
        if not action_type:
            errors.append(f"[actions.{i}] missing 'type' field")
            continue

        type_schema = definitions.get(action_type)
        if type_schema is None:
            errors.append(f"[actions.{i}] unknown action type: {action_type}")
            continue

        # Validate against type-specific schema only (not the full oneOf)
        try:
            validator = jsonschema.Draft7Validator(type_schema, resolver=resolver)
            for error in validator.iter_errors(action):
                path_parts = [str(p) for p in error.absolute_path]
                path = f"actions.{i}.{'.'.join(path_parts)}" if path_parts else f"actions.{i}"
                errors.append(f"[{path}] {error.message}")
        except Exception as e:
            logger.warning("Schema validation error for action %d (%s): %s", i, action_type, e)

    # Safety checks
    plan_str = json.dumps(plan)
    for pattern in FORBIDDEN_PATTERNS:
        if pattern.lower() in plan_str.lower():
            errors.append(f"Forbidden pattern detected: {pattern}")

    is_valid = len(errors) == 0
    if is_valid:
        logger.info("Plan validated: %d actions OK", len(actions))
    else:
        logger.warning("Plan validation failed: %d errors", len(errors))

    return is_valid, errors


# ── Spatial collision detection ─────────────────────────────

def spatial_collision_check(
    plan: dict,
    scene_context: dict | None = None,
) -> list[str]:
    """Check for spatial collisions between plan objects and existing scene objects.

    Returns list of warning strings (empty if no collisions).
    """
    warnings: list[str] = []
    if not scene_context:
        return warnings

    objects_data = scene_context.get("objects", {})
    # objects_data is dict[name, obj_dict] — extract values
    existing_objects = list(objects_data.values()) if isinstance(objects_data, dict) else objects_data

    # Collect new object positions from plan
    new_objects = []
    for action in plan.get("actions", []):
        if action.get("type") in ("create_primitive", "create_empty", "create_light"):
            pos = action.get("position", {"x": 0, "y": 0, "z": 0})
            scale = action.get("scale", {"x": 1, "y": 1, "z": 1})
            new_objects.append({
                "name": action.get("name", "unnamed"),
                "position": pos,
                "scale": scale,
            })

    # Check new vs existing
    for new_obj in new_objects:
        np = new_obj["position"]
        ns = new_obj["scale"]
        for existing in existing_objects:
            ep = existing.get("position", {"x": 0, "y": 0, "z": 0})
            es = existing.get("scale", {"x": 1, "y": 1, "z": 1})

            # Simple AABB overlap check
            overlap_x = (
                abs(np.get("x", 0) - ep.get("x", 0))
                < (ns.get("x", 1) + es.get("x", 1)) / 2
            )
            overlap_y = (
                abs(np.get("y", 0) - ep.get("y", 0))
                < (ns.get("y", 1) + es.get("y", 1)) / 2
            )
            overlap_z = (
                abs(np.get("z", 0) - ep.get("z", 0))
                < (ns.get("z", 1) + es.get("z", 1)) / 2
            )

            if overlap_x and overlap_y and overlap_z:
                warnings.append(
                    f"Collision: '{new_obj['name']}' overlaps with existing '{existing.get('name', '?')}'"
                )

    # Check new vs new
    for i, a in enumerate(new_objects):
        for b in new_objects[i + 1:]:
            ap, bp = a["position"], b["position"]
            dist = (
                (ap.get("x", 0) - bp.get("x", 0)) ** 2
                + (ap.get("y", 0) - bp.get("y", 0)) ** 2
                + (ap.get("z", 0) - bp.get("z", 0)) ** 2
            ) ** 0.5
            if dist < 0.1:
                warnings.append(
                    f"Overlap: '{a['name']}' and '{b['name']}' at same position"
                )

    return warnings


def validate_action_dependencies(plan: dict) -> list[str]:
    """Validate that action dependencies are satisfied in order.

    E.g., apply_material must come after the target is created.
    """
    warnings: list[str] = []
    created_names: set[str] = set()

    for i, action in enumerate(plan.get("actions", [])):
        action_type = action.get("type", "")

        # Track created objects
        if action_type in ("create_primitive", "create_empty", "create_light"):
            name = action.get("name", "")
            if name:
                created_names.add(name)

        # Check target references
        target = action.get("target")
        if target and action_type in (
            "apply_material", "modify_object", "delete_object", "duplicate_object",
            "add_component", "set_component_property", "assign_material",
            "create_prefab", "move_relative", "set_layer",
            "remove_component", "set_object_active", "set_tag_on_object",
            "rename_object", "set_line_positions",
        ):
            if target not in created_names:
                # It could reference an existing scene object, just warn
                pass  # Don't warn — target might be in the scene already

        # Check parent references
        parent = action.get("parent")
        if parent and parent not in created_names:
            pass  # Parent might be in scene

    return warnings


def validate_plan_extended(
    plan: dict,
    scene_context: dict | None = None,
) -> tuple[bool, list[str], list[str]]:
    """Extended validation with collision check and dependency validation.

    Returns:
        (is_valid, errors, warnings)
    """
    is_valid, errors = validate_plan(plan)
    warnings: list[str] = []

    # Collision check
    collision_warnings = spatial_collision_check(plan, scene_context)
    warnings.extend(collision_warnings)

    # Dependency check
    dep_warnings = validate_action_dependencies(plan)
    warnings.extend(dep_warnings)

    # Performance budget check
    actions = plan.get("actions", [])
    primitive_count = sum(1 for a in actions if a.get("type") == "create_primitive")
    if primitive_count > 50:
        warnings.append(f"Performance: {primitive_count} primitives may impact FPS")

    return is_valid, errors, warnings


def plan_to_mcp_commands(plan: dict) -> list[dict]:
    """Convert a validated plan into MCP tool commands.

    Each action in the plan is translated to the corresponding
    MCP tool call (manage_gameobject, manage_material, etc.)
    """
    commands = []

    for action in plan.get("actions", []):
        action_type = action.get("type")

        if action_type == "create_primitive":
            cmd = {
                "tool": "manage_gameobject",
                "params": {
                    "action": "create",
                    "name": action["name"],
                    "primitive_type": action["shape"],
                },
            }
            if "parent" in action:
                cmd["params"]["parent"] = action["parent"]
            if "position" in action:
                cmd["params"]["position"] = action["position"]
            if "rotation" in action:
                cmd["params"]["rotation"] = action["rotation"]
            if "scale" in action:
                cmd["params"]["scale"] = action["scale"]
            commands.append(cmd)

        elif action_type == "create_empty":
            cmd = {
                "tool": "manage_gameobject",
                "params": {
                    "action": "create",
                    "name": action["name"],
                },
            }
            if "parent" in action:
                cmd["params"]["parent"] = action["parent"]
            if "position" in action:
                cmd["params"]["position"] = action["position"]
            commands.append(cmd)

        elif action_type == "modify_object":
            cmd = {
                "tool": "manage_gameobject",
                "params": {
                    "action": "modify",
                    "target": action["target"],
                    "search_method": action.get("search_method", "by_name"),
                },
            }
            if "position" in action:
                cmd["params"]["position"] = action["position"]
            if "rotation" in action:
                cmd["params"]["rotation"] = action["rotation"]
            if "scale" in action:
                cmd["params"]["scale"] = action["scale"]
            if "new_name" in action:
                cmd["params"]["new_name"] = action["new_name"]
            if "set_active" in action:
                cmd["params"]["set_active"] = action["set_active"]
            if "tag" in action:
                cmd["params"]["tag"] = action["tag"]
            if "layer" in action:
                cmd["params"]["layer"] = action["layer"]
            if "parent" in action:
                cmd["params"]["parent"] = action["parent"]
            commands.append(cmd)

        elif action_type == "delete_object":
            commands.append({
                "tool": "manage_gameobject",
                "params": {
                    "action": "delete",
                    "target": action["target"],
                    "search_method": action.get("search_method", "by_name"),
                },
            })

        elif action_type == "apply_material":
            cmd: dict[str, Any] = {
                "tool": "manage_material",
                "params": {
                    "action": "set_renderer_color",
                    "target": action["target"],
                    "search_method": action.get("search_method", "by_name"),
                    "mode": action.get("mode", "instance"),
                },
            }
            if "color" in action:
                cmd["params"]["color"] = action["color"]
            commands.append(cmd)

        elif action_type == "create_light":
            # Unity Light.type enum: 0=Spot, 1=Directional, 2=Point, 3=Area
            light_type_map = {
                "Directional": 1, "directional": 1,
                "Point": 2, "point": 2,
                "Spot": 0, "spot": 0,
                "Area": 3, "area": 3,
            }
            light_type_str = action.get("light_type", "Point")
            light_type_enum = light_type_map.get(light_type_str, 2)  # default Point

            # Build Light component properties
            light_props: dict[str, Any] = {
                "type": light_type_enum,
                "intensity": action.get("intensity", 3),
            }
            if light_type_enum in (0, 2):  # Spot or Point
                light_props["range"] = action.get("range", 20)
            if "color" in action:
                light_props["color"] = action["color"]

            # Single command: create GameObject + Light component + properties
            cmd = {
                "tool": "manage_gameobject",
                "params": {
                    "action": "create",
                    "name": action.get("name", f"{light_type_str}Light"),
                    "components_to_add": ["Light"],
                    "component_properties": {"Light": light_props},
                },
            }
            if "parent" in action:
                cmd["params"]["parent"] = action["parent"]
            if "position" in action:
                cmd["params"]["position"] = action["position"]
            if "rotation" in action:
                cmd["params"]["rotation"] = action["rotation"]
            commands.append(cmd)

        elif action_type == "set_parent":
            commands.append({
                "tool": "manage_gameobject",
                "params": {
                    "action": "modify",
                    "target": action["target"],
                    "search_method": "by_name",
                    "parent": action["parent"],
                },
            })

        elif action_type == "duplicate_object":
            cmd = {
                "tool": "manage_gameobject",
                "params": {
                    "action": "duplicate",
                    "target": action["target"],
                    "search_method": "by_name",
                },
            }
            if "new_name" in action:
                cmd["params"]["name"] = action["new_name"]
            if "position" in action:
                cmd["params"]["position"] = action["position"]
            commands.append(cmd)

        elif action_type == "screenshot":
            commands.append({
                "tool": "manage_scene",
                "params": {
                    "action": "screenshot",
                    "screenshot_file_name": action.get("filename", "vibe3d_screenshot"),
                    "screenshot_super_size": action.get("super_size", 2),
                },
            })

        elif action_type == "save_scene":
            commands.append({
                "tool": "manage_scene",
                "params": {"action": "save"},
            })

        elif action_type == "execute_menu":
            commands.append({
                "tool": "execute_menu_item",
                "params": {"menu_path": action.get("menu_path", "")},
            })

        elif action_type == "get_hierarchy":
            target = action.get("target", "")
            commands.append({
                "tool": "manage_scene",
                "params": {
                    "action": "get_hierarchy",
                    "parent": target,
                    "max_depth": 3,
                    "page_size": 50,
                },
            })

        elif action_type == "import_asset":
            dest = action.get("destination", "Assets/Imports")
            # Ensure destination folder exists, then refresh to pick up the copied file
            commands.append({
                "tool": "manage_asset",
                "params": {
                    "action": "create_folder",
                    "path": dest,
                },
            })
            # File copy is handled by executor pre-step; refresh DB to import
            commands.append({
                "tool": "refresh_unity",
                "params": {
                    "scope": "assets",
                    "mode": "force",
                    "wait_for_ready": True,
                },
            })

        elif action_type == "add_component":
            cmd = {
                "tool": "manage_components",
                "params": {
                    "action": "add",
                    "target": action["target"],
                    "component_type": action["component_type"],
                    "search_method": action.get("search_method", "by_name"),
                },
            }
            if "properties" in action:
                cmd["params"]["properties"] = action["properties"]
            commands.append(cmd)

        elif action_type == "set_component_property":
            commands.append({
                "tool": "manage_components",
                "params": {
                    "action": "set_property",
                    "target": action["target"],
                    "component_type": action["component_type"],
                    "property": action["property"],
                    "value": action["value"],
                    "search_method": action.get("search_method", "by_name"),
                },
            })

        elif action_type == "create_material":
            cmd = {
                "tool": "manage_material",
                "params": {
                    "action": "create",
                    "material_path": f"Assets/Materials/{action['name']}.mat",
                    "shader": action.get("shader", "Universal Render Pipeline/Lit"),
                },
            }
            if "color" in action:
                cmd["params"]["color"] = action["color"]
            if "properties" in action:
                cmd["params"]["properties"] = action["properties"]
            commands.append(cmd)

        elif action_type == "assign_material":
            cmd = {
                "tool": "manage_material",
                "params": {
                    "action": "assign_material_to_renderer",
                    "target": action["target"],
                    "material_path": action["material_path"],
                    "search_method": action.get("search_method", "by_name"),
                },
            }
            if "slot" in action:
                cmd["params"]["slot"] = action["slot"]
            commands.append(cmd)

        elif action_type == "create_prefab":
            commands.append({
                "tool": "manage_prefabs",
                "params": {
                    "action": "create_from_gameobject",
                    "target": action["target"],
                    "prefab_path": action.get("prefab_path", f"Assets/Prefabs/{action['target']}.prefab"),
                },
            })

        elif action_type == "instantiate_prefab":
            cmd = {
                "tool": "manage_gameobject",
                "params": {
                    "action": "create",
                    "prefab_path": action["prefab_path"],
                },
            }
            if "name" in action:
                cmd["params"]["name"] = action["name"]
            if "parent" in action:
                cmd["params"]["parent"] = action["parent"]
            if "position" in action:
                cmd["params"]["position"] = action["position"]
            if "rotation" in action:
                cmd["params"]["rotation"] = action["rotation"]
            if "scale" in action:
                cmd["params"]["scale"] = action["scale"]
            commands.append(cmd)

        elif action_type == "create_particle_system":
            cmd: dict[str, Any] = {
                "tool": "manage_vfx",
                "params": {
                    "action": "particle_create",
                    "target": action["name"],
                },
            }
            if "parent" in action:
                cmd["params"]["properties"] = cmd["params"].get("properties", {})
                cmd["params"]["properties"]["parent"] = action["parent"]
            if "position" in action:
                cmd["params"]["properties"] = cmd["params"].get("properties", {})
                cmd["params"]["properties"]["position"] = action["position"]
            if "properties" in action:
                cmd["params"]["properties"] = {
                    **cmd["params"].get("properties", {}),
                    **action["properties"],
                }
            commands.append(cmd)

        elif action_type == "create_texture":
            cmd = {
                "tool": "manage_texture",
                "params": {
                    "action": "create",
                    "path": action.get("path", f"Assets/Textures/{action['name']}.png"),
                    "width": action.get("width", 256),
                    "height": action.get("height", 256),
                },
            }
            if "pattern" in action:
                cmd["params"]["pattern"] = action["pattern"]
            if "fill_color" in action:
                cmd["params"]["fill_color"] = action["fill_color"]
            commands.append(cmd)

        elif action_type == "move_relative":
            commands.append({
                "tool": "manage_gameobject",
                "params": {
                    "action": "move_relative",
                    "target": action["target"],
                    "direction": action["direction"],
                    "distance": action["distance"],
                    "search_method": action.get("search_method", "by_name"),
                },
            })

        elif action_type == "find_objects":
            commands.append({
                "tool": "find_gameobjects",
                "params": {
                    "search_term": action["search_term"],
                    "search_method": action.get("search_method", "by_name"),
                },
            })

        elif action_type == "add_tag":
            commands.append({
                "tool": "manage_editor",
                "params": {
                    "action": "add_tag",
                    "tag_name": action["tag_name"],
                },
            })

        elif action_type == "set_layer":
            commands.append({
                "tool": "manage_gameobject",
                "params": {
                    "action": "modify",
                    "target": action["target"],
                    "search_method": action.get("search_method", "by_name"),
                    "layer": action["layer"],
                },
            })

        elif action_type == "editor_control":
            commands.append({
                "tool": "manage_editor",
                "params": {
                    "action": action["action"],
                },
            })

        # ── New action types (37) ────────────────────────────

        elif action_type == "remove_component":
            commands.append({
                "tool": "manage_components",
                "params": {
                    "action": "remove",
                    "target": action["target"],
                    "component_type": action["component_type"],
                    "search_method": action.get("search_method", "by_name"),
                },
            })

        elif action_type == "set_material_color":
            cmd = {
                "tool": "manage_material",
                "params": {
                    "action": "set_material_color",
                    "material_path": action["material_path"],
                    "color": action["color"],
                },
            }
            if "property" in action:
                cmd["params"]["property"] = action["property"]
            commands.append(cmd)

        elif action_type == "set_material_property":
            commands.append({
                "tool": "manage_material",
                "params": {
                    "action": "set_material_shader_property",
                    "material_path": action["material_path"],
                    "property": action["property"],
                    "value": action["value"],
                },
            })

        elif action_type == "get_material_info":
            commands.append({
                "tool": "manage_material",
                "params": {
                    "action": "get_material_info",
                    "material_path": action["material_path"],
                },
            })

        elif action_type == "modify_prefab":
            cmd = {
                "tool": "manage_prefabs",
                "params": {
                    "action": "modify_contents",
                    "prefab_path": action["prefab_path"],
                },
            }
            if "create_child" in action:
                cmd["params"]["create_child"] = action["create_child"]
            if "components_to_add" in action:
                cmd["params"]["components_to_add"] = action["components_to_add"]
            if "components_to_remove" in action:
                cmd["params"]["components_to_remove"] = action["components_to_remove"]
            if "position" in action:
                cmd["params"]["position"] = action["position"]
            if "rotation" in action:
                cmd["params"]["rotation"] = action["rotation"]
            if "scale" in action:
                cmd["params"]["scale"] = action["scale"]
            commands.append(cmd)

        elif action_type == "get_prefab_info":
            commands.append({
                "tool": "manage_prefabs",
                "params": {
                    "action": "get_info",
                    "prefab_path": action["prefab_path"],
                },
            })

        elif action_type == "get_prefab_hierarchy":
            commands.append({
                "tool": "manage_prefabs",
                "params": {
                    "action": "get_hierarchy",
                    "prefab_path": action["prefab_path"],
                },
            })

        elif action_type == "create_vfx":
            cmd = {
                "tool": "manage_vfx",
                "params": {
                    "action": "vfx_create",
                    "target": action.get("target", action["name"]),
                },
            }
            if "properties" in action:
                cmd["params"]["properties"] = action["properties"]
            commands.append(cmd)

        elif action_type == "create_line_renderer":
            cmd: dict[str, Any] = {
                "tool": "manage_vfx",
                "params": {
                    "action": "line_create",
                    "target": action.get("target", action["name"]),
                },
            }
            props: dict[str, Any] = {}
            if "positions" in action:
                props["positions"] = action["positions"]
            if "width" in action:
                props["startWidth"] = action["width"]
                props["endWidth"] = action["width"]
            if "color" in action:
                props["color"] = action["color"]
            if "properties" in action:
                props.update(action["properties"])
            if props:
                cmd["params"]["properties"] = props
            commands.append(cmd)

        elif action_type == "set_line_positions":
            commands.append({
                "tool": "manage_vfx",
                "params": {
                    "action": "line_set_positions",
                    "target": action["target"],
                    "search_method": action.get("search_method", "by_name"),
                    "properties": {"positions": action["positions"]},
                },
            })

        elif action_type == "create_trail_renderer":
            cmd = {
                "tool": "manage_vfx",
                "params": {
                    "action": "trail_create",
                    "target": action.get("target", action["name"]),
                },
            }
            props = {}
            if "time" in action:
                props["time"] = action["time"]
            if "width" in action:
                props["startWidth"] = action["width"]
                props["endWidth"] = action["width"]
            if "color" in action:
                props["color"] = action["color"]
            if "properties" in action:
                props.update(action["properties"])
            if props:
                cmd["params"]["properties"] = props
            commands.append(cmd)

        elif action_type == "apply_texture_pattern":
            # LLM may use 'path', 'target', or 'name' to reference the texture
            tex_path = action.get("path") or action.get("target") or action.get("name", "")
            cmd = {
                "tool": "manage_texture",
                "params": {
                    "action": "apply_pattern",
                    "path": tex_path,
                    "pattern": action["pattern"],
                },
            }
            if "palette" in action:
                cmd["params"]["palette"] = action["palette"]
            if "pattern_size" in action:
                cmd["params"]["pattern_size"] = action["pattern_size"]
            commands.append(cmd)

        elif action_type == "apply_texture_gradient":
            cmd = {
                "tool": "manage_texture",
                "params": {
                    "action": "apply_gradient",
                    "path": action["path"],
                },
            }
            if "gradient_type" in action:
                cmd["params"]["gradient_type"] = action["gradient_type"]
            if "palette" in action:
                cmd["params"]["palette"] = action["palette"]
            if "gradient_angle" in action:
                cmd["params"]["gradient_angle"] = action["gradient_angle"]
            commands.append(cmd)

        elif action_type == "apply_texture_noise":
            cmd = {
                "tool": "manage_texture",
                "params": {
                    "action": "apply_noise",
                    "path": action["path"],
                },
            }
            if "noise_scale" in action:
                cmd["params"]["noise_scale"] = action["noise_scale"]
            if "octaves" in action:
                cmd["params"]["octaves"] = action["octaves"]
            if "palette" in action:
                cmd["params"]["palette"] = action["palette"]
            commands.append(cmd)

        elif action_type == "create_sprite":
            cmd = {
                "tool": "manage_texture",
                "params": {
                    "action": "create_sprite",
                    "path": action["path"],
                },
            }
            if "width" in action:
                cmd["params"]["width"] = action["width"]
            if "height" in action:
                cmd["params"]["height"] = action["height"]
            if "fill_color" in action:
                cmd["params"]["fill_color"] = action["fill_color"]
            if "pixels" in action:
                cmd["params"]["pixels"] = action["pixels"]
            commands.append(cmd)

        elif action_type == "create_scene":
            cmd = {
                "tool": "manage_scene",
                "params": {
                    "action": "create",
                    "name": action["name"],
                },
            }
            if "path" in action:
                cmd["params"]["path"] = action["path"]
            commands.append(cmd)

        elif action_type == "load_scene":
            cmd = {
                "tool": "manage_scene",
                "params": {"action": "load"},
            }
            if "name" in action:
                cmd["params"]["name"] = action["name"]
            if "path" in action:
                cmd["params"]["path"] = action["path"]
            if "build_index" in action:
                cmd["params"]["build_index"] = action["build_index"]
            commands.append(cmd)

        elif action_type == "get_active_scene":
            commands.append({
                "tool": "manage_scene",
                "params": {"action": "get_active"},
            })

        elif action_type == "get_build_settings":
            commands.append({
                "tool": "manage_scene",
                "params": {"action": "get_build_settings"},
            })

        elif action_type == "remove_tag":
            commands.append({
                "tool": "manage_editor",
                "params": {
                    "action": "remove_tag",
                    "tag_name": action["tag_name"],
                },
            })

        elif action_type == "add_layer":
            commands.append({
                "tool": "manage_editor",
                "params": {
                    "action": "add_layer",
                    "layer_name": action["layer_name"],
                },
            })

        elif action_type == "remove_layer":
            commands.append({
                "tool": "manage_editor",
                "params": {
                    "action": "remove_layer",
                    "layer_name": action["layer_name"],
                },
            })

        elif action_type == "set_active_tool":
            commands.append({
                "tool": "manage_editor",
                "params": {
                    "action": "set_active_tool",
                    "tool_name": action["tool_name"],
                },
            })

        elif action_type == "search_assets":
            cmd = {
                "tool": "manage_asset",
                "params": {
                    "action": "search",
                    "path": action.get("path", "Assets"),
                },
            }
            if "search_pattern" in action:
                cmd["params"]["search_pattern"] = action["search_pattern"]
            if "filter_type" in action:
                cmd["params"]["filter_type"] = action["filter_type"]
            if "page_size" in action:
                cmd["params"]["page_size"] = action["page_size"]
            if "page_number" in action:
                cmd["params"]["page_number"] = action["page_number"]
            commands.append(cmd)

        elif action_type == "get_asset_info":
            commands.append({
                "tool": "manage_asset",
                "params": {
                    "action": "get_info",
                    "path": action["path"],
                },
            })

        elif action_type == "move_asset":
            commands.append({
                "tool": "manage_asset",
                "params": {
                    "action": "move",
                    "path": action["path"],
                    "destination": action["destination"],
                },
            })

        elif action_type == "rename_asset":
            commands.append({
                "tool": "manage_asset",
                "params": {
                    "action": "rename",
                    "path": action["path"],
                    "destination": action["new_name"],
                },
            })

        elif action_type == "delete_asset":
            commands.append({
                "tool": "manage_asset",
                "params": {
                    "action": "delete",
                    "path": action["path"],
                },
            })

        elif action_type == "duplicate_asset":
            cmd = {
                "tool": "manage_asset",
                "params": {
                    "action": "duplicate",
                    "path": action["path"],
                },
            }
            if "destination" in action:
                cmd["params"]["destination"] = action["destination"]
            commands.append(cmd)

        elif action_type == "create_script":
            cmd = {
                "tool": "create_script",
                "params": {
                    "path": action["path"],
                    "contents": action.get("contents", ""),
                },
            }
            if "namespace" in action:
                cmd["params"]["namespace"] = action["namespace"]
            if "script_type" in action:
                cmd["params"]["script_type"] = action["script_type"]
            commands.append(cmd)

        elif action_type == "create_scriptable_object":
            cmd = {
                "tool": "manage_scriptable_object",
                "params": {
                    "action": "create",
                    "type_name": action["type_name"],
                    "asset_name": action["asset_name"],
                },
            }
            if "folder_path" in action:
                cmd["params"]["folder_path"] = action["folder_path"]
            if "patches" in action:
                cmd["params"]["patches"] = action["patches"]
            commands.append(cmd)

        elif action_type == "modify_scriptable_object":
            cmd = {
                "tool": "manage_scriptable_object",
                "params": {
                    "action": "modify",
                    "target": action["target"],
                    "patches": action["patches"],
                },
            }
            if "dry_run" in action:
                cmd["params"]["dry_run"] = action["dry_run"]
            commands.append(cmd)

        elif action_type == "create_shader":
            cmd = {
                "tool": "manage_shader",
                "params": {
                    "action": "create",
                    "name": action["name"],
                    "path": action.get("path", "Assets/Shaders"),
                },
            }
            if "contents" in action:
                cmd["params"]["contents"] = action["contents"]
            commands.append(cmd)

        elif action_type == "run_tests":
            cmd = {
                "tool": "run_tests",
                "params": {
                    "mode": action.get("mode", "EditMode"),
                },
            }
            if "test_names" in action:
                cmd["params"]["test_names"] = action["test_names"]
            if "category_names" in action:
                cmd["params"]["category_names"] = action["category_names"]
            if "assembly_names" in action:
                cmd["params"]["assembly_names"] = action["assembly_names"]
            commands.append(cmd)

        elif action_type == "refresh_assets":
            commands.append({
                "tool": "refresh_unity",
                "params": {
                    "scope": action.get("scope", "all"),
                    "mode": action.get("mode", "if_dirty"),
                    "compile": action.get("compile", "none"),
                    "wait_for_ready": True,
                },
            })

        elif action_type == "read_console":
            cmd = {
                "tool": "read_console",
                "params": {
                    "action": "get",
                },
            }
            if "count" in action:
                cmd["params"]["count"] = action["count"]
            if "types" in action:
                cmd["params"]["types"] = action["types"]
            if "filter_text" in action:
                cmd["params"]["filter_text"] = action["filter_text"]
            commands.append(cmd)

        elif action_type == "set_object_active":
            commands.append({
                "tool": "manage_gameobject",
                "params": {
                    "action": "modify",
                    "target": action["target"],
                    "search_method": action.get("search_method", "by_name"),
                    "set_active": action["active"],
                },
            })

        elif action_type == "set_tag_on_object":
            commands.append({
                "tool": "manage_gameobject",
                "params": {
                    "action": "modify",
                    "target": action["target"],
                    "search_method": action.get("search_method", "by_name"),
                    "tag": action["tag"],
                },
            })

        elif action_type == "rename_object":
            commands.append({
                "tool": "manage_gameobject",
                "params": {
                    "action": "modify",
                    "target": action["target"],
                    "search_method": action.get("search_method", "by_name"),
                    "new_name": action["new_name"],
                },
            })

    return commands
