"""Data recorder for simulation time-series logging.

Buffers sensor data and flushes to database in batches.
"""

from collections import deque
from datetime import datetime, timezone


class DataRecorder:
    """Buffers simulation data for batch database insertion."""

    def __init__(self, buffer_size: int = 100):
        self.buffer_size = buffer_size
        self._buffer: deque[dict] = deque(maxlen=buffer_size * 2)
        self._total_records = 0

    def record(self, simulation_id: str, simulation_time: float, state: dict):
        """Record a simulation state snapshot."""
        record = {
            "simulation_id": simulation_id,
            "simulation_time": simulation_time,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **self._flatten(state),
        }
        self._buffer.append(record)
        self._total_records += 1

        if len(self._buffer) >= self.buffer_size:
            return self.flush()
        return []

    def flush(self) -> list[dict]:
        """Flush buffer and return records for database insertion."""
        records = list(self._buffer)
        self._buffer.clear()
        return records

    @staticmethod
    def _flatten(d: dict, prefix: str = "") -> dict:
        """Flatten nested dict with dot-separated keys."""
        items = {}
        for k, v in d.items():
            key = f"{prefix}{k}" if not prefix else f"{prefix}.{k}"
            if isinstance(v, dict):
                items.update(DataRecorder._flatten(v, key))
            else:
                items[key] = v
        return items

    @property
    def total_records(self) -> int:
        return self._total_records
