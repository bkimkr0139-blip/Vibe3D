"""Vibe3D Accelerator — FastAPI backend/orchestrator.

Receives natural language commands, generates action plans,
validates them, and executes via MCP to control Unity Editor.
"""

import asyncio
import json
import logging
import os
import time
import traceback
import uuid
from collections import deque
from dataclasses import asdict
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config
from .plan_validator import validate_plan, validate_plan_extended
from .plan_generator import generate_plan, detect_disambiguation, apply_arrangement
from .executor import PlanExecutor, JobResult, JobStatus
from .scene_cache import SceneCache
from .suggestion_engine import SuggestionEngine
from .error_analyzer import analyze as analyze_error
from .source_analyzer import analyze_file, source_to_plan, batch_analyze
from .composite_analyzer import composite_analyze
from .workflow_manager import WorkflowManager
from .nlu_engine import NLUEngine
from .component_library import ComponentLibrary
from .webgl_builder import generate_setup_plan, generate_build_plan
from ..mcp_client import UnityMCPClient

# ── Logging ──────────────────────────────────────────────────

# Ensure log directory exists (important for frozen/exe builds)
os.makedirs(config.LOGS_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(config.LOGS_DIR / "vibe3d.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("vibe3d")

# ── App ──────────────────────────────────────────────────────

app = FastAPI(
    title="Vibe3D Unity Accelerator",
    version="2.0.0",
    description="Natural language → Unity 3D via MCP",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve frontend static files
frontend_dir = config.FRONTEND_DIR
if frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_dir / "static")), name="static")

    # Favicon — return SVG inline to avoid 404
    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        favicon_path = frontend_dir / "static" / "favicon.ico"
        if favicon_path.exists():
            return FileResponse(str(favicon_path))
        # Return a minimal 1x1 transparent ICO to suppress 404
        from fastapi.responses import Response
        return Response(content=b"", media_type="image/x-icon", status_code=204)

# ── State ────────────────────────────────────────────────────

mcp_client = UnityMCPClient(url=config.MCP_SERVER_URL, timeout=config.MCP_TIMEOUT)
executor = PlanExecutor(mcp_client)
scene_cache = SceneCache()
suggestion_engine = SuggestionEngine()
workflow_mgr = WorkflowManager()
nlu_engine = NLUEngine(api_key=config.ANTHROPIC_API_KEY)
component_library = ComponentLibrary()
job_history: deque[dict] = deque(maxlen=200)
command_history: deque[str] = deque(maxlen=50)
ws_connections: list[WebSocket] = []
twin_ws_connections: list[WebSocket] = []

# Last composite analysis plan — used when the user types a follow-up command
# like "분석 결과로 만들어" after performing a composite analysis.
_last_composite_plan: Optional[dict] = None

# Pending plans waiting for user approval
_pending_plans: dict[str, dict] = {}  # job_id → {plan, method, command, created_at}

# Server-side color overrides — populated after plan execution
# Persists across scene data fetches so the 3D viewer reflects actual colors
_scene_color_overrides: dict[str, dict] = {}  # object name → {"r":..,"g":..,"b":..}
_3d_data_cache: dict | None = None  # cached 3d-data response
_last_equipment_event: dict = {}  # last selected equipment event (for REST polling)


async def _refresh_scene_and_3d_cache():
    """Refresh scene_cache from MCP and invalidate the 3D data cache."""
    global _3d_data_cache
    await asyncio.to_thread(scene_cache.refresh, mcp_client)
    _3d_data_cache = None


# Working directory state
_working_dir: str = config.UNITY_PROJECT_PATH
_pinned_dirs: list[str] = [
    config.UNITY_PROJECT_PATH,
    str(config.ASSETS_DIR / "import"),
    str(config.ASSETS_DIR / "library"),
]

# File extension categories
ASSET_EXTENSIONS = {
    "3d_model": {".fbx", ".obj", ".glb", ".gltf", ".blend", ".3ds", ".dae"},
    "texture": {".png", ".jpg", ".jpeg", ".tga", ".bmp", ".psd", ".tif", ".exr", ".hdr"},
    "material": {".mat", ".shader", ".shadergraph"},
    "prefab": {".prefab"},
    "scene": {".unity"},
    "script": {".cs", ".js"},
    "audio": {".wav", ".mp3", ".ogg", ".aiff"},
    "data": {".json", ".xml", ".csv", ".yaml", ".txt"},
    "other": set(),
}


def _safe_asdict(obj) -> dict:
    """Convert a dataclass to a JSON-serializable dict (enums → values)."""
    d = asdict(obj)

    def _convert(v):
        if isinstance(v, Enum):
            return v.value
        if isinstance(v, dict):
            return {k: _convert(val) for k, val in v.items()}
        if isinstance(v, list):
            return [_convert(item) for item in v]
        return v

    return {k: _convert(v) for k, v in d.items()}


def _extract_color_overrides(plan: dict):
    """Extract color changes from an executed plan into server-side overrides.

    Handles all color-changing action types: apply_material, create_material + assign_material,
    set_renderer_color, set_material_color, create_primitive/light with color, and delete_object.
    """
    global _scene_color_overrides
    actions = plan.get("actions", [])
    material_colors: dict[str, dict] = {}  # material name → color

    for a in actions:
        atype = a.get("type", "")

        # create_material — remember color for later assign_material lookup
        if atype == "create_material" and a.get("name") and a.get("color"):
            material_colors[a["name"]] = a["color"]

        # apply_material — direct color on target
        if atype == "apply_material" and a.get("target") and a.get("color"):
            _scene_color_overrides[a["target"]] = a["color"]

        # assign_material — apply remembered material color to target
        if atype == "assign_material" and a.get("target") and a.get("material_path"):
            mat_name = a["material_path"].rsplit("/", 1)[-1].replace(".mat", "")
            if mat_name in material_colors:
                _scene_color_overrides[a["target"]] = material_colors[mat_name]

        # set_renderer_color / set_material_color
        if atype in ("set_renderer_color", "set_material_color"):
            if a.get("target") and a.get("color"):
                _scene_color_overrides[a["target"]] = a["color"]

        # create_primitive with color
        if atype == "create_primitive" and a.get("name") and a.get("color"):
            _scene_color_overrides[a["name"]] = a["color"]

        # create_light with color
        if atype == "create_light" and a.get("name") and a.get("color"):
            _scene_color_overrides[a["name"]] = a["color"]

        # delete_object — remove stale override
        if atype == "delete_object" and a.get("target"):
            _scene_color_overrides.pop(a["target"], None)

    if material_colors or any(
        a.get("type") in ("apply_material", "set_renderer_color", "set_material_color")
        for a in actions
    ):
        count = len(_scene_color_overrides)
        logger.info("Color overrides updated: %d entries", count)


def _classify_file(ext: str) -> str:
    ext_lower = ext.lower()
    for category, extensions in ASSET_EXTENSIONS.items():
        if ext_lower in extensions:
            return category
    return "other"


# ── Models ───────────────────────────────────────────────────

class CommandRequest(BaseModel):
    command: str
    auto_execute: bool = True
    working_dir: str = ""


class PlanRequest(BaseModel):
    plan: dict


class CommandResponse(BaseModel):
    job_id: str
    status: str
    message: str
    plan: dict | None = None
    result: dict | None = None
    disambiguation: dict | None = None
    suggestions: list[dict] = []
    error_analysis: dict | None = None
    undo_available: bool = False
    warnings: list[str] = []
    confirmation_message: str = ""


class WorkingDirRequest(BaseModel):
    path: str


class ObjectActionRequest(BaseModel):
    target: str
    search_method: str = "by_name"
    action: str  # inspect, delete, duplicate, modify, color
    position: list | dict | None = None
    rotation: list | dict | None = None
    scale: list | dict | None = None
    color: dict | None = None


class MultiCommandRequest(BaseModel):
    commands: list[str]
    sequential: bool = True


class SourceAnalyzeRequest(BaseModel):
    file_path: str


class CompositeAnalyzeRequest(BaseModel):
    file_paths: list[str]
    generate_plan: bool = True


class ChatRequest(BaseModel):
    message: str


class ComponentInstantiateRequest(BaseModel):
    template_id: str
    params: dict = {}


class DrawingAnalyzeRequest(BaseModel):
    image_path: str


class EquipmentEventRequest(BaseModel):
    type: str = "EQUIPMENT_SELECTED"
    assetId: str = ""
    assetTag: str = ""
    assetName: str = ""
    assetType: str = ""
    metadata: dict = {}
    timestamp: float = 0


# ── WebSocket broadcast ──────────────────────────────────────

async def broadcast(event: str, data: dict):
    """Broadcast event to all connected WebSocket clients."""
    message = json.dumps({"event": event, "data": data}, ensure_ascii=False, default=str)
    disconnected = []
    for ws in ws_connections:
        try:
            await ws.send_text(message)
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        ws_connections.remove(ws)


# ── Core Routes ──────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the main Web UI."""
    index_path = frontend_dir / "index.html"
    if index_path.exists():
        return index_path.read_text(encoding="utf-8")
    return HTMLResponse("<h1>Vibe3D Accelerator</h1><p>Frontend not found.</p>")


@app.get("/api/status")
async def get_status():
    """Get MCP connection status and system info."""
    connected = False
    try:
        connected = await asyncio.to_thread(mcp_client.ping)
    except Exception:
        pass

    return {
        "mcp_connected": connected,
        "mcp_url": config.MCP_SERVER_URL,
        "session_id": mcp_client.session_id,
        "has_api_key": bool(config.ANTHROPIC_API_KEY),
        "nlu_available": nlu_engine.available,
        "unity_project": config.UNITY_PROJECT_PATH,
        "jobs_completed": len(job_history),
        "working_dir": _working_dir,
        "pinned_dirs": _pinned_dirs,
        "component_count": len(component_library.get_categories()),
    }


@app.post("/api/connect")
async def connect_mcp():
    """Initialize MCP connection."""
    try:
        success = await asyncio.to_thread(mcp_client.initialize)
        if success:
            await broadcast("mcp_status", {"connected": True})
            return {"status": "connected", "session_id": mcp_client.session_id}
        else:
            raise HTTPException(500, "Failed to initialize MCP session")
    except ConnectionError as e:
        raise HTTPException(503, f"MCP server unreachable: {e}")


@app.get("/api/tools")
async def list_tools():
    """List available MCP tools."""
    try:
        tools = await asyncio.to_thread(mcp_client.list_tools)
        return {"tools": tools, "count": len(tools)}
    except Exception as e:
        raise HTTPException(503, f"MCP error: {e}")


# ── Command Execution ────────────────────────────────────────

@app.post("/api/command", response_model=CommandResponse)
async def execute_command(req: CommandRequest):
    """Process a natural language command — AI-first with preview-before-execute.

    Pipeline: NLU (LLM) → template fallback → validate → return plan for approval.
    The plan is NOT auto-executed. User must call /api/command/{job_id}/approve.
    """
    job_id = str(uuid.uuid4())[:8]
    logger.info("Job %s: command: %s", job_id, req.command)

    command_history.appendleft(req.command)
    await broadcast("job_start", {"job_id": job_id, "command": req.command})

    sc = scene_cache.get_context()
    if not sc.get("objects"):
        # Scene cache is empty — refresh from Unity before processing command
        await _refresh_scene_and_3d_cache()
        sc = scene_cache.get_context()

    # Step 0: Check if command refers to a pending composite plan
    import re as _re
    _COMPOSITE_EXEC_RE = _re.compile(
        r"분석.*만들|구조.*만들|결과.*만들|결과.*실행|결과.*적용|분석.*실행"
        r"|분석.*배치|전체.*만들|파일.*만들|build.*from.*analy|create.*from.*analy"
        r"|import.*all|모두.*만들|전부.*만들|전체.*생성|오브젝트.*만들",
        _re.IGNORECASE,
    )
    global _last_composite_plan
    plan = None
    method = None
    confirmation_message = ""

    if _last_composite_plan and _COMPOSITE_EXEC_RE.search(req.command):
        plan = _last_composite_plan
        method = "composite"
        confirmation_message = f"분석 결과를 기반으로 {len(plan.get('actions', []))}개 오브젝트를 생성합니다."
        logger.info("Job %s: using stored composite plan (%d actions)", job_id, len(plan.get("actions", [])))

    # Step 1: AI-first plan generation
    await broadcast("stage_update", {
        "stage": "plan_generating", "job_id": job_id,
        "message": "AI가 명령을 분석하고 있습니다...",
    })

    if plan is None:
        # Try NLU engine (LLM) first
        nlu_result = await nlu_engine.chat(req.command, sc)

        if nlu_result.get("type") == "response":
            # LLM returned a conversational response (question answer, etc.)
            return CommandResponse(
                job_id=job_id, status="response",
                message=nlu_result.get("content", ""),
            )

        if nlu_result.get("type") == "plan" and nlu_result.get("content"):
            plan = nlu_result["content"]
            method = nlu_result.get("method", "llm")
            confirmation_message = nlu_result.get("confirmation_message", "")
            # Strip LLM metadata fields that aren't part of the plan schema
            for _key in ("type", "confirmation_message", "plan_description"):
                plan.pop(_key, None)

        # Fallback to template if LLM didn't produce a plan
        if plan is None:
            plan, method = await generate_plan(req.command, scene_context=sc)

    if plan is None:
        suggestions = suggestion_engine.get_suggestions(
            req.command, list(command_history), sc
        )
        entry = {
            "job_id": job_id, "command": req.command, "status": "failed",
            "error": "Cannot parse command", "timestamp": time.time(),
        }
        job_history.appendleft(entry)
        await broadcast("job_failed", entry)
        return CommandResponse(
            job_id=job_id, status="failed",
            message="명령을 이해할 수 없습니다. 다시 시도해 주세요.",
            suggestions=[{"label": s.label, "command": s.command, "confidence": s.confidence} for s in suggestions],
        )

    logger.info("Job %s: plan via %s (%d actions)", job_id, method, len(plan.get("actions", [])))
    await broadcast("plan_generated", {"job_id": job_id, "plan": plan, "method": method})

    # Step 2: Validate
    await broadcast("stage_update", {
        "stage": "validating", "job_id": job_id,
        "message": f"플랜 검증 중... ({len(plan.get('actions', []))}개 작업)",
    })
    is_valid, errors, warnings = validate_plan_extended(plan, sc)
    if not is_valid:
        entry = {
            "job_id": job_id, "command": req.command, "status": "validation_failed",
            "errors": errors, "plan": plan, "timestamp": time.time(),
        }
        job_history.appendleft(entry)
        await broadcast("job_failed", entry)
        return CommandResponse(
            job_id=job_id, status="validation_failed",
            message=f"플랜 검증 실패: {'; '.join(errors[:3])}", plan=plan,
            warnings=warnings,
        )

    # Step 3: Store pending plan and return for user approval (never auto-execute)
    if not confirmation_message:
        actions = plan.get("actions", [])
        confirmation_message = plan.get(
            "confirmation_message",
            plan.get("description", f"총 {len(actions)}개 작업을 실행합니다."),
        )

    _pending_plans[job_id] = {
        "plan": plan,
        "method": method,
        "command": req.command,
        "created_at": time.time(),
    }
    # Clean old pending plans (older than 10 minutes)
    now = time.time()
    expired = [k for k, v in _pending_plans.items() if now - v["created_at"] > 600]
    for k in expired:
        del _pending_plans[k]

    await broadcast("plan_preview", {
        "job_id": job_id,
        "plan": plan,
        "method": method,
        "confirmation_message": confirmation_message,
    })

    return CommandResponse(
        job_id=job_id, status="plan_ready",
        message=confirmation_message,
        plan=plan,
        confirmation_message=confirmation_message,
        warnings=warnings,
    )


@app.post("/api/execute")
async def execute_plan(req: PlanRequest):
    """Execute a pre-generated plan directly."""
    job_id = str(uuid.uuid4())[:8]
    is_valid, errors = validate_plan(req.plan)
    if not is_valid:
        raise HTTPException(400, f"Invalid plan: {'; '.join(errors[:3])}")
    try:
        result = await asyncio.to_thread(executor.execute, job_id, "(direct plan)", req.plan, "direct")
    except ConnectionError as e:
        raise HTTPException(503, f"MCP connection lost: {e}")
    except Exception as e:
        logger.error("Execute plan failed: %s\n%s", e, traceback.format_exc())
        raise HTTPException(500, f"Execution failed: {e}")
    entry = {
        "job_id": job_id, "status": result.status.value,
        "total": result.total_actions, "success": result.success_count,
        "fail": result.fail_count, "duration_s": round(result.duration_s, 2),
        "timestamp": time.time(),
    }
    job_history.appendleft(entry)
    return {"job_id": job_id, "result": _safe_asdict(result)}


@app.post("/api/command/{job_id}/approve")
async def approve_plan(job_id: str):
    """Approve and execute a pending plan."""
    pending = _pending_plans.pop(job_id, None)
    if not pending:
        raise HTTPException(404, f"No pending plan found for job {job_id}")

    plan = pending["plan"]
    method = pending["method"]
    command = pending["command"]

    logger.info("Job %s: APPROVED by user, executing %d actions", job_id, len(plan.get("actions", [])))
    await broadcast("plan_approved", {"job_id": job_id})

    # Track WebGL build state for monitoring
    if method == "webgl_build":
        # Extract output_path from plan description
        desc = plan.get("description", "")
        build_path = desc.replace("WebGL 빌드 → ", "").strip() if "→" in desc else ""
        _webgl_build_state.update({
            "status": "building",
            "output_path": build_path,
            "started_at": time.time(),
            "completed_at": 0.0,
            "message": "빌드 시작...",
        })

    # Progress callback via WebSocket
    loop = asyncio.get_running_loop()

    def _progress_sync(jid, idx, total, action_type, status):
        asyncio.run_coroutine_threadsafe(
            broadcast("action_progress", {
                "job_id": jid, "current": idx + 1, "total": total,
                "action_type": action_type, "status": status,
            }),
            loop,
        )

    await broadcast("stage_update", {
        "stage": "mcp_executing", "job_id": job_id,
        "message": f"MCP 실행 중... ({len(plan.get('actions', []))}개 작업)",
    })

    # Snapshot original colors for apply_material targets (for undo)
    original_colors: dict[str, dict] = {}
    for a in plan.get("actions", []):
        if a.get("type") == "apply_material" and a.get("target"):
            target_name = a["target"]
            if target_name not in original_colors:
                # Check server-side color overrides first, then infer from name
                prev = _scene_color_overrides.get(target_name)
                if prev:
                    original_colors[target_name] = dict(prev)
                else:
                    inferred = _infer_color_3d(target_name)
                    original_colors[target_name] = {**inferred, "a": 1.0}

    try:
        result = await asyncio.to_thread(
            executor.execute, job_id, command, plan, method, _progress_sync,
            original_colors if original_colors else None,
        )
    except ConnectionError as e:
        raise HTTPException(503, f"MCP connection lost: {e}")
    except Exception as e:
        logger.error("Job %s executor failed: %s\n%s", job_id, e, traceback.format_exc())
        raise HTTPException(500, f"Execution failed: {e}")

    await broadcast("stage_update", {
        "stage": "mcp_done", "job_id": job_id,
        "message": f"MCP 완료: {result.success_count}/{result.total_actions} 성공 ({result.duration_s:.1f}s)",
    })

    if result.success_count > 0:
        # Update server-side color overrides from plan
        _extract_color_overrides(plan)
        # Invalidate + refresh scene cache so next commands have fresh context
        scene_cache.invalidate()
        try:
            await _refresh_scene_and_3d_cache()
        except Exception as e:
            logger.warning("Scene cache refresh after approve failed: %s", e)

    entry = {
        "job_id": job_id, "command": command, "status": result.status.value,
        "method": method, "total": result.total_actions,
        "success": result.success_count, "fail": result.fail_count,
        "duration_s": round(result.duration_s, 2), "timestamp": time.time(),
        "undo_available": result.undo_plan is not None,
    }
    job_history.appendleft(entry)
    event = "job_completed" if result.status == JobStatus.COMPLETED else "job_failed"
    await broadcast(event, entry)

    return {
        "job_id": job_id,
        "status": result.status.value,
        "message": f"{result.success_count}/{result.total_actions} 성공 ({result.duration_s:.1f}s)",
        "result": _safe_asdict(result),
        "plan": plan,  # Include plan so frontend can extract visual changes
        "undo_available": result.undo_plan is not None,
    }


@app.post("/api/command/{job_id}/reject")
async def reject_plan(job_id: str):
    """Reject and discard a pending plan."""
    pending = _pending_plans.pop(job_id, None)
    if not pending:
        raise HTTPException(404, f"No pending plan found for job {job_id}")

    logger.info("Job %s: REJECTED by user", job_id)
    await broadcast("plan_rejected", {"job_id": job_id})

    entry = {
        "job_id": job_id, "command": pending["command"], "status": "rejected",
        "timestamp": time.time(),
    }
    job_history.appendleft(entry)

    return {"status": "rejected", "job_id": job_id}


@app.post("/api/multi-command")
async def execute_multi_commands(req: MultiCommandRequest):
    """Execute multiple commands in sequence."""
    results = []
    for i, cmd in enumerate(req.commands):
        job_id = str(uuid.uuid4())[:8]
        plan, method = await generate_plan(cmd)
        if plan is None:
            results.append({"index": i, "command": cmd, "status": "failed", "message": "Cannot parse"})
            continue
        is_valid, errors = validate_plan(plan)
        if not is_valid:
            results.append({"index": i, "command": cmd, "status": "invalid", "errors": errors})
            continue
        try:
            result = await asyncio.to_thread(executor.execute, job_id, cmd, plan, method)
            results.append({
                "index": i, "command": cmd, "job_id": job_id,
                "status": result.status.value,
                "success": result.success_count, "total": result.total_actions,
            })
        except Exception as e:
            results.append({"index": i, "command": cmd, "status": "error", "message": str(e)})

    return {"total_commands": len(req.commands), "results": results}


# ── Working Directory & File Browser ─────────────────────────

@app.get("/api/workdir")
async def get_working_dir():
    """Get current working directory info."""
    return {"path": _working_dir, "pinned": _pinned_dirs}


@app.post("/api/workdir")
async def set_working_dir(req: WorkingDirRequest):
    """Set the working directory."""
    global _working_dir
    path = req.path.strip()
    if not os.path.isdir(path):
        raise HTTPException(400, f"Not a valid directory: {path}")
    _working_dir = path
    await broadcast("workdir_changed", {"path": path})
    return {"path": _working_dir}


@app.post("/api/workdir/pin")
async def pin_directory(req: WorkingDirRequest):
    """Pin a directory for quick access."""
    path = req.path.strip().replace("\\", "/")
    # Check both forward and backslash variants
    existing = [p.replace("\\", "/") for p in _pinned_dirs]
    if path not in existing:
        _pinned_dirs.append(path)
    return {"pinned": _pinned_dirs}


@app.post("/api/workdir/unpin")
async def unpin_directory(req: WorkingDirRequest):
    """Remove a pinned directory."""
    path = req.path.strip().replace("\\", "/")
    # Remove matching entry (normalize for comparison)
    to_remove = [p for p in _pinned_dirs if p.replace("\\", "/") == path]
    for p in to_remove:
        _pinned_dirs.remove(p)
    return {"pinned": _pinned_dirs}


@app.get("/api/files")
async def list_files(
    path: str = "",
    show_hidden: bool = False,
):
    """List files and directories at the given path."""
    target = path or _working_dir
    if not os.path.isdir(target):
        raise HTTPException(400, f"Not a directory: {target}")

    entries = []
    try:
        for item in sorted(os.listdir(target)):
            if not show_hidden and item.startswith("."):
                continue
            full_path = os.path.join(target, item)
            is_dir = os.path.isdir(full_path)
            ext = os.path.splitext(item)[1] if not is_dir else ""
            entry = {
                "name": item,
                "path": full_path.replace("\\", "/"),
                "is_dir": is_dir,
                "ext": ext,
                "category": _classify_file(ext) if not is_dir else "folder",
            }
            if not is_dir:
                try:
                    stat = os.stat(full_path)
                    entry["size"] = stat.st_size
                    entry["modified"] = stat.st_mtime
                except OSError:
                    pass
            entries.append(entry)
    except PermissionError:
        raise HTTPException(403, f"Permission denied: {target}")

    return {
        "path": target.replace("\\", "/"),
        "parent": str(Path(target).parent).replace("\\", "/"),
        "entries": entries,
        "count": len(entries),
    }


@app.get("/api/files/drives")
async def list_drives():
    """List available drives (Windows)."""
    import string
    drives = []
    for letter in string.ascii_uppercase:
        drive = f"{letter}:\\"
        if os.path.exists(drive):
            drives.append({"letter": letter, "path": drive})
    return {"drives": drives}


# ── Scene / Object Operations ────────────────────────────────

@app.get("/api/hierarchy")
async def get_hierarchy(parent: str = "", max_depth: int = 3):
    """Get Unity scene hierarchy."""
    try:
        result = await asyncio.to_thread(mcp_client.get_hierarchy, parent, max_depth)
        return result
    except Exception as e:
        raise HTTPException(503, f"MCP error: {e}")


@app.get("/api/object/inspect")
async def inspect_object(target: str, search_method: str = "by_name"):
    """Get detailed info about a specific object."""
    try:
        result = await asyncio.to_thread(mcp_client.find_objects, target, search_method)
        return result
    except Exception as e:
        raise HTTPException(503, f"MCP error: {e}")


@app.post("/api/object/action")
async def object_action(req: ObjectActionRequest):
    """Perform action on an object (delete, duplicate, modify transform, color)."""
    try:
        if req.action == "delete":
            result = await asyncio.to_thread(mcp_client.delete_object, req.target, req.search_method)
        elif req.action == "duplicate":
            result = await asyncio.to_thread(mcp_client.tool_call, "manage_gameobject", {
                "action": "duplicate", "target": req.target, "search_method": req.search_method,
            })
        elif req.action == "modify":
            args = {"action": "modify", "target": req.target, "search_method": req.search_method}
            if req.position:
                args["position"] = req.position
            if req.rotation:
                args["rotation"] = req.rotation
            if req.scale:
                args["scale"] = req.scale
            result = await asyncio.to_thread(mcp_client.tool_call, "manage_gameobject", args)
        elif req.action == "color":
            if not req.color:
                raise HTTPException(400, "color is required for color action")
            result = await asyncio.to_thread(
                mcp_client.set_color,
                req.target, req.color["r"], req.color["g"], req.color["b"],
                req.color.get("a", 1.0), req.search_method,
            )
        elif req.action == "inspect":
            result = await asyncio.to_thread(mcp_client.find_objects, req.target, req.search_method)
        else:
            raise HTTPException(400, f"Unknown action: {req.action}")
        return result
    except ConnectionError as e:
        raise HTTPException(503, f"MCP error: {e}")


@app.post("/api/screenshot")
async def take_screenshot(filename: str = "vibe3d_screenshot"):
    """Take a screenshot."""
    try:
        return await asyncio.to_thread(mcp_client.screenshot, filename)
    except Exception as e:
        raise HTTPException(503, f"MCP error: {e}")


@app.get("/api/console")
async def read_console(count: int = 30):
    """Read Unity console messages."""
    try:
        return await asyncio.to_thread(mcp_client.read_console, count)
    except Exception as e:
        raise HTTPException(503, f"MCP error: {e}")


@app.get("/api/jobs")
async def get_jobs(limit: int = 50):
    """Get recent job history."""
    return {"jobs": list(job_history)[:limit]}


@app.get("/api/command-history")
async def get_command_history():
    """Get command history for autocomplete."""
    return {"commands": list(command_history)}


@app.post("/api/scene/save")
async def save_scene():
    """Save the current Unity scene."""
    try:
        return await asyncio.to_thread(mcp_client.save_scene)
    except Exception as e:
        raise HTTPException(503, f"MCP error: {e}")


# ── Template Presets ─────────────────────────────────────────

@app.get("/api/presets")
async def get_presets():
    """Get available command presets/templates."""
    return {
        "presets": [
            {
                "category": "기본 생성",
                "icon": "cube",
                "items": [
                    {"label": "바닥 (Floor)", "command": "가로 {w}m 세로 {d}m 바닥을 만들고 회색 콘크리트 재질 적용", "params": {"w": "20", "d": "10"}},
                    {"label": "큐브 (Cube)", "command": "큐브를 ({x},{y},{z})에 만들어줘", "params": {"x": "0", "y": "1", "z": "0"}},
                    {"label": "구 (Sphere)", "command": "구를 ({x},{y},{z})에 만들어줘", "params": {"x": "0", "y": "1", "z": "0"}},
                    {"label": "탱크 (Cylinder)", "command": "스테인리스 탱크를 ({x},{y},{z})에 배치하고 이름을 {name}으로", "params": {"x": "0", "y": "0", "z": "0", "name": "Tank_A"}},
                ],
            },
            {
                "category": "조명",
                "icon": "light",
                "items": [
                    {"label": "조명 1개", "command": "조명을 높이 {h}m에 만들어줘", "params": {"h": "5"}},
                    {"label": "조명 그리드", "command": "조명 {n}개를 천장 높이 {h}m에 격자로 배치해줘", "params": {"n": "4", "h": "5"}},
                ],
            },
            {
                "category": "재질/색상",
                "icon": "palette",
                "items": [
                    {"label": "색상 적용", "command": "{target}에 {color} 재질 적용해줘", "params": {"target": "Floor", "color": "빨간"}},
                ],
            },
            {
                "category": "씬 관리",
                "icon": "scene",
                "items": [
                    {"label": "스크린샷", "command": "현재 씬을 스크린샷 찍어줘", "params": {}},
                    {"label": "씬 저장", "command": "현재 씬을 저장해줘", "params": {}},
                ],
            },
            {
                "category": "발효설비",
                "icon": "factory",
                "items": [
                    {"label": "시설 빌드", "command": "Fermentation/Build Complete Facility 메뉴 실행", "params": {}},
                    {"label": "계층 확인", "command": "FermentationFacility 하위 구조를 보여줘", "params": {}},
                ],
            },
        ]
    }


# ── Suggest / Autocomplete ───────────────────────────────────

@app.get("/api/suggest")
async def get_suggestions(prefix: str = "", limit: int = 5):
    """Get autocomplete suggestions for command input."""
    results = []

    # Match from command history
    prefix_lower = prefix.lower()
    for cmd in command_history:
        if prefix_lower in cmd.lower():
            results.append({"label": cmd, "source": "history"})
            if len(results) >= limit:
                break

    # Match from presets
    presets_resp = await get_presets()
    for group in presets_resp.get("presets", []):
        for item in group.get("items", []):
            if prefix_lower in item["label"].lower() or prefix_lower in item["command"].lower():
                results.append({"label": item["label"], "command": item["command"], "source": "preset"})

    # Match from scene objects
    sc = scene_cache.get_context()
    objects = sc.get("objects", {})
    for obj in (objects.values() if isinstance(objects, dict) else objects):
        name = obj.get("name", "") if isinstance(obj, dict) else str(obj)
        if prefix_lower in name.lower():
            results.append({"label": name, "source": "scene_object"})

    return {"suggestions": results[:limit], "prefix": prefix}


# ── Scene Context ────────────────────────────────────────────

@app.get("/api/scene/context")
async def get_scene_context():
    """Get cached scene context (objects, bounds)."""
    ctx = scene_cache.get_context()
    if not ctx.get("objects"):
        # Try to refresh from MCP (blocking I/O → thread)
        await _refresh_scene_and_3d_cache()
        ctx = scene_cache.get_context()
    return ctx


@app.post("/api/scene/context/refresh")
async def refresh_scene_context():
    """Force refresh scene context from Unity."""
    await _refresh_scene_and_3d_cache()
    return scene_cache.get_context()


# ── Undo ─────────────────────────────────────────────────────

@app.post("/api/undo/{job_id}")
async def undo_job(job_id: str):
    """Undo a previously executed job."""
    undo_plan = executor.get_undo_plan(job_id)
    if not undo_plan:
        raise HTTPException(404, f"No undo plan for job {job_id}")

    try:
        undo_result = await asyncio.to_thread(executor.execute_undo, job_id)
    except Exception as e:
        logger.error("Undo %s failed: %s\n%s", job_id, e, traceback.format_exc())
        raise HTTPException(500, f"Undo failed: {e}")
    if undo_result is None:
        raise HTTPException(404, "Undo execution failed")

    if undo_result.success_count > 0:
        # Clean up color overrides for objects that were undone (deleted)
        undo_plan_actions = undo_plan.get("actions", [])
        for a in undo_plan_actions:
            if a.get("type") == "delete_object" and a.get("target"):
                _scene_color_overrides.pop(a["target"], None)
        scene_cache.invalidate()
        try:
            await _refresh_scene_and_3d_cache()
        except Exception as e:
            logger.warning("Scene cache refresh after undo failed: %s", e)

    entry = {
        "job_id": undo_result.job_id, "command": f"Undo {job_id}",
        "status": undo_result.status.value,
        "success": undo_result.success_count, "total": undo_result.total_actions,
        "timestamp": time.time(),
    }
    job_history.appendleft(entry)
    await broadcast("job_completed", entry)
    return {"job_id": undo_result.job_id, "result": _safe_asdict(undo_result)}


# ── WebGL Viewer Setup & Build ───────────────────────────────

class WebGLBuildRequest(BaseModel):
    output_path: str


@app.post("/api/webgl/setup")
async def webgl_setup():
    """Generate a plan to install WebGL viewer (CameraRig + scripts + UI).

    Returns plan_ready for user approval via /api/command/{job_id}/approve.
    """
    job_id = str(uuid.uuid4())[:8]
    plan = generate_setup_plan()
    method = "webgl_setup"

    is_valid, errors, warnings = validate_plan_extended(plan, scene_cache.get_context())
    if not is_valid:
        raise HTTPException(400, f"Plan validation failed: {'; '.join(errors[:3])}")

    _pending_plans[job_id] = {
        "plan": plan,
        "method": method,
        "command": "WebGL Viewer Setup",
        "created_at": time.time(),
    }

    await broadcast("plan_preview", {
        "job_id": job_id,
        "plan": plan,
        "method": method,
        "confirmation_message": plan.get("confirmation_message", ""),
    })

    return {
        "job_id": job_id,
        "status": "plan_ready",
        "message": plan.get("confirmation_message", ""),
        "plan": plan,
    }


@app.post("/api/webgl/build")
async def webgl_build(req: WebGLBuildRequest):
    """Generate a plan to build WebGL to the specified output path.

    Automatically includes viewer setup (CameraRig, scripts, components)
    if not already installed in the scene.

    Returns plan_ready for user approval via /api/command/{job_id}/approve.
    """
    output_path = req.output_path.strip()
    if not output_path:
        raise HTTPException(400, "output_path is required")

    # Auto-detect if viewer setup is needed
    ctx = scene_cache.get_context()
    objects = ctx.get("objects", {})
    obj_iter = objects.values() if isinstance(objects, dict) else objects
    has_rig = any(
        (o.get("name") if isinstance(o, dict) else str(o)) == "CameraRig"
        for o in obj_iter
    )

    need_setup = True
    components_only = False

    if has_rig:
        # CameraRig exists — check if OrbitPanZoomController is attached via
        # a harmless set_property call (sets rotateSpeed to its default value).
        try:
            resp = await asyncio.to_thread(
                mcp_client.tool_call, "manage_components",
                {
                    "action": "set_property",
                    "target": "CameraRig",
                    "component_type": "OrbitPanZoomController",
                    "property": "rotateSpeed",
                    "value": 0.25,
                    "search_method": "by_name",
                },
            )
            # Parse success from response
            ok = False
            if isinstance(resp, dict):
                rd = resp.get("result", resp)
                if isinstance(rd, dict) and not rd.get("isError", False):
                    for item in rd.get("content", []):
                        if item.get("type") == "text":
                            try:
                                ok = json.loads(item["text"]).get("success", False)
                            except (json.JSONDecodeError, TypeError):
                                pass
                            break
            if ok:
                need_setup = False
                logger.info("[WebGL] OrbitPanZoomController detected on CameraRig → skip setup")
            else:
                need_setup = True
                components_only = True
                logger.info("[WebGL] CameraRig exists but OrbitPanZoomController missing → components_only setup")
        except Exception as e:
            logger.warning("[WebGL] Component check failed, assuming setup needed: %s", e)
            need_setup = True
            components_only = True
    else:
        logger.info("[WebGL] CameraRig not found → full setup")

    job_id = str(uuid.uuid4())[:8]
    plan = generate_build_plan(
        output_path,
        include_setup=need_setup,
        components_only=components_only,
    )
    method = "webgl_build"

    is_valid, errors, warnings = validate_plan_extended(plan, scene_cache.get_context())
    if not is_valid:
        raise HTTPException(400, f"Plan validation failed: {'; '.join(errors[:3])}")

    _pending_plans[job_id] = {
        "plan": plan,
        "method": method,
        "command": f"WebGL Build → {output_path}",
        "created_at": time.time(),
    }

    await broadcast("plan_preview", {
        "job_id": job_id,
        "plan": plan,
        "method": method,
        "confirmation_message": plan.get("confirmation_message", ""),
    })

    return {
        "job_id": job_id,
        "status": "plan_ready",
        "message": plan.get("confirmation_message", ""),
        "plan": plan,
    }


@app.get("/api/webgl/status")
async def webgl_status():
    """Check if WebGL viewer components are installed in the scene."""
    ctx = scene_cache.get_context()
    objects = ctx.get("objects", {})

    has_camera_rig = False
    has_pivot = False
    has_viewer_canvas = False

    obj_iter = objects.values() if isinstance(objects, dict) else objects
    for obj in obj_iter:
        name = obj.get("name", "") if isinstance(obj, dict) else str(obj)
        if name == "CameraRig":
            has_camera_rig = True
        elif name == "Pivot":
            has_pivot = True
        elif name == "ViewerCanvas":
            has_viewer_canvas = True

    installed = has_camera_rig and has_pivot and has_viewer_canvas
    return {
        "installed": installed,
        "camera_rig": has_camera_rig,
        "pivot": has_pivot,
        "viewer_canvas": has_viewer_canvas,
    }


# Track WebGL build state
_webgl_build_state: dict[str, Any] = {
    "status": "idle",        # idle | building | completed | failed
    "output_path": "",
    "started_at": 0.0,
    "completed_at": 0.0,
    "message": "",
}


@app.get("/api/webgl/build-status")
async def webgl_build_status():
    """Check WebGL build status by monitoring output directory + Unity console."""
    state = _webgl_build_state.copy()

    if state["status"] == "building" and state["output_path"]:
        output_path = Path(state["output_path"])
        # Check if build output has been updated since build started
        started = state["started_at"]
        index_html = output_path / "index.html"
        build_dir = output_path / "Build"

        if index_html.exists() and index_html.stat().st_mtime > started:
            # Build output updated — build is done
            build_files = []
            if build_dir.exists():
                build_files = [f.name for f in build_dir.iterdir() if f.is_file()]
            state["status"] = "completed"
            state["completed_at"] = index_html.stat().st_mtime
            state["message"] = f"빌드 완료 ({len(build_files)}개 파일)"
            state["build_files"] = build_files
            state["duration_s"] = round(state["completed_at"] - started, 1)
            _webgl_build_state.update(state)
        else:
            # Still building — check elapsed time
            elapsed = time.time() - started
            state["elapsed_s"] = round(elapsed, 1)
            state["message"] = f"빌드 진행 중... ({int(elapsed)}초 경과)"

            # Check console for errors
            try:
                console = await asyncio.to_thread(mcp_client.read_console, 10)
                result = console.get("result", console)
                for item in result.get("content", []):
                    if item.get("type") == "text":
                        import json as _json
                        parsed = _json.loads(item["text"])
                        for entry in parsed.get("data", []):
                            msg = entry if isinstance(entry, str) else entry.get("message", "")
                            if "[Vibe3D]" in str(msg):
                                if "failed" in str(msg).lower() or "exception" in str(msg).lower():
                                    state["status"] = "failed"
                                    state["message"] = str(msg)[:200]
                                    _webgl_build_state.update(state)
                                elif "succeeded" in str(msg).lower():
                                    state["status"] = "completed"
                                    state["message"] = str(msg)[:200]
                                    _webgl_build_state.update(state)
            except Exception:
                pass

    return state


# ── Source Analysis ──────────────────────────────────────────

@app.post("/api/source/analyze")
async def analyze_source_file(req: SourceAnalyzeRequest):
    """Analyze a source file for quality and recommendations."""
    file_path = req.file_path
    if not file_path:
        raise HTTPException(400, "file_path required")
    analysis = analyze_file(file_path)
    return {
        "file_path": analysis.file_path,
        "file_type": analysis.file_type,
        "score": analysis.score,
        "issues": analysis.issues,
        "recommendations": analysis.recommendations,
        "auto_fix_available": analysis.auto_fix_available,
        "metadata": analysis.metadata,
    }


@app.post("/api/source/to-plan")
async def convert_source_to_plan(req: SourceAnalyzeRequest):
    """Convert a source file to a Unity action plan."""
    file_path = req.file_path
    if not file_path:
        raise HTTPException(400, "file_path required")
    analysis = analyze_file(file_path)
    plan = source_to_plan(file_path, analysis)
    if not plan:
        raise HTTPException(422, "Cannot generate plan from this source type")
    return {"plan": plan, "analysis_score": analysis.score}


@app.post("/api/source/composite-analyze")
async def composite_analyze_endpoint(req: CompositeAnalyzeRequest):
    """Analyze multiple files together for cross-file relationships and unified plan."""
    if not req.file_paths:
        raise HTTPException(400, "file_paths must not be empty")

    logger.info("[API] Composite analyze: %d files", len(req.file_paths))
    await broadcast("stage_update", {
        "stage": "composite_start",
        "message": f"복합 분석 시작: {len(req.file_paths)}개 파일",
        "total": len(req.file_paths),
    })

    # Progress callback that broadcasts via WebSocket
    loop = asyncio.get_running_loop()

    def _composite_progress(stage: str, detail: str, current: int, total: int):
        asyncio.run_coroutine_threadsafe(
            broadcast("composite_progress", {
                "stage": stage,
                "detail": detail,
                "current": current,
                "total": total,
            }),
            loop,
        )

    result = await asyncio.to_thread(composite_analyze, req.file_paths, _composite_progress)

    # Store composite plan for follow-up commands like "분석 결과로 만들어"
    global _last_composite_plan
    if result.composite_plan and result.composite_plan.get("actions"):
        _last_composite_plan = result.composite_plan
        logger.info("[API] Stored composite plan: %d actions", len(result.composite_plan["actions"]))

    await broadcast("stage_update", {
        "stage": "composite_done",
        "message": result.summary,
        "plan_actions": len(result.composite_plan.get("actions", [])) if result.composite_plan else 0,
    })

    return {
        "files": [
            {
                "file_path": a.file_path,
                "file_type": a.file_type,
                "score": a.score,
                "issues": a.issues,
                "recommendations": a.recommendations,
                "metadata": a.metadata,
            }
            for a in result.files
        ],
        "relationships": result.relationships,
        "scene_structure": result.scene_structure,
        "composite_plan": result.composite_plan if req.generate_plan else None,
        "summary": result.summary,
    }


@app.post("/api/source/composite-plan")
async def composite_plan_endpoint(req: CompositeAnalyzeRequest):
    """Generate a unified execution plan from multiple files."""
    if not req.file_paths:
        raise HTTPException(400, "file_paths must not be empty")

    loop = asyncio.get_running_loop()

    def _progress(stage, detail, current, total):
        asyncio.run_coroutine_threadsafe(
            broadcast("composite_progress", {
                "stage": stage, "detail": detail, "current": current, "total": total,
            }),
            loop,
        )

    result = await asyncio.to_thread(composite_analyze, req.file_paths, _progress)
    if not result.composite_plan or not result.composite_plan.get("actions"):
        raise HTTPException(422, "Cannot generate plan from the given files")
    return {
        "plan": result.composite_plan,
        "summary": result.summary,
        "relationship_count": len(result.relationships),
    }


@app.get("/api/source/batch")
async def batch_analyze_files(path: str = ""):
    """Analyze all files in a directory."""
    target = path or _working_dir
    results = batch_analyze(target)
    return {
        "path": target,
        "count": len(results),
        "files": [
            {
                "file_path": a.file_path,
                "file_type": a.file_type,
                "score": a.score,
                "issues_count": len(a.issues),
            }
            for a in results
        ],
    }


# ── Preview ──────────────────────────────────────────────────

@app.post("/api/preview")
async def preview_plan(req: PlanRequest):
    """Generate a 2D preview of a plan (positions/bounds)."""
    actions = req.plan.get("actions", [])
    preview_objects = []
    for action in actions:
        if action.get("type") in ("create_primitive", "create_empty", "create_light"):
            pos = action.get("position", {"x": 0, "y": 0, "z": 0})
            scale = action.get("scale", {"x": 1, "y": 1, "z": 1})
            preview_objects.append({
                "name": action.get("name", "?"),
                "type": action.get("type"),
                "shape": action.get("shape", action.get("light_type", "Empty")),
                "x": pos.get("x", 0),
                "y": pos.get("y", 0),
                "z": pos.get("z", 0),
                "sx": scale.get("x", 1),
                "sy": scale.get("y", 1),
                "sz": scale.get("z", 1),
            })

    # Include existing scene objects for context
    sc = scene_cache.get_context()
    existing = [
        {
            "name": o.get("name", ""),
            "x": o.get("position", {}).get("x", 0),
            "z": o.get("position", {}).get("z", 0),
            "sx": o.get("scale", {}).get("x", 1),
            "sz": o.get("scale", {}).get("z", 1),
            "existing": True,
        }
        for o in (sc.get("objects", {}).values() if isinstance(sc.get("objects"), dict) else sc.get("objects", []))
    ]

    return {
        "new_objects": preview_objects,
        "existing_objects": existing,
        "bounds": sc.get("bounds", {}),
    }


# ── Workflows ────────────────────────────────────────────────

@app.get("/api/workflows")
async def list_workflows():
    """List all workflow templates."""
    workflows = workflow_mgr.list_all()
    return {"workflows": [w.__dict__ if hasattr(w, '__dict__') else w for w in workflows]}


@app.post("/api/workflows")
async def create_workflow(data: dict):
    """Create a new workflow template."""
    wf = workflow_mgr.create(
        name=data.get("name", "Untitled"),
        description=data.get("description", ""),
        steps=data.get("steps", []),
        plan_template=data.get("plan_template", {}),
    )
    return {"workflow": wf.__dict__ if hasattr(wf, '__dict__') else wf}


@app.get("/api/workflows/{workflow_id}")
async def get_workflow(workflow_id: str):
    """Get a specific workflow template."""
    wf = workflow_mgr.get(workflow_id)
    if not wf:
        raise HTTPException(404, "Workflow not found")
    return {"workflow": wf.__dict__ if hasattr(wf, '__dict__') else wf}


@app.delete("/api/workflows/{workflow_id}")
async def delete_workflow(workflow_id: str):
    """Delete a workflow template."""
    success = workflow_mgr.delete(workflow_id)
    if not success:
        raise HTTPException(404, "Workflow not found")
    return {"deleted": True}


@app.post("/api/workflows/{workflow_id}/execute")
async def execute_workflow(workflow_id: str, params: dict):
    """Execute a workflow with given parameters."""
    plan = workflow_mgr.execute(workflow_id, params)
    if not plan:
        raise HTTPException(404, "Workflow not found or execution failed")
    # Validate and execute the generated plan
    is_valid, errors = validate_plan(plan)
    if not is_valid:
        raise HTTPException(400, f"Generated plan invalid: {'; '.join(errors[:3])}")
    job_id = str(uuid.uuid4())[:8]
    result = executor.execute(job_id, f"(workflow:{workflow_id})", plan, "workflow")
    return {"job_id": job_id, "result": _safe_asdict(result)}


# ── Chat (NLU) ───────────────────────────────────────────

@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest):
    """Unified AI chat — returns plan for approval or conversational response.

    Plans are NOT auto-executed. They are stored as pending and require
    user approval via /api/command/{job_id}/approve.
    """
    sc = scene_cache.get_context()
    result = await nlu_engine.chat(req.message, sc)

    if result.get("type") == "plan" and result.get("content"):
        plan = result["content"]
        method = result.get("method", "llm")
        confirmation_message = result.get("confirmation_message", "")
        is_valid, errors, warnings = validate_plan_extended(plan, sc)

        if is_valid:
            job_id = str(uuid.uuid4())[:8]
            if not confirmation_message:
                confirmation_message = plan.get(
                    "confirmation_message",
                    plan.get("description", f"총 {len(plan.get('actions', []))}개 작업을 실행합니다."),
                )

            # Store as pending plan for approval
            _pending_plans[job_id] = {
                "plan": plan,
                "method": method,
                "command": req.message,
                "created_at": time.time(),
            }

            await broadcast("plan_preview", {
                "job_id": job_id,
                "plan": plan,
                "method": method,
                "confirmation_message": confirmation_message,
            })

            return {
                "type": "plan",
                "status": "plan_ready",
                "message": confirmation_message,
                "plan": plan,
                "job_id": job_id,
                "confirmation_message": confirmation_message,
            }
        else:
            return {
                "type": "plan",
                "status": "validation_failed",
                "message": f"플랜 검증 실패: {'; '.join(errors[:3])}",
                "plan": plan,
                "errors": errors,
            }

    return {"type": "response", "message": result.get("content", "")}


@app.get("/api/chat/history")
async def get_chat_history():
    """Get conversation history."""
    return {"history": nlu_engine.get_history()}


@app.post("/api/chat/clear")
async def clear_chat_history():
    """Clear conversation history."""
    nlu_engine.clear_history()
    return {"status": "cleared"}


# ── Component Library ────────────────────────────────────

@app.get("/api/components")
async def list_components():
    """List all component template categories."""
    return {"categories": component_library.get_categories()}


@app.get("/api/components/{template_id}")
async def get_component_template(template_id: str):
    """Get a specific component template."""
    tmpl = component_library.get_template(template_id)
    if not tmpl:
        raise HTTPException(404, f"Template not found: {template_id}")
    return {"template": tmpl}


@app.post("/api/components/instantiate")
async def instantiate_component(req: ComponentInstantiateRequest):
    """Instantiate a component from template and execute."""
    plan = component_library.instantiate(req.template_id, req.params)
    if not plan:
        raise HTTPException(404, f"Template not found: {req.template_id}")

    # Validate and execute
    is_valid, errors = validate_plan(plan)
    if not is_valid:
        raise HTTPException(400, f"Generated plan invalid: {'; '.join(errors[:3])}")

    job_id = str(uuid.uuid4())[:8]
    await broadcast("job_start", {"job_id": job_id, "command": f"Component: {req.template_id}"})
    await broadcast("plan_generated", {"job_id": job_id, "plan": plan, "method": "component_library"})

    try:
        result = await asyncio.to_thread(executor.execute, job_id, f"(component:{req.template_id})", plan, "component_library")
        if result.success_count > 0:
            scene_cache.invalidate()
        entry = {
            "job_id": job_id, "command": f"Component: {req.template_id}",
            "status": result.status.value, "success": result.success_count,
            "total": result.total_actions, "timestamp": time.time(),
        }
        job_history.appendleft(entry)
        await broadcast("job_completed" if result.status == JobStatus.COMPLETED else "job_failed", entry)
        return {"job_id": job_id, "result": _safe_asdict(result), "plan": plan}
    except Exception as e:
        raise HTTPException(500, f"Execution failed: {e}")


# ── Drawing Analysis ─────────────────────────────────────

@app.post("/api/drawing/analyze")
async def analyze_drawing(req: DrawingAnalyzeRequest):
    """Analyze an engineering drawing using NLU Vision API."""
    if not nlu_engine.available:
        raise HTTPException(400, "ANTHROPIC_API_KEY not configured")
    result = await nlu_engine.analyze_drawing(req.image_path)
    if not result:
        raise HTTPException(422, "Drawing analysis failed")
    return {"analysis": result, "image_path": req.image_path}


# ── Equipment Selection (iframe → parent app) ────────────

@app.post("/api/equipment/event")
async def equipment_event(req: EquipmentEventRequest):
    """Receive equipment selection event from frontend (postMessage + REST)."""
    global _last_equipment_event
    _last_equipment_event = req.model_dump()
    await broadcast("equipment_selected", _last_equipment_event)
    logger.info("Equipment selected: %s (%s)", req.assetName, req.assetTag)
    return {"status": "ok"}


@app.get("/api/equipment/selected")
async def equipment_selected():
    """Get last selected equipment info (REST polling for parent app)."""
    return _last_equipment_event or {"type": "NONE"}


# ── Screenshot Serving ───────────────────────────────────

@app.get("/api/screenshots/latest")
async def get_latest_screenshot():
    """Get the latest screenshot as an image file."""
    screenshots_dir = Path(config.UNITY_PROJECT_PATH) / "Screenshots"
    if not screenshots_dir.exists():
        raise HTTPException(404, "No screenshots directory")
    pngs = sorted(screenshots_dir.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not pngs:
        raise HTTPException(404, "No screenshots found")
    return FileResponse(str(pngs[0]), media_type="image/png")


# ── 3D Scene Data ────────────────────────────────────────────

def _infer_primitive_3d(name: str) -> str:
    """Infer primitive type from object name for 3D viewer."""
    n = name.lower()
    if any(k in n for k in ("floor", "ground", "platform", "slab", "checker")):
        return "Cube"
    if "plane" in n:
        return "Plane"
    # Dome/dish heads — must check BEFORE cylinder (dishhead contains "head" not "dome")
    if any(k in n for k in ("sphere", "ball", "dome", "dishhead", "dish_head")):
        return "Sphere"
    if any(k in n for k in (
        "cylinder", "body", "pipe", "column", "tube", "col_", "jacket",
        "tank", "vessel", "scrubber", "receiver", "drum", "shaft",
        "nozzle", "inlet", "outlet", "header", "exhaust",
    )):
        return "Cylinder"
    if "capsule" in n:
        return "Capsule"
    if "cone" in n:
        return "Cone"
    if any(k in n for k in ("light", "lamp")):
        return "Light"
    if any(k in n for k in ("camera", "eventsystem")):
        return "Empty"
    return "Cube"


def _extract_asset_tag(name: str) -> str:
    """Extract P&ID-style asset tag from object name (e.g. 'TCV-7742', 'V-101')."""
    import re
    m = re.search(r'[A-Z]{1,4}-\d{2,5}[A-Z]?', name)
    return m.group(0) if m else name


def _infer_asset_type(name: str) -> str:
    """Infer equipment type from object name for HeatOps matching."""
    n = name.lower()
    if any(k in n for k in ("ferment", "reactor", "tank", "vessel", "digest")):
        return "VESSEL"
    if "valve" in n:
        return "CONTROL_VALVE" if "control" in n else "VALVE"
    if "pump" in n:
        return "PUMP"
    if any(k in n for k in ("pipe", "duct")):
        return "PIPE"
    if any(k in n for k in ("heat", "exchanger", "cooler", "heater")):
        return "HEAT_EXCHANGER"
    if any(k in n for k in ("motor", "engine", "turbine", "generator")):
        return "MACHINE"
    if any(k in n for k in ("sensor", "gauge", "meter", "instrument")):
        return "INSTRUMENT"
    return "EQUIPMENT"


def _infer_color_3d(name: str) -> dict:
    """Infer object color from name for 3D viewer."""
    n = name.lower()
    if any(k in n for k in ("floor", "ground", "slab")):
        return {"r": 0.35, "g": 0.36, "b": 0.38}
    if "platform" in n or "checker" in n:
        return {"r": 0.45, "g": 0.47, "b": 0.50}
    if "dome" in n:
        return {"r": 0.78, "g": 0.80, "b": 0.83}
    if any(k in n for k in ("body", "tank", "vessel")):
        return {"r": 0.75, "g": 0.77, "b": 0.80}
    if any(k in n for k in ("col_", "column", "beam", "brace", "stanchion")):
        return {"r": 0.55, "g": 0.55, "b": 0.58}
    if any(k in n for k in ("pipe", "tube")):
        return {"r": 0.50, "g": 0.52, "b": 0.55}
    if "valve" in n:
        return {"r": 0.60, "g": 0.30, "b": 0.30}
    if "pump" in n:
        return {"r": 0.30, "g": 0.45, "b": 0.60}
    if any(k in n for k in ("light", "lamp")):
        return {"r": 1.00, "g": 0.95, "b": 0.60}
    if "wall" in n:
        return {"r": 0.85, "g": 0.85, "b": 0.82}
    if any(k in n for k in ("jacket", "cooling")):
        return {"r": 0.30, "g": 0.50, "b": 0.70}
    if any(k in n for k in ("agitator", "motor")):
        return {"r": 0.40, "g": 0.42, "b": 0.45}
    if any(k in n for k in ("door", "window", "panel")):
        return {"r": 0.40, "g": 0.55, "b": 0.70}
    if any(k in n for k in ("rail", "guard", "handrail", "ladder", "stair")):
        return {"r": 0.65, "g": 0.65, "b": 0.60}
    return {"r": 0.60, "g": 0.60, "b": 0.65}


def _parse_vec3(v, default_x=0.0, default_y=0.0, default_z=0.0) -> dict:
    """Parse a vec3 from either list [x,y,z] or dict {x,y,z} format."""
    if isinstance(v, (list, tuple)) and len(v) >= 3:
        return {"x": float(v[0] or default_x), "y": float(v[1] or default_y), "z": float(v[2] or default_z)}
    if isinstance(v, dict):
        return {
            "x": float(v.get("x", default_x) or default_x),
            "y": float(v.get("y", default_y) or default_y),
            "z": float(v.get("z", default_z) or default_z),
        }
    return {"x": default_x, "y": default_y, "z": default_z}


def _node_to_3d_obj(
    node: dict,
    parent_world_pos: dict,
) -> Optional[dict]:
    """Convert a single MCP hierarchy node into a renderable 3D object dict.

    Returns None if the node should not be rendered (no MeshRenderer/Light).
    """
    name = node.get("name") or ""
    if not name:
        return None

    transform = node.get("transform", {})
    local_pos = _parse_vec3(transform.get("position", [0, 0, 0]))
    rotation = _parse_vec3(
        transform.get("rotation") or transform.get("localEulerAngles", [0, 0, 0])
    )
    scale = _parse_vec3(
        transform.get("scale") or transform.get("localScale", [1, 1, 1]),
        1.0, 1.0, 1.0,
    )

    world_pos = {
        "x": parent_world_pos["x"] + local_pos["x"],
        "y": parent_world_pos["y"] + local_pos["y"],
        "z": parent_world_pos["z"] + local_pos["z"],
    }

    # Determine if renderable from component types
    comp_types = node.get("componentTypes") or []
    has_mesh = "MeshRenderer" in comp_types
    has_light = "Light" in comp_types

    if has_light:
        primitive = "Light"
    elif has_mesh:
        primitive = _infer_primitive_3d(name)
    else:
        primitive = None  # container node — not renderable

    obj_dict = None
    if primitive:
        obj_dict = {
            "name": name,
            "path": node.get("path", name),
            "tag": _extract_asset_tag(name),
            "type": _infer_asset_type(name),
            "position": world_pos,
            "rotation": rotation,
            "scale": scale,
            "primitive": primitive,
            "color": _scene_color_overrides.get(name) or _infer_color_3d(name),
        }

    return obj_dict, world_pos


async def _fetch_children_recursive(
    parent_id: int,
    parent_world_pos: dict,
    result: list,
    max_depth: int = 4,
) -> None:
    """Recursively fetch children of a node via MCP and flatten into result list."""
    if max_depth <= 0:
        return

    # Fetch all children of this parent (paginated)
    all_items: list[dict] = []
    cursor = 0
    while True:
        resp = await asyncio.to_thread(
            mcp_client.tool_call, "manage_scene", {
                "action": "get_hierarchy",
                "include_transform": True,
                "parent": parent_id,
                "page_size": 500,
                "cursor": cursor,
            }
        )
        data = _extract_mcp_data(resp)
        if not data:
            break
        items = data.get("items") or []
        all_items.extend(items)
        next_cursor = data.get("next_cursor")
        if next_cursor is None:
            break
        cursor = next_cursor

    # Process each child
    children_with_kids: list[tuple[int, dict]] = []
    for item in all_items:
        pair = _node_to_3d_obj(item, parent_world_pos)
        if pair is None:
            continue
        obj_dict, world_pos = pair
        if obj_dict is not None:
            result.append(obj_dict)

        child_count = item.get("childCount", 0)
        if child_count > 0:
            children_with_kids.append((item["instanceID"], world_pos))

    # Recurse into children that have sub-children (in parallel)
    if children_with_kids:
        tasks = [
            _fetch_children_recursive(cid, wpos, result, max_depth - 1)
            for cid, wpos in children_with_kids
        ]
        await asyncio.gather(*tasks)


def _extract_mcp_data(resp: Any) -> Optional[dict]:
    """Extract 'data' from MCP tool_call response."""
    if not isinstance(resp, dict):
        return None
    # Direct structured content
    if "data" in resp:
        return resp["data"]
    # Wrapped in result.content
    result = resp.get("result", resp)
    if not isinstance(result, dict):
        return None
    content = result.get("content", [])
    for item in content:
        if item.get("type") == "text":
            try:
                parsed = json.loads(item["text"])
                return parsed.get("data")
            except (json.JSONDecodeError, TypeError):
                pass
    return None


def _calc_bounds_and_camera(objects: list[dict]) -> tuple[dict, Optional[dict]]:
    """Calculate bounding box and suggested camera position from object list."""
    if not objects:
        return {}, None
    min_x = min(o["position"]["x"] for o in objects)
    min_y = min(o["position"]["y"] for o in objects)
    min_z = min(o["position"]["z"] for o in objects)
    max_x = max(o["position"]["x"] for o in objects)
    max_y = max(o["position"]["y"] for o in objects)
    max_z = max(o["position"]["z"] for o in objects)
    cx, cy, cz = (min_x + max_x) / 2, (min_y + max_y) / 2, (min_z + max_z) / 2
    span = max(max_x - min_x, max_y - min_y, max_z - min_z, 1.0)
    dist = span * 1.2
    return (
        {"min": {"x": min_x, "y": min_y, "z": min_z},
         "max": {"x": max_x, "y": max_y, "z": max_z}},
        {"position": [cx + dist * 0.6, cy + dist * 0.5, cz + dist * 0.6],
         "target": [cx, cy, cz]},
    )


@app.get("/api/scene/3d-data")
async def get_scene_3d_data(refresh: bool = False):
    """Get scene hierarchy with transforms for Three.js 3D viewer.

    Uses a memory cache to avoid expensive MCP calls on every request.
    Pass ?refresh=true to force a fresh fetch from Unity.
    """
    global _3d_data_cache

    if _3d_data_cache and not refresh:
        # Apply latest color overrides to cached objects
        for obj in _3d_data_cache.get("objects", []):
            override = _scene_color_overrides.get(obj["name"])
            if override:
                obj["color"] = override
        return _3d_data_cache

    try:
        # Step 1: Fetch root items WITHOUT include_transform (fast, ~0.4s)
        resp = await asyncio.to_thread(
            mcp_client.tool_call, "manage_scene", {
                "action": "get_hierarchy",
                "max_depth": 1,
            }
        )
        data = _extract_mcp_data(resp)
        if not data or not data.get("items"):
            # Fallback: use cached scene context
            return _build_3d_from_scene_cache()

        # Step 2: For each root with children, recursively fetch WITH transforms
        origin = {"x": 0.0, "y": 0.0, "z": 0.0}
        objects: list[dict] = []
        fetch_tasks: list = []

        for item in data["items"]:
            pair = _node_to_3d_obj(item, origin)
            if pair is not None:
                obj_dict, world_pos = pair
                if obj_dict is not None:
                    objects.append(obj_dict)
            else:
                world_pos = origin

            if item.get("childCount", 0) > 0:
                fetch_tasks.append(
                    _fetch_children_recursive(
                        item["instanceID"], world_pos, objects, max_depth=4
                    )
                )

        if fetch_tasks:
            await asyncio.gather(*fetch_tasks)

        bounds, camera_suggestion = _calc_bounds_and_camera(objects)

        result = {
            "objects": objects,
            "bounds": bounds,
            "camera_suggestion": camera_suggestion,
        }
        _3d_data_cache = result
        logger.info("[3D-data] Fetched and cached %d objects", len(objects))
        return result

    except Exception as e:
        logger.warning("3D data live fetch failed (%s), using cache fallback", e)
        return _build_3d_from_scene_cache()


def _build_3d_from_scene_cache() -> dict:
    """Build 3D viewer data from the scene_cache (no MCP transform calls)."""
    ctx = scene_cache.get_context()
    objects = []
    for obj_data in (ctx.get("objects") or {}).values():
        name = obj_data.get("name", "")
        prim = _infer_primitive_3d(name)
        if prim == "Empty":
            continue
        objects.append({
            "name": name,
            "path": obj_data.get("path", name),
            "tag": _extract_asset_tag(name),
            "type": _infer_asset_type(name),
            "position": obj_data.get("position", {"x": 0, "y": 0, "z": 0}),
            "rotation": {"x": 0, "y": 0, "z": 0},
            "scale": obj_data.get("scale", {"x": 1, "y": 1, "z": 1}),
            "primitive": prim,
            "color": _scene_color_overrides.get(name) or _infer_color_3d(name),
        })
    bounds, cam = _calc_bounds_and_camera(objects)
    return {"objects": objects, "bounds": bounds, "camera_suggestion": cam}


# ── Digital Twin ─────────────────────────────────────────────

@app.post("/api/twin/sync")
async def twin_sync():
    """Manually trigger digital twin sync."""
    try:
        from .fermentation_bridge import FermentationBridge
        bridge = FermentationBridge(mcp_client)
        return {"status": "sync_triggered", "bridge": bridge.get_twin_status()}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/twin/status")
async def twin_status():
    """Get digital twin bridge status."""
    try:
        from .fermentation_bridge import FermentationBridge
        bridge = FermentationBridge(mcp_client)
        return bridge.get_twin_status()
    except Exception as e:
        return {"running": False, "error": str(e)}


# ── WebSocket (Twin) ────────────────────────────────────────

@app.websocket("/ws/twin")
async def twin_websocket(ws: WebSocket):
    """WebSocket for real-time digital twin sensor streaming."""
    await ws.accept()
    twin_ws_connections.append(ws)
    logger.info("Twin WS connected (total: %d)", len(twin_ws_connections))
    try:
        while True:
            data = await ws.receive_text()
            if data == "ping":
                await ws.send_text(json.dumps({"event": "pong"}))
    except WebSocketDisconnect:
        if ws in twin_ws_connections:
            twin_ws_connections.remove(ws)
        logger.info("Twin WS disconnected (total: %d)", len(twin_ws_connections))


# ── WebSocket (Main) ────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    """WebSocket for real-time job updates."""
    await ws.accept()
    ws_connections.append(ws)
    logger.info("WS connected (total: %d)", len(ws_connections))
    try:
        while True:
            data = await ws.receive_text()
            if data == "ping":
                await ws.send_text(json.dumps({"event": "pong"}))
    except WebSocketDisconnect:
        if ws in ws_connections:
            ws_connections.remove(ws)
        logger.info("WS disconnected (total: %d)", len(ws_connections))


# ── Startup ──────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    """Initialize MCP connection on startup."""
    logger.info("Vibe3D Accelerator v2.0 starting...")
    logger.info("MCP Server: %s", config.MCP_SERVER_URL)
    logger.info("Unity Project: %s", config.UNITY_PROJECT_PATH)
    logger.info("LLM available: %s", bool(config.ANTHROPIC_API_KEY))
    try:
        if await asyncio.to_thread(mcp_client.initialize):
            logger.info("MCP connected (session: %s)", mcp_client.session_id)
            # Pre-populate scene cache so commands have context immediately
            await _refresh_scene_and_3d_cache()
            ctx = scene_cache.get_context()
            logger.info("Scene cache loaded: %d objects", len(ctx.get("objects", {})))
        else:
            logger.warning("MCP connection failed — start Unity and MCP server first")
    except Exception as e:
        logger.warning("MCP not available at startup: %s", e)
