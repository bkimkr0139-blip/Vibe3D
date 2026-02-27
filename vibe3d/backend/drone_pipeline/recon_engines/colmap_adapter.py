"""COLMAP + OpenMVS reconstruction engine adapter.

This is a stub implementation.  COLMAP must be installed separately.
When ``COLMAP_PATH`` is set and the binary is accessible, the full
pipeline runs the following SfM/MVS stages:

    1. Feature extraction  (``colmap feature_extractor``)
    2. Feature matching    (``colmap exhaustive_matcher`` or ``sequential_matcher``)
    3. Sparse reconstruction (``colmap mapper``)
    4. Dense reconstruction  (``colmap image_undistorter`` + ``patch_match_stereo`` + ``stereo_fusion``)
    5. Meshing             (``colmap poisson_mesher``)

Otherwise, methods return descriptive warnings so the caller can
surface actionable messages to the user.
"""

import asyncio
import json
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Any, Callable, Optional

from ...config import COLMAP_PATH
from ..models import QAReport, ReconReport, Preset
from .base import ReconEngineBase

logger = logging.getLogger(__name__)

# -- Constants ----------------------------------------------------------------

_SUPPORTED_IMAGE_EXTS: set[str] = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}

_MIN_IMAGES = 3
_RECOMMENDED_IMAGES = 20

# Preview mode caps image size for faster processing
_PREVIEW_MAX_IMAGE_SIZE = 1000   # pixels (longest edge)
_PRODUCTION_MAX_IMAGE_SIZE = -1  # unlimited


class ColmapAdapter(ReconEngineBase):
    """COLMAP CLI reconstruction adapter.

    Wraps the ``colmap`` command-line tool.  Each pipeline stage is
    executed as an async subprocess so the event loop stays responsive.

    Configuration:
        Set ``COLMAP_PATH`` in your ``.env`` file (defaults to ``"colmap"``
        which relies on PATH resolution).
    """

    def __init__(self) -> None:
        self._colmap_path: str = COLMAP_PATH

    # -- Properties ------------------------------------------------------------

    @property
    def name(self) -> str:
        return "COLMAP"

    @property
    def is_available(self) -> bool:
        """Check if the COLMAP binary is accessible on ``PATH``."""
        return bool(shutil.which(self._colmap_path))

    # -- Input validation ------------------------------------------------------

    async def validate_inputs(self, project_dir: str) -> QAReport:
        """Validate images exist and COLMAP is accessible.

        Checks performed:
            - ``raw/images/`` directory exists.
            - At least ``_MIN_IMAGES`` supported images present.
            - COLMAP binary is reachable.
        """
        report = QAReport(score=50)
        proj = Path(project_dir)
        images_dir = proj / "raw" / "images"

        # Check images directory
        if not images_dir.is_dir():
            report.score = 0
            report.warnings.append(
                f"Images directory not found: {images_dir}"
            )
            logger.warning("validate_inputs: images dir missing -- %s", images_dir)
            return report

        # Count supported images
        image_files = [
            f for f in images_dir.iterdir()
            if f.is_file() and f.suffix.lower() in _SUPPORTED_IMAGE_EXTS
        ]
        image_count = len(image_files)
        report.image_count = image_count

        if image_count < _MIN_IMAGES:
            report.score = 10
            report.warnings.append(
                f"Only {image_count} images -- minimum {_MIN_IMAGES} required, "
                f"{_RECOMMENDED_IMAGES}+ recommended for reliable reconstruction."
            )
        elif image_count < _RECOMMENDED_IMAGES:
            report.score = 60
            report.recommendations.append(
                f"{image_count} images detected. Consider adding more for "
                f"better coverage ({_RECOMMENDED_IMAGES}+ recommended)."
            )
        else:
            report.score = 80

        # Check COLMAP availability
        if not self.is_available:
            report.warnings.append(
                f"COLMAP not found at '{self._colmap_path}' -- "
                "install COLMAP or set COLMAP_PATH in .env"
            )
            report.score = max(report.score - 20, 0)
            logger.warning("validate_inputs: COLMAP binary not found")

        logger.info(
            "validate_inputs: %d images, score=%d, warnings=%d",
            image_count, report.score, len(report.warnings),
        )
        return report

    # -- Reconstruction runs ---------------------------------------------------

    async def run_preview(
        self,
        project_dir: str,
        *,
        progress_cb: Optional[Callable[[str, float], None]] = None,
    ) -> ReconReport:
        """Run COLMAP preview reconstruction (reduced resolution).

        Uses ``--max_image_size {_PREVIEW_MAX_IMAGE_SIZE}`` to trade
        quality for speed, suitable for same-day validation.
        """
        return await self._run_colmap(
            project_dir, Preset.PREVIEW, progress_cb=progress_cb,
        )

    async def run_production(
        self,
        project_dir: str,
        *,
        progress_cb: Optional[Callable[[str, float], None]] = None,
    ) -> ReconReport:
        """Run COLMAP production reconstruction (full quality).

        No resolution cap; runs all stages at maximum quality.
        Suitable for overnight batch processing.
        """
        return await self._run_colmap(
            project_dir, Preset.PRODUCTION, progress_cb=progress_cb,
        )

    # -- Artifacts -------------------------------------------------------------

    def get_artifacts(self, project_dir: str) -> dict[str, Any]:
        """Return paths to reconstruction outputs.

        Scans ``work/recon/`` for known output files and returns only
        those that exist on disk.
        """
        work = Path(project_dir) / "work" / "recon"
        artifacts: dict[str, Any] = {}

        # Dense point cloud
        for candidate in ("dense.ply", "fused.ply"):
            path = work / candidate
            if path.exists():
                artifacts["dense_cloud"] = str(path)
                break

        # High-poly mesh
        for candidate in ("meshed-poisson.ply", "mesh.obj", "mesh.ply"):
            path = work / candidate
            if path.exists():
                artifacts["mesh_high"] = str(path)
                break

        # Textures
        tex_dir = work / "textures"
        if tex_dir.is_dir():
            tex_files = [
                str(f) for f in sorted(tex_dir.iterdir())
                if f.is_file() and f.suffix.lower() in {".jpg", ".jpeg", ".png"}
            ]
            if tex_files:
                artifacts["textures"] = tex_files

        # Reconstruction report
        report_path = work / "recon_report.json"
        if report_path.exists():
            artifacts["recon_report"] = str(report_path)

        logger.debug("get_artifacts: %s -> %s", project_dir, list(artifacts.keys()))
        return artifacts

    # -- Internal pipeline -----------------------------------------------------

    async def _run_colmap(
        self,
        project_dir: str,
        preset: Preset,
        *,
        progress_cb: Optional[Callable[[str, float], None]] = None,
    ) -> ReconReport:
        """Execute the COLMAP pipeline stages.

        Pipeline stages (when fully implemented):
            1. ``feature_extractor``  -- detect keypoints in each image
            2. ``exhaustive_matcher`` -- match features across image pairs
               (``sequential_matcher`` for >100 images)
            3. ``mapper``             -- sparse SfM reconstruction
            4. ``image_undistorter`` + ``patch_match_stereo`` +
               ``stereo_fusion``     -- dense MVS reconstruction
            5. ``poisson_mesher``     -- surface reconstruction

        Args:
            project_dir: Absolute path to the project root.
            preset: PREVIEW (fast) or PRODUCTION (full quality).
            progress_cb: Optional ``(stage, percent)`` callback.

        Returns:
            ReconReport with statistics, elapsed time, and any warnings.
        """
        start_time = time.time()
        report = ReconReport(engine="colmap", preset=preset.value)

        # -- Pre-flight checks -------------------------------------------------
        if not self.is_available:
            report.warnings.append(
                f"COLMAP not installed (path: '{self._colmap_path}'). "
                "Install COLMAP and set COLMAP_PATH in .env to enable "
                "reconstruction."
            )
            report.elapsed_seconds = time.time() - start_time
            logger.warning("_run_colmap: COLMAP binary not available, aborting")
            return report

        proj = Path(project_dir)
        images_dir = proj / "raw" / "images"
        work_dir = proj / "work" / "recon"
        work_dir.mkdir(parents=True, exist_ok=True)

        # Count input images
        images = [
            f for f in images_dir.iterdir()
            if f.is_file() and f.suffix.lower() in _SUPPORTED_IMAGE_EXTS
        ]
        report.image_count = len(images)

        if report.image_count < _MIN_IMAGES:
            report.warnings.append(
                f"Only {report.image_count} images -- need at least "
                f"{_MIN_IMAGES} for reconstruction."
            )
            report.elapsed_seconds = time.time() - start_time
            return report

        # Determine matching strategy based on image count
        use_sequential = report.image_count > 100
        max_image_size = (
            _PREVIEW_MAX_IMAGE_SIZE
            if preset == Preset.PREVIEW
            else _PRODUCTION_MAX_IMAGE_SIZE
        )

        logger.info(
            "_run_colmap: %d images, preset=%s, matcher=%s, max_size=%s",
            report.image_count,
            preset.value,
            "sequential" if use_sequential else "exhaustive",
            max_image_size if max_image_size > 0 else "unlimited",
        )

        # -- Pipeline stages (stub) --------------------------------------------
        #
        # Each stage would call _run_subprocess() with the appropriate
        # COLMAP command.  The full implementation is gated on COLMAP
        # binary integration.
        #
        # Stage 1: Feature extraction
        #   await self._run_subprocess([
        #       self._colmap_path, "feature_extractor",
        #       "--database_path", str(work_dir / "db.db"),
        #       "--image_path", str(images_dir),
        #       "--ImageReader.single_camera", "1",
        #   ])
        #
        # Stage 2: Feature matching
        #   matcher = "sequential_matcher" if use_sequential else "exhaustive_matcher"
        #   await self._run_subprocess([
        #       self._colmap_path, matcher,
        #       "--database_path", str(work_dir / "db.db"),
        #   ])
        #
        # Stage 3: Sparse reconstruction
        #   sparse_dir = work_dir / "sparse"
        #   sparse_dir.mkdir(exist_ok=True)
        #   await self._run_subprocess([
        #       self._colmap_path, "mapper",
        #       "--database_path", str(work_dir / "db.db"),
        #       "--image_path", str(images_dir),
        #       "--output_path", str(sparse_dir),
        #   ])
        #
        # Stage 4: Dense reconstruction
        #   dense_dir = work_dir / "dense"
        #   await self._run_subprocess([
        #       self._colmap_path, "image_undistorter",
        #       "--image_path", str(images_dir),
        #       "--input_path", str(sparse_dir / "0"),
        #       "--output_path", str(dense_dir),
        #       "--output_type", "COLMAP",
        #   ])
        #   await self._run_subprocess([
        #       self._colmap_path, "patch_match_stereo",
        #       "--workspace_path", str(dense_dir),
        #       *(["--PatchMatchStereo.max_image_size",
        #          str(max_image_size)] if max_image_size > 0 else []),
        #   ])
        #   await self._run_subprocess([
        #       self._colmap_path, "stereo_fusion",
        #       "--workspace_path", str(dense_dir),
        #       "--output_path", str(work_dir / "fused.ply"),
        #   ])
        #
        # Stage 5: Meshing
        #   await self._run_subprocess([
        #       self._colmap_path, "poisson_mesher",
        #       "--input_path", str(work_dir / "fused.ply"),
        #       "--output_path", str(work_dir / "meshed-poisson.ply"),
        #   ])

        report.warnings.append(
            "COLMAP pipeline execution not yet implemented. "
            "Full SfM/MVS pipeline stages are defined but need "
            "COLMAP binary integration."
        )
        report.elapsed_seconds = time.time() - start_time

        # -- Persist report to disk --------------------------------------------
        report_path = work_dir / "recon_report.json"
        try:
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)
            logger.info("Reconstruction report saved to %s", report_path)
        except OSError as exc:
            logger.error("Failed to write recon report: %s", exc)
            report.warnings.append(f"Could not save report: {exc}")

        return report

    # -- Subprocess helper (for future use) ------------------------------------

    async def _run_subprocess(
        self,
        cmd: list[str],
        *,
        cwd: Optional[str] = None,
        timeout: float = 3600.0,
    ) -> tuple[int, str, str]:
        """Run a COLMAP subprocess asynchronously.

        Args:
            cmd: Command and arguments to execute.
            cwd: Working directory for the subprocess.
            timeout: Maximum execution time in seconds (default: 1 hour).

        Returns:
            Tuple of (return_code, stdout, stderr).

        Raises:
            asyncio.TimeoutError: If the process exceeds *timeout*.
            RuntimeError: If the process exits with a non-zero code.
        """
        logger.debug("Subprocess: %s", " ".join(cmd))
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            logger.error("Subprocess timed out after %.0fs: %s", timeout, cmd[0])
            raise

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        rc = proc.returncode or 0

        if rc != 0:
            logger.error(
                "Subprocess failed (rc=%d): %s\nstderr: %s",
                rc, " ".join(cmd), stderr[:500],
            )
            raise RuntimeError(
                f"{cmd[0]} exited with code {rc}: {stderr[:200]}"
            )

        logger.debug("Subprocess completed (rc=%d, stdout=%d bytes)", rc, len(stdout))
        return rc, stdout, stderr
