"""Unit tests for biogas engine physics model."""

import pytest

from simulation.physics.biogas_engine import BiogasEngine


class TestBiogasEngine:
    def test_initialization(self):
        engine = BiogasEngine()
        state = engine.get_state()
        assert state["rpm"] == 0
        assert state["power_output"] == 0

    def test_load_ramp(self):
        engine = BiogasEngine()
        # Ramp to 80% load over time
        for _ in range(600):  # 10 minutes
            state = engine.step(1.0, load_setpoint=80.0)
        assert state["power_output"] > 0
        assert state["rpm"] == 1500

    def test_zero_load_stops(self):
        engine = BiogasEngine()
        engine.step(1.0, load_setpoint=50.0)
        state = engine.step(1.0, load_setpoint=0.0)
        assert state["rpm"] == 0
        assert state["power_output"] == 0

    def test_rated_power_not_exceeded(self):
        engine = BiogasEngine({"rated_power": 1000.0})
        for _ in range(1200):
            state = engine.step(1.0, load_setpoint=100.0)
        assert state["power_output"] <= 1000.0

    def test_low_methane_reduces_efficiency(self):
        engine = BiogasEngine()
        for _ in range(600):
            engine.step(1.0, load_setpoint=80.0, biogas_ch4=60.0)
        eff_normal = engine.electrical_efficiency

        engine2 = BiogasEngine()
        for _ in range(600):
            engine2.step(1.0, load_setpoint=80.0, biogas_ch4=45.0)
        eff_low = engine2.electrical_efficiency

        assert eff_low < eff_normal
