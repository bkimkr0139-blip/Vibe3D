"""Biomass combustion boiler model.

Models a grate-fired biomass boiler with steam generation.
Typical applications: Wood chip, agricultural residue, or MSW-derived fuel boilers.

Key sub-models:
    - Combustion: Stoichiometric combustion with excess air
    - Heat transfer: Radiation + convection in furnace
    - Steam generation: Subcritical drum-type boiler
    - Emissions: CO, NOx, particulate estimation
"""

import numpy as np


class BiomassBoiler:
    """Grate-fired biomass boiler with steam generation."""

    DEFAULT_PARAMS = {
        "rated_steam_flow": 20000.0,    # kg/h
        "rated_steam_pressure": 40.0,   # bar
        "rated_steam_temp": 400.0,      # C (superheated)
        "feedwater_temp": 105.0,        # C
        "rated_thermal_input": 15000.0, # kW (fuel thermal)
        "design_efficiency": 0.88,      # boiler efficiency
        "grate_area": 25.0,             # m2
        "excess_air": 0.40,             # 40% excess air
    }

    # Biomass fuel properties (wood chips, 30% moisture)
    FUEL = {
        "lhv": 12.5,               # MJ/kg as-received
        "moisture": 0.30,          # fraction
        "ash_content": 0.02,       # fraction
        "carbon": 0.35,            # fraction (as-received)
        "hydrogen": 0.04,
        "oxygen": 0.28,
        "stoich_air": 4.5,         # kg air / kg fuel (stoichiometric)
    }

    def __init__(self, params: dict | None = None):
        p = {**self.DEFAULT_PARAMS, **(params or {})}
        self.rated_steam_flow = p["rated_steam_flow"]
        self.rated_steam_pressure = p["rated_steam_pressure"]
        self.rated_steam_temp = p["rated_steam_temp"]
        self.feedwater_temp = p["feedwater_temp"]
        self.rated_thermal = p["rated_thermal_input"]
        self.design_efficiency = p["design_efficiency"]

        # State variables
        self.fuel_feed_rate = 0.0       # kg/h
        self.steam_flow = 0.0           # kg/h
        self.steam_pressure = 1.0       # bar
        self.steam_temperature = 25.0   # C
        self.combustion_temp = 25.0     # C
        self.flue_gas_temp = 25.0       # C
        self.boiler_efficiency = 0.0    # %
        self.load_percent = 0.0

    def step(self, dt: float, fuel_feed: float = None, load_setpoint: float = None) -> dict:
        """Advance boiler state by dt seconds.

        Args:
            dt: Time step in seconds.
            fuel_feed: Biomass fuel feed rate (kg/h). If None, derived from load_setpoint.
            load_setpoint: Target load (0-100%). Used if fuel_feed is None.
        """
        if load_setpoint is not None and fuel_feed is None:
            load_setpoint = np.clip(load_setpoint, 0.0, 100.0)
            target_thermal = self.rated_thermal * load_setpoint / 100.0
            fuel_lhv_kw = self.FUEL["lhv"] * 1000 / 3600  # kW per kg/h -> need kg/h
            fuel_feed = target_thermal / max(fuel_lhv_kw, 0.01) * 3.6

        if fuel_feed is None:
            fuel_feed = 0.0

        # Feed rate ramp (grate response ~5%/min)
        max_ramp = self.rated_steam_flow * 0.05 / 60.0 * dt  # kg/h change
        ramp_fuel = self.rated_thermal / (self.FUEL["lhv"] * 1000 / 3600) * 3.6  # rated fuel
        max_fuel_ramp = ramp_fuel * 0.05 / 60.0 * dt
        delta = fuel_feed - self.fuel_feed_rate
        self.fuel_feed_rate += np.clip(delta, -max_fuel_ramp, max_fuel_ramp)
        self.fuel_feed_rate = max(self.fuel_feed_rate, 0.0)

        if self.fuel_feed_rate < 1.0:
            self.steam_flow = 0.0
            self.steam_pressure = max(self.steam_pressure - 0.5 * dt / 60.0, 1.0)
            self.steam_temperature = max(self.steam_temperature - 2.0 * dt / 60.0, 25.0)
            self.combustion_temp = max(self.combustion_temp - 5.0 * dt / 60.0, 25.0)
            self.flue_gas_temp = max(self.flue_gas_temp - 3.0 * dt / 60.0, 25.0)
            self.boiler_efficiency = 0.0
            self.load_percent = 0.0
            return self.get_state()

        # Combustion
        thermal_input = self.fuel_feed_rate * self.FUEL["lhv"] * 1000 / 3600  # kW
        self.load_percent = thermal_input / self.rated_thermal * 100.0

        # Efficiency (drops at part-load)
        load_frac = min(self.load_percent / 100.0, 1.0)
        self.boiler_efficiency = self.design_efficiency * (0.85 + 0.15 * load_frac)

        # Combustion temperature
        target_comb_temp = 850.0 + 200.0 * load_frac
        tau_comb = 30.0  # seconds thermal inertia
        self.combustion_temp += (target_comb_temp - self.combustion_temp) * (1 - np.exp(-dt / tau_comb))

        # Flue gas temperature
        target_flue = 150.0 + 30.0 * load_frac
        self.flue_gas_temp += (target_flue - self.flue_gas_temp) * (1 - np.exp(-dt / tau_comb))

        # Steam generation
        useful_heat = thermal_input * self.boiler_efficiency  # kW
        # Approximate enthalpy rise: ~2800 kJ/kg for subcritical steam from 105C feedwater
        enthalpy_rise = 2800.0  # kJ/kg
        target_steam_flow = useful_heat * 3.6 / enthalpy_rise * 1000  # kg/h

        tau_steam = 60.0  # seconds steam response
        self.steam_flow += (target_steam_flow - self.steam_flow) * (1 - np.exp(-dt / tau_steam))

        # Steam conditions
        self.steam_pressure = self.rated_steam_pressure * min(load_frac * 1.1, 1.0)
        self.steam_temperature = self.rated_steam_temp * (0.85 + 0.15 * load_frac)

        return self.get_state()

    def get_state(self) -> dict:
        return {
            "fuel_feed_rate": round(self.fuel_feed_rate, 1),
            "steam_flow": round(self.steam_flow, 0),
            "steam_pressure": round(self.steam_pressure, 1),
            "steam_temperature": round(self.steam_temperature, 1),
            "combustion_temp": round(self.combustion_temp, 0),
            "flue_gas_temp": round(self.flue_gas_temp, 1),
            "boiler_efficiency": round(self.boiler_efficiency * 100, 1),
            "load_percent": round(self.load_percent, 1),
            "feedwater_temp": self.feedwater_temp,
        }
