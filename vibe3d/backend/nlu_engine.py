"""Vibe3D NLU Engine — AI-First Natural Language → Unity MCP Command Conversion.

Uses Claude API as the primary intelligence layer for understanding all
natural language commands (Korean/English, with typo tolerance).
Falls back to template-based generation only when API key is unavailable.
"""

import json
import logging
import os
import re
from collections import defaultdict
from typing import Optional

logger = logging.getLogger("vibe3d.nlu")

# ── System prompt for NLU ────────────────────────────────────────

NLU_SYSTEM_PROMPT = """\
You are a Unity 3D industrial facility design AI assistant.
You understand natural language commands in Korean and English, even with typos or vague descriptions.
You convert commands into Unity MCP API call plans, or answer questions conversationally.

## Core Rules
1. ALWAYS respond in Korean (unless user writes in English).
2. Understand typos and informal language:
   - "바란색" = "파란색" = blue
   - "빨강" = "빨간색" = red
   - "녹색" / "녹쌕" = green
   - "큐부" = "큐브" = Cube
   - "실린더" = "실린더" = Cylinder
   - Understand context even with misspellings.
3. Positions are in meters (1 Unity unit = 1 meter).
4. When modifying objects, use exact names from the scene context provided.
5. For color changes on parent objects that have NO MeshRenderer, target their children (Body, Dome, etc.) instead.

## Korean ↔ English Object Name Mappings
- 기둥/컬럼 = Column (Col_*)
- 빔/보 = Beam (Beam_*)
- 바닥/플로어 = Floor (Floor_*)
- 벽/월 = Wall (Wall_*)
- 난간/레일링 = Railing (Railing_*, RailingPost_*)
- 통로/복도 = Walkway (Walkway_*, PassageWay*)
- 계단 = Stairs (Stairs_*)
- 배관/파이프 = Pipe (Pipe_*)
- 밸브 = Valve (Valve_*)
- 탱크/발효탱크 = Tank (KF-*)
- 조명/라이트 = Light (Light_*)
- 호이스트 = Hoist (Hoist_*)
- 건물/구조물/프레임/골격/골조 = Structure (Col_* + Beam_*)
- 외부 프레임 = External frame (Col_* + Beam_*)
- 플랫폼 = Platform (Platform_*, Slab_*)

## Color Reference (0-1 range)
- 빨간색/빨강/red: {"r":1,"g":0.2,"b":0.2,"a":1}
- 파란색/파랑/블루/바란/blue: {"r":0.25,"g":0.41,"b":0.88,"a":1}
- 초록색/녹색/green: {"r":0.2,"g":0.8,"b":0.3,"a":1}
- 노란색/노랑/yellow: {"r":1,"g":0.84,"b":0,"a":1}
- 하얀색/흰색/white: {"r":1,"g":1,"b":1,"a":1}
- 검정/검은색/black: {"r":0.1,"g":0.1,"b":0.1,"a":1}
- 주황색/오렌지/orange: {"r":1,"g":0.5,"b":0,"a":1}
- 보라색/퍼플/purple: {"r":0.6,"g":0.2,"b":0.8,"a":1}
- 스테인리스/메탈/silver: {"r":0.82,"g":0.82,"b":0.85,"a":1}
- 갈색/브라운/brown: {"r":0.55,"g":0.35,"b":0.17,"a":1}

## Action Types (63 available)

### Basic Object Operations
- create_primitive: {"type":"create_primitive","shape":"Cube|Sphere|Cylinder|Capsule|Plane|Quad","name":"...","position":{"x":0,"y":0,"z":0},"scale":{"x":1,"y":1,"z":1},"color":{"r":1,"g":1,"b":1,"a":1}}
- create_empty: {"type":"create_empty","name":"...","position":{...}}
- create_light: {"type":"create_light","light_type":"Directional|Point|Spot|Area","name":"...","position":{...},"intensity":1.0}
- modify_object: {"type":"modify_object","target":"Name","search_method":"by_name","position":{...},"rotation":{...},"scale":{...},"new_name":"..."}
- delete_object: {"type":"delete_object","target":"Name","search_method":"by_name"}
- duplicate_object: {"type":"duplicate_object","target":"Name","new_name":"...","position":{...}}
- move_relative: {"type":"move_relative","target":"Name","direction":"left|right|up|down|forward|back","distance":3.0}

### Material & Color
- apply_material: {"type":"apply_material","target":"Name","search_method":"by_name","color":{"r":0.5,"g":0.5,"b":0.5,"a":1.0}}
- create_material: {"type":"create_material","name":"Steel","shader":"Universal Render Pipeline/Lit","color":{...}}
- assign_material: {"type":"assign_material","target":"Name","material_path":"Assets/Materials/M.mat"}

### Components & Physics
- add_component: {"type":"add_component","target":"Name","component_type":"Rigidbody","properties":{"mass":100}}
- remove_component: {"type":"remove_component","target":"Name","component_type":"Rigidbody"}
- set_component_property: {"type":"set_component_property","target":"Name","component_type":"Rigidbody","property":"mass","value":50}

### Scene Management
- screenshot: {"type":"screenshot","filename":"my_shot"}
- save_scene: {"type":"save_scene"}
- load_scene: {"type":"load_scene","name":"sceneName"}

### Texture & Pattern
- create_texture: {"type":"create_texture","name":"MyTexture","width":256,"height":256,"pattern":"stripes_diag","fill_color":{"r":1,"g":1,"b":0,"a":1},"path":"Assets/Textures/MyTexture.png"}
  - pattern values: "checkerboard", "stripes", "stripes_h", "stripes_v", "stripes_diag", "dots", "grid", "brick"
- apply_texture_pattern: {"type":"apply_texture_pattern","path":"Assets/Textures/MyTexture.png","pattern":"stripes_diag","palette":[[255,255,0],[0,0,0]],"pattern_size":32}
  - Must include "path" (the texture asset path) and "pattern" (same enum as above)
- apply_material after texture: use assign_material to apply the material to the target object

### Other
- create_prefab, instantiate_prefab, modify_prefab
- create_particle_system, create_vfx, create_line_renderer
- import_asset, search_assets, create_folder
- create_script, execute_menu

## Response Modes

### For Commands (create/modify/delete/color/move/etc.)
Return a JSON plan:
{
    "type": "plan",
    "confirmation_message": "사용자에게 보여줄 한국어 설명 (예: '건물 외부 프레임(기둥 12개, 빔 8개)의 색상을 파란색으로 변경합니다.')",
    "plan_description": "Brief description",
    "project": "My project",
    "scene": "bio-plants",
    "actions": [...]
}

### For Questions (what/how/where/etc.)
Return a conversational response:
{
    "type": "response",
    "content": "한국어로 된 답변..."
}

## Important
- The "confirmation_message" field MUST be a clear, friendly Korean explanation of exactly what will happen.
  Include specific object names and counts. This message will be shown to the user for approval.
- Example: "파란색으로 변경할 대상: Col_01~Col_12 (기둥 12개), Beam_01~Beam_08 (빔 8개). 총 20개 오브젝트의 색상을 파란색(R:0.25, G:0.41, B:0.88)으로 변경합니다."
- When uncertain about exact object names, use the scene context to find matching objects.
- Output ONLY valid JSON, no markdown code blocks.
"""

DRAWING_ANALYSIS_PROMPT = """\
Analyze this engineering drawing image and extract information in JSON format.

For P&ID drawings, extract:
1. vessels: [{name, type, volume, diameter, height}]
2. pipes: [{from, to, size_JIS, medium}]
3. valves: [{name, type, pipe_connection}]
4. instruments: [{name, type, vessel}]
5. pumps: [{name, type, vessel_connection}]
6. heat_exchangers: [{name, vessel_connection}]
7. safety_devices: [{name, type, vessel}]

For Layout drawings, extract:
1. building: {width_mm, depth_mm, height_mm}
2. zones: [{name, x_range, z_range, purpose}]
3. equipment_positions: [{name, x_mm, z_mm, orientation_deg}]

Return ONLY valid JSON, no markdown.
"""


class NLUEngine:
    """AI-first natural language understanding engine for Unity commands."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._client = None
        self._conversation_history: list[dict] = []
        self._max_history = 20

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def _get_client(self):
        if self._client is None and self.available:
            try:
                import anthropic
                self._client = anthropic.Anthropic(api_key=self.api_key)
            except ImportError:
                logger.warning("anthropic package not installed")
                return None
        return self._client

    async def process_command(
        self, user_input: str, scene_context: dict, conversation_mode: bool = False
    ) -> Optional[dict]:
        """Convert natural language to MCP command plan using Claude API.

        Args:
            user_input: User's natural language command
            scene_context: Current scene state (objects, bounds, etc.)
            conversation_mode: If True, maintain conversation history

        Returns:
            Plan dict with actions, or None if processing fails
        """
        client = self._get_client()
        if not client:
            return None

        scene_summary = self._summarize_scene(scene_context)

        user_message = f"""현재 씬 상태:
{scene_summary}

사용자 명령: {user_input}

위 명령을 분석하여 Unity MCP 실행 플랜을 JSON으로 생성하세요. JSON만 출력하세요."""

        messages = []
        if conversation_mode and self._conversation_history:
            messages.extend(self._conversation_history[-self._max_history:])
        messages.append({"role": "user", "content": user_message})

        try:
            import asyncio
            response = await asyncio.to_thread(
                client.messages.create,
                model="claude-sonnet-4-5-20250929",
                max_tokens=4096,
                system=NLU_SYSTEM_PROMPT,
                messages=messages,
            )

            content = response.content[0].text

            if conversation_mode:
                self._conversation_history.append({"role": "user", "content": user_message})
                self._conversation_history.append({"role": "assistant", "content": content})

            plan = self._extract_json(content)
            if plan and "actions" in plan:
                return plan

            logger.warning("NLU response missing 'actions': %s", content[:200])
            return None

        except Exception as e:
            logger.error("NLU processing failed: %s", e)
            return None

    async def analyze_drawing(self, image_path: str) -> Optional[dict]:
        """Analyze an engineering drawing using Claude Vision API."""
        client = self._get_client()
        if not client:
            return None

        try:
            import base64
            import asyncio

            with open(image_path, "rb") as f:
                img_data = base64.standard_b64encode(f.read()).decode()

            ext = os.path.splitext(image_path)[1].lower()
            media_types = {
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".gif": "image/gif",
                ".webp": "image/webp",
            }
            media_type = media_types.get(ext, "image/png")

            response = await asyncio.to_thread(
                client.messages.create,
                model="claude-sonnet-4-5-20250929",
                max_tokens=4096,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": img_data,
                            },
                        },
                        {"type": "text", "text": DRAWING_ANALYSIS_PROMPT},
                    ],
                }],
            )

            content = response.content[0].text
            return self._extract_json(content)

        except Exception as e:
            logger.error("Drawing analysis failed: %s", e)
            return None

    async def chat(
        self, message: str, scene_context: dict
    ) -> dict:
        """Process any user input — commands, questions, or conversation.

        This is the unified entry point for all user messages.
        The LLM decides whether to generate a plan or respond conversationally.

        Returns:
            {
                "type": "plan" | "response",
                "content": str (for response) or dict (for plan),
                "plan_description": str (for plan),
                "confirmation_message": str (for plan — user-friendly explanation),
                "method": str,
            }
        """
        client = self._get_client()

        if not client:
            # Without API, try template-based plan generation
            from .plan_generator import generate_plan
            import asyncio
            plan, method = await generate_plan(message, scene_context=scene_context)
            if plan:
                # Generate a basic confirmation message from the plan
                actions = plan.get("actions", [])
                desc = plan.get("description", "")
                confirmation = desc or f"총 {len(actions)}개 작업을 실행합니다."
                return {
                    "type": "plan",
                    "content": plan,
                    "plan_description": f"템플릿 기반 플랜 ({len(actions)}개 작업)",
                    "confirmation_message": confirmation,
                    "method": method,
                }
            return {
                "type": "response",
                "content": "명령을 이해할 수 없습니다. ANTHROPIC_API_KEY를 설정하면 "
                           "AI가 자연어를 더 정확하게 이해할 수 있습니다.",
            }

        scene_summary = self._summarize_scene(scene_context)

        # Build unified system prompt with scene context
        chat_system = f"""{NLU_SYSTEM_PROMPT}

## 현재 씬 상태
{scene_summary}
"""

        messages = list(self._conversation_history[-self._max_history:])
        messages.append({"role": "user", "content": message})

        try:
            import asyncio
            response = await asyncio.to_thread(
                client.messages.create,
                model="claude-sonnet-4-5-20250929",
                max_tokens=4096,
                system=chat_system,
                messages=messages,
            )

            content = response.content[0].text

            # Store conversation
            self._conversation_history.append({"role": "user", "content": message})
            self._conversation_history.append({"role": "assistant", "content": content})

            # Try to parse as JSON plan
            parsed = self._extract_json(content)
            if parsed:
                if parsed.get("type") == "response":
                    return {
                        "type": "response",
                        "content": parsed.get("content", content),
                    }
                if "actions" in parsed:
                    return {
                        "type": "plan",
                        "content": parsed,
                        "plan_description": parsed.get(
                            "plan_description", f"AI 플랜 ({len(parsed['actions'])}개 작업)"
                        ),
                        "confirmation_message": parsed.get(
                            "confirmation_message",
                            parsed.get("plan_description", f"총 {len(parsed['actions'])}개 작업을 실행합니다."),
                        ),
                        "method": "llm",
                    }

            # Plain text response
            return {"type": "response", "content": content}

        except Exception as e:
            logger.error("Chat processing failed: %s", e)
            return {
                "type": "response",
                "content": f"처리 중 오류가 발생했습니다: {str(e)}",
            }

    def clear_history(self):
        """Clear conversation history."""
        self._conversation_history.clear()

    def get_history(self) -> list[dict]:
        """Get conversation history."""
        return list(self._conversation_history)

    # ── Private helpers ──────────────────────────────────────────

    def _summarize_scene(self, scene_context: dict) -> str:
        """Create a rich scene summary grouped by hierarchy for the AI prompt.

        Groups objects by parent path prefix, shows counts and representative names.
        Capped at ~2000 tokens for prompt efficiency.
        """
        if not scene_context:
            return "빈 씬 (오브젝트 없음)"

        objects = scene_context.get("objects", {})
        if isinstance(objects, dict):
            obj_list = list(objects.values())
        else:
            obj_list = objects or []

        if not obj_list:
            return "빈 씬 (오브젝트 없음)"

        total = len(obj_list)

        # Group objects by path prefix (first 2 segments)
        groups: dict[str, list[dict]] = defaultdict(list)
        for obj in obj_list:
            if not isinstance(obj, dict):
                continue
            path = obj.get("path", "")
            name = obj.get("name", "?")
            # Extract group from path: "BioFacility/Structure/Col_01" → "BioFacility/Structure"
            parts = path.strip("/").split("/") if path else []
            if len(parts) >= 2:
                group_key = "/".join(parts[:2])
            elif parts:
                group_key = parts[0]
            else:
                group_key = "(root)"
            groups[group_key].append(obj)

        # Build summary
        lines = [f"씬: 총 {total}개 오브젝트"]

        # Bounds
        bounds = scene_context.get("bounds", {})
        if bounds:
            bmin = bounds.get("min", {})
            bmax = bounds.get("max", {})
            lines.append(
                f"범위: X[{bmin.get('x', 0):.1f}~{bmax.get('x', 0):.1f}] "
                f"Y[{bmin.get('y', 0):.1f}~{bmax.get('y', 0):.1f}] "
                f"Z[{bmin.get('z', 0):.1f}~{bmax.get('z', 0):.1f}]"
            )

        lines.append("")

        # Show each group with representative names
        for group_key in sorted(groups.keys()):
            members = groups[group_key]
            names = [m.get("name", "?") for m in members]
            count = len(members)

            # Collect representative names (first 5 unique prefixes)
            seen_prefixes: set[str] = set()
            representatives: list[str] = []
            for n in names:
                # Get prefix before underscore or digit
                prefix = re.split(r'[_\d]', n)[0] if n else ""
                if prefix and prefix not in seen_prefixes:
                    seen_prefixes.add(prefix)
                    representatives.append(n)
                if len(representatives) >= 5:
                    break

            rep_str = ", ".join(representatives)
            if count > len(representatives):
                rep_str += f" 외 {count - len(representatives)}개"

            lines.append(f"[{group_key}] ({count}개): {rep_str}")

        # Full object name list (for LLM to do exact matching)
        lines.append("")
        lines.append("전체 오브젝트 이름 목록:")
        all_names = []
        for obj in obj_list:
            if isinstance(obj, dict):
                all_names.append(obj.get("name", "?"))

        # Show names in compact form, max ~100 names
        if len(all_names) <= 100:
            lines.append(", ".join(all_names))
        else:
            lines.append(", ".join(all_names[:100]))
            lines.append(f"... 외 {len(all_names) - 100}개")

        return "\n".join(lines)

    def _is_question(self, text: str) -> bool:
        """Detect if the text is a question rather than a command."""
        question_patterns = [
            r"\?$", r"뭐야", r"뭔가요", r"얼마", r"어디", r"어떻게",
            r"무엇", r"몇\s*개", r"있어\?", r"있나요", r"보여줘",
            r"알려줘", r"what\s", r"how\s", r"where\s", r"which\s",
            r"show\s+me", r"tell\s+me", r"list\s",
        ]
        text_lower = text.lower().strip()
        return any(re.search(p, text_lower) for p in question_patterns)

    def _extract_json(self, text: str) -> Optional[dict]:
        """Extract JSON from text that may contain markdown or extra content."""
        # Try direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try extracting from code block
        patterns = [
            r"```json\s*([\s\S]*?)\s*```",
            r"```\s*([\s\S]*?)\s*```",
            r"\{[\s\S]*\}",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                try:
                    candidate = match.group(1) if match.lastindex else match.group(0)
                    return json.loads(candidate)
                except (json.JSONDecodeError, IndexError):
                    continue

        return None
