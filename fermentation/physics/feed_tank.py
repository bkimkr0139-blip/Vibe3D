"""
Feed tank model — volume/temperature tracking with steam sterilization.

P&ID reference (Ko Bio Tech, CBF-2009):
  Page 5: KF-70L FEED TANK   — 8A dosing, 15A CWS, 8A transfer
  Page 6: KF-500L FEED TANK  — 10A dosing, 20A CWS, 15A transfer
  Page 7: KF-4000L FEED TANK — 20A dosing, 40A CWS, 20A transfer

Each feed tank includes:
  - Steam jacket + internal coil for sterilization (121 °C)
  - CWS jacket with heat exchanger for cooling
  - Transfer line (with steam barrier) to corresponding fermentor
  - Agitator for mixing
  - Wet scrubber exhaust
"""

import math


FEED_TANK_CONFIGS = {
    "KF-70L-FD": {
        "volume_L": 100.0,
        "working_volume_L": 80.0,
        "jacket_area_m2": 0.18,
        # Piping from P&ID Page 5
        "pipe_top_opening": "2.5in",
        "pipe_steam": "8A",
        "pipe_cws": "15A",
        "pipe_transfer": "8A",
        "transfer_rate_L_per_min": 4.0,     # 8A @ ~1 m/s
        "target_fermentor": "KF-70L",
    },
    "KF-500L-FD": {
        "volume_L": 500.0,
        "working_volume_L": 400.0,
        "jacket_area_m2": 0.8,
        # Piping from P&ID Page 6
        "pipe_top_opening": "5in",
        "pipe_steam": "10A",
        "pipe_cws": "20A",
        "pipe_transfer": "15A",
        "transfer_rate_L_per_min": 12.0,    # 15A @ ~1 m/s
        "target_fermentor": "KF-700L",
    },
    "KF-4KL-FD": {
        "volume_L": 4000.0,
        "working_volume_L": 3200.0,
        "jacket_area_m2": 5.0,
        # Piping from P&ID Page 7
        "pipe_top_opening": "10in",
        "pipe_steam": "20A",
        "pipe_cws": "40A",
        "pipe_transfer": "20A",
        "transfer_rate_L_per_min": 22.0,    # 20A @ ~1 m/s
        "target_fermentor": "KF-7KL",
    },
}


DEFAULT_PARAMS = {
    "vessel": "KF-4KL-FD",
    "jacket_U": 450.0,           # W/(m2*K)
    "broth_Cp": 4180.0,          # J/(kg*K)
    "broth_density": 1020.0,     # kg/m3
    "sterilization_T": 121.0,    # °C
    "sterilization_hold_min": 20.0,
    "cooling_target_T": 30.0,    # °C
    "transfer_rate_L_per_min": 50.0,
    "T0": 25.0,
    "V0_fraction": 0.8,
    "S_media": 20.0,             # g/L  substrate in media
}


class FeedTank:
    """Feed / media preparation tank with sterilization cycle."""

    DEFAULT_PARAMS = DEFAULT_PARAMS

    # Sterilization phases
    PHASE_IDLE = "idle"
    PHASE_HEATING = "heating"
    PHASE_HOLDING = "holding"
    PHASE_COOLING = "cooling"
    PHASE_READY = "ready"
    PHASE_TRANSFERRING = "transferring"
    PHASE_EMPTY = "empty"

    def __init__(self, params: dict | None = None):
        p = {**self.DEFAULT_PARAMS, **(params or {})}

        vessel_name = p["vessel"]
        vc = FEED_TANK_CONFIGS.get(vessel_name, FEED_TANK_CONFIGS["KF-4KL-FD"])
        self.vessel_name = vessel_name
        self.volume_L = vc["volume_L"]
        self.working_volume_L = vc["working_volume_L"]
        self.jacket_area = vc["jacket_area_m2"]

        self.jacket_U = p["jacket_U"]
        self.Cp = p["broth_Cp"]
        self.rho = p["broth_density"]
        self.sterilization_T = p["sterilization_T"]
        self.sterilization_hold_s = p["sterilization_hold_min"] * 60.0
        self.cooling_target = p["cooling_target_T"]
        self.transfer_rate = vc.get("transfer_rate_L_per_min", p["transfer_rate_L_per_min"])

        # State
        self.T = p["T0"]
        self.V = self.working_volume_L * p["V0_fraction"]
        self.S_media = p["S_media"]
        self.phase = self.PHASE_IDLE
        self.hold_elapsed_s = 0.0
        self.sterile = False

        # Actuators
        self.valve_steam = 0.0       # 0-100 %
        self.valve_cooling = 0.0     # 0-100 %
        self.valve_transfer = False  # on/off

        self.time_h = 0.0

    def start_sterilization(self):
        """Begin steam sterilization cycle."""
        if self.phase == self.PHASE_IDLE and self.V > 0:
            self.phase = self.PHASE_HEATING
            self.valve_steam = 100.0
            self.valve_cooling = 0.0
            self.sterile = False
            self.hold_elapsed_s = 0.0

    def start_transfer(self):
        """Begin transfer to fermentor."""
        if self.phase == self.PHASE_READY and self.V > 0:
            self.phase = self.PHASE_TRANSFERRING
            self.valve_transfer = True

    def step(self, dt: float, jacket_T_override: float | None = None) -> dict:
        """Advance by dt seconds."""
        dt_h = dt / 3600.0

        # Determine jacket temperature based on valves
        steam_frac = self.valve_steam / 100.0
        cool_frac = self.valve_cooling / 100.0
        if steam_frac > 0:
            jacket_T = 140.0  # steam jacket ~140 °C
        elif cool_frac > 0:
            jacket_T = 5.0 + (25.0 - 5.0) * (1.0 - cool_frac)
        else:
            jacket_T = self.T  # adiabatic

        if jacket_T_override is not None:
            jacket_T = jacket_T_override

        # Heat transfer
        if self.V > 0:
            mass_kg = (self.V / 1000.0) * self.rho  # V in m3 * density in kg/m3
            Q = self.jacket_U * self.jacket_area * (jacket_T - self.T)
            dT = Q / (mass_kg * self.Cp) * dt
            self.T += dT

        # Phase state machine
        if self.phase == self.PHASE_HEATING:
            if self.T >= self.sterilization_T:
                self.phase = self.PHASE_HOLDING
                self.hold_elapsed_s = 0.0

        elif self.phase == self.PHASE_HOLDING:
            self.hold_elapsed_s += dt
            if self.hold_elapsed_s >= self.sterilization_hold_s:
                self.phase = self.PHASE_COOLING
                self.valve_steam = 0.0
                self.valve_cooling = 100.0
                self.sterile = True

        elif self.phase == self.PHASE_COOLING:
            if self.T <= self.cooling_target:
                self.phase = self.PHASE_READY
                self.valve_cooling = 0.0

        elif self.phase == self.PHASE_TRANSFERRING:
            transfer_vol = self.transfer_rate * (dt / 60.0)
            transfer_vol = min(transfer_vol, self.V)
            self.V -= transfer_vol
            if self.V <= 0.1:
                self.V = 0.0
                self.phase = self.PHASE_EMPTY
                self.valve_transfer = False

        self.time_h += dt_h
        return self.get_state()

    def get_transferred_volume(self, dt: float) -> float:
        """Calculate volume transferred this step (L)."""
        if self.phase != self.PHASE_TRANSFERRING:
            return 0.0
        return min(self.transfer_rate * (dt / 60.0), self.V)

    def get_state(self) -> dict:
        return {
            "vessel": self.vessel_name,
            "time_h": round(self.time_h, 3),
            "temperature": round(self.T, 2),
            "volume_L": round(self.V, 2),
            "phase": self.phase,
            "sterile": self.sterile,
            "S_media": round(self.S_media, 2),
            "hold_elapsed_s": round(self.hold_elapsed_s, 1),
            "valve_steam": round(self.valve_steam, 1),
            "valve_cooling": round(self.valve_cooling, 1),
            "valve_transfer": self.valve_transfer,
        }
