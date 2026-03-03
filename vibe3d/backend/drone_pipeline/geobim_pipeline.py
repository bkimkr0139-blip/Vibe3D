"""GeoBIM Batch Pipeline Orchestrator (Section 1.3).

Steps:
  00_ingest_validate   — validate OBJ/MTL/textures, tile naming
  10_generate_collider — Blender headless collider proxy
  20_building_segment  — RANSAC+DBSCAN building separation
  30_attribute_extract — GeoBIM attributes (height/footprint/obb/volume)
  40_export_assets     — JSONL + SQLite + colliders → Unity folder
"""

import logging
import time
from pathlib import Path
from typing import Optional

from .geobim_collider_proxy import get_generator
from .geobim_db import get_db
from .geobim_export import get_exporter
from .geobim_extractor import get_extractor
from .geobim_models import PipelineStage, PipelineState

logger = logging.getLogger("vibe3d.geobim.pipeline")


class GeoBIMPipeline:
    """Runs the full offline GeoBIM pipeline in sequence."""

    def __init__(self):
        self._state = PipelineState()
        self._progress_callback = None

    @property
    def state(self) -> PipelineState:
        return self._state

    def set_progress_callback(self, cb):
        self._progress_callback = cb

    def _notify(self):
        if self._progress_callback:
            self._progress_callback(self._state)

    def run_full(self, tile_folder: str, export_folder: str,
                 skip_collider: bool = False) -> PipelineState:
        """Run the complete 00-40 pipeline."""
        self._state = PipelineState(
            tile_folder=tile_folder,
            export_folder=export_folder,
            is_running=True,
        )

        try:
            # ── Step 00: Ingest & Validate ──
            self._run_step(PipelineStage.INGEST_VALIDATE, 0.0,
                           lambda: self._step_00_ingest(tile_folder))

            # ── Step 10: Collider Proxy ──
            if not skip_collider:
                self._run_step(PipelineStage.GENERATE_COLLIDER, 20.0,
                               lambda: self._step_10_collider(tile_folder, export_folder))

            # ── Step 20: Building Segmentation ──
            self._run_step(PipelineStage.BUILDING_SEGMENTATION, 40.0,
                           lambda: self._step_20_segmentation(tile_folder))

            # ── Step 30: Attribute Extraction ──
            # (already done in step 20 — extractor computes all attributes)
            self._run_step(PipelineStage.ATTRIBUTE_EXTRACTION, 70.0,
                           lambda: self._step_30_attributes())

            # ── Step 40: Export ──
            collider_dir = str(Path(export_folder) / "collider") if not skip_collider else None
            self._run_step(PipelineStage.EXPORT_ASSETS, 85.0,
                           lambda: self._step_40_export(export_folder, collider_dir))

            self._state.progress_pct = 100.0
            self._state.is_running = False
            self._state.current_stage = None
            self._notify()
            logger.info("GeoBIM pipeline complete!")

        except Exception as e:
            self._state.error = str(e)
            self._state.is_running = False
            logger.error(f"Pipeline failed: {e}")

        return self._state

    def _run_step(self, stage: PipelineStage, pct: float, fn):
        self._state.current_stage = stage
        self._state.progress_pct = pct
        self._notify()
        logger.info(f"Running pipeline stage: {stage.value}")
        t0 = time.time()
        fn()
        elapsed = time.time() - t0
        self._state.stages_completed.append(stage.value)
        logger.info(f"Stage {stage.value} completed in {elapsed:.1f}s")

    # ── Step implementations ────────────────────────────────

    def _step_00_ingest(self, tile_folder: str):
        """Validate OBJ/MTL/texture references and tile naming."""
        folder = Path(tile_folder)
        issues = []

        obj_files = sorted(folder.rglob("*.obj"))
        if not obj_files:
            raise ValueError(f"No OBJ files found in {tile_folder}")

        for obj_path in obj_files:
            # Check MTL reference
            with open(obj_path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if line.startswith("mtllib "):
                        mtl_name = line.strip().split(None, 1)[1]
                        mtl_path = obj_path.parent / mtl_name
                        if not mtl_path.exists():
                            issues.append(f"{obj_path.name}: MTL not found: {mtl_name}")
                        else:
                            # Check texture references in MTL
                            with open(mtl_path, "r", encoding="utf-8", errors="replace") as mf:
                                for mline in mf:
                                    if mline.strip().startswith("map_"):
                                        tex_name = mline.strip().split()[-1]
                                        tex_path = mtl_path.parent / tex_name
                                        if not tex_path.exists():
                                            issues.append(f"{obj_path.name}: texture not found: {tex_name}")
                        break

        if issues:
            logger.warning(f"Ingest validation: {len(issues)} issues found")
            for issue in issues[:10]:
                logger.warning(f"  - {issue}")
        else:
            logger.info(f"Ingest validation passed: {len(obj_files)} OBJ files")

    def _step_10_collider(self, tile_folder: str, export_folder: str):
        """Generate collider proxies via Blender headless."""
        gen = get_generator()
        collider_dir = str(Path(export_folder) / "collider")
        results = gen.generate_all(tile_folder, collider_dir)

        db = get_db()
        success_count = 0
        for r in results:
            db.save_collider_proxy(r.to_dict())
            if r.success:
                success_count += 1

        self._state.collider_count = success_count
        logger.info(f"Collider generation: {success_count}/{len(results)} succeeded")

    def _step_20_segmentation(self, tile_folder: str):
        """Run building segmentation (RANSAC+DBSCAN)."""
        extractor = get_extractor()
        report = extractor.extract_all(tile_folder)

        db = get_db()
        db.clear_all()
        db.save_buildings(report.buildings)
        db.save_report(report)

        self._state.building_count = report.building_count

    def _step_30_attributes(self):
        """Verify and log attribute extraction results.

        Note: attributes are already computed during step 20 extraction.
        This step validates completeness.
        """
        db = get_db()
        buildings = db.get_buildings(limit=10000)
        missing_obb = sum(1 for b in buildings if b.obb is None)
        low_confidence = sum(1 for b in buildings if b.confidence < 0.5)

        logger.info(
            f"Attribute check: {len(buildings)} buildings, "
            f"{missing_obb} missing OBB, {low_confidence} low-confidence (<0.5)"
        )

    def _step_40_export(self, export_folder: str, collider_dir: Optional[str]):
        """Export all data to Unity-compatible format."""
        exporter = get_exporter()
        result = exporter.export_all(export_folder, collider_dir)
        logger.info(f"Export result: {result['buildings_exported']} buildings, "
                     f"{result['colliders_exported']} colliders")


# ── Singleton ───────────────────────────────────────────────

_pipeline: Optional[GeoBIMPipeline] = None


def get_pipeline() -> GeoBIMPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = GeoBIMPipeline()
    return _pipeline
