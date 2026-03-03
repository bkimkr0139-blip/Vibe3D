"""Bookmark / Work Set API router.

CRUD endpoints for camera bookmarks and work sets.
"""

import logging
from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from .bookmark_manager import get_bookmark_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/bookmarks", tags=["bookmarks"])


# ── Request Models ──────────────────────────────────────────

class BookmarkCreateRequest(BaseModel):
    name: str
    category: str = "general"
    camera_position: list = [0, 0, 0]
    camera_target: list = [0, 0, 0]
    camera_zoom: float = 1.0
    selected_objects: list = []
    annotations: list = []
    measurements: list = []
    metadata: dict = {}
    thumbnail: str = ""


class BookmarkUpdateRequest(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    camera_position: Optional[list] = None
    camera_target: Optional[list] = None
    camera_zoom: Optional[float] = None
    selected_objects: Optional[list] = None
    annotations: Optional[list] = None
    measurements: Optional[list] = None
    metadata: Optional[dict] = None
    thumbnail: Optional[str] = None


# ── Endpoints ──────────────────────────────────────────────

@router.get("/")
async def list_bookmarks(
    category: Optional[str] = Query(None, description="Filter by category"),
    limit: int = Query(50, ge=1, le=200),
):
    """List all bookmarks, optionally filtered by category."""
    mgr = get_bookmark_manager()
    bookmarks = mgr.list_all(category=category, limit=limit)
    return {"bookmarks": [asdict(b) for b in bookmarks]}


@router.post("/")
async def create_bookmark(req: BookmarkCreateRequest):
    """Create a new bookmark/work set."""
    mgr = get_bookmark_manager()
    bm = mgr.create(
        name=req.name,
        category=req.category,
        camera_position=req.camera_position,
        camera_target=req.camera_target,
        camera_zoom=req.camera_zoom,
        selected_objects=req.selected_objects,
        annotations=req.annotations,
        measurements=req.measurements,
        metadata=req.metadata,
        thumbnail=req.thumbnail,
    )
    return asdict(bm)


@router.get("/{bookmark_id}")
async def get_bookmark(bookmark_id: str):
    """Get a specific bookmark by ID."""
    mgr = get_bookmark_manager()
    bm = mgr.get(bookmark_id)
    if not bm:
        raise HTTPException(404, f"Bookmark {bookmark_id} not found")
    return asdict(bm)


@router.put("/{bookmark_id}")
async def update_bookmark(bookmark_id: str, req: BookmarkUpdateRequest):
    """Update a bookmark's fields."""
    mgr = get_bookmark_manager()
    kwargs = {k: v for k, v in req.dict().items() if v is not None}
    if not kwargs:
        raise HTTPException(400, "No fields to update")

    bm = mgr.update(bookmark_id, **kwargs)
    if not bm:
        raise HTTPException(404, f"Bookmark {bookmark_id} not found")
    return asdict(bm)


@router.delete("/{bookmark_id}")
async def delete_bookmark(bookmark_id: str):
    """Delete a bookmark."""
    mgr = get_bookmark_manager()
    ok = mgr.delete(bookmark_id)
    if not ok:
        raise HTTPException(404, f"Bookmark {bookmark_id} not found")
    return {"deleted": True, "bookmark_id": bookmark_id}
