"""Abstract base class for photogrammetry reconstruction engines.

Each adapter wraps a CLI tool (COLMAP, RealityCapture, Metashape, etc.)
and provides a unified interface for the pipeline orchestrator.

Usage:
    class MyEngine(ReconEngineBase):
        ...

    engine = MyEngine()
    if engine.is_available:
        report = await engine.run(project_dir, Preset.PREVIEW)
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Callable, Optional

from ..models import QAReport, ReconReport, Preset

logger = logging.getLogger(__name__)


class ReconEngineBase(ABC):
    """Base class for photogrammetry reconstruction engine adapters.

    Each adapter wraps a CLI tool (COLMAP, RealityCapture, Metashape, etc.)
    and provides a unified interface for the pipeline orchestrator.

    Subclasses must implement:
        - name: Engine display name (e.g. "COLMAP", "RealityCapture").
        - is_available: Whether the engine CLI is installed and accessible.
        - validate_inputs: Pre-flight checks on input data.
        - run_preview: Fast, reduced-quality reconstruction.
        - run_production: Full-quality reconstruction.
        - get_artifacts: Enumerate output files after reconstruction.
    """

    # ── Abstract properties ──────────────────────────────────

    @property
    @abstractmethod
    def name(self) -> str:
        """Engine display name (e.g. 'COLMAP', 'RealityCapture')."""

    @property
    @abstractmethod
    def is_available(self) -> bool:
        """Whether the engine CLI is installed and accessible on this machine."""

    # ── Abstract methods ─────────────────────────────────────

    @abstractmethod
    async def validate_inputs(self, project_dir: str) -> QAReport:
        """Validate input files before reconstruction.

        Returns a QAReport with engine-specific checks (image count,
        format support, EXIF completeness, etc.).
        """

    @abstractmethod
    async def run_preview(
        self,
        project_dir: str,
        *,
        progress_cb: Optional[Callable[[str, float], None]] = None,
    ) -> ReconReport:
        """Run fast preview reconstruction (reduced resolution/quality).

        Args:
            project_dir: Absolute path to the project root directory.
            progress_cb: Optional callback ``(stage_name, percent)`` for
                progress reporting (0.0 to 1.0).

        Returns:
            ReconReport with reconstruction statistics and any warnings.
        """

    @abstractmethod
    async def run_production(
        self,
        project_dir: str,
        *,
        progress_cb: Optional[Callable[[str, float], None]] = None,
    ) -> ReconReport:
        """Run full production reconstruction (maximum quality).

        Args:
            project_dir: Absolute path to the project root directory.
            progress_cb: Optional callback ``(stage_name, percent)`` for
                progress reporting (0.0 to 1.0).

        Returns:
            ReconReport with reconstruction statistics and any warnings.
        """

    @abstractmethod
    def get_artifacts(self, project_dir: str) -> dict[str, Any]:
        """Return dict of output artifact paths.

        Expected keys (present only if the file exists):
            - ``dense_cloud``: Path to dense point cloud (.ply).
            - ``mesh_high``: Path to high-poly mesh (.ply / .obj).
            - ``textures``: List of texture image paths.
            - ``recon_report``: Path to the JSON reconstruction report.
        """

    # ── Convenience runner ───────────────────────────────────

    async def run(
        self,
        project_dir: str,
        preset: Preset,
        *,
        progress_cb: Optional[Callable[[str, float], None]] = None,
    ) -> ReconReport:
        """Run reconstruction based on preset.

        Dispatches to ``run_preview`` or ``run_production`` depending on
        the *preset* value.

        Args:
            project_dir: Absolute path to the project root directory.
            preset: Quality/speed preset (PREVIEW or PRODUCTION).
            progress_cb: Optional callback ``(stage_name, percent)``.

        Returns:
            ReconReport from the selected pipeline.
        """
        logger.info(
            "Starting %s reconstruction with %s preset in %s",
            self.name, preset.value, project_dir,
        )
        if preset == Preset.PREVIEW:
            return await self.run_preview(project_dir, progress_cb=progress_cb)
        return await self.run_production(project_dir, progress_cb=progress_cb)
