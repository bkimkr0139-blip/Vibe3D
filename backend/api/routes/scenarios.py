"""Training scenario management endpoints."""

from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("/")
async def list_scenarios():
    """List all available training scenarios."""
    return {
        "scenarios": [
            {
                "id": "normal_startup",
                "name": "Normal Plant Startup",
                "description": "Standard biomass/biogas plant startup sequence",
            },
            {
                "id": "biogas_composition_change",
                "name": "Biogas Composition Change",
                "description": "Handle sudden methane content variation in biogas",
            },
            {
                "id": "feedstock_switch",
                "name": "Feedstock Switching",
                "description": "Transition between different biomass feedstock types",
            },
            {
                "id": "digester_upset",
                "name": "Digester Upset Recovery",
                "description": "Recover from anaerobic digester pH/temperature upset",
            },
            {
                "id": "emergency_shutdown",
                "name": "Emergency Shutdown",
                "description": "Execute emergency plant shutdown procedure",
            },
        ]
    }


@router.get("/{scenario_id}")
async def get_scenario(scenario_id: str):
    """Get detailed scenario configuration."""
    raise HTTPException(status_code=501, detail="Not implemented yet")
