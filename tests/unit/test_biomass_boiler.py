"""Unit tests for biomass boiler physics model."""

import pytest

from simulation.physics.biomass_boiler import BiomassBoiler


class TestBiomassBoiler:
    def test_initialization(self):
        boiler = BiomassBoiler()
        state = boiler.get_state()
        assert state["fuel_feed_rate"] == 0
        assert state["steam_flow"] == 0

    def test_produces_steam_at_load(self):
        boiler = BiomassBoiler()
        for _ in range(600):
            state = boiler.step(1.0, load_setpoint=80.0)
        assert state["steam_flow"] > 0
        assert state["steam_pressure"] > 1.0
        assert state["combustion_temp"] > 100.0

    def test_no_steam_at_zero_load(self):
        boiler = BiomassBoiler()
        state = boiler.step(1.0, load_setpoint=0.0)
        assert state["steam_flow"] == 0
