# mesh_edit_models.py
# Data models for tile-level mesh editing (Blender headless batch).

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ═══════════════════════════════════════════════════════════════
# Enums
# ═══════════════════════════════════════════════════════════════

class EditPreset(str, Enum):
    """Available editing presets (P0-1 ~ P0-5 from dev instruction)."""
    CLEAN_NOISE = "clean_noise"
    DECIMATE_TO_TARGET = "decimate_to_target"
    GENERATE_LODS = "generate_lods"
    GENERATE_COLLIDER_PROXY = "generate_collider_proxy"
    PACK_FOR_UNITY = "pack_for_unity"


class EditJobStage(str, Enum):
    """Processing stages within a single edit job."""
    QUEUED = "queued"
    IMPORT_TILE = "import_tile"
    CLEANUP = "cleanup"
    DECIMATE = "decimate"
    COLLIDER_PROXY = "collider_proxy"
    LODS = "lods"
    EXPORT = "export"
    PACKAGE = "package"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EditJobStatus(str, Enum):
    """High-level job lifecycle status."""
    PENDING = "pending"
    RUNNING = "running"
    PREVIEW_READY = "preview_ready"
    APPLYING = "applying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ═══════════════════════════════════════════════════════════════
# Dataclasses
# ═══════════════════════════════════════════════════════════════

@dataclass
class MeshStats:
    """Triangle/vertex/material stats for a mesh."""
    triangles: int = 0
    vertices: int = 0
    materials: int = 0
    texture_count: int = 0
    size_bytes: int = 0


@dataclass
class EditManifest:
    """Per-version manifest (manifest.json inside tiles_edit/tile_{x}_{y}/v{nnnn}/)."""
    tile_id: str = ""
    version: int = 0
    base_version: str = "raw"
    preset: str = ""
    params: dict = field(default_factory=dict)
    input_stats: dict = field(default_factory=dict)
    output_stats: dict = field(default_factory=dict)
    files: dict = field(default_factory=dict)  # {"LOD0": "tile_LOD0.fbx", ...}
    quality_flags: dict = field(default_factory=dict)
    created_at: float = 0.0
    tool_versions: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "tile_id": self.tile_id,
            "version": self.version,
            "base_version": self.base_version,
            "preset": self.preset,
            "params": self.params,
            "input_stats": self.input_stats,
            "output_stats": self.output_stats,
            "files": self.files,
            "quality_flags": self.quality_flags,
            "created_at": self.created_at,
            "tool_versions": self.tool_versions,
        }


@dataclass
class EditJobResult:
    """Full state of an edit job (in-memory + persisted to SQLite)."""
    job_id: str = ""
    tile_id: str = ""
    preset: str = ""
    status: EditJobStatus = EditJobStatus.PENDING
    stage: EditJobStage = EditJobStage.QUEUED
    progress_pct: float = 0.0
    version: int = 0
    project_dir: str = ""

    # Before/after stats
    original: MeshStats = field(default_factory=MeshStats)
    result: MeshStats = field(default_factory=MeshStats)

    # LOD stats
    lod0_triangles: int = 0
    lod1_triangles: int = 0
    lod2_triangles: int = 0
    collider_triangles: int = 0

    # Output paths
    output_dir: str = ""
    lod_files: list[str] = field(default_factory=list)
    collider_file: str = ""
    manifest: EditManifest = field(default_factory=EditManifest)

    # Timing
    started_at: float = 0.0
    completed_at: float = 0.0
    duration_s: float = 0.0

    # Error
    error: Optional[str] = None
    warnings: list[str] = field(default_factory=list)

    # Params used
    params: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "tile_id": self.tile_id,
            "preset": self.preset,
            "status": self.status.value if isinstance(self.status, EditJobStatus) else self.status,
            "stage": self.stage.value if isinstance(self.stage, EditJobStage) else self.stage,
            "progress_pct": round(self.progress_pct, 1),
            "version": self.version,
            "original": {
                "triangles": self.original.triangles,
                "vertices": self.original.vertices,
                "size_bytes": self.original.size_bytes,
            },
            "result": {
                "triangles": self.result.triangles,
                "vertices": self.result.vertices,
                "size_bytes": self.result.size_bytes,
            },
            "lod0_triangles": self.lod0_triangles,
            "lod1_triangles": self.lod1_triangles,
            "lod2_triangles": self.lod2_triangles,
            "collider_triangles": self.collider_triangles,
            "output_dir": self.output_dir,
            "lod_files": self.lod_files,
            "collider_file": self.collider_file,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_s": round(self.duration_s, 2),
            "error": self.error,
            "warnings": self.warnings,
            "params": self.params,
        }


# ═══════════════════════════════════════════════════════════════
# Default parameters per preset
# ═══════════════════════════════════════════════════════════════

DEFAULT_PARAMS: dict[str, dict] = {
    "clean_noise": {
        "min_fragment_area": 0.5,   # m² — loose parts smaller than this are deleted
        "remove_degenerate": True,  # remove zero-area / collapsed faces
    },
    "decimate_to_target": {
        "target_triangles": 100000,
        "preserve_boundaries": True,
    },
    "generate_lods": {
        "lod_ratios": [1.0, 0.4, 0.15],  # LOD0=100%, LOD1=40%, LOD2=15%
        "export_format": "fbx",
    },
    "generate_collider_proxy": {
        "target_triangles": 50000,
        "min_fragment_area": 1.0,
    },
    "pack_for_unity": {
        "target_triangles_lod0": 600000,
        "lod_ratios": [1.0, 0.35, 0.10],
        "collider_target_triangles": 50000,
        "min_fragment_area": 0.5,
        "preserve_boundaries": True,
        "export_format": "fbx",
    },
}
