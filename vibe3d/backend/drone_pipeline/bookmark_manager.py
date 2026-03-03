"""Bookmark / Work Set manager.

Saves and restores camera positions, selected objects, and measurement results
as named "sets" for instant recall during meetings/reviews.

Storage: SQLite (shared with mesh_edit jobs DB or separate file).
"""

import json
import logging
import os
import sqlite3
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class Bookmark:
    bookmark_id: str
    name: str
    category: str = "general"  # general, measurement, visibility, path, review
    camera_position: list = field(default_factory=lambda: [0, 0, 0])
    camera_target: list = field(default_factory=lambda: [0, 0, 0])
    camera_zoom: float = 1.0
    selected_objects: list = field(default_factory=list)  # list of object names/ids
    annotations: list = field(default_factory=list)  # list of {text, position}
    measurements: list = field(default_factory=list)  # list of measurement results
    metadata: dict = field(default_factory=dict)  # freeform extra data
    thumbnail: str = ""  # base64 thumbnail (optional)
    created_at: float = 0.0
    updated_at: float = 0.0


class BookmarkManager:
    """Manages bookmark/work set persistence in SQLite."""

    def __init__(self, db_path: str = ""):
        if not db_path:
            data_dir = Path(os.environ.get("VIBE3D_DATA_DIR", Path.cwd() / "vibe3d" / "data"))
            data_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(data_dir / "bookmarks.sqlite")

        self._db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS bookmarks (
                    bookmark_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    category TEXT DEFAULT 'general',
                    camera_position TEXT DEFAULT '[]',
                    camera_target TEXT DEFAULT '[]',
                    camera_zoom REAL DEFAULT 1.0,
                    selected_objects TEXT DEFAULT '[]',
                    annotations TEXT DEFAULT '[]',
                    measurements TEXT DEFAULT '[]',
                    metadata TEXT DEFAULT '{}',
                    thumbnail TEXT DEFAULT '',
                    created_at REAL DEFAULT 0,
                    updated_at REAL DEFAULT 0
                )
            """)
            conn.commit()

    def create(self, name: str, category: str = "general",
               camera_position: list = None, camera_target: list = None,
               camera_zoom: float = 1.0, selected_objects: list = None,
               annotations: list = None, measurements: list = None,
               metadata: dict = None, thumbnail: str = "") -> Bookmark:
        """Create a new bookmark."""
        now = time.time()
        bm = Bookmark(
            bookmark_id=str(uuid.uuid4())[:8],
            name=name,
            category=category,
            camera_position=camera_position or [0, 0, 0],
            camera_target=camera_target or [0, 0, 0],
            camera_zoom=camera_zoom,
            selected_objects=selected_objects or [],
            annotations=annotations or [],
            measurements=measurements or [],
            metadata=metadata or {},
            thumbnail=thumbnail,
            created_at=now,
            updated_at=now,
        )

        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """INSERT INTO bookmarks
                   (bookmark_id, name, category, camera_position, camera_target,
                    camera_zoom, selected_objects, annotations, measurements,
                    metadata, thumbnail, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (bm.bookmark_id, bm.name, bm.category,
                 json.dumps(bm.camera_position), json.dumps(bm.camera_target),
                 bm.camera_zoom, json.dumps(bm.selected_objects),
                 json.dumps(bm.annotations), json.dumps(bm.measurements),
                 json.dumps(bm.metadata), bm.thumbnail,
                 bm.created_at, bm.updated_at),
            )
            conn.commit()

        logger.info("Bookmark created: %s (%s)", bm.name, bm.bookmark_id)
        return bm

    def get(self, bookmark_id: str) -> Optional[Bookmark]:
        """Get a bookmark by ID."""
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM bookmarks WHERE bookmark_id = ?", (bookmark_id,)
            ).fetchone()

        if not row:
            return None
        return self._row_to_bookmark(row)

    def list_all(self, category: str = None, limit: int = 50) -> list:
        """List all bookmarks, optionally filtered by category."""
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            if category:
                rows = conn.execute(
                    "SELECT * FROM bookmarks WHERE category = ? ORDER BY updated_at DESC LIMIT ?",
                    (category, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM bookmarks ORDER BY updated_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()

        return [self._row_to_bookmark(r) for r in rows]

    def update(self, bookmark_id: str, **kwargs) -> Optional[Bookmark]:
        """Update a bookmark's fields."""
        bm = self.get(bookmark_id)
        if not bm:
            return None

        updates = []
        values = []
        json_fields = {"camera_position", "camera_target", "selected_objects",
                        "annotations", "measurements", "metadata"}

        for key, val in kwargs.items():
            if hasattr(bm, key) and key not in ("bookmark_id", "created_at"):
                if key in json_fields:
                    updates.append(f"{key} = ?")
                    values.append(json.dumps(val))
                else:
                    updates.append(f"{key} = ?")
                    values.append(val)

        if not updates:
            return bm

        updates.append("updated_at = ?")
        values.append(time.time())
        values.append(bookmark_id)

        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                f"UPDATE bookmarks SET {', '.join(updates)} WHERE bookmark_id = ?",
                values,
            )
            conn.commit()

        return self.get(bookmark_id)

    def delete(self, bookmark_id: str) -> bool:
        """Delete a bookmark."""
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM bookmarks WHERE bookmark_id = ?", (bookmark_id,)
            )
            conn.commit()
            return cursor.rowcount > 0

    def _row_to_bookmark(self, row) -> Bookmark:
        return Bookmark(
            bookmark_id=row["bookmark_id"],
            name=row["name"],
            category=row["category"],
            camera_position=json.loads(row["camera_position"] or "[]"),
            camera_target=json.loads(row["camera_target"] or "[]"),
            camera_zoom=row["camera_zoom"] or 1.0,
            selected_objects=json.loads(row["selected_objects"] or "[]"),
            annotations=json.loads(row["annotations"] or "[]"),
            measurements=json.loads(row["measurements"] or "[]"),
            metadata=json.loads(row["metadata"] or "{}"),
            thumbnail=row["thumbnail"] or "",
            created_at=row["created_at"] or 0,
            updated_at=row["updated_at"] or 0,
        )


# ── Singleton ──────────────────────────────────────────────
_manager: Optional[BookmarkManager] = None


def get_bookmark_manager() -> BookmarkManager:
    global _manager
    if _manager is None:
        _manager = BookmarkManager()
    return _manager
