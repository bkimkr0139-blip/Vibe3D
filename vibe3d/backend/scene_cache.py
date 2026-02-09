"""Scene context cache for the Vibe3D Unity Accelerator.

Caches Unity scene hierarchy and object transforms so that plan_generator
can perform spatial reasoning (e.g. "옆에", "위에") without querying MCP
on every request.  The cache is TTL-based and invalidated automatically
after *DEFAULT_PARAMS["ttl_seconds"]*.

Usage::

    from vibe3d.backend.scene_cache import SceneCache
    cache = SceneCache()          # singleton
    cache.refresh(mcp_client)     # pull hierarchy from Unity
    ctx = cache.get_context()     # dict ready for plan_generator
"""

import json
import logging
import math
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── Default parameters ───────────────────────────────────────

DEFAULT_PARAMS = {
    "ttl_seconds": 5.0,
    "max_depth": 3,
    "spatial_offset": 2.0,       # metres — default gap for "옆에", "앞에", etc.
    "y_stack_gap": 0.05,         # metres — tiny gap when stacking "위에"
}

# ── Spatial reference presets (Korean → axis offsets) ────────

_SPATIAL_REFS: dict[str, dict[str, float]] = {
    # Korean
    "옆에":  {"x": 1.0, "y": 0.0, "z": 0.0},
    "위에":  {"x": 0.0, "y": 1.0, "z": 0.0},
    "아래에": {"x": 0.0, "y": -1.0, "z": 0.0},
    "앞에":  {"x": 0.0, "y": 0.0, "z": -1.0},
    "뒤에":  {"x": 0.0, "y": 0.0, "z": 1.0},
    "가운데": {"x": 0.0, "y": 0.0, "z": 0.0},  # centroid — handled specially
    # English aliases
    "beside": {"x": 1.0, "y": 0.0, "z": 0.0},
    "above":  {"x": 0.0, "y": 1.0, "z": 0.0},
    "below":  {"x": 0.0, "y": -1.0, "z": 0.0},
    "front":  {"x": 0.0, "y": 0.0, "z": -1.0},
    "behind": {"x": 0.0, "y": 0.0, "z": 1.0},
    "center": {"x": 0.0, "y": 0.0, "z": 0.0},
}


# ── Helper types ─────────────────────────────────────────────

def _vec(x: float = 0.0, y: float = 0.0, z: float = 0.0) -> dict[str, float]:
    return {"x": x, "y": y, "z": z}


def _vec_add(a: dict[str, float], b: dict[str, float]) -> dict[str, float]:
    return {"x": a["x"] + b["x"], "y": a["y"] + b["y"], "z": a["z"] + b["z"]}


def _vec_scale(v: dict[str, float], s: float) -> dict[str, float]:
    return {"x": v["x"] * s, "y": v["y"] * s, "z": v["z"] * s}


def _distance(a: dict[str, float], b: dict[str, float]) -> float:
    dx = a["x"] - b["x"]
    dy = a["y"] - b["y"]
    dz = a["z"] - b["z"]
    return math.sqrt(dx * dx + dy * dy + dz * dz)


# ── Cached object record ────────────────────────────────────

class CachedObject:
    """Lightweight snapshot of a single Unity GameObject."""

    __slots__ = ("name", "path", "position", "scale", "children")

    def __init__(
        self,
        name: str,
        path: str = "",
        position: Optional[dict[str, float]] = None,
        scale: Optional[dict[str, float]] = None,
    ):
        self.name: str = name
        self.path: str = path
        self.position: dict[str, float] = position or _vec()
        self.scale: dict[str, float] = scale or _vec(1, 1, 1)
        self.children: list[str] = []

    def half_extents(self) -> dict[str, float]:
        """Return half the bounding size (scale / 2) for AABB estimation."""
        return _vec_scale(self.scale, 0.5)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": self.path,
            "position": self.position,
            "scale": self.scale,
            "children": self.children,
        }


# ── Singleton scene cache ───────────────────────────────────

class SceneCache:
    """Singleton cache of the Unity scene hierarchy and transforms.

    Mirrors the singleton pattern used by ``SimulationManager``.
    """

    _instance: Optional["SceneCache"] = None

    def __new__(cls) -> "SceneCache":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._objects: dict[str, CachedObject] = {}
            cls._instance._root_names: list[str] = []
            cls._instance._last_refresh: float = 0.0
            cls._instance._ttl: float = DEFAULT_PARAMS["ttl_seconds"]
            cls._instance._scene_bounds_min: dict[str, float] = _vec()
            cls._instance._scene_bounds_max: dict[str, float] = _vec()
        return cls._instance

    # ── Public API ───────────────────────────────────────────

    def refresh(self, mcp_client: Any) -> bool:
        """Pull the scene hierarchy from Unity via *mcp_client* and rebuild the cache.

        Recursively fetches children for nodes with ``childCount > 0``
        using ``parent=instanceID`` pagination, so the cache contains
        all scene objects (not just root-level items).

        Args:
            mcp_client: A ``UnityMCPClient`` instance (or compatible duck-type)
                        that exposes ``tool_call(tool, args)`` or
                        ``get_hierarchy(parent, max_depth)``.

        Returns:
            ``True`` if the cache was successfully refreshed, ``False`` on error.
        """
        try:
            resp = mcp_client.get_hierarchy(
                parent="",
                max_depth=DEFAULT_PARAMS["max_depth"],
            )
            hierarchy_data = self._extract_hierarchy(resp)
            if hierarchy_data is None:
                logger.warning("refresh: could not extract hierarchy from MCP response")
                return False

            self._objects.clear()
            self._root_names.clear()

            children = hierarchy_data.get("children", [])
            for child in children:
                self._walk(child, parent_path="")

            # Recursively fetch children for nodes with childCount > 0
            self._fetch_children_deep(children, mcp_client, max_depth=4)

            self._root_names = [c.get("name", "") for c in children if c.get("name")]
            self._recalculate_bounds()
            self._last_refresh = time.monotonic()
            logger.info(
                "Scene cache refreshed: %d objects, bounds min=%s max=%s",
                len(self._objects),
                self._scene_bounds_min,
                self._scene_bounds_max,
            )
            return True

        except Exception as exc:
            logger.error("Scene cache refresh failed: %s", exc)
            return False

    def _fetch_children_deep(
        self, items: list[dict], mcp_client: Any, max_depth: int = 4
    ) -> None:
        """Recursively fetch children for items that have childCount > 0."""
        if max_depth <= 0:
            return
        for item in items:
            child_count = item.get("childCount", 0)
            if child_count <= 0:
                continue
            instance_id = item.get("instanceID")
            if instance_id is None:
                continue
            parent_path = item.get("path") or item.get("name", "")
            try:
                child_items = self._fetch_all_children(mcp_client, instance_id)
                for child in child_items:
                    self._walk(child, parent_path=parent_path)
                # Recurse into children that have their own children
                self._fetch_children_deep(child_items, mcp_client, max_depth - 1)
            except Exception as exc:
                logger.debug("_fetch_children_deep(%s): %s", instance_id, exc)

    @staticmethod
    def _fetch_all_children(mcp_client: Any, parent_id: int) -> list[dict]:
        """Fetch all children of a parent node via MCP pagination."""
        all_items: list[dict] = []
        cursor: Any = 0
        while True:
            resp = mcp_client.tool_call("manage_scene", {
                "action": "get_hierarchy",
                "parent": parent_id,
                "page_size": 500,
                "cursor": cursor,
            })
            data = SceneCache._extract_data(resp)
            if not data:
                break
            items = data.get("items") or []
            all_items.extend(items)
            next_cursor = data.get("next_cursor")
            if next_cursor is None:
                break
            cursor = next_cursor
        return all_items

    @staticmethod
    def _extract_data(resp: Any) -> Optional[dict]:
        """Extract ``data`` dict from MCP tool_call response."""
        if not isinstance(resp, dict):
            return None
        if "data" in resp:
            return resp["data"]
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

    def get_context(self) -> dict[str, Any]:
        """Return a serialisable dict suitable for plan_generator prompts.

        Includes the full object list, scene bounds, and staleness flag.
        """
        stale = self.is_stale
        return {
            "object_count": len(self._objects),
            "objects": {n: o.to_dict() for n, o in self._objects.items()},
            "root_names": list(self._root_names),
            "bounds": {
                "min": dict(self._scene_bounds_min),
                "max": dict(self._scene_bounds_max),
            },
            "stale": stale,
            "age_seconds": round(time.monotonic() - self._last_refresh, 2)
            if self._last_refresh > 0
            else -1,
        }

    def get_object(self, name: str) -> Optional[CachedObject]:
        """Look up a cached object by exact name.

        Args:
            name: The GameObject name (case-sensitive).

        Returns:
            The ``CachedObject`` or ``None`` if not found.
        """
        return self._objects.get(name)

    def invalidate(self) -> None:
        """Force the cache to be considered stale (does NOT clear data)."""
        self._last_refresh = 0.0
        logger.debug("Scene cache invalidated")

    # ── Mutation helpers (called after plan execution) ───────

    def add_object(
        self,
        name: str,
        position: Optional[dict[str, float]] = None,
        scale: Optional[dict[str, float]] = None,
        parent: str = "",
    ) -> None:
        """Register a newly created object in the cache without a full refresh.

        Args:
            name: GameObject name.
            position: World position ``{x, y, z}``.
            scale: Local scale ``{x, y, z}``.
            parent: Parent object name (empty string for root).
        """
        path = f"{parent}/{name}" if parent else name
        obj = CachedObject(name=name, path=path, position=position, scale=scale)
        self._objects[name] = obj

        if parent and parent in self._objects:
            self._objects[parent].children.append(name)
        elif not parent:
            self._root_names.append(name)

        self._recalculate_bounds()
        logger.debug("Cache: added object '%s' at %s", name, position)

    def remove_object(self, name: str) -> None:
        """Remove a deleted object from the cache.

        Args:
            name: The name of the object to remove.
        """
        obj = self._objects.pop(name, None)
        if obj is None:
            return

        # Remove from parent children list
        for other in self._objects.values():
            if name in other.children:
                other.children.remove(name)
                break

        if name in self._root_names:
            self._root_names.remove(name)

        # Recursively remove children
        if obj.children:
            for child_name in list(obj.children):
                self.remove_object(child_name)

        self._recalculate_bounds()
        logger.debug("Cache: removed object '%s'", name)

    def modify_object(
        self,
        name: str,
        position: Optional[dict[str, float]] = None,
        scale: Optional[dict[str, float]] = None,
    ) -> None:
        """Update position/scale of an existing cached object.

        Args:
            name: The name of the object to modify.
            position: New world position (or ``None`` to keep current).
            scale: New local scale (or ``None`` to keep current).
        """
        obj = self._objects.get(name)
        if obj is None:
            logger.debug("Cache: modify_object '%s' not found — ignored", name)
            return
        if position is not None:
            obj.position = position
        if scale is not None:
            obj.scale = scale
        self._recalculate_bounds()
        logger.debug("Cache: modified object '%s'", name)

    # ── Spatial queries ─────────────────────────────────────

    def get_scene_bounds(self) -> dict[str, dict[str, float]]:
        """Return axis-aligned bounding box of the entire scene.

        Returns:
            ``{"min": {x,y,z}, "max": {x,y,z}}``.
        """
        return {
            "min": dict(self._scene_bounds_min),
            "max": dict(self._scene_bounds_max),
        }

    def find_nearest(self, position: dict[str, float]) -> Optional[CachedObject]:
        """Find the cached object closest to *position*.

        Args:
            position: A ``{x, y, z}`` dict.

        Returns:
            The nearest ``CachedObject``, or ``None`` if the cache is empty.
        """
        if not self._objects:
            return None
        best: Optional[CachedObject] = None
        best_dist = float("inf")
        for obj in self._objects.values():
            d = _distance(position, obj.position)
            if d < best_dist:
                best_dist = d
                best = obj
        return best

    def resolve_spatial_reference(
        self,
        reference: str,
        anchor_name: str,
    ) -> Optional[dict[str, float]]:
        """Convert a Korean/English spatial reference into a world position.

        Supported references: "옆에", "위에", "아래에", "앞에", "뒤에",
        "가운데", and their English equivalents.

        For "가운데"/"center" the scene centroid is returned regardless of
        *anchor_name*.

        Args:
            reference: The spatial keyword (e.g. ``"옆에"``).
            anchor_name: Name of the reference object in the cache.

        Returns:
            A ``{x, y, z}`` position dict, or ``None`` if the anchor is not
            found or the reference is unknown.
        """
        ref_lower = reference.strip()
        direction = _SPATIAL_REFS.get(ref_lower)
        if direction is None:
            logger.debug("resolve_spatial_reference: unknown ref '%s'", reference)
            return None

        # "가운데" / "center" → scene centroid
        if ref_lower in ("가운데", "center"):
            return self._scene_centroid()

        anchor = self._objects.get(anchor_name)
        if anchor is None:
            logger.debug(
                "resolve_spatial_reference: anchor '%s' not in cache", anchor_name
            )
            return None

        offset = DEFAULT_PARAMS["spatial_offset"]
        half = anchor.half_extents()

        # Build offset vector: direction * (half_extent + offset)
        dx = direction["x"] * (half["x"] + offset)
        dz = direction["z"] * (half["z"] + offset)

        if ref_lower in ("위에", "above"):
            # Stack on top: anchor_y + anchor_half_height + gap
            dy = half["y"] + DEFAULT_PARAMS["y_stack_gap"]
        elif ref_lower in ("아래에", "below"):
            dy = -(half["y"] + DEFAULT_PARAMS["y_stack_gap"])
        else:
            dy = direction["y"] * (half["y"] + offset)

        return _vec_add(anchor.position, _vec(dx, dy, dz))

    # ── Properties ──────────────────────────────────────────

    @property
    def is_stale(self) -> bool:
        """``True`` if the cache is older than the configured TTL."""
        if self._last_refresh <= 0:
            return True
        return (time.monotonic() - self._last_refresh) > self._ttl

    @property
    def object_count(self) -> int:
        return len(self._objects)

    @property
    def object_names(self) -> list[str]:
        return list(self._objects.keys())

    # ── Internal helpers ────────────────────────────────────

    @staticmethod
    def _extract_hierarchy(resp: Any) -> Optional[dict]:
        """Extract the hierarchy dict from a MCP ``get_hierarchy`` response.

        Handles multiple formats:
        1. ``{"result": {"content": [{"type": "text", "text": "{\"hierarchy\": {...}}"}]}}``
        2. ``{"result": {"content": [{"type": "text", "text": "{\"data\": {\"items\": [...]}}"}]}}``
        3. Direct hierarchy dict.
        """
        if resp is None or not isinstance(resp, dict):
            logger.debug("_extract_hierarchy: resp is %s", type(resp).__name__)
            return None

        # Skip error responses
        if "error" in resp and "result" not in resp:
            logger.debug("_extract_hierarchy: MCP error response")
            return None

        try:
            result = resp.get("result", resp)
            if not isinstance(result, dict):
                return None
            content = result.get("content", [])
            for item in content:
                if item.get("type") == "text":
                    parsed = json.loads(item["text"])
                    # Format 1: hierarchy key
                    if "hierarchy" in parsed:
                        return parsed["hierarchy"]
                    # Format 2: data.items (MCP com.coplaydev.unity-mcp)
                    if "data" in parsed:
                        data = parsed["data"]
                        if "items" in data:
                            # Wrap items as children of a virtual root
                            return {"name": "(root)", "children": data["items"]}
                        if "hierarchy" in data:
                            return data["hierarchy"]
                    # Format 3: direct items array
                    if "items" in parsed:
                        return {"name": "(root)", "children": parsed["items"]}
                    return parsed
        except (json.JSONDecodeError, KeyError, TypeError, AttributeError) as exc:
            logger.debug("_extract_hierarchy parse error: %s", exc)
        return None

    def _walk(self, node: dict, parent_path: str) -> None:
        """Recursively walk a hierarchy node and populate ``_objects``.

        Handles both nested hierarchy format (with ``children`` and ``transform``)
        and flat MCP item format (with ``path``, ``childCount``, no transform).
        """
        name = node.get("name") or node.get("Name", "")
        if not name:
            return

        # Use 'path' from MCP if available, otherwise build from parent
        path = node.get("path") or (f"{parent_path}/{name}" if parent_path else name)
        transform = node.get("transform", {})
        position = transform.get("position", _vec())
        scale = transform.get("scale", _vec(1, 1, 1))

        obj = CachedObject(name=name, path=path, position=position, scale=scale)

        children = node.get("children") or node.get("Children") or []
        obj.children = [c.get("name", "") for c in children if c.get("name")]

        self._objects[name] = obj

        for child in children:
            self._walk(child, parent_path=path)

    def _recalculate_bounds(self) -> None:
        """Recompute axis-aligned scene bounding box from cached objects."""
        if not self._objects:
            self._scene_bounds_min = _vec()
            self._scene_bounds_max = _vec()
            return

        min_x = min_y = min_z = float("inf")
        max_x = max_y = max_z = float("-inf")

        for obj in self._objects.values():
            half = obj.half_extents()
            p = obj.position

            lo_x = p["x"] - half["x"]
            lo_y = p["y"] - half["y"]
            lo_z = p["z"] - half["z"]
            hi_x = p["x"] + half["x"]
            hi_y = p["y"] + half["y"]
            hi_z = p["z"] + half["z"]

            if lo_x < min_x:
                min_x = lo_x
            if lo_y < min_y:
                min_y = lo_y
            if lo_z < min_z:
                min_z = lo_z
            if hi_x > max_x:
                max_x = hi_x
            if hi_y > max_y:
                max_y = hi_y
            if hi_z > max_z:
                max_z = hi_z

        self._scene_bounds_min = _vec(min_x, min_y, min_z)
        self._scene_bounds_max = _vec(max_x, max_y, max_z)

    def _scene_centroid(self) -> dict[str, float]:
        """Return the arithmetic mean position of all cached objects."""
        if not self._objects:
            return _vec()
        sx = sy = sz = 0.0
        n = len(self._objects)
        for obj in self._objects.values():
            sx += obj.position["x"]
            sy += obj.position["y"]
            sz += obj.position["z"]
        return _vec(sx / n, sy / n, sz / n)
