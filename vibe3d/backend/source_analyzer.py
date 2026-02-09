"""Source file quality analysis engine for Vibe3D Unity Accelerator.

Analyzes source files (3D models, textures, data files, drawings) for quality,
compatibility, and readiness for Unity import. Generates actionable
recommendations and optional import/placement plans.
"""

import csv
import io
import json
import logging
import os
import struct
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── File type extension mappings ──────────────────────────────

MODEL_EXTENSIONS = {".fbx", ".obj", ".glb", ".gltf", ".blend", ".3ds", ".dae"}
TEXTURE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tga", ".bmp"}
DATA_EXTENSIONS = {".csv", ".json", ".xml", ".yaml"}
DRAWING_EXTENSIONS = {".dwg", ".dxf", ".pdf"}

# Common texture companion extensions for 3D models
TEXTURE_COMPANION_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tga", ".bmp", ".tif", ".psd"}


def _classify_extension(ext: str) -> str:
    """Classify a file extension into a category string."""
    ext_lower = ext.lower()
    if ext_lower in MODEL_EXTENSIONS:
        return "3d_model"
    if ext_lower in TEXTURE_EXTENSIONS:
        return "texture"
    if ext_lower in DATA_EXTENSIONS:
        return "data"
    if ext_lower in DRAWING_EXTENSIONS:
        return "drawing"
    return "other"


# ── Data class ────────────────────────────────────────────────


@dataclass
class SourceAnalysis:
    """Result of analyzing a single source file."""

    file_path: str
    file_type: str          # category: "3d_model", "texture", "data", "drawing", "other"
    score: int              # 0-100 quality score
    issues: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    auto_fix_available: bool = False
    metadata: dict = field(default_factory=dict)


# ── PNG / JPG header parsing (stdlib only) ────────────────────


def _read_png_dimensions(file_path: str) -> Optional[tuple[int, int]]:
    """Read width and height from a PNG file header using struct."""
    try:
        with open(file_path, "rb") as f:
            header = f.read(24)
            if len(header) < 24:
                return None
            # PNG signature: 8 bytes, then IHDR chunk
            if header[:8] != b"\x89PNG\r\n\x1a\n":
                return None
            # IHDR chunk starts at offset 8: 4 bytes length, 4 bytes type, then data
            # Width at offset 16, height at offset 20 (big-endian 4-byte unsigned)
            width = struct.unpack(">I", header[16:20])[0]
            height = struct.unpack(">I", header[20:24])[0]
            return (width, height)
    except (OSError, struct.error):
        return None


def _read_jpg_dimensions(file_path: str) -> Optional[tuple[int, int]]:
    """Read width and height from a JPEG file by scanning for SOF markers."""
    try:
        with open(file_path, "rb") as f:
            data = f.read(2)
            if data != b"\xff\xd8":
                return None
            # Scan for SOF0/SOF2 markers
            while True:
                marker = f.read(2)
                if len(marker) < 2:
                    return None
                if marker[0] != 0xFF:
                    return None
                # SOF markers: C0 (baseline), C1 (extended), C2 (progressive)
                if marker[1] in (0xC0, 0xC1, 0xC2):
                    # Read SOF segment: length(2) + precision(1) + height(2) + width(2)
                    sof_data = f.read(7)
                    if len(sof_data) < 7:
                        return None
                    height = struct.unpack(">H", sof_data[3:5])[0]
                    width = struct.unpack(">H", sof_data[5:7])[0]
                    return (width, height)
                else:
                    # Skip this segment
                    length_data = f.read(2)
                    if len(length_data) < 2:
                        return None
                    seg_length = struct.unpack(">H", length_data)[0]
                    f.seek(seg_length - 2, 1)
    except (OSError, struct.error):
        return None


def _is_power_of_two(n: int) -> bool:
    """Check if n is a power of 2."""
    return n > 0 and (n & (n - 1)) == 0


# ── Type-specific analyzers ───────────────────────────────────


def _analyze_3d_model(file_path: str, file_size: int) -> SourceAnalysis:
    """Analyze a 3D model file."""
    ext = os.path.splitext(file_path)[1].lower()
    issues: list[str] = []
    recommendations: list[str] = []
    score = 50  # baseline
    metadata: dict = {"extension": ext, "file_size_bytes": file_size}

    # Size-based heuristics
    size_mb = file_size / (1024 * 1024)
    metadata["file_size_mb"] = round(size_mb, 2)

    if file_size < 1024:
        issues.append("File size is suspiciously small (< 1 KB) -- may be empty or corrupt")
        score -= 30
    elif size_mb > 100:
        issues.append(f"File is very large ({size_mb:.1f} MB) -- may cause long import times")
        recommendations.append("Consider generating LOD (Level of Detail) variants for better performance")
        score -= 15
    elif size_mb > 50:
        recommendations.append("File is large; consider LOD generation for runtime performance")
        score -= 5
    else:
        score += 20  # reasonable size

    # Check for companion texture files in the same directory
    directory = os.path.dirname(file_path)
    base_name = os.path.splitext(os.path.basename(file_path))[0].lower()
    companion_textures: list[str] = []

    try:
        dir_entries = os.listdir(directory)
    except OSError:
        dir_entries = []

    for entry in dir_entries:
        entry_ext = os.path.splitext(entry)[1].lower()
        if entry_ext in TEXTURE_COMPANION_EXTENSIONS:
            companion_textures.append(entry)

    metadata["companion_textures"] = companion_textures

    if companion_textures:
        score += 15
        metadata["has_textures"] = True
    else:
        recommendations.append(
            "No texture files found in the same directory -- "
            "consider placing textures alongside the model for proper material import"
        )
        metadata["has_textures"] = False
        score -= 5

    # Format-specific notes
    if ext == ".blend":
        recommendations.append(
            "Blender files may require Blender installed for Unity import; "
            "consider exporting to FBX for broader compatibility"
        )
    elif ext == ".obj":
        # Check for .mtl companion
        mtl_path = os.path.splitext(file_path)[0] + ".mtl"
        if os.path.isfile(mtl_path):
            metadata["has_mtl"] = True
            score += 5
        else:
            metadata["has_mtl"] = False
            issues.append("No .mtl material file found alongside .obj -- materials may be missing")
    elif ext in (".glb", ".gltf"):
        score += 5  # glTF is well-supported and self-describing
        metadata["format_note"] = "glTF is a modern, well-supported format"

    score = max(0, min(100, score))

    return SourceAnalysis(
        file_path=file_path,
        file_type="3d_model",
        score=score,
        issues=issues,
        recommendations=recommendations,
        auto_fix_available=False,
        metadata=metadata,
    )


def _analyze_texture(file_path: str, file_size: int) -> SourceAnalysis:
    """Analyze a texture/image file."""
    ext = os.path.splitext(file_path)[1].lower()
    issues: list[str] = []
    recommendations: list[str] = []
    score = 50
    auto_fix = False
    metadata: dict = {"extension": ext, "file_size_bytes": file_size}

    size_mb = file_size / (1024 * 1024)
    metadata["file_size_mb"] = round(size_mb, 2)

    # Size checks
    if file_size < 100:
        issues.append("File is extremely small -- likely corrupt or placeholder")
        score -= 40
    elif size_mb > 50:
        issues.append(f"Texture file is very large ({size_mb:.1f} MB) -- will consume excessive memory")
        recommendations.append("Resize or compress the texture to reduce memory usage")
        auto_fix = True
        score -= 20
    elif size_mb > 10:
        recommendations.append("Texture is fairly large; consider compression")
        auto_fix = True
        score -= 5
    else:
        score += 15

    # Try to read dimensions
    dimensions: Optional[tuple[int, int]] = None

    if ext == ".png":
        dimensions = _read_png_dimensions(file_path)
    elif ext in (".jpg", ".jpeg"):
        dimensions = _read_jpg_dimensions(file_path)

    if dimensions:
        width, height = dimensions
        metadata["width"] = width
        metadata["height"] = height
        metadata["resolution"] = f"{width}x{height}"

        # Check power-of-2
        w_pot = _is_power_of_two(width)
        h_pot = _is_power_of_two(height)
        metadata["width_is_pot"] = w_pot
        metadata["height_is_pot"] = h_pot

        if w_pot and h_pot:
            score += 15
            metadata["pot_compliant"] = True
        else:
            metadata["pot_compliant"] = False
            recommendations.append(
                f"Dimensions ({width}x{height}) are not power-of-2 -- "
                "Unity will pad or rescale at import, which may waste memory. "
                "Consider resizing to nearest POT (e.g. 512, 1024, 2048, 4096)"
            )
            auto_fix = True
            score -= 5

        # Resolution quality scoring
        max_dim = max(width, height)
        if max_dim >= 4096:
            score += 10
            if max_dim > 8192:
                recommendations.append(
                    f"Resolution ({width}x{height}) is extremely high -- "
                    "consider if this detail level is necessary at runtime"
                )
        elif max_dim >= 2048:
            score += 10
        elif max_dim >= 1024:
            score += 5
        elif max_dim >= 512:
            pass  # neutral
        elif max_dim >= 128:
            score -= 5
            recommendations.append("Resolution is quite low -- may appear blurry on large surfaces")
        else:
            score -= 15
            issues.append("Resolution is very low -- quality will be poor")
    else:
        if ext in (".png", ".jpg", ".jpeg"):
            issues.append("Could not read image dimensions from file header")
            score -= 10
        # For TGA/BMP we simply skip dimension analysis
        metadata["dimensions_parsed"] = False

    # Format-specific notes
    if ext == ".tga":
        recommendations.append(
            "TGA format is uncompressed and large on disk; "
            "consider converting to PNG for better compression"
        )
        auto_fix = True
    elif ext == ".bmp":
        recommendations.append(
            "BMP format is uncompressed; consider converting to PNG"
        )
        auto_fix = True

    score = max(0, min(100, score))

    return SourceAnalysis(
        file_path=file_path,
        file_type="texture",
        score=score,
        issues=issues,
        recommendations=recommendations,
        auto_fix_available=auto_fix,
        metadata=metadata,
    )


def _analyze_data_file(file_path: str, file_size: int) -> SourceAnalysis:
    """Analyze a data file (CSV, JSON, XML, YAML)."""
    ext = os.path.splitext(file_path)[1].lower()
    issues: list[str] = []
    recommendations: list[str] = []
    score = 50
    metadata: dict = {"extension": ext, "file_size_bytes": file_size}

    if file_size == 0:
        issues.append("File is empty")
        return SourceAnalysis(
            file_path=file_path,
            file_type="data",
            score=5,
            issues=issues,
            recommendations=["Provide a non-empty data file"],
            auto_fix_available=False,
            metadata=metadata,
        )

    # Read file content (cap at 5 MB to avoid memory issues)
    content: Optional[str] = None
    if file_size <= 5 * 1024 * 1024:
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError as exc:
            issues.append(f"Could not read file: {exc}")
            return SourceAnalysis(
                file_path=file_path,
                file_type="data",
                score=10,
                issues=issues,
                recommendations=[],
                auto_fix_available=False,
                metadata=metadata,
            )
    else:
        issues.append(f"Data file is very large ({file_size / (1024*1024):.1f} MB)")
        recommendations.append("Consider splitting large data files for faster processing")
        score -= 10

    if ext == ".csv" and content is not None:
        score, issues, recommendations, metadata = _analyze_csv(
            content, score, issues, recommendations, metadata
        )
    elif ext == ".json" and content is not None:
        score, issues, recommendations, metadata = _analyze_json(
            content, score, issues, recommendations, metadata
        )
    elif ext == ".xml" and content is not None:
        score, issues, recommendations, metadata = _analyze_xml(
            content, score, issues, recommendations, metadata
        )
    elif ext == ".yaml" and content is not None:
        # YAML parsing requires PyYAML which may not be available;
        # do basic checks
        metadata["format"] = "yaml"
        if content.strip():
            score += 20
            line_count = content.count("\n") + 1
            metadata["line_count"] = line_count
        else:
            issues.append("YAML file appears empty or whitespace-only")
            score -= 20

    score = max(0, min(100, score))

    return SourceAnalysis(
        file_path=file_path,
        file_type="data",
        score=score,
        issues=issues,
        recommendations=recommendations,
        auto_fix_available=False,
        metadata=metadata,
    )


def _analyze_csv(
    content: str,
    score: int,
    issues: list[str],
    recommendations: list[str],
    metadata: dict,
) -> tuple[int, list[str], list[str], dict]:
    """Analyze CSV content in detail."""
    try:
        reader = csv.reader(io.StringIO(content))
        rows = list(reader)
    except csv.Error as exc:
        issues.append(f"CSV parsing error: {exc}")
        return score - 20, issues, recommendations, metadata

    if not rows:
        issues.append("CSV file has no rows")
        return score - 30, issues, recommendations, metadata

    header = rows[0]
    data_rows = rows[1:]

    metadata["format"] = "csv"
    metadata["columns"] = header
    metadata["column_count"] = len(header)
    metadata["row_count"] = len(data_rows)

    score += 20  # parseable

    if not data_rows:
        issues.append("CSV file has headers but no data rows")
        score -= 10

    # Check for inconsistent column counts
    expected_cols = len(header)
    inconsistent_rows = [
        i + 2 for i, row in enumerate(data_rows)
        if len(row) != expected_cols
    ]
    if inconsistent_rows:
        sample = inconsistent_rows[:5]
        issues.append(
            f"Inconsistent column count in {len(inconsistent_rows)} rows "
            f"(expected {expected_cols}): rows {sample}"
        )
        score -= 10

    # Check for empty headers
    empty_headers = [i for i, h in enumerate(header) if not h.strip()]
    if empty_headers:
        issues.append(f"Empty header names at column indices: {empty_headers}")
        score -= 5

    # Check for known schema fields (common in plant/engineering data)
    known_fields = {
        "id", "name", "type", "value", "unit", "timestamp", "temperature",
        "pressure", "flow_rate", "status", "position", "x", "y", "z",
    }
    header_lower = {h.strip().lower() for h in header}
    matches = header_lower & known_fields
    if matches:
        metadata["recognized_fields"] = sorted(matches)
        score += 5

    return score, issues, recommendations, metadata


def _analyze_json(
    content: str,
    score: int,
    issues: list[str],
    recommendations: list[str],
    metadata: dict,
) -> tuple[int, list[str], list[str], dict]:
    """Analyze JSON content in detail."""
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        issues.append(f"Invalid JSON: {exc}")
        recommendations.append("Fix JSON syntax errors before import")
        return score - 30, issues, recommendations, metadata

    metadata["format"] = "json"
    score += 20  # parseable

    if isinstance(data, dict):
        metadata["top_level_type"] = "object"
        metadata["top_level_keys"] = list(data.keys())[:20]
        metadata["key_count"] = len(data)

        # Check for known schema patterns
        known_schema = {
            "project", "scene", "actions", "name", "type", "version",
            "config", "settings", "objects", "components", "materials",
        }
        found_keys = set(data.keys()) & known_schema
        if found_keys:
            metadata["recognized_schema_keys"] = sorted(found_keys)
            score += 10
    elif isinstance(data, list):
        metadata["top_level_type"] = "array"
        metadata["array_length"] = len(data)
        if data and isinstance(data[0], dict):
            metadata["item_keys_sample"] = list(data[0].keys())[:15]
        if not data:
            issues.append("JSON array is empty")
            score -= 5
    else:
        metadata["top_level_type"] = type(data).__name__
        recommendations.append(
            "JSON top-level value is a scalar; expected object or array"
        )

    return score, issues, recommendations, metadata


def _analyze_xml(
    content: str,
    score: int,
    issues: list[str],
    recommendations: list[str],
    metadata: dict,
) -> tuple[int, list[str], list[str], dict]:
    """Analyze XML content in detail."""
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        issues.append(f"Invalid XML: {exc}")
        recommendations.append("Fix XML syntax errors before import")
        return score - 30, issues, recommendations, metadata

    metadata["format"] = "xml"
    metadata["root_tag"] = root.tag
    metadata["child_count"] = len(root)

    score += 20  # parseable

    # Collect unique child tag names
    child_tags = sorted({child.tag for child in root})
    metadata["child_tags"] = child_tags[:20]

    return score, issues, recommendations, metadata


# ── Vessel/equipment recognition from filenames ──────────────

# Known vessel specs from P&ID analysis (CBF-2009)
VESSEL_DATABASE: dict[str, dict] = {
    # Fermentors
    "70L-FER":   {"name": "KF-70L",    "type": "fermentor",  "volume_L": 70,   "diameter_mm": 400,  "height_m": 0.8,  "color": "stainless"},
    "700-FER":   {"name": "KF-700L",   "type": "fermentor",  "volume_L": 700,  "diameter_mm": 800,  "height_m": 1.6,  "color": "stainless"},
    "700FER":    {"name": "KF-700L",   "type": "fermentor",  "volume_L": 700,  "diameter_mm": 800,  "height_m": 1.6,  "color": "stainless"},
    "7KL-FER":   {"name": "KF-7KL",    "type": "fermentor",  "volume_L": 7000, "diameter_mm": 1800, "height_m": 3.0,  "color": "stainless"},
    # Feed tanks
    "70L-FEED":  {"name": "KF-70L-FD", "type": "feed_tank",  "volume_L": 100,  "diameter_mm": 420,  "height_m": 0.9,  "color": "steel"},
    "500L-FEED": {"name": "KF-500L-FD","type": "feed_tank",  "volume_L": 500,  "diameter_mm": 750,  "height_m": 1.3,  "color": "steel"},
    "4KL-FEED":  {"name": "KF-4KL-FD", "type": "feed_tank",  "volume_L": 4000, "diameter_mm": 1500, "height_m": 2.5,  "color": "steel"},
    # Broth tank
    "7KL-BROTH": {"name": "KF-7000L",  "type": "broth_tank", "volume_L": 7000, "diameter_mm": 1800, "height_m": 3.0,  "color": "copper"},
}

# Filename pattern → vessel key mapping
import re as _re
_VESSEL_PATTERNS: list[tuple[str, str]] = [
    (r"4KL[-_ ]?FEED",  "4KL-FEED"),
    (r"500L?[-_ ]?FEED", "500L-FEED"),
    (r"70L[-_ ]?FEED",  "70L-FEED"),
    (r"7KL[-_ ]?BROTH", "7KL-BROTH"),
    (r"7KL[-_ ]?FER",   "7KL-FER"),
    (r"700[-_ ]?FER",   "700-FER"),
    (r"70L[-_ ]?FER",   "70L-FER"),
]


def _extract_vessel_from_filename(file_path: str) -> Optional[dict]:
    """Extract vessel/equipment info from a DWG filename.

    Matches known fermentation vessel patterns against the file basename.
    Returns vessel spec dict or None.
    """
    basename = os.path.splitext(os.path.basename(file_path))[0].upper()
    for pattern, vessel_key in _VESSEL_PATTERNS:
        if _re.search(pattern, basename, _re.IGNORECASE):
            vessel = VESSEL_DATABASE.get(vessel_key)
            if vessel:
                return dict(vessel)  # return a copy
    return None


def _analyze_drawing(file_path: str, file_size: int) -> SourceAnalysis:
    """Analyze a drawing file (DWG, DXF, PDF)."""
    ext = os.path.splitext(file_path)[1].lower()
    issues: list[str] = []
    recommendations: list[str] = []
    score = 40
    auto_fix = False
    metadata: dict = {"extension": ext, "file_size_bytes": file_size}

    if file_size == 0:
        issues.append("File is empty")
        return SourceAnalysis(
            file_path=file_path,
            file_type="drawing",
            score=5,
            issues=issues,
            recommendations=[],
            auto_fix_available=False,
            metadata=metadata,
        )

    if ext == ".dwg":
        # DWG is a proprietary binary format; ezdxf cannot read it
        metadata["format"] = "dwg"
        metadata["binary_format"] = True
        issues.append(
            "DWG is a proprietary binary format -- "
            "ezdxf and most open-source tools cannot read it directly"
        )
        recommendations.append(
            "Convert DWG to DXF using AutoCAD, ODA File Converter, or similar tool "
            "for automated layer extraction"
        )
        # We can still give a baseline score from file size
        if file_size > 1024:
            score += 10  # at least it's not empty
        auto_fix = False

        # Extract vessel/equipment info from DWG filename
        vessel_info = _extract_vessel_from_filename(file_path)
        if vessel_info:
            metadata["vessel_info"] = vessel_info
            score += 15  # bonus for recognized vessel type
            recommendations.append(
                f"Recognized vessel: {vessel_info['name']} "
                f"({vessel_info['volume_L']}L, φ{vessel_info['diameter_mm']}mm) -- "
                "can create 3D representation from P&ID specs"
            )

    elif ext == ".dxf":
        metadata["format"] = "dxf"
        # Try ezdxf if available
        try:
            import ezdxf  # type: ignore[import-untyped]
            doc = ezdxf.readfile(file_path)
            layers = list(doc.layers)
            metadata["layer_count"] = len(layers)
            metadata["layer_names"] = [layer.dxf.name for layer in layers][:30]

            # Count entities in modelspace
            msp = doc.modelspace()
            entity_count = len(list(msp))
            metadata["entity_count"] = entity_count

            score += 25  # readable + has content
            if entity_count == 0:
                issues.append("DXF file has no entities in modelspace")
                score -= 10
            elif entity_count > 50000:
                recommendations.append(
                    f"DXF has {entity_count} entities -- consider simplifying for Unity import"
                )
        except ImportError:
            metadata["ezdxf_available"] = False
            recommendations.append(
                "Install ezdxf (pip install ezdxf) for detailed DXF analysis"
            )
            # Basic size-based score
            if file_size > 1024:
                score += 10
        except Exception as exc:
            issues.append(f"Failed to parse DXF: {exc}")
            score -= 10

    elif ext == ".pdf":
        metadata["format"] = "pdf"

        # Try to determine page count by reading PDF trailer/cross-ref
        page_count = _estimate_pdf_pages(file_path)
        if page_count is not None:
            metadata["estimated_page_count"] = page_count
            score += 15
        else:
            metadata["estimated_page_count"] = None

        # Check for pre-rendered PNG versions alongside the PDF
        directory = os.path.dirname(file_path)
        base_name = os.path.splitext(os.path.basename(file_path))[0].lower()
        rendered_pngs: list[str] = []
        try:
            for entry in os.listdir(directory):
                entry_lower = entry.lower()
                entry_base = os.path.splitext(entry_lower)[0]
                entry_ext = os.path.splitext(entry_lower)[1]
                if entry_ext == ".png" and base_name in entry_base:
                    rendered_pngs.append(entry)
        except OSError:
            pass

        metadata["rendered_pngs"] = rendered_pngs
        if rendered_pngs:
            score += 10
            metadata["has_rendered_versions"] = True
        else:
            metadata["has_rendered_versions"] = False
            recommendations.append(
                "No pre-rendered PNG found for this PDF -- "
                "consider rendering pages to PNG for direct use as textures in Unity"
            )
            auto_fix = True

    score = max(0, min(100, score))

    return SourceAnalysis(
        file_path=file_path,
        file_type="drawing",
        score=score,
        issues=issues,
        recommendations=recommendations,
        auto_fix_available=auto_fix,
        metadata=metadata,
    )


def _estimate_pdf_pages(file_path: str) -> Optional[int]:
    """Estimate PDF page count by scanning for /Type /Page entries.

    This is a heuristic -- it scans raw bytes for the pattern.
    Not 100% reliable but works for most simple PDFs without external libs.
    """
    try:
        with open(file_path, "rb") as f:
            # Read up to 2 MB for the search
            data = f.read(2 * 1024 * 1024)

        # Look for /Count N in the Pages dictionary
        # Pattern: /Type /Pages ... /Count <number>
        import re
        # Search for /Count followed by a number in the Pages dict
        matches = re.findall(rb"/Type\s*/Pages\b.*?/Count\s+(\d+)", data, re.DOTALL)
        if matches:
            # Return the largest count found (the root Pages node)
            return max(int(m) for m in matches)

        # Fallback: count /Type /Page occurrences (excluding /Pages)
        page_count = len(re.findall(rb"/Type\s*/Page\b(?!s)", data))
        return page_count if page_count > 0 else None
    except OSError:
        return None


def _analyze_other(file_path: str, file_size: int) -> SourceAnalysis:
    """Basic analysis for unrecognized file types."""
    ext = os.path.splitext(file_path)[1].lower()
    metadata: dict = {
        "extension": ext or "(no extension)",
        "file_size_bytes": file_size,
    }
    issues: list[str] = []
    recommendations: list[str] = []
    score = 30  # low baseline for unknown types

    if file_size == 0:
        issues.append("File is empty")
        score = 5
    elif file_size > 100 * 1024 * 1024:
        issues.append(f"File is very large ({file_size / (1024*1024):.1f} MB)")
        score = 15
    else:
        score = 40

    recommendations.append(
        f"File type '{ext or 'unknown'}' is not specifically supported -- "
        "manual review recommended before Unity import"
    )

    return SourceAnalysis(
        file_path=file_path,
        file_type="other",
        score=score,
        issues=issues,
        recommendations=recommendations,
        auto_fix_available=False,
        metadata=metadata,
    )


# ── Public API ────────────────────────────────────────────────


def analyze_file(file_path: str) -> SourceAnalysis:
    """Analyze a single source file for quality and Unity import readiness.

    Detects file type by extension and delegates to the appropriate
    type-specific analyzer.

    Args:
        file_path: Absolute or relative path to the file.

    Returns:
        A SourceAnalysis with score, issues, and recommendations.
    """
    logger.debug("Analyzing file: %s", file_path)

    # Existence check
    if not os.path.isfile(file_path):
        logger.warning("File not found: %s", file_path)
        return SourceAnalysis(
            file_path=file_path,
            file_type="unknown",
            score=0,
            issues=["File does not exist"],
            recommendations=["Verify the file path and ensure the file is accessible"],
            auto_fix_available=False,
            metadata={},
        )

    try:
        file_size = os.path.getsize(file_path)
    except OSError as exc:
        logger.warning("Cannot stat file %s: %s", file_path, exc)
        return SourceAnalysis(
            file_path=file_path,
            file_type="unknown",
            score=0,
            issues=[f"Cannot read file stats: {exc}"],
            recommendations=[],
            auto_fix_available=False,
            metadata={},
        )

    ext = os.path.splitext(file_path)[1].lower()
    file_type = _classify_extension(ext)

    try:
        if file_type == "3d_model":
            return _analyze_3d_model(file_path, file_size)
        elif file_type == "texture":
            return _analyze_texture(file_path, file_size)
        elif file_type == "data":
            return _analyze_data_file(file_path, file_size)
        elif file_type == "drawing":
            return _analyze_drawing(file_path, file_size)
        else:
            return _analyze_other(file_path, file_size)
    except Exception as exc:
        logger.exception("Unexpected error analyzing %s", file_path)
        return SourceAnalysis(
            file_path=file_path,
            file_type=file_type,
            score=0,
            issues=[f"Analysis failed with unexpected error: {exc}"],
            recommendations=["Check file integrity and try again"],
            auto_fix_available=False,
            metadata={"extension": ext},
        )


def source_to_plan(file_path: str, analysis: SourceAnalysis) -> Optional[dict]:
    """Generate a Unity import/action plan based on the source analysis.

    Args:
        file_path: Path to the analyzed source file.
        analysis: The SourceAnalysis result from analyze_file().

    Returns:
        A plan dict compatible with the Vibe3D plan executor, or None if
        no plan can be generated for the given file type.
    """
    file_name = os.path.basename(file_path)
    base_name = os.path.splitext(file_name)[0]

    if analysis.file_type == "3d_model":
        # Import the model and place it at origin
        plan: dict = {
            "project": "My project",
            "scene": "bio-plants",
            "description": f"Import 3D model: {file_name}",
            "source_file": file_path,
            "actions": [
                {
                    "type": "import_asset",
                    "source_path": file_path,
                    "destination": f"Assets/Models/{file_name}",
                    "asset_type": "model",
                },
                {
                    "type": "instantiate_prefab",
                    "asset_path": f"Assets/Models/{base_name}",
                    "name": base_name,
                    "position": {"x": 0, "y": 0, "z": 0},
                    "rotation": {"x": 0, "y": 0, "z": 0},
                    "scale": {"x": 1, "y": 1, "z": 1},
                },
            ],
        }
        # If companion textures exist, add material setup actions
        companion_textures = analysis.metadata.get("companion_textures", [])
        if companion_textures:
            for tex_file in companion_textures[:5]:  # limit to first 5
                plan["actions"].insert(1, {
                    "type": "import_asset",
                    "source_path": os.path.join(os.path.dirname(file_path), tex_file),
                    "destination": f"Assets/Textures/{tex_file}",
                    "asset_type": "texture",
                })
        return plan

    elif analysis.file_type == "texture":
        # Generate material application plan
        width = analysis.metadata.get("width")
        height = analysis.metadata.get("height")
        plan = {
            "project": "My project",
            "scene": "bio-plants",
            "description": f"Import texture and create material: {file_name}",
            "source_file": file_path,
            "actions": [
                {
                    "type": "import_asset",
                    "source_path": file_path,
                    "destination": f"Assets/Textures/{file_name}",
                    "asset_type": "texture",
                },
                {
                    "type": "create_material",
                    "name": f"Mat_{base_name}",
                    "shader": "Standard",
                    "main_texture": f"Assets/Textures/{file_name}",
                },
            ],
        }
        if width and height:
            plan["actions"][0]["metadata"] = {
                "width": width,
                "height": height,
                "pot_compliant": analysis.metadata.get("pot_compliant", False),
            }
        return plan

    elif analysis.file_type == "data":
        # Generate configuration plan
        plan = {
            "project": "My project",
            "scene": "bio-plants",
            "description": f"Load configuration data: {file_name}",
            "source_file": file_path,
            "actions": [
                {
                    "type": "load_config",
                    "source_path": file_path,
                    "format": analysis.metadata.get("format", "unknown"),
                },
            ],
        }
        # Add column/key info to help downstream processing
        if "columns" in analysis.metadata:
            plan["actions"][0]["columns"] = analysis.metadata["columns"]
        if "top_level_keys" in analysis.metadata:
            plan["actions"][0]["schema_keys"] = analysis.metadata["top_level_keys"]
        return plan

    # Drawings and other types: no automated plan
    logger.debug("No plan generation available for file type: %s", analysis.file_type)
    return None


def batch_analyze(directory: str) -> list[SourceAnalysis]:
    """Analyze all files in a directory (non-recursive).

    Args:
        directory: Path to the directory to scan.

    Returns:
        A list of SourceAnalysis results, one per file found.
        Returns an empty list if the directory does not exist or is empty.
    """
    logger.info("Batch analyzing directory: %s", directory)

    if not os.path.isdir(directory):
        logger.warning("Directory does not exist: %s", directory)
        return []

    results: list[SourceAnalysis] = []

    try:
        entries = sorted(os.listdir(directory))
    except OSError as exc:
        logger.error("Cannot list directory %s: %s", directory, exc)
        return []

    for entry in entries:
        full_path = os.path.join(directory, entry)
        if os.path.isfile(full_path):
            analysis = analyze_file(full_path)
            results.append(analysis)

    logger.info(
        "Batch analysis complete: %d files, avg score %.1f",
        len(results),
        sum(r.score for r in results) / len(results) if results else 0,
    )

    return results
