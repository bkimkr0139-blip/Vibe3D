# mesh_edit_engine.py
# Blender headless subprocess wrapper for tile mesh editing.

import json
import logging
import shutil
import subprocess
import time
from pathlib import Path
from typing import Callable, Optional

from .mesh_edit_models import (
    DEFAULT_PARAMS,
    EditJobResult,
    EditJobStage,
    EditJobStatus,
    EditManifest,
    MeshStats,
)

logger = logging.getLogger("vibe3d.mesh_edit.engine")

# Path to the Blender script (shipped alongside this module)
_BLENDER_SCRIPT = Path(__file__).resolve().parent / "blender_scripts" / "tile_edit.py"

# Version registry filename
_ACTIVE_VERSIONS_FILE = "active_versions.json"


class MeshEditEngine:
    """Runs Blender headless to process tile meshes."""

    def __init__(self, blender_path: str = "blender"):
        self._blender_path = blender_path
        self._blender_available: Optional[bool] = None
        self._blender_version: str = ""

    # ── Blender availability ──────────────────────────────────

    def check_blender(self) -> dict:
        """Check if Blender CLI is available (cached)."""
        if self._blender_available is not None:
            return {
                "available": self._blender_available,
                "version": self._blender_version,
                "path": self._blender_path,
            }
        try:
            proc = subprocess.run(
                [self._blender_path, "--version"],
                capture_output=True, text=True, timeout=10,
            )
            self._blender_available = proc.returncode == 0
            if self._blender_available:
                self._blender_version = proc.stdout.strip().split("\n")[0]
                logger.info(f"Blender found: {self._blender_version}")
        except (FileNotFoundError, subprocess.TimeoutExpired):
            self._blender_available = False
            logger.warning("Blender not found -- mesh editing disabled")
        return {
            "available": self._blender_available,
            "version": self._blender_version,
            "path": self._blender_path,
        }

    # ── Run edit job ──────────────────────────────────────────

    def run_edit_job(
        self,
        job: EditJobResult,
        input_path: str,
        work_dir: str,
        progress_cb: Optional[Callable] = None,
    ) -> EditJobResult:
        """Execute a full edit job via Blender subprocess.

        Args:
            job: EditJobResult (mutated in-place with progress).
            input_path: Path to the input OBJ/FBX file.
            work_dir: Temporary working directory for Blender output.
            progress_cb: Optional callback(job) on stage changes.
        """
        job.started_at = time.time()
        job.status = EditJobStatus.RUNNING

        # Merge default params with job-specific overrides
        preset = job.preset
        params = {**DEFAULT_PARAMS.get(preset, {}), **job.params}
        job.params = params

        def _update_stage(stage: EditJobStage, pct: float):
            job.stage = stage
            job.progress_pct = pct
            if progress_cb:
                progress_cb(job)

        # ── Pre-flight checks ─────────────────────────────────
        blender_info = self.check_blender()
        if not blender_info["available"]:
            job.status = EditJobStatus.FAILED
            job.stage = EditJobStage.FAILED
            job.error = "Blender not available. Install Blender and ensure it's in PATH."
            job.completed_at = time.time()
            job.duration_s = job.completed_at - job.started_at
            if progress_cb:
                progress_cb(job)
            return job

        input_p = Path(input_path)
        if not input_p.exists():
            job.status = EditJobStatus.FAILED
            job.stage = EditJobStage.FAILED
            job.error = f"Input file not found: {input_path}"
            job.completed_at = time.time()
            job.duration_s = job.completed_at - job.started_at
            if progress_cb:
                progress_cb(job)
            return job

        # ── Stage: IMPORT ─────────────────────────────────────
        _update_stage(EditJobStage.IMPORT_TILE, 5.0)

        work_p = Path(work_dir)
        work_p.mkdir(parents=True, exist_ok=True)
        output_dir = str(work_p / "output")

        blender_params = {
            "preset": preset,
            "input_path": str(input_p).replace("\\", "/"),
            "output_dir": output_dir.replace("\\", "/"),
            "params": params,
        }

        # ── Run Blender subprocess ────────────────────────────
        _update_stage(EditJobStage.CLEANUP, 15.0)

        try:
            blender_result = self._run_blender(blender_params)
        except Exception as e:
            job.status = EditJobStatus.FAILED
            job.stage = EditJobStage.FAILED
            job.error = str(e)
            job.completed_at = time.time()
            job.duration_s = job.completed_at - job.started_at
            if progress_cb:
                progress_cb(job)
            return job

        # ── Parse Blender output ──────────────────────────────
        if not blender_result.get("success"):
            job.status = EditJobStatus.FAILED
            job.stage = EditJobStage.FAILED
            job.error = blender_result.get("error", "Unknown Blender error")
            job.completed_at = time.time()
            job.duration_s = job.completed_at - job.started_at
            if progress_cb:
                progress_cb(job)
            return job

        _update_stage(EditJobStage.EXPORT, 70.0)

        # Populate stats from Blender result
        input_stats = blender_result.get("input_stats", {})
        output_stats = blender_result.get("output_stats", {})
        job.original = MeshStats(
            triangles=input_stats.get("triangles", 0),
            vertices=input_stats.get("vertices", 0),
            materials=input_stats.get("materials", 0),
        )
        job.result = MeshStats(
            triangles=output_stats.get("triangles", 0),
            vertices=output_stats.get("vertices", 0),
            materials=output_stats.get("materials", 0),
        )

        # LOD/collider stats from stages
        stages = blender_result.get("stages", {})
        lods = stages.get("lods", {}).get("lods", [])
        for lod in lods:
            level = lod.get("level", 0)
            tris = lod.get("triangles", 0)
            if level == 0:
                job.lod0_triangles = tris
            elif level == 1:
                job.lod1_triangles = tris
            elif level == 2:
                job.lod2_triangles = tris

        collider_data = stages.get("collider", {})
        job.collider_triangles = collider_data.get("triangles", 0)

        # Export file info
        export_data = stages.get("export", {})
        files = export_data.get("files", {})
        job.lod_files = []
        for key in sorted(files.keys()):
            if key.startswith("LOD"):
                job.lod_files.append(files[key].get("filename", ""))
        if "COLLIDER" in files:
            job.collider_file = files["COLLIDER"].get("filename", "")

        # Set output dir
        job.output_dir = output_dir

        # Warnings
        quality = blender_result.get("quality_flags", {})
        if quality.get("seam_risk"):
            job.warnings.append("Seam risk detected at tile boundary")

        # ── Stage: PACKAGE ────────────────────────────────────
        _update_stage(EditJobStage.PACKAGE, 85.0)

        # Package results from work dir to versioned edit dir
        try:
            self._package_results(job, output_dir)
        except Exception as e:
            job.warnings.append(f"Packaging warning: {e}")

        # ── Completed (preview_ready) ─────────────────────────
        job.status = EditJobStatus.PREVIEW_READY
        job.stage = EditJobStage.COMPLETED
        job.progress_pct = 100.0
        job.completed_at = time.time()
        job.duration_s = round(job.completed_at - job.started_at, 2)

        # Build manifest
        job.manifest = EditManifest(
            tile_id=job.tile_id,
            version=job.version,
            preset=job.preset,
            params=job.params,
            input_stats=input_stats,
            output_stats=output_stats,
            files={k: v.get("filename", "") for k, v in files.items()},
            quality_flags=quality,
            created_at=job.completed_at,
            tool_versions={"blender": self._blender_version},
        )

        if progress_cb:
            progress_cb(job)

        logger.info(
            f"Edit job {job.job_id} completed: {job.preset} on {job.tile_id} "
            f"({job.original.triangles} -> {job.result.triangles} tris, {job.duration_s}s)"
        )
        return job

    # ── Blender subprocess ────────────────────────────────────

    def _run_blender(self, params: dict, timeout: int = 600) -> dict:
        """Run tile_edit.py in Blender headless, parse RESULT: from stdout."""
        if not _BLENDER_SCRIPT.exists():
            raise FileNotFoundError(f"Blender script not found: {_BLENDER_SCRIPT}")

        params_json = json.dumps(params, ensure_ascii=False)

        cmd = [
            self._blender_path,
            "--background",
            "--python", str(_BLENDER_SCRIPT),
            "--", params_json,
        ]

        logger.debug(f"Running Blender: {' '.join(cmd[:4])} ...")

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"Blender timed out after {timeout}s")
        except FileNotFoundError:
            raise RuntimeError(f"Blender executable not found: {self._blender_path}")

        # Parse RESULT: line from stdout
        stdout = proc.stdout or ""
        for line in stdout.splitlines():
            if line.startswith("RESULT:"):
                try:
                    return json.loads(line[7:])
                except json.JSONDecodeError as e:
                    raise RuntimeError(f"Invalid JSON in Blender output: {e}")

        # No RESULT line found
        stderr_tail = proc.stderr[-1000:] if proc.stderr else ""
        stdout_tail = proc.stdout[-500:] if proc.stdout else ""
        raise RuntimeError(
            f"No RESULT output from Blender (exit code {proc.returncode}). "
            f"stdout tail: {stdout_tail}, stderr tail: {stderr_tail}"
        )

    # ── Package results to versioned directory ────────────────

    def _package_results(self, job: EditJobResult, work_output_dir: str):
        """Move processed files from work dir to tiles_edit/tile_id/v{nnnn}/."""
        project_dir = Path(job.project_dir)
        edit_base = project_dir / "tiles_edit" / job.tile_id
        version_dir = edit_base / f"v{job.version:04d}"
        version_dir.mkdir(parents=True, exist_ok=True)

        # Move files from work output to version directory
        work_out = Path(work_output_dir)
        if work_out.exists():
            for f in work_out.iterdir():
                dest = version_dir / f.name
                shutil.move(str(f), str(dest))

        # Write manifest.json
        manifest_data = job.manifest.to_dict() if job.manifest.tile_id else {
            "tile_id": job.tile_id,
            "version": job.version,
            "preset": job.preset,
            "params": job.params,
            "created_at": time.time(),
        }
        manifest_path = version_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest_data, indent=2, ensure_ascii=False))

        job.output_dir = str(version_dir)
        logger.info(f"Packaged edit results to {version_dir}")

    # ── Apply edited tile (update active_versions.json) ───────

    @staticmethod
    def apply_version(project_dir: str, tile_id: str, version: int) -> dict:
        """Mark a version as active in the version registry."""
        p = Path(project_dir)
        registry_path = p / "tiles_edit" / _ACTIVE_VERSIONS_FILE

        registry: dict = {}
        if registry_path.exists():
            try:
                registry = json.loads(registry_path.read_text())
            except (json.JSONDecodeError, OSError):
                pass

        registry[tile_id] = {
            "version": version,
            "applied_at": time.time(),
        }

        registry_path.parent.mkdir(parents=True, exist_ok=True)
        registry_path.write_text(json.dumps(registry, indent=2))
        logger.info(f"Applied tile {tile_id} version {version}")

        return {"tile_id": tile_id, "version": version, "registry": str(registry_path)}

    @staticmethod
    def get_active_versions(project_dir: str) -> dict:
        """Read the active version registry."""
        registry_path = Path(project_dir) / "tiles_edit" / _ACTIVE_VERSIONS_FILE
        if not registry_path.exists():
            return {}
        try:
            return json.loads(registry_path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}


# ── Singleton ───────────────────────────────────────────────

_engine: Optional[MeshEditEngine] = None


def get_engine(blender_path: str = "blender") -> MeshEditEngine:
    global _engine
    if _engine is None:
        _engine = MeshEditEngine(blender_path)
    return _engine
