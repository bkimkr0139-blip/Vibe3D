"""SQLAlchemy ORM models for BIO plant simulation data.

Tables:
    simulations: Simulation metadata and lifecycle
    sensor_data: Time-series sensor data (TimescaleDB hypertable)
    events: Operational event logging
    alarms: Alarm management
    scenarios: Training scenario definitions
    evaluations: Training assessment results
    maintenance_logs: Predictive maintenance records
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Float, Integer, DateTime, Boolean,
    ForeignKey, Enum, Text, JSON,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Simulation(Base):
    __tablename__ = "simulations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    status = Column(
        Enum("pending", "running", "paused", "completed", "failed", "stopped",
             name="simulation_status"),
        default="pending",
    )
    plant_type = Column(String(50), nullable=False, default="biogas_engine")
    realtime_factor = Column(Float, default=1.0)
    scenario_id = Column(String(100), nullable=True)
    feedstock_type = Column(String(50), default="mixed_waste")
    start_time = Column(DateTime(timezone=True), nullable=True)
    end_time = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), onupdate=lambda: datetime.now(timezone.utc))

    sensor_data = relationship("SensorData", back_populates="simulation")
    events = relationship("Event", back_populates="simulation")


class SensorData(Base):
    """Time-series sensor data. Converted to TimescaleDB hypertable in init_db.sql."""
    __tablename__ = "sensor_data"

    id = Column(Integer, primary_key=True, autoincrement=True)
    time = Column(DateTime(timezone=True), nullable=False, index=True)
    simulation_id = Column(UUID(as_uuid=True), ForeignKey("simulations.id"), nullable=False)
    simulation_time = Column(Float, nullable=False)

    # Digester sensors
    digester_temp = Column(Float)
    digester_ph = Column(Float)
    biogas_flow_rate = Column(Float)
    methane_content = Column(Float)
    co2_content = Column(Float)
    h2s_ppm = Column(Float)
    volatile_solids = Column(Float)
    vfa_concentration = Column(Float)

    # Engine sensors
    engine_rpm = Column(Float)
    engine_power = Column(Float)
    engine_exhaust_temp = Column(Float)
    engine_fuel_flow = Column(Float)
    engine_efficiency = Column(Float)

    # Boiler sensors
    boiler_fuel_feed = Column(Float)
    steam_flow = Column(Float)
    steam_pressure = Column(Float)
    steam_temperature = Column(Float)
    combustion_temp = Column(Float)
    flue_gas_temp = Column(Float)
    boiler_efficiency = Column(Float)

    # Steam turbine sensors
    st_power = Column(Float)
    condenser_pressure = Column(Float)

    # Plant totals
    total_power = Column(Float)
    total_thermal = Column(Float)

    simulation = relationship("Simulation", back_populates="sensor_data")


class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    simulation_id = Column(UUID(as_uuid=True), ForeignKey("simulations.id"), nullable=False)
    event_type = Column(String(50), nullable=False)
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    severity = Column(String(20), default="info")
    message = Column(Text)
    data = Column(JSON, nullable=True)

    simulation = relationship("Simulation", back_populates="events")


class Scenario(Base):
    __tablename__ = "scenarios"

    id = Column(String(100), primary_key=True)
    name = Column(String(200), nullable=False)
    description = Column(Text)
    initial_conditions = Column(JSON)
    plant_type = Column(String(50))
    difficulty = Column(String(20), default="normal")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
