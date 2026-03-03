"""GeoBIM SQLite database — matches Appendix A schema from dev instruction.

Table: buildings
  building_id, tile_id, cx/cy/cz, aabb_min/max, obb_json,
  height_min/max/avg, area_2d, surface_area_approx, volume_approx,
  footprint_json, confidence, tags_json
"""

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Optional

from .geobim_models import BuildingCandidate, ExtractionStatus, GeoBIMReport, OBBData

logger = logging.getLogger("vibe3d.geobim.db")

_DEFAULT_DB = Path(__file__).resolve().parent.parent.parent / "data" / "geobim.sqlite"


class GeoBIMDatabase:
    """SQLite persistence for GeoBIM building data (Appendix A)."""

    def __init__(self, db_path: Optional[str] = None):
        self._db_path = Path(db_path) if db_path else _DEFAULT_DB
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @property
    def db_path(self) -> Path:
        return self._db_path

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self):
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS buildings (
                    building_id TEXT PRIMARY KEY,
                    tile_id TEXT NOT NULL,
                    label TEXT NOT NULL DEFAULT '',
                    cx REAL DEFAULT 0, cy REAL DEFAULT 0, cz REAL DEFAULT 0,
                    aabb_minx REAL DEFAULT 0, aabb_miny REAL DEFAULT 0, aabb_minz REAL DEFAULT 0,
                    aabb_maxx REAL DEFAULT 0, aabb_maxy REAL DEFAULT 0, aabb_maxz REAL DEFAULT 0,
                    obb_json TEXT DEFAULT '{}',
                    height_min REAL DEFAULT 0,
                    height_max REAL DEFAULT 0,
                    height_avg REAL DEFAULT 0,
                    ground_elevation REAL DEFAULT 0,
                    area_2d REAL DEFAULT 0,
                    surface_area_approx REAL DEFAULT 0,
                    volume_approx REAL DEFAULT 0,
                    footprint_json TEXT DEFAULT '[]',
                    vertex_count INTEGER DEFAULT 0,
                    face_count INTEGER DEFAULT 0,
                    confidence REAL DEFAULT 0,
                    cluster_id INTEGER DEFAULT -1,
                    tags_json TEXT DEFAULT '["building"]',
                    created_at REAL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    status TEXT NOT NULL,
                    tile_count INTEGER DEFAULT 0,
                    tiles_processed INTEGER DEFAULT 0,
                    building_count INTEGER DEFAULT 0,
                    total_footprint_area REAL DEFAULT 0,
                    total_volume REAL DEFAULT 0,
                    avg_height REAL DEFAULT 0,
                    max_height REAL DEFAULT 0,
                    ground_plane_z REAL DEFAULT 0,
                    processing_time_s REAL DEFAULT 0,
                    error TEXT,
                    created_at REAL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS collider_proxies (
                    tile_name TEXT PRIMARY KEY,
                    input_path TEXT,
                    output_path TEXT,
                    original_triangles INTEGER DEFAULT 0,
                    proxy_triangles INTEGER DEFAULT 0,
                    reduction_ratio REAL DEFAULT 0,
                    success INTEGER DEFAULT 0,
                    error TEXT,
                    processing_time_s REAL DEFAULT 0,
                    created_at REAL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS review_queue (
                    building_id TEXT PRIMARY KEY,
                    confidence REAL DEFAULT 0,
                    status TEXT DEFAULT 'pending',
                    reviewer_label TEXT,
                    reviewed_at REAL,
                    notes TEXT DEFAULT '',
                    FOREIGN KEY (building_id) REFERENCES buildings(building_id)
                );

                CREATE INDEX IF NOT EXISTS idx_buildings_tile_id ON buildings(tile_id);
                CREATE INDEX IF NOT EXISTS idx_buildings_centroid ON buildings(cx, cz);
                CREATE INDEX IF NOT EXISTS idx_buildings_height ON buildings(height_max);
                CREATE INDEX IF NOT EXISTS idx_buildings_confidence ON buildings(confidence);
            """)

    # ── Buildings CRUD ──────────────────────────────────────

    def save_buildings(self, buildings: list[BuildingCandidate]):
        with self._conn() as conn:
            for b in buildings:
                conn.execute("""
                    INSERT OR REPLACE INTO buildings
                    (building_id, tile_id, label, cx, cy, cz,
                     aabb_minx, aabb_miny, aabb_minz,
                     aabb_maxx, aabb_maxy, aabb_maxz,
                     obb_json, height_min, height_max, height_avg,
                     ground_elevation, area_2d, surface_area_approx, volume_approx,
                     footprint_json, vertex_count, face_count,
                     confidence, cluster_id, tags_json, created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    b.id, b.tile_name, b.label,
                    b.centroid[0], b.centroid[1], b.centroid[2],
                    b.bbox_min[0], b.bbox_min[1], b.bbox_min[2],
                    b.bbox_max[0], b.bbox_max[1], b.bbox_max[2],
                    json.dumps(b.obb.to_dict() if b.obb else {}),
                    b.height_min, b.height_max, b.height_avg,
                    b.ground_elevation, b.footprint_area,
                    b.surface_area_approx, b.volume_approx,
                    json.dumps(b.footprint), b.vertex_count, b.face_count,
                    b.confidence, b.cluster_id, json.dumps(b.tags),
                    time.time(),
                ))

    def get_building(self, building_id: str) -> Optional[BuildingCandidate]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM buildings WHERE building_id = ?", (building_id,)).fetchone()
        return self._row_to_building(row) if row else None

    def get_buildings(self, tile_name: Optional[str] = None,
                      min_height: Optional[float] = None,
                      min_confidence: Optional[float] = None,
                      limit: int = 500) -> list[BuildingCandidate]:
        query = "SELECT * FROM buildings WHERE 1=1"
        params: list = []

        if tile_name:
            query += " AND tile_id = ?"
            params.append(tile_name)
        if min_height is not None:
            query += " AND height_max >= ?"
            params.append(min_height)
        if min_confidence is not None:
            query += " AND confidence >= ?"
            params.append(min_confidence)

        query += " ORDER BY confidence DESC LIMIT ?"
        params.append(limit)

        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_building(r) for r in rows]

    def get_footprints(self) -> list[dict]:
        """Return minimal footprint data for overlay rendering."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT building_id, label, footprint_json, cx, cy, cz, "
                "height_max, confidence FROM buildings ORDER BY confidence DESC"
            ).fetchall()
        results = []
        for r in rows:
            results.append({
                "id": r["building_id"],
                "label": r["label"],
                "footprint": json.loads(r["footprint_json"]),
                "centroid": [r["cx"], r["cy"], r["cz"]],
                "height": r["height_max"],
                "confidence": r["confidence"],
            })
        return results

    def get_summary(self) -> dict:
        with self._conn() as conn:
            row = conn.execute("""
                SELECT
                    COUNT(*) as count,
                    COALESCE(AVG(height_max), 0) as avg_height,
                    COALESCE(MAX(height_max), 0) as max_height,
                    COALESCE(SUM(area_2d), 0) as total_area,
                    COALESCE(SUM(volume_approx), 0) as total_volume,
                    COALESCE(AVG(confidence), 0) as avg_confidence,
                    COUNT(DISTINCT tile_id) as tile_count
                FROM buildings
            """).fetchone()
        return {
            "building_count": row["count"],
            "avg_height": round(row["avg_height"], 2),
            "max_height": round(row["max_height"], 2),
            "total_footprint_area": round(row["total_area"], 2),
            "total_volume": round(row["total_volume"], 2),
            "avg_confidence": round(row["avg_confidence"], 3),
            "tile_count": row["tile_count"],
        }

    def spatial_query(self, x: float, z: float, radius: float = 10.0) -> list[BuildingCandidate]:
        """Find buildings near a point (XZ plane), using centroid index."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM buildings WHERE "
                "cx BETWEEN ? AND ? AND cz BETWEEN ? AND ?",
                (x - radius, x + radius, z - radius, z + radius)
            ).fetchall()
        results = []
        for r in rows:
            dx = r["cx"] - x
            dz = r["cz"] - z
            if (dx * dx + dz * dz) <= radius * radius:
                results.append(self._row_to_building(r))
        return results

    def clear_all(self):
        with self._conn() as conn:
            conn.execute("DELETE FROM buildings")
            conn.execute("DELETE FROM reports")
            conn.execute("DELETE FROM collider_proxies")

    # ── Collider Proxies ────────────────────────────────────

    def save_collider_proxy(self, result: dict):
        with self._conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO collider_proxies
                (tile_name, input_path, output_path, original_triangles,
                 proxy_triangles, reduction_ratio, success, error,
                 processing_time_s, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)
            """, (
                result["tile_name"], result.get("input_path", ""),
                result.get("output_path", ""),
                result.get("original_triangles", 0),
                result.get("proxy_triangles", 0),
                result.get("reduction_ratio", 0),
                1 if result.get("success") else 0,
                result.get("error"),
                result.get("processing_time_s", 0),
                time.time(),
            ))

    def get_collider_proxies(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM collider_proxies").fetchall()
        return [dict(r) for r in rows]

    # ── Reports ─────────────────────────────────────────────

    def save_report(self, report: GeoBIMReport):
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO reports
                (status, tile_count, tiles_processed, building_count,
                 total_footprint_area, total_volume, avg_height, max_height,
                 ground_plane_z, processing_time_s, error, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                report.status.value, report.tile_count, report.tiles_processed,
                report.building_count, report.total_footprint_area,
                report.total_volume, report.avg_height,
                report.max_height, report.ground_plane_z, report.processing_time_s,
                report.error, time.time(),
            ))

    def get_latest_report(self) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM reports ORDER BY id DESC LIMIT 1").fetchone()
        return dict(row) if row else None

    # ── Review Queue (HITL — Section 3.3.3) ────────────────

    def populate_review_queue(self, threshold: float = 0.5):
        """Move low-confidence buildings into review queue."""
        with self._conn() as conn:
            conn.execute("DELETE FROM review_queue")
            conn.execute("""
                INSERT INTO review_queue (building_id, confidence, status)
                SELECT building_id, confidence, 'pending'
                FROM buildings WHERE confidence < ?
            """, (threshold,))
            count = conn.execute("SELECT COUNT(*) FROM review_queue").fetchone()[0]
        logger.info(f"[HITL] Review queue populated: {count} items (threshold={threshold})")
        return count

    def get_review_queue(self, status: Optional[str] = None, limit: int = 100) -> list[dict]:
        """Get items in the review queue."""
        query = """
            SELECT rq.*, b.label, b.tile_id, b.height_max, b.area_2d,
                   b.cx, b.cy, b.cz, b.footprint_json
            FROM review_queue rq
            JOIN buildings b ON rq.building_id = b.building_id
        """
        params: list = []
        if status:
            query += " WHERE rq.status = ?"
            params.append(status)
        query += " ORDER BY rq.confidence ASC LIMIT ?"
        params.append(limit)

        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def review_building(self, building_id: str, decision: str, notes: str = "") -> bool:
        """
        Mark a building review decision.
        decision: 'building' (confirm), 'not_building' (reject), 'skip'
        """
        with self._conn() as conn:
            row = conn.execute(
                "SELECT building_id FROM review_queue WHERE building_id = ?",
                (building_id,)
            ).fetchone()
            if not row:
                return False

            conn.execute("""
                UPDATE review_queue
                SET status = ?, reviewer_label = ?, reviewed_at = ?, notes = ?
                WHERE building_id = ?
            """, (decision, decision, time.time(), notes, building_id))

            # If rejected, remove from buildings + update tags
            if decision == 'not_building':
                conn.execute(
                    "UPDATE buildings SET tags_json = ? WHERE building_id = ?",
                    (json.dumps(["rejected"]), building_id)
                )
        return True

    def get_review_stats(self) -> dict:
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM review_queue").fetchone()[0]
            pending = conn.execute(
                "SELECT COUNT(*) FROM review_queue WHERE status = 'pending'"
            ).fetchone()[0]
            confirmed = conn.execute(
                "SELECT COUNT(*) FROM review_queue WHERE status = 'building'"
            ).fetchone()[0]
            rejected = conn.execute(
                "SELECT COUNT(*) FROM review_queue WHERE status = 'not_building'"
            ).fetchone()[0]
            skipped = conn.execute(
                "SELECT COUNT(*) FROM review_queue WHERE status = 'skip'"
            ).fetchone()[0]
        return {
            "total": total, "pending": pending,
            "confirmed": confirmed, "rejected": rejected, "skipped": skipped,
        }

    # ── Helpers ─────────────────────────────────────────────

    @staticmethod
    def _row_to_building(row) -> BuildingCandidate:
        obb_data = json.loads(row["obb_json"]) if row["obb_json"] else {}
        obb = OBBData(
            center=obb_data.get("center", [0, 0, 0]),
            axes=obb_data.get("axes", [[1,0,0],[0,1,0],[0,0,1]]),
            extents=obb_data.get("extents", [0, 0, 0]),
        ) if obb_data.get("center") else None

        return BuildingCandidate(
            id=row["building_id"],
            tile_name=row["tile_id"],
            label=row["label"],
            height=row["height_max"],
            height_min=row["height_min"],
            height_max=row["height_max"],
            height_avg=row["height_avg"],
            ground_elevation=row["ground_elevation"],
            roof_elevation=row["aabb_maxy"],
            footprint_area=row["area_2d"],
            surface_area_approx=row["surface_area_approx"],
            volume_approx=row["volume_approx"],
            bbox_min=[row["aabb_minx"], row["aabb_miny"], row["aabb_minz"]],
            bbox_max=[row["aabb_maxx"], row["aabb_maxy"], row["aabb_maxz"]],
            obb=obb,
            footprint=json.loads(row["footprint_json"]),
            centroid=[row["cx"], row["cy"], row["cz"]],
            vertex_count=row["vertex_count"],
            face_count=row["face_count"],
            confidence=row["confidence"],
            cluster_id=row["cluster_id"],
            tags=json.loads(row["tags_json"]),
        )


# ── Singleton ───────────────────────────────────────────────

_db: Optional[GeoBIMDatabase] = None


def get_db() -> GeoBIMDatabase:
    global _db
    if _db is None:
        _db = GeoBIMDatabase()
    return _db
