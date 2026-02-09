"""
Media (culture medium) database for fermentation.

Each medium is a dict with composition and physical properties.
"""


MEDIA_DB = {
    "glucose_minimal": {
        "name": "Glucose Minimal Medium",
        "description": "Defined minimal medium with glucose as sole carbon source",
        "glucose_g_L": 20.0,
        "nitrogen_g_L": 2.0,
        "phosphate_g_L": 1.0,
        "sulfate_g_L": 0.5,
        "trace_metals": True,
        "vitamins": False,
        "initial_pH": 7.0,
        "density_kg_m3": 1005.0,
        "substrate_conc_g_L": 20.0,
    },
    "complex_yeast": {
        "name": "Complex Yeast Medium (YPD)",
        "description": "Yeast extract + peptone + dextrose",
        "glucose_g_L": 20.0,
        "yeast_extract_g_L": 10.0,
        "peptone_g_L": 20.0,
        "nitrogen_g_L": 5.0,
        "phosphate_g_L": 1.5,
        "sulfate_g_L": 0.3,
        "trace_metals": True,
        "vitamins": True,
        "initial_pH": 6.5,
        "density_kg_m3": 1015.0,
        "substrate_conc_g_L": 20.0,
    },
    "corn_steep": {
        "name": "Corn Steep Liquor Medium",
        "description": "Industrial medium with corn steep liquor as nitrogen source",
        "glucose_g_L": 30.0,
        "corn_steep_g_L": 15.0,
        "nitrogen_g_L": 4.0,
        "phosphate_g_L": 2.0,
        "sulfate_g_L": 0.5,
        "trace_metals": True,
        "vitamins": True,
        "initial_pH": 6.8,
        "density_kg_m3": 1020.0,
        "substrate_conc_g_L": 30.0,
    },
    "soy_hydrolysate": {
        "name": "Soy Hydrolysate Medium",
        "description": "Soy-based industrial medium for high-density cultures",
        "glucose_g_L": 40.0,
        "soy_hydrolysate_g_L": 20.0,
        "nitrogen_g_L": 6.0,
        "phosphate_g_L": 2.5,
        "sulfate_g_L": 0.8,
        "trace_metals": True,
        "vitamins": True,
        "initial_pH": 7.0,
        "density_kg_m3": 1025.0,
        "substrate_conc_g_L": 40.0,
    },
}


def get_media(name: str) -> dict | None:
    """Get medium by name. Returns None if not found."""
    return MEDIA_DB.get(name)


def list_media() -> list[str]:
    """List all available media names."""
    return list(MEDIA_DB.keys())


def get_media_substrate(name: str) -> float:
    """Get substrate concentration (g/L) for a given medium."""
    media = MEDIA_DB.get(name)
    if media is None:
        return 20.0  # default
    return media["substrate_conc_g_L"]
