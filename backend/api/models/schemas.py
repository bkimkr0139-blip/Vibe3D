"""Pydantic schemas for API request/response models."""

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field


class PlantType(str, Enum):
    """Supported biomass/biogas plant configurations."""
    BIOGAS_ENGINE = "biogas_engine"          # Anaerobic digester + gas engine
    BIOMASS_BOILER = "biomass_boiler"        # Biomass combustion + steam turbine
    COMBINED = "combined"                     # Both biogas + biomass systems


class SimulationStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


class SimulationCreate(BaseModel):
    """Request to start a new simulation."""
    plant_type: PlantType = PlantType.BIOGAS_ENGINE
    scenario_id: str | None = None
    realtime_factor: float = Field(default=1.0, ge=0.1, le=100.0)
    feedstock_type: str = Field(default="mixed_waste", description="Biomass feedstock type")


class SimulationResponse(BaseModel):
    """Response after creating a simulation."""
    id: UUID
    status: SimulationStatus
    plant_type: PlantType
    created_at: datetime


class DigesterState(BaseModel):
    """Anaerobic digester state variables."""
    temperature: float = Field(description="Digester temperature (C)")
    ph: float = Field(description="pH level")
    biogas_flow_rate: float = Field(description="Biogas production rate (Nm3/h)")
    methane_content: float = Field(description="CH4 percentage in biogas (%)")
    co2_content: float = Field(description="CO2 percentage in biogas (%)")
    h2s_content: float = Field(description="H2S content (ppm)")
    volatile_solids: float = Field(description="Volatile solids concentration (g/L)")
    hydraulic_retention_time: float = Field(description="HRT (days)")
    organic_loading_rate: float = Field(description="OLR (kgVS/m3/day)")


class EngineState(BaseModel):
    """Biogas engine state variables."""
    rpm: float = Field(description="Engine speed (RPM)")
    power_output: float = Field(description="Electrical power output (kW)")
    exhaust_temp: float = Field(description="Exhaust gas temperature (C)")
    fuel_flow: float = Field(description="Biogas consumption rate (Nm3/h)")
    air_fuel_ratio: float = Field(description="Air-fuel ratio")
    electrical_efficiency: float = Field(description="Electrical efficiency (%)")
    thermal_efficiency: float = Field(description="Thermal efficiency (%)")


class BoilerState(BaseModel):
    """Biomass boiler state variables."""
    steam_pressure: float = Field(description="Steam drum pressure (bar)")
    steam_temperature: float = Field(description="Superheated steam temperature (C)")
    feedwater_temp: float = Field(description="Feedwater temperature (C)")
    fuel_feed_rate: float = Field(description="Biomass fuel feed rate (kg/h)")
    combustion_temp: float = Field(description="Furnace temperature (C)")
    flue_gas_temp: float = Field(description="Flue gas exit temperature (C)")
    steam_flow: float = Field(description="Steam mass flow rate (kg/h)")
    boiler_efficiency: float = Field(description="Boiler thermal efficiency (%)")


class PlantOverview(BaseModel):
    """Overall plant performance metrics."""
    total_power_output: float = Field(description="Total electrical output (kW)")
    total_thermal_output: float = Field(description="Total thermal output (kW)")
    overall_efficiency: float = Field(description="Overall CHP efficiency (%)")
    co2_emissions: float = Field(description="CO2 emission rate (kg/h)")
    nox_emissions: float = Field(description="NOx emission rate (g/h)")


class SimulationState(BaseModel):
    """Full simulation state snapshot."""
    simulation_id: UUID
    status: SimulationStatus
    simulation_time: float = Field(description="Elapsed simulation time (s)")
    digester: DigesterState | None = None
    engine: EngineState | None = None
    boiler: BoilerState | None = None
    plant: PlantOverview


class ControlAdjustment(BaseModel):
    """Manual control parameter adjustment."""
    parameter: str = Field(description="Parameter name to adjust")
    value: float = Field(description="New setpoint value")
    ramp_rate: float | None = Field(default=None, description="Rate of change per second")
