"""
Threshold-based anomaly detector for fermentation parameters.

Monitors a single parameter against setpoint and thresholds.
"""

from datetime import datetime, timezone


class AnomalyDetector:
    """
    Simple threshold-based anomaly detector.

    Fires when parameter crosses low or high threshold.
    Implements debounce to avoid spurious alarms.
    """

    def __init__(self,
                 parameter: str = "pH",
                 setpoint: float = 7.0,
                 low_threshold: float = 6.3,
                 high_threshold: float = 7.7,
                 debounce_s: float = 10.0):
        self.parameter = parameter
        self.setpoint = setpoint
        self.low_threshold = low_threshold
        self.high_threshold = high_threshold
        self.debounce_s = debounce_s

        self._alert_active = False
        self._last_alert_time = -999.0
        self._consecutive_violations = 0
        self._violation_threshold = 3  # consecutive readings before alert

    def check(self, value: float, time_s: float) -> dict | None:
        """
        Check a parameter value against thresholds.

        Returns an alert dict if anomaly detected, else None.
        """
        is_low = value < self.low_threshold
        is_high = value > self.high_threshold

        if is_low or is_high:
            self._consecutive_violations += 1
        else:
            self._consecutive_violations = 0
            self._alert_active = False
            return None

        # Debounce: need consecutive violations and time gap
        if self._consecutive_violations < self._violation_threshold:
            return None
        if (time_s - self._last_alert_time) < self.debounce_s and self._alert_active:
            return None

        # Fire alert
        self._alert_active = True
        self._last_alert_time = time_s

        deviation = value - self.setpoint
        severity = self._classify_severity(abs(deviation))

        return {
            "parameter": self.parameter,
            "value": round(value, 4),
            "setpoint": self.setpoint,
            "deviation": round(deviation, 4),
            "severity": severity,
            "direction": "low" if is_low else "high",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "message": (
                f"{self.parameter} {'below' if is_low else 'above'} threshold: "
                f"{value:.3f} (setpoint={self.setpoint}, "
                f"threshold={'%.3f' % (self.low_threshold if is_low else self.high_threshold)})"
            ),
        }

    def _classify_severity(self, abs_deviation: float) -> str:
        """Classify alert severity based on deviation magnitude."""
        # Fraction of distance from setpoint to threshold
        threshold_distance = abs(self.setpoint - self.low_threshold)
        if threshold_distance == 0:
            return "critical"

        ratio = abs_deviation / threshold_distance
        if ratio >= 2.0:
            return "critical"
        elif ratio >= 1.5:
            return "high"
        elif ratio >= 1.0:
            return "medium"
        else:
            return "low"

    def reset(self):
        """Reset detector state."""
        self._alert_active = False
        self._consecutive_violations = 0
        self._last_alert_time = -999.0

    def get_state(self) -> dict:
        return {
            "parameter": self.parameter,
            "setpoint": self.setpoint,
            "low_threshold": self.low_threshold,
            "high_threshold": self.high_threshold,
            "alert_active": self._alert_active,
            "consecutive_violations": self._consecutive_violations,
        }
