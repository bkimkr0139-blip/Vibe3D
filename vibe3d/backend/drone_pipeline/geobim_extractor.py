"""GeoBIM Extractor — automatic building separation from OBJ tile meshes.

Algorithm (Section 3.3.1 — rule-based 3D geometry):
  OBJ parse → triangle face normals
  → RANSAC ground plane estimation (|n·up| > 0.85)
  → remove ground ±1.0m triangles
  → extract vertical faces (|n·up| < 0.35)
  → DBSCAN clustering (eps=3m, min_samples=30)
  → size filter (height>2m, area>10m²)
  → per-cluster: height/footprint/bbox/obb/area/volume/confidence

Enhanced attributes (Section 3.4):
  - height_min/max/avg with outlier trimming (0.5%)
  - OBB via PCA approximation
  - volume_approx = area_2d × (height_avg - ground_level)
  - surface_area_approx from triangle areas
  - confidence = height_score × area_score × compactness
"""

import logging
import time
import uuid
from pathlib import Path
from typing import Optional

import numpy as np

from .geobim_models import BuildingCandidate, ExtractionStatus, GeoBIMReport, OBBData, RoofPlane

logger = logging.getLogger("vibe3d.geobim")

# ── Defaults ─────────────────────────────────────────────────

DEFAULT_PARAMS = {
    "ground_normal_thresh": 0.85,   # |n·up| threshold for ground faces
    "ground_tolerance": 1.0,        # ±m from RANSAC plane
    "vertical_thresh": 0.35,        # |n·up| below this = vertical face
    "dbscan_eps": 3.0,              # meters clustering radius
    "dbscan_min_samples": 30,       # min triangles per cluster
    "min_building_height": 2.0,     # m
    "min_building_area": 10.0,      # m²
    "ransac_iterations": 200,
    "ransac_inlier_thresh": 0.5,    # m
    "outlier_trim_pct": 0.5,        # % trim top/bottom for height stats
}


class GeoBIMExtractor:
    """Extracts building candidates from OBJ tile files."""

    def __init__(self, params: Optional[dict] = None):
        self.params = {**DEFAULT_PARAMS, **(params or {})}
        self._report = GeoBIMReport()
        self._progress_callback = None

    @property
    def report(self) -> GeoBIMReport:
        return self._report

    def set_progress_callback(self, cb):
        self._progress_callback = cb

    def _notify_progress(self):
        if self._progress_callback:
            self._progress_callback(self._report)

    # ── Main entry ──────────────────────────────────────────

    def extract_all(self, tile_folder: str) -> GeoBIMReport:
        """Run extraction on all OBJ tiles in a folder."""
        t0 = time.time()
        folder = Path(tile_folder)
        obj_files = sorted(folder.glob("*.obj"))
        if not obj_files:
            obj_files = sorted(folder.rglob("*.obj"))

        self._report = GeoBIMReport(
            status=ExtractionStatus.RUNNING,
            tile_count=len(obj_files),
        )
        self._notify_progress()

        all_buildings: list[BuildingCandidate] = []

        for obj_path in obj_files:
            try:
                buildings = self._process_tile(obj_path)
                all_buildings.extend(buildings)
                self._report.tiles_processed += 1
                self._notify_progress()
            except Exception as e:
                logger.error(f"Error processing {obj_path.name}: {e}")
                continue

        # Assign IDs and labels
        for i, b in enumerate(all_buildings):
            b.id = f"bldg-{uuid.uuid4().hex[:8]}"
            b.label = f"Building-{i+1:03d}"

        self._report.buildings = all_buildings
        self._report.building_count = len(all_buildings)
        if all_buildings:
            heights = [b.height_max for b in all_buildings]
            self._report.avg_height = float(np.mean(heights))
            self._report.max_height = float(np.max(heights))
            self._report.total_footprint_area = sum(b.footprint_area for b in all_buildings)
            self._report.total_volume = sum(b.volume_approx for b in all_buildings)

        self._report.processing_time_s = time.time() - t0
        self._report.status = ExtractionStatus.COMPLETED
        self._notify_progress()
        logger.info(
            f"GeoBIM extraction complete: {len(all_buildings)} buildings "
            f"from {len(obj_files)} tiles in {self._report.processing_time_s:.1f}s"
        )
        return self._report

    # ── Per-tile processing ─────────────────────────────────

    def _process_tile(self, obj_path: Path) -> list[BuildingCandidate]:
        tile_name = obj_path.parent.name if obj_path.parent.name != obj_path.parent.parent.name else obj_path.stem

        vertices, faces = self._parse_obj(obj_path)
        if len(faces) < 100:
            logger.debug(f"Skipping {tile_name}: only {len(faces)} faces")
            return []

        # Compute face normals, centroids, and areas
        v0 = vertices[faces[:, 0]]
        v1 = vertices[faces[:, 1]]
        v2 = vertices[faces[:, 2]]
        edges1 = v1 - v0
        edges2 = v2 - v0
        cross = np.cross(edges1, edges2)
        norms = np.linalg.norm(cross, axis=1, keepdims=True)
        norms[norms < 1e-10] = 1e-10
        normals = cross / norms
        face_areas = (norms.ravel() * 0.5)
        centroids = (v0 + v1 + v2) / 3.0

        # RANSAC ground plane (Y-up)
        ground_y = self._ransac_ground(centroids, normals)
        self._report.ground_plane_z = float(ground_y)

        tol = self.params["ground_tolerance"]
        vert_thresh = self.params["vertical_thresh"]

        above_ground = np.abs(centroids[:, 1] - ground_y) > tol
        is_vertical = np.abs(normals[:, 1]) < vert_thresh

        building_mask = above_ground & is_vertical
        if building_mask.sum() < self.params["dbscan_min_samples"]:
            return []

        bldg_centroids = centroids[building_mask]
        bldg_face_indices = np.where(building_mask)[0]

        clusters = self._dbscan_xz(bldg_centroids)
        unique_labels = set(clusters)
        unique_labels.discard(-1)

        buildings = []
        for label in unique_labels:
            cluster_mask = clusters == label
            cluster_face_idx = bldg_face_indices[cluster_mask]

            cluster_faces = faces[cluster_face_idx]
            cluster_vert_idx = np.unique(cluster_faces.ravel())
            cluster_verts = vertices[cluster_vert_idx]
            cluster_areas = face_areas[cluster_face_idx]
            cluster_normals = normals[cluster_face_idx]
            cluster_centroids = centroids[cluster_face_idx]

            b = self._build_candidate(
                tile_name, label, cluster_verts,
                len(cluster_face_idx), ground_y, cluster_areas,
                cluster_normals, cluster_centroids,
            )
            if b is not None:
                buildings.append(b)

        return buildings

    # ── OBJ Parser ──────────────────────────────────────────

    @staticmethod
    def _parse_obj(path: Path) -> tuple[np.ndarray, np.ndarray]:
        """Minimal OBJ parser — extracts vertices and triangulated faces."""
        verts = []
        faces = []
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith("v "):
                    parts = line.split()
                    verts.append([float(parts[1]), float(parts[2]), float(parts[3])])
                elif line.startswith("f "):
                    parts = line.split()[1:]
                    indices = []
                    for p in parts:
                        idx = int(p.split("/")[0]) - 1
                        indices.append(idx)
                    for i in range(1, len(indices) - 1):
                        faces.append([indices[0], indices[i], indices[i + 1]])

        vertices = np.array(verts, dtype=np.float64) if verts else np.zeros((0, 3))
        face_arr = np.array(faces, dtype=np.int32) if faces else np.zeros((0, 3), dtype=np.int32)

        if len(face_arr) > 0 and len(vertices) > 0:
            face_arr = np.clip(face_arr, 0, len(vertices) - 1)

        return vertices, face_arr

    # ── RANSAC Ground ───────────────────────────────────────

    def _ransac_ground(self, centroids: np.ndarray, normals: np.ndarray) -> float:
        """Estimate ground Y using RANSAC on near-horizontal faces."""
        up_thresh = self.params["ground_normal_thresh"]
        horizontal_mask = np.abs(normals[:, 1]) > up_thresh
        if horizontal_mask.sum() < 10:
            return float(np.percentile(centroids[:, 1], 5))

        horiz_y = centroids[horizontal_mask, 1]
        best_y = float(np.median(horiz_y))
        best_inliers = 0
        inlier_thresh = self.params["ransac_inlier_thresh"]
        rng = np.random.default_rng(42)

        for _ in range(self.params["ransac_iterations"]):
            sample_y = rng.choice(horiz_y)
            inliers = np.abs(horiz_y - sample_y) < inlier_thresh
            count = inliers.sum()
            if count > best_inliers:
                best_inliers = count
                best_y = float(np.mean(horiz_y[inliers]))

        return best_y

    # ── DBSCAN XZ ───────────────────────────────────────────

    def _dbscan_xz(self, centroids: np.ndarray) -> np.ndarray:
        """DBSCAN clustering on XZ (horizontal) plane."""
        try:
            from sklearn.cluster import DBSCAN
            xz = centroids[:, [0, 2]]
            db = DBSCAN(
                eps=self.params["dbscan_eps"],
                min_samples=self.params["dbscan_min_samples"],
            ).fit(xz)
            return db.labels_
        except ImportError:
            logger.warning("sklearn not available, using grid-based fallback")
            return self._grid_cluster_xz(centroids)

    def _grid_cluster_xz(self, centroids: np.ndarray) -> np.ndarray:
        """Fallback grid-based clustering when sklearn unavailable."""
        eps = self.params["dbscan_eps"]
        xz = centroids[:, [0, 2]]
        grid_keys = np.floor(xz / eps).astype(np.int32)

        cell_map: dict[tuple, list[int]] = {}
        for i, key in enumerate(grid_keys):
            k = (int(key[0]), int(key[1]))
            cell_map.setdefault(k, []).append(i)

        labels = np.full(len(centroids), -1, dtype=np.int32)
        cluster_id = 0
        min_samples = self.params["dbscan_min_samples"]

        for indices in cell_map.values():
            if len(indices) >= min_samples:
                for idx in indices:
                    labels[idx] = cluster_id
                cluster_id += 1

        return labels

    # ── Build Candidate (enhanced attributes) ───────────────

    def _build_candidate(
        self, tile_name: str, cluster_id: int,
        verts: np.ndarray, face_count: int,
        ground_y: float, face_areas: np.ndarray,
        face_normals: Optional[np.ndarray] = None,
        face_centroids: Optional[np.ndarray] = None,
    ) -> Optional[BuildingCandidate]:
        """Create a BuildingCandidate with full GeoBIM attributes."""
        if len(verts) < 4:
            return None

        bbox_min = verts.min(axis=0)
        bbox_max = verts.max(axis=0)

        # ── Height stats with outlier trimming (Section 3.4 A) ──
        y_vals = verts[:, 1]
        trim_pct = self.params["outlier_trim_pct"]
        lo = np.percentile(y_vals, trim_pct)
        hi = np.percentile(y_vals, 100 - trim_pct)
        trimmed_y = y_vals[(y_vals >= lo) & (y_vals <= hi)]
        if len(trimmed_y) == 0:
            trimmed_y = y_vals

        height_min_abs = float(np.min(trimmed_y))
        height_max_abs = float(np.max(trimmed_y))
        height_avg_abs = float(np.mean(trimmed_y))

        height_min = height_min_abs - ground_y
        height_max = height_max_abs - ground_y
        height_avg = height_avg_abs - ground_y
        height = height_max  # legacy compat

        if height_max < self.params["min_building_height"]:
            return None

        # ── Footprint (Section 3.4 B) ──
        xz = verts[:, [0, 2]]
        footprint_pts, footprint_area = self._compute_footprint(xz)

        if footprint_area < self.params["min_building_area"]:
            return None

        # ── Centroid ──
        centroid = [
            float(np.mean(verts[:, 0])),
            float(np.mean(verts[:, 1])),
            float(np.mean(verts[:, 2])),
        ]

        # ── OBB via PCA (Section 3.4 C) ──
        obb = self._compute_obb(verts)

        # ── Volume approx (Section 3.4 D) ──
        volume_approx = footprint_area * max(height_avg, 0)

        # ── Surface area approx ──
        surface_area = float(np.sum(face_areas))

        # ── Confidence score (Section 3.4 F) ──
        height_score = min(height_max / 10.0, 1.0)
        area_score = min(footprint_area / 100.0, 1.0)
        perimeter = self._polygon_perimeter(footprint_pts)
        compactness = (4 * np.pi * footprint_area) / (perimeter ** 2 + 1e-6) if perimeter > 0 else 0
        confidence = height_score * 0.4 + area_score * 0.3 + compactness * 0.3

        # ── Roof planes (Section 3.4E) ──
        roof_planes = []
        if face_normals is not None and face_centroids is not None:
            roof_planes = self._extract_roof_planes(
                face_normals, face_centroids, face_areas,
                height_max_abs, ground_y,
            )

        # ── Derive roof_type tag ──
        tags = ["building"]
        if roof_planes:
            avg_tilt = sum(rp.tilt_deg for rp in roof_planes) / len(roof_planes)
            if avg_tilt < 5:
                tags.append("roof_type:flat")
            elif avg_tilt < 30:
                tags.append("roof_type:low_slope")
            elif len(roof_planes) >= 2:
                tags.append("roof_type:gable")
            else:
                tags.append("roof_type:shed")

        return BuildingCandidate(
            tile_name=tile_name,
            height=height,
            height_min=height_min,
            height_max=height_max,
            height_avg=height_avg,
            ground_elevation=ground_y,
            roof_elevation=height_max_abs,
            footprint_area=footprint_area,
            surface_area_approx=surface_area,
            volume_approx=volume_approx,
            bbox_min=bbox_min.tolist(),
            bbox_max=bbox_max.tolist(),
            obb=obb,
            footprint=footprint_pts,
            centroid=centroid,
            roof_planes=roof_planes,
            vertex_count=len(verts),
            face_count=face_count,
            confidence=confidence,
            cluster_id=cluster_id,
            tags=tags,
        )

    # ── Roof Plane Extraction (Section 3.4E) ────────────────

    def _extract_roof_planes(
        self, normals: np.ndarray, centroids: np.ndarray,
        areas: np.ndarray, roof_y: float, ground_y: float,
        top_pct: float = 30.0, max_planes: int = 4,
    ) -> list[RoofPlane]:
        """Extract roof planes via RANSAC on upper-region triangles."""
        if len(normals) < 10:
            return []

        # Select top portion of triangles (height > roof_y - top_pct% of building height)
        building_height = roof_y - ground_y
        if building_height < 1:
            return []
        height_threshold = roof_y - building_height * (top_pct / 100.0)
        top_mask = centroids[:, 1] > height_threshold

        if top_mask.sum() < 5:
            return []

        top_normals = normals[top_mask]
        top_areas = areas[top_mask]
        top_centroids = centroids[top_mask]

        # Iterative RANSAC for multiple planes
        remaining = np.ones(len(top_normals), dtype=bool)
        planes = []
        rng = np.random.default_rng(42)

        for _ in range(max_planes):
            if remaining.sum() < 5:
                break

            active_idx = np.where(remaining)[0]
            active_normals = top_normals[active_idx]
            active_areas = top_areas[active_idx]
            active_centroids = top_centroids[active_idx]

            best_normal = None
            best_inlier_mask = None
            best_inlier_count = 0

            for _ in range(50):
                # Sample a random face as plane hypothesis
                si = rng.integers(0, len(active_normals))
                candidate_n = active_normals[si]
                # Inliers: faces whose normal is similar (dot product > 0.85)
                dots = np.abs(np.dot(active_normals, candidate_n))
                inlier_mask = dots > 0.85
                count = inlier_mask.sum()
                if count > best_inlier_count:
                    best_inlier_count = count
                    best_inlier_mask = inlier_mask
                    best_normal = active_normals[inlier_mask].mean(axis=0)

            if best_normal is None or best_inlier_count < 3:
                break

            # Normalize
            norm_len = np.linalg.norm(best_normal)
            if norm_len < 1e-6:
                break
            best_normal = best_normal / norm_len

            # Calculate plane properties
            inlier_areas = active_areas[best_inlier_mask]
            inlier_centroids = active_centroids[best_inlier_mask]
            plane_area = float(np.sum(inlier_areas))
            plane_center = inlier_centroids.mean(axis=0)

            # Distance from origin
            d = float(np.dot(best_normal, plane_center))

            # Tilt: angle from vertical (horizontal plane = 0°)
            tilt = float(np.degrees(np.arccos(np.clip(abs(best_normal[1]), 0, 1))))

            # Azimuth: direction the plane faces on XZ plane
            azimuth = float(np.degrees(np.arctan2(best_normal[0], best_normal[2]))) % 360

            planes.append(RoofPlane(
                normal=best_normal.tolist(),
                d=d, area=plane_area,
                tilt_deg=tilt, azimuth_deg=azimuth,
            ))

            # Remove inliers from remaining set
            remaining[active_idx[best_inlier_mask]] = False

        return planes

    # ── OBB via PCA ─────────────────────────────────────────

    @staticmethod
    def _compute_obb(verts: np.ndarray) -> OBBData:
        """Oriented bounding box via PCA approximation."""
        center = verts.mean(axis=0)
        centered = verts - center
        try:
            cov = np.cov(centered, rowvar=False)
            eigenvalues, eigenvectors = np.linalg.eigh(cov)
            # Sort by descending eigenvalue
            order = np.argsort(-eigenvalues)
            axes = eigenvectors[:, order].T  # rows are principal axes

            # Project onto principal axes to get extents
            projected = centered @ axes.T
            p_min = projected.min(axis=0)
            p_max = projected.max(axis=0)
            extents = ((p_max - p_min) / 2).tolist()

            # Adjust center to midpoint of projected extents
            mid = (p_min + p_max) / 2
            obb_center = (center + mid @ axes).tolist()

            return OBBData(
                center=obb_center,
                axes=axes.tolist(),
                extents=extents,
            )
        except Exception:
            # Fallback to AABB
            half = ((verts.max(axis=0) - verts.min(axis=0)) / 2).tolist()
            return OBBData(center=center.tolist(), extents=half)

    # ── Footprint ───────────────────────────────────────────

    @staticmethod
    def _compute_footprint(xz: np.ndarray) -> tuple[list[list[float]], float]:
        """Compute convex hull footprint on XZ plane."""
        try:
            from scipy.spatial import ConvexHull
            if len(xz) < 3:
                return [], 0.0
            unique_xz = np.unique(xz, axis=0)
            if len(unique_xz) < 3:
                return [], 0.0
            hull = ConvexHull(unique_xz)
            pts = unique_xz[hull.vertices].tolist()
            return pts, float(hull.volume)  # 2D hull: volume = area
        except Exception:
            mn = xz.min(axis=0)
            mx = xz.max(axis=0)
            w, h = float(mx[0] - mn[0]), float(mx[1] - mn[1])
            pts = [
                [float(mn[0]), float(mn[1])],
                [float(mx[0]), float(mn[1])],
                [float(mx[0]), float(mx[1])],
                [float(mn[0]), float(mx[1])],
            ]
            return pts, w * h

    @staticmethod
    def _polygon_perimeter(pts: list[list[float]]) -> float:
        if len(pts) < 2:
            return 0.0
        total = 0.0
        for i in range(len(pts)):
            j = (i + 1) % len(pts)
            dx = pts[j][0] - pts[i][0]
            dz = pts[j][1] - pts[i][1]
            total += (dx * dx + dz * dz) ** 0.5
        return total


# ── Singleton accessor ──────────────────────────────────────

_extractor: Optional[GeoBIMExtractor] = None


def get_extractor() -> GeoBIMExtractor:
    global _extractor
    if _extractor is None:
        _extractor = GeoBIMExtractor()
    return _extractor
