"""Anaerobic Digestion Model for biogas production.

Based on simplified ADM1 (Anaerobic Digestion Model No. 1).
Models the biochemical conversion of organic substrates to biogas (CH4 + CO2).

Key processes:
    1. Hydrolysis: Complex organics -> Soluble organics
    2. Acidogenesis: Soluble organics -> Volatile fatty acids (VFA)
    3. Acetogenesis: VFA -> Acetate + H2
    4. Methanogenesis: Acetate/H2 -> CH4 + CO2
"""

import numpy as np


class AnaerobicDigester:
    """Continuous stirred-tank reactor (CSTR) anaerobic digester model."""

    # Default design parameters (mesophilic)
    DEFAULT_PARAMS = {
        "volume": 2000.0,           # m3 - digester volume
        "temperature": 37.0,         # C - mesophilic range
        "hrt": 20.0,                 # days - hydraulic retention time
        "feed_vs_concentration": 40.0,  # g/L - volatile solids in feed
        "ph_setpoint": 7.0,         # target pH
    }

    # Kinetic parameters (Monod kinetics)
    KINETICS = {
        "k_hyd": 0.25,      # 1/day - hydrolysis rate constant
        "k_acid": 5.0,      # 1/day - acidogenesis max rate
        "Ks_acid": 0.5,     # g/L - half-saturation (acidogenesis)
        "k_meth": 8.0,      # 1/day - methanogenesis max rate
        "Ks_meth": 0.3,     # g/L - half-saturation (methanogenesis)
        "Y_acid": 0.10,     # g/g - acidogen yield
        "Y_meth": 0.05,     # g/g - methanogen yield
    }

    # Biogas composition ranges
    BIOGAS = {
        "ch4_fraction_nominal": 0.60,   # 60% CH4 typical
        "co2_fraction_nominal": 0.35,   # 35% CO2
        "h2s_ppm_nominal": 500,         # ppm H2S
        "yield_nm3_per_kgVS": 0.5,     # Nm3 biogas per kg VS destroyed
    }

    def __init__(self, params: dict | None = None):
        p = {**self.DEFAULT_PARAMS, **(params or {})}
        self.volume = p["volume"]
        self.temperature = p["temperature"]
        self.hrt = p["hrt"]
        self.feed_vs = p["feed_vs_concentration"]

        # State variables
        self.vs_concentration = self.feed_vs * 0.5  # g/L
        self.vfa_concentration = 1.0                  # g/L
        self.acetate_concentration = 0.5              # g/L
        self.ph = 7.0
        self.biogas_flow = 0.0      # Nm3/h
        self.methane_content = 60.0  # %
        self.co2_content = 35.0      # %
        self.h2s_ppm = 500.0
        self.acidogen_biomass = 0.5  # g/L
        self.methanogen_biomass = 0.3  # g/L

    def step(self, dt: float, feed_rate: float = None) -> dict:
        """Advance digester state by dt seconds.

        Args:
            dt: Time step in seconds.
            feed_rate: Feedstock volumetric feed rate (m3/h). Defaults to V/HRT.

        Returns:
            Dict of current state variables.
        """
        dt_days = dt / 86400.0
        k = self.KINETICS

        if feed_rate is None:
            feed_rate = self.volume / (self.hrt * 24.0)  # m3/h

        dilution_rate = feed_rate / self.volume  # 1/h
        D = dilution_rate * 24.0  # 1/day

        # Hydrolysis
        r_hyd = k["k_hyd"] * self.vs_concentration

        # Acidogenesis (Monod)
        r_acid = (k["k_acid"] * self.vfa_concentration /
                  (k["Ks_acid"] + self.vfa_concentration)) * self.acidogen_biomass

        # Methanogenesis (Monod)
        r_meth = (k["k_meth"] * self.acetate_concentration /
                  (k["Ks_meth"] + self.acetate_concentration)) * self.methanogen_biomass

        # Temperature correction (Arrhenius-type)
        temp_factor = np.exp(0.069 * (self.temperature - 35.0))

        # Mass balance updates
        self.vs_concentration += (D * (self.feed_vs - self.vs_concentration) - r_hyd * temp_factor) * dt_days
        self.vfa_concentration += (r_hyd * temp_factor - r_acid * temp_factor - D * self.vfa_concentration) * dt_days
        self.acetate_concentration += (r_acid * temp_factor * 0.6 - r_meth * temp_factor - D * self.acetate_concentration) * dt_days

        # Biomass growth
        self.acidogen_biomass += (k["Y_acid"] * r_acid * temp_factor - D * self.acidogen_biomass) * dt_days
        self.methanogen_biomass += (k["Y_meth"] * r_meth * temp_factor - D * self.methanogen_biomass) * dt_days

        # Biogas production
        vs_destroyed = r_hyd * temp_factor * self.volume / 1000.0  # kg/day
        biogas_daily = vs_destroyed * self.BIOGAS["yield_nm3_per_kgVS"]  # Nm3/day
        self.biogas_flow = biogas_daily / 24.0  # Nm3/h

        # pH model (simplified Henderson-Hasselbalch)
        total_vfa = self.vfa_concentration + self.acetate_concentration
        self.ph = 7.0 - 0.5 * np.log10(max(total_vfa / 2.0, 0.01))
        self.ph = np.clip(self.ph, 5.5, 8.5)

        # Biogas composition (pH-dependent)
        self.methane_content = self.BIOGAS["ch4_fraction_nominal"] * 100 * (0.8 + 0.2 * (self.ph - 6.0) / 1.5)
        self.methane_content = np.clip(self.methane_content, 45.0, 75.0)
        self.co2_content = 100.0 - self.methane_content - 5.0  # ~5% other gases
        self.h2s_ppm = self.BIOGAS["h2s_ppm_nominal"] * (1.0 + 0.5 * (7.0 - self.ph))

        # Enforce non-negative
        self.vs_concentration = max(self.vs_concentration, 0.0)
        self.vfa_concentration = max(self.vfa_concentration, 0.0)
        self.acetate_concentration = max(self.acetate_concentration, 0.0)

        return self.get_state()

    def get_state(self) -> dict:
        return {
            "temperature": self.temperature,
            "ph": round(self.ph, 2),
            "biogas_flow_rate": round(self.biogas_flow, 2),
            "methane_content": round(self.methane_content, 1),
            "co2_content": round(self.co2_content, 1),
            "h2s_ppm": round(self.h2s_ppm, 0),
            "volatile_solids": round(self.vs_concentration, 2),
            "vfa_concentration": round(self.vfa_concentration, 2),
            "hydraulic_retention_time": self.hrt,
            "organic_loading_rate": round(self.feed_vs / self.hrt, 2),
        }
