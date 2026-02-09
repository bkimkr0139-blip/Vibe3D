"""
Virtual sensor model — adds measurement realism to physics outputs.

Features:
  - First-order lag filter (sensor response time)
  - Gaussian noise
  - Linear drift
  - Fault injection (stuck, spike, fast drift)
"""

import math
import random


# Sensor profiles for fermentation instrumentation
SENSOR_PROFILES = {
    "pH": {
        "noise_std": 0.02,
        "lag_tau": 5.0,        # seconds
        "drift_rate": 0.0001,  # units/hour
        "range_min": 0.0,
        "range_max": 14.0,
        "unit": "pH",
    },
    "DO": {
        "noise_std": 0.5,      # % saturation
        "lag_tau": 15.0,
        "drift_rate": 0.01,
        "range_min": 0.0,
        "range_max": 100.0,
        "unit": "% sat",
    },
    "temperature": {
        "noise_std": 0.1,      # °C
        "lag_tau": 3.0,
        "drift_rate": 0.005,
        "range_min": -10.0,
        "range_max": 200.0,
        "unit": "°C",
    },
    "pressure": {
        "noise_std": 0.005,    # bar
        "lag_tau": 0.5,
        "drift_rate": 0.0002,
        "range_min": 0.0,
        "range_max": 10.0,
        "unit": "bar",
    },
    "level": {
        "noise_std": 0.5,      # % of range
        "lag_tau": 2.0,
        "drift_rate": 0.001,
        "range_min": 0.0,
        "range_max": 100.0,
        "unit": "%",
    },
}


class VirtualSensor:
    """Simulates a real sensor with lag, noise, drift, and fault injection."""

    def __init__(self, sensor_type: str, params: dict | None = None):
        profile = SENSOR_PROFILES.get(sensor_type, SENSOR_PROFILES["temperature"])
        p = {**profile, **(params or {})}

        self.sensor_type = sensor_type
        self.noise_std = p["noise_std"]
        self.lag_tau = p["lag_tau"]
        self.drift_rate = p["drift_rate"]
        self.range_min = p["range_min"]
        self.range_max = p["range_max"]
        self.unit = p["unit"]

        # Internal state
        self._filtered_value = None
        self._drift_accumulated = 0.0
        self._time_h = 0.0

        # Fault state
        self._fault_type = None       # None, "stuck", "spike", "drift_fast"
        self._stuck_value = None
        self._spike_magnitude = 0.0
        self._spike_remaining_s = 0.0
        self._drift_fast_rate = 0.0

    def read(self, true_value: float, dt: float) -> float:
        """
        Process true physics value through sensor model.
        dt in seconds.
        """
        dt_h = dt / 3600.0

        # First-order lag filter
        if self._filtered_value is None:
            self._filtered_value = true_value
        else:
            if self.lag_tau > 0:
                alpha = 1.0 - math.exp(-dt / self.lag_tau)
            else:
                alpha = 1.0
            self._filtered_value += alpha * (true_value - self._filtered_value)

        # Drift accumulation
        self._drift_accumulated += self.drift_rate * dt_h
        self._time_h += dt_h

        # Base measured value
        measured = self._filtered_value + self._drift_accumulated

        # Gaussian noise
        measured += random.gauss(0, self.noise_std)

        # Fault injection
        if self._fault_type == "stuck":
            measured = self._stuck_value
        elif self._fault_type == "spike":
            if self._spike_remaining_s > 0:
                measured += self._spike_magnitude
                self._spike_remaining_s -= dt
                if self._spike_remaining_s <= 0:
                    self._fault_type = None
            else:
                self._fault_type = None
        elif self._fault_type == "drift_fast":
            self._drift_accumulated += self._drift_fast_rate * dt_h
            measured = self._filtered_value + self._drift_accumulated

        # Clamp to sensor range
        measured = max(self.range_min, min(self.range_max, measured))

        return measured

    def inject_fault(self, fault_type: str, **kwargs):
        """
        Inject a sensor fault.

        fault_type:
          "stuck"      — sensor freezes at current value
                         kwargs: value (optional, defaults to last reading)
          "spike"      — sudden offset for a duration
                         kwargs: magnitude (float), duration_s (float, default 10)
          "drift_fast" — accelerated drift
                         kwargs: rate (float, units/hour)
        """
        self._fault_type = fault_type

        if fault_type == "stuck":
            self._stuck_value = kwargs.get("value", self._filtered_value or 0.0)

        elif fault_type == "spike":
            self._spike_magnitude = kwargs.get("magnitude", 1.0)
            self._spike_remaining_s = kwargs.get("duration_s", 10.0)

        elif fault_type == "drift_fast":
            self._drift_fast_rate = kwargs.get("rate", 0.1)

    def clear_fault(self):
        """Remove any injected fault."""
        self._fault_type = None
        self._stuck_value = None
        self._spike_remaining_s = 0.0
        self._drift_fast_rate = 0.0

    def reset_drift(self):
        """Zero out accumulated drift (simulates recalibration)."""
        self._drift_accumulated = 0.0

    def get_state(self) -> dict:
        return {
            "sensor_type": self.sensor_type,
            "filtered_value": round(self._filtered_value, 6) if self._filtered_value else None,
            "drift_accumulated": round(self._drift_accumulated, 6),
            "fault_type": self._fault_type,
            "time_h": round(self._time_h, 3),
        }
