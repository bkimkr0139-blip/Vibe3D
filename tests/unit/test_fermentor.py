"""Unit tests for the Fermentor physics model."""

import pytest
from fermentation.physics.fermentor import Fermentor, VESSEL_CONFIGS


class TestFermentorInitialization:
    def test_default_initialization(self):
        f = Fermentor()
        state = f.get_state()
        assert state["vessel"] == "KF-7KL"
        assert state["X"] == 0.5
        assert state["S"] == 20.0
        assert 6.5 <= state["pH"] <= 7.5
        assert state["DO"] > 0
        assert state["temperature"] == 30.0

    def test_custom_vessel(self):
        f = Fermentor({"vessel": "KF-70L"})
        assert f.vessel_name == "KF-70L"
        assert f.volume_L == 70.0
        assert f.max_rpm == 800

    def test_custom_parameters(self):
        f = Fermentor({"X0": 1.0, "S0": 40.0, "pH0": 6.5})
        state = f.get_state()
        assert state["X"] == 1.0
        assert state["S"] == 40.0
        assert state["pH"] == 6.5

    def test_all_vessel_configs(self):
        for vessel_name in VESSEL_CONFIGS:
            f = Fermentor({"vessel": vessel_name})
            assert f.vessel_name == vessel_name
            assert f.volume_L == VESSEL_CONFIGS[vessel_name]["volume_L"]


class TestFermentorGrowth:
    def test_biomass_increases_with_substrate(self):
        """Biomass should increase when substrate and DO are available."""
        f = Fermentor({"X0": 0.5, "S0": 20.0, "DO0": 7.0})
        # Run for a simulated hour with aeration and agitation
        for _ in range(3600):
            state = f.step(1.0, rpm_setpoint=200, aeration_vvm=0.5)
        assert state["X"] > 0.5, "Biomass should have grown"

    def test_substrate_decreases(self):
        """Substrate should be consumed during growth."""
        f = Fermentor({"X0": 1.0, "S0": 20.0})
        initial_S = f.S
        for _ in range(3600):
            state = f.step(1.0, rpm_setpoint=200, aeration_vvm=0.5)
        assert state["S"] < initial_S, "Substrate should decrease"

    def test_no_growth_without_aeration(self):
        """No oxygen transfer without agitation+aeration → DO drops → growth stalls."""
        f = Fermentor({"X0": 0.5, "S0": 20.0, "DO0": 7.0})
        # Run without agitation/aeration for ~1 hour
        for _ in range(3600):
            state = f.step(1.0, rpm_setpoint=0, aeration_vvm=0.0)
        # DO should drop significantly (OUR depletes DO without OTR)
        assert state["DO"] < 2.0, "DO should drop without aeration"


class TestFermentorpH:
    def test_ph_stays_in_range(self):
        """pH should remain within physically reasonable bounds."""
        f = Fermentor({"X0": 1.0, "S0": 30.0})
        for _ in range(7200):
            state = f.step(1.0, rpm_setpoint=200, aeration_vvm=0.5)
        assert 2.0 <= state["pH"] <= 12.0

    def test_ph_drops_with_growth(self):
        """pH should decrease due to metabolic acid production."""
        f = Fermentor({"X0": 1.0, "S0": 20.0, "pH0": 7.0})
        initial_ph = f.pH
        for _ in range(3600):
            f.step(1.0, rpm_setpoint=200, aeration_vvm=0.5)
        assert f.pH < initial_ph, "pH should drop from metabolic acids"

    def test_base_addition_raises_ph(self):
        """Adding base should increase pH."""
        f = Fermentor({"X0": 1.0, "S0": 20.0, "pH0": 5.5})
        initial_ph = f.pH
        # Open base valve for 60 seconds
        for _ in range(60):
            f.step(1.0, valve_base=True, rpm_setpoint=200, aeration_vvm=0.5)
        assert f.pH > initial_ph, "Base should raise pH"
        assert f.total_base_added_L > 0

    def test_acid_addition_lowers_ph(self):
        """Adding acid should decrease pH."""
        f = Fermentor({"pH0": 7.5})
        initial_ph = f.pH
        for _ in range(60):
            f.step(1.0, valve_acid=True)
        assert f.pH < initial_ph


class TestFermentorDO:
    def test_do_with_aeration(self):
        """DO should be maintained near saturation with good aeration."""
        f = Fermentor({"X0": 0.1, "S0": 5.0, "DO0": 7.0})
        for _ in range(1800):
            state = f.step(1.0, rpm_setpoint=200, aeration_vvm=1.0)
        assert state["DO"] > 3.0, "DO should stay reasonable with aeration"

    def test_do_non_negative(self):
        """DO should never go below zero."""
        f = Fermentor({"X0": 5.0, "S0": 30.0, "DO0": 7.0})
        for _ in range(7200):
            state = f.step(1.0, rpm_setpoint=100, aeration_vvm=0.3)
        assert state["DO"] >= 0.0


class TestFermentorTemperature:
    def test_cooling_jacket(self):
        """Cooling water should lower temperature."""
        f = Fermentor({"T0": 35.0})
        for _ in range(600):
            state = f.step(1.0, valve_cooling=100.0)
        assert state["temperature"] < 35.0, "Cooling should reduce temperature"

    def test_steam_heating(self):
        """Steam jacket should raise temperature."""
        f = Fermentor({"T0": 25.0})
        for _ in range(600):
            state = f.step(1.0, valve_steam=100.0)
        assert state["temperature"] > 25.0, "Steam should raise temperature"


class TestFermentorAgitation:
    def test_rpm_ramp(self):
        """RPM should ramp gradually, not jump instantly."""
        f = Fermentor()
        state = f.step(1.0, rpm_setpoint=200)
        # Should not reach setpoint in 1 second (ramp rate = 50 RPM/min)
        assert state["rpm"] < 200
        assert state["rpm"] > 0

    def test_rpm_reaches_setpoint(self):
        """RPM should eventually reach setpoint."""
        f = Fermentor()
        for _ in range(300):
            state = f.step(1.0, rpm_setpoint=200)
        assert abs(state["rpm"] - 200) < 1.0
