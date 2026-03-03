# mesh_edit_manager.py
# Job queue manager for tile mesh editing — SQLite + async execution.

import asyncio
import json
import logging
import sqlite3
import tempfile
import time
import uuid
from pathlib import Path
from typing import Callable, Optional

from .mesh_edit_engine import MeshEditEngine, get_engine
from .mesh_edit_models import (
    DEFAULT_PARAMS,
    EditJobResult,
    EditJobStage,
    EditJobStatus,
    EditManifest,
    MeshStats,
)

logger = logging.getLogger("vibe3d.mesh_edit.manager")

_DEFAULT_DB = Path(__file__).resolve().parent.parent.parent / "data" / "mesh_edit.sqlite"


class MeshEditManager:
    """Manages tile mesh edit jobs with async execution and SQLite persistence."""

    def __init__(self, db_path: Optional[str] = None, blender_path: str = "blender"):
        self._db_path = Path(db_path) if db_path else _DEFAULT_DB
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._engine = get_engine(blender_path)
        self._jobs: dict[str, EditJobResult] = {}   # in-memory cache
        self._broadcast: Optional[Callable] = None   # WS broadcast function
        self._init_db()

    def set_broadcast(self, broadcast_fn: Callable):
        """Inject WebSocket broadcast function from main.py."""
        self._broadcast = broadcast_fn

    # ── SQLite setup ──────────────────────────────────────────

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self):
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS edit_jobs (
                    job_id TEXT PRIMARY KEY,
                    tile_id TEXT NOT NULL,
                    preset TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    stage TEXT NOT NULL DEFAULT 'queued',
                    progress_pct REAL DEFAULT 0,
                    version INTEGER DEFAULT 0,
                    project_dir TEXT DEFAULT '',
                    original_triangles INTEGER DEFAULT 0,
                    original_vertices INTEGER DEFAULT 0,
                    result_triangles INTEGER DEFAULT 0,
                    result_vertices INTEGER DEFAULT 0,
                    lod0_triangles INTEGER DEFAULT 0,
                    lod1_triangles INTEGER DEFAULT 0,
                    lod2_triangles INTEGER DEFAULT 0,
                    collider_triangles INTEGER DEFAULT 0,
                    output_dir TEXT DEFAULT '',
                    lod_files TEXT DEFAULT '[]',
                    collider_file TEXT DEFAULT '',
                    params TEXT DEFAULT '{}',
                    error TEXT,
                    warnings TEXT DEFAULT '[]',
                    started_at REAL DEFAULT 0,
                    completed_at REAL DEFAULT 0,
                    duration_s REAL DEFAULT 0,
                    created_at REAL DEFAULT 0
                );

                CREATE INDEX IF NOT EXISTS idx_edit_jobs_tile_id ON edit_jobs(tile_id);
                CREATE INDEX IF NOT EXISTS idx_edit_jobs_status ON edit_jobs(status);
                CREATE INDEX IF NOT EXISTS idx_edit_jobs_created ON edit_jobs(created_at DESC);
            """)

    # ── Job lifecycle ─────────────────────────────────────────

    def start_job(
        self,
        tile_id: str,
        preset: str,
        project_dir: str,
        params: Optional[dict] = None,
    ) -> str:
        """Create a new edit job and launch async execution. Returns job_id."""
        job_id = f"edit_{uuid.uuid4().hex[:12]}"
        version = self._get_next_version(project_dir, tile_id)

        job = EditJobResult(
            job_id=job_id,
            tile_id=tile_id,
            preset=preset,
            status=EditJobStatus.PENDING,
            stage=EditJobStage.QUEUED,
            version=version,
            project_dir=project_dir,
            params=params or {},
        )

        self._jobs[job_id] = job
        self._save_job(job)

        # Broadcast start event
        self._ws_event("mesh_edit_started", {
            "job_id": job_id,
            "tile_id": tile_id,
            "preset": preset,
        })

        # Launch async execution
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(self._execute_job(job_id, project_dir))
            else:
                loop.create_task(self._execute_job(job_id, project_dir))
        except RuntimeError:
            # No event loop — run synchronously (for testing)
            logger.warning("No event loop available, running job synchronously")
            self._execute_job_sync(job_id, project_dir)

        return job_id

    async def _execute_job(self, job_id: str, project_dir: str):
        """Run the edit job in a background thread."""
        job = self._jobs.get(job_id)
        if job is None:
            return

        # Find input file
        input_path = self._find_tile_input(project_dir, job.tile_id)
        if not input_path:
            job.status = EditJobStatus.FAILED
            job.stage = EditJobStage.FAILED
            job.error = f"Tile input file not found for {job.tile_id}"
            self._save_job(job)
            self._ws_event("mesh_edit_failed", {
                "job_id": job_id, "tile_id": job.tile_id, "error": job.error,
            })
            return

        # Work directory
        work_dir = Path(tempfile.mkdtemp(prefix=f"tile_edit_{job.tile_id}_"))

        def progress_cb(j: EditJobResult):
            self._save_job(j)
            self._ws_event("mesh_edit_progress", {
                "job_id": j.job_id,
                "stage": j.stage.value if isinstance(j.stage, EditJobStage) else j.stage,
                "progress_pct": round(j.progress_pct, 1),
                "status": j.status.value if isinstance(j.status, EditJobStatus) else j.status,
            })

        try:
            await asyncio.to_thread(
                self._engine.run_edit_job,
                job, input_path, str(work_dir), progress_cb,
            )
        except Exception as e:
            job.status = EditJobStatus.FAILED
            job.stage = EditJobStage.FAILED
            job.error = str(e)

        self._save_job(job)

        if job.status == EditJobStatus.PREVIEW_READY:
            self._ws_event("mesh_edit_preview_ready", {
                "job_id": job_id,
                "tile_id": job.tile_id,
                "preview": self.get_preview(job_id),
            })
        elif job.status == EditJobStatus.FAILED:
            self._ws_event("mesh_edit_failed", {
                "job_id": job_id,
                "tile_id": job.tile_id,
                "error": job.error,
            })

    def _execute_job_sync(self, job_id: str, project_dir: str):
        """Synchronous fallback for environments without event loop."""
        job = self._jobs.get(job_id)
        if job is None:
            return

        input_path = self._find_tile_input(project_dir, job.tile_id)
        if not input_path:
            job.status = EditJobStatus.FAILED
            job.error = f"Tile input file not found for {job.tile_id}"
            self._save_job(job)
            return

        work_dir = Path(tempfile.mkdtemp(prefix=f"tile_edit_{job.tile_id}_"))
        self._engine.run_edit_job(job, input_path, str(work_dir), None)
        self._save_job(job)

    # ── Query methods ─────────────────────────────────────────

    def get_job_status(self, job_id: str) -> Optional[dict]:
        """Get current job status (in-memory first, then DB fallback)."""
        job = self._jobs.get(job_id)
        if job:
            return job.to_dict()

        # DB fallback
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM edit_jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        if row:
            return self._row_to_dict(row)
        return None

    def get_preview(self, job_id: str) -> Optional[dict]:
        """Get before/after stats for a completed job."""
        job = self._jobs.get(job_id)
        if job is None:
            status = self.get_job_status(job_id)
            if status is None:
                return None
            return {
                "job_id": job_id,
                "tile_id": status.get("tile_id"),
                "preset": status.get("preset"),
                "status": status.get("status"),
                "original": status.get("original", {}),
                "result": status.get("result", {}),
                "lod0_triangles": status.get("lod0_triangles", 0),
                "lod1_triangles": status.get("lod1_triangles", 0),
                "lod2_triangles": status.get("lod2_triangles", 0),
                "collider_triangles": status.get("collider_triangles", 0),
                "duration_s": status.get("duration_s", 0),
                "version": status.get("version", 0),
            }

        return {
            "job_id": job_id,
            "tile_id": job.tile_id,
            "preset": job.preset,
            "status": job.status.value if isinstance(job.status, EditJobStatus) else job.status,
            "original": {
                "triangles": job.original.triangles,
                "vertices": job.original.vertices,
            },
            "result": {
                "triangles": job.result.triangles,
                "vertices": job.result.vertices,
            },
            "lod0_triangles": job.lod0_triangles,
            "lod1_triangles": job.lod1_triangles,
            "lod2_triangles": job.lod2_triangles,
            "collider_triangles": job.collider_triangles,
            "duration_s": job.duration_s,
            "version": job.version,
            "lod_files": job.lod_files,
            "collider_file": job.collider_file,
            "warnings": job.warnings,
        }

    def apply_job(self, job_id: str) -> dict:
        """Apply a preview-ready job: update active_versions.json."""
        job = self._jobs.get(job_id)
        if job is None:
            return {"error": f"Job {job_id} not found"}

        if job.status != EditJobStatus.PREVIEW_READY:
            return {"error": f"Job {job_id} is not preview_ready (status={job.status})"}

        job.status = EditJobStatus.APPLYING
        self._save_job(job)

        try:
            result = MeshEditEngine.apply_version(job.project_dir, job.tile_id, job.version)
            job.status = EditJobStatus.COMPLETED
            self._save_job(job)

            self._ws_event("mesh_edit_applied", {
                "job_id": job_id,
                "tile_id": job.tile_id,
                "version": job.version,
            })

            return {"success": True, **result}
        except Exception as e:
            job.status = EditJobStatus.FAILED
            job.error = str(e)
            self._save_job(job)
            return {"error": str(e)}

    def cancel_job(self, job_id: str) -> dict:
        """Cancel a running or pending job."""
        job = self._jobs.get(job_id)
        if job is None:
            return {"error": f"Job {job_id} not found"}

        if job.status in (EditJobStatus.COMPLETED, EditJobStatus.CANCELLED):
            return {"error": f"Job {job_id} already {job.status.value}"}

        job.status = EditJobStatus.CANCELLED
        job.stage = EditJobStage.CANCELLED
        job.completed_at = time.time()
        if job.started_at:
            job.duration_s = round(job.completed_at - job.started_at, 2)
        self._save_job(job)

        return {"success": True, "job_id": job_id}

    def get_history(self, tile_id: Optional[str] = None, limit: int = 50) -> list[dict]:
        """Get edit history, optionally filtered by tile_id."""
        query = "SELECT * FROM edit_jobs"
        params: list = []

        if tile_id:
            query += " WHERE tile_id = ?"
            params.append(tile_id)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def check_blender(self) -> dict:
        """Proxy to engine's blender check."""
        return self._engine.check_blender()

    # ── Rollback ──────────────────────────────────────────────

    def rollback_version(self, tile_id: str, version: int, project_dir: str = "") -> dict:
        """Rollback a tile to a specific version (or 0 = revert to raw)."""
        if version == 0:
            # Revert to raw: remove from active_versions
            registry = MeshEditEngine.get_active_versions(project_dir) if project_dir else {}
            if tile_id in registry:
                del registry[tile_id]
                reg_path = Path(project_dir) / "tiles_edit" / "active_versions.json"
                reg_path.write_text(json.dumps(registry, indent=2))
            return {"success": True, "tile_id": tile_id, "version": 0, "message": "Reverted to raw tile"}

        # Check version exists
        ver_dir = Path(project_dir) / "tiles_edit" / tile_id / f"v{version:04d}" if project_dir else None
        if ver_dir and not ver_dir.exists():
            # Check in DB for the version
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT * FROM edit_jobs WHERE tile_id = ? AND version = ? AND status = 'completed'",
                    (tile_id, version),
                ).fetchone()
            if not row:
                return {"error": f"Version {version} not found for tile {tile_id}"}

        result = MeshEditEngine.apply_version(project_dir, tile_id, version)
        self._ws_event("mesh_edit_applied", {
            "tile_id": tile_id, "version": version, "rollback": True,
        })
        return {"success": True, **result}

    # ── Version comparison ────────────────────────────────────

    def compare_versions(self, tile_id: str, v1: int = 0, v2: int = 0) -> dict:
        """Compare stats between two versions of a tile. v=0 means latest."""
        with self._conn() as conn:
            if v1 == 0 and v2 == 0:
                # Compare first vs latest
                rows = conn.execute(
                    "SELECT * FROM edit_jobs WHERE tile_id = ? AND status IN ('completed','preview_ready') "
                    "ORDER BY version ASC", (tile_id,)
                ).fetchall()
                if len(rows) < 2:
                    return {"error": "Need at least 2 versions to compare", "versions_available": len(rows)}
                row1, row2 = rows[0], rows[-1]
            else:
                row1 = conn.execute(
                    "SELECT * FROM edit_jobs WHERE tile_id = ? AND version = ?", (tile_id, v1)
                ).fetchone()
                row2 = conn.execute(
                    "SELECT * FROM edit_jobs WHERE tile_id = ? AND version = ?", (tile_id, v2)
                ).fetchone()

            if not row1 or not row2:
                return {"error": f"Version not found: v1={v1}, v2={v2}"}

        d1, d2 = self._row_to_dict(row1), self._row_to_dict(row2)
        return {
            "tile_id": tile_id,
            "v1": {"version": d1["version"], "preset": d1["preset"],
                    "original": d1["original"], "result": d1["result"],
                    "lod0": d1["lod0_triangles"], "collider": d1["collider_triangles"],
                    "duration_s": d1["duration_s"]},
            "v2": {"version": d2["version"], "preset": d2["preset"],
                    "original": d2["original"], "result": d2["result"],
                    "lod0": d2["lod0_triangles"], "collider": d2["collider_triangles"],
                    "duration_s": d2["duration_s"]},
            "diff": {
                "triangles": d2["result"]["triangles"] - d1["result"]["triangles"],
                "vertices": d2["result"]["vertices"] - d1["result"]["vertices"],
                "collider": d2["collider_triangles"] - d1["collider_triangles"],
            },
        }

    # ── Tile versions list ────────────────────────────────────

    def get_tile_versions(self, tile_id: str) -> list[dict]:
        """Get all versions of a tile (completed/preview_ready jobs)."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM edit_jobs WHERE tile_id = ? "
                "AND status IN ('completed','preview_ready') "
                "ORDER BY version ASC", (tile_id,)
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    # ── Tile validation ───────────────────────────────────────

    def validate_tile(self, tile_id: str, project_dir: str = "") -> dict:
        """Validate a tile file for common issues."""
        issues: list[dict] = []
        input_path = self._find_tile_input(project_dir, tile_id) if project_dir else None

        if not input_path:
            return {
                "tile_id": tile_id,
                "valid": False,
                "issues": [{"severity": "error", "code": "FILE_NOT_FOUND",
                            "message": f"Tile file not found for {tile_id}"}],
            }

        p = Path(input_path)
        size_bytes = p.stat().st_size if p.exists() else 0

        # Check file size
        if size_bytes == 0:
            issues.append({"severity": "error", "code": "EMPTY_FILE", "message": "Tile file is empty"})
        elif size_bytes > 500_000_000:
            issues.append({"severity": "warning", "code": "LARGE_FILE",
                           "message": f"Tile is very large ({size_bytes / 1e6:.0f}MB), processing may be slow"})

        # Check for MTL (texture references)
        if p.suffix.lower() == ".obj":
            mtl_path = p.with_suffix(".mtl")
            if not mtl_path.exists():
                issues.append({"severity": "warning", "code": "MISSING_MTL",
                               "message": "MTL file not found (textures may be missing)"})
            else:
                mtl_text = mtl_path.read_text(errors="ignore")
                # Check for referenced texture files
                import re
                tex_refs = re.findall(r'map_\w+\s+(.+)', mtl_text)
                for tex_ref in tex_refs:
                    tex_file = p.parent / tex_ref.strip()
                    if not tex_file.exists():
                        issues.append({"severity": "warning", "code": "MISSING_TEXTURE",
                                       "message": f"Referenced texture not found: {tex_ref.strip()}"})

        # Check tile naming convention
        import re
        if not re.match(r'tile_\d+_\d+', tile_id):
            issues.append({"severity": "info", "code": "NAMING_CONVENTION",
                           "message": f"Tile ID '{tile_id}' doesn't match tile_X_Y convention"})

        return {
            "tile_id": tile_id,
            "valid": not any(i["severity"] == "error" for i in issues),
            "file_path": input_path,
            "size_bytes": size_bytes,
            "format": p.suffix.lower(),
            "issues": issues,
            "issue_count": len(issues),
        }

    # ── Quality report ────────────────────────────────────────

    def generate_report(self, project_dir: str = "") -> dict:
        """Generate a quality report across all edit jobs."""
        with self._conn() as conn:
            # Overall stats
            total = conn.execute("SELECT COUNT(*) FROM edit_jobs").fetchone()[0]
            completed = conn.execute(
                "SELECT COUNT(*) FROM edit_jobs WHERE status = 'completed'"
            ).fetchone()[0]
            failed = conn.execute(
                "SELECT COUNT(*) FROM edit_jobs WHERE status = 'failed'"
            ).fetchone()[0]

            # Per-tile aggregates
            tile_stats = conn.execute("""
                SELECT tile_id,
                    COUNT(*) as edit_count,
                    MAX(version) as latest_version,
                    SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) as completed_count,
                    AVG(duration_s) as avg_duration,
                    MIN(original_triangles) as min_original_tris,
                    MAX(original_triangles) as max_original_tris,
                    MIN(result_triangles) as min_result_tris,
                    MAX(result_triangles) as max_result_tris,
                    AVG(collider_triangles) as avg_collider_tris
                FROM edit_jobs
                GROUP BY tile_id
                ORDER BY tile_id
            """).fetchall()

            # Active versions
            active = MeshEditEngine.get_active_versions(project_dir) if project_dir else {}

        tiles = []
        for row in tile_stats:
            tile_id = row["tile_id"]
            active_ver = active.get(tile_id, {}).get("version", 0)
            reduction = 0
            if row["max_original_tris"] and row["max_original_tris"] > 0:
                reduction = round(
                    (1 - row["min_result_tris"] / row["max_original_tris"]) * 100, 1
                )
            tiles.append({
                "tile_id": tile_id,
                "edit_count": row["edit_count"],
                "latest_version": row["latest_version"],
                "active_version": active_ver,
                "completed": row["completed_count"],
                "avg_duration_s": round(row["avg_duration"] or 0, 1),
                "original_tris": row["max_original_tris"],
                "result_tris": row["min_result_tris"],
                "reduction_pct": reduction,
                "avg_collider_tris": round(row["avg_collider_tris"] or 0),
            })

        return {
            "total_jobs": total,
            "completed": completed,
            "failed": failed,
            "success_rate": round(completed / max(total, 1) * 100, 1),
            "tile_count": len(tiles),
            "tiles": tiles,
            "active_versions": active,
        }

    # ── Internal helpers ──────────────────────────────────────

    def _save_job(self, job: EditJobResult):
        """Persist job state to SQLite."""
        with self._conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO edit_jobs
                (job_id, tile_id, preset, status, stage, progress_pct, version,
                 project_dir, original_triangles, original_vertices,
                 result_triangles, result_vertices,
                 lod0_triangles, lod1_triangles, lod2_triangles, collider_triangles,
                 output_dir, lod_files, collider_file, params,
                 error, warnings, started_at, completed_at, duration_s, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                job.job_id, job.tile_id, job.preset,
                job.status.value if isinstance(job.status, EditJobStatus) else job.status,
                job.stage.value if isinstance(job.stage, EditJobStage) else job.stage,
                job.progress_pct, job.version, job.project_dir,
                job.original.triangles, job.original.vertices,
                job.result.triangles, job.result.vertices,
                job.lod0_triangles, job.lod1_triangles, job.lod2_triangles,
                job.collider_triangles,
                job.output_dir, json.dumps(job.lod_files), job.collider_file,
                json.dumps(job.params), job.error, json.dumps(job.warnings),
                job.started_at, job.completed_at, job.duration_s,
                time.time(),
            ))

    def _find_tile_input(self, project_dir: str, tile_id: str) -> Optional[str]:
        """Find the input tile file (OBJ/FBX) from tiles_raw or tiles/."""
        p = Path(project_dir)
        # Check tiles_raw first (original tiles)
        for folder in ["tiles_raw", "tiles"]:
            base = p / folder
            if not base.exists():
                continue
            for ext in [".obj", ".fbx", ".glb"]:
                candidate = base / f"{tile_id}{ext}"
                if candidate.exists():
                    return str(candidate)
                # Also check subdirectories
                for sub in base.rglob(f"{tile_id}{ext}"):
                    return str(sub)
                # Check without exact name match (tile might have different naming)
                for sub in base.rglob(f"*{tile_id}*{ext}"):
                    return str(sub)
        return None

    def _get_next_version(self, project_dir: str, tile_id: str) -> int:
        """Determine the next version number for a tile."""
        edit_dir = Path(project_dir) / "tiles_edit" / tile_id
        if not edit_dir.exists():
            return 1

        versions = []
        for d in edit_dir.iterdir():
            if d.is_dir() and d.name.startswith("v"):
                try:
                    versions.append(int(d.name[1:]))
                except ValueError:
                    pass
        return max(versions, default=0) + 1

    def _ws_event(self, event_type: str, data: dict):
        """Broadcast a WebSocket event if broadcast function is set."""
        if self._broadcast:
            try:
                asyncio.ensure_future(self._broadcast(event_type, data))
            except RuntimeError:
                pass  # No event loop

    @staticmethod
    def _row_to_dict(row) -> dict:
        """Convert a SQLite Row to a dict."""
        return {
            "job_id": row["job_id"],
            "tile_id": row["tile_id"],
            "preset": row["preset"],
            "status": row["status"],
            "stage": row["stage"],
            "progress_pct": round(row["progress_pct"], 1),
            "version": row["version"],
            "original": {
                "triangles": row["original_triangles"],
                "vertices": row["original_vertices"],
            },
            "result": {
                "triangles": row["result_triangles"],
                "vertices": row["result_vertices"],
            },
            "lod0_triangles": row["lod0_triangles"],
            "lod1_triangles": row["lod1_triangles"],
            "lod2_triangles": row["lod2_triangles"],
            "collider_triangles": row["collider_triangles"],
            "output_dir": row["output_dir"],
            "lod_files": json.loads(row["lod_files"]) if row["lod_files"] else [],
            "collider_file": row["collider_file"],
            "params": json.loads(row["params"]) if row["params"] else {},
            "error": row["error"],
            "warnings": json.loads(row["warnings"]) if row["warnings"] else [],
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
            "duration_s": round(row["duration_s"], 2),
        }


# ── Singleton ───────────────────────────────────────────────

_manager: Optional[MeshEditManager] = None


def get_manager() -> MeshEditManager:
    global _manager
    if _manager is None:
        _manager = MeshEditManager()
    return _manager
