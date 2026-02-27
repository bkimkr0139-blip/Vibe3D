"""Data models for the Drone2Twin pipeline.

Defines project state, pipeline stages, QA/optimize reports, and artifacts.
"""

import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Optional


# ── Enums ───────────────────────────────────────────────────


class InputOption(str, Enum):
    """How source data is provided."""
    VENDOR_PACK = "vendor_pack"   # Option A: pre-processed mesh+textures from vendor
    RAW_IMAGES = "raw_images"     # Option B: raw drone/camera images
    OBJ_FOLDER = "obj_folder"    # Option C: OBJ tile folder (Skyline etc.)


class PipelineStage(str, Enum):
    """Pipeline execution stages."""
    CREATED = "created"
    INGEST_QA = "ingest_qa"
    RECONSTRUCTION = "reconstruction"   # Option B only
    OPTIMIZATION = "optimization"
    UNITY_IMPORT = "unity_import"
    WEBGL_BUILD = "webgl_build"
    DEPLOY = "deploy"
    COMPLETED = "completed"
    FAILED = "failed"


class Preset(str, Enum):
    """Quality/speed presets."""
    PREVIEW = "preview"           # fast, medium quality (same-day check)
    PRODUCTION = "production"     # slow, highest quality (overnight batch)


# ── OBJ Tile Info ────────────────────────────────────────────


@dataclass
class OBJTileInfo:
    """Info about a single OBJ tile from a city-view tile set."""
    name: str = ""
    row: int = 0
    col: int = 0
    obj_path: str = ""
    mtl_path: str = ""
    texture_paths: list[str] = field(default_factory=list)
    size_mb: float = 0.0
    vertex_count: int = 0
    face_count: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


# ── Reports ─────────────────────────────────────────────────


@dataclass
class QAReport:
    """Ingest quality analysis report."""
    score: int = 0                              # 0-100 quality score
    input_option: str = ""                      # detected input option
    image_count: int = 0
    avg_resolution: str = ""                    # e.g. "4000x3000"
    blur_count: int = 0                         # number of blurry images
    exif_gps_missing: int = 0                   # images without GPS
    overlap_estimate: str = ""                  # "good" / "warning" / "insufficient"
    gcp_available: bool = False
    mesh_files: list[str] = field(default_factory=list)
    texture_files: list[str] = field(default_factory=list)
    total_size_mb: float = 0.0
    warnings: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    obj_tiles: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ReconReport:
    """Reconstruction stage report."""
    engine: str = ""                            # "colmap" / "realitycapture" / etc.
    preset: str = ""
    image_count: int = 0
    tie_points: int = 0
    avg_reprojection_error: float = 0.0
    dense_points: int = 0
    mesh_vertices: int = 0
    mesh_faces: int = 0
    coordinate_system: str = ""
    elapsed_seconds: float = 0.0
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class OptimizeReport:
    """Mesh optimization report."""
    input_polycount: int = 0
    output_polycounts: dict = field(default_factory=dict)   # {"lod0": N, "lod1": N, "lod2": N}
    texture_sizes: list[str] = field(default_factory=list)  # ["2048x2048", ...]
    decimation_ratio: float = 0.0
    output_files: list[str] = field(default_factory=list)
    blender_available: bool = False
    elapsed_seconds: float = 0.0
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PerfReport:
    """WebGL performance analysis report."""
    total_size_mb: float = 0.0
    wasm_size_mb: float = 0.0
    data_size_mb: float = 0.0
    js_size_mb: float = 0.0
    texture_count: int = 0
    lod_files: int = 0
    estimated_load_time_3g: str = ""            # e.g. "45s"
    estimated_load_time_4g: str = ""            # e.g. "12s"
    estimated_load_time_wifi: str = ""          # e.g. "3s"
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# ── Project ─────────────────────────────────────────────────


@dataclass
class DroneProject:
    """A Drone2Twin pipeline project."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str = ""
    input_option: InputOption = InputOption.VENDOR_PACK
    preset: Preset = Preset.PREVIEW
    base_dir: str = ""                          # project root folder
    stage: PipelineStage = PipelineStage.CREATED
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    # Reports — populated as pipeline progresses
    qa_report: Optional[QAReport] = None
    recon_report: Optional[ReconReport] = None
    optimize_report: Optional[OptimizeReport] = None
    perf_report: Optional[PerfReport] = None

    # Artifacts — stage → list of file paths
    artifacts: dict = field(default_factory=dict)

    # Error info (if stage == FAILED)
    error: Optional[str] = None

    def to_dict(self) -> dict:
        """Serialize for JSON storage and API response."""
        d = {
            "id": self.id,
            "name": self.name,
            "input_option": self.input_option.value,
            "preset": self.preset.value,
            "base_dir": self.base_dir,
            "stage": self.stage.value,
            "run_id": self.run_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "artifacts": self.artifacts,
            "error": self.error,
        }
        if self.qa_report:
            d["qa_report"] = self.qa_report.to_dict()
        if self.recon_report:
            d["recon_report"] = self.recon_report.to_dict()
        if self.optimize_report:
            d["optimize_report"] = self.optimize_report.to_dict()
        if self.perf_report:
            d["perf_report"] = self.perf_report.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "DroneProject":
        """Deserialize from JSON."""
        proj = cls(
            id=d.get("id", uuid.uuid4().hex[:12]),
            name=d.get("name", ""),
            input_option=InputOption(d.get("input_option", "vendor_pack")),
            preset=Preset(d.get("preset", "preview")),
            base_dir=d.get("base_dir", ""),
            stage=PipelineStage(d.get("stage", "created")),
            run_id=d.get("run_id", ""),
            created_at=d.get("created_at", time.time()),
            updated_at=d.get("updated_at", time.time()),
            artifacts=d.get("artifacts", {}),
            error=d.get("error"),
        )
        if "qa_report" in d and d["qa_report"]:
            proj.qa_report = QAReport(**d["qa_report"])
        if "recon_report" in d and d["recon_report"]:
            proj.recon_report = ReconReport(**d["recon_report"])
        if "optimize_report" in d and d["optimize_report"]:
            proj.optimize_report = OptimizeReport(**d["optimize_report"])
        if "perf_report" in d and d["perf_report"]:
            proj.perf_report = PerfReport(**d["perf_report"])
        return proj


# ── Standard folder structure ────────────────────────────────

PROJECT_DIRS = [
    "raw/images",
    "raw/flightlog",
    "raw/gcp",
    "vendor",
    "work/recon",
    "work/optimize",
    "work/unity",
    "work/webgl",
    "config",
    "reports",
]
