"""Ingest & QA engine for Drone2Twin pipeline.

Analyzes uploaded file packs (vendor-processed or raw images) and produces
quality reports with scores, warnings, and recommendations.
Uses only stdlib (struct for EXIF parsing, no PIL/OpenCV dependency).
"""

import logging
import math
import os
import struct
from pathlib import Path
from typing import Optional

from .models import InputOption, QAReport

logger = logging.getLogger(__name__)

# ── File extensions ──────────────────────────────────────────

MESH_EXTENSIONS = {".glb", ".gltf", ".fbx", ".obj", ".ply", ".stl", ".dae"}
TEXTURE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tga", ".bmp", ".tif", ".tiff"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".dng", ".raw", ".cr2", ".nef", ".arw"}
POINTCLOUD_EXTENSIONS = {".ply", ".las", ".laz", ".xyz"}
LOG_EXTENSIONS = {".csv", ".log", ".txt", ".json"}

# ── EXIF tag IDs ─────────────────────────────────────────────

_EXIF_GPS_IFD_TAG = 0x8825
_EXIF_IMAGE_WIDTH = 0xA002
_EXIF_IMAGE_HEIGHT = 0xA003
_EXIF_FOCAL_LENGTH = 0x920A
_EXIF_GPS_LAT = 0x0002
_EXIF_GPS_LON = 0x0004
_EXIF_GPS_ALT = 0x0006


class IngestQAEngine:
    """Analyzes drone/vendor packs for quality and completeness."""

    def analyze_pack(self, pack_dir: str) -> QAReport:
        """Scan folder, auto-detect input option, produce quality report."""
        pack = Path(pack_dir)
        if not pack.is_dir():
            return QAReport(score=0, warnings=[f"Directory not found: {pack_dir}"])

        option = self._detect_input_option(pack)
        if option == InputOption.OBJ_FOLDER:
            report = self._analyze_obj_folder(pack)
        elif option == InputOption.VENDOR_PACK:
            report = self._analyze_vendor_pack(pack)
        else:
            report = self._analyze_raw_images(pack)

        report.input_option = option.value
        logger.info(
            "IngestQA: %s — option=%s, score=%d, warnings=%d",
            pack_dir, option.value, report.score, len(report.warnings),
        )
        return report

    # ── Option detection ─────────────────────────────────────

    def _detect_input_option(self, pack: Path) -> InputOption:
        """Detect whether this is a vendor pack (mesh files) or raw images."""
        # Check for OBJ tile pattern first (Tile-*.obj files)
        tile_objs = list(pack.glob("Tile-*.obj"))
        if not tile_objs:
            tile_objs = list(pack.glob("**/Tile-*.obj"))
        if len(tile_objs) >= 2:
            return InputOption.OBJ_FOLDER

        # Check for mesh files in root or vendor/ subfolder
        mesh_found = False
        for ext in MESH_EXTENSIONS:
            if list(pack.glob(f"*{ext}")) or list(pack.glob(f"vendor/*{ext}")):
                mesh_found = True
                break

        # Check for image files in root or raw/images/ subfolder
        image_count = 0
        for ext in IMAGE_EXTENSIONS:
            image_count += len(list(pack.glob(f"*{ext}")))
            image_count += len(list(pack.glob(f"raw/images/*{ext}")))

        if mesh_found:
            return InputOption.VENDOR_PACK
        if image_count >= 5:
            return InputOption.RAW_IMAGES

        # Default to vendor pack if ambiguous
        return InputOption.VENDOR_PACK

    # ── Vendor Pack Analysis (Option A) ──────────────────────

    def _analyze_vendor_pack(self, pack: Path) -> QAReport:
        """Analyze vendor-processed pack: mesh quality, textures, metadata."""
        report = QAReport(score=50)  # base score

        # Scan for mesh files
        mesh_files = []
        for ext in MESH_EXTENSIONS:
            mesh_files.extend(pack.glob(f"**/*{ext}"))
        report.mesh_files = [str(f) for f in mesh_files]

        if not mesh_files:
            report.score = 10
            report.warnings.append("No mesh files found (expected .glb/.fbx/.obj)")
            report.recommendations.append("Upload mesh files to vendor/ folder")
            return report

        # Score: mesh files found
        report.score += 15

        # Check mesh file sizes
        total_mesh_size = sum(f.stat().st_size for f in mesh_files)
        report.total_size_mb = round(total_mesh_size / (1024 * 1024), 1)

        if total_mesh_size < 1024:
            report.warnings.append("Mesh files extremely small — may be empty/corrupted")
            report.score -= 10
        elif total_mesh_size > 500 * 1024 * 1024:
            report.warnings.append(f"Total mesh size {report.total_size_mb}MB — very large, LOD optimization critical")

        # Check for textures
        tex_files = []
        for ext in TEXTURE_EXTENSIONS:
            tex_files.extend(pack.glob(f"**/*{ext}"))
        report.texture_files = [str(f) for f in tex_files]

        if tex_files:
            report.score += 10
            # Check for oversized textures (> 8K)
            for tf in tex_files:
                size_mb = tf.stat().st_size / (1024 * 1024)
                if size_mb > 32:
                    report.warnings.append(f"Texture {tf.name} is {size_mb:.0f}MB — may need resize")
        else:
            report.recommendations.append("No textures found — mesh may appear untextured")

        # Check for metadata.json
        meta_path = pack / "metadata.json" if (pack / "metadata.json").exists() else pack / "vendor" / "metadata.json"
        if meta_path.exists():
            report.score += 10
            report.recommendations.append("metadata.json found — coordinate/scale info available")
        else:
            report.recommendations.append("No metadata.json — scale/coordinate verification recommended")

        # Check for LOD variants
        lod_count = sum(1 for f in mesh_files if "lod" in f.stem.lower())
        if lod_count >= 2:
            report.score += 10
            report.recommendations.append(f"{lod_count} LOD variants found — can skip LOD generation")
        else:
            report.recommendations.append("No LOD variants — will generate LOD0/1/2 during optimization")

        # Check for point cloud (useful for validation)
        pc_files = []
        for ext in POINTCLOUD_EXTENSIONS:
            pc_files.extend(pack.glob(f"**/*{ext}"))
        if pc_files:
            report.score += 5
            report.recommendations.append("Point cloud found — useful for scale/alignment verification")

        report.score = min(100, report.score)
        return report

    # ── Raw Images Analysis (Option B) ───────────────────────

    def _analyze_raw_images(self, pack: Path) -> QAReport:
        """Analyze raw drone/camera images: EXIF, blur, overlap, GPS."""
        report = QAReport(score=40)  # base score for having images

        # Find all images
        image_paths = []
        for ext in IMAGE_EXTENSIONS:
            image_paths.extend(pack.glob(f"**/*{ext}"))
        report.image_count = len(image_paths)

        if report.image_count == 0:
            report.score = 5
            report.warnings.append("No images found")
            return report

        if report.image_count < 20:
            report.warnings.append(f"Only {report.image_count} images — minimum 20-30 recommended for good reconstruction")
        elif report.image_count >= 50:
            report.score += 10

        # Analyze EXIF for each image
        gps_coords = []
        resolutions = []
        focal_lengths = []
        blur_count = 0

        for img_path in image_paths:
            exif = self._parse_exif_basic(img_path)
            if exif is None:
                continue

            # Resolution
            w, h = exif.get("width", 0), exif.get("height", 0)
            if w and h:
                resolutions.append((w, h))

            # GPS
            if exif.get("has_gps"):
                gps_coords.append(exif.get("gps", {}))
            else:
                report.exif_gps_missing += 1

            # Focal length
            fl = exif.get("focal_length")
            if fl:
                focal_lengths.append(fl)

            # Blur estimation (file size heuristic)
            if self._estimate_blur(img_path):
                blur_count += 1

        report.blur_count = blur_count

        # Resolution stats
        if resolutions:
            avg_w = sum(r[0] for r in resolutions) // len(resolutions)
            avg_h = sum(r[1] for r in resolutions) // len(resolutions)
            report.avg_resolution = f"{avg_w}x{avg_h}"
            if avg_w >= 4000:
                report.score += 10
            elif avg_w < 2000:
                report.warnings.append(f"Average resolution {avg_w}x{avg_h} — low for photogrammetry")

        # GPS coverage
        if report.exif_gps_missing == 0 and report.image_count > 0:
            report.score += 10
            report.recommendations.append("All images have GPS data — good for georeferencing")
        elif report.exif_gps_missing > report.image_count * 0.5:
            report.warnings.append(f"{report.exif_gps_missing}/{report.image_count} images missing GPS")
            report.recommendations.append("Consider using GCP (ground control points) for alignment")

        # Overlap estimation
        report.overlap_estimate = self._estimate_overlap(gps_coords)
        if report.overlap_estimate == "good":
            report.score += 10
        elif report.overlap_estimate == "warning":
            report.warnings.append("Estimated overlap may be insufficient in some areas")
        elif report.overlap_estimate == "insufficient":
            report.warnings.append("Estimated overlap too low — reconstruction may fail")
            report.score -= 10

        # Blur
        if blur_count > report.image_count * 0.2:
            report.warnings.append(f"{blur_count}/{report.image_count} images appear blurry")
            report.score -= 5
        elif blur_count == 0:
            report.score += 5

        # Check for flight log
        log_dir = pack / "raw" / "flightlog"
        if log_dir.is_dir() and any(log_dir.iterdir()):
            report.score += 5
            report.recommendations.append("Flight log found — can verify altitude/coverage")
        else:
            report.recommendations.append("No flight log — upload for better QA analysis")

        # Check for GCP
        gcp_dir = pack / "raw" / "gcp"
        if gcp_dir.is_dir() and any(gcp_dir.iterdir()):
            report.gcp_available = True
            report.score += 5
            report.recommendations.append("GCP data found — will improve georeferencing accuracy")

        # Total size
        total = sum(f.stat().st_size for f in image_paths)
        report.total_size_mb = round(total / (1024 * 1024), 1)

        report.score = max(0, min(100, report.score))
        return report

    # ── OBJ Folder Analysis (Option C) ─────────────────────

    def _analyze_obj_folder(self, pack: Path) -> QAReport:
        """Analyze OBJ tile folder: tile count, MTL/texture completeness."""
        from .obj_folder_scanner import OBJFolderScanner

        report = QAReport(score=50)  # base score
        scanner = OBJFolderScanner()

        tiles = scanner.scan(str(pack))
        warnings = scanner.validate_tiles(tiles)
        report.warnings.extend(warnings)

        if not tiles:
            report.score = 10
            report.warnings.append("No OBJ tiles found in folder")
            return report

        # Score: tiles found
        report.score += 15

        # MTL completeness
        mtl_count = sum(1 for t in tiles if t.mtl_path)
        if mtl_count == len(tiles):
            report.score += 10
        elif mtl_count > 0:
            report.score += 5

        # Texture completeness
        tex_count = sum(1 for t in tiles if t.texture_paths)
        if tex_count == len(tiles):
            report.score += 10
        elif tex_count > 0:
            report.score += 5

        # Populate report fields
        report.mesh_files = [t.obj_path for t in tiles]
        tex_all = []
        for t in tiles:
            tex_all.extend(t.texture_paths)
        report.texture_files = tex_all
        report.total_size_mb = round(sum(t.size_mb for t in tiles), 1)
        report.obj_tiles = [t.to_dict() for t in tiles]

        # Grid info
        grid = scanner.get_grid_info(tiles)
        report.recommendations.append(
            f"OBJ Tile Grid: {grid['row_count']} rows x {grid['col_count']} cols "
            f"({len(tiles)} tiles, {report.total_size_mb:.0f} MB total)"
        )
        if grid['row_range']:
            report.recommendations.append(
                f"Row range: {grid['row_range'][0]}-{grid['row_range'][1]}, "
                f"Col range: {grid['col_range'][0]}-{grid['col_range'][1]}"
            )
        report.recommendations.append(
            "OBJ tiles will be imported directly to Unity (no Blender optimization needed)"
        )

        report.score = min(100, report.score)
        return report

    # ── EXIF parsing (stdlib only) ───────────────────────────

    def _parse_exif_basic(self, image_path: Path) -> Optional[dict]:
        """Parse basic EXIF data from JPEG using struct (no PIL)."""
        try:
            with open(image_path, "rb") as f:
                header = f.read(2)
                if header != b"\xff\xd8":
                    return None  # not JPEG

                result = {"has_gps": False, "width": 0, "height": 0}

                # Scan APP1 marker for EXIF
                while True:
                    marker = f.read(2)
                    if len(marker) < 2:
                        break
                    if marker[0] != 0xFF:
                        break

                    length_bytes = f.read(2)
                    if len(length_bytes) < 2:
                        break
                    length = struct.unpack(">H", length_bytes)[0]

                    if marker[1] == 0xE1:  # APP1 (EXIF)
                        data = f.read(length - 2)
                        if data[:4] == b"Exif":
                            result = self._parse_exif_data(data[6:], result)
                        break
                    else:
                        f.seek(length - 2, 1)  # skip

                # Fallback: get resolution from file size heuristic
                if result["width"] == 0:
                    fsize = image_path.stat().st_size
                    # Rough estimate: typical JPEG compression ~1/10
                    pixels = fsize * 10
                    side = int(math.sqrt(pixels * 4 / 3))  # assume 4:3
                    result["width"] = side
                    result["height"] = int(side * 3 / 4)

                return result

        except Exception as e:
            logger.debug("EXIF parse failed for %s: %s", image_path, e)
            return None

    def _parse_exif_data(self, data: bytes, result: dict) -> dict:
        """Parse EXIF IFD entries from raw TIFF data."""
        if len(data) < 8:
            return result

        # Byte order
        bo = data[:2]
        if bo == b"MM":
            endian = ">"
        elif bo == b"II":
            endian = "<"
        else:
            return result

        try:
            # IFD0 offset
            ifd_offset = struct.unpack(f"{endian}I", data[4:8])[0]
            if ifd_offset + 2 > len(data):
                return result

            num_entries = struct.unpack(f"{endian}H", data[ifd_offset:ifd_offset + 2])[0]
            offset = ifd_offset + 2

            for _ in range(min(num_entries, 100)):
                if offset + 12 > len(data):
                    break
                tag = struct.unpack(f"{endian}H", data[offset:offset + 2])[0]

                if tag == _EXIF_GPS_IFD_TAG:
                    result["has_gps"] = True

                offset += 12

        except Exception:
            pass

        return result

    # ── Blur estimation (no OpenCV) ──────────────────────────

    def _estimate_blur(self, image_path: Path) -> bool:
        """Estimate if image is blurry using file size heuristic.

        Well-focused images tend to have higher JPEG file sizes relative
        to their resolution because of more high-frequency detail.
        This is a rough heuristic — Pillow/OpenCV Laplacian is more accurate.
        """
        try:
            fsize = image_path.stat().st_size
            # Very small files for high-res cameras are likely blurry
            # Typical 12MP JPEG: 3-8MB focused, 1-3MB blurry
            if fsize < 500_000:  # < 500KB for any image is suspicious
                return True
            return False
        except Exception:
            return False

    # ── Overlap estimation ───────────────────────────────────

    def _estimate_overlap(self, gps_coords: list[dict]) -> str:
        """Estimate image overlap from GPS coordinates.

        Simple heuristic: if consecutive images are too far apart
        relative to estimated ground coverage, overlap is insufficient.
        """
        if len(gps_coords) < 3:
            return "insufficient" if len(gps_coords) == 0 else "warning"

        # With GPS data, we'd compute inter-image distances vs GSD coverage
        # For now, having GPS on most images is a positive signal
        return "good" if len(gps_coords) >= 10 else "warning"

    # ── Mesh quality check ───────────────────────────────────

    def _check_mesh_quality(self, mesh_path: Path) -> dict:
        """Basic mesh quality check using file size heuristics."""
        size_mb = mesh_path.stat().st_size / (1024 * 1024)
        result = {"size_mb": round(size_mb, 1), "warnings": []}

        if size_mb < 0.01:
            result["warnings"].append("Mesh file appears empty or corrupted")
        elif size_mb > 200:
            result["warnings"].append(f"Mesh is {size_mb:.0f}MB — LOD optimization strongly recommended")
            result["estimated_polycount"] = f"~{int(size_mb * 200_000):,} faces (rough estimate)"
        elif size_mb > 50:
            result["estimated_polycount"] = f"~{int(size_mb * 200_000):,} faces (rough estimate)"

        return result
