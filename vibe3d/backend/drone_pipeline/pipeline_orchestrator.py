"""Pipeline orchestrator for the Drone2Twin pipeline.

State machine that manages project lifecycle and executes pipeline stages
(Ingest QA → Reconstruction → Optimization → Unity Import → WebGL Build → Deploy).
"""

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Callable, Optional

from .. import config
from .models import (
    DroneProject,
    InputOption,
    OptimizeReport,
    PerfReport,
    PipelineStage,
    Preset,
    PROJECT_DIRS,
    QAReport,
    ReconReport,
)
from .ingest_qa import IngestQAEngine
from .optimize_engine import BlenderOptimizeEngine
from .perf_reporter import PerfReporter
from .deployment import DeploymentManager

logger = logging.getLogger(__name__)


class PipelineOrchestrator:
    """Drone2Twin pipeline state machine (singleton)."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        self._projects: dict[str, DroneProject] = {}
        self._data_dir = config.DATA_DIR / "drone_projects"
        self._data_dir.mkdir(parents=True, exist_ok=True)

        # External dependencies (injected from main.py)
        self._mcp_client = None
        self._executor = None
        self._broadcast_fn = None

        # Sub-engines
        self._ingest_qa = IngestQAEngine()
        self._optimizer = BlenderOptimizeEngine()
        self._perf_reporter = PerfReporter()
        self._deployer = DeploymentManager()

        # Load existing projects
        self._load_projects()
        logger.info(
            "PipelineOrchestrator initialized: %d projects loaded", len(self._projects)
        )

    def set_dependencies(
        self,
        mcp_client=None,
        executor=None,
        broadcast_fn: Optional[Callable] = None,
    ):
        """Inject external dependencies from main.py."""
        self._mcp_client = mcp_client
        self._executor = executor
        self._broadcast_fn = broadcast_fn

    # ── Project CRUD ─────────────────────────────────────────

    def create_project(
        self,
        name: str,
        input_option: str = "vendor_pack",
        preset: str = "preview",
        base_dir: str = "",
    ) -> DroneProject:
        """Create a new Drone2Twin project with standard folder structure."""
        project = DroneProject(
            name=name,
            input_option=InputOption(input_option),
            preset=Preset(preset),
        )

        # Determine project base directory
        if base_dir:
            project.base_dir = base_dir
        elif config.DRONE_PROJECTS_DIR:
            project.base_dir = str(Path(config.DRONE_PROJECTS_DIR) / name)
        else:
            project.base_dir = str(self._data_dir / name)

        # Create standard folder structure
        base = Path(project.base_dir)
        for subdir in PROJECT_DIRS:
            (base / subdir).mkdir(parents=True, exist_ok=True)

        # Save project config
        self._projects[project.id] = project
        self._save_project(project)

        logger.info("Created project '%s' (id=%s) at %s", name, project.id, project.base_dir)
        return project

    def get_project(self, project_id: str) -> Optional[DroneProject]:
        """Get project by ID."""
        return self._projects.get(project_id)

    def list_projects(self) -> list[dict]:
        """List all projects as dicts."""
        return [p.to_dict() for p in sorted(
            self._projects.values(),
            key=lambda p: p.created_at,
            reverse=True,
        )]

    def delete_project(self, project_id: str) -> bool:
        """Delete a project (metadata only, does not remove files)."""
        if project_id in self._projects:
            del self._projects[project_id]
            meta_file = self._data_dir / f"{project_id}.json"
            if meta_file.exists():
                meta_file.unlink()
            return True
        return False

    # ── Pipeline execution ───────────────────────────────────

    async def run_pipeline(
        self,
        project_id: str,
        *,
        progress_cb: Optional[Callable] = None,
    ) -> DroneProject:
        """Run full pipeline based on input option.

        Option A (vendor_pack): QA → Optimize → Unity Import → WebGL Build
        Option B (raw_images):  QA → Reconstruct → Optimize → Unity Import → WebGL Build
        """
        project = self._projects.get(project_id)
        if not project:
            raise ValueError(f"Project '{project_id}' not found")

        stages: list[PipelineStage]
        if project.input_option == InputOption.OBJ_FOLDER:
            # OBJ tiles: QA → direct Unity Import (skip Recon/Optimize)
            stages = [
                PipelineStage.INGEST_QA,
                PipelineStage.UNITY_IMPORT,
            ]
        elif project.input_option == InputOption.RAW_IMAGES:
            stages = [
                PipelineStage.INGEST_QA,
                PipelineStage.RECONSTRUCTION,
                PipelineStage.OPTIMIZATION,
                PipelineStage.UNITY_IMPORT,
                PipelineStage.WEBGL_BUILD,
            ]
        else:
            stages = [
                PipelineStage.INGEST_QA,
                PipelineStage.OPTIMIZATION,
                PipelineStage.UNITY_IMPORT,
                PipelineStage.WEBGL_BUILD,
            ]

        total = len(stages)
        for i, stage in enumerate(stages):
            await self._broadcast("drone_pipeline_progress", {
                "project_id": project_id,
                "stage": stage.value,
                "progress": i / total,
                "message": f"Stage {i + 1}/{total}: {stage.value}",
            })

            try:
                await self.run_stage(project_id, stage, progress_cb=progress_cb)
            except Exception as e:
                project.stage = PipelineStage.FAILED
                project.error = str(e)
                self._save_project(project)
                await self._broadcast("drone_pipeline_failed", {
                    "project_id": project_id,
                    "stage": stage.value,
                    "error": str(e),
                })
                logger.error("Pipeline failed at %s: %s", stage.value, e)
                return project

        project.stage = PipelineStage.COMPLETED
        project.updated_at = time.time()
        self._save_project(project)

        await self._broadcast("drone_pipeline_complete", {
            "project_id": project_id,
            "stages_completed": total,
        })

        logger.info("Pipeline complete for project '%s'", project.name)
        return project

    async def run_stage(
        self,
        project_id: str,
        stage: PipelineStage,
        *,
        progress_cb: Optional[Callable] = None,
    ) -> DroneProject:
        """Run a single pipeline stage."""
        project = self._projects.get(project_id)
        if not project:
            raise ValueError(f"Project '{project_id}' not found")

        project.stage = stage
        project.updated_at = time.time()
        self._save_project(project)

        handlers = {
            PipelineStage.INGEST_QA: self._run_ingest_qa,
            PipelineStage.RECONSTRUCTION: self._run_reconstruction,
            PipelineStage.OPTIMIZATION: self._run_optimization,
            PipelineStage.UNITY_IMPORT: self._run_unity_import,
            PipelineStage.WEBGL_BUILD: self._run_webgl_build,
            PipelineStage.DEPLOY: self._run_deploy,
        }

        handler = handlers.get(stage)
        if handler is None:
            raise ValueError(f"No handler for stage '{stage.value}'")

        await handler(project, progress_cb=progress_cb)
        self._save_project(project)

        await self._broadcast("drone_stage_complete", {
            "project_id": project_id,
            "stage": stage.value,
        })

        return project

    # ── Stage handlers ───────────────────────────────────────

    async def _run_ingest_qa(self, project: DroneProject, **kwargs):
        """Run Ingest QA analysis."""
        report = await asyncio.to_thread(
            self._ingest_qa.analyze_pack, project.base_dir
        )
        project.qa_report = report
        project.artifacts["ingest_qa"] = []

        # Auto-detect input option from QA
        if report.input_option:
            project.input_option = InputOption(report.input_option)

        # Save report file
        report_path = Path(project.base_dir) / "reports" / "ingest_qa.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)
        project.artifacts["ingest_qa"].append(str(report_path))

        logger.info("IngestQA complete: score=%d, option=%s", report.score, report.input_option)

    async def _run_reconstruction(self, project: DroneProject, **kwargs):
        """Run 3D reconstruction (Option B only)."""
        from .recon_engines.colmap_adapter import ColmapAdapter

        engine_name = config.RECON_ENGINE.lower()
        if engine_name == "colmap":
            engine = ColmapAdapter()
        else:
            raise ValueError(f"Unsupported reconstruction engine: {engine_name}")

        if not engine.is_available:
            logger.warning(
                "Reconstruction engine '%s' not available — skipping with warning",
                engine.name,
            )
            project.recon_report = ReconReport(
                engine=engine.name,
                preset=project.preset.value,
                warnings=[f"{engine.name} not installed — reconstruction skipped"],
            )
            return

        progress_cb = kwargs.get("progress_cb")
        report = await engine.run(
            project.base_dir,
            project.preset,
            progress_cb=progress_cb,
        )
        project.recon_report = report

        # Collect artifacts
        artifacts = engine.get_artifacts(project.base_dir)
        project.artifacts["reconstruction"] = list(artifacts.values())

        # Save report
        report_path = Path(project.base_dir) / "reports" / "recon_report.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)

    async def _run_optimization(self, project: DroneProject, **kwargs):
        """Run mesh optimization (Blender CLI or stub)."""
        base = Path(project.base_dir)

        # Find input mesh
        input_mesh = self._find_input_mesh(project)
        if not input_mesh:
            project.optimize_report = OptimizeReport(
                warnings=["No mesh file found for optimization"],
            )
            return

        output_dir = str(base / "work" / "optimize")
        progress_cb = kwargs.get("progress_cb")

        report = await self._optimizer.optimize(
            input_mesh, output_dir, project.preset, progress_cb=progress_cb,
        )
        project.optimize_report = report
        project.artifacts["optimization"] = report.output_files

        # Save report
        report_path = base / "reports" / "optimize_report.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)

    async def _run_unity_import(self, project: DroneProject, **kwargs):
        """Generate and execute Unity import plan via MCP."""
        # Delegate to OBJ tile handler if applicable
        if project.input_option == InputOption.OBJ_FOLDER:
            await self._run_unity_import_obj_tiles(project, **kwargs)
            return

        from .unity_import_planner import generate_import_plan

        # Find optimized GLB files (or original mesh)
        base = Path(project.base_dir)
        optimize_dir = base / "work" / "optimize"
        glb_paths = []

        if optimize_dir.is_dir():
            for f in optimize_dir.iterdir():
                if f.suffix.lower() in {".glb", ".gltf", ".fbx", ".obj"}:
                    glb_paths.append(str(f))

        if not glb_paths:
            # Fallback: try vendor/ or raw mesh
            mesh = self._find_input_mesh(project)
            if mesh:
                glb_paths = [mesh]

        if not glb_paths:
            logger.warning("No mesh files found for Unity import")
            return

        # Generate plan
        plan = generate_import_plan(glb_paths)
        project.artifacts["unity_import"] = [str(base / "work" / "unity")]

        # Execute via MCP executor (if available)
        if self._executor and self._mcp_client:
            import uuid
            job_id = uuid.uuid4().hex[:8]

            try:
                result = await self._executor.execute(
                    job_id=job_id,
                    command=f"Drone2Twin Unity Import: {project.name}",
                    plan=plan,
                    method="drone_pipeline",
                )
                project.artifacts["unity_import_result"] = {
                    "job_id": job_id,
                    "status": result.status.value if hasattr(result.status, "value") else str(result.status),
                }
                logger.info("Unity import executed: job_id=%s", job_id)
            except Exception as e:
                logger.error("Unity import failed: %s", e)
                raise
        else:
            # Store plan for manual approval
            project.artifacts["unity_import_plan"] = plan
            logger.info("Unity import plan generated (no MCP — stored for manual approval)")

    async def _run_unity_import_obj_tiles(self, project: DroneProject, **kwargs):
        """Import OBJ tiles sequentially with per-tile progress."""
        from .unity_import_planner import generate_obj_tile_import_plan
        from .obj_folder_scanner import OBJFolderScanner

        # Get tiles from QA report or scan directly
        tiles = []
        if project.qa_report and project.qa_report.obj_tiles:
            tiles = project.qa_report.obj_tiles
        else:
            scanner = OBJFolderScanner()
            tile_infos = scanner.scan(project.base_dir)
            tiles = [t.to_dict() for t in tile_infos]

        if not tiles:
            logger.warning("No OBJ tiles found for import")
            return

        total = len(tiles)
        results = []
        failed = []

        for i, tile in enumerate(tiles):
            tile_name = tile.get("name", f"tile_{i}")
            size_mb = tile.get("size_mb", 0)

            # Broadcast per-tile progress
            await self._broadcast("drone_tile_progress", {
                "project_id": project.id,
                "tile_index": i,
                "total": total,
                "tile_name": tile_name,
                "size_mb": size_mb,
                "message": f"Importing tile {i + 1}/{total}: {tile_name} ({size_mb:.1f} MB)",
            })

            # Generate plan for this tile
            plan = generate_obj_tile_import_plan(
                tile, is_first_tile=(i == 0),
            )

            # Execute via MCP
            if self._executor and self._mcp_client:
                import uuid
                job_id = uuid.uuid4().hex[:8]

                try:
                    result = await asyncio.to_thread(
                        lambda p=plan, j=job_id: None  # placeholder for sync call
                    )
                    # Actually execute async
                    result = await self._executor.execute(
                        job_id=job_id,
                        command=f"CityTile Import: {tile_name}",
                        plan=plan,
                        method="drone_pipeline",
                    )
                    results.append({
                        "tile": tile_name,
                        "job_id": job_id,
                        "status": "ok",
                    })
                    logger.info(
                        "Tile %d/%d imported: %s (job=%s)",
                        i + 1, total, tile_name, job_id,
                    )
                except Exception as e:
                    logger.error("Tile %s import failed: %s", tile_name, e)
                    failed.append({"tile": tile_name, "error": str(e)})
                    # Continue with next tile
                    continue
            else:
                # No MCP — store plan
                results.append({
                    "tile": tile_name,
                    "plan": plan,
                    "status": "plan_only",
                })

        # Save results
        project.artifacts["unity_import"] = results
        if failed:
            project.artifacts["unity_import_failed"] = failed

        # Broadcast completion
        await self._broadcast("drone_tiles_complete", {
            "project_id": project.id,
            "total": total,
            "imported": len(results),
            "failed": len(failed),
            "message": f"OBJ tile import complete: {len(results)}/{total} tiles imported"
            + (f" ({len(failed)} failed)" if failed else ""),
        })

        # Save scene
        if self._executor and self._mcp_client and results:
            try:
                import uuid
                save_plan = {
                    "project": "My project",
                    "scene": config.DEFAULT_SCENE,
                    "description": "Save scene after CityTile import",
                    "actions": [{"type": "save_scene"}],
                }
                await self._executor.execute(
                    job_id=uuid.uuid4().hex[:8],
                    command="Save scene after CityTile import",
                    plan=save_plan,
                    method="drone_pipeline",
                )
            except Exception as e:
                logger.warning("Scene save after tile import failed: %s", e)

        logger.info(
            "OBJ tile import complete: %d/%d tiles, %d failed",
            len(results), total, len(failed),
        )

    async def _run_webgl_build(self, project: DroneProject, **kwargs):
        """Run WebGL build using existing webgl_builder."""
        from ..webgl_builder import generate_build_plan

        base = Path(project.base_dir)
        output_path = str(base / "work" / "webgl")

        plan = generate_build_plan(output_path, include_setup=True)

        if self._executor and self._mcp_client:
            import uuid
            job_id = uuid.uuid4().hex[:8]

            try:
                result = await self._executor.execute(
                    job_id=job_id,
                    command=f"Drone2Twin WebGL Build: {project.name}",
                    plan=plan,
                    method="drone_pipeline",
                )
                project.artifacts["webgl_build"] = [output_path]

                # Generate performance report
                perf = self._perf_reporter.analyze_build(output_path)
                project.perf_report = perf
                self._perf_reporter.generate_report_file(
                    output_path,
                    perf,
                    str(base / "reports"),
                )
            except Exception as e:
                logger.error("WebGL build failed: %s", e)
                raise
        else:
            project.artifacts["webgl_build_plan"] = plan
            logger.info("WebGL build plan generated (no MCP — stored for manual approval)")

    async def _run_deploy(self, project: DroneProject, **kwargs):
        """Deploy WebGL build to nginx directory."""
        base = Path(project.base_dir)
        build_dir = str(base / "work" / "webgl")

        if not self._deployer.is_configured:
            logger.warning("NGINX_DEPLOY_DIR not configured — skipping deployment")
            return

        result = self._deployer.deploy(build_dir)
        project.artifacts["deploy"] = result

        # Smoke test if URL is derivable
        # (would need server URL configuration — skip for now)

        logger.info("Deployment: %s", result)

    # ── Helpers ──────────────────────────────────────────────

    def _find_input_mesh(self, project: DroneProject) -> Optional[str]:
        """Find the primary mesh file for the project."""
        base = Path(project.base_dir)

        # Priority order: recon output → vendor → raw
        search_dirs = [
            base / "work" / "recon",
            base / "vendor",
            base,
        ]
        mesh_exts = {".glb", ".gltf", ".fbx", ".obj", ".ply"}

        for search_dir in search_dirs:
            if not search_dir.is_dir():
                continue
            for f in search_dir.iterdir():
                if f.suffix.lower() in mesh_exts:
                    return str(f)

        return None

    async def _broadcast(self, event: str, data: dict):
        """Broadcast event via WebSocket (if available)."""
        if self._broadcast_fn:
            try:
                await self._broadcast_fn(event, data)
            except Exception as e:
                logger.debug("Broadcast failed: %s", e)

    # ── Persistence ──────────────────────────────────────────

    def _save_project(self, project: DroneProject):
        """Save project metadata to JSON file."""
        path = self._data_dir / f"{project.id}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(project.to_dict(), f, indent=2, ensure_ascii=False)

    def _load_projects(self):
        """Load all projects from data directory."""
        if not self._data_dir.is_dir():
            return
        for f in self._data_dir.glob("*.json"):
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                project = DroneProject.from_dict(data)
                self._projects[project.id] = project
            except Exception as e:
                logger.warning("Failed to load project %s: %s", f.name, e)

    def get_reports(self, project_id: str) -> dict:
        """Get all reports for a project."""
        project = self._projects.get(project_id)
        if not project:
            return {}

        reports = {}
        if project.qa_report:
            reports["ingest_qa"] = project.qa_report.to_dict()
        if project.recon_report:
            reports["reconstruction"] = project.recon_report.to_dict()
        if project.optimize_report:
            reports["optimization"] = project.optimize_report.to_dict()
        if project.perf_report:
            reports["performance"] = project.perf_report.to_dict()
        return reports
