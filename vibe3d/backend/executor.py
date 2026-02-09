"""Plan executor — runs validated MCP commands against Unity.

Enhanced with:
- Per-action progress callbacks for real-time UI updates
- Undo plan generation (reverse of executed actions)
- Error analysis integration for smart recovery suggestions
"""

import logging
import shutil
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional

from ..mcp_client import UnityMCPClient
from . import config
from .plan_validator import plan_to_mcp_commands

logger = logging.getLogger(__name__)

# Type for progress callback: (job_id, action_idx, total, action_type, status)
ProgressCallback = Optional[Callable[[str, int, int, str, str], None]]


class JobStatus(str, Enum):
    PENDING = "pending"
    VALIDATING = "validating"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"


@dataclass
class JobResult:
    job_id: str
    status: JobStatus
    command: str
    plan: Optional[dict] = None
    method: str = ""
    total_actions: int = 0
    success_count: int = 0
    fail_count: int = 0
    results: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    started_at: float = 0.0
    completed_at: float = 0.0
    duration_s: float = 0.0
    undo_plan: Optional[dict] = None
    error_analysis: Optional[dict] = None


def _generate_undo_plan(plan: dict, original_colors: dict | None = None) -> dict:
    """Generate an undo plan that reverses the actions of the original plan.

    - create_primitive → delete_object
    - create_empty → delete_object
    - create_light → delete_object
    - apply_material → apply_material with original color (if snapshot provided)
    - modify_object → (not reversible without snapshot)
    - delete_object → (not reversible)
    - duplicate_object → delete (the copy)

    Args:
        plan: The original plan that was executed.
        original_colors: Optional dict mapping object name → {r, g, b, a} before execution.
    """
    original_colors = original_colors or {}
    undo_actions = []
    for action in reversed(plan.get("actions", [])):
        action_type = action.get("type", "")
        if action_type in ("create_primitive", "create_empty", "create_light"):
            name = action.get("name", "")
            if name:
                undo_actions.append({
                    "type": "delete_object",
                    "target": name,
                    "search_method": "by_name",
                })
        elif action_type == "duplicate_object":
            new_name = action.get("new_name", "")
            if new_name:
                undo_actions.append({
                    "type": "delete_object",
                    "target": new_name,
                    "search_method": "by_name",
                })
        elif action_type == "apply_material":
            target = action.get("target", "")
            if target and target in original_colors:
                undo_actions.append({
                    "type": "apply_material",
                    "target": target,
                    "color": original_colors[target],
                })

    if not undo_actions:
        return {}

    return {
        "project": plan.get("project", "My project"),
        "scene": plan.get("scene", "bio-plants"),
        "description": f"Undo: {plan.get('description', '')}",
        "actions": undo_actions,
    }


class PlanExecutor:
    """Executes validated plans via MCP batch commands."""

    MAX_BATCH = 25  # MCP batch limit

    def __init__(self, mcp_client: UnityMCPClient):
        self.mcp = mcp_client
        self._undo_store: dict[str, dict] = {}  # job_id → undo_plan

    def get_undo_plan(self, job_id: str) -> dict | None:
        """Get the undo plan for a completed job."""
        return self._undo_store.get(job_id)

    def execute_undo(self, job_id: str) -> JobResult | None:
        """Execute the undo plan for a previous job."""
        undo_plan = self._undo_store.get(job_id)
        if not undo_plan:
            return None
        undo_job_id = f"undo-{job_id}"
        return self.execute(undo_job_id, f"(undo {job_id})", undo_plan, "undo")

    def execute(
        self,
        job_id: str,
        command: str,
        plan: dict,
        method: str,
        progress_callback: ProgressCallback = None,
        original_colors: dict | None = None,
    ) -> JobResult:
        """Execute a validated plan and return results."""
        result = JobResult(
            job_id=job_id,
            status=JobStatus.EXECUTING,
            command=command,
            plan=plan,
            method=method,
            started_at=time.time(),
        )

        # Pre-step: handle file imports (copy external files into Unity project)
        self._handle_import_actions(plan, result)

        # Convert plan actions to MCP commands
        logger.info("[Executor] Converting %d plan actions to MCP commands...", len(plan.get("actions", [])))
        mcp_commands = plan_to_mcp_commands(plan)
        result.total_actions = len(mcp_commands)
        logger.info("[Executor] Converted to %d MCP commands", len(mcp_commands))

        if not mcp_commands:
            logger.info("[Executor] No MCP commands to execute")
            result.status = JobStatus.COMPLETED
            result.completed_at = time.time()
            result.duration_s = result.completed_at - result.started_at
            return result

        # Log each MCP command
        for i, cmd in enumerate(mcp_commands):
            tool = cmd.get("tool", "?")
            params_summary = {k: v for k, v in cmd.get("params", {}).items() if k != "commands"}
            logger.info("[Executor] CMD[%d]: tool=%s params=%s", i, tool, str(params_summary)[:150])

        # Split commands into dependency-aware phases:
        # Phase 1: create commands (manage_gameobject action=create)
        # Phase 2: everything else (materials, component modifications, etc.)
        # This prevents batch timing issues where modify commands reference
        # objects that were just created in the same batch.
        phases = self._split_by_dependency(mcp_commands)
        total_commands = sum(len(p) for p in phases)

        # Execute phases sequentially, each phase split into MAX_BATCH chunks
        all_success = 0
        all_fail = 0
        batch_num = 0
        # Count total batches across all phases
        total_batches = sum(
            (len(phase) + self.MAX_BATCH - 1) // self.MAX_BATCH
            for phase in phases
        )
        global_idx = 0  # tracks position across all commands

        for phase_idx, phase_commands in enumerate(phases):
            for chunk_start in range(0, len(phase_commands), self.MAX_BATCH):
                batch = phase_commands[chunk_start : chunk_start + self.MAX_BATCH]
                batch_num += 1

                logger.info("[Executor] === Batch %d/%d (phase %d): %d commands → MCP ===",
                            batch_num, total_batches, phase_idx + 1, len(batch))

                try:
                    # Notify progress before batch
                    if progress_callback:
                        for ci, cmd in enumerate(batch):
                            action_idx = global_idx + ci
                            tool_name = cmd.get("tool", cmd.get("params", {}).get("action", "unknown"))
                            try:
                                progress_callback(job_id, action_idx, total_commands, tool_name, "executing")
                            except Exception:
                                pass

                    t_batch = time.time()
                    resp = self.mcp.batch_execute(batch)
                    batch_elapsed = time.time() - t_batch
                    batch_result = self._parse_batch_result(resp)
                    all_success += batch_result["success"]
                    all_fail += batch_result["fail"]
                    result.results.append({
                        "batch": batch_num,
                        "phase": phase_idx + 1,
                        "commands": len(batch),
                        "success": batch_result["success"],
                        "fail": batch_result["fail"],
                        "details": batch_result.get("details", []),
                    })

                    # Log per-action results
                    for ci, detail in enumerate(batch_result.get("details", [])):
                        action_idx = global_idx + ci
                        status_str = "OK" if detail.get("succeeded") else "FAIL"
                        logger.info("[Executor] Action[%d]: %s → %s", action_idx, detail.get("tool", "?"), status_str)

                    # Notify progress after batch
                    if progress_callback:
                        for ci, detail in enumerate(batch_result.get("details", [])):
                            action_idx = global_idx + ci
                            status = "completed" if detail.get("succeeded") else "failed"
                            try:
                                progress_callback(job_id, action_idx, total_commands, detail.get("tool", ""), status)
                            except Exception:
                                pass

                    logger.info(
                        "[Executor] Batch %d: %d/%d success (%.3fs)",
                        batch_num, batch_result["success"], len(batch), batch_elapsed,
                    )

                    if batch_result.get("error"):
                        logger.warning("[Executor] Batch %d error: %s", batch_num, batch_result["error"])

                except Exception as e:
                    all_fail += len(batch)
                    result.errors.append(f"Batch {batch_num} failed: {str(e)}")
                    logger.error("[Executor] Batch %d execution failed: %s", batch_num, e)

                global_idx += len(batch)

        result.success_count = all_success
        result.fail_count = all_fail
        result.completed_at = time.time()
        result.duration_s = result.completed_at - result.started_at

        if all_fail == 0:
            result.status = JobStatus.COMPLETED
        elif all_success == 0:
            result.status = JobStatus.FAILED
        else:
            result.status = JobStatus.PARTIAL

        logger.info("[Executor] === Job %s %s: %d/%d success, %.3fs ===",
                     job_id, result.status.value, all_success, result.total_actions, result.duration_s)

        # Generate and store undo plan
        if result.success_count > 0 and method != "undo":
            undo = _generate_undo_plan(plan, original_colors)
            if undo:
                result.undo_plan = undo
                self._undo_store[job_id] = undo
                # Keep max 50 undo plans
                if len(self._undo_store) > 50:
                    oldest = next(iter(self._undo_store))
                    del self._undo_store[oldest]

        # Run error analysis on failures
        if result.fail_count > 0 and result.errors:
            try:
                from .error_analyzer import analyze_error
                analysis = analyze_error(
                    "; ".join(result.errors),
                    plan,
                    [],  # scene objects populated by caller
                )
                result.error_analysis = {
                    "category": analysis.category.value,
                    "root_cause": analysis.root_cause,
                    "suggestions": [
                        {"label": s["label"], "fix_plan": s.get("fix_plan")}
                        for s in analysis.suggestions
                    ],
                    "auto_fixable": analysis.auto_fixable,
                }
            except Exception as e:
                logger.debug("Error analysis skipped: %s", e)

        return result

    @staticmethod
    def _split_by_dependency(commands: list[dict]) -> list[list[dict]]:
        """Split commands into dependency-aware phases (list of batches).

        Phase 1: create/delete commands (manage_gameobject action=create/delete,
                  manage_scene, manage_editor)
        Phase 2: modifier commands (materials, components, etc.) that reference
                  objects created in phase 1.

        Returns a list of batches (list of lists). Each batch will be sent
        as a separate batch_execute call to avoid the MCP timing issue where
        modify commands fail because the target object hasn't been registered
        yet within the same batch_execute call.
        """
        creates: list[dict] = []
        modifiers: list[dict] = []

        for cmd in commands:
            tool = cmd.get("tool", "")
            params = cmd.get("params", {})
            action = params.get("action", "")

            if tool == "manage_gameobject" and action in ("create", "delete"):
                creates.append(cmd)
            elif tool == "manage_scene":
                creates.append(cmd)
            elif tool == "manage_editor":
                creates.append(cmd)
            else:
                modifiers.append(cmd)

        # If there are no modifiers or no creates, single phase
        if not modifiers or not creates:
            return [commands]

        logger.info("[Executor] Dependency split: %d creates + %d modifiers → 2 phases",
                    len(creates), len(modifiers))
        return [creates, modifiers]

    def _handle_import_actions(self, plan: dict, result: JobResult) -> None:
        """Copy external files into the Unity project for import_asset actions."""
        unity_project = Path(config.UNITY_PROJECT_PATH)
        for action in plan.get("actions", []):
            if action.get("type") != "import_asset":
                continue
            source = action.get("source_path", "")
            dest_folder = action.get("destination", "Assets/Imports")
            filename = action.get("filename", "")
            if not source:
                result.errors.append("import_asset: source_path is empty")
                continue
            src_path = Path(source)
            if not src_path.exists():
                result.errors.append(f"import_asset: source not found: {source}")
                continue
            # Build destination inside Unity project
            dest_dir = unity_project / dest_folder
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest_file = dest_dir / (filename or src_path.name)
            try:
                shutil.copy2(str(src_path), str(dest_file))
                logger.info("Imported file: %s → %s", src_path, dest_file)
            except Exception as e:
                result.errors.append(f"import_asset copy failed: {e}")

    def _parse_batch_result(self, resp: Any) -> dict[str, Any]:
        """Parse MCP batch_execute response.

        Response structure (from SSE):
        {
            "jsonrpc": "2.0", "id": N,
            "result": {
                "content": [{"type": "text", "text": "{\"success\":true,\"data\":{\"results\":[...],...}}"}]
            }
        }
        """
        import json as _json

        if not resp or not isinstance(resp, dict):
            logger.warning("_parse_batch_result: invalid response type=%s", type(resp).__name__)
            return {"success": 0, "fail": 0, "details": []}

        # Check for error response from MCP
        if "error" in resp and "result" not in resp:
            err_msg = resp.get("error", "")
            if isinstance(err_msg, dict):
                err_msg = err_msg.get("message", str(err_msg))
            logger.warning("_parse_batch_result: MCP error: %s", err_msg)
            return {"success": 0, "fail": 0, "details": [], "error": str(err_msg)}

        # Navigate SSE response: resp is the outermost jsonrpc envelope
        result_data = resp.get("result", resp)
        if not isinstance(result_data, dict):
            return {"success": 0, "fail": 0, "details": []}
        content = result_data.get("content", [])

        for item in content:
            if item.get("type") == "text":
                try:
                    parsed = _json.loads(item["text"])
                    data = parsed.get("data", parsed)
                    results_list = data.get("results", [])

                    success = data.get("callSuccessCount", 0)
                    fail = data.get("callFailureCount", 0)

                    # If callSuccessCount not present, count manually
                    if success == 0 and fail == 0 and results_list:
                        success = sum(1 for r in results_list if r.get("callSucceeded", False))
                        fail = len(results_list) - success

                    details = []
                    for r in results_list:
                        details.append({
                            "succeeded": r.get("callSucceeded", False),
                            "tool": r.get("tool", r.get("toolName", "")),
                        })
                    return {"success": success, "fail": fail, "details": details}
                except (_json.JSONDecodeError, KeyError, TypeError):
                    pass

        # Fallback: treat entire response as having unknown results
        return {"success": 0, "fail": 0, "details": []}
