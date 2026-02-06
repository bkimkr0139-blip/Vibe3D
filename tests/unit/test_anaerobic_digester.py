"""Unit tests for anaerobic digester physics model."""

import pytest

from simulation.physics.anaerobic_digester import AnaerobicDigester


class TestAnaerobicDigester:
    def test_initialization(self):
        digester = AnaerobicDigester()
        state = digester.get_state()
        assert state["temperature"] == 37.0
        assert 6.0 <= state["ph"] <= 8.0
        assert state["hydraulic_retention_time"] == 20.0

    def test_step_produces_biogas(self):
        digester = AnaerobicDigester()
        # Run for 1 day (86400s) in 100s steps
        for _ in range(864):
            state = digester.step(100.0)
        assert state["biogas_flow_rate"] > 0
        assert 45.0 <= state["methane_content"] <= 75.0

    def test_ph_stays_in_range(self):
        digester = AnaerobicDigester()
        for _ in range(1000):
            state = digester.step(100.0)
        assert 5.5 <= state["ph"] <= 8.5

    def test_custom_parameters(self):
        digester = AnaerobicDigester({"volume": 5000.0, "temperature": 55.0})
        assert digester.volume == 5000.0
        assert digester.temperature == 55.0

    def test_volatile_solids_non_negative(self):
        digester = AnaerobicDigester()
        for _ in range(5000):
            state = digester.step(100.0)
        assert state["volatile_solids"] >= 0
