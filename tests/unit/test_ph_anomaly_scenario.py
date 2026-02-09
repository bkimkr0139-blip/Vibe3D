"""Unit tests for the pH anomaly PoC scenario."""

import pytest
from fermentation.scenarios.ph_anomaly import pHAnomalyScenario
from fermentation.scenarios.base import ScenarioPhase
from fermentation.detection.anomaly_detector import AnomalyDetector


class TestAnomalyDetector:
    def test_no_alert_in_range(self):
        d = AnomalyDetector(setpoint=7.0, low_threshold=6.3, high_threshold=7.7)
        result = d.check(7.0, 0.0)
        assert result is None

    def test_alert_below_threshold(self):
        d = AnomalyDetector(
            setpoint=7.0, low_threshold=6.3, high_threshold=7.7,
            debounce_s=0.0,
        )
        # Need consecutive violations
        for i in range(5):
            result = d.check(6.0, float(i))
        assert result is not None
        assert result["direction"] == "low"
        assert result["severity"] in ("low", "medium", "high", "critical")

    def test_alert_above_threshold(self):
        d = AnomalyDetector(
            setpoint=7.0, low_threshold=6.3, high_threshold=7.7,
            debounce_s=0.0,
        )
        for i in range(5):
            result = d.check(8.0, float(i))
        assert result is not None
        assert result["direction"] == "high"

    def test_debounce(self):
        """Debounce should prevent repeated alerts too quickly."""
        d = AnomalyDetector(
            setpoint=7.0, low_threshold=6.3, high_threshold=7.7,
            debounce_s=10.0,
        )
        # First alert
        for i in range(5):
            d.check(6.0, float(i))
        # Second alert within debounce window should be suppressed
        result = d.check(6.0, 6.0)
        assert result is None

    def test_reset(self):
        d = AnomalyDetector()
        for i in range(5):
            d.check(5.0, float(i))
        d.reset()
        assert d._consecutive_violations == 0


class TestpHAnomalyScenario:
    def test_initial_state(self):
        s = pHAnomalyScenario()
        assert s.phase == ScenarioPhase.IDLE
        assert not s.is_complete

    def test_transitions_from_idle_to_setup(self):
        s = pHAnomalyScenario()
        state = {"fermentors": {"KF-7KL": {"pH": 7.0}}}
        result = s.evaluate(state, 1.0)
        assert s.phase == ScenarioPhase.SETUP
        assert "controls" in result

    def test_setup_to_growth_transition(self):
        s = pHAnomalyScenario(setup_duration_s=5.0)
        state = {"fermentors": {"KF-7KL": {"pH": 7.0}}}
        # Pass through IDLE → SETUP
        s.evaluate(state, 1.0)
        assert s.phase == ScenarioPhase.SETUP
        # Wait for setup duration
        for _ in range(10):
            s.evaluate(state, 1.0)
        assert s.phase == ScenarioPhase.GROWTH

    def test_growth_to_anomaly_transition(self):
        s = pHAnomalyScenario(setup_duration_s=2.0, growth_duration_s=5.0)
        state = {"fermentors": {"KF-7KL": {"pH": 7.0}}}
        # IDLE → SETUP → GROWTH → ANOMALY
        for _ in range(20):
            s.evaluate(state, 1.0)
        assert s.phase == ScenarioPhase.ANOMALY

    def test_full_scenario_phase_sequence(self):
        """Scenario should progress through all phases."""
        s = pHAnomalyScenario(
            setup_duration_s=2.0,
            growth_duration_s=3.0,
            ph_low_threshold=6.5,
        )
        phases_seen = set()

        # Simulate with pH values that trigger detection/correction
        ph = 7.0
        dosing_state = {"KF-7KL-base": {"phase": "idle"}}

        for i in range(200):
            # Simulate pH dropping during anomaly phase
            if s.phase == ScenarioPhase.ANOMALY:
                ph = max(5.5, ph - 0.05)
            elif s.phase in (ScenarioPhase.CORRECTION, ScenarioPhase.RECOVERY):
                ph = min(7.0, ph + 0.02)
                dosing_state = {"KF-7KL-base": {"phase": "complete"}}

            state = {
                "fermentors": {"KF-7KL": {"pH": ph}},
                "dosing": dosing_state,
            }
            s.evaluate(state, 1.0)
            phases_seen.add(s.phase)

            if s.is_complete:
                break

        assert ScenarioPhase.SETUP in phases_seen
        assert ScenarioPhase.GROWTH in phases_seen
        assert ScenarioPhase.ANOMALY in phases_seen
        assert ScenarioPhase.DETECTION in phases_seen

    def test_scenario_events_logged(self):
        s = pHAnomalyScenario(setup_duration_s=1.0)
        state = {"fermentors": {"KF-7KL": {"pH": 7.0}}}
        s.evaluate(state, 1.0)
        scenario_state = s.get_state()
        assert len(scenario_state["events"]) > 0
        assert scenario_state["events"][0]["to_phase"] == "setup"
