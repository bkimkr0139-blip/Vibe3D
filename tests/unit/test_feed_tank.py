"""Unit tests for the FeedTank model."""

import pytest
from fermentation.physics.feed_tank import FeedTank, FEED_TANK_CONFIGS


class TestFeedTankInitialization:
    def test_default_init(self):
        ft = FeedTank()
        state = ft.get_state()
        assert state["vessel"] == "KF-4KL-FD"
        assert state["phase"] == "idle"
        assert state["volume_L"] > 0
        assert not state["sterile"]

    def test_custom_vessel(self):
        ft = FeedTank({"vessel": "KF-70L-FD"})
        assert ft.vessel_name == "KF-70L-FD"
        assert ft.volume_L == 100.0


class TestSterilizationCycle:
    def test_heating_phase(self):
        """Tank should heat up when sterilization starts."""
        ft = FeedTank({"T0": 25.0})
        ft.start_sterilization()
        assert ft.phase == FeedTank.PHASE_HEATING
        assert ft.valve_steam == 100.0

        # Step for a while — temperature should increase
        for _ in range(100):
            ft.step(1.0)
        assert ft.T > 25.0

    def test_full_sterilization_cycle(self):
        """Full cycle: heating → holding → cooling → ready."""
        ft = FeedTank({"T0": 25.0, "sterilization_hold_min": 0.5})  # short hold for test
        ft.start_sterilization()

        # Run until ready — use 10s steps for faster convergence
        for i in range(5000):
            ft.step(10.0)
            if ft.phase == FeedTank.PHASE_READY:
                break

        assert ft.sterile, "Tank should be sterile after cycle"
        assert ft.phase == FeedTank.PHASE_READY
        assert ft.T <= ft.cooling_target + 5.0  # near cooling target

    def test_holding_time_accumulates(self):
        """Hold time should accumulate during holding phase."""
        ft = FeedTank({"T0": 120.0})  # start near sterilization temp
        ft.start_sterilization()
        # Should enter holding after heating to 121 °C (only 1 °C away)
        for _ in range(500):
            ft.step(1.0)
            if ft.phase == FeedTank.PHASE_HOLDING:
                break
        assert ft.phase == FeedTank.PHASE_HOLDING
        ft.step(10.0)
        assert ft.hold_elapsed_s > 0


class TestTransfer:
    def test_transfer_reduces_volume(self):
        """Transfer should reduce tank volume."""
        ft = FeedTank({"T0": 30.0})
        # Force to ready state
        ft.phase = FeedTank.PHASE_READY
        ft.sterile = True
        initial_vol = ft.V

        ft.start_transfer()
        assert ft.phase == FeedTank.PHASE_TRANSFERRING

        # Step until some volume transferred
        for _ in range(100):
            ft.step(1.0)
        assert ft.V < initial_vol

    def test_transfer_empties_tank(self):
        """Tank should eventually empty during transfer."""
        ft = FeedTank({"T0": 30.0, "V0_fraction": 0.1})  # small volume
        ft.phase = FeedTank.PHASE_READY
        ft.sterile = True
        ft.start_transfer()

        for _ in range(5000):
            ft.step(1.0)
            if ft.phase == FeedTank.PHASE_EMPTY:
                break

        assert ft.phase == FeedTank.PHASE_EMPTY
        assert ft.V == 0.0

    def test_no_transfer_when_not_ready(self):
        """Transfer should not start in idle phase."""
        ft = FeedTank()
        ft.start_transfer()
        assert ft.phase != FeedTank.PHASE_TRANSFERRING
