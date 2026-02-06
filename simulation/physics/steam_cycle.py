"""Steam turbine and condenser model (Rankine cycle).

Models a back-pressure or condensing steam turbine driven by
biomass boiler steam. Includes condenser and feedwater system.
"""

import numpy as np


class SteamTurbine:
    """Simple steam turbine model for biomass power plant."""

    DEFAULT_PARAMS = {
        "rated_power": 5000.0,          # kW
        "inlet_pressure": 40.0,          # bar
        "inlet_temperature": 400.0,      # C
        "exhaust_pressure": 0.1,         # bar (condensing) or 2-6 bar (back-pressure CHP)
        "isentropic_efficiency": 0.85,
        "mechanical_efficiency": 0.98,
        "generator_efficiency": 0.97,
        "mode": "condensing",            # "condensing" or "backpressure"
    }

    def __init__(self, params: dict | None = None):
        p = {**self.DEFAULT_PARAMS, **(params or {})}
        self.rated_power = p["rated_power"]
        self.inlet_pressure = p["inlet_pressure"]
        self.exhaust_pressure = p["exhaust_pressure"]
        self.eta_is = p["isentropic_efficiency"]
        self.eta_mech = p["mechanical_efficiency"]
        self.eta_gen = p["generator_efficiency"]
        self.mode = p["mode"]

        # State
        self.power_output = 0.0         # kW
        self.steam_flow = 0.0           # kg/h
        self.exhaust_temp = 25.0        # C
        self.condenser_pressure = self.exhaust_pressure  # bar
        self.feedwater_temp = 45.0      # C

    def step(self, dt: float, inlet_steam_flow: float,
             inlet_pressure: float, inlet_temp: float) -> dict:
        """Advance turbine state.

        Args:
            dt: Time step (s).
            inlet_steam_flow: Steam mass flow rate (kg/h).
            inlet_pressure: Inlet steam pressure (bar).
            inlet_temp: Inlet steam temperature (C).
        """
        self.steam_flow = inlet_steam_flow

        if inlet_steam_flow < 100.0:  # minimum flow
            self.power_output = 0.0
            self.exhaust_temp = 25.0
            return self.get_state()

        # Simplified enthalpy drop calculation
        # Using approximate steam tables correlation
        pressure_ratio = inlet_pressure / max(self.exhaust_pressure, 0.01)
        h_inlet = 3200.0 + 2.0 * (inlet_temp - 400.0)  # kJ/kg approximate
        h_drop_ideal = 200.0 * np.log(pressure_ratio)     # kJ/kg approximate
        h_drop_actual = h_drop_ideal * self.eta_is

        # Power output
        mass_flow_kgs = inlet_steam_flow / 3600.0  # kg/s
        shaft_power = mass_flow_kgs * h_drop_actual  # kW
        self.power_output = shaft_power * self.eta_mech * self.eta_gen

        # Cap at rated
        self.power_output = min(self.power_output, self.rated_power)

        # Exhaust conditions
        if self.mode == "condensing":
            self.exhaust_temp = 45.0 + 5.0 * (inlet_steam_flow / 20000.0)
            self.condenser_pressure = self.exhaust_pressure
            self.feedwater_temp = self.exhaust_temp + 5.0
        else:
            # Back-pressure: exhaust is usable heat
            self.exhaust_temp = 150.0 + 20.0 * (self.exhaust_pressure - 2.0)
            self.feedwater_temp = 105.0

        return self.get_state()

    def get_state(self) -> dict:
        return {
            "power_output": round(self.power_output, 1),
            "steam_flow": round(self.steam_flow, 0),
            "exhaust_temp": round(self.exhaust_temp, 1),
            "condenser_pressure": round(self.condenser_pressure, 3),
            "feedwater_temp": round(self.feedwater_temp, 1),
        }
