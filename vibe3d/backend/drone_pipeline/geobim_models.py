"""GeoBIM data models — building candidates extracted from OBJ tile meshes.

Follows the GeoBIM Dev Instruction v1.0 schema (Appendix A).
Fields: building_id, tile_id, centroid, bbox_aabb, bbox_obb, height_min/max/avg,
footprint, area_2d, surface_area_approx, volume_approx, confidence, tags.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ExtractionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class PipelineStage(str, Enum):
    """Batch pipeline stages (Section 1.3)."""
    INGEST_VALIDATE = "00_ingest_validate"
    GENERATE_COLLIDER = "10_generate_collider_proxy"
    BUILDING_SEGMENTATION = "20_building_segmentation"
    ATTRIBUTE_EXTRACTION = "30_geobim_attribute_extraction"
    EXPORT_ASSETS = "40_export_assets_for_unity"


@dataclass
class OBBData:
    """Oriented Bounding Box (PCA-based approximation)."""
    center: list[float] = field(default_factory=lambda: [0, 0, 0])
    axes: list[list[float]] = field(default_factory=lambda: [[1,0,0],[0,1,0],[0,0,1]])
    extents: list[float] = field(default_factory=lambda: [0, 0, 0])

    def to_dict(self) -> dict:
        return {
            "center": [round(v, 3) for v in self.center],
            "axes": [[round(c, 4) for c in ax] for ax in self.axes],
            "extents": [round(v, 3) for v in self.extents],
        }


@dataclass
class SensorParams:
    """Visibility sensor model parameters (Section 4.8)."""
    position: list[float] = field(default_factory=lambda: [0, 0, 0])
    height: float = 3.0
    yaw: float = 0.0         # degrees
    pitch: float = 0.0       # degrees
    hfov: float = 90.0       # horizontal FOV degrees
    vfov: float = 60.0       # vertical FOV degrees
    max_distance: float = 100.0
    yaw_steps: int = 36
    pitch_steps: int = 18

    def to_dict(self) -> dict:
        return {
            "position": [round(v, 2) for v in self.position],
            "height": self.height, "yaw": self.yaw, "pitch": self.pitch,
            "hfov": self.hfov, "vfov": self.vfov,
            "max_distance": self.max_distance,
            "yaw_steps": self.yaw_steps, "pitch_steps": self.pitch_steps,
        }


@dataclass
class RoofPlane:
    """A detected roof plane segment (Section 3.4E)."""
    normal: list[float] = field(default_factory=lambda: [0, 1, 0])
    d: float = 0.0           # plane distance from origin
    area: float = 0.0        # m²
    tilt_deg: float = 0.0    # angle from horizontal
    azimuth_deg: float = 0.0 # compass direction the plane faces

    def to_dict(self) -> dict:
        return {
            "normal": [round(v, 4) for v in self.normal],
            "d": round(self.d, 3),
            "area": round(self.area, 2),
            "tilt_deg": round(self.tilt_deg, 1),
            "azimuth_deg": round(self.azimuth_deg, 1),
        }


@dataclass
class BuildingCandidate:
    """A building detected by the GeoBIM extractor (matches Appendix A schema)."""
    id: str = ""
    tile_name: str = ""
    label: str = ""
    # Heights
    height: float = 0.0           # height_max - ground_elevation (legacy compat)
    height_min: float = 0.0
    height_max: float = 0.0
    height_avg: float = 0.0
    ground_elevation: float = 0.0
    roof_elevation: float = 0.0
    # Geometry
    footprint_area: float = 0.0   # area_2d
    surface_area_approx: float = 0.0
    volume_approx: float = 0.0
    bbox_min: list[float] = field(default_factory=lambda: [0, 0, 0])
    bbox_max: list[float] = field(default_factory=lambda: [0, 0, 0])
    obb: Optional[OBBData] = None
    footprint: list[list[float]] = field(default_factory=list)  # [[x,z], ...] convex hull
    centroid: list[float] = field(default_factory=lambda: [0, 0, 0])
    # Roof planes (Section 3.4E)
    roof_planes: list[RoofPlane] = field(default_factory=list)
    # Mesh stats
    vertex_count: int = 0
    face_count: int = 0
    # Quality
    confidence: float = 0.0
    cluster_id: int = -1
    tags: list[str] = field(default_factory=lambda: ["building"])

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "tile_name": self.tile_name,
            "label": self.label,
            "height": round(self.height, 2),
            "height_min": round(self.height_min, 2),
            "height_max": round(self.height_max, 2),
            "height_avg": round(self.height_avg, 2),
            "ground_elevation": round(self.ground_elevation, 2),
            "roof_elevation": round(self.roof_elevation, 2),
            "footprint_area": round(self.footprint_area, 2),
            "area_2d": round(self.footprint_area, 2),
            "surface_area_approx": round(self.surface_area_approx, 2),
            "volume_approx": round(self.volume_approx, 2),
            "bbox_min": [round(v, 2) for v in self.bbox_min],
            "bbox_max": [round(v, 2) for v in self.bbox_max],
            "bbox_aabb": {
                "min": [round(v, 2) for v in self.bbox_min],
                "max": [round(v, 2) for v in self.bbox_max],
            },
            "obb": self.obb.to_dict() if self.obb else None,
            "footprint": [[round(c, 2) for c in pt] for pt in self.footprint],
            "centroid": [round(v, 2) for v in self.centroid],
            "roof_planes": [rp.to_dict() for rp in self.roof_planes] if self.roof_planes else [],
            "vertex_count": self.vertex_count,
            "face_count": self.face_count,
            "confidence": round(self.confidence, 3),
            "cluster_id": self.cluster_id,
            "tags": self.tags,
        }
        return d

    def to_jsonl(self) -> dict:
        """JSONL-compatible dict matching dev instruction BuildingIndex spec."""
        return {
            "building_id": self.id,
            "tile_id": self.tile_name,
            "centroid": [round(v, 3) for v in self.centroid],
            "bbox_aabb": {
                "min": [round(v, 3) for v in self.bbox_min],
                "max": [round(v, 3) for v in self.bbox_max],
            },
            "bbox_obb": self.obb.to_dict() if self.obb else None,
            "height_min": round(self.height_min, 2),
            "height_max": round(self.height_max, 2),
            "height_avg": round(self.height_avg, 2),
            "footprint": [[round(c, 3) for c in pt] for pt in self.footprint],
            "area_2d": round(self.footprint_area, 2),
            "surface_area_approx": round(self.surface_area_approx, 2),
            "volume_approx": round(self.volume_approx, 2),
            "confidence": round(self.confidence, 3),
            "tags": self.tags,
            "roof_planes": [rp.to_dict() for rp in self.roof_planes] if self.roof_planes else [],
        }


@dataclass
class ColliderProxyResult:
    """Result of collider proxy generation for a tile."""
    tile_name: str = ""
    input_path: str = ""
    output_path: str = ""
    original_triangles: int = 0
    proxy_triangles: int = 0
    reduction_ratio: float = 0.0
    success: bool = False
    error: Optional[str] = None
    processing_time_s: float = 0.0

    def to_dict(self) -> dict:
        return {
            "tile_name": self.tile_name,
            "input_path": self.input_path,
            "output_path": self.output_path,
            "original_triangles": self.original_triangles,
            "proxy_triangles": self.proxy_triangles,
            "reduction_ratio": round(self.reduction_ratio, 4),
            "success": self.success,
            "error": self.error,
            "processing_time_s": round(self.processing_time_s, 2),
        }


@dataclass
class PipelineState:
    """State of the batch pipeline orchestrator."""
    current_stage: Optional[PipelineStage] = None
    stages_completed: list[str] = field(default_factory=list)
    tile_folder: str = ""
    export_folder: str = ""
    building_count: int = 0
    collider_count: int = 0
    error: Optional[str] = None
    is_running: bool = False
    progress_pct: float = 0.0

    def to_dict(self) -> dict:
        return {
            "current_stage": self.current_stage.value if self.current_stage else None,
            "stages_completed": self.stages_completed,
            "tile_folder": self.tile_folder,
            "export_folder": self.export_folder,
            "building_count": self.building_count,
            "collider_count": self.collider_count,
            "error": self.error,
            "is_running": self.is_running,
            "progress_pct": round(self.progress_pct, 1),
        }


@dataclass
class GeoBIMReport:
    """Summary report for a GeoBIM extraction run."""
    status: ExtractionStatus = ExtractionStatus.PENDING
    tile_count: int = 0
    tiles_processed: int = 0
    building_count: int = 0
    total_footprint_area: float = 0.0
    total_volume: float = 0.0
    avg_height: float = 0.0
    max_height: float = 0.0
    ground_plane_z: float = 0.0
    processing_time_s: float = 0.0
    error: Optional[str] = None
    buildings: list[BuildingCandidate] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "status": self.status.value,
            "tile_count": self.tile_count,
            "tiles_processed": self.tiles_processed,
            "building_count": self.building_count,
            "total_footprint_area": round(self.total_footprint_area, 2),
            "total_volume": round(self.total_volume, 2),
            "avg_height": round(self.avg_height, 2),
            "max_height": round(self.max_height, 2),
            "ground_plane_z": round(self.ground_plane_z, 2),
            "processing_time_s": round(self.processing_time_s, 2),
            "error": self.error,
        }
