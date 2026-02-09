"""Plan generator — converts natural language commands to Unity action plans.

Supports two modes:
1. Template-based: pattern matching for common commands (no API key needed)
2. Claude API: uses Anthropic API for complex natural language understanding

Enhanced with:
- Multi-action command parsing (split by ";", "그리고", "and")
- Scene context injection for spatial reasoning
- Intent disambiguation detection
- Spatial reference resolution ("옆에", "위에" → coordinates)
"""

import json
import logging
import math
import re
from typing import Optional

from . import config

logger = logging.getLogger(__name__)

# ── System prompt for Claude ────────────────────────────────

SYSTEM_PROMPT = """You are a Unity 3D scene builder assistant. Given a natural language command,
you must output ONLY a valid JSON action plan. No explanations, no markdown, just JSON.

The plan must follow this structure:
{
  "project": "My project",
  "scene": "bio-plants",
  "description": "brief description of what the plan does",
  "actions": [ ... ]
}

Available action types (63):

--- Basic Object Operations ---
- create_primitive: {"type":"create_primitive", "shape":"Cube|Sphere|Cylinder|Capsule|Plane|Quad", "name":"...", "parent":"...", "position":{"x":0,"y":0,"z":0}, "rotation":{"x":0,"y":0,"z":0}, "scale":{"x":1,"y":1,"z":1}}
- create_empty: {"type":"create_empty", "name":"...", "parent":"...", "position":{"x":0,"y":0,"z":0}}
- create_light: {"type":"create_light", "light_type":"Directional|Point|Spot|Area", "name":"...", "position":{...}, "rotation":{...}, "intensity":1.0}
- modify_object: {"type":"modify_object", "target":"Name", "search_method":"by_name", "position":{...}, "rotation":{...}, "scale":{...}, "new_name":"...", "set_active":true, "tag":"...", "layer":"...", "parent":"..."}
- delete_object: {"type":"delete_object", "target":"Name", "search_method":"by_name"}
- duplicate_object: {"type":"duplicate_object", "target":"Name", "new_name":"...", "position":{...}}
- set_parent: {"type":"set_parent", "target":"Child", "parent":"Parent"}
- move_relative: {"type":"move_relative", "target":"Name", "direction":"left|right|up|down|forward|back", "distance":3.0}
- find_objects: {"type":"find_objects", "search_term":"Tank", "search_method":"by_name|by_tag|by_layer|by_component"}
- set_object_active: {"type":"set_object_active", "target":"Name", "active":true|false}
- set_tag_on_object: {"type":"set_tag_on_object", "target":"Name", "tag":"Vessel"}
- rename_object: {"type":"rename_object", "target":"OldName", "new_name":"NewName"}

--- Material & Color ---
- apply_material: {"type":"apply_material", "target":"Name", "color":{"r":0.5,"g":0.5,"b":0.5,"a":1.0}}
- create_material: {"type":"create_material", "name":"Steel", "shader":"Universal Render Pipeline/Lit", "color":{"r":0.75,"g":0.75,"b":0.78,"a":1.0}}
- assign_material: {"type":"assign_material", "target":"Name", "material_path":"Assets/Materials/Steel.mat", "slot":0}
- set_material_color: {"type":"set_material_color", "material_path":"Assets/Materials/Steel.mat", "color":{"r":1,"g":0,"b":0,"a":1}, "property":"_BaseColor"}
- set_material_property: {"type":"set_material_property", "material_path":"Assets/Materials/M.mat", "property":"_Metallic", "value":0.9}
- get_material_info: {"type":"get_material_info", "material_path":"Assets/Materials/M.mat"}

--- Components & Physics ---
- add_component: {"type":"add_component", "target":"Name", "component_type":"Rigidbody", "properties":{"mass":100,"useGravity":true}}
- remove_component: {"type":"remove_component", "target":"Name", "component_type":"Rigidbody"}
- set_component_property: {"type":"set_component_property", "target":"Name", "component_type":"Rigidbody", "property":"mass", "value":50}

--- Prefabs ---
- create_prefab: {"type":"create_prefab", "target":"Name", "prefab_path":"Assets/Prefabs/Name.prefab"}
- instantiate_prefab: {"type":"instantiate_prefab", "prefab_path":"Assets/Prefabs/Tank.prefab", "name":"Tank_Instance", "position":{...}}
- modify_prefab: {"type":"modify_prefab", "prefab_path":"Assets/Prefabs/P.prefab", "create_child":{"name":"Sub","primitive_type":"Sphere","position":[0,1,0]}}
- get_prefab_info: {"type":"get_prefab_info", "prefab_path":"Assets/Prefabs/P.prefab"}
- get_prefab_hierarchy: {"type":"get_prefab_hierarchy", "prefab_path":"Assets/Prefabs/P.prefab"}

--- VFX ---
- create_particle_system: {"type":"create_particle_system", "name":"Smoke", "position":{...}, "properties":{"startSize":0.5}}
- create_vfx: {"type":"create_vfx", "name":"SparkVFX", "properties":{}}
- create_line_renderer: {"type":"create_line_renderer", "name":"Pipe_Line", "positions":[{"x":0,"y":0,"z":0},{"x":5,"y":0,"z":0}], "width":0.1, "color":{"r":1,"g":1,"b":1,"a":1}}
- set_line_positions: {"type":"set_line_positions", "target":"Pipe_Line", "positions":[{"x":0,"y":0,"z":0},{"x":10,"y":0,"z":0}]}
- create_trail_renderer: {"type":"create_trail_renderer", "name":"Trail_0", "time":2.0, "width":0.5}

--- Textures ---
- create_texture: {"type":"create_texture", "name":"CheckerTex", "width":256, "height":256, "pattern":"checkerboard"}
- apply_texture_pattern: {"type":"apply_texture_pattern", "path":"Assets/Textures/T.png", "pattern":"checkerboard|stripes|dots|grid|brick", "pattern_size":16}
- apply_texture_gradient: {"type":"apply_texture_gradient", "path":"Assets/Textures/T.png", "gradient_type":"linear|radial", "gradient_angle":45}
- apply_texture_noise: {"type":"apply_texture_noise", "path":"Assets/Textures/T.png", "noise_scale":10.0, "octaves":4}
- create_sprite: {"type":"create_sprite", "path":"Assets/Sprites/S.png", "width":64, "height":64, "fill_color":{"r":1,"g":0,"b":0,"a":1}}

--- Scene Management ---
- screenshot: {"type":"screenshot", "filename":"my_shot", "super_size":2}
- save_scene: {"type":"save_scene"}
- create_scene: {"type":"create_scene", "name":"NewScene", "path":"Assets/Scenes/NewScene.unity"}
- load_scene: {"type":"load_scene", "name":"bio-plants", "path":"Assets/Scenes/bio-plants.unity"}
- get_hierarchy: {"type":"get_hierarchy", "target":"ParentName"}
- get_active_scene: {"type":"get_active_scene"}
- get_build_settings: {"type":"get_build_settings"}

--- Asset Management ---
- import_asset: {"type":"import_asset", "source_path":"C:/path/file.fbx", "destination":"Assets/Models"}
- search_assets: {"type":"search_assets", "path":"Assets", "search_pattern":"*.mat", "filter_type":"Material"}
- get_asset_info: {"type":"get_asset_info", "path":"Assets/Materials/Steel.mat"}
- move_asset: {"type":"move_asset", "path":"Assets/Old/M.mat", "destination":"Assets/New/M.mat"}
- rename_asset: {"type":"rename_asset", "path":"Assets/Materials/Old.mat", "new_name":"New.mat"}
- delete_asset: {"type":"delete_asset", "path":"Assets/Materials/Unused.mat"}
- duplicate_asset: {"type":"duplicate_asset", "path":"Assets/Prefabs/Tank.prefab", "destination":"Assets/Prefabs/Tank_Copy.prefab"}

--- Editor & Tags & Layers ---
- editor_control: {"type":"editor_control", "action":"play|pause|stop"}
- add_tag: {"type":"add_tag", "tag_name":"Vessel"}
- remove_tag: {"type":"remove_tag", "tag_name":"Vessel"}
- add_layer: {"type":"add_layer", "layer_name":"Water"}
- remove_layer: {"type":"remove_layer", "layer_name":"Water"}
- set_layer: {"type":"set_layer", "target":"Name", "layer":"Water"}
- set_active_tool: {"type":"set_active_tool", "tool_name":"Move|Rotate|Scale|Rect|Transform"}
- execute_menu: {"type":"execute_menu", "menu_path":"Fermentation/Build Complete Facility"}

--- Scripting & Code ---
- create_script: {"type":"create_script", "name":"MyScript", "path":"Assets/Scripts/MyScript.cs", "contents":"using UnityEngine;..."}
- create_shader: {"type":"create_shader", "name":"MyShader", "path":"Assets/Shaders", "contents":"Shader \\"Custom/MyShader\\" {...}"}
- create_scriptable_object: {"type":"create_scriptable_object", "type_name":"MyData", "asset_name":"Data1", "folder_path":"Assets/Data"}
- modify_scriptable_object: {"type":"modify_scriptable_object", "target":"Assets/Data/Data1.asset", "patches":[{"path":"fieldName","value":42}]}

--- Testing & Utilities ---
- run_tests: {"type":"run_tests", "mode":"EditMode|PlayMode", "test_names":["MyTest"]}
- refresh_assets: {"type":"refresh_assets", "scope":"all|assets|scripts", "mode":"if_dirty|force", "compile":"none|request"}
- read_console: {"type":"read_console", "count":10, "types":["error","warning"], "filter_text":"NullRef"}

Rules:
- Unity uses left-handed Y-up coordinate system
- Default unit is meters
- Colors are 0-1 range (not 0-255)
- Positions default to (0,0,0) if not specified
- Scale defaults to (1,1,1) if not specified
- Maximum 100 actions per plan
- Always include descriptive object names
- Use "parent" to organize objects hierarchically
- For physics, use add_component with Rigidbody + Collider (MeshCollider or BoxCollider)
- For material creation, use "Universal Render Pipeline/Lit" as default shader
- For line renderers, provide positions array for the path points
- For prefab editing, use modify_prefab with create_child to add children
- Use refresh_assets after creating scripts or modifying assets outside Unity
- Use read_console to check for compilation errors after script changes

Common material presets (as RGB 0-1):
- Concrete gray: (0.6, 0.6, 0.6)
- Steel/Metal: (0.75, 0.75, 0.78)
- Stainless steel: (0.8, 0.82, 0.85)
- Copper: (0.72, 0.45, 0.2)
- Wood: (0.55, 0.35, 0.17)
- Glass (blue tint): (0.7, 0.85, 0.95, 0.3)
- Red: (0.8, 0.15, 0.15)
- Green: (0.15, 0.65, 0.15)
- Blue: (0.2, 0.4, 0.8)
- White: (0.95, 0.95, 0.95)
"""

# ── Template patterns ────────────────────────────────────────

FLOOR_PATTERN = re.compile(
    r"(?:가로|width)\s*(\d+(?:\.\d+)?)\s*m?\s*(?:세로|height|depth)\s*(\d+(?:\.\d+)?)\s*m?\s*바닥|"
    r"(\d+(?:\.\d+)?)\s*[mx×]\s*(\d+(?:\.\d+)?)\s*(?:m\s*)?바닥|"
    r"(\d+(?:\.\d+)?)\s*m?\s*[x×]\s*(\d+(?:\.\d+)?)\s*m?\s*(?:바닥|floor)|"
    # English: "create a 10 by 5 floor", "make a 10m by 5m floor"
    r"(\d+(?:\.\d+)?)\s*m?\s*(?:by)\s*(\d+(?:\.\d+)?)\s*m?\s*(?:바닥|floor)",
    re.IGNORECASE,
)

CUBE_PATTERN = re.compile(
    r"큐브|cube|박스|box|상자",
    re.IGNORECASE,
)

SPHERE_PATTERN = re.compile(
    r"구(?:를|을|가|\s|,|\(|$)|sphere|공(?:을|를|가|\s|,|\(|$)",
    re.IGNORECASE,
)

CYLINDER_PATTERN = re.compile(
    r"실린더|cylinder|원기둥|탱크|tank",
    re.IGNORECASE,
)

POSITION_PATTERN = re.compile(
    r"\(?\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\)?",
)

CAPSULE_PATTERN = re.compile(
    r"캡슐|capsule|파이프|pipe",
    re.IGNORECASE,
)

LIGHT_PATTERN = re.compile(
    r"조명|light|라이트|불",
    re.IGNORECASE,
)

DELETE_ALL_PATTERN = re.compile(
    r"(?:모두|모든|전부|전체|다|all)\s*(?:오브젝트|객체|물체|object)?\s*(?:를?\s*)?(?:삭제|지워|제거|delete|remove|clear)",
    re.IGNORECASE,
)

DELETE_PATTERN = re.compile(
    r"(?:삭제|지워|제거|delete|remove)\s+(?:해줘\s+)?([\w가-힣]+)"
    r"|"
    r"([\w가-힣]+)\s*(?:을|를)?\s*(?:삭제|지워|제거|delete|remove)(?:\s*해줘)?",
    re.IGNORECASE,
)

# English creation pattern: "create a red cube at (0,1,0) named MyCube"
ENGLISH_CREATE_PATTERN = re.compile(
    r"(?:create|make|place|add|spawn)\s+(?:a\s+)?(?:(?:new|big|small|large|tiny)\s+)?"
    r"(?:(\w+)\s+)?"  # optional color/adjective
    r"(cube|sphere|cylinder|capsule|box|ball|plane)"
    r"(?:\s+(?:at|to)\s+(?:the\s+)?(?:origin|center|\(?\s*-?\d+(?:\.\d+)?\s*,\s*-?\d+(?:\.\d+)?\s*,\s*-?\d+(?:\.\d+)?\s*\)?))?"
    r"(?:\s+(?:named|called|name)\s+([\w]+))?",
    re.IGNORECASE,
)

ENGLISH_SHAPE_MAP = {
    "cube": "Cube", "box": "Cube",
    "sphere": "Sphere", "ball": "Sphere",
    "cylinder": "Cylinder",
    "capsule": "Capsule",
    "plane": "Plane",
}

DUPLICATE_PATTERN = re.compile(
    r"(?:복제|복사|클론|duplicate|copy|clone)\s+(?:해줘\s+)?([\w가-힣]+)"
    r"|"
    r"([\w가-힣]+)\s*(?:을|를)?\s*(?:복제|복사|클론|duplicate|copy|clone)(?:\s*해줘)?",
    re.IGNORECASE,
)

RENAME_PATTERN = re.compile(
    r"([\w가-힣]+)\s*(?:을|를)?\s*(?:이름을?\s*)?(?:으로|로)?\s*([\w가-힣]+)\s*(?:으로|로)\s*(?:변경|바꿔|rename)",
    re.IGNORECASE,
)

MOVE_PATTERN = re.compile(
    r"(?:이동|옮기|move)\s+(?:해줘\s+)?([\w가-힣]+)\s+(?:을|를)?\s*(?:위치|to)?\s*\(?\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\)?"
    r"|"
    r"([\w가-힣]+)\s*(?:을|를)?\s*\(?\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\)?\s*(?:으로|로)?\s*(?:이동|옮기|move)(?:\s*해줘)?"
    r"|"
    # English: "move Tank_A to (1,2,3)", "place Tank_A at (1,2,3)"
    r"(?:move|place)\s+([\w]+)\s+(?:to|at)\s+\(?\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\)?",
    re.IGNORECASE,
)

COLOR_CHANGE_PATTERN = re.compile(
    # Alt 1: "Floor 색상 스테인리스 변경", "Floor 색상을 스테인리스로 변경"
    r"([\w가-힣]+)\s*(?:을|를|의|에)?\s*(?:색상|색|재질|color)\s*(?:을|를)?\s*([\w가-힣]+)\s*(?:으로|로)?\s*(?:변경|바꿔|적용|change)?"
    r"|"
    # Alt 2: "Floor에 스테인리스 재질 적용해줘", "Floor를 스테인리스 색으로 변경"
    r"([\w가-힣]+)\s*(?:에)?\s*([\w가-힣]+)\s+(?:재질|색상|색)\s*(?:으로|로)?\s*(?:을|를)?\s*(?:적용|변경|바꿔)(?:\s*해줘)?"
    r"|"
    # Alt 3: "Floor를 스테인리스로 변경", "Floor에 스테인리스 적용" (no 색상/색/재질 keyword)
    r"([\w가-힣]+)\s*(?:을|를|에)?\s*([\w가-힣]+)\s*(?:으로|로)\s*(?:변경|바꿔|적용|change)(?:\s*해줘)?"
    r"|"
    # Alt 4 (English): "set Tank_A color to red", "change Floor color to stainless"
    r"(?:set|change)\s+([\w]+)\s+color\s+(?:to\s+)?(red|blue|green|gray|grey|white|black|gold|copper|wood|concrete|stainless|steel|metal)"
    r"|"
    # Alt 5 (English): "make Tank_A red", "paint Floor blue" — exclude articles
    r"(?:make|paint)\s+(?!a\b|an\b|the\b)([\w]+)\s+(red|blue|green|gray|grey|white|black|gold|copper|wood|concrete|stainless|steel|metal)\s*$",
    re.IGNORECASE,
)

SCALE_PATTERN = re.compile(
    r"(?:크기|스케일|scale)\s+(?:를?\s*)?([\w가-힣]+)\s+(?:을|를)?\s*\(?\s*(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)\s*\)?",
    re.IGNORECASE,
)

SCREENSHOT_PATTERN = re.compile(
    r"스크린샷|screenshot|캡처|capture",
    re.IGNORECASE,
)

SAVE_PATTERN = re.compile(
    r"씬\s*저장|씬\s*세이브|save\s*scene|저장",
    re.IGNORECASE,
)

MENU_EXECUTE_PATTERN = re.compile(
    r"(.+?)\s*메뉴\s*(?:를?\s*)?(?:실행|execute|run)(?:\s*해줘)?"
    r"|"
    # English: "execute menu Fermentation/Build", "run menu Fermentation/Build Complete Facility"
    r"(?:execute|run)\s+menu\s+(.+)",
    re.IGNORECASE,
)

HIERARCHY_PATTERN = re.compile(
    r"([\w가-힣/]+)\s*(?:의?\s*)?(?:하위\s*구조|하위|자식|children|child|hierarchy)\s*(?:(?:을|를)?\s*)?(?:보여|show|확인|조회)",
    re.IGNORECASE,
)

IMPORT_PATTERN = re.compile(
    r"(?:import|임포트|가져오기|가져와)\s+([\w.\-/\\]+)\s+(?:from|에서)\s+(.+?)(?:\s*$)"
    r"|"
    r"(.+?)\s+(?:에서|from)\s+([\w.\-/\\]+)\s*(?:를?\s*)?(?:import|임포트|가져오기|가져와)(?:\s*해줘)?",
    re.IGNORECASE,
)

WALL_PATTERN = re.compile(
    r"벽|wall",
    re.IGNORECASE,
)

GRID_PATTERN = re.compile(
    r"(?:그리드|grid|격자|배열)\s*(\d+)\s*[x×]\s*(\d+)",
    re.IGNORECASE,
)

PARENT_PATTERN = re.compile(
    r"(?:부모|parent)\s*(?:를?\s*)?(?:로?\s*)?([\w가-힣]+)",
    re.IGNORECASE,
)

# ── New advanced patterns ────────────────────────────────────

COMPONENT_PATTERN = re.compile(
    r"([\w가-힣]+)\s*(?:에|에게|한테)?\s*(?:Rigidbody|리지드바디|BoxCollider|박스콜라이더|SphereCollider|MeshCollider|"
    r"CapsuleCollider|AudioSource|오디오|Light|라이트|Camera|카메라)\s*(?:를?\s*)?(?:추가|넣|add|attach)",
    re.IGNORECASE,
)

COMPONENT_EXTRACT = re.compile(
    r"(Rigidbody|BoxCollider|SphereCollider|MeshCollider|CapsuleCollider|AudioSource|Light|Camera)",
    re.IGNORECASE,
)

PHYSICS_PATTERN = re.compile(
    r"([\w가-힣]+)\s*(?:에|한테)?\s*(?:물리|physics|rigidbody)\s*(?:를?\s*)?(?:적용|추가|넣|apply|add)",
    re.IGNORECASE,
)

RELATIVE_MOVE_PATTERN = re.compile(
    r"([\w가-힣]+)\s*(?:을|를)?\s*(?:왼쪽|오른쪽|위|아래|앞|뒤|left|right|up|down|forward|back)\s*(?:으로|로)?\s*(\d+(?:\.\d+)?)\s*m?\s*(?:이동|move)?",
    re.IGNORECASE,
)

DIRECTION_MAP = {
    "왼쪽": "left", "오른쪽": "right", "위": "up", "아래": "down",
    "앞": "forward", "뒤": "back",
    "left": "left", "right": "right", "up": "up", "down": "down",
    "forward": "forward", "back": "back",
}

DIRECTION_EXTRACT = re.compile(
    r"(왼쪽|오른쪽|위|아래|앞|뒤|left|right|up|down|forward|back)",
    re.IGNORECASE,
)

PREFAB_SAVE_PATTERN = re.compile(
    r"([\w가-힣]+)\s*(?:을|를)?\s*(?:프리팹|prefab)\s*(?:으로|로)?\s*(?:저장|만들|생성|save|create)",
    re.IGNORECASE,
)

TEXTURE_CREATE_PATTERN = re.compile(
    r"(\d+)\s*[x×]\s*(\d+)\s+[\w가-힣\s]*(?:텍스처|texture)\s*(?:를?\s*)?(?:생성|만들|create)"
    r"|"
    r"(?:텍스처|texture)\s*(?:를?\s*)?(?:생성|만들|create)\s*(\d+)\s*[x×]\s*(\d+)"
    r"|"
    r"(\d+)\s*[x×]\s*(\d+)\s*(?:텍스처|texture)",
    re.IGNORECASE,
)

TEXTURE_PATTERN_EXTRACT = re.compile(
    r"(체커보드|checkerboard|줄무늬|stripes|도트|dots|그리드|grid|벽돌|brick)",
    re.IGNORECASE,
)

TEXTURE_PATTERN_MAP = {
    "체커보드": "checkerboard", "checkerboard": "checkerboard",
    "줄무늬": "stripes", "stripes": "stripes",
    "도트": "dots", "dots": "dots",
    "그리드": "grid", "grid": "grid",
    "벽돌": "brick", "brick": "brick",
}

EDITOR_CONTROL_PATTERN = re.compile(
    r"(?:플레이|play)\s*(?:모드)?\s*(?:시작|start)|"
    r"(?:일시정지|pause)|"
    r"(?:정지|중지|stop)\s*(?:모드)?",
    re.IGNORECASE,
)

EDITOR_ACTION_MAP = {
    "플레이": "play", "play": "play", "시작": "play", "start": "play",
    "일시정지": "pause", "pause": "pause",
    "정지": "stop", "중지": "stop", "stop": "stop",
}

# ── Additional advanced patterns ────────────────────────────

REMOVE_COMPONENT_PATTERN = re.compile(
    r"([\w가-힣]+)\s*(?:에서|에|한테서)?\s*(?:Rigidbody|리지드바디|BoxCollider|박스콜라이더|SphereCollider|MeshCollider|"
    r"CapsuleCollider|AudioSource|오디오|Light|라이트|Camera|카메라)\s*(?:를?\s*)?(?:제거|삭제|remove|delete)",
    re.IGNORECASE,
)

LOAD_SCENE_PATTERN = re.compile(
    r"(?:씬|scene)\s+([\w가-힣\-_]+)\s*(?:를?\s*)?(?:로드|불러와|열어|load|open)"
    r"|"
    r"([\w가-힣\-_]+)\s+(?:씬|scene)\s*(?:를?\s*)?(?:로드|불러와|열어|load|open)",
    re.IGNORECASE,
)

CREATE_SCENE_PATTERN = re.compile(
    r"(?:새|new)\s*(?:씬|scene)\s+([\w가-힣\-_]+)\s*(?:를?\s*)?(?:만들|생성|create)?"
    r"|"
    r"(?:씬|scene)\s+([\w가-힣\-_]+)\s*(?:를?\s*)?(?:만들|생성|create)",
    re.IGNORECASE,
)

SEARCH_ASSETS_PATTERN = re.compile(
    r"(?:에셋|asset|자산)\s*(?:을|를)?\s*(?:검색|찾기|search|find)\s+([\w.*가-힣]+)"
    r"|"
    r"([\w.*가-힣]+)\s+(?:에셋|asset|자산)\s*(?:을|를)?\s*(?:검색|찾기|search|find)",
    re.IGNORECASE,
)

RENAME_OBJECT_PATTERN = re.compile(
    r"([\w가-힣]+)\s*(?:을|를)?\s*(?:이름을?\s*)?(?:으로|로)?\s*([\w가-힣]+)\s*(?:으로|로)\s*(?:이름\s*)?(?:변경|바꿔|rename)"
    r"|"
    r"(?:이름\s*변경|rename)\s+([\w가-힣]+)\s*(?:을|를)?\s*([\w가-힣]+)\s*(?:으로|로)?",
    re.IGNORECASE,
)

SET_ACTIVE_PATTERN = re.compile(
    r"([\w가-힣]+)\s*(?:을|를)?\s*(?:활성화|켜|enable|activate)"
    r"|"
    r"([\w가-힣]+)\s*(?:을|를)?\s*(?:비활성화|끄기|끄|disable|deactivate|hide)",
    re.IGNORECASE,
)

ADD_LAYER_PATTERN = re.compile(
    r"(?:레이어|layer)\s+([\w가-힣]+)\s*(?:을|를)?\s*(?:추가|만들|add|create)",
    re.IGNORECASE,
)

REFRESH_PATTERN = re.compile(
    r"(?:에셋|asset|자산)\s*(?:을|를)?\s*(?:새로고침|갱신|리프레시|refresh)"
    r"|"
    r"(?:새로고침|갱신|리프레시|refresh)\s*(?:에셋|asset|자산)?",
    re.IGNORECASE,
)

READ_CONSOLE_PATTERN = re.compile(
    r"(?:콘솔|console)\s*(?:을|를)?\s*(?:확인|읽기|보기|read|check|show)"
    r"|"
    r"(?:에러|error|오류|경고|warning)\s*(?:을|를)?\s*(?:확인|보기|check|show)",
    re.IGNORECASE,
)

LINE_RENDERER_PATTERN = re.compile(
    r"(?:라인|line|선)\s*(?:렌더러|renderer)?\s*(?:을|를)?\s*(?:만들|생성|그려|create|draw)",
    re.IGNORECASE,
)

SET_TAG_OBJECT_PATTERN = re.compile(
    r"([\w가-힣]+)\s*(?:에|의)?\s*(?:태그|tag)\s*(?:를?\s*)?(?:으로|로)?\s*([\w가-힣]+)\s*(?:으로|로)?\s*(?:설정|변경|set|change)?",
    re.IGNORECASE,
)

RUN_TESTS_PATTERN = re.compile(
    r"(?:테스트|test)\s*(?:를?\s*)?(?:실행|돌려|run|execute)"
    r"|"
    r"(?:실행|돌려|run)\s+(?:테스트|test)",
    re.IGNORECASE,
)

CREATE_SCRIPT_PATTERN = re.compile(
    r"(?:스크립트|script)\s+([\w가-힣]+)\s*(?:을|를)?\s*(?:만들|생성|create)"
    r"|"
    r"([\w가-힣]+)\s+(?:스크립트|script)\s*(?:을|를)?\s*(?:만들|생성|create)",
    re.IGNORECASE,
)

COLOR_MAP = {
    "빨간": {"r": 0.8, "g": 0.15, "b": 0.15, "a": 1.0},
    "빨강": {"r": 0.8, "g": 0.15, "b": 0.15, "a": 1.0},
    "red": {"r": 0.8, "g": 0.15, "b": 0.15, "a": 1.0},
    "파란": {"r": 0.2, "g": 0.4, "b": 0.8, "a": 1.0},
    "파랑": {"r": 0.2, "g": 0.4, "b": 0.8, "a": 1.0},
    "바란": {"r": 0.2, "g": 0.4, "b": 0.8, "a": 1.0},  # common typo for 파란
    "blue": {"r": 0.2, "g": 0.4, "b": 0.8, "a": 1.0},
    "초록": {"r": 0.15, "g": 0.65, "b": 0.15, "a": 1.0},
    "녹색": {"r": 0.15, "g": 0.65, "b": 0.15, "a": 1.0},
    "green": {"r": 0.15, "g": 0.65, "b": 0.15, "a": 1.0},
    "노란": {"r": 0.9, "g": 0.8, "b": 0.1, "a": 1.0},
    "노랑": {"r": 0.9, "g": 0.8, "b": 0.1, "a": 1.0},
    "yellow": {"r": 0.9, "g": 0.8, "b": 0.1, "a": 1.0},
    "주황": {"r": 0.9, "g": 0.5, "b": 0.1, "a": 1.0},
    "orange": {"r": 0.9, "g": 0.5, "b": 0.1, "a": 1.0},
    "보라": {"r": 0.5, "g": 0.2, "b": 0.7, "a": 1.0},
    "purple": {"r": 0.5, "g": 0.2, "b": 0.7, "a": 1.0},
    "회색": {"r": 0.6, "g": 0.6, "b": 0.6, "a": 1.0},
    "gray": {"r": 0.6, "g": 0.6, "b": 0.6, "a": 1.0},
    "grey": {"r": 0.6, "g": 0.6, "b": 0.6, "a": 1.0},
    "흰": {"r": 0.95, "g": 0.95, "b": 0.95, "a": 1.0},
    "하얀": {"r": 0.95, "g": 0.95, "b": 0.95, "a": 1.0},
    "white": {"r": 0.95, "g": 0.95, "b": 0.95, "a": 1.0},
    "검은": {"r": 0.1, "g": 0.1, "b": 0.1, "a": 1.0},
    "검정": {"r": 0.1, "g": 0.1, "b": 0.1, "a": 1.0},
    "black": {"r": 0.1, "g": 0.1, "b": 0.1, "a": 1.0},
    "콘크리트": {"r": 0.6, "g": 0.6, "b": 0.6, "a": 1.0},
    "concrete": {"r": 0.6, "g": 0.6, "b": 0.6, "a": 1.0},
    "스테인리스": {"r": 0.8, "g": 0.82, "b": 0.85, "a": 1.0},
    "stainless": {"r": 0.8, "g": 0.82, "b": 0.85, "a": 1.0},
    "steel": {"r": 0.75, "g": 0.75, "b": 0.78, "a": 1.0},
    "메탈": {"r": 0.75, "g": 0.75, "b": 0.78, "a": 1.0},
    "metal": {"r": 0.75, "g": 0.75, "b": 0.78, "a": 1.0},
    "나무": {"r": 0.55, "g": 0.35, "b": 0.17, "a": 1.0},
    "wood": {"r": 0.55, "g": 0.35, "b": 0.17, "a": 1.0},
    "구리": {"r": 0.72, "g": 0.45, "b": 0.2, "a": 1.0},
    "copper": {"r": 0.72, "g": 0.45, "b": 0.2, "a": 1.0},
    "금": {"r": 0.83, "g": 0.69, "b": 0.22, "a": 1.0},
    "gold": {"r": 0.83, "g": 0.69, "b": 0.22, "a": 1.0},
    # Compound color names (longer keys checked first by _find_color)
    "유광 스테인리스 메탈": {"r": 0.85, "g": 0.87, "b": 0.9, "a": 1.0},
    "유광스테인리스메탈": {"r": 0.85, "g": 0.87, "b": 0.9, "a": 1.0},
    "유광 스테인리스": {"r": 0.85, "g": 0.87, "b": 0.9, "a": 1.0},
    "유광스테인리스": {"r": 0.85, "g": 0.87, "b": 0.9, "a": 1.0},
    "스테인리스 메탈": {"r": 0.8, "g": 0.82, "b": 0.85, "a": 1.0},
    "스테인리스메탈": {"r": 0.8, "g": 0.82, "b": 0.85, "a": 1.0},
    "매트 스테인리스": {"r": 0.7, "g": 0.72, "b": 0.75, "a": 1.0},
    "glossy stainless": {"r": 0.85, "g": 0.87, "b": 0.9, "a": 1.0},
    "stainless steel": {"r": 0.8, "g": 0.82, "b": 0.85, "a": 1.0},
    "brushed metal": {"r": 0.7, "g": 0.72, "b": 0.75, "a": 1.0},
    "dark metal": {"r": 0.35, "g": 0.35, "b": 0.38, "a": 1.0},
    "검은 메탈": {"r": 0.35, "g": 0.35, "b": 0.38, "a": 1.0},
}


def _find_color(text: str) -> Optional[dict]:
    """Find color in text by substring matching, preferring longest key match."""
    text_lower = text.lower()
    # Check longer keys first so "유광 스테인리스 메탈" matches before "스테인리스"
    for keyword in sorted(COLOR_MAP, key=len, reverse=True):
        if keyword in text_lower:
            return COLOR_MAP[keyword]
    return None


def _find_position(text: str) -> Optional[dict]:
    match = POSITION_PATTERN.search(text)
    if match:
        return {"x": float(match.group(1)), "y": float(match.group(2)), "z": float(match.group(3))}
    # English spatial keywords
    if re.search(r"\bat\s+(?:the\s+)?origin\b", text, re.IGNORECASE):
        return {"x": 0, "y": 0, "z": 0}
    if re.search(r"\bat\s+(?:the\s+)?center\b", text, re.IGNORECASE):
        return {"x": 0, "y": 0, "z": 0}
    return None


# ── Korean→English object name mapping ────────────────────────
# Maps common Korean object references to their English Unity names
KOREAN_NAME_MAP = {
    "바닥": "Floor",
    "조명": "Light_0",
    "라이트": "Light_0",
    "불": "Light_0",
    "카메라": "Main Camera",
    "큐브": "Cube_0",
    "구": "Sphere_0",
    "실린더": "Cylinder_0",
    "캡슐": "Capsule_0",
    "벽": "Wall_0",
}

# Fermentation vessel keywords → when used as target, expand to all matching scene objects
FERMENTATION_VESSEL_KEYWORDS = {
    "발효탱크", "발효조", "배양기", "발효기", "fermenter", "fermentor",
    "피드탱크", "공급탱크", "feed tank",
    "브로스탱크", "배양액탱크", "broth tank",
    "탱크",  # generic "tank" in Korean — when used in color change context
}

# Structure group keywords → resolve to matching objects in BioFacility/Structure
# Maps Korean building element names to Unity object name prefixes
STRUCTURE_KEYWORDS: dict[str, list[str]] = {
    # Frame elements (columns + beams)
    "프레임": ["Col_", "Beam_"],
    "골격": ["Col_", "Beam_"],
    "골조": ["Col_", "Beam_"],
    "frame": ["Col_", "Beam_"],
    # Columns only
    "기둥": ["Col_"],
    "컬럼": ["Col_"],
    "column": ["Col_"],
    # Beams only
    "빔": ["Beam_"],
    "보": ["Beam_"],
    "beam": ["Beam_"],
    # Railings
    "난간": ["Railing_", "RailingPost_"],
    "레일링": ["Railing_", "RailingPost_"],
    "railing": ["Railing_", "RailingPost_"],
    # Walkways
    "통로": ["Walkway_", "PassageWay"],
    "워크웨이": ["Walkway_"],
    "walkway": ["Walkway_"],
    # Stairs
    "계단": ["Stairs_"],
    "stairs": ["Stairs_"],
    # Floors / platforms
    "바닥": ["Floor_", "Platform_"],
    "플로어": ["Floor_"],
    "플랫폼": ["Platform_"],
    # Walls / panels
    "벽": ["Wall_", "Panel_"],
    "패널": ["Panel_"],
    # Hoists
    "호이스트": ["Hoist_"],
    "크레인": ["Hoist_"],
    "hoist": ["Hoist_"],
    # Cargo lift
    "리프트": ["CargoLift_"],
    "엘리베이터": ["CargoLift_"],
    "lift": ["CargoLift_"],
    # Pipes
    "배관": ["Pipe_", "Valve_"],
    "파이프": ["Pipe_"],
    "pipe": ["Pipe_"],
    # Vessels (generic)
    "용기": ["Body", "Dome", "Jacket"],
    "vessel": ["Body", "Dome", "Jacket"],
}


def _resolve_color_targets(
    target_text: str, scene_context: dict | None = None
) -> list[str]:
    """Resolve a target name to one or more Unity object names for color change.

    Handles:
    1. Fermentation vessel keywords → expand to KF-*/Body, KF-*/Dome children
    2. Structure keywords → expand to Col_*, Beam_*, Railing_*, etc.
    3. Multi-word Korean descriptions → extract structure keyword from phrase
    4. Standard Korean name resolution as fallback
    """
    cleaned = re.sub(r"(?:으로|에서|에게|에|을|를|의|이|가|은|는)$", "", target_text).strip()

    # Check for structure keyword match (single word or within multi-word phrase)
    matched_prefixes: list[str] = []
    cleaned_lower = cleaned.lower()
    for keyword, prefixes in STRUCTURE_KEYWORDS.items():
        if keyword in cleaned_lower:
            matched_prefixes.extend(prefixes)
    if matched_prefixes:
        # De-duplicate prefixes
        matched_prefixes = list(dict.fromkeys(matched_prefixes))
        if scene_context:
            objects = scene_context.get("objects", {})
            if isinstance(objects, dict):
                targets = [
                    name for name in objects
                    if any(name.startswith(pfx) for pfx in matched_prefixes)
                ]
                if targets:
                    return targets
        # Fallback: return prefixed names with wildcard search (by_name)
        return [pfx.rstrip("_") for pfx in matched_prefixes]

    # Check if it's a generic fermentation vessel reference
    if cleaned in FERMENTATION_VESSEL_KEYWORDS:
        if scene_context:
            objects = scene_context.get("objects", {})
            if isinstance(objects, dict):
                # Find renderable vessel children (Body, Dome of KF-* vessels)
                renderable = [
                    name for name in objects
                    if (name.startswith("KF-") and "/" in name  # path: KF-700L/Body
                        and any(part in name for part in ("Body", "Dome")))
                    or (name in ("Body", "Dome")  # flat name match
                        and isinstance(objects.get(name), dict)
                        and "MeshRenderer" in str(objects[name].get("components", "")))
                ]
                if renderable:
                    return renderable
                # Fallback: find KF-* parent names, they may work on some scenes
                vessels = [
                    name for name in objects
                    if name.startswith("KF-") or "Ferment" in name
                ]
                if vessels:
                    return vessels
        # Fallback: use by_path with known vessel children (Body is the main vessel body)
        return [
            "BioFacility/Vessels/KF-70L/Body",
            "BioFacility/Vessels/KF-70L/Dome",
            "BioFacility/Vessels/KF-700L/Body",
            "BioFacility/Vessels/KF-700L/Dome",
            "BioFacility/Vessels/KF-7KL/Body",
            "BioFacility/Vessels/KF-7KL/Dome",
            "BioFacility/Vessels/KF-70L-FD/Body",
            "BioFacility/Vessels/KF-70L-FD/Dome",
            "BioFacility/Vessels/KF-500L-FD/Body",
            "BioFacility/Vessels/KF-500L-FD/Dome",
            "BioFacility/Vessels/KF-4KL-FD/Body",
            "BioFacility/Vessels/KF-4KL-FD/Dome",
            "BioFacility/Vessels/KF-7KL-BROTH/Body",
            "BioFacility/Vessels/KF-7KL-BROTH/Dome",
        ]

    # Try standard Korean name resolution
    resolved = _resolve_korean_name(cleaned, scene_context)
    return [resolved] if resolved else [cleaned]


def _resolve_korean_name(
    target: str | None, scene_context: dict | None = None
) -> str | None:
    """Resolve a Korean object name to its English Unity name.

    First checks the static KOREAN_NAME_MAP, then tries fuzzy matching
    against actual scene objects if scene_context is provided.
    """
    if not target:
        return target

    # 1. Strip Korean particles from the target
    cleaned = re.sub(r"(?:으로|에서|에게|에|을|를|의|이|가|은|는)$", "", target)

    # 2. Direct Korean→English mapping
    mapped = KOREAN_NAME_MAP.get(cleaned)
    if mapped:
        # If scene_context available, verify the mapped name exists
        if scene_context:
            objects = scene_context.get("objects", {})
            if isinstance(objects, dict):
                if mapped in objects:
                    return mapped
                # Try partial match (e.g., "Floor" matches "Floor (1)")
                for obj_name in objects:
                    if obj_name.startswith(mapped):
                        return obj_name
        return mapped

    # 3. Try matching against scene objects (fuzzy: Korean target as prefix)
    if scene_context:
        objects = scene_context.get("objects", {})
        if isinstance(objects, dict):
            # Exact match first
            if cleaned in objects:
                return cleaned
            # Case-insensitive match
            for obj_name in objects:
                if obj_name.lower() == cleaned.lower():
                    return obj_name

    return cleaned


def generate_plan_template(command: str, scene_context: dict | None = None) -> Optional[dict]:
    """Try to generate a plan from template patterns (no LLM needed)."""
    plan = {
        "project": "My project",
        "scene": config.DEFAULT_SCENE,
        "description": command,
        "actions": [],
    }

    # ── Early delete detection (MUST come before all creation patterns) ──
    # Commands like "바닥을 제거해", "Floor 삭제", "20m x 10m 바닥 제거" contain creation
    # keywords (바닥, floor) but the user's intent is deletion. Check delete keywords first.
    _has_delete_intent = bool(re.search(
        r"삭제|지워|제거|delete|remove|없애|치워",
        command, re.IGNORECASE,
    ))
    if _has_delete_intent:
        # Skip straight to delete handling (below) by jumping over creation patterns
        # But first check component removal (e.g., "Rigidbody 제거")
        rem_comp_match = REMOVE_COMPONENT_PATTERN.search(command)
        if rem_comp_match:
            target = rem_comp_match.group(1)
            comp_extract = COMPONENT_EXTRACT.search(command)
            if comp_extract:
                plan["actions"].append({
                    "type": "remove_component",
                    "target": target,
                    "component_type": comp_extract.group(1),
                })
                return plan

        # Delete ALL objects
        if DELETE_ALL_PATTERN.search(command):
            if scene_context:
                raw_objects = scene_context.get("objects", {})
                obj_list = list(raw_objects.values()) if isinstance(raw_objects, dict) else raw_objects
                skip = {"Main Camera", "Directional Light", "EventSystem"}
                for obj in obj_list:
                    name = obj.get("name", "") if isinstance(obj, dict) else str(obj)
                    if name and name not in skip:
                        plan["actions"].append({
                            "type": "delete_object",
                            "target": name,
                            "search_method": "by_name",
                        })
            if not plan["actions"]:
                plan["actions"].append({
                    "type": "delete_object",
                    "target": "*",
                    "search_method": "by_name",
                })
            return plan

        # Delete single object
        del_match = DELETE_PATTERN.search(command)
        if del_match:
            target = del_match.group(1) or del_match.group(2)
            # Resolve Korean names to English (바닥→Floor, 조명→Light_0, etc.)
            target = _resolve_korean_name(target, scene_context)
            if target and target not in ("해줘", "해", "줘", "모두", "모든", "전부", "전체", "다"):
                plan["actions"].append({
                    "type": "delete_object",
                    "target": target,
                    "search_method": "by_name",
                })
                return plan

    # ── Early color-change intent detection (MUST come before creation patterns) ──
    # Commands like "발효탱크 컬러 유광 스테인리스 메탈 컬러로 수정" contain creation
    # keywords (탱크) but the user's intent is color/material change. Detect this early
    # so CYLINDER_PATTERN doesn't hijack the command into creating a new object.
    _has_color_change_intent = bool(re.search(
        r"(?:색상|색깔|색갈|색|컬러|재질|color|material).*?(?:변경|수정|바꿔|적용|칠해|change|apply|update)"
        r"|(?:변경|수정|바꿔|적용|칠해|change|apply|update).*?(?:색상|색깔|색갈|색|컬러|재질|color|material)",
        command, re.IGNORECASE,
    ))
    if _has_color_change_intent:
        color = _find_color(command)
        if color:
            # Extract target: text before first color/material keyword
            parts = re.split(
                r"\s*(?:색상|색깔|색갈|컬러|재질|색|color)\s*(?:을|를|의|에)?\s*",
                command, maxsplit=1, flags=re.IGNORECASE,
            )
            target_text = parts[0].strip() if parts else ""
            target_text = re.sub(r"(?:으로|에서|에게|에|을|를|의|이|가|은|는)\s*$", "", target_text).strip()

            if target_text:
                targets = _resolve_color_targets(target_text, scene_context)
                for t in targets:
                    action = {
                        "type": "apply_material",
                        "target": t,
                        "color": color,
                    }
                    # Use by_path for hierarchical targets (e.g., BioFacility/Vessels/KF-700L/Body)
                    if "/" in t:
                        action["search_method"] = "by_path"
                    plan["actions"].append(action)
                if plan["actions"]:
                    return plan

    # Remove component (must come before generic delete — "Rigidbody 제거" contains "제거")
    rem_comp_match = REMOVE_COMPONENT_PATTERN.search(command)
    if rem_comp_match:
        target = rem_comp_match.group(1)
        comp_extract = COMPONENT_EXTRACT.search(command)
        if comp_extract:
            plan["actions"].append({
                "type": "remove_component",
                "target": target,
                "component_type": comp_extract.group(1),
            })
            return plan

    # Set active/inactive (must come before light pattern — "Light_0을 활성화" contains "light")
    active_match = SET_ACTIVE_PATTERN.search(command)
    if active_match:
        if active_match.group(1):
            plan["actions"].append({
                "type": "set_object_active",
                "target": active_match.group(1),
                "active": True,
            })
        else:
            plan["actions"].append({
                "type": "set_object_active",
                "target": active_match.group(2),
                "active": False,
            })
        return plan

    # Floor creation
    floor_match = FLOOR_PATTERN.search(command)
    if floor_match:
        groups = floor_match.groups()
        w, d = None, None
        for i in range(0, len(groups), 2):
            if groups[i] is not None:
                w, d = float(groups[i]), float(groups[i + 1])
                break
        if w and d:
            color = _find_color(command)
            plan["actions"].append({
                "type": "create_primitive",
                "shape": "Cube",
                "name": "Floor",
                "position": {"x": 0, "y": -0.05, "z": 0},
                "scale": {"x": w, "y": 0.1, "z": d},
            })
            if color:
                plan["actions"].append({
                    "type": "apply_material",
                    "target": "Floor",
                    "color": color,
                })
            return plan

    # Light creation
    if LIGHT_PATTERN.search(command):
        count_match = re.search(r"(\d+)\s*(?:개|lights?)\b", command, re.IGNORECASE)
        count = int(count_match.group(1)) if count_match else 1
        height_match = re.search(r"(?:높이|height)\s*(\d+(?:\.\d+)?)|(\d+(?:\.\d+)?)\s*m", command, re.IGNORECASE)
        height = float(height_match.group(1) or height_match.group(2)) if height_match else 5.0

        if count == 1:
            plan["actions"].append({
                "type": "create_light",
                "light_type": "Point",
                "name": "Light_0",
                "position": {"x": 0, "y": height, "z": 0},
            })
        else:
            # Grid layout
            cols = int(count ** 0.5) or 1
            rows = (count + cols - 1) // cols
            spacing = 4.0
            for i in range(count):
                r, c = divmod(i, cols)
                x = (c - (cols - 1) / 2) * spacing
                z = (r - (rows - 1) / 2) * spacing
                plan["actions"].append({
                    "type": "create_light",
                    "light_type": "Point",
                    "name": f"Light_{i}",
                    "position": {"x": x, "y": height, "z": z},
                })
        return plan

    # Screenshot
    if SCREENSHOT_PATTERN.search(command):
        plan["actions"].append({"type": "screenshot", "filename": "vibe3d_capture"})
        return plan

    # Import asset (e.g., "Import layout_page_1.png from C:/path/to/file")
    import_match = IMPORT_PATTERN.search(command)
    if import_match:
        if import_match.group(1):
            # "Import filename from source_path"
            filename = import_match.group(1).strip()
            source_path = import_match.group(2).strip()
        else:
            # "source_path 에서 filename 가져와"
            source_path = import_match.group(3).strip()
            filename = import_match.group(4).strip()
        # Determine destination folder based on file extension
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext in ("png", "jpg", "jpeg", "tga", "bmp", "gif", "psd", "tif", "tiff"):
            dest_folder = "Assets/Textures"
        elif ext in ("fbx", "obj", "blend", "dae", "3ds"):
            dest_folder = "Assets/Models"
        elif ext in ("mat",):
            dest_folder = "Assets/Materials"
        elif ext in ("wav", "mp3", "ogg", "aiff"):
            dest_folder = "Assets/Audio"
        else:
            dest_folder = "Assets/Imports"
        plan["actions"].append({
            "type": "import_asset",
            "source_path": source_path,
            "filename": filename,
            "destination": dest_folder,
        })
        return plan

    # Prefab save (e.g., "Tank_A를 프리팹으로 저장") — must come before generic save
    prefab_match = PREFAB_SAVE_PATTERN.search(command)
    if prefab_match:
        target = prefab_match.group(1)
        plan["actions"].append({
            "type": "create_prefab",
            "target": target,
            "prefab_path": f"Assets/Prefabs/{target}.prefab",
        })
        return plan

    # Save scene
    if SAVE_PATTERN.search(command):
        plan["actions"].append({"type": "save_scene"})
        return plan

    # Menu execution (e.g., "Fermentation/Build Complete Facility 메뉴 실행", "execute menu X")
    menu_match = MENU_EXECUTE_PATTERN.search(command)
    if menu_match:
        menu_path = (menu_match.group(1) or menu_match.group(2) or "").strip()
        if menu_path:
            plan["actions"].append({"type": "execute_menu", "menu_path": menu_path})
            return plan

    # Hierarchy view (e.g., "FermentationFacility 하위 구조를 보여줘")
    hier_match = HIERARCHY_PATTERN.search(command)
    if hier_match:
        target = hier_match.group(1).strip()
        plan["actions"].append({"type": "get_hierarchy", "target": target})
        return plan

    # Delete ALL objects
    if DELETE_ALL_PATTERN.search(command):
        if scene_context:
            raw_objects = scene_context.get("objects", {})
            obj_list = list(raw_objects.values()) if isinstance(raw_objects, dict) else raw_objects
            skip = {"Main Camera", "Directional Light", "EventSystem"}
            for obj in obj_list:
                name = obj.get("name", "") if isinstance(obj, dict) else str(obj)
                if name and name not in skip:
                    plan["actions"].append({
                        "type": "delete_object",
                        "target": name,
                        "search_method": "by_name",
                    })
        if not plan["actions"]:
            plan["actions"].append({
                "type": "delete_object",
                "target": "*",
                "search_method": "by_name",
            })
        return plan

    # Delete single object
    del_match = DELETE_PATTERN.search(command)
    if del_match:
        target = del_match.group(1) or del_match.group(2)
        target = _resolve_korean_name(target, scene_context)
        # Exclude false positives from Korean particles
        if target and target not in ("해줘", "해", "줘", "모두", "모든", "전부", "전체", "다"):
            plan["actions"].append({
                "type": "delete_object",
                "target": target,
                "search_method": "by_name",
            })
            return plan

    # Duplicate object
    dup_match = DUPLICATE_PATTERN.search(command)
    if dup_match:
        target = dup_match.group(1) or dup_match.group(2)
        position = _find_position(command)
        action: dict = {
            "type": "duplicate_object",
            "target": target,
            "new_name": f"{target}_copy",
        }
        if position:
            action["position"] = position
        plan["actions"].append(action)
        return plan

    # Move object
    move_match = MOVE_PATTERN.search(command)
    if move_match:
        if move_match.group(1):
            target = move_match.group(1)
            pos = {"x": float(move_match.group(2)), "y": float(move_match.group(3)), "z": float(move_match.group(4))}
        elif move_match.group(5):
            target = move_match.group(5)
            pos = {"x": float(move_match.group(6)), "y": float(move_match.group(7)), "z": float(move_match.group(8))}
        else:
            target = move_match.group(9)
            pos = {"x": float(move_match.group(10)), "y": float(move_match.group(11)), "z": float(move_match.group(12))}
        plan["actions"].append({
            "type": "modify_object",
            "target": target,
            "search_method": "by_name",
            "position": pos,
        })
        return plan

    # Color change (e.g., "Tank_A 색상을 빨간으로 변경", "Floor에 빨간 재질 적용해줘",
    #                    "Floor를 스테인리스로 변경", "set Tank_A color to red", "make Floor blue")
    color_match = COLOR_CHANGE_PATTERN.search(command)
    if color_match:
        # Alt 1: groups(1,2), Alt 2: groups(3,4), Alt 3: groups(5,6), Alt 4: groups(7,8), Alt 5: groups(9,10)
        target = color_match.group(1) or color_match.group(3) or color_match.group(5) or color_match.group(7) or color_match.group(9)
        color_name = color_match.group(2) or color_match.group(4) or color_match.group(6) or color_match.group(8) or color_match.group(10)
        # Strip trailing Korean particles from target/color_name
        if target:
            target = re.sub(r"(?:으로|에서|에게|에|을|를|의|이|가|은|는)$", "", target)
        if color_name:
            color_name = re.sub(r"(?:으로|로)$", "", color_name)
        if target and color_name:
            color = COLOR_MAP.get(color_name.lower()) or COLOR_MAP.get(color_name)
            if color:
                plan["actions"].append({
                    "type": "apply_material",
                    "target": target,
                    "color": color,
                })
                return plan

    # Scale object
    scale_match = SCALE_PATTERN.search(command)
    if scale_match:
        target = scale_match.group(1)
        plan["actions"].append({
            "type": "modify_object",
            "target": target,
            "search_method": "by_name",
            "scale": {
                "x": float(scale_match.group(2)),
                "y": float(scale_match.group(3)),
                "z": float(scale_match.group(4)),
            },
        })
        return plan

    # Wall creation (e.g., "벽 10m 높이 3m")
    if WALL_PATTERN.search(command):
        length_match = re.search(r"(\d+(?:\.\d+)?)\s*m", command)
        height_match = re.search(r"높이\s*(\d+(?:\.\d+)?)|height\s*(\d+(?:\.\d+)?)", command, re.IGNORECASE)
        length = float(length_match.group(1)) if length_match else 10.0
        height = 3.0
        if height_match:
            height = float(height_match.group(1) or height_match.group(2))
        color = _find_color(command)
        plan["actions"].append({
            "type": "create_primitive",
            "shape": "Cube",
            "name": "Wall_0",
            "position": {"x": 0, "y": height / 2, "z": 0},
            "scale": {"x": length, "y": height, "z": 0.2},
        })
        if color:
            plan["actions"].append({
                "type": "apply_material",
                "target": "Wall_0",
                "color": color,
            })
        return plan

    # Grid of objects (e.g., "그리드 3x4 큐브 간격 2m")
    grid_match = GRID_PATTERN.search(command)
    if grid_match:
        cols = int(grid_match.group(1))
        rows = int(grid_match.group(2))
        shape = "Cube"
        if CYLINDER_PATTERN.search(command):
            shape = "Cylinder"
        elif SPHERE_PATTERN.search(command):
            shape = "Sphere"
        spacing_match = re.search(r"간격\s*(\d+(?:\.\d+)?)|spacing\s*(\d+(?:\.\d+)?)", command, re.IGNORECASE)
        spacing = 2.0
        if spacing_match:
            spacing = float(spacing_match.group(1) or spacing_match.group(2))
        color = _find_color(command)
        parent_name = f"{shape}_Grid"
        plan["actions"].append({
            "type": "create_empty",
            "name": parent_name,
            "position": {"x": 0, "y": 0, "z": 0},
        })
        idx = 0
        for r in range(rows):
            for c in range(cols):
                name = f"{shape}_{idx}"
                x = (c - (cols - 1) / 2) * spacing
                z = (r - (rows - 1) / 2) * spacing
                plan["actions"].append({
                    "type": "create_primitive",
                    "shape": shape,
                    "name": name,
                    "parent": parent_name,
                    "position": {"x": x, "y": 0.5, "z": z},
                })
                if color:
                    plan["actions"].append({
                        "type": "apply_material",
                        "target": name,
                        "color": color,
                    })
                idx += 1
        return plan

    # Component add (e.g., "Tank_A에 Rigidbody 추가")
    comp_match = COMPONENT_PATTERN.search(command)
    if comp_match:
        target = comp_match.group(1)
        comp_extract = COMPONENT_EXTRACT.search(command)
        if comp_extract:
            component_type = comp_extract.group(1)
            plan["actions"].append({
                "type": "add_component",
                "target": target,
                "component_type": component_type,
            })
            return plan

    # Physics apply (e.g., "Tank_A에 물리 적용")
    phys_match = PHYSICS_PATTERN.search(command)
    if phys_match:
        target = phys_match.group(1)
        plan["actions"].append({
            "type": "add_component",
            "target": target,
            "component_type": "Rigidbody",
            "properties": {"mass": 1, "useGravity": True},
        })
        plan["actions"].append({
            "type": "add_component",
            "target": target,
            "component_type": "MeshCollider",
        })
        return plan

    # Relative move (e.g., "Tank_A를 오른쪽으로 3m 이동")
    rel_move_match = RELATIVE_MOVE_PATTERN.search(command)
    if rel_move_match:
        target = rel_move_match.group(1)
        distance = float(rel_move_match.group(2))
        dir_match = DIRECTION_EXTRACT.search(command)
        direction = DIRECTION_MAP.get(dir_match.group(1).lower() if dir_match else "", "right")
        plan["actions"].append({
            "type": "move_relative",
            "target": target,
            "direction": direction,
            "distance": distance,
        })
        return plan

    # Texture creation (e.g., "256x256 체커보드 텍스처 생성")
    tex_match = TEXTURE_CREATE_PATTERN.search(command)
    if tex_match:
        w = int(tex_match.group(1) or tex_match.group(3) or tex_match.group(5))
        h = int(tex_match.group(2) or tex_match.group(4) or tex_match.group(6))
        pat_match = TEXTURE_PATTERN_EXTRACT.search(command)
        pattern = TEXTURE_PATTERN_MAP.get(pat_match.group(1).lower(), "checkerboard") if pat_match else None
        action_item = {
            "type": "create_texture",
            "name": f"Tex_{w}x{h}",
            "width": w,
            "height": h,
        }
        if pattern:
            action_item["pattern"] = pattern
        plan["actions"].append(action_item)
        return plan

    # Editor control (e.g., "플레이 모드 시작", "정지")
    if EDITOR_CONTROL_PATTERN.search(command):
        action_val = "play"
        for keyword, act in EDITOR_ACTION_MAP.items():
            if keyword in command.lower():
                action_val = act
                break
        plan["actions"].append({
            "type": "editor_control",
            "action": action_val,
        })
        return plan

    # Load scene (e.g., "씬 bio-plants 로드", "MainScene 씬 불러와")
    load_scene_match = LOAD_SCENE_PATTERN.search(command)
    if load_scene_match:
        scene_name = load_scene_match.group(1) or load_scene_match.group(2)
        plan["actions"].append({
            "type": "load_scene",
            "name": scene_name,
        })
        return plan

    # Create scene (e.g., "새 씬 TestScene 만들어")
    create_scene_match = CREATE_SCENE_PATTERN.search(command)
    if create_scene_match:
        scene_name = create_scene_match.group(1) or create_scene_match.group(2)
        plan["actions"].append({
            "type": "create_scene",
            "name": scene_name,
        })
        return plan

    # Search assets (e.g., "에셋 검색 *.mat", "Material 에셋 찾기")
    search_match = SEARCH_ASSETS_PATTERN.search(command)
    if search_match:
        pattern = search_match.group(1) or search_match.group(2)
        cmd_action: dict = {"type": "search_assets", "path": "Assets"}
        if "*" in pattern:
            cmd_action["search_pattern"] = pattern
        else:
            cmd_action["filter_type"] = pattern
        plan["actions"].append(cmd_action)
        return plan

    # Rename object (e.g., "Tank_A를 이름 MainTank으로 변경")
    rename_match = RENAME_OBJECT_PATTERN.search(command)
    if rename_match:
        old_name = rename_match.group(1) or rename_match.group(3)
        new_name = rename_match.group(2) or rename_match.group(4)
        if old_name and new_name and new_name not in ("해줘", "해", "줘"):
            plan["actions"].append({
                "type": "rename_object",
                "target": old_name,
                "new_name": new_name,
            })
            return plan

    # Add layer (e.g., "레이어 Water 추가")
    layer_match = ADD_LAYER_PATTERN.search(command)
    if layer_match:
        plan["actions"].append({
            "type": "add_layer",
            "layer_name": layer_match.group(1),
        })
        return plan

    # Refresh assets (e.g., "에셋 새로고침", "refresh")
    if REFRESH_PATTERN.search(command):
        plan["actions"].append({
            "type": "refresh_assets",
            "scope": "all",
            "mode": "force",
        })
        return plan

    # Read console (e.g., "콘솔 확인", "에러 확인")
    if READ_CONSOLE_PATTERN.search(command):
        action_item: dict = {"type": "read_console", "count": 20}
        if re.search(r"에러|error|오류", command, re.IGNORECASE):
            action_item["types"] = ["error"]
        elif re.search(r"경고|warning", command, re.IGNORECASE):
            action_item["types"] = ["warning"]
        plan["actions"].append(action_item)
        return plan

    # Line renderer (e.g., "라인 렌더러 생성")
    if LINE_RENDERER_PATTERN.search(command):
        name_match = re.search(r"이름[을를]?\s*([\w가-힣]+)", command) or re.search(r"name[:\s]+([\w]+)", command, re.IGNORECASE)
        name = name_match.group(1) if name_match else "Line_0"
        plan["actions"].append({
            "type": "create_line_renderer",
            "name": name,
            "positions": [
                {"x": 0, "y": 0, "z": 0},
                {"x": 5, "y": 0, "z": 0},
            ],
            "width": 0.1,
        })
        return plan

    # Set tag on object (e.g., "Tank_A 태그를 Vessel로 설정")
    tag_obj_match = SET_TAG_OBJECT_PATTERN.search(command)
    if tag_obj_match:
        target = tag_obj_match.group(1)
        tag = tag_obj_match.group(2)
        if target and tag and tag not in ("해줘", "해", "줘"):
            plan["actions"].append({
                "type": "set_tag_on_object",
                "target": target,
                "tag": tag,
            })
            return plan

    # Run tests (e.g., "테스트 실행", "test run")
    if RUN_TESTS_PATTERN.search(command):
        action_item = {"type": "run_tests", "mode": "EditMode"}
        if re.search(r"PlayMode|플레이모드|플레이\s*모드", command, re.IGNORECASE):
            action_item["mode"] = "PlayMode"
        plan["actions"].append(action_item)
        return plan

    # Create script (e.g., "스크립트 MyController 생성")
    script_match = CREATE_SCRIPT_PATTERN.search(command)
    if script_match:
        script_name = script_match.group(1) or script_match.group(2)
        plan["actions"].append({
            "type": "create_script",
            "name": script_name,
            "path": f"Assets/Scripts/{script_name}.cs",
            "contents": f"using UnityEngine;\n\npublic class {script_name} : MonoBehaviour\n{{\n    void Start()\n    {{\n    }}\n\n    void Update()\n    {{\n    }}\n}}\n",
        })
        return plan

    # English explicit creation: "create a red cube at (0,1,0) named MyCube"
    eng_create = ENGLISH_CREATE_PATTERN.search(command)
    if eng_create:
        adj_or_color = eng_create.group(1)  # might be color or adjective
        shape_word = eng_create.group(2).lower()
        eng_name = eng_create.group(3)
        shape = ENGLISH_SHAPE_MAP.get(shape_word, "Cube")
        name = eng_name or f"{shape}_0"
        position = _find_position(command)
        color = _find_color(command)

        action_item: dict = {"type": "create_primitive", "shape": shape, "name": name}
        if position:
            action_item["position"] = position
        plan["actions"].append(action_item)
        if color:
            plan["actions"].append({"type": "apply_material", "target": name, "color": color})
        return plan

    # Generic object creation
    shape = None
    if CAPSULE_PATTERN.search(command):
        shape = "Capsule"
    elif CYLINDER_PATTERN.search(command):
        shape = "Cylinder"
    elif SPHERE_PATTERN.search(command):
        shape = "Sphere"
    elif CUBE_PATTERN.search(command):
        shape = "Cube"

    if shape:
        name_match = re.search(r"이름[을를]?\s*([\w가-힣]+)", command) or re.search(r"name[:\s]+([\w]+)", command, re.IGNORECASE)
        name = name_match.group(1) if name_match else shape + "_0"
        position = _find_position(command)
        color = _find_color(command)

        # Check for parent
        parent = None
        parent_match = PARENT_PATTERN.search(command)
        if parent_match:
            parent = parent_match.group(1)

        action_item: dict = {
            "type": "create_primitive",
            "shape": shape,
            "name": name,
        }
        if position:
            action_item["position"] = position
        if parent:
            action_item["parent"] = parent
        plan["actions"].append(action_item)

        if color:
            plan["actions"].append({
                "type": "apply_material",
                "target": name,
                "color": color,
            })
        return plan

    # ── Fallback: color name detection ───────────────────────
    # Catches formats the main regex misses (e.g., "Floor에 스테인리스 적용")
    if re.search(r"변경|바꿔|적용|칠해|change|apply|색상|색|재질|color", command, re.IGNORECASE):
        color = _find_color(command)
        if color:
            # Find which color key matched to locate it in the command
            text_lower = command.lower()
            color_key = None
            for key in COLOR_MAP:
                if key in text_lower:
                    color_key = key
                    break
            if color_key:
                # Remove color name, action words, and particles to isolate target
                target_text = command
                target_text = re.sub(re.escape(color_key), "", target_text, count=1, flags=re.IGNORECASE).strip()
                target_text = re.sub(
                    r"(?:색상|색|재질|color|변경|바꿔|적용|칠해|change|apply|해줘|해|줘)\s*",
                    "", target_text, flags=re.IGNORECASE,
                ).strip()
                target_text = re.sub(
                    r"(?:으로|로|에서|에게|에|을|를|의|이|가|은|는)\s*",
                    "", target_text,
                ).strip()
                words = [w for w in target_text.split() if w and len(w) > 0]
                if words:
                    target = words[0]
                    plan["actions"].append({
                        "type": "apply_material",
                        "target": target,
                        "color": color,
                    })
                    return plan

    return None  # Cannot handle with templates


async def generate_plan_llm(command: str, context: str = "") -> Optional[dict]:
    """Generate a plan using Claude API."""
    if not config.ANTHROPIC_API_KEY:
        logger.warning("No ANTHROPIC_API_KEY set — cannot use LLM plan generation")
        return None

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

        user_message = command
        if context:
            user_message = f"Current scene context:\n{context}\n\nCommand: {command}"

        response = client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )

        text = response.content[0].text.strip()
        # Extract JSON from response (handle markdown code blocks)
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()

        plan = json.loads(text)
        return plan

    except ImportError:
        logger.error("anthropic package not installed. Run: pip install anthropic")
        return None
    except json.JSONDecodeError as e:
        logger.error("LLM returned invalid JSON: %s", e)
        return None
    except Exception as e:
        logger.error("LLM plan generation failed: %s", e)
        return None


# ── Multi-action command splitting ──────────────────────────

SPLIT_PATTERN = re.compile(
    r"\s*(?:;\s*|그리고\s+|하고\s+|\band\b\s+|\bthen\b\s+)",
    re.IGNORECASE,
)


def split_multi_command(command: str) -> list[str]:
    """Split a compound command into individual sub-commands."""
    parts = SPLIT_PATTERN.split(command)
    return [p.strip() for p in parts if p.strip()]


def merge_plans(plans: list[dict]) -> dict:
    """Merge multiple plans into a single plan with combined actions."""
    if not plans:
        return {"project": "My project", "scene": config.DEFAULT_SCENE, "description": "", "actions": []}
    merged = {
        "project": plans[0].get("project", "My project"),
        "scene": plans[0].get("scene", config.DEFAULT_SCENE),
        "description": " + ".join(p.get("description", "") for p in plans),
        "actions": [],
    }
    for p in plans:
        merged["actions"].extend(p.get("actions", []))
    return merged


def generate_multi_plan_template(command: str, scene_context: dict | None = None) -> Optional[dict]:
    """Parse a compound command and generate a merged plan."""
    parts = split_multi_command(command)
    if len(parts) <= 1:
        return None  # Not a multi-command

    plans = []
    for part in parts:
        plan = generate_plan_template(part, scene_context)
        if plan:
            plans.append(plan)

    if not plans:
        return None
    return merge_plans(plans)


# ── Spatial reference resolution ────────────────────────────

SPATIAL_REF_PATTERN = re.compile(
    r"([\w가-힣]+)\s*(?:의?\s*)?(?:옆에|옆|beside|next\s*to)",
    re.IGNORECASE,
)
SPATIAL_ABOVE_PATTERN = re.compile(
    r"([\w가-힣]+)\s*(?:의?\s*)?(?:위에|위|above|on\s*top)",
    re.IGNORECASE,
)
SPATIAL_FRONT_PATTERN = re.compile(
    r"([\w가-힣]+)\s*(?:의?\s*)?(?:앞에|앞|in\s*front)",
    re.IGNORECASE,
)
SPATIAL_BEHIND_PATTERN = re.compile(
    r"([\w가-힣]+)\s*(?:의?\s*)?(?:뒤에|뒤|behind|back)",
    re.IGNORECASE,
)
SPATIAL_CENTER_PATTERN = re.compile(
    r"(?:가운데|중앙|center|middle)",
    re.IGNORECASE,
)

DEFAULT_GAP = 2.0  # meters between objects


def resolve_spatial_reference(command: str, scene_context: dict | None) -> Optional[dict]:
    """Resolve spatial references like '탱크 옆에' to absolute coordinates.

    Args:
        command: Natural language command
        scene_context: Scene cache context with objects list
            {"objects": [{"name": "Tank_A", "position": {"x":2,"y":0,"z":0}, "scale": {"x":1,"y":2,"z":1}}, ...]}

    Returns:
        Position dict {"x", "y", "z"} or None if no spatial ref found
    """
    if not scene_context:
        return None

    raw_objects = scene_context.get("objects", {})
    objects = list(raw_objects.values()) if isinstance(raw_objects, dict) else raw_objects
    if not objects:
        return None

    def find_object(name: str) -> dict | None:
        name_lower = name.lower()
        for obj in objects:
            if obj.get("name", "").lower() == name_lower:
                return obj
        # Fuzzy match
        for obj in objects:
            if name_lower in obj.get("name", "").lower():
                return obj
        return None

    # "옆에" / beside
    m = SPATIAL_REF_PATTERN.search(command)
    if m:
        ref_obj = find_object(m.group(1))
        if ref_obj:
            pos = ref_obj.get("position", {"x": 0, "y": 0, "z": 0})
            scale = ref_obj.get("scale", {"x": 1, "y": 1, "z": 1})
            return {
                "x": round(pos["x"] + scale.get("x", 1) / 2 + DEFAULT_GAP, 2),
                "y": round(pos["y"], 2),
                "z": round(pos["z"], 2),
            }

    # "위에" / above
    m = SPATIAL_ABOVE_PATTERN.search(command)
    if m:
        ref_obj = find_object(m.group(1))
        if ref_obj:
            pos = ref_obj.get("position", {"x": 0, "y": 0, "z": 0})
            scale = ref_obj.get("scale", {"x": 1, "y": 1, "z": 1})
            return {
                "x": round(pos["x"], 2),
                "y": round(pos["y"] + scale.get("y", 1), 2),
                "z": round(pos["z"], 2),
            }

    # "앞에" / in front (negative z in Unity)
    m = SPATIAL_FRONT_PATTERN.search(command)
    if m:
        ref_obj = find_object(m.group(1))
        if ref_obj:
            pos = ref_obj.get("position", {"x": 0, "y": 0, "z": 0})
            scale = ref_obj.get("scale", {"x": 1, "y": 1, "z": 1})
            return {
                "x": round(pos["x"], 2),
                "y": round(pos["y"], 2),
                "z": round(pos["z"] - scale.get("z", 1) / 2 - DEFAULT_GAP, 2),
            }

    # "뒤에" / behind
    m = SPATIAL_BEHIND_PATTERN.search(command)
    if m:
        ref_obj = find_object(m.group(1))
        if ref_obj:
            pos = ref_obj.get("position", {"x": 0, "y": 0, "z": 0})
            scale = ref_obj.get("scale", {"x": 1, "y": 1, "z": 1})
            return {
                "x": round(pos["x"], 2),
                "y": round(pos["y"], 2),
                "z": round(pos["z"] + scale.get("z", 1) / 2 + DEFAULT_GAP, 2),
            }

    # "가운데" / center
    if SPATIAL_CENTER_PATTERN.search(command):
        if objects:
            xs = [o.get("position", {}).get("x", 0) for o in objects]
            zs = [o.get("position", {}).get("z", 0) for o in objects]
            return {
                "x": round(sum(xs) / len(xs), 2),
                "y": 0,
                "z": round(sum(zs) / len(zs), 2),
            }

    return None


# ── Intent disambiguation ───────────────────────────────────

def detect_disambiguation(command: str) -> list[dict] | None:
    """Detect if a command is ambiguous and return possible interpretations.

    Returns:
        List of {label, description, plan_modifier} dicts, or None if unambiguous.
    """
    count_match = re.search(r"(\d+)\s*개", command)
    if not count_match:
        return None

    count = int(count_match.group(1))
    if count <= 1:
        return None

    # Check if arrangement is specified
    has_arrangement = bool(
        re.search(r"격자|grid|일렬|줄|라인|line|원형|circle|삼각|triangle", command, re.IGNORECASE)
    )
    if has_arrangement:
        return None  # Already specified

    # Ambiguous: N objects with no arrangement
    return [
        {
            "label": f"일렬 배치 ({count}개, 2m 간격)",
            "description": "X축 방향으로 2m 간격 일렬 배치",
            "arrangement": "line",
        },
        {
            "label": f"격자 배치 ({count}개)",
            "description": "정사각형에 가까운 격자 배치",
            "arrangement": "grid",
        },
        {
            "label": f"원형 배치 ({count}개)",
            "description": "원형으로 균등 배치",
            "arrangement": "circle",
        },
    ]


def apply_arrangement(plan: dict, arrangement: str, count: int) -> dict:
    """Apply an arrangement modifier to a plan with multiple objects."""
    actions = plan.get("actions", [])
    create_actions = [a for a in actions if a.get("type") == "create_primitive"]

    if arrangement == "line":
        spacing = 2.0
        for i, action in enumerate(create_actions):
            action["position"] = {
                "x": round((i - (count - 1) / 2) * spacing, 2),
                "y": action.get("position", {}).get("y", 0.5),
                "z": 0,
            }
    elif arrangement == "grid":
        cols = max(1, int(math.ceil(math.sqrt(count))))
        rows = max(1, (count + cols - 1) // cols)
        spacing = 2.0
        for i, action in enumerate(create_actions):
            r, c = divmod(i, cols)
            action["position"] = {
                "x": round((c - (cols - 1) / 2) * spacing, 2),
                "y": action.get("position", {}).get("y", 0.5),
                "z": round((r - (rows - 1) / 2) * spacing, 2),
            }
    elif arrangement == "circle":
        radius = max(2.0, count * 0.5)
        for i, action in enumerate(create_actions):
            angle = 2 * math.pi * i / count
            action["position"] = {
                "x": round(radius * math.cos(angle), 2),
                "y": action.get("position", {}).get("y", 0.5),
                "z": round(radius * math.sin(angle), 2),
            }

    return plan


# ── Enhanced SYSTEM_PROMPT with scene context ───────────────

SYSTEM_PROMPT_WITH_CONTEXT = SYSTEM_PROMPT + """

Current scene objects (use these for spatial references):
{scene_context}

When the user refers to existing objects (e.g., "탱크 옆에", "Floor 위에"),
calculate positions relative to the objects listed above.
"""


# ── Main entry point (enhanced) ─────────────────────────────

async def generate_plan(
    command: str,
    context: str = "",
    scene_context: dict | None = None,
) -> tuple[dict | None, str]:
    """Generate a plan from a natural language command.

    Args:
        command: Natural language command (may be compound with ";")
        context: Working directory context string
        scene_context: Scene cache dict with object positions/scales

    Returns:
        (plan_dict_or_None, method_used: "template"|"template_multi"|"llm"|"failed")
    """
    # Try multi-command template first
    plan = generate_multi_plan_template(command, scene_context)
    if plan:
        return plan, "template_multi"

    # Try single template
    plan = generate_plan_template(command, scene_context)
    if plan:
        # Enhance with spatial references if available
        if scene_context:
            spatial_pos = resolve_spatial_reference(command, scene_context)
            if spatial_pos:
                for action in plan.get("actions", []):
                    if action.get("type") == "create_primitive" and "position" not in action:
                        action["position"] = spatial_pos
        return plan, "template"

    # Fall back to LLM with enriched context
    enriched_context = context
    if scene_context:
        obj_summary = ", ".join(
            f"{o['name']}({o.get('position', {}).get('x', 0):.0f},{o.get('position', {}).get('y', 0):.0f},{o.get('position', {}).get('z', 0):.0f})"
            for o in (list(scene_context.get("objects", {}).values()) if isinstance(scene_context.get("objects"), dict) else scene_context.get("objects", []))[:20]
        )
        enriched_context = f"{context}\nScene objects: {obj_summary}" if context else f"Scene objects: {obj_summary}"

    plan = await generate_plan_llm(command, enriched_context)
    if plan:
        return plan, "llm"

    return None, "failed"
