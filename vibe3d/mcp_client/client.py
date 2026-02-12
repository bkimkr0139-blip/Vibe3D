"""Unity MCP Client — HTTP+SSE transport for mcp-for-unity server."""

import json
import logging
import urllib.request
import urllib.error
from typing import Any, Optional

logger = logging.getLogger(__name__)


class UnityMCPClient:
    """Communicates with Unity via MCP-FOR-UNITY server (HTTP+SSE)."""

    def __init__(self, url: str = "http://localhost:8080/mcp", timeout: int = 60):
        self.url = url
        self.timeout = timeout
        self.session_id: Optional[str] = None
        self.req_id = 0
        self._initialized = False

    # ── Low-level transport ──────────────────────────────────

    def _request(self, method: str, params: Optional[dict] = None) -> list[dict]:
        import time as _time
        self.req_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self.req_id,
            "method": method,
            "params": params or {},
        }
        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream, application/json",
        }
        if self.session_id:
            headers["mcp-session-id"] = self.session_id

        # Log request details
        tool_name = ""
        if method == "tools/call" and params:
            tool_name = params.get("name", "")
            args_summary = str(params.get("arguments", {}))[:200]
            logger.info("[MCP→] REQ #%d: %s(%s) %s", self.req_id, method, tool_name, args_summary)
        else:
            logger.debug("[MCP→] REQ #%d: %s", self.req_id, method)

        t0 = _time.time()
        req = urllib.request.Request(self.url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                sid = resp.headers.get("mcp-session-id")
                if sid:
                    self.session_id = sid
                raw = resp.read().decode("utf-8")
                elapsed = _time.time() - t0
                results = []
                for line in raw.split("\n"):
                    line = line.strip()
                    if line.startswith("data: "):
                        try:
                            parsed = json.loads(line[6:])
                            if parsed is not None:  # MCP can send `data: null` for heartbeats
                                results.append(parsed)
                        except json.JSONDecodeError:
                            pass

                # Log response summary
                if tool_name:
                    logger.info("[MCP←] RES #%d: %s — %d result(s), %.3fs",
                                self.req_id, tool_name, len(results), elapsed)
                else:
                    logger.debug("[MCP←] RES #%d: %s — %d result(s), %.3fs",
                                 self.req_id, method, len(results), elapsed)
                return results
        except urllib.error.URLError as e:
            elapsed = _time.time() - t0
            logger.error("[MCP✗] REQ #%d FAILED after %.3fs: %s", self.req_id, elapsed, e)
            raise ConnectionError(f"Cannot reach MCP server at {self.url}: {e}") from e

    def _notify(self, method: str, params: Optional[dict] = None) -> None:
        payload = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream, application/json",
        }
        if self.session_id:
            headers["mcp-session-id"] = self.session_id
        req = urllib.request.Request(self.url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                sid = resp.headers.get("mcp-session-id")
                if sid:
                    self.session_id = sid
                resp.read()
        except urllib.error.URLError:
            pass  # notifications are fire-and-forget

    # ── Session management ───────────────────────────────────

    def initialize(self) -> bool:
        """Initialize MCP session. Must be called before any tool calls."""
        try:
            results = self._request("initialize", {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "vibe3d-accelerator", "version": "1.0.0"},
            })
            self._notify("notifications/initialized")
            self._initialized = True
            logger.info("MCP session initialized (session_id=%s)", self.session_id)
            return True
        except ConnectionError:
            self._initialized = False
            return False

    @property
    def is_connected(self) -> bool:
        return self._initialized and self.session_id is not None

    def ping(self) -> bool:
        """Check if Unity MCP server is responsive."""
        try:
            results = self._request("ping")
            return True
        except (ConnectionError, Exception):
            return False

    # ── Tool calling ─────────────────────────────────────────

    def tool_call(self, name: str, arguments: dict) -> dict:
        """Call a single MCP tool and return the result."""
        if not self._initialized:
            self.initialize()
        try:
            results = self._request("tools/call", {"name": name, "arguments": arguments})
        except ConnectionError as e:
            if "404" in str(e):
                # Session expired (MCP server restarted) — re-initialize
                logger.warning("MCP session expired, re-initializing...")
                self.session_id = None
                self._initialized = False
                self.initialize()
                results = self._request("tools/call", {"name": name, "arguments": arguments})
            else:
                raise
        # Return last valid dict result; skip non-dict entries
        for r in reversed(results):
            if isinstance(r, dict):
                return r
        return {"error": "No response from MCP server"}

    def list_tools(self) -> list[dict]:
        """List all available MCP tools."""
        if not self._initialized:
            self.initialize()
        results = self._request("tools/list")
        tools = []
        for r in results:
            if "result" in r and "tools" in r["result"]:
                tools = r["result"]["tools"]
                break
        return tools

    # ── High-level Unity operations ──────────────────────────

    def create_object(
        self,
        name: str,
        primitive_type: str = "Cube",
        parent: str = "",
        position: Optional[dict] = None,
        rotation: Optional[dict] = None,
        scale: Optional[dict] = None,
    ) -> dict:
        """Create a GameObject in Unity."""
        args: dict[str, Any] = {
            "action": "create",
            "name": name,
            "primitive_type": primitive_type,
        }
        if parent:
            args["parent"] = parent
        if position:
            args["position"] = position
        if rotation:
            args["rotation"] = rotation
        if scale:
            args["scale"] = scale
        return self.tool_call("manage_gameobject", args)

    def modify_object(
        self,
        target: str,
        search_method: str = "by_name",
        position: Optional[dict] = None,
        rotation: Optional[dict] = None,
        scale: Optional[dict] = None,
    ) -> dict:
        """Modify an existing GameObject."""
        args: dict[str, Any] = {
            "action": "modify",
            "target": target,
            "search_method": search_method,
        }
        if position:
            args["position"] = position
        if rotation:
            args["rotation"] = rotation
        if scale:
            args["scale"] = scale
        return self.tool_call("manage_gameobject", args)

    def delete_object(self, target: str, search_method: str = "by_name") -> dict:
        """Delete a GameObject."""
        return self.tool_call("manage_gameobject", {
            "action": "delete",
            "target": target,
            "search_method": search_method,
        })

    def set_color(
        self,
        target: str,
        r: float, g: float, b: float, a: float = 1.0,
        search_method: str = "by_name",
    ) -> dict:
        """Set renderer color on an object."""
        return self.tool_call("manage_material", {
            "action": "set_renderer_color",
            "target": target,
            "search_method": search_method,
            "color": {"r": r, "g": g, "b": b, "a": a},
        })

    def batch_execute(self, commands: list[dict]) -> dict:
        """Execute up to 25 commands in a single batch."""
        if len(commands) > 25:
            raise ValueError("batch_execute supports max 25 commands")
        return self.tool_call("batch_execute", {"commands": commands})

    def get_hierarchy(self, parent: str = "", max_depth: int = 3) -> dict:
        """Get scene hierarchy."""
        args: dict[str, Any] = {"action": "get_hierarchy", "max_depth": max_depth}
        if parent:
            args["parent"] = parent
        return self.tool_call("manage_scene", args)

    def screenshot(self, filename: str = "vibe3d_screenshot", super_size: int = 2) -> dict:
        """Take a screenshot of the current view."""
        return self.tool_call("manage_scene", {
            "action": "screenshot",
            "screenshot_file_name": filename,
            "screenshot_super_size": super_size,
        })

    def save_scene(self) -> dict:
        """Save the current scene."""
        return self.tool_call("manage_scene", {"action": "save"})

    def find_objects(self, search_term: str, search_method: str = "by_name") -> dict:
        """Find GameObjects in the scene."""
        return self.tool_call("find_gameobjects", {
            "search_term": search_term,
            "search_method": search_method,
        })

    def read_console(self, count: int = 20, types: Optional[list] = None) -> dict:
        """Read Unity console logs."""
        args: dict[str, Any] = {"count": count}
        if types:
            args["types"] = types
        return self.tool_call("read_console", args)

    def execute_menu(self, menu_path: str) -> dict:
        """Execute a Unity Editor menu item."""
        return self.tool_call("execute_menu_item", {"menu_path": menu_path})
