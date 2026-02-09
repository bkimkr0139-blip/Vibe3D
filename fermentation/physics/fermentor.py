"""
Fermentor physics model — Monod growth kinetics with pH, DO, and temperature.

Vessel configurations for Chuncheon Bio Industry Promotion Institute:
  KF-70L   (seed fermentor, 70 L)
  KF-700L  (pilot fermentor, 700 L)
  KF-7KL   (production fermentor, 7000 L)

P&ID reference: 제안용_PnID-(CBF-2009년).pdf, Ko Bio Tech
Valve legend (common to all fermentors):
  - Acid / Base / Anti-foamer: Pneumatic Diaphragm Valve (on/off)
  - Steam jacket / CWS jacket: Control Valve (0-100%)
  - Transfer: Pneumatic Valve (STS 304)
  - Drain: Ball Valve STS (manual)
"""

import math
import numpy as np


# ---------------------------------------------------------------------------
# Pipe bore → flow capacity (at 1 m/s liquid velocity)
# Korean "A" sizes ≈ DN mm nominal bore
# ---------------------------------------------------------------------------
PIPE_FLOW_L_PER_H = {
    "8A":   239,     # DN8,  ID ~9.2 mm
    "10A":  442,     # DN10, ID ~12.5 mm
    "13A":  733,     # DN13/15, ID ~16.1 mm
    "15A":  733,     # DN15, ID ~16.1 mm
    "20A":  1331,    # DN20, ID ~21.7 mm
    "25A":  2154,    # DN25, ID ~27.6 mm
    "40A":  4800,    # DN40, ID ~41.2 mm
}


# ---------------------------------------------------------------------------
# Vessel configurations (from P&ID + Layout drawings)
# ---------------------------------------------------------------------------
VESSEL_CONFIGS = {
    "KF-70L": {
        "volume_L": 70.0,
        "working_volume_L": 50.0,
        # Geometry: ~400 mm dia × ~700 mm cyl height
        "vessel_diameter_mm": 400,
        "jacket_area_m2": 0.38,       # π×0.4×0.5 × 60% coverage
        "impeller_diameter_m": 0.08,
        "max_rpm": 800,
        "max_aeration_vvm": 2.0,
        "pressure_design_bar": 2.5,
        # Piping from P&ID (Page 2: KF-70L FERMENTOR)
        "pipe_dosing": "8A",          # Acid/Base/Antifoam lines
        "pipe_steam": "13A",          # Steam jacket supply
        "pipe_cws": "15A",            # CWS jacket supply
        "pipe_transfer": "8A",        # Seed transfer out
        "pipe_air": "8A",             # Air supply (sparger)
        # Dosing flow rates (derived from 8A pipe + diaphragm Cv)
        "acid_flow_L_h": 1.0,
        "base_flow_L_h": 1.0,
        "antifoam_flow_L_h": 0.3,
        # Connections (from Transfer Line Flow, Page 1)
        "feed_tank": "KF-70L-FD",
        "seed_target": "KF-700L",     # seed train: 70L → 700L
    },
    "KF-700L": {
        "volume_L": 700.0,
        "working_volume_L": 500.0,
        # Geometry: ~800 mm dia × ~1400 mm cyl height
        "vessel_diameter_mm": 800,
        "jacket_area_m2": 1.5,        # π×0.8×1.0 × 60%
        "impeller_diameter_m": 0.18,
        "max_rpm": 500,
        "max_aeration_vvm": 1.5,
        "pressure_design_bar": 2.5,
        # Piping from P&ID (Page 3: KF-700L FERMENTOR)
        "pipe_dosing": "10A",
        "pipe_steam": "15A",
        "pipe_cws": "20A",
        "pipe_transfer": "15A",
        "pipe_air": "10A",
        # Dosing flow rates
        "acid_flow_L_h": 3.0,
        "base_flow_L_h": 3.0,
        "antifoam_flow_L_h": 1.0,
        # Connections
        "feed_tank": "KF-500L-FD",
        "seed_target": "KF-7KL",      # seed train: 700L → 7KL
    },
    "KF-7KL": {
        "volume_L": 7000.0,
        "working_volume_L": 5000.0,
        # Geometry: 1800 mm dia × ~2750 mm cyl (from Layout: φ1800)
        "vessel_diameter_mm": 1800,
        "jacket_area_m2": 7.8,        # π×1.8×2.0 × 70%
        "impeller_diameter_m": 0.45,
        "max_rpm": 300,
        "max_aeration_vvm": 1.0,
        "pressure_design_bar": 2.5,
        # Piping from P&ID (Page 4: KF-7KL FERMENTOR)
        "pipe_dosing": "20A",
        "pipe_steam": "25A",
        "pipe_cws": "40A",
        "pipe_transfer": "25A",        # Broth transfer to 7KL BROTH
        "pipe_air": "20A",
        # Dosing flow rates
        "acid_flow_L_h": 10.0,
        "base_flow_L_h": 10.0,
        "antifoam_flow_L_h": 3.0,
        # Connections
        "feed_tank": "KF-4KL-FD",
        "broth_tank": "KF-7000L",     # harvest → broth tank
    },
}


DEFAULT_PARAMS = {
    # Vessel (defaults to KF-7KL)
    "vessel": "KF-7KL",
    # Kinetics (Monod)
    "mu_max": 0.45,           # 1/h  maximum specific growth rate
    "Ks": 0.5,                # g/L  substrate half-saturation
    "Ko": 0.02,               # mg/L DO half-saturation
    "Y_xs": 0.5,              # g_X / g_S  biomass yield on substrate
    "m_s": 0.02,              # g_S / (g_X * h)  maintenance coefficient
    "Y_acid": 0.08,           # mol_acid / g_S  metabolic acid production yield
    # pH model
    "pH_opt": 7.0,
    "pH_range": 1.5,          # half-width of pH growth window
    "buffer_capacity": 0.05,  # mol/L/pH  simplified buffer capacity
    # DO model
    "C_star_mg_L": 7.6,       # saturation DO at 30 °C, 1 atm
    "kLa_base": 120.0,        # 1/h  base kLa at reference RPM/vvm
    "rpm_ref": 200.0,
    "vvm_ref": 0.5,
    "OUR_coeff": 0.35,        # mmol_O2 / (g_X * h)  specific OUR
    # Temperature model
    "T_opt": 30.0,            # °C  optimum temperature
    "T_range": 10.0,          # °C  growth temperature half-width
    "jacket_U": 500.0,        # W/(m2*K)  overall heat transfer coeff
    "metabolic_heat_W_per_gX": 0.005,  # W / g_X  metabolic heat generation
    "broth_Cp": 4180.0,       # J/(kg*K)
    "broth_density": 1010.0,  # kg/m3
    # Agitation
    "rpm_ramp_rate": 50.0,    # RPM/min
    # Initial state
    "X0": 0.5,                # g/L  initial biomass
    "S0": 20.0,               # g/L  initial substrate
    "pH0": 7.0,
    "DO0": 7.0,               # mg/L
    "T0": 30.0,               # °C
    "V0_fraction": 0.7,       # initial fill fraction of working volume
    # Acid/base/antifoam concentrations
    "acid_conc_mol_L": 2.0,   # 2 M HCl
    "base_conc_mol_L": 2.0,   # 2 M NaOH
}


class Fermentor:
    """Bioreactor physics model with Monod kinetics, pH, DO, and temperature."""

    DEFAULT_PARAMS = DEFAULT_PARAMS

    def __init__(self, params: dict | None = None):
        p = {**self.DEFAULT_PARAMS, **(params or {})}

        # Vessel geometry
        vessel_name = p["vessel"]
        vc = VESSEL_CONFIGS.get(vessel_name, VESSEL_CONFIGS["KF-7KL"])
        self.vessel_name = vessel_name
        self.volume_L = vc["volume_L"]
        self.working_volume_L = vc["working_volume_L"]
        self.jacket_area = vc["jacket_area_m2"]
        self.max_rpm = vc["max_rpm"]
        self.max_vvm = vc["max_aeration_vvm"]

        # Kinetics
        self.mu_max = p["mu_max"]
        self.Ks = p["Ks"]
        self.Ko = p["Ko"]
        self.Y_xs = p["Y_xs"]
        self.m_s = p["m_s"]
        self.Y_acid = p["Y_acid"]

        # pH model
        self.pH_opt = p["pH_opt"]
        self.pH_range = p["pH_range"]
        self.buffer_capacity = p["buffer_capacity"]
        self.acid_conc = p["acid_conc_mol_L"]
        self.base_conc = p["base_conc_mol_L"]

        # DO model
        self.C_star = p["C_star_mg_L"]
        self.kLa_base = p["kLa_base"]
        self.rpm_ref = p["rpm_ref"]
        self.vvm_ref = p["vvm_ref"]
        self.OUR_coeff = p["OUR_coeff"]

        # Temperature model
        self.T_opt = p["T_opt"]
        self.T_range = p["T_range"]
        self.jacket_U = p["jacket_U"]
        self.metabolic_heat = p["metabolic_heat_W_per_gX"]
        self.Cp = p["broth_Cp"]
        self.rho = p["broth_density"]

        # Agitation
        self.rpm_ramp_rate = p["rpm_ramp_rate"]

        # State variables
        self.X = p["X0"]           # g/L biomass
        self.S = p["S0"]           # g/L substrate
        self.pH = p["pH0"]
        self.DO = p["DO0"]         # mg/L
        self.T = p["T0"]           # °C
        self.V = self.working_volume_L * p["V0_fraction"]  # L current volume
        self.acid_accumulated = 0.0  # mol accumulated metabolic acid

        # Actuator states
        self.rpm_setpoint = 0.0
        self.rpm = 0.0
        self.aeration_vvm = 0.0
        self.jacket_T = p["T0"]    # °C jacket fluid temperature
        self.feed_rate = 0.0       # L/h  feed input rate
        self.S_feed = 0.0          # g/L  feed substrate concentration

        # Valve states (Boolean for on/off, float 0-100 for proportional)
        self.valve_acid = False
        self.valve_base = False
        self.valve_antifoam = False
        self.valve_steam = 0.0      # 0-100 %
        self.valve_cooling = 0.0    # 0-100 %

        # Dosing flow rates from P&ID pipe sizes (L/h per valve open)
        self._acid_flow = vc.get("acid_flow_L_h", 5.0)
        self._base_flow = vc.get("base_flow_L_h", 5.0)
        self._antifoam_flow = vc.get("antifoam_flow_L_h", 1.0)

        # Cumulative trackers
        self.time_h = 0.0
        self.total_base_added_L = 0.0
        self.total_acid_added_L = 0.0

    # ------------------------------------------------------------------
    # Growth factor functions
    # ------------------------------------------------------------------
    def _f_temperature(self, T: float) -> float:
        """Temperature growth factor (Gaussian-like)."""
        return math.exp(-((T - self.T_opt) / self.T_range) ** 2)

    def _f_pH(self, pH: float) -> float:
        """pH growth factor (Gaussian-like)."""
        return math.exp(-((pH - self.pH_opt) / self.pH_range) ** 2)

    def _kLa(self, rpm: float, vvm: float) -> float:
        """Volumetric mass transfer coefficient (1/h)."""
        if rpm <= 0 or vvm <= 0:
            return 0.0
        rpm_ratio = rpm / max(self.rpm_ref, 1.0)
        vvm_ratio = vvm / max(self.vvm_ref, 0.01)
        return self.kLa_base * (rpm_ratio ** 0.7) * (vvm_ratio ** 0.5)

    # ------------------------------------------------------------------
    # Main physics step
    # ------------------------------------------------------------------
    def step(self, dt: float,
             rpm_setpoint: float | None = None,
             aeration_vvm: float | None = None,
             jacket_T: float | None = None,
             feed_rate: float | None = None,
             S_feed: float | None = None,
             valve_acid: bool | None = None,
             valve_base: bool | None = None,
             valve_antifoam: bool | None = None,
             valve_steam: float | None = None,
             valve_cooling: float | None = None,
             ) -> dict:
        """
        Advance simulation by dt seconds.
        Returns current state dict.
        """
        dt_h = dt / 3600.0  # convert seconds to hours

        # --- Update setpoints ---
        if rpm_setpoint is not None:
            self.rpm_setpoint = min(rpm_setpoint, self.max_rpm)
        if aeration_vvm is not None:
            self.aeration_vvm = min(aeration_vvm, self.max_vvm)
        if jacket_T is not None:
            self.jacket_T = jacket_T
        if feed_rate is not None:
            self.feed_rate = feed_rate
        if S_feed is not None:
            self.S_feed = S_feed
        if valve_acid is not None:
            self.valve_acid = valve_acid
        if valve_base is not None:
            self.valve_base = valve_base
        if valve_antifoam is not None:
            self.valve_antifoam = valve_antifoam
        if valve_steam is not None:
            self.valve_steam = max(0.0, min(100.0, valve_steam))
        if valve_cooling is not None:
            self.valve_cooling = max(0.0, min(100.0, valve_cooling))

        # --- Agitation ramp ---
        rpm_diff = self.rpm_setpoint - self.rpm
        max_change = self.rpm_ramp_rate * (dt / 60.0)  # RPM/min * min
        if abs(rpm_diff) > max_change:
            self.rpm += math.copysign(max_change, rpm_diff)
        else:
            self.rpm = self.rpm_setpoint

        # --- Jacket temperature from steam/cooling valves ---
        # Steam → raises jacket temp toward 121 °C
        # Cooling → lowers jacket temp toward 5 °C
        steam_frac = self.valve_steam / 100.0
        cool_frac = self.valve_cooling / 100.0
        jacket_target = self.T  # neutral
        if steam_frac > cool_frac:
            jacket_target = self.T + (121.0 - self.T) * steam_frac
        elif cool_frac > 0:
            jacket_target = self.T + (5.0 - self.T) * cool_frac
        tau_jacket = 60.0  # seconds time constant
        alpha_j = 1.0 - math.exp(-dt / tau_jacket)
        self.jacket_T = self.jacket_T + alpha_j * (jacket_target - self.jacket_T)

        # --- Dilution rate ---
        D = (self.feed_rate / max(self.V, 1.0)) if self.V > 0 else 0.0  # 1/h

        # --- Monod growth ---
        substrate_term = self.S / (self.Ks + self.S) if self.S > 0 else 0.0
        do_term = self.DO / (self.Ko + self.DO) if self.DO > 0 else 0.0
        f_T = self._f_temperature(self.T)
        f_pH = self._f_pH(self.pH)
        mu = self.mu_max * substrate_term * do_term * f_T * f_pH

        # --- Biomass ---
        dX = (mu - D) * self.X
        self.X = max(0.0, self.X + dX * dt_h)

        # --- Substrate ---
        dS = D * (self.S_feed - self.S) - (mu / self.Y_xs) * self.X - self.m_s * self.X
        self.S = max(0.0, self.S + dS * dt_h)

        # --- Dissolved Oxygen ---
        kLa = self._kLa(self.rpm, self.aeration_vvm)
        OTR = kLa * (self.C_star - self.DO)                 # mg/L/h
        OUR = self.OUR_coeff * self.X * 32.0                 # mg/L/h (mmol * 32 mg/mmol)
        dDO = OTR - OUR - D * self.DO
        self.DO = max(0.0, min(self.C_star * 1.2, self.DO + dDO * dt_h))

        # --- pH model ---
        # Metabolic acid production
        substrate_consumed = ((mu / self.Y_xs) * self.X + self.m_s * self.X) * dt_h
        acid_produced_mol = self.Y_acid * max(0.0, substrate_consumed)

        # Acid/base dosing
        acid_dosed_mol = 0.0
        base_dosed_mol = 0.0
        if self.valve_acid:
            acid_vol = self._acid_flow * dt_h  # L
            acid_dosed_mol = acid_vol * self.acid_conc
            self.total_acid_added_L += acid_vol
        if self.valve_base:
            base_vol = self._base_flow * dt_h  # L
            base_dosed_mol = base_vol * self.base_conc
            self.total_base_added_L += base_vol

        net_acid_mol = acid_produced_mol + acid_dosed_mol - base_dosed_mol
        volume_m3 = self.V / 1000.0
        if volume_m3 > 0 and self.buffer_capacity > 0:
            # delta pH = - net_acid / (buffer_capacity * volume)
            dpH = -net_acid_mol / (self.buffer_capacity * self.V)
            self.pH += dpH
            self.pH = max(2.0, min(12.0, self.pH))

        # --- Temperature ---
        V_m3 = self.V / 1000.0
        mass_kg = V_m3 * self.rho  # kg
        if mass_kg > 0:
            # Jacket heat transfer
            Q_jacket = self.jacket_U * self.jacket_area * (self.jacket_T - self.T)  # W
            # Metabolic heat
            Q_metabolic = self.metabolic_heat * self.X * self.V  # W
            dT = (Q_jacket + Q_metabolic) / (mass_kg * self.Cp) * dt  # °C
            self.T += dT

        # --- Volume ---
        feed_volume = self.feed_rate * dt_h
        dV = feed_volume
        if self.valve_acid:
            dV += self._acid_flow * dt_h
        if self.valve_base:
            dV += self._base_flow * dt_h
        self.V = min(self.working_volume_L, self.V + dV)

        # --- Time ---
        self.time_h += dt_h

        return self.get_state()

    def get_state(self) -> dict:
        """Return current fermentor state."""
        return {
            "vessel": self.vessel_name,
            "time_h": round(self.time_h, 3),
            "X": round(self.X, 4),           # g/L biomass
            "S": round(self.S, 4),           # g/L substrate
            "pH": round(self.pH, 3),
            "DO": round(self.DO, 3),         # mg/L
            "temperature": round(self.T, 2), # °C
            "volume_L": round(self.V, 2),
            "rpm": round(self.rpm, 1),
            "aeration_vvm": round(self.aeration_vvm, 3),
            "jacket_T": round(self.jacket_T, 2),
            "valve_acid": self.valve_acid,
            "valve_base": self.valve_base,
            "valve_antifoam": self.valve_antifoam,
            "valve_steam": round(self.valve_steam, 1),
            "valve_cooling": round(self.valve_cooling, 1),
            "total_base_added_L": round(self.total_base_added_L, 4),
            "total_acid_added_L": round(self.total_acid_added_L, 4),
        }
