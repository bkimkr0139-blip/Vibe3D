"""WebGL build performance analysis for Drone2Twin pipeline.

Analyzes build output to estimate loading times and identify
potential performance issues.
"""

import json
import logging
from pathlib import Path
from typing import Optional

from .models import PerfReport

logger = logging.getLogger(__name__)

# ── Network speed constants (bytes/sec) ──────────────────────

SPEED_3G = 125_000        # 1 Mbps
SPEED_4G = 1_250_000      # 10 Mbps
SPEED_WIFI = 6_250_000    # 50 Mbps

# ── Thresholds ───────────────────────────────────────────────

WARN_TOTAL_MB = 50        # warn if total build > 50MB
WARN_WASM_MB = 20         # warn if .wasm > 20MB
WARN_DATA_MB = 30         # warn if .data > 30MB
WARN_LOAD_3G_SEC = 60     # warn if 3G load > 60s


class PerfReporter:
    """Analyze WebGL build output for performance metrics."""

    def analyze_build(self, build_dir: str) -> PerfReport:
        """Scan build directory and produce performance report."""
        build = Path(build_dir)
        if not build.is_dir():
            return PerfReport(warnings=[f"Build directory not found: {build_dir}"])

        report = PerfReport()

        # Scan all files
        total_bytes = 0
        wasm_bytes = 0
        data_bytes = 0
        js_bytes = 0
        texture_count = 0
        lod_count = 0

        for f in build.rglob("*"):
            if not f.is_file():
                continue
            size = f.stat().st_size
            total_bytes += size
            ext = f.suffix.lower()

            if ext == ".wasm" or ext == ".wasm.br" or ext == ".wasm.gz":
                wasm_bytes += size
            elif ext == ".data" or ext == ".data.br" or ext == ".data.gz":
                data_bytes += size
            elif ext in (".js", ".js.br", ".js.gz"):
                js_bytes += size
            elif ext in (".ktx2", ".basis"):
                texture_count += 1
            elif ext in (".png", ".jpg", ".jpeg") and "texture" in str(f).lower():
                texture_count += 1

            # LOD files
            if "lod" in f.stem.lower() and ext in (".glb", ".gltf", ".fbx"):
                lod_count += 1

        # Size metrics (MB)
        report.total_size_mb = round(total_bytes / (1024 * 1024), 1)
        report.wasm_size_mb = round(wasm_bytes / (1024 * 1024), 1)
        report.data_size_mb = round(data_bytes / (1024 * 1024), 1)
        report.js_size_mb = round(js_bytes / (1024 * 1024), 1)
        report.texture_count = texture_count
        report.lod_files = lod_count

        # Loading time estimates
        report.estimated_load_time_3g = self._format_time(total_bytes / SPEED_3G)
        report.estimated_load_time_4g = self._format_time(total_bytes / SPEED_4G)
        report.estimated_load_time_wifi = self._format_time(total_bytes / SPEED_WIFI)

        # Warnings
        if report.total_size_mb > WARN_TOTAL_MB:
            report.warnings.append(
                f"Total build size {report.total_size_mb}MB exceeds {WARN_TOTAL_MB}MB threshold — "
                "consider Addressables streaming to reduce initial load"
            )
        if report.wasm_size_mb > WARN_WASM_MB:
            report.warnings.append(
                f"WASM size {report.wasm_size_mb}MB exceeds {WARN_WASM_MB}MB — "
                "enable code stripping (High) in Unity Build Settings"
            )
        if report.data_size_mb > WARN_DATA_MB:
            report.warnings.append(
                f"Data file {report.data_size_mb}MB exceeds {WARN_DATA_MB}MB — "
                "use Addressables to split data loading"
            )
        load_3g_sec = total_bytes / SPEED_3G
        if load_3g_sec > WARN_LOAD_3G_SEC:
            report.warnings.append(
                f"Estimated 3G load time {self._format_time(load_3g_sec)} exceeds {WARN_LOAD_3G_SEC}s — "
                "optimize for mobile users"
            )
        if texture_count == 0 and report.data_size_mb > 5:
            report.warnings.append(
                "No KTX2/Basis textures found — consider texture compression for WebGL"
            )

        logger.info(
            "PerfReport: %.1fMB total (wasm=%.1f, data=%.1f, js=%.1f), "
            "%d textures, %d LODs, WiFi load ~%s",
            report.total_size_mb, report.wasm_size_mb, report.data_size_mb,
            report.js_size_mb, texture_count, lod_count,
            report.estimated_load_time_wifi,
        )
        return report

    def generate_report_file(self, build_dir: str, report: PerfReport, output_dir: Optional[str] = None):
        """Save performance report as JSON."""
        out = Path(output_dir or build_dir)
        out.mkdir(parents=True, exist_ok=True)
        path = out / "webgl_perf_report.json"

        with open(path, "w", encoding="utf-8") as f:
            json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)

        logger.info("Performance report saved: %s", path)
        return str(path)

    @staticmethod
    def _format_time(seconds: float) -> str:
        """Format seconds into human-readable string."""
        if seconds < 1:
            return "<1s"
        if seconds < 60:
            return f"{int(seconds)}s"
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}m{secs}s"
