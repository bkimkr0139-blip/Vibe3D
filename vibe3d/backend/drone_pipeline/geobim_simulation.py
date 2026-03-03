"""GeoBIM Simulation — NavMesh pathfinding + Visibility analysis.

Section 4.7: NavMesh-based pathfinding (A* on 2D obstacle grid)
Section 4.8: Sensor visibility / blind-spot analysis (ray marching)
"""

import heapq
import logging
import math
import time
from dataclasses import dataclass, field
from typing import Optional

from .geobim_db import get_db
from .geobim_models import SensorParams

logger = logging.getLogger("vibe3d.geobim.simulation")


# ══════════════════════════════════════════════════════════════
# Grid Pathfinder (Section 4.7)
# ══════════════════════════════════════════════════════════════


@dataclass
class PathResult:
    """Result of a pathfinding query."""
    success: bool = False
    path: list[list[float]] = field(default_factory=list)  # [[x,z], ...]
    distance: float = 0.0
    elapsed_ms: float = 0.0
    grid_resolution: float = 1.0
    cells_explored: int = 0
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "path": [[round(c, 2) for c in p] for p in self.path],
            "distance": round(self.distance, 2),
            "elapsed_ms": round(self.elapsed_ms, 1),
            "grid_resolution": self.grid_resolution,
            "cells_explored": self.cells_explored,
            "error": self.error,
        }


class GridPathfinder:
    """A* pathfinding on a 2D occupancy grid built from building footprints."""

    def __init__(self, resolution: float = 1.0, agent_radius: float = 0.5):
        self.resolution = resolution
        self.agent_radius = agent_radius
        self._grid: Optional[dict] = None  # (gx, gz) → True (blocked)
        self._bounds = None  # (min_x, min_z, max_x, max_z)

    def _build_grid(self, footprints: list[dict]) -> None:
        """Build occupancy grid from building footprints."""
        if not footprints:
            self._grid = {}
            self._bounds = (0, 0, 100, 100)
            return

        # Find world bounds from all footprints
        all_x, all_z = [], []
        for fp in footprints:
            for pt in fp.get("footprint", []):
                all_x.append(pt[0])
                all_z.append(pt[1])

        if not all_x:
            self._grid = {}
            self._bounds = (0, 0, 100, 100)
            return

        pad = 20.0
        min_x, max_x = min(all_x) - pad, max(all_x) + pad
        min_z, max_z = min(all_z) - pad, max(all_z) + pad
        self._bounds = (min_x, min_z, max_x, max_z)

        # Rasterize building footprints onto grid
        self._grid = {}
        inflate = max(1, int(math.ceil(self.agent_radius / self.resolution)))

        for fp in footprints:
            polygon = fp.get("footprint", [])
            if len(polygon) < 3:
                continue
            # Find polygon AABB in grid coords
            px = [p[0] for p in polygon]
            pz = [p[1] for p in polygon]
            gx_min = int((min(px) - min_x) / self.resolution) - inflate
            gx_max = int((max(px) - min_x) / self.resolution) + inflate
            gz_min = int((min(pz) - min_z) / self.resolution) - inflate
            gz_max = int((max(pz) - min_z) / self.resolution) + inflate

            for gx in range(gx_min, gx_max + 1):
                for gz in range(gz_min, gz_max + 1):
                    wx = min_x + gx * self.resolution
                    wz = min_z + gz * self.resolution
                    if self._point_in_polygon(wx, wz, polygon):
                        self._grid[(gx, gz)] = True

        logger.info(f"Grid built: {len(self._grid)} blocked cells, "
                     f"bounds=({min_x:.0f},{min_z:.0f})-({max_x:.0f},{max_z:.0f})")

    @staticmethod
    def _point_in_polygon(x: float, z: float, polygon: list[list[float]]) -> bool:
        inside = False
        n = len(polygon)
        j = n - 1
        for i in range(n):
            xi, zi = polygon[i]
            xj, zj = polygon[j]
            if ((zi > z) != (zj > z)) and (x < (xj - xi) * (z - zi) / (zj - zi) + xi):
                inside = not inside
            j = i
        return inside

    def _world_to_grid(self, x: float, z: float) -> tuple[int, int]:
        bx, bz = self._bounds[0], self._bounds[1]
        return int((x - bx) / self.resolution), int((z - bz) / self.resolution)

    def _grid_to_world(self, gx: int, gz: int) -> tuple[float, float]:
        bx, bz = self._bounds[0], self._bounds[1]
        return bx + gx * self.resolution, bz + gz * self.resolution

    def find_path(self, start: list[float], end: list[float]) -> PathResult:
        """A* pathfinding from start [x,z] to end [x,z]."""
        t0 = time.time()

        # Build grid if not yet built
        if self._grid is None:
            db = get_db()
            fps = db.get_footprints()
            self._build_grid(fps)

        sx, sz = self._world_to_grid(start[0], start[1])
        ex, ez = self._world_to_grid(end[0], end[1])

        # Check start/end validity
        if self._grid.get((sx, sz)):
            return PathResult(error="Start point is inside a building")
        if self._grid.get((ex, ez)):
            return PathResult(error="End point is inside a building")

        # A* search
        open_set = []
        heapq.heappush(open_set, (0, sx, sz))
        came_from: dict[tuple[int, int], tuple[int, int]] = {}
        g_score: dict[tuple[int, int], float] = {(sx, sz): 0}
        explored = 0

        # 8-directional movement
        dirs = [(-1, 0), (1, 0), (0, -1), (0, 1),
                (-1, -1), (-1, 1), (1, -1), (1, 1)]
        dir_costs = [1.0, 1.0, 1.0, 1.0, 1.414, 1.414, 1.414, 1.414]

        max_cells = 500_000  # safety limit

        while open_set and explored < max_cells:
            _, cx, cz = heapq.heappop(open_set)
            explored += 1

            if (cx, cz) == (ex, ez):
                # Reconstruct path
                path_grid = [(cx, cz)]
                while (cx, cz) in came_from:
                    cx, cz = came_from[(cx, cz)]
                    path_grid.append((cx, cz))
                path_grid.reverse()

                # Smooth path (remove collinear points)
                path_world = [list(self._grid_to_world(g[0], g[1])) for g in path_grid]
                path_world = self._smooth_path(path_world)

                # Calculate total distance
                total_dist = 0.0
                for i in range(1, len(path_world)):
                    dx = path_world[i][0] - path_world[i - 1][0]
                    dz = path_world[i][1] - path_world[i - 1][1]
                    total_dist += math.sqrt(dx * dx + dz * dz)

                elapsed = (time.time() - t0) * 1000
                return PathResult(
                    success=True, path=path_world, distance=total_dist,
                    elapsed_ms=elapsed, grid_resolution=self.resolution,
                    cells_explored=explored,
                )

            for d, cost in zip(dirs, dir_costs):
                nx, nz = cx + d[0], cz + d[1]
                if self._grid.get((nx, nz)):
                    continue
                tentative_g = g_score.get((cx, cz), float("inf")) + cost
                if tentative_g < g_score.get((nx, nz), float("inf")):
                    came_from[(nx, nz)] = (cx, cz)
                    g_score[(nx, nz)] = tentative_g
                    h = math.sqrt((nx - ex) ** 2 + (nz - ez) ** 2)
                    heapq.heappush(open_set, (tentative_g + h, nx, nz))

        elapsed = (time.time() - t0) * 1000
        return PathResult(error="No path found", elapsed_ms=elapsed, cells_explored=explored)

    @staticmethod
    def _smooth_path(path: list[list[float]]) -> list[list[float]]:
        """Remove collinear intermediate points."""
        if len(path) <= 2:
            return path
        result = [path[0]]
        for i in range(1, len(path) - 1):
            dx1 = path[i][0] - path[i - 1][0]
            dz1 = path[i][1] - path[i - 1][1]
            dx2 = path[i + 1][0] - path[i][0]
            dz2 = path[i + 1][1] - path[i][1]
            cross = abs(dx1 * dz2 - dz1 * dx2)
            if cross > 0.01:
                result.append(path[i])
        result.append(path[-1])
        return result

    def flood_fill(self, start: list[float], max_time: float = 300.0,
                   speed: float = 1.4) -> dict:
        """
        Flood-fill reachable area analysis (Section 4.7 — accessibility).
        Returns cells reachable within max_time at given speed.
        """
        t0 = time.time()

        # Build grid if not yet built
        if self._grid is None:
            db = get_db()
            fps = db.get_footprints()
            self._build_grid(fps)

        sx, sz = self._world_to_grid(start[0], start[1])
        max_dist = max_time * speed
        max_grid_dist = max_dist / self.resolution

        # BFS flood fill with distance tracking
        queue = [(0.0, sx, sz)]
        dist_map: dict[tuple[int, int], float] = {(sx, sz): 0.0}
        heapq.heapify(queue)

        dirs = [(-1, 0), (1, 0), (0, -1), (0, 1),
                (-1, -1), (-1, 1), (1, -1), (1, 1)]
        dir_costs = [1.0, 1.0, 1.0, 1.0, 1.414, 1.414, 1.414, 1.414]

        while queue:
            d, cx, cz = heapq.heappop(queue)
            if d > max_grid_dist:
                continue

            for (ddx, ddz), cost in zip(dirs, dir_costs):
                nx, nz = cx + ddx, cz + ddz
                if self._grid.get((nx, nz)):
                    continue
                nd = d + cost
                if nd > max_grid_dist:
                    continue
                key = (nx, nz)
                if key not in dist_map or nd < dist_map[key]:
                    dist_map[key] = nd
                    heapq.heappush(queue, (nd, nx, nz))

        # Build result cells with time values
        reachable_cells = []
        for (gx, gz), gd in dist_map.items():
            wx, wz = self._grid_to_world(gx, gz)
            real_dist = gd * self.resolution
            travel_time = real_dist / speed if speed > 0 else 0
            reachable_cells.append({
                "x": round(wx, 1),
                "z": round(wz, 1),
                "distance": round(real_dist, 1),
                "time_s": round(travel_time, 1),
            })

        total_area = len(reachable_cells) * self.resolution * self.resolution
        elapsed_ms = (time.time() - t0) * 1000

        return {
            "success": True,
            "reachable_cells": reachable_cells,
            "cell_count": len(reachable_cells),
            "reachable_area_m2": round(total_area, 1),
            "max_time_s": max_time,
            "speed_mps": speed,
            "max_distance_m": round(max_dist, 1),
            "elapsed_ms": round(elapsed_ms, 1),
        }

    def invalidate(self) -> None:
        """Force grid rebuild on next query."""
        self._grid = None


# ══════════════════════════════════════════════════════════════
# Visibility Analyzer (Section 4.8)
# ══════════════════════════════════════════════════════════════


@dataclass
class VisibilityResult:
    """Result of a visibility/blind-spot analysis."""
    coverage_ratio: float = 0.0   # 0-1, fraction of area visible
    visible_cells: int = 0
    total_cells: int = 0
    blind_cells: int = 0
    grid_resolution: float = 1.0
    # Heatmap grid: list of {x, z, visible: bool, hit_count: int}
    heatmap: list[dict] = field(default_factory=list)
    sensors: list[dict] = field(default_factory=list)
    elapsed_ms: float = 0.0
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "coverage_ratio": round(self.coverage_ratio, 4),
            "visible_cells": self.visible_cells,
            "total_cells": self.total_cells,
            "blind_cells": self.blind_cells,
            "grid_resolution": self.grid_resolution,
            "heatmap": self.heatmap,
            "sensors": self.sensors,
            "elapsed_ms": round(self.elapsed_ms, 1),
            "error": self.error,
        }


class VisibilityAnalyzer:
    """Sensor-based visibility / blind-spot analysis using 2D ray marching."""

    def analyze(
        self,
        sensors: list[dict],
        region: Optional[dict] = None,
        grid_resolution: float = 2.0,
        max_cells: int = 50000,
    ) -> VisibilityResult:
        """
        Run visibility analysis for given sensors.

        sensors: list of {position:[x,y,z], hfov, vfov, yaw, max_distance, ...}
        region: optional {min_x, min_z, max_x, max_z} — defaults to building bounds + padding
        """
        t0 = time.time()

        db = get_db()
        footprints_raw = db.get_footprints()
        buildings = db.get_buildings(limit=5000)

        # Parse sensor params
        sensor_list = []
        for s in sensors:
            sp = SensorParams(
                position=s.get("position", [0, 3, 0]),
                height=s.get("height", 3.0),
                yaw=s.get("yaw", 0.0),
                pitch=s.get("pitch", 0.0),
                hfov=s.get("hfov", 360.0),
                vfov=s.get("vfov", 60.0),
                max_distance=s.get("max_distance", 100.0),
                yaw_steps=s.get("yaw_steps", 72),
                pitch_steps=s.get("pitch_steps", 1),
            )
            sensor_list.append(sp)

        if not sensor_list:
            return VisibilityResult(error="No sensors provided")

        # Determine analysis region
        if region:
            min_x = region["min_x"]
            min_z = region["min_z"]
            max_x = region["max_x"]
            max_z = region["max_z"]
        else:
            # Auto from buildings + sensor positions
            all_x, all_z = [], []
            for fp in footprints_raw:
                for pt in fp.get("footprint", []):
                    all_x.append(pt[0])
                    all_z.append(pt[1])
            for sp in sensor_list:
                all_x.append(sp.position[0])
                all_z.append(sp.position[2])

            if not all_x:
                return VisibilityResult(error="No data to analyze")

            pad = 30.0
            min_x, max_x = min(all_x) - pad, max(all_x) + pad
            min_z, max_z = min(all_z) - pad, max(all_z) + pad

        # Build obstacle segments from footprints
        segments = []
        for fp in footprints_raw:
            poly = fp.get("footprint", [])
            if len(poly) < 3:
                continue
            for i in range(len(poly)):
                j = (i + 1) % len(poly)
                segments.append((poly[i][0], poly[i][1], poly[j][0], poly[j][1]))

        # Generate grid cells
        nx = int((max_x - min_x) / grid_resolution) + 1
        nz = int((max_z - min_z) / grid_resolution) + 1
        total = nx * nz
        if total > max_cells:
            # Increase resolution to fit
            scale = math.sqrt(total / max_cells)
            grid_resolution *= scale
            nx = int((max_x - min_x) / grid_resolution) + 1
            nz = int((max_z - min_z) / grid_resolution) + 1
            total = nx * nz

        # Check visibility for each cell from each sensor
        hit_count = {}  # (gx, gz) → int

        for sp in sensor_list:
            sx, sz = sp.position[0], sp.position[2]
            max_d = sp.max_distance
            hfov_rad = math.radians(sp.hfov)
            yaw_rad = math.radians(sp.yaw)

            for gx in range(nx):
                for gz in range(nz):
                    wx = min_x + gx * grid_resolution
                    wz = min_z + gz * grid_resolution

                    # Distance check
                    dx, dz = wx - sx, wz - sz
                    dist = math.sqrt(dx * dx + dz * dz)
                    if dist > max_d or dist < 0.1:
                        continue

                    # FOV check (horizontal)
                    if sp.hfov < 360.0:
                        angle = math.atan2(dz, dx)
                        diff = abs(self._angle_diff(angle, yaw_rad))
                        if diff > hfov_rad / 2:
                            continue

                    # Ray march: check if any segment blocks line of sight
                    blocked = False
                    for seg in segments:
                        if self._ray_intersects_segment(
                            sx, sz, wx, wz,
                            seg[0], seg[1], seg[2], seg[3]
                        ):
                            blocked = True
                            break

                    if not blocked:
                        key = (gx, gz)
                        hit_count[key] = hit_count.get(key, 0) + 1

        # Build heatmap
        heatmap = []
        visible_count = 0
        for gx in range(nx):
            for gz in range(nz):
                wx = min_x + gx * grid_resolution
                wz = min_z + gz * grid_resolution
                hits = hit_count.get((gx, gz), 0)
                vis = hits > 0
                if vis:
                    visible_count += 1
                heatmap.append({
                    "x": round(wx, 1),
                    "z": round(wz, 1),
                    "visible": vis,
                    "hit_count": hits,
                })

        elapsed = (time.time() - t0) * 1000
        coverage = visible_count / total if total > 0 else 0

        return VisibilityResult(
            coverage_ratio=coverage,
            visible_cells=visible_count,
            total_cells=total,
            blind_cells=total - visible_count,
            grid_resolution=grid_resolution,
            heatmap=heatmap,
            sensors=[s.to_dict() for s in sensor_list],
            elapsed_ms=elapsed,
        )

    def building_coverage_report(
        self,
        sensors: list[dict],
        building_ids: list[str] | None = None,
        grid_resolution: float = 2.0,
    ) -> dict:
        """Per-building blind-spot coverage aggregation (Section 4.8)."""
        t0 = time.time()

        db = get_db()
        all_buildings = db.get_buildings(limit=5000)
        if building_ids:
            all_buildings = [b for b in all_buildings if b.id in building_ids]

        if not all_buildings:
            return {"error": "No buildings found", "buildings": []}

        # Run full visibility analysis first
        result = self.analyze(sensors, None, grid_resolution)
        if result.error:
            return {"error": result.error, "buildings": []}

        # Build hit lookup: (rounded x, z) → hit_count
        hit_lookup = {}
        for cell in result.heatmap:
            key = (round(cell["x"] / grid_resolution) * grid_resolution,
                   round(cell["z"] / grid_resolution) * grid_resolution)
            hit_lookup[key] = cell.get("hit_count", 0)

        # Per-building coverage
        building_reports = []
        for bldg in all_buildings:
            if not bldg.footprint or len(bldg.footprint) < 3:
                continue

            # Find grid cells that fall within building footprint
            fp = bldg.footprint
            fp_xs = [p[0] for p in fp]
            fp_zs = [p[1] for p in fp]
            fp_min_x, fp_max_x = min(fp_xs), max(fp_xs)
            fp_min_z, fp_max_z = min(fp_zs), max(fp_zs)

            total_cells = 0
            visible_cells = 0

            gx = fp_min_x
            while gx <= fp_max_x:
                gz = fp_min_z
                while gz <= fp_max_z:
                    if self._point_in_polygon_static(gx, gz, fp):
                        total_cells += 1
                        key = (round(gx / grid_resolution) * grid_resolution,
                               round(gz / grid_resolution) * grid_resolution)
                        if hit_lookup.get(key, 0) > 0:
                            visible_cells += 1
                    gz += grid_resolution
                gx += grid_resolution

            coverage = visible_cells / total_cells if total_cells > 0 else 0
            building_reports.append({
                "building_id": bldg.id,
                "label": bldg.label,
                "coverage_ratio": round(coverage, 4),
                "visible_cells": visible_cells,
                "total_cells": total_cells,
                "blind_cells": total_cells - visible_cells,
                "area_m2": round(bldg.footprint_area, 1),
                "height_max": round(bldg.height_max, 1),
            })

        # Sort by coverage (worst first)
        building_reports.sort(key=lambda r: r["coverage_ratio"])

        elapsed = (time.time() - t0) * 1000
        avg_coverage = (
            sum(r["coverage_ratio"] for r in building_reports) / len(building_reports)
            if building_reports else 0
        )

        return {
            "buildings": building_reports,
            "building_count": len(building_reports),
            "avg_coverage": round(avg_coverage, 4),
            "overall_coverage": round(result.coverage_ratio, 4),
            "sensor_count": len(sensors),
            "elapsed_ms": round(elapsed, 1),
        }

    @staticmethod
    def _point_in_polygon_static(x: float, z: float, polygon: list[list[float]]) -> bool:
        inside = False
        n = len(polygon)
        j = n - 1
        for i in range(n):
            xi, zi = polygon[i]
            xj, zj = polygon[j]
            if ((zi > z) != (zj > z)) and (x < (xj - xi) * (z - zi) / (zj - zi) + xi):
                inside = not inside
            j = i
        return inside

    @staticmethod
    def _angle_diff(a: float, b: float) -> float:
        """Signed angle difference, result in [-pi, pi]."""
        d = a - b
        while d > math.pi:
            d -= 2 * math.pi
        while d < -math.pi:
            d += 2 * math.pi
        return d

    @staticmethod
    def _ray_intersects_segment(
        rx: float, rz: float, tx: float, tz: float,
        ax: float, az: float, bx: float, bz: float,
    ) -> bool:
        """Test if ray from (rx,rz)->(tx,tz) intersects segment (ax,az)-(bx,bz)."""
        dx, dz = tx - rx, tz - rz
        sx, sz = bx - ax, bz - az
        denom = dx * sz - dz * sx
        if abs(denom) < 1e-10:
            return False

        t = ((ax - rx) * sz - (az - rz) * sx) / denom
        u = ((ax - rx) * dz - (az - rz) * dx) / denom

        # t in (epsilon, 1-epsilon) to exclude start/end grazing
        # u in [0, 1] for segment hit
        return 0.01 < t < 0.99 and 0.0 <= u <= 1.0


# ── Singletons ───────────────────────────────────────────────

_pathfinder: Optional[GridPathfinder] = None
_visibility: Optional[VisibilityAnalyzer] = None


def get_pathfinder(resolution: float = 1.0) -> GridPathfinder:
    global _pathfinder
    if _pathfinder is None:
        _pathfinder = GridPathfinder(resolution=resolution)
    return _pathfinder


def get_visibility() -> VisibilityAnalyzer:
    global _visibility
    if _visibility is None:
        _visibility = VisibilityAnalyzer()
    return _visibility
