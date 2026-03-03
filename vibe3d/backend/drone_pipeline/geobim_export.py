"""GeoBIM Export — JSONL + folder structure for Unity import.

Section 3.5: Export rules
  - /export_unity/collider/tile_x_y_COLLIDER.fbx
  - /geobim_db/buildings.sqlite (copy) + buildings.jsonl
  - Summary report JSON
"""

import json
import logging
import shutil
import time
from pathlib import Path
from typing import Optional

from .geobim_db import get_db

logger = logging.getLogger("vibe3d.geobim.export")


class GeoBIMExporter:
    """Exports GeoBIM data to Unity-compatible folder structure."""

    def export_all(self, output_dir: str, collider_dir: Optional[str] = None) -> dict:
        """Export buildings.jsonl + buildings.sqlite + summary.json to output_dir."""
        t0 = time.time()
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        db = get_db()
        buildings = db.get_buildings(limit=10000)

        # ── 1. JSONL export ──
        jsonl_path = out / "buildings.jsonl"
        with open(jsonl_path, "w", encoding="utf-8") as f:
            for b in buildings:
                f.write(json.dumps(b.to_jsonl(), ensure_ascii=False) + "\n")
        logger.info(f"Exported {len(buildings)} buildings to {jsonl_path}")

        # ── 2. Copy SQLite DB ──
        geobim_db_dir = out / "geobim_db"
        geobim_db_dir.mkdir(exist_ok=True)
        db_src = db.db_path
        db_dst = geobim_db_dir / "buildings.sqlite"
        if db_src.exists():
            shutil.copy2(str(db_src), str(db_dst))
            logger.info(f"Copied database to {db_dst}")

        # ── 3. Copy collider proxies ──
        collider_count = 0
        if collider_dir:
            collider_src = Path(collider_dir)
            collider_dst = out / "collider"
            collider_dst.mkdir(exist_ok=True)
            for f in collider_src.glob("*_COLLIDER.*"):
                shutil.copy2(str(f), str(collider_dst / f.name))
                collider_count += 1
            logger.info(f"Copied {collider_count} collider proxies")

        # ── 4. Summary report ──
        summary = db.get_summary()
        summary["export_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
        summary["collider_count"] = collider_count
        summary["output_dir"] = str(out)

        summary_path = out / "geobim_summary.json"
        with open(summary_path, "w", encoding="utf-8") as f:
            f.write(json.dumps(summary, indent=2, ensure_ascii=False))

        # ── 5. Measurement results template ──
        measurements_path = out / "measurements.json"
        if not measurements_path.exists():
            with open(measurements_path, "w") as f:
                json.dump({"measurements": [], "exported_at": summary["export_time"]}, f, indent=2)

        elapsed = time.time() - t0
        result = {
            "success": True,
            "buildings_exported": len(buildings),
            "colliders_exported": collider_count,
            "output_dir": str(out),
            "files": {
                "jsonl": str(jsonl_path),
                "sqlite": str(db_dst),
                "summary": str(summary_path),
                "measurements": str(measurements_path),
            },
            "processing_time_s": round(elapsed, 2),
        }
        logger.info(f"GeoBIM export complete: {len(buildings)} buildings in {elapsed:.1f}s")
        return result

    def export_measurements(self, measurements: list[dict], output_path: str, fmt: str = "json") -> str:
        """Export measurement results to JSON or CSV."""
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        if fmt == "csv":
            import csv
            fieldnames = ["type", "value", "unit", "points", "timestamp"]
            with open(out, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                for m in measurements:
                    writer.writerow({
                        "type": m.get("type", ""),
                        "value": m.get("value", 0),
                        "unit": m.get("unit", "m"),
                        "points": json.dumps(m.get("points", [])),
                        "timestamp": m.get("timestamp", ""),
                    })
        else:
            with open(out, "w", encoding="utf-8") as f:
                json.dump({"measurements": measurements}, f, indent=2, ensure_ascii=False)

        logger.info(f"Exported {len(measurements)} measurements to {out}")
        return str(out)


# ── Singleton ───────────────────────────────────────────────

_exporter: Optional[GeoBIMExporter] = None


def get_exporter() -> GeoBIMExporter:
    global _exporter
    if _exporter is None:
        _exporter = GeoBIMExporter()
    return _exporter
