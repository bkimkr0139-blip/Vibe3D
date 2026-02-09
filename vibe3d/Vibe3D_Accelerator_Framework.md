# Vibe3D Accelerator Framework
## 자연어 기반 Unity 3D 산업 디자인 통합 개발 프레임워크

**Version:** 1.0
**Date:** 2026-02-08
**Purpose:** 이 문서를 읽고 Claude가 Vibe3D Accelerator를 완전히 구축할 수 있도록 하는 통합 구축 문서

---

## 목차

1. [프레임워크 개요](#1-프레임워크-개요)
2. [시스템 아키텍처](#2-시스템-아키텍처)
3. [MCP 통신 레이어](#3-mcp-통신-레이어)
4. [Unity MCP 전체 API 레퍼런스](#4-unity-mcp-전체-api-레퍼런스)
5. [소스 파일 분석 파이프라인](#5-소스-파일-분석-파이프라인)
6. [자연어 → Unity 명령 변환 엔진](#6-자연어--unity-명령-변환-엔진)
7. [산업 표준 3D 컴포넌트 라이브러리](#7-산업-표준-3d-컴포넌트-라이브러리)
8. [UI/UX 설계 명세](#8-uiux-설계-명세)
9. [프로젝트 구조 및 구현 가이드](#9-프로젝트-구조-및-구현-가이드)
10. [검증된 패턴과 워크어라운드](#10-검증된-패턴과-워크어라운드)
11. [구현 로드맵](#11-구현-로드맵)

---

## 1. 프레임워크 개요

### 1.1 비전
Vibe3D Accelerator는 **자연어로 Unity 3D 산업 시설을 설계하는 AI 기반 개발 도구**이다.
사용자가 "KF-7KL 발효조에 pH 프로브를 추가해줘"라고 말하면, AI가 이를 해석하여 Unity MCP 명령으로 변환하고, 결과를 실시간으로 보여준다.

### 1.2 핵심 기능
```
┌─────────────────────────────────────────────────────────────┐
│                    Vibe3D Accelerator                        │
├─────────────────────────────────────────────────────────────┤
│  [1] 자연어 작업 지시  → Unity 전체 기능 제어               │
│  [2] 엔지니어링 도면 분석 → 자동 3D 모델 생성               │
│  [3] P&ID/Layout 기반 검증 → 불일치 자동 감지/수정          │
│  [4] 산업 표준 컴포넌트 라이브러리 → 원클릭 배치            │
│  [5] 실시간 미리보기 + 스크린샷 기반 피드백                 │
│  [6] 프로젝트 히스토리 + 실행 취소/재실행                   │
└─────────────────────────────────────────────────────────────┘
```

### 1.3 실증 사례
바이오 발효 디지털 트윈 프로젝트에서 검증 완료:
- **653개 산업 표준 오브젝트** 생성 (Structure:51, Vessels:260, Piping:206, ControlRoom:22, Utilities:114)
- P&ID 도면 8장 + Layout 도면 2장 분석 → Unity 씬 자동 구축
- 530+ MCP API 호출 성공적 실행

---

## 2. 시스템 아키텍처

### 2.1 전체 구조
```
┌──────────────────────────────────────────────────────────────────┐
│                        사용자 (User)                              │
│  "7KL 발효조에 Steam 파이프 연결하고 빨간색으로 칠해줘"         │
└────────────────────────┬─────────────────────────────────────────┘
                         │ 자연어 입력 (Korean/English)
                         ▼
┌──────────────────────────────────────────────────────────────────┐
│                   Vibe3D Accelerator UI                           │
│  ┌─────────────┐ ┌──────────────┐ ┌───────────────────────┐     │
│  │  Chat Panel  │ │ Scene Viewer │ │ Component Library     │     │
│  │  (자연어입력) │ │ (3D Preview) │ │ (드래그&드롭)         │     │
│  │             │ │              │ │                       │     │
│  │  Progress   │ │  Screenshot  │ │ [Vessel] [Pipe]       │     │
│  │  Timeline   │ │  Feedback    │ │ [Valve] [Pump]        │     │
│  └─────────────┘ └──────────────┘ └───────────────────────┘     │
│  ┌─────────────────────────────────────────────────────────┐     │
│  │  Source File Panel (P&ID/Layout 도면 뷰어)              │     │
│  └─────────────────────────────────────────────────────────┘     │
└────────────────────────┬─────────────────────────────────────────┘
                         │ REST API + WebSocket
                         ▼
┌──────────────────────────────────────────────────────────────────┐
│                   Backend (FastAPI)                               │
│  ┌───────────────┐ ┌──────────────┐ ┌────────────────────┐      │
│  │ NLU Engine    │ │ MCP Bridge   │ │ File Analyzer      │      │
│  │ (Claude API)  │ │ (Session Mgr)│ │ (PNG/PDF/DWG)      │      │
│  │               │ │              │ │                    │      │
│  │ Intent→Cmd   │ │ Batch Exec   │ │ Drawing Parser     │      │
│  │ Entity Extract│ │ Error Handle │ │ P&ID Extractor     │      │
│  └───────┬───────┘ └──────┬───────┘ └────────────────────┘      │
│          │                │                                      │
│  ┌───────▼────────────────▼──────────────────────────────┐      │
│  │              Command Orchestrator                      │      │
│  │  - 다단계 명령 분해 (Multi-step Decomposition)         │      │
│  │  - 의존성 그래프 기반 실행 순서 결정                   │      │
│  │  - 롤백/리트라이 지원                                  │      │
│  └───────────────────────┬───────────────────────────────┘      │
└──────────────────────────┼───────────────────────────────────────┘
                           │ HTTP POST (JSON-RPC 2.0)
                           │ Streamable HTTP + SSE
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│              Unity Editor + MCP for Unity Server                  │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │  MCP Server (uvicorn, port 8080)                         │    │
│  │  Protocol: Streamable HTTP, Session-based                │    │
│  │  Tools: 25+ Unity operation tools                        │    │
│  └──────────────────────────────────────────────────────────┘    │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │  Unity Scene (씬 오브젝트, 머터리얼, 프리팹, 스크립트)   │    │
│  └──────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────┘
```

### 2.2 기술 스택

| 레이어 | 기술 | 역할 |
|--------|------|------|
| **Frontend** | Next.js 14+ (React) + TailwindCSS | 채팅 UI, 도면 뷰어, 컴포넌트 라이브러리 |
| **Backend** | FastAPI (Python 3.12) | REST API, WebSocket, MCP Bridge |
| **AI Engine** | Claude API (claude-sonnet-4-5-20250929) | 자연어→Unity 명령 변환, 도면 분석 |
| **MCP Bridge** | HTTP Client (httpx/aiohttp) | Unity MCP 세션 관리, 명령 실행 |
| **Unity** | Unity 6 LTS + MCP for Unity 2.14+ | 3D 씬 렌더링, 오브젝트 관리 |
| **File Analysis** | Pillow, pdf2image, ezdxf | PNG/PDF/DWG 파일 파싱 |
| **State** | SQLite + Redis | 프로젝트 상태, 명령 히스토리, 캐시 |

---

## 3. MCP 통신 레이어

### 3.1 프로토콜 상세

Unity MCP는 **Streamable HTTP** 프로토콜을 사용한다.

```
Protocol:     JSON-RPC 2.0 over HTTP POST
Endpoint:     http://localhost:8080/mcp
Content-Type: application/json
Accept:       application/json, text/event-stream
Response:     Server-Sent Events (SSE) format
Session:      mcp-session-id 헤더로 관리
```

### 3.2 세션 생명주기

```python
class MCPSession:
    """MCP 세션 관리자 - 검증된 구현"""

    def __init__(self, url="http://localhost:8080/mcp"):
        self.url = url
        self.session_id = None
        self.call_id = 0

    async def initialize(self):
        """Step 1: 세션 초기화"""
        response = await httpx.AsyncClient().post(
            self.url,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream"
            },
            json={
                "jsonrpc": "2.0", "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "vibe3d", "version": "1.0"}
                }
            }
        )
        # 응답 헤더에서 세션 ID 추출
        self.session_id = response.headers.get("mcp-session-id")

        """Step 2: 핸드셰이크 완료"""
        await httpx.AsyncClient().post(
            self.url,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "mcp-session-id": self.session_id
            },
            json={"jsonrpc": "2.0", "method": "notifications/initialized"}
        )
        return self.session_id

    async def call_tool(self, tool_name: str, arguments: dict, timeout=30):
        """Step 3: 도구 호출"""
        self.call_id += 1
        response = await httpx.AsyncClient().post(
            self.url,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "mcp-session-id": self.session_id
            },
            json={
                "jsonrpc": "2.0", "id": self.call_id,
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments}
            },
            timeout=timeout
        )
        # SSE 응답 파싱
        for line in response.text.split('\n'):
            if line.startswith('data: '):
                data = json.loads(line[6:])
                content = data["result"]["content"][0]["text"]
                return json.loads(content)
        return None
```

### 3.3 핵심 주의사항 (실전 검증됨)

```python
# 1. Windows 인코딩 문제 - 반드시 UTF-8 지정
subprocess.run(cmd, encoding='utf-8', errors='replace')

# 2. 세션 만료 - 자동 재초기화 필요
async def safe_call(self, tool, args):
    try:
        return await self.call_tool(tool, args)
    except SessionExpiredError:
        await self.initialize()  # 재연결
        return await self.call_tool(tool, args)

# 3. batch_execute 성공 카운트 파싱 주의
# results[].success 가 아닌 전체 result 구조 확인 필요
# batch는 최대 25개 명령까지 지원

# 4. find_gameobjects는 정확한 이름 매치만 지원
# 부분 검색은 get_hierarchy로 parent 하위 탐색 필요

# 5. 대량 데이터 반환 시 페이지네이션 필수
# page_size, cursor, next_cursor 패턴 사용
```

---

## 4. Unity MCP 전체 API 레퍼런스

### 4.1 GameObject 관리 (manage_gameobject)

```json
// CREATE - 오브젝트 생성
{
    "action": "create",
    "name": "MyObject",
    "primitive_type": "Cube|Sphere|Cylinder|Capsule|Plane|Quad",
    "parent": "ParentPath/ChildPath",
    "position": [x, y, z],        // 부모 기준 LOCAL 좌표
    "rotation": [rx, ry, rz],     // 오일러 각도
    "scale": [sx, sy, sz]
}

// MODIFY - 오브젝트 수정
{
    "action": "modify",
    "target": "ObjectName",
    "search_method": "by_name|by_id|by_path|by_tag|by_layer",
    "position": [x, y, z],        // 선택적
    "rotation": [rx, ry, rz],     // 선택적
    "scale": [sx, sy, sz],        // 선택적
    "new_name": "NewName",        // 이름 변경
    "include_properties": true     // true면 현재 상태 읽기 (수정없이)
}

// DELETE - 오브젝트 삭제
{
    "action": "delete",
    "target": "ObjectName",
    "search_method": "by_name"
}

// DUPLICATE - 오브젝트 복제
{
    "action": "duplicate",
    "target": "ObjectName",
    "search_method": "by_name"
}

// MOVE_RELATIVE - 상대 이동
{
    "action": "move_relative",
    "target": "ObjectName",
    "direction": "left|right|up|down|forward|back",
    "distance": 2.0
}
```

### 4.2 머터리얼 관리 (manage_material)

```json
// 렌더러 색상 설정 (가장 자주 사용)
{
    "action": "set_renderer_color",
    "target": "ObjectName",
    "color": [r, g, b, a],          // 0.0~1.0
    "mode": "property_block",        // shared|instance|property_block
    "search_method": "by_name"
}

// 머터리얼 생성
{
    "action": "create",
    "material_path": "Assets/Materials/MyMat.mat",
    "shader": "Universal Render Pipeline/Lit",
    "properties": {"_Color": [1,0,0,1], "_Metallic": 0.5}
}

// 머터리얼 할당
{
    "action": "assign_material_to_renderer",
    "target": "ObjectName",
    "material_path": "Assets/Materials/MyMat.mat"
}

// 머터리얼 정보 조회
{
    "action": "get_material_info",
    "material_path": "Assets/Materials/MyMat.mat"
}
```

### 4.3 씬 관리 (manage_scene)

```json
// 현재 씬 정보
{"action": "get_active"}

// 계층 구조 조회 (페이지네이션 필수!)
{
    "action": "get_hierarchy",
    "parent": "BioFacility/Vessels",   // 선택적: 특정 부모 하위만
    "page_size": 50,                    // 권장: 50
    "max_depth": 1,                     // 0=직접 자식만, 1=손자까지
    "cursor": 0                         // 다음 페이지
}
// 응답에 next_cursor가 null이면 마지막 페이지

// 씬 저장
{"action": "save"}

// 스크린샷
{
    "action": "screenshot",
    "screenshot_file_name": "my_screenshot"  // .png 자동 추가
}

// 씬 로드
{"action": "load", "path": "Assets/Scenes/MyScene.unity"}

// 빌드 설정
{"action": "get_build_settings"}
```

### 4.4 컴포넌트 관리 (manage_components)

```json
// 컴포넌트 추가
{
    "action": "add",
    "target": "ObjectName",
    "component_type": "Rigidbody",
    "properties": {"mass": 10, "useGravity": true}
}

// 컴포넌트 속성 설정
{
    "action": "set_property",
    "target": "ObjectName",
    "component_type": "Transform",
    "property": "position",
    "value": {"x": 1, "y": 2, "z": 3}
}

// 컴포넌트 제거
{
    "action": "remove",
    "target": "ObjectName",
    "component_type": "BoxCollider"
}
```

### 4.5 에셋 관리 (manage_asset)

```json
// 에셋 검색 (페이지네이션 필수!)
{
    "action": "search",
    "path": "Assets",
    "search_pattern": "*.prefab",
    "filter_type": "Prefab",
    "page_size": 25,
    "page_number": 1,
    "generate_preview": false         // 미리보기 비활성 (대용량 방지)
}

// 폴더 생성
{"action": "create_folder", "path": "Assets/MyFolder"}

// 에셋 정보 조회
{"action": "get_info", "path": "Assets/Materials/MyMat.mat"}

// 에셋 이동
{"action": "move", "path": "Assets/Old/file.mat", "destination": "Assets/New/"}

// 에셋 삭제
{"action": "delete", "path": "Assets/Temp/file.mat"}
```

### 4.6 프리팹 관리 (manage_prefabs)

```json
// 프리팹 정보
{"action": "get_info", "prefab_path": "Assets/Prefabs/MyPrefab.prefab"}

// 프리팹 계층 구조
{"action": "get_hierarchy", "prefab_path": "Assets/Prefabs/MyPrefab.prefab"}

// GameObject에서 프리팹 생성
{
    "action": "create_from_gameobject",
    "target": "SceneObject",
    "prefab_path": "Assets/Prefabs/NewPrefab.prefab"
}

// 프리팹 내용 수정 (헤드리스)
{
    "action": "modify_contents",
    "prefab_path": "Assets/Prefabs/MyPrefab.prefab",
    "create_child": [
        {"name": "Child1", "primitive_type": "Sphere", "position": [1,0,0]},
        {"name": "Child2", "primitive_type": "Cube", "parent": "Child1"}
    ]
}
```

### 4.7 오브젝트 검색 (find_gameobjects)

```json
{
    "search_term": "KF-70L",
    "search_method": "by_name|by_tag|by_layer|by_component|by_path|by_id",
    "include_inactive": false,
    "page_size": 50,
    "cursor": null
}
// 주의: by_name은 정확한 이름 매치만 지원
```

### 4.8 에디터 제어 (manage_editor)

```json
// 플레이 모드
{"action": "play"}
{"action": "pause"}
{"action": "stop"}

// 태그/레이어 관리
{"action": "add_tag", "tag_name": "Equipment"}
{"action": "add_layer", "layer_name": "Piping"}
```

### 4.9 스크립트 관리

```json
// C# 스크립트 생성 (create_script)
{
    "path": "Assets/Scripts/MyScript.cs",
    "contents": "using UnityEngine;\npublic class MyScript : MonoBehaviour { }"
}

// 구조적 편집 (script_apply_edits) - 메서드 단위 안전한 편집
{
    "name": "MyScript",
    "path": "Assets/Scripts",
    "edits": [
        {
            "op": "replace_method",
            "className": "MyScript",
            "methodName": "Update",
            "replacement": "void Update() { transform.Rotate(Vector3.up); }"
        }
    ]
}

// 텍스트 편집 (apply_text_edits) - 정확한 위치 기반
{
    "uri": "Assets/Scripts/MyScript.cs",
    "edits": [
        {"startLine": 10, "startCol": 1, "endLine": 15, "endCol": 1, "newText": "// replaced"}
    ]
}
```

### 4.10 배치 실행 (batch_execute)

```json
{
    "commands": [
        {
            "tool": "manage_gameobject",
            "params": {"action": "create", "name": "Obj1", "primitive_type": "Cube"}
        },
        {
            "tool": "manage_material",
            "params": {"action": "set_renderer_color", "target": "Obj1", "color": [1,0,0,1]}
        }
    ],
    "parallel": false,        // 읽기전용만 병렬 가능
    "fail_fast": false,       // true면 첫 실패시 중단
    "max_parallelism": null   // 병렬 워커 수
}
// 최대 25개 명령/배치
```

### 4.11 기타 도구

```json
// 콘솔 읽기
{"action": "get", "types": ["error", "warning"], "count": 10}
{"action": "clear"}

// 텍스처 생성
{"action": "create", "path": "Assets/Textures/grid.png", "width": 256, "height": 256,
 "pattern": "checkerboard", "palette": [[255,0,0],[255,255,255]], "pattern_size": 32}

// 셰이더 관리
{"action": "create", "name": "MyShader", "path": "Assets/Shaders/", "contents": "..."}

// VFX 관리
{"action": "particle_create", "target": "MyObject"}

// 테스트 실행
{"mode": "EditMode"} → job_id 반환 → get_test_job으로 폴링

// 에셋 새로고침
{"mode": "force", "compile": "request", "wait_for_ready": true}

// 메뉴 아이템 실행
{"menu_path": "GameObject/3D Object/Cube"}

// ScriptableObject 관리
{"action": "create", "type_name": "MySOType", "folder_path": "Assets/Data", "asset_name": "Config1"}
```

---

## 5. 소스 파일 분석 파이프라인

### 5.1 지원 파일 형식

| 형식 | 용도 | 분석 방법 |
|------|------|-----------|
| **PNG/JPG** | P&ID 도면, 레이아웃 | Claude Vision API로 직접 분석 |
| **PDF** | 엔지니어링 문서 | pdf2image → PNG 변환 → Vision 분석 |
| **DWG** | CAD 도면 | ezdxf 라이브러리로 엔티티 추출 |
| **DXF** | CAD 교환 형식 | ezdxf 직접 파싱 |

### 5.2 도면 분석 프로세스

```python
class DrawingAnalyzer:
    """엔지니어링 도면 분석기"""

    async def analyze_pnid(self, image_path: str) -> PnIDResult:
        """P&ID 도면 분석 - Claude Vision 사용"""
        image_data = base64.b64encode(open(image_path, 'rb').read())

        response = await claude.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=4096,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": image_data
                    }},
                    {"type": "text", "text": """
이 P&ID 도면을 분석하여 다음 정보를 JSON으로 추출해주세요:
1. vessels: [{name, type, volume, diameter, height}]
2. pipes: [{from, to, size_JIS, medium(steam/cws/air/drain)}]
3. valves: [{name, type(ball/gate/control/check), pipe_connection}]
4. instruments: [{name, type(pH/DO/Level/Temp), vessel}]
5. pumps: [{name, type, vessel_connection}]
6. heat_exchangers: [{name, vessel_connection}]
7. safety_devices: [{name, type(PRV/rupture_disc), vessel}]
"""}
                ]
            }]
        )
        return PnIDResult.parse(response.content[0].text)

    async def analyze_layout(self, image_path: str) -> LayoutResult:
        """레이아웃 도면 분석"""
        # 건물 치수, 장비 배치, 구역 구분 추출
        response = await claude.messages.create(
            model="claude-sonnet-4-5-20250929",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {...}},
                    {"type": "text", "text": """
이 레이아웃 도면을 분석하여 JSON으로:
1. building: {width_mm, depth_mm, height_mm, frame_type}
2. zones: [{name, x_range, z_range, purpose}]
3. equipment_positions: [{name, x_mm, z_mm, orientation_deg}]
4. access_points: [{type(door/passage/stairs), position}]
5. utilities: [{name, type, position}]
"""}
                ]
            }]
        )
        return LayoutResult.parse(response.content[0].text)

    async def compare_pnid_vs_scene(self, pnid: PnIDResult, scene_objects: list) -> list:
        """P&ID와 씬 불일치 감지"""
        gaps = []
        for vessel in pnid.vessels:
            if vessel.name not in [o.name for o in scene_objects]:
                gaps.append(Gap(type="missing_vessel", detail=vessel))
        for pipe in pnid.pipes:
            if not self._find_pipe_in_scene(pipe, scene_objects):
                gaps.append(Gap(type="missing_pipe", detail=pipe))
        return gaps
```

### 5.3 DWG 파일 분석

```python
import ezdxf

def extract_dwg_entities(dwg_path: str) -> dict:
    """DWG 파일에서 엔티티 추출"""
    doc = ezdxf.readfile(dwg_path)
    msp = doc.modelspace()

    entities = {
        "lines": [],
        "circles": [],
        "texts": [],
        "blocks": [],
        "dimensions": []
    }

    for entity in msp:
        if entity.dxftype() == 'LINE':
            entities["lines"].append({
                "start": list(entity.dxf.start),
                "end": list(entity.dxf.end),
                "layer": entity.dxf.layer
            })
        elif entity.dxftype() == 'TEXT':
            entities["texts"].append({
                "text": entity.dxf.text,
                "position": list(entity.dxf.insert),
                "height": entity.dxf.height
            })
        elif entity.dxftype() == 'CIRCLE':
            entities["circles"].append({
                "center": list(entity.dxf.center),
                "radius": entity.dxf.radius
            })

    return entities
```

---

## 6. 자연어 → Unity 명령 변환 엔진

### 6.1 NLU 파이프라인

```
사용자 입력 → Intent 분류 → Entity 추출 → Command 생성 → 실행 계획 → MCP 호출
```

### 6.2 Intent 분류 체계

```python
INTENTS = {
    # 생성 계열
    "create_object":     "오브젝트 생성 (vessel, pipe, valve, ...)",
    "create_from_drawing": "도면 기반 자동 생성",
    "create_component":  "기존 오브젝트에 컴포넌트 추가",

    # 수정 계열
    "modify_transform":  "위치/회전/스케일 변경",
    "modify_color":      "색상/머터리얼 변경",
    "modify_name":       "이름 변경",
    "modify_hierarchy":  "부모-자식 관계 변경",

    # 삭제 계열
    "delete_object":     "오브젝트 삭제",
    "delete_component":  "컴포넌트 제거",

    # 조회 계열
    "query_scene":       "씬 구조 조회",
    "query_object":      "특정 오브젝트 정보",
    "query_count":       "오브젝트 개수",

    # 분석 계열
    "analyze_drawing":   "도면 분석",
    "compare_drawing":   "도면 vs 씬 비교",
    "verify_compliance": "P&ID 준수 검증",

    # 시스템 계열
    "save_scene":        "씬 저장",
    "take_screenshot":   "스크린샷",
    "undo_action":       "작업 취소",
    "run_play":          "플레이 모드",
}
```

### 6.3 Entity 추출

```python
ENTITIES = {
    "object_name":    "KF-7KL, Steam_Header, Valve_CWS_4KL, ...",
    "object_type":    "vessel, pipe, valve, pump, hx, probe, ...",
    "primitive_type": "Cube, Sphere, Cylinder, Capsule, ...",
    "position":       "[x, y, z] or 'above KF-7KL' or '옆에'",
    "color":          "red, blue, [1,0,0,1], 빨간색, ...",
    "parent":         "BioFacility/Vessels, ...",
    "medium":         "steam, cws, air, drain, ...",
    "pipe_size":      "8A, 10A, 15A, 20A, 25A, 40A, 50A, 65A",
    "scale":          "[sx, sy, sz] or 'large', 'small', ...",
    "file_path":      "도면 파일 경로",
}
```

### 6.4 자연어 → 명령 변환 프롬프트

```python
NLU_SYSTEM_PROMPT = """
당신은 Unity 3D 산업 시설 설계 AI입니다.
사용자의 자연어 명령을 Unity MCP API 호출로 변환합니다.

## 규칙
1. 하나의 자연어 명령을 여러 MCP 호출로 분해할 수 있습니다.
2. 위치는 미터 단위입니다 (1 Unity unit = 1 meter).
3. 색상 코드: Steam=빨강[1,0.3,0.3], CWS=파랑[0.25,0.41,0.88],
   Air=노랑[1,0.84,0], Drain=갈색[0.4,0.25,0.15]
4. 부모 경로: BioFacility/{Structure|Vessels|Piping|ControlRoom|Utilities}
5. 오브젝트가 이미 존재하는지 먼저 확인하세요.

## 출력 형식
```json
{
    "plan": "실행 계획 설명",
    "commands": [
        {"tool": "manage_gameobject", "params": {...}},
        {"tool": "manage_material", "params": {...}}
    ],
    "verification": "검증 방법"
}
```

## 산업 컴포넌트 표준
- Vessel: body(Cylinder) + dished_heads(Sphere) + flange(Cylinder) + nozzles
- Valve: body + stem(Cylinder) + handwheel(Sphere) + flanges
- Pump: motor(Cylinder) + coupling + casing + base(Cube)
- HX: shell(Cylinder) + tube_sheets + nozzles + saddles
- PRV: body + bonnet + spring_cap + inlet_flange
"""

async def natural_language_to_commands(user_input: str, context: SceneContext) -> CommandPlan:
    """자연어를 MCP 명령 목록으로 변환"""
    response = await claude.messages.create(
        model="claude-sonnet-4-5-20250929",
        system=NLU_SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": f"""
현재 씬 상태:
{context.hierarchy_summary}

사용자 명령: {user_input}

이 명령을 실행하기 위한 MCP API 호출 목록을 JSON으로 생성해주세요.
"""}
        ]
    )
    return CommandPlan.parse(response.content[0].text)
```

### 6.5 다단계 명령 분해 예시

```
사용자: "KF-7KL 발효조를 산업 표준으로 업그레이드해줘"

→ AI 분해:
  Step 1: KF-7KL 현재 위치/크기 조회 (manage_gameobject modify+include_properties)
  Step 2: 상부 접시형 헤드 생성 (manage_gameobject create Sphere)
  Step 3: 하부 접시형 헤드 생성 (manage_gameobject create Sphere)
  Step 4: 상부 플랜지 생성 (manage_gameobject create Cylinder)
  Step 5: 맨홀 생성 (manage_gameobject create Cylinder)
  Step 6: 사이트글라스 생성 (manage_gameobject create Cylinder)
  Step 7: 스커트 생성 (manage_gameobject create Cylinder)
  Step 8: 스텐레스 색상 적용 (manage_material set_renderer_color x 각 부품)
  Step 9: 스크린샷으로 결과 확인 (manage_scene screenshot)
```

---

## 7. 산업 표준 3D 컴포넌트 라이브러리

### 7.1 컴포넌트 템플릿 시스템

```python
COMPONENT_TEMPLATES = {
    "vessel_fermenter": {
        "description": "발효조 (Fermenter Vessel)",
        "parts": [
            {"name": "{name}",           "type": "Cylinder", "rel_pos": [0,0,0],
             "scale_formula": "[d, h/2, d]", "color": [0.82, 0.82, 0.82, 1]},
            {"name": "DishHead_Top_{id}", "type": "Sphere",  "rel_pos": [0, "h/2", 0],
             "scale_formula": "[d, d*0.3, d]", "color": [0.82, 0.82, 0.82, 1]},
            {"name": "DishHead_Bot_{id}", "type": "Sphere",  "rel_pos": [0, "-h/2", 0],
             "scale_formula": "[d, d*0.3, d]", "color": [0.82, 0.82, 0.82, 1]},
            {"name": "Flange_Top_{id}",   "type": "Cylinder", "rel_pos": [0, "h/2+d*0.1", 0],
             "scale_formula": "[d*1.15, 0.02, d*1.15]", "color": [0.65, 0.65, 0.65, 1]},
            {"name": "Manway_{id}",       "type": "Cylinder", "rel_pos": ["d/2+0.01", "h/4", 0],
             "scale_formula": "[0.1, 0.05, 0.1]", "rotation": [0, 0, 90]},
            {"name": "SightGlass_{id}",   "type": "Cylinder", "rel_pos": ["d/2+0.01", 0, 0],
             "scale_formula": "[0.05, 0.08, 0.05]", "rotation": [0, 0, 90]},
        ],
        "options": {
            "has_jacket": {"parts": [
                {"name": "Jacket_{id}", "type": "Cylinder", "rel_pos": [0,0,0],
                 "scale_formula": "[d*1.1, h*0.4, d*1.1]", "color": [0.75, 0.75, 0.8, 1]}
            ]},
            "has_skirt": {"condition": "d >= 1.0", "parts": [
                {"name": "Skirt_{id}", "type": "Cylinder", "rel_pos": [0, "-h/2-skirt_h/2", 0],
                 "scale_formula": "[d*0.95, skirt_h/2, d*0.95]", "color": [0.5, 0.5, 0.5, 1]}
            ]},
            "has_legs": {"condition": "d < 1.0", "parts": "3_legs_at_120_degrees"},
            "agitator": {"parts": [
                {"name": "Shaft_{id}",    "type": "Cylinder", "rel_pos": [0, "h/4", 0],
                 "scale_formula": "[0.02, h*0.6, 0.02]"},
                {"name": "Impeller_{id}", "type": "Cylinder", "rel_pos": [0, "-h/6", 0],
                 "scale_formula": "[d*0.35, 0.01, d*0.35]"},
            ]},
        },
        "parameters": {
            "d": "직경 (미터)",
            "h": "높이 (미터)",
            "id": "고유 식별자"
        }
    },

    "valve_manual": {
        "description": "수동 밸브 (Ball/Gate Valve)",
        "parts": [
            {"name": "Valve_{id}",   "type": "existing", "note": "기존 오브젝트 활용"},
            {"name": "Stem_{id}",    "type": "Cylinder", "rel_pos": [0, 0.12, 0],
             "scale": [0.008, 0.06, 0.008], "color": [0.5, 0.5, 0.5, 1]},
            {"name": "HW_{id}",      "type": "Sphere",   "rel_pos": [0, 0.2, 0],
             "scale": [0.04, 0.01, 0.04], "color": "medium_color"},
            {"name": "VFlange1_{id}","type": "Cylinder", "rel_pos": [-0.06, 0, 0],
             "scale": [0.04, 0.005, 0.04], "rotation": [0,0,90]},
            {"name": "VFlange2_{id}","type": "Cylinder", "rel_pos": [0.06, 0, 0],
             "scale": [0.04, 0.005, 0.04], "rotation": [0,0,90]},
        ]
    },

    "pump_centrifugal": {
        "description": "원심 펌프 (Centrifugal Pump)",
        "parts": [
            {"name": "CircPump_{id}", "type": "existing"},
            {"name": "Motor_{id}",    "type": "Cylinder", "rel_pos": [-0.25, 0, 0],
             "scale": [0.08, 0.12, 0.08], "rotation": [0,0,90], "color": [0.2, 0.6, 0.2, 1]},
            {"name": "Coupling_{id}", "type": "Cylinder", "rel_pos": [-0.1, 0, 0],
             "scale": [0.04, 0.03, 0.04], "rotation": [0,0,90], "color": [0.5, 0.5, 0.5, 1]},
            {"name": "Base_{id}",     "type": "Cube",     "rel_pos": [-0.12, -0.1, 0],
             "scale": [0.5, 0.02, 0.2], "color": [0.35, 0.35, 0.35, 1]},
        ]
    },

    "hx_shell_tube": {
        "description": "열교환기 Shell & Tube",
        "parts": [
            {"name": "HX_{id}",        "type": "existing"},
            {"name": "TSheet_F_{id}",  "type": "Cylinder", "rel_pos": [-0.15, 0, 0],
             "scale": [0.09, 0.008, 0.09], "rotation": [0,0,90]},
            {"name": "TSheet_R_{id}",  "type": "Cylinder", "rel_pos": [0.15, 0, 0],
             "scale": [0.09, 0.008, 0.09], "rotation": [0,0,90]},
            {"name": "Noz_ShIn_{id}",  "type": "Cylinder", "rel_pos": [-0.07, 0.08, 0],
             "scale": [0.02, 0.03, 0.02]},
            {"name": "Noz_ShOut_{id}", "type": "Cylinder", "rel_pos": [0.07, 0.08, 0],
             "scale": [0.02, 0.03, 0.02]},
            {"name": "Saddle_F_{id}",  "type": "Cube", "rel_pos": [-0.1, -0.07, 0],
             "scale": [0.02, 0.04, 0.12]},
            {"name": "Saddle_R_{id}",  "type": "Cube", "rel_pos": [0.1, -0.07, 0],
             "scale": [0.02, 0.04, 0.12]},
        ]
    },

    "prv_safety": {
        "description": "안전 릴리프 밸브 (PRV)",
        "parts": [
            {"name": "PRV_{id}",       "type": "existing"},
            {"name": "Bonnet_{id}",    "type": "Cylinder", "rel_pos": [0, 0.08, 0],
             "scale": [0.03, 0.03, 0.03], "color": [1, 0, 0, 1]},
            {"name": "SpringCap_{id}", "type": "Cylinder", "rel_pos": [0, 0.15, 0],
             "scale": [0.025, 0.025, 0.025], "color": [0.8, 0, 0, 1]},
            {"name": "FlangeIn_{id}",  "type": "Cylinder", "rel_pos": [0, -0.05, 0],
             "scale": [0.05, 0.005, 0.05], "color": [0.6, 0.6, 0.6, 1]},
        ]
    },

    "steam_trap": {
        "description": "스팀 트랩",
        "parts": [
            {"name": "SteamTrap_{id}", "type": "existing"},
            {"name": "STIn_{id}",  "type": "Cylinder", "rel_pos": [-0.05, 0, 0],
             "scale": [0.015, 0.02, 0.015], "rotation": [0,0,90]},
            {"name": "STOut_{id}", "type": "Cylinder", "rel_pos": [0.05, 0, 0],
             "scale": [0.015, 0.02, 0.015], "rotation": [0,0,90]},
        ]
    },
}
```

### 7.2 배관 라우팅 패턴

```python
class PipeRouter:
    """배관 라우팅 엔진"""

    # JIS 파이프 사이즈 → Unity 반경 매핑
    PIPE_SIZES = {
        "8A":  0.007, "10A": 0.009, "15A": 0.012,
        "20A": 0.015, "25A": 0.018, "40A": 0.025,
        "50A": 0.032, "65A": 0.040
    }

    # 매체별 색상
    MEDIUM_COLORS = {
        "steam":    [1.0, 0.3, 0.3, 1.0],   # Red
        "cws":      [0.25, 0.41, 0.88, 1.0], # Blue
        "air":      [1.0, 0.84, 0.0, 1.0],   # Yellow
        "drain":    [0.4, 0.25, 0.15, 1.0],   # Brown
        "seed":     [0.2, 0.7, 0.2, 1.0],     # Green
        "feed":     [0.3, 0.5, 1.0, 1.0],     # Light Blue
        "broth":    [0.6, 0.4, 0.2, 1.0],     # Dark Brown
        "exhaust":  [0.6, 0.6, 0.6, 1.0],     # Gray
    }

    def route_header_to_drop(self, header_pos, drop_pos, medium, pipe_size):
        """헤더에서 드롭까지 수평 라우팅"""
        mid_x = (header_pos[0] + drop_pos[0]) / 2
        dist = abs(drop_pos[0] - header_pos[0])
        radius = self.PIPE_SIZES.get(pipe_size, 0.012)
        color = self.MEDIUM_COLORS[medium]

        commands = [
            # 수평 파이프 (헤더 → 엘보)
            {"tool": "manage_gameobject", "params": {
                "action": "create", "name": f"{medium.title()}Run_{id}",
                "primitive_type": "Cylinder", "parent": "BioFacility/Piping",
                "position": [mid_x, header_pos[1], header_pos[2]],
                "scale": [radius, dist/2, radius],
                "rotation": [0, 0, 90]
            }},
            # 엘보 (방향 전환점)
            {"tool": "manage_gameobject", "params": {
                "action": "create", "name": f"Elbow_{medium[0].upper()}_{id}",
                "primitive_type": "Sphere", "parent": "BioFacility/Piping",
                "position": [drop_pos[0], header_pos[1], header_pos[2]],
                "scale": [radius*2, radius*2, radius*2]
            }},
        ]
        # + 색상 명령 추가
        return commands
```

### 7.3 프로브/센서 색상 표준

```python
PROBE_COLORS = {
    "pH":    [1.0, 1.0, 0.0, 1.0],   # Yellow
    "DO":    [0.0, 0.8, 0.0, 1.0],   # Green
    "Level": [0.0, 0.5, 1.0, 1.0],   # Blue
    "Temp":  [1.0, 0.4, 0.0, 1.0],   # Orange
}
```

---

## 8. UI/UX 설계 명세

### 8.1 레이아웃

```
┌─────────────────────────────────────────────────────────────────────────┐
│  🔧 Vibe3D Accelerator                    [Project] [Settings] [Help]  │
├─────────────┬────────────────────────────────┬──────────────────────────┤
│             │                                │                          │
│  📁 Scene   │     🖼️ Unity Live Preview      │  📦 Components           │
│  Explorer   │     (Screenshot 기반 갱신)      │                          │
│             │                                │  [Vessel]                │
│  BioFacility│                                │   ├ Fermenter            │
│  ├ Structure│                                │   ├ Feed Tank            │
│  ├ Vessels  │                                │   └ Broth Tank           │
│  ├ Piping   │                                │  [Piping]                │
│  ├ CR       │                                │   ├ Header               │
│  └ Utilities│                                │   ├ Drop + Run           │
│             │                                │   └ Elbow                │
│             │                                │  [Equipment]             │
│             │                                │   ├ Valve                │
│             │                                │   ├ Pump                 │
│             │                                │   ├ Heat Exchanger       │
│             │                                │   ├ Steam Trap           │
│             │                                │   └ PRV                  │
│             │                                │  [Instruments]           │
│             │                                │   ├ pH Probe             │
│             │                                │   ├ DO Probe             │
│             │                                │   ├ Level Probe          │
│             │                                │   └ Temp Probe           │
├─────────────┼────────────────────────────────┤                          │
│             │                                │  📐 Properties           │
│  📄 도면    │  💬 AI Chat                     │                          │
│  Viewer     │                                │  Name: KF-7KL            │
│             │  You: KF-7KL에 CWS 파이프를    │  Position: -1.5, 0, -1   │
│  [P&ID]     │  연결하고 파란색으로 칠해줘     │  Scale: 1.8, 1.75, 1.8   │
│  [Layout]   │                                │  Color: ■ Steel Gray     │
│  [DWG]      │  AI: 실행 계획:                │                          │
│             │  1. CWS 드롭 위치 확인         │  Components:             │
│  pnid_1.png │  2. CWS 배관 생성             │   • DishHead_Top         │
│  pnid_2.png │  3. 파란색 적용               │   • DishHead_Bot         │
│  ...        │  4. 엘보 추가                  │   • Flange_Top           │
│  layout.png │                                │   • Jacket               │
│             │  [▶ 실행] [✏️ 수정] [❌ 취소]   │   • Skirt                │
│             │                                │   • ...                  │
│             │  ✅ 완료! 3개 오브젝트 생성     │                          │
├─────────────┴────────────────────────────────┴──────────────────────────┤
│  ⏪ Undo  │  ⏩ Redo  │  📷 Screenshot  │  💾 Save  │  ▶️ Play  │  ⏹ Stop │
└─────────────────────────────────────────────────────────────────────────┘
```

### 8.2 핵심 인터랙션 흐름

#### Flow 1: 자연어 명령
```
1. 사용자가 Chat Panel에 한국어/영어로 명령 입력
2. AI가 명령을 해석하여 실행 계획 표시 (단계별)
3. 사용자가 [실행] 클릭 (또는 자동 실행 모드)
4. 각 단계별 진행 상황 표시 (프로그레스 바)
5. 완료 후 자동 스크린샷으로 결과 표시
6. 히스토리에 기록 (실행 취소 가능)
```

#### Flow 2: 도면 분석
```
1. 사용자가 도면 파일 드래그&드롭 (PNG/PDF/DWG)
2. AI가 도면 자동 분석 (P&ID/Layout 자동 감지)
3. 추출된 장비/배관/계기 목록 표시
4. 현재 씬과 비교하여 불일치 항목 하이라이트
5. [자동 수정] 버튼으로 일괄 반영
```

#### Flow 3: 컴포넌트 드래그&드롭
```
1. 우측 Component Library에서 템플릿 선택
2. 파라미터 입력 (직경, 높이, 매체 등)
3. Scene Viewer에서 위치 지정 (클릭 또는 좌표 입력)
4. 자동으로 멀티파트 산업 표준 모델 생성
```

### 8.3 실시간 피드백 시스템

```python
class LiveFeedback:
    """실시간 피드백 시스템"""

    async def capture_and_display(self):
        """스크린샷 캡처 후 프론트엔드에 전송"""
        result = await mcp.call_tool("manage_scene", {
            "action": "screenshot",
            "screenshot_file_name": f"live_{timestamp}"
        })
        # WebSocket으로 프론트엔드에 이미지 전송
        await ws.send_json({
            "type": "screenshot_update",
            "path": result["data"]["fullPath"],
            "timestamp": timestamp
        })

    async def stream_progress(self, commands, ws):
        """명령 실행 진행 상황 스트리밍"""
        total = len(commands)
        for i, cmd in enumerate(commands):
            await ws.send_json({
                "type": "progress",
                "current": i + 1,
                "total": total,
                "description": f"{cmd['tool']}: {cmd['params'].get('name', '')}"
            })
            result = await mcp.call_tool(cmd["tool"], cmd["params"])
            await ws.send_json({
                "type": "result",
                "step": i + 1,
                "success": result.get("success", False)
            })
```

---

## 9. 프로젝트 구조 및 구현 가이드

### 9.1 프로젝트 디렉토리 구조

```
vibe3d-accelerator/
├── frontend/                      # Next.js 프론트엔드
│   ├── app/
│   │   ├── layout.tsx             # 전체 레이아웃
│   │   ├── page.tsx               # 메인 페이지
│   │   └── api/                   # API Routes (BFF)
│   │       ├── chat/route.ts      # 자연어 명령 처리
│   │       ├── mcp/route.ts       # MCP 프록시
│   │       └── files/route.ts     # 파일 업로드/분석
│   ├── components/
│   │   ├── ChatPanel.tsx          # 자연어 채팅 패널
│   │   ├── SceneViewer.tsx        # Unity 스크린샷 뷰어
│   │   ├── SceneExplorer.tsx      # 씬 계층 구조 트리
│   │   ├── ComponentLibrary.tsx   # 컴포넌트 라이브러리
│   │   ├── PropertyPanel.tsx      # 속성 편집 패널
│   │   ├── DrawingViewer.tsx      # 도면 뷰어
│   │   ├── ProgressBar.tsx        # 진행 상황 표시
│   │   └── Toolbar.tsx            # 하단 도구 바
│   ├── lib/
│   │   ├── mcp-client.ts          # MCP 클라이언트
│   │   ├── websocket.ts           # WebSocket 연결
│   │   └── types.ts               # 타입 정의
│   ├── package.json
│   └── tailwind.config.ts
│
├── backend/                       # FastAPI 백엔드
│   ├── main.py                    # FastAPI 앱 진입점
│   ├── routers/
│   │   ├── chat.py                # 자연어 명령 라우터
│   │   ├── mcp_proxy.py           # MCP 프록시 라우터
│   │   ├── files.py               # 파일 분석 라우터
│   │   └── websocket.py           # WebSocket 라우터
│   ├── services/
│   │   ├── nlu_engine.py          # 자연어 → 명령 변환
│   │   ├── mcp_session.py         # MCP 세션 관리자
│   │   ├── command_orchestrator.py # 명령 실행 오케스트레이터
│   │   ├── drawing_analyzer.py    # 도면 분석기
│   │   ├── component_library.py   # 컴포넌트 템플릿 엔진
│   │   ├── pipe_router.py         # 배관 라우팅 엔진
│   │   └── history_manager.py     # 히스토리/실행취소
│   ├── models/
│   │   ├── commands.py            # 명령 모델
│   │   ├── scene.py               # 씬 상태 모델
│   │   └── drawing.py             # 도면 분석 결과 모델
│   ├── data/
│   │   ├── component_templates.json  # 컴포넌트 템플릿 데이터
│   │   ├── color_standards.json      # 색상 표준 데이터
│   │   └── pipe_sizes.json           # JIS 파이프 사이즈
│   └── requirements.txt
│
├── docs/                          # 문서
│   └── Vibe3D_Accelerator_Framework.md  # 이 문서
│
├── docker-compose.yml             # Docker 구성
├── .env.example                   # 환경 변수 템플릿
└── README.md
```

### 9.2 Backend 핵심 구현

#### main.py
```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 시작: MCP 세션 초기화
    app.state.mcp = MCPSession()
    await app.state.mcp.initialize()
    yield
    # 종료: 정리

app = FastAPI(title="Vibe3D Accelerator", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"])

app.include_router(chat_router, prefix="/api/chat")
app.include_router(mcp_router, prefix="/api/mcp")
app.include_router(files_router, prefix="/api/files")
app.include_router(ws_router, prefix="/ws")
```

#### services/mcp_session.py
```python
import httpx
import json
import asyncio
from typing import Optional

class MCPSession:
    def __init__(self, url: str = "http://localhost:8080/mcp"):
        self.url = url
        self.session_id: Optional[str] = None
        self.call_id = 0
        self._client = httpx.AsyncClient(timeout=60.0)
        self._lock = asyncio.Lock()

    async def initialize(self):
        resp = await self._client.post(self.url, headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream"
        }, json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "vibe3d-backend", "version": "1.0"}
            }
        })
        self.session_id = resp.headers.get("mcp-session-id")

        await self._client.post(self.url, headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "mcp-session-id": self.session_id
        }, json={"jsonrpc": "2.0", "method": "notifications/initialized"})

        return self.session_id

    async def call_tool(self, tool: str, args: dict, timeout: float = 30) -> dict:
        async with self._lock:
            self.call_id += 1
            try:
                resp = await self._client.post(self.url, headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                    "mcp-session-id": self.session_id
                }, json={
                    "jsonrpc": "2.0", "id": self.call_id,
                    "method": "tools/call",
                    "params": {"name": tool, "arguments": args}
                }, timeout=timeout)

                for line in resp.text.split('\n'):
                    if line.startswith('data: '):
                        data = json.loads(line[6:])
                        text = data["result"]["content"][0]["text"]
                        return json.loads(text) if text.startswith('{') else {"text": text}
            except Exception as e:
                if "Session not found" in str(e) or "session" in str(e).lower():
                    await self.initialize()
                    return await self.call_tool(tool, args, timeout)
                raise
        return None

    async def batch_execute(self, commands: list, fail_fast=False) -> list:
        """최대 25개씩 배치 실행"""
        results = []
        for i in range(0, len(commands), 25):
            chunk = commands[i:i+25]
            result = await self.call_tool("batch_execute", {
                "commands": chunk,
                "fail_fast": fail_fast
            }, timeout=60)
            results.extend(result.get("results", []) if result else [])
        return results
```

#### services/nlu_engine.py
```python
import anthropic
import json

class NLUEngine:
    def __init__(self):
        self.client = anthropic.AsyncAnthropic()

    async def process(self, user_input: str, scene_context: dict) -> dict:
        """자연어 → MCP 명령 변환"""
        response = await self.client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=4096,
            system=NLU_SYSTEM_PROMPT,  # 섹션 6.4의 프롬프트
            messages=[{
                "role": "user",
                "content": f"""
현재 씬: {json.dumps(scene_context, ensure_ascii=False)}

사용자 명령: {user_input}

MCP 명령 목록을 JSON으로 생성하세요.
출력 형식:
{{
    "intent": "create_object|modify_transform|...",
    "plan_description": "한국어 설명",
    "commands": [
        {{"tool": "manage_gameobject", "params": {{...}}, "description": "설명"}}
    ],
    "verification_screenshot": true
}}"""
            }]
        )
        return json.loads(response.content[0].text)

    async def analyze_drawing(self, image_path: str, drawing_type: str) -> dict:
        """도면 분석"""
        import base64
        with open(image_path, 'rb') as f:
            img_data = base64.standard_b64encode(f.read()).decode()

        prompt = PNID_ANALYSIS_PROMPT if drawing_type == "pnid" else LAYOUT_ANALYSIS_PROMPT

        response = await self.client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=4096,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {
                        "type": "base64", "media_type": "image/png", "data": img_data
                    }},
                    {"type": "text", "text": prompt}
                ]
            }]
        )
        return json.loads(response.content[0].text)
```

#### services/command_orchestrator.py
```python
class CommandOrchestrator:
    def __init__(self, mcp: MCPSession, history: HistoryManager):
        self.mcp = mcp
        self.history = history

    async def execute_plan(self, plan: dict, ws=None) -> dict:
        """명령 계획 실행 + 진행 상황 스트리밍"""
        commands = plan["commands"]
        results = []

        # 히스토리에 기록 (롤백용)
        batch_id = self.history.start_batch(plan["plan_description"])

        for i, cmd in enumerate(commands):
            # 진행 상황 전송
            if ws:
                await ws.send_json({
                    "type": "progress",
                    "step": i + 1,
                    "total": len(commands),
                    "description": cmd.get("description", "")
                })

            # 실행
            result = await self.mcp.call_tool(cmd["tool"], cmd["params"])
            results.append(result)

            # 히스토리 기록
            self.history.record(batch_id, cmd, result)

            if result and not result.get("success", True):
                if ws:
                    await ws.send_json({"type": "error", "step": i+1, "detail": str(result)})

        # 검증 스크린샷
        if plan.get("verification_screenshot"):
            screenshot = await self.mcp.call_tool("manage_scene", {
                "action": "screenshot",
                "screenshot_file_name": f"verify_{batch_id}"
            })
            if ws:
                await ws.send_json({
                    "type": "screenshot",
                    "path": screenshot["data"]["fullPath"]
                })

        self.history.complete_batch(batch_id)
        return {"batch_id": batch_id, "results": results}

    async def undo(self, batch_id: str):
        """배치 작업 취소 (역순으로 delete)"""
        records = self.history.get_batch(batch_id)
        for record in reversed(records):
            if record["cmd"]["tool"] == "manage_gameobject" and \
               record["cmd"]["params"]["action"] == "create":
                name = record["cmd"]["params"]["name"]
                await self.mcp.call_tool("manage_gameobject", {
                    "action": "delete",
                    "target": name,
                    "search_method": "by_name"
                })
```

### 9.3 Frontend 핵심 구현

#### components/ChatPanel.tsx
```tsx
'use client';
import { useState, useRef, useEffect } from 'react';

interface Message {
    role: 'user' | 'assistant';
    content: string;
    commands?: any[];
    screenshot?: string;
}

export function ChatPanel() {
    const [messages, setMessages] = useState<Message[]>([]);
    const [input, setInput] = useState('');
    const [executing, setExecuting] = useState(false);
    const wsRef = useRef<WebSocket | null>(null);

    useEffect(() => {
        wsRef.current = new WebSocket('ws://localhost:8000/ws/live');
        wsRef.current.onmessage = (event) => {
            const data = JSON.parse(event.data);
            if (data.type === 'screenshot') {
                // 스크린샷 업데이트
            } else if (data.type === 'progress') {
                // 진행 상황 업데이트
            }
        };
        return () => wsRef.current?.close();
    }, []);

    async function handleSubmit() {
        if (!input.trim()) return;

        setMessages(prev => [...prev, { role: 'user', content: input }]);
        setExecuting(true);

        const response = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: input })
        });

        const result = await response.json();
        setMessages(prev => [...prev, {
            role: 'assistant',
            content: result.plan_description,
            commands: result.commands,
            screenshot: result.screenshot
        }]);

        setExecuting(false);
        setInput('');
    }

    return (
        <div className="flex flex-col h-full bg-gray-900 text-white">
            <div className="flex-1 overflow-y-auto p-4 space-y-4">
                {messages.map((msg, i) => (
                    <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                        <div className={`max-w-[80%] p-3 rounded-lg ${
                            msg.role === 'user' ? 'bg-blue-600' : 'bg-gray-700'
                        }`}>
                            <p>{msg.content}</p>
                            {msg.commands && (
                                <div className="mt-2 text-xs bg-gray-800 p-2 rounded">
                                    {msg.commands.length}개 명령 실행 완료
                                </div>
                            )}
                            {msg.screenshot && (
                                <img src={msg.screenshot} className="mt-2 rounded" />
                            )}
                        </div>
                    </div>
                ))}
            </div>
            <div className="p-4 border-t border-gray-700">
                <div className="flex gap-2">
                    <input
                        value={input}
                        onChange={e => setInput(e.target.value)}
                        onKeyDown={e => e.key === 'Enter' && handleSubmit()}
                        placeholder="자연어로 Unity 작업을 지시하세요..."
                        className="flex-1 bg-gray-800 p-3 rounded-lg"
                        disabled={executing}
                    />
                    <button onClick={handleSubmit} disabled={executing}
                        className="px-6 py-3 bg-blue-600 rounded-lg hover:bg-blue-500">
                        {executing ? '실행 중...' : '전송'}
                    </button>
                </div>
            </div>
        </div>
    );
}
```

---

## 10. 검증된 패턴과 워크어라운드

### 10.1 Windows 환경 이슈

| 이슈 | 원인 | 해결책 |
|------|------|--------|
| `cp949` UnicodeDecodeError | Windows 한국어 기본 인코딩 | `encoding='utf-8', errors='replace'` |
| MCP 세션 만료 | Idle timeout | 자동 재초기화 로직 |
| `find_gameobjects` 부분검색 불가 | 정확한 이름 매치만 | `get_hierarchy` + parent 필터링 |
| `batch_execute` 성공 카운트 0 | 응답 구조 다름 | 개별 결과 확인 필요 |
| 스크린샷 빈 화면 | 카메라 방향 문제 | 카메라 위치/회전 먼저 설정 |

### 10.2 성능 최적화

```python
# 1. 위치 캐싱 - 반복 조회 방지
POSITION_CACHE = {}
async def get_cached_pos(name):
    if name not in POSITION_CACHE:
        POSITION_CACHE[name] = await get_pos(name)
    return POSITION_CACHE[name]

# 2. batch_execute 활용 - 25개씩 묶어 실행
# 개별 호출 대비 10~100배 빠름

# 3. 페이지네이션 - 대량 데이터 조회 시 필수
# page_size=50 + cursor 추적

# 4. include_properties 사용 주의
# false(기본): 메타데이터만 → 빠름
# true: 모든 속성 포함 → 느림, 페이로드 큼

# 5. generate_preview=false (에셋 검색 시)
# 미리보기 비활성으로 대용량 base64 방지
```

### 10.3 오브젝트 명명 규칙

```
[Category]_[Type]_[Vessel/Location]_[Suffix]

예시:
  DishHead_Top_KF7KL       # 발효조 상부 접시형 헤드
  Valve_Steam_700L          # 700L 스팀 밸브
  SteamRun_7KL              # 7KL 스팀 배관 런
  Elbow_C_500LFD            # 500L-FD CWS 엘보
  Probe_pH_7KL              # 7KL pH 프로브
  AddTank_700L_Acid_15L     # 700L 산 첨가 탱크 15L
  Motor_CircPump_KF7KL      # 7KL 순환펌프 모터
  Noz_ShIn_HX_KF700L        # 700L HX Shell 입구 노즐
```

### 10.4 계층 구조 표준

```
BioFacility/
├── Structure/          # 건축 구조물 (프레임, 바닥, 계단, 난간)
├── Vessels/            # 용기 및 관련 부품 (헤드, 플랜지, 프로브, PRV, 교반기)
├── Piping/             # 배관 (헤더, 드롭, 런, 밸브, 트랩, 전송라인)
├── ControlRoom/        # 제어실 (패널, 도어, 랙)
└── Utilities/          # 유틸리티 (HX, 펌프, 보일러, 압축기, 스크러버)
```

---

## 11. 구현 로드맵

### Phase 1: 기반 구축 (Week 1)
- [ ] 프로젝트 초기화 (Next.js + FastAPI)
- [ ] MCP 세션 관리자 구현 (연결/재연결/에러 처리)
- [ ] 기본 REST API 엔드포인트 (MCP 프록시)
- [ ] WebSocket 실시간 통신

### Phase 2: 핵심 UI (Week 2)
- [ ] 채팅 패널 (자연어 입력/응답 표시)
- [ ] Scene Explorer (계층 구조 트리뷰)
- [ ] Scene Viewer (스크린샷 기반 미리보기)
- [ ] Property Panel (속성 조회/편집)

### Phase 3: AI 엔진 (Week 3)
- [ ] NLU Engine (Claude API 연동)
- [ ] 자연어 → MCP 명령 변환
- [ ] Command Orchestrator (실행+진행상황+에러처리)
- [ ] 히스토리/Undo 시스템

### Phase 4: 도면 분석 (Week 4)
- [ ] Drawing Viewer (PNG/PDF/DWG 뷰어)
- [ ] P&ID 자동 분석 (Claude Vision)
- [ ] Layout 자동 분석
- [ ] 씬 vs 도면 비교/갭 분석

### Phase 5: 컴포넌트 라이브러리 (Week 5)
- [ ] 컴포넌트 템플릿 엔진
- [ ] 드래그&드롭 배치
- [ ] 파라미터 기반 인스턴스화
- [ ] 배관 라우팅 엔진

### Phase 6: 고급 기능 (Week 6)
- [ ] 다중 씬 지원
- [ ] 프리팹 자동 생성
- [ ] 스크립트 생성/편집
- [ ] 테스트 자동화

### 환경 변수 (.env)
```
# Backend
ANTHROPIC_API_KEY=sk-ant-...
MCP_SERVER_URL=http://localhost:8080/mcp
BACKEND_PORT=8000

# Frontend
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_WS_URL=ws://localhost:8000/ws
```

### Docker 구성 (docker-compose.yml)
```yaml
version: '3.8'
services:
  frontend:
    build: ./frontend
    ports: ["3000:3000"]
    environment:
      - NEXT_PUBLIC_API_URL=http://backend:8000

  backend:
    build: ./backend
    ports: ["8000:8000"]
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - MCP_SERVER_URL=http://host.docker.internal:8080/mcp
    extra_hosts:
      - "host.docker.internal:host-gateway"
```

---

## 부록: 빠른 시작 가이드

다른 세션에서 이 문서를 기반으로 Vibe3D Accelerator를 구축하려면:

1. 이 문서를 전체 읽기
2. 섹션 9.1의 프로젝트 구조대로 디렉토리 생성
3. 섹션 9.2의 Backend 코드 구현 (main.py → services/ 순서)
4. 섹션 9.3의 Frontend 코드 구현
5. 섹션 7의 컴포넌트 템플릿을 JSON 데이터로 저장
6. 섹션 3의 MCP 세션 관리 로직 적용
7. 섹션 6의 NLU 프롬프트 적용
8. 섹션 11의 로드맵 순서로 점진적 구현

**핵심 의존성:**
```
# Backend (requirements.txt)
fastapi>=0.104
uvicorn>=0.24
httpx>=0.25
anthropic>=0.39
websockets>=12.0
python-multipart>=0.0.6
pillow>=10.0
ezdxf>=0.18

# Frontend (package.json)
next@14+
react@18+
tailwindcss@3+
```

---

*이 문서는 바이오 발효 디지털 트윈 프로젝트에서 실증된 패턴과 코드를 기반으로 작성되었습니다.*
*문서 버전: 1.0 | 최종 갱신: 2026-02-08*
