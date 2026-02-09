"""
Broth tank model — fermentation broth collection with CWS cooling.

P&ID reference (Ko Bio Tech, CBF-2009):
  Page 8: KF-7000L BROTH TANK
  - CWS cooling jacket: 40A lines (large capacity)
  - Steam supply: 25A (for CIP sterilization)
  - Broth Out: 25A
  - No agitation, no acid/base/antifoam
  - Heat exchanger on CWS loop
  - Wet scrubber exhaust

No biology — just volume collection and temperature control.
"""

import math


BROTH_TANK_CONFIGS = {
    "KF-7000L": {
        "volume_L": 7000.0,
        "working_volume_L": 6000.0,
        "jacket_area_m2": 8.0,
        # Piping from P&ID Page 8
        "pipe_steam": "25A",       # CIP sterilization
        "pipe_cws": "40A",         # cooling water (large capacity)
        "pipe_broth_out": "25A",   # broth discharge
        "source_fermentor": "KF-7KL",
    },
}


DEFAULT_PARAMS = {
    "vessel": "KF-7000L",
    "jacket_U": 400.0,          # W/(m2*K)
    "broth_Cp": 4180.0,
    "broth_density": 1010.0,
    "cooling_target_T": 4.0,    # °C  cold storage target
    "T0": 30.0,
    "V0": 0.0,                  # starts empty
}


class BrothTank:
    """Broth collection tank with cooling water jacket."""

    DEFAULT_PARAMS = DEFAULT_PARAMS

    PHASE_EMPTY = "empty"
    PHASE_RECEIVING = "receiving"
    PHASE_COOLING = "cooling"
    PHASE_STORED = "stored"
    PHASE_DRAINING = "draining"

    def __init__(self, params: dict | None = None):
        p = {**self.DEFAULT_PARAMS, **(params or {})}

        vessel_name = p["vessel"]
        vc = BROTH_TANK_CONFIGS.get(vessel_name, BROTH_TANK_CONFIGS["KF-7000L"])
        self.vessel_name = vessel_name
        self.volume_L = vc["volume_L"]
        self.working_volume_L = vc["working_volume_L"]
        self.jacket_area = vc["jacket_area_m2"]

        self.jacket_U = p["jacket_U"]
        self.Cp = p["broth_Cp"]
        self.rho = p["broth_density"]
        self.cooling_target = p["cooling_target_T"]

        # State
        self.T = p["T0"]
        self.V = p["V0"]
        self.phase = self.PHASE_EMPTY if self.V < 1.0 else self.PHASE_STORED

        # Actuators
        self.valve_cooling = 0.0   # 0-100 %
        self.valve_inlet = False
        self.valve_drain = False

        self.time_h = 0.0

    def receive(self, volume_L: float, temperature: float):
        """Receive broth from fermentor — energy-balance mixing."""
        if volume_L <= 0:
            return
        if self.V > 0:
            # Mixing temperature
            self.T = (self.T * self.V + temperature * volume_L) / (self.V + volume_L)
        else:
            self.T = temperature
        self.V += volume_L
        self.V = min(self.V, self.working_volume_L)
        if self.phase == self.PHASE_EMPTY:
            self.phase = self.PHASE_RECEIVING

    def start_cooling(self):
        """Start CWS cooling."""
        if self.V > 0:
            self.phase = self.PHASE_COOLING
            self.valve_cooling = 100.0

    def step(self, dt: float) -> dict:
        """Advance by dt seconds."""
        dt_h = dt / 3600.0

        # Cooling heat transfer
        if self.V > 0 and self.valve_cooling > 0:
            cool_frac = self.valve_cooling / 100.0
            cws_T = 5.0  # cooling water supply temp
            mass_kg = (self.V / 1000.0) * self.rho  # V in m3 * density in kg/m3
            Q = self.jacket_U * self.jacket_area * (cws_T - self.T) * cool_frac
            dT = Q / (mass_kg * self.Cp) * dt
            self.T += dT

        # Phase transitions
        if self.phase == self.PHASE_COOLING:
            if self.T <= self.cooling_target + 0.5:
                self.phase = self.PHASE_STORED
                self.valve_cooling = 0.0

        elif self.phase == self.PHASE_DRAINING:
            # simplified: instant drain
            self.V = 0.0
            self.phase = self.PHASE_EMPTY
            self.valve_drain = False

        self.time_h += dt_h
        return self.get_state()

    def get_state(self) -> dict:
        return {
            "vessel": self.vessel_name,
            "time_h": round(self.time_h, 3),
            "temperature": round(self.T, 2),
            "volume_L": round(self.V, 2),
            "phase": self.phase,
            "valve_cooling": round(self.valve_cooling, 1),
            "valve_inlet": self.valve_inlet,
            "valve_drain": self.valve_drain,
        }
