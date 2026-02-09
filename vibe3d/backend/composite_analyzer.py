"""Composite file analysis engine for Vibe3D Unity Accelerator.

Analyzes multiple source files together to infer cross-file relationships,
scene structure, and generate unified Unity import/placement plans.
"""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .source_analyzer import (
    SourceAnalysis,
    analyze_file,
    MODEL_EXTENSIONS,
    TEXTURE_EXTENSIONS,
    DATA_EXTENSIONS,
    DRAWING_EXTENSIONS,
)

logger = logging.getLogger(__name__)


@dataclass
class CompositeAnalysis:
    """Result of analyzing multiple source files together."""

    files: list[SourceAnalysis] = field(default_factory=list)
    relationships: list[dict] = field(default_factory=list)
    scene_structure: dict = field(default_factory=dict)
    composite_plan: dict = field(default_factory=dict)
    summary: str = ""


# ── Relationship types ────────────────────────────────────────


def _basename_no_ext(path: str) -> str:
    return os.path.splitext(os.path.basename(path))[0].lower()


def _ext(path: str) -> str:
    return os.path.splitext(path)[1].lower()


def _infer_relationships(analyses: list[SourceAnalysis]) -> list[dict]:
    """Infer cross-file relationships from individual analyses."""
    relationships: list[dict] = []

    models = [a for a in analyses if a.file_type == "3d_model"]
    textures = [a for a in analyses if a.file_type == "texture"]
    data_files = [a for a in analyses if a.file_type == "data"]
    drawings = [a for a in analyses if a.file_type == "drawing"]

    # Model ↔ Texture matching (same base name)
    for model in models:
        model_base = _basename_no_ext(model.file_path)
        for tex in textures:
            tex_base = _basename_no_ext(tex.file_path)
            # Exact match or common suffixes (e.g., Tank_diffuse, Tank_normal)
            if tex_base == model_base or tex_base.startswith(model_base + "_"):
                relationships.append({
                    "type": "model_texture",
                    "source": model.file_path,
                    "target": tex.file_path,
                    "confidence": 0.9 if tex_base == model_base else 0.7,
                    "description": f"텍스처 '{os.path.basename(tex.file_path)}'가 모델 '{os.path.basename(model.file_path)}'에 매핑됨",
                })

    # Data ↔ Layout matching (CSV/JSON with position columns → placement info)
    for df in data_files:
        columns = df.metadata.get("columns", [])
        col_lower = [c.lower().strip() for c in columns]
        has_position = any(c in col_lower for c in ("x", "y", "z", "position", "pos_x", "pos_y", "pos_z"))
        has_name = any(c in col_lower for c in ("name", "id", "object", "item"))

        if has_position and has_name:
            # This data file likely contains placement information
            relationships.append({
                "type": "layout_data",
                "source": df.file_path,
                "confidence": 0.8,
                "description": f"배치 데이터 파일 — 위치 컬럼({', '.join(c for c in col_lower if c in ('x','y','z','position'))}) 감지",
            })
            # Link to models if names match
            for model in models:
                model_base = _basename_no_ext(model.file_path)
                relationships.append({
                    "type": "data_model",
                    "source": df.file_path,
                    "target": model.file_path,
                    "confidence": 0.5,
                    "description": f"데이터 → 모델 배치 가능",
                })

    # Drawing ↔ Model matching (layout references)
    for drawing in drawings:
        for model in models:
            relationships.append({
                "type": "drawing_model",
                "source": drawing.file_path,
                "target": model.file_path,
                "confidence": 0.4,
                "description": f"도면이 모델 배치 레이아웃 참조로 사용 가능",
            })
        for tex in textures:
            tex_base = _basename_no_ext(tex.file_path)
            drawing_base = _basename_no_ext(drawing.file_path)
            if drawing_base in tex_base or tex_base in drawing_base:
                relationships.append({
                    "type": "drawing_texture",
                    "source": drawing.file_path,
                    "target": tex.file_path,
                    "confidence": 0.6,
                    "description": f"도면의 렌더링된 이미지 버전으로 추정",
                })

    return relationships


def _build_scene_structure(
    analyses: list[SourceAnalysis],
    relationships: list[dict],
) -> dict:
    """Build a proposed scene hierarchy from analyses and relationships."""
    root_children: list[dict] = []
    used_files: set[str] = set()

    # Group model+texture pairs
    model_groups: list[dict] = []
    for rel in relationships:
        if rel["type"] == "model_texture":
            model_path = rel["source"]
            tex_path = rel["target"]
            # Find or create group
            existing = next((g for g in model_groups if g["model"] == model_path), None)
            if existing:
                existing["textures"].append(tex_path)
            else:
                model_groups.append({
                    "model": model_path,
                    "textures": [tex_path],
                })
            used_files.add(model_path)
            used_files.add(tex_path)

    # Models without textures
    for a in analyses:
        if a.file_type == "3d_model" and a.file_path not in used_files:
            model_groups.append({"model": a.file_path, "textures": []})
            used_files.add(a.file_path)

    # Convert groups to hierarchy nodes
    for i, group in enumerate(model_groups):
        model_name = _basename_no_ext(group["model"])
        node: dict = {
            "name": model_name,
            "type": "model_instance",
            "source": group["model"],
            "position": {"x": i * 3.0, "y": 0, "z": 0},
            "children": [],
        }
        for tex in group["textures"]:
            node["children"].append({
                "name": f"Mat_{_basename_no_ext(tex)}",
                "type": "material",
                "source": tex,
            })
        root_children.append(node)

    # Drawing files with vessel info → equipment nodes
    for a in analyses:
        if a.file_type == "drawing" and a.file_path not in used_files:
            vessel_info = a.metadata.get("vessel_info")
            if vessel_info:
                idx = len(root_children)
                # Position vessels in a line with spacing proportional to diameter
                diameter_m = vessel_info["diameter_mm"] / 1000.0
                height_m = vessel_info["height_m"]
                x_offset = idx * 5.0  # 5m spacing between vessels
                node = {
                    "name": vessel_info["name"],
                    "type": "vessel",
                    "source": a.file_path,
                    "vessel_info": vessel_info,
                    "position": {"x": x_offset, "y": height_m / 2.0, "z": 0},
                    "scale": {
                        "x": diameter_m,
                        "y": height_m,
                        "z": diameter_m,
                    },
                    "children": [],
                }
                root_children.append(node)
                used_files.add(a.file_path)
            else:
                # Drawing without vessel info → reference display node
                root_children.append({
                    "name": f"Drawing_{_basename_no_ext(a.file_path)}",
                    "type": "drawing_reference",
                    "source": a.file_path,
                    "position": {"x": len(root_children) * 5.0, "y": 1.0, "z": 0},
                })
                used_files.add(a.file_path)

    # Standalone textures → plane displays
    for a in analyses:
        if a.file_type == "texture" and a.file_path not in used_files:
            root_children.append({
                "name": f"Display_{_basename_no_ext(a.file_path)}",
                "type": "texture_display",
                "source": a.file_path,
                "position": {"x": len(root_children) * 3.0, "y": 1.5, "z": 0},
            })
            used_files.add(a.file_path)

    # Data files → config nodes
    for a in analyses:
        if a.file_type == "data" and a.file_path not in used_files:
            root_children.append({
                "name": f"Config_{_basename_no_ext(a.file_path)}",
                "type": "data_config",
                "source": a.file_path,
            })
            used_files.add(a.file_path)

    return {
        "name": "CompositeImport",
        "type": "root",
        "children": root_children,
    }


def _generate_composite_plan(
    analyses: list[SourceAnalysis],
    relationships: list[dict],
    scene_structure: dict,
) -> dict:
    """Generate a unified Unity action plan from the composite analysis."""
    actions: list[dict] = []

    # Create root empty object
    actions.append({
        "type": "create_empty",
        "name": scene_structure.get("name", "CompositeImport"),
        "position": {"x": 0, "y": 0, "z": 0},
    })

    parent_name = scene_structure.get("name", "CompositeImport")

    for child in scene_structure.get("children", []):
        if child["type"] == "model_instance":
            # Import model asset
            source = child["source"]
            filename = os.path.basename(source)
            ext = _ext(source)
            dest_folder = "Assets/Models"

            actions.append({
                "type": "import_asset",
                "source_path": source,
                "filename": filename,
                "destination": dest_folder,
            })

            # Import companion textures
            for mat_child in child.get("children", []):
                if mat_child["type"] == "material":
                    tex_file = os.path.basename(mat_child["source"])
                    actions.append({
                        "type": "import_asset",
                        "source_path": mat_child["source"],
                        "filename": tex_file,
                        "destination": "Assets/Textures",
                    })
                    # Create material
                    actions.append({
                        "type": "create_material",
                        "name": mat_child["name"],
                        "shader": "Universal Render Pipeline/Lit",
                    })

            # Create primitive placeholder (or instantiate if model imported)
            pos = child.get("position", {"x": 0, "y": 0, "z": 0})
            actions.append({
                "type": "create_primitive",
                "shape": "Cube",
                "name": child["name"],
                "parent": parent_name,
                "position": pos,
            })

        elif child["type"] == "vessel":
            # Create vessel from P&ID specs
            vessel_info = child.get("vessel_info", {})
            pos = child.get("position", {"x": 0, "y": 0, "z": 0})
            scale = child.get("scale", {"x": 1, "y": 1, "z": 1})
            vessel_name = child["name"]

            # Create vessel body (cylinder)
            actions.append({
                "type": "create_primitive",
                "shape": "Cylinder",
                "name": vessel_name,
                "parent": parent_name,
                "position": pos,
                "scale": scale,
            })

            # Apply material color based on vessel type
            # Use by_path to avoid name collisions with existing scene objects
            color_map = {
                "stainless": {"r": 0.8, "g": 0.82, "b": 0.85, "a": 1.0},
                "steel":     {"r": 0.75, "g": 0.75, "b": 0.78, "a": 1.0},
                "copper":    {"r": 0.72, "g": 0.45, "b": 0.2, "a": 1.0},
            }
            color_key = vessel_info.get("color", "stainless")
            color = color_map.get(color_key, color_map["stainless"])
            actions.append({
                "type": "apply_material",
                "target": f"{parent_name}/{vessel_name}",
                "search_method": "by_path",
                "color": color,
            })

            # Add label (small sphere on top as indicator)
            label_name = f"{vessel_name}_Label"
            label_y = pos["y"] + scale["y"] / 2 + 0.3
            actions.append({
                "type": "create_primitive",
                "shape": "Sphere",
                "name": label_name,
                "parent": vessel_name,
                "position": {"x": 0, "y": scale["y"] / 2 + 0.3, "z": 0},
                "scale": {"x": 0.15, "y": 0.15, "z": 0.15},
            })

        elif child["type"] == "drawing_reference":
            # Create placeholder for unrecognized drawings
            pos = child.get("position", {"x": 0, "y": 1, "z": 0})
            actions.append({
                "type": "create_primitive",
                "shape": "Cube",
                "name": child["name"],
                "parent": parent_name,
                "position": pos,
                "scale": {"x": 0.5, "y": 0.5, "z": 0.5},
            })

        elif child["type"] == "texture_display":
            # Import texture and create display plane
            source = child["source"]
            filename = os.path.basename(source)
            actions.append({
                "type": "import_asset",
                "source_path": source,
                "filename": filename,
                "destination": "Assets/Textures",
            })
            pos = child.get("position", {"x": 0, "y": 1.5, "z": 0})
            actions.append({
                "type": "create_primitive",
                "shape": "Plane",
                "name": child["name"],
                "parent": parent_name,
                "position": pos,
                "rotation": {"x": 90, "y": 0, "z": 0},
                "scale": {"x": 1, "y": 1, "z": 1},
            })

    return {
        "project": "My project",
        "scene": "bio-plants",
        "description": f"복합 임포트: {len(analyses)}개 파일",
        "actions": actions,
    }


def _generate_summary(
    analyses: list[SourceAnalysis],
    relationships: list[dict],
) -> str:
    """Generate a Korean language summary of the composite analysis."""
    type_counts: dict[str, int] = {}
    for a in analyses:
        type_counts[a.file_type] = type_counts.get(a.file_type, 0) + 1

    type_names = {
        "3d_model": "3D 모델",
        "texture": "텍스처",
        "data": "데이터",
        "drawing": "도면",
        "other": "기타",
    }

    parts = []
    for ft, count in type_counts.items():
        parts.append(f"{type_names.get(ft, ft)} {count}개")
    file_summary = ", ".join(parts)

    avg_score = sum(a.score for a in analyses) / len(analyses) if analyses else 0

    rel_count = len(relationships)
    rel_summary = f"파일 간 관계 {rel_count}개 감지" if rel_count else "파일 간 관계 없음"

    total_issues = sum(len(a.issues) for a in analyses)

    return (
        f"분석 완료: {file_summary} (평균 품질 점수: {avg_score:.0f}/100). "
        f"{rel_summary}. "
        f"총 이슈 {total_issues}개."
    )


# ── Public API ────────────────────────────────────────────────


def composite_analyze(
    file_paths: list[str],
    progress_callback=None,
) -> CompositeAnalysis:
    """Analyze multiple files together for cross-file relationships and scene structure.

    Args:
        file_paths: List of absolute or relative file paths.
        progress_callback: Optional callable(stage, detail, current, total) for progress.

    Returns:
        CompositeAnalysis with individual analyses, relationships,
        inferred scene structure, and a unified plan.
    """
    import time
    t0 = time.time()
    total_files = len(file_paths)
    logger.info("=== Composite analysis START: %d files ===", total_files)

    def _progress(stage: str, detail: str, current: int = 0, total: int = 0):
        logger.info("[Composite] %s: %s (%d/%d)", stage, detail, current, total)
        if progress_callback:
            try:
                progress_callback(stage, detail, current, total)
            except Exception:
                pass

    _progress("init", f"{total_files}개 파일 분석 시작", 0, total_files)

    # Step 1: Individual analysis
    analyses: list[SourceAnalysis] = []
    for i, fp in enumerate(file_paths):
        fname = os.path.basename(fp)
        _progress("file_analyze", f"파일 분석 중: {fname}", i + 1, total_files)
        a = analyze_file(fp)
        logger.info("  [%d/%d] %s → type=%s, score=%d", i + 1, total_files, fname, a.file_type, a.score)
        analyses.append(a)

    if not analyses:
        _progress("complete", "분석할 파일 없음", 0, 0)
        return CompositeAnalysis(summary="분석할 파일이 없습니다.")

    t1 = time.time()
    logger.info("[Composite] File analysis done in %.3fs", t1 - t0)

    # Step 2: Relationship inference
    _progress("relationships", "파일 간 관계 분석 중", 0, 0)
    relationships = _infer_relationships(analyses)
    logger.info("[Composite] Found %d relationships in %.3fs", len(relationships), time.time() - t1)
    for rel in relationships:
        logger.info("  Relationship: %s → %s (%s, confidence=%.1f)",
                     os.path.basename(rel.get("source", "")),
                     os.path.basename(rel.get("target", "")),
                     rel.get("type", ""), rel.get("confidence", 0))

    # Step 3: Scene structure
    _progress("scene_structure", "씬 구조 생성 중", 0, 0)
    t2 = time.time()
    scene_structure = _build_scene_structure(analyses, relationships)
    children_count = len(scene_structure.get("children", []))
    logger.info("[Composite] Scene structure built: %d root children in %.3fs", children_count, time.time() - t2)

    # Step 4: Composite plan
    _progress("plan_generation", "통합 플랜 생성 중", 0, 0)
    t3 = time.time()
    composite_plan = _generate_composite_plan(analyses, relationships, scene_structure)
    action_count = len(composite_plan.get("actions", []))
    logger.info("[Composite] Plan generated: %d actions in %.3fs", action_count, time.time() - t3)
    for i, action in enumerate(composite_plan.get("actions", [])):
        logger.info("  Action[%d]: type=%s, name=%s", i, action.get("type", "?"), action.get("name", action.get("target", "?")))

    # Step 5: Summary
    summary = _generate_summary(analyses, relationships)

    total_time = time.time() - t0
    logger.info("=== Composite analysis COMPLETE: %d files, %d relationships, %d actions, %.3fs ===",
                total_files, len(relationships), action_count, total_time)
    _progress("complete", f"분석 완료: {action_count}개 작업 생성 ({total_time:.1f}s)", total_files, total_files)

    return CompositeAnalysis(
        files=analyses,
        relationships=relationships,
        scene_structure=scene_structure,
        composite_plan=composite_plan,
        summary=summary,
    )
