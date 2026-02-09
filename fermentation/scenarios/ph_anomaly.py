"""
pH Anomaly PoC Scenario.

Sequence:
  1. SETUP     — ramp up RPM & aeration, bring to operating conditions
  2. GROWTH    — normal exponential growth for N minutes
  3. ANOMALY   — inject accelerated acid production (pH drops)
  4. DETECTION — anomaly detector fires alert
  5. CORRECTION — operator triggers 3x base dosing (15s open / 13s pause)
  6. RECOVERY  — pH returns to setpoint range
  7. COMPLETED
"""

from fermentation.scenarios.base import BaseScenario, ScenarioPhase
from fermentation.detection.anomaly_detector import AnomalyDetector


class pHAnomalyScenario(BaseScenario):
    """PoC scenario: pH anomaly detection and manual correction."""

    name = "ph_anomaly"
    description = "pH drops due to metabolic shift → detection → 3x alkali dose → recovery"

    def __init__(self,
                 vessel: str = "KF-7KL",
                 setup_duration_s: float = 60.0,
                 growth_duration_s: float = 300.0,
                 anomaly_acid_boost: float = 0.5,
                 ph_setpoint: float = 7.0,
                 ph_low_threshold: float = 6.3,
                 ph_recovery_threshold: float = 6.8):
        super().__init__()
        self.vessel = vessel
        self.setup_duration = setup_duration_s
        self.growth_duration = growth_duration_s
        self.anomaly_acid_boost = anomaly_acid_boost
        self.ph_setpoint = ph_setpoint
        self.ph_low_threshold = ph_low_threshold
        self.ph_recovery_threshold = ph_recovery_threshold

        self.detector = AnomalyDetector(
            parameter="pH",
            setpoint=ph_setpoint,
            low_threshold=ph_low_threshold,
            high_threshold=ph_setpoint + (ph_setpoint - ph_low_threshold),
        )

        self._anomaly_injected = False
        self._correction_started = False
        self._original_Y_acid = None

    def evaluate(self, state: dict, dt: float) -> dict:
        self._time += dt
        result = {}

        fermentors = state.get("fermentors", {})
        ferm_state = fermentors.get(self.vessel, {})
        current_ph = ferm_state.get("pH", 7.0)

        # --- IDLE → SETUP ---
        if self.phase == ScenarioPhase.IDLE:
            self.transition(ScenarioPhase.SETUP, "Starting scenario: ramp up RPM & aeration")
            result["controls"] = {
                self.vessel: {
                    "rpm_setpoint": 200.0,
                    "aeration_vvm": 0.5,
                    "valve_cooling": 50.0,
                }
            }

        # --- SETUP → GROWTH ---
        elif self.phase == ScenarioPhase.SETUP:
            if self.phase_elapsed() >= self.setup_duration:
                self.transition(ScenarioPhase.GROWTH, "Entering normal growth phase")

        # --- GROWTH → ANOMALY ---
        elif self.phase == ScenarioPhase.GROWTH:
            if self.phase_elapsed() >= self.growth_duration:
                self.transition(
                    ScenarioPhase.ANOMALY,
                    f"Injecting pH anomaly: boosting acid production by {self.anomaly_acid_boost}"
                )
                self._anomaly_injected = True

        # --- ANOMALY → DETECTION ---
        elif self.phase == ScenarioPhase.ANOMALY:
            # Check if pH has dropped enough to trigger detection
            alert = self.detector.check(current_ph, self._time)
            if alert is not None:
                self.transition(
                    ScenarioPhase.DETECTION,
                    f"pH anomaly detected: pH={current_ph:.2f} (threshold={self.ph_low_threshold})"
                )
                result["alerts"] = [alert]

        # --- DETECTION → CORRECTION ---
        elif self.phase == ScenarioPhase.DETECTION:
            # Automatically transition — in real scenario, operator would decide
            if self.phase_elapsed() >= 5.0:  # 5s delay for operator reaction
                self.transition(
                    ScenarioPhase.CORRECTION,
                    "Starting alkali dosing: 3 doses (15s open / 13s pause)"
                )
                self._correction_started = True
                result["controls"] = {
                    self.vessel: {"start_base_dosing": True}
                }

        # --- CORRECTION → RECOVERY ---
        elif self.phase == ScenarioPhase.CORRECTION:
            # Wait for dosing to complete and pH to start recovering
            dosing = state.get("dosing", {})
            base_dosing = dosing.get(f"{self.vessel}-base", {})
            dosing_complete = base_dosing.get("phase") == "complete"

            if dosing_complete:
                self.transition(
                    ScenarioPhase.RECOVERY,
                    "Dosing complete, monitoring pH recovery"
                )
                # Restore normal acid production
                self._anomaly_injected = False

        # --- RECOVERY → COMPLETED ---
        elif self.phase == ScenarioPhase.RECOVERY:
            if current_ph >= self.ph_recovery_threshold:
                self.transition(
                    ScenarioPhase.COMPLETED,
                    f"pH recovered to {current_ph:.2f} — scenario complete"
                )

        # --- Anomaly injection: boost acid production ---
        if self._anomaly_injected and not self._correction_started:
            result["modify_params"] = {
                self.vessel: {"Y_acid": self.anomaly_acid_boost}
            }

        return result
