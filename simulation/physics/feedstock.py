"""Biomass feedstock property database.

Provides physical/chemical properties for various biomass and waste feedstocks
used in anaerobic digestion and direct combustion.
"""

FEEDSTOCK_DB = {
    # Anaerobic digestion feedstocks
    "food_waste": {
        "category": "digestion",
        "total_solids": 0.25,           # fraction
        "volatile_solids_ratio": 0.90,  # VS/TS
        "biogas_yield": 0.65,           # Nm3/kgVS
        "methane_fraction": 0.62,
        "c_n_ratio": 15.0,
        "description": "Municipal food waste",
    },
    "sewage_sludge": {
        "category": "digestion",
        "total_solids": 0.05,
        "volatile_solids_ratio": 0.75,
        "biogas_yield": 0.35,
        "methane_fraction": 0.65,
        "c_n_ratio": 8.0,
        "description": "Municipal sewage sludge",
    },
    "cattle_manure": {
        "category": "digestion",
        "total_solids": 0.10,
        "volatile_solids_ratio": 0.80,
        "biogas_yield": 0.25,
        "methane_fraction": 0.60,
        "c_n_ratio": 20.0,
        "description": "Dairy cattle manure",
    },
    "corn_silage": {
        "category": "digestion",
        "total_solids": 0.33,
        "volatile_solids_ratio": 0.95,
        "biogas_yield": 0.55,
        "methane_fraction": 0.52,
        "c_n_ratio": 40.0,
        "description": "Corn silage energy crop",
    },
    "mixed_waste": {
        "category": "digestion",
        "total_solids": 0.15,
        "volatile_solids_ratio": 0.82,
        "biogas_yield": 0.45,
        "methane_fraction": 0.58,
        "c_n_ratio": 18.0,
        "description": "Mixed organic waste (default)",
    },

    # Combustion feedstocks
    "wood_chips": {
        "category": "combustion",
        "moisture": 0.30,
        "lhv": 12.5,                    # MJ/kg as-received
        "ash_content": 0.01,
        "carbon": 0.35,
        "hydrogen": 0.04,
        "nitrogen": 0.001,
        "sulfur": 0.0005,
        "description": "Softwood chips (30% MC)",
    },
    "wood_pellets": {
        "category": "combustion",
        "moisture": 0.08,
        "lhv": 17.0,
        "ash_content": 0.005,
        "carbon": 0.46,
        "hydrogen": 0.055,
        "nitrogen": 0.001,
        "sulfur": 0.0003,
        "description": "EN-Plus A1 wood pellets",
    },
    "straw": {
        "category": "combustion",
        "moisture": 0.14,
        "lhv": 14.5,
        "ash_content": 0.05,
        "carbon": 0.40,
        "hydrogen": 0.05,
        "nitrogen": 0.005,
        "sulfur": 0.001,
        "description": "Cereal straw bales",
    },
    "palm_kernel_shell": {
        "category": "combustion",
        "moisture": 0.12,
        "lhv": 16.0,
        "ash_content": 0.03,
        "carbon": 0.44,
        "hydrogen": 0.05,
        "nitrogen": 0.003,
        "sulfur": 0.001,
        "description": "Palm kernel shell (PKS)",
    },
}


def get_feedstock(name: str) -> dict:
    """Get feedstock properties by name."""
    if name not in FEEDSTOCK_DB:
        raise ValueError(f"Unknown feedstock: {name}. Available: {list(FEEDSTOCK_DB.keys())}")
    return FEEDSTOCK_DB[name]


def list_feedstocks(category: str | None = None) -> list[str]:
    """List available feedstock names, optionally filtered by category."""
    if category:
        return [k for k, v in FEEDSTOCK_DB.items() if v["category"] == category]
    return list(FEEDSTOCK_DB.keys())
