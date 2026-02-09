"""Pydantic schemas for fermentation API."""

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field


class FermentationMode(str, Enum):
    SINGLE_7KL = "single_7kl"
    SEED_TRAIN = "seed_train"
    FULL_FACILITY = "full_facility"


class FermentationStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    STOPPED = "stopped"


class FermentationCreate(BaseModel):
    """Request to start a new fermentation simulation."""
    mode: FermentationMode = FermentationMode.SINGLE_7KL
    realtime_factor: float = Field(default=1.0, ge=0.1, le=100.0)
    media_type: str = Field(default="glucose_minimal")


class FermentationResponse(BaseModel):
    """Response after creating a fermentation simulation."""
    id: UUID
    status: FermentationStatus
    mode: FermentationMode
    created_at: datetime


class FermentorState(BaseModel):
    """Single fermentor state snapshot."""
    vessel: str
    time_h: float
    X: float = Field(description="Biomass concentration (g/L)")
    S: float = Field(description="Substrate concentration (g/L)")
    pH: float = Field(description="pH")
    DO: float = Field(description="Dissolved oxygen (mg/L)")
    temperature: float = Field(description="Broth temperature (°C)")
    volume_L: float = Field(description="Current volume (L)")
    rpm: float = Field(description="Impeller speed (RPM)")
    aeration_vvm: float = Field(description="Aeration rate (vvm)")
    jacket_T: float = Field(description="Jacket temperature (°C)")
    valve_acid: bool
    valve_base: bool
    valve_antifoam: bool
    valve_steam: float
    valve_cooling: float
    total_base_added_L: float
    total_acid_added_L: float


class SensorReadings(BaseModel):
    """Sensor readings for a vessel."""
    pH: float | None = None
    DO: float | None = None
    temperature: float | None = None
    pressure: float | None = None


class FermentationState(BaseModel):
    """Full fermentation simulation state."""
    simulation_id: UUID
    status: FermentationStatus
    simulation_time: float = Field(description="Elapsed simulation time (s)")
    mode: FermentationMode
    fermentors: dict[str, FermentorState] = {}
    sensors: dict[str, SensorReadings] = {}
    dosing: dict = {}
    feed_tanks: dict = {}
    broth_tank: dict | None = None


class FermentationControl(BaseModel):
    """Manual control input for a fermentor."""
    rpm_setpoint: float | None = Field(default=None, description="RPM setpoint")
    aeration_vvm: float | None = Field(default=None, description="Aeration (vvm)")
    valve_acid: bool | None = None
    valve_base: bool | None = None
    valve_antifoam: bool | None = None
    valve_steam: float | None = Field(default=None, ge=0, le=100)
    valve_cooling: float | None = Field(default=None, ge=0, le=100)
    start_base_dosing: bool | None = Field(default=None, description="Trigger base dosing sequence")
    start_acid_dosing: bool | None = Field(default=None, description="Trigger acid dosing sequence")


class AnomalyAlert(BaseModel):
    """Anomaly detection alert."""
    vessel: str
    parameter: str
    value: float
    setpoint: float
    deviation: float
    severity: str = Field(description="low / medium / high / critical")
    timestamp: datetime
    message: str
