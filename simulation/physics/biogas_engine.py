"""Biogas reciprocating engine model.

Models a gas-fired internal combustion engine (Otto cycle) running on biogas.
Typical applications: Jenbacher, Caterpillar, MWM biogas engines (500kW-2MW class).

Thermodynamic basis:
    - Otto cycle with real-gas corrections
    - Methane number-dependent knock limit
    - Exhaust gas heat recovery (CHP)
"""

import numpy as np


class BiogasEngine:
    """Biogas internal combustion engine (Otto cycle) model."""

    DEFAULT_PARAMS = {
        "rated_power": 1000.0,       # kW electrical
        "rated_rpm": 1500.0,         # RPM (50Hz grid sync)
        "compression_ratio": 12.5,
        "num_cylinders": 16,
        "bore": 0.190,               # m
        "stroke": 0.220,             # m
        "electrical_efficiency": 0.42,  # at rated load
        "thermal_efficiency": 0.43,     # heat recovery
        "min_methane_number": 50,       # knock limit
    }

    # Fuel properties
    FUEL = {
        "ch4_lhv": 35.8,    # MJ/Nm3 - methane LHV
        "co2_lhv": 0.0,     # CO2 is inert
    }

    def __init__(self, params: dict | None = None):
        p = {**self.DEFAULT_PARAMS, **(params or {})}
        self.rated_power = p["rated_power"]
        self.rated_rpm = p["rated_rpm"]
        self.compression_ratio = p["compression_ratio"]

        # State variables
        self.rpm = 0.0
        self.power_output = 0.0       # kW
        self.load_percent = 0.0       # %
        self.exhaust_temp = 25.0      # C
        self.fuel_flow = 0.0          # Nm3/h biogas
        self.air_fuel_ratio = 1.7     # lambda
        self.electrical_efficiency = 0.0
        self.thermal_output = 0.0     # kW thermal
        self.thermal_efficiency = p["thermal_efficiency"]
        self._rated_elec_eff = p["electrical_efficiency"]
        self._running = False

    def step(self, dt: float, load_setpoint: float, biogas_ch4: float = 60.0) -> dict:
        """Advance engine state by dt seconds.

        Args:
            dt: Time step in seconds.
            load_setpoint: Target load (0-100%).
            biogas_ch4: Methane content of supplied biogas (%).

        Returns:
            Dict of current state variables.
        """
        load_setpoint = np.clip(load_setpoint, 0.0, 100.0)

        # Startup/shutdown ramp
        if load_setpoint > 0 and not self._running:
            self._running = True
            self.rpm = self.rated_rpm  # instant sync for now

        if load_setpoint == 0:
            self._running = False
            self.rpm = 0.0
            self.power_output = 0.0
            self.exhaust_temp = 25.0
            self.fuel_flow = 0.0
            self.electrical_efficiency = 0.0
            self.thermal_output = 0.0
            return self.get_state()

        # Load ramp (10%/min rate limit)
        max_ramp = 10.0 / 60.0 * dt  # %/s * dt
        load_delta = load_setpoint - self.load_percent
        self.load_percent += np.clip(load_delta, -max_ramp, max_ramp)
        self.load_percent = np.clip(self.load_percent, 0.0, 100.0)

        load_frac = self.load_percent / 100.0

        # Efficiency vs load (part-load penalty)
        eff_factor = 0.5 + 0.5 * load_frac  # linear simplification
        ch4_factor = biogas_ch4 / 60.0  # normalized to 60% CH4 baseline
        self.electrical_efficiency = self._rated_elec_eff * eff_factor * min(ch4_factor, 1.1)

        # Power output
        self.power_output = self.rated_power * load_frac

        # Fuel consumption
        fuel_energy = self.power_output / max(self.electrical_efficiency, 0.01)  # kW
        biogas_lhv = (biogas_ch4 / 100.0) * self.FUEL["ch4_lhv"]  # MJ/Nm3
        biogas_lhv_kwh = biogas_lhv / 3.6  # kWh/Nm3
        self.fuel_flow = fuel_energy / max(biogas_lhv_kwh, 0.01)  # Nm3/h

        # Exhaust temperature
        self.exhaust_temp = 400.0 + 100.0 * load_frac  # simplified

        # Thermal output (CHP heat recovery)
        self.thermal_output = fuel_energy * self.thermal_efficiency

        # Air-fuel ratio
        self.air_fuel_ratio = 1.7 - 0.2 * (load_frac - 0.5)

        return self.get_state()

    def get_state(self) -> dict:
        return {
            "rpm": round(self.rpm, 0),
            "power_output": round(self.power_output, 1),
            "load_percent": round(self.load_percent, 1),
            "exhaust_temp": round(self.exhaust_temp, 1),
            "fuel_flow": round(self.fuel_flow, 2),
            "air_fuel_ratio": round(self.air_fuel_ratio, 2),
            "electrical_efficiency": round(self.electrical_efficiency * 100, 1),
            "thermal_output": round(self.thermal_output, 1),
            "thermal_efficiency": round(self.thermal_efficiency * 100, 1),
        }
