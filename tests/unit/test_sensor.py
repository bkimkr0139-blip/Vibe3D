"""Unit tests for the VirtualSensor model."""

import pytest
import random
from fermentation.physics.sensor import VirtualSensor, SENSOR_PROFILES


class TestSensorBasics:
    def test_initialization(self):
        s = VirtualSensor("pH")
        assert s.sensor_type == "pH"
        assert s.noise_std == SENSOR_PROFILES["pH"]["noise_std"]

    def test_all_sensor_types(self):
        for stype in SENSOR_PROFILES:
            s = VirtualSensor(stype)
            assert s.sensor_type == stype

    def test_first_read_returns_near_true(self):
        random.seed(42)
        s = VirtualSensor("temperature", {"noise_std": 0.0, "lag_tau": 0.0})
        reading = s.read(30.0, 1.0)
        assert abs(reading - 30.0) < 0.01


class TestSensorNoise:
    def test_noise_distribution(self):
        """Readings should scatter around true value."""
        random.seed(42)
        s = VirtualSensor("pH", {"noise_std": 0.02, "lag_tau": 0.0, "drift_rate": 0.0})
        readings = []
        for _ in range(1000):
            readings.append(s.read(7.0, 1.0))
        mean = sum(readings) / len(readings)
        assert abs(mean - 7.0) < 0.05, "Mean should be close to true value"

    def test_zero_noise(self):
        """Zero noise should give exact readings (modulo lag/drift)."""
        s = VirtualSensor("temperature", {"noise_std": 0.0, "lag_tau": 0.0, "drift_rate": 0.0})
        reading = s.read(30.0, 1.0)
        assert reading == 30.0


class TestSensorDrift:
    def test_drift_accumulates(self):
        """Drift should accumulate over time."""
        s = VirtualSensor("pH", {"noise_std": 0.0, "lag_tau": 0.0, "drift_rate": 1.0})
        # Run for 1 simulated hour (3600 seconds)
        for _ in range(3600):
            reading = s.read(7.0, 1.0)
        # Drift rate = 1.0 unit/hour → after 1h, drift ≈ 1.0
        assert abs(reading - 8.0) < 0.1, "Drift should accumulate"

    def test_drift_reset(self):
        """Drift reset should zero accumulated drift."""
        s = VirtualSensor("pH", {"noise_std": 0.0, "lag_tau": 0.0, "drift_rate": 1.0})
        for _ in range(3600):
            s.read(7.0, 1.0)
        s.reset_drift()
        reading = s.read(7.0, 1.0)
        assert abs(reading - 7.0) < 0.1


class TestSensorLag:
    def test_lag_filter_smooths(self):
        """Sensor lag should smooth sudden changes."""
        s = VirtualSensor("temperature", {"noise_std": 0.0, "lag_tau": 10.0, "drift_rate": 0.0})
        # Initial reading at 30
        s.read(30.0, 1.0)
        # Step change to 50
        reading = s.read(50.0, 1.0)
        # Should not jump instantly to 50
        assert reading < 50.0
        assert reading > 30.0


class TestFaultInjection:
    def test_stuck_fault(self):
        """Stuck sensor should freeze at a fixed value."""
        s = VirtualSensor("pH", {"noise_std": 0.0, "lag_tau": 0.0, "drift_rate": 0.0})
        s.read(7.0, 1.0)
        s.inject_fault("stuck", value=6.5)
        for _ in range(10):
            reading = s.read(7.5, 1.0)
            assert reading == 6.5

    def test_spike_fault(self):
        """Spike should add offset for specified duration."""
        s = VirtualSensor("temperature", {"noise_std": 0.0, "lag_tau": 0.0, "drift_rate": 0.0})
        s.read(30.0, 1.0)
        s.inject_fault("spike", magnitude=10.0, duration_s=5.0)
        # During spike
        reading = s.read(30.0, 1.0)
        assert reading > 35.0  # 30 + ~10 spike
        # After spike
        for _ in range(10):
            reading = s.read(30.0, 1.0)
        assert abs(reading - 30.0) < 1.0

    def test_drift_fast_fault(self):
        """Fast drift should accelerate drift beyond normal rate."""
        s = VirtualSensor("pH", {"noise_std": 0.0, "lag_tau": 0.0, "drift_rate": 0.0})
        s.read(7.0, 1.0)
        s.inject_fault("drift_fast", rate=10.0)  # 10 units/hour
        for _ in range(3600):
            reading = s.read(7.0, 1.0)
        # Should drift significantly
        assert abs(reading - 7.0) > 5.0

    def test_clear_fault(self):
        """Clearing fault should restore normal behavior."""
        s = VirtualSensor("pH", {"noise_std": 0.0, "lag_tau": 0.0, "drift_rate": 0.0})
        s.read(7.0, 1.0)
        s.inject_fault("stuck", value=5.0)
        s.clear_fault()
        reading = s.read(7.0, 1.0)
        assert abs(reading - 7.0) < 0.5

    def test_sensor_range_clamping(self):
        """Readings should be clamped to sensor range."""
        s = VirtualSensor("pH", {"noise_std": 0.0, "lag_tau": 0.0, "drift_rate": 0.0})
        s.inject_fault("stuck", value=15.0)
        reading = s.read(7.0, 1.0)
        assert reading <= 14.0  # pH range max
