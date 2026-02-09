-- BIO Database Initialization
-- Run after PostgreSQL + TimescaleDB container starts

-- Enable TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ============================================================
-- Simulations table
-- ============================================================
CREATE TABLE IF NOT EXISTS simulations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    status VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'paused', 'completed', 'failed', 'stopped')),
    plant_type VARCHAR(50) NOT NULL DEFAULT 'biogas_engine',
    realtime_factor FLOAT DEFAULT 1.0,
    scenario_id VARCHAR(100),
    feedstock_type VARCHAR(50) DEFAULT 'mixed_waste',
    start_time TIMESTAMPTZ,
    end_time TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ
);

-- ============================================================
-- Sensor data (time-series) — converted to hypertable
-- ============================================================
CREATE TABLE IF NOT EXISTS sensor_data (
    id SERIAL,
    time TIMESTAMPTZ NOT NULL,
    simulation_id UUID NOT NULL REFERENCES simulations(id),
    simulation_time FLOAT NOT NULL,

    -- Digester sensors
    digester_temp FLOAT,
    digester_ph FLOAT,
    biogas_flow_rate FLOAT,
    methane_content FLOAT,
    co2_content FLOAT,
    h2s_ppm FLOAT,
    volatile_solids FLOAT,
    vfa_concentration FLOAT,

    -- Engine sensors
    engine_rpm FLOAT,
    engine_power FLOAT,
    engine_exhaust_temp FLOAT,
    engine_fuel_flow FLOAT,
    engine_efficiency FLOAT,

    -- Boiler sensors
    boiler_fuel_feed FLOAT,
    steam_flow FLOAT,
    steam_pressure FLOAT,
    steam_temperature FLOAT,
    combustion_temp FLOAT,
    flue_gas_temp FLOAT,
    boiler_efficiency FLOAT,

    -- Steam turbine sensors
    st_power FLOAT,
    condenser_pressure FLOAT,

    -- Plant totals
    total_power FLOAT,
    total_thermal FLOAT
);

-- Convert to TimescaleDB hypertable for time-series optimization
SELECT create_hypertable('sensor_data', 'time', if_not_exists => TRUE);

-- Index for efficient per-simulation queries
CREATE INDEX IF NOT EXISTS idx_sensor_data_sim_id ON sensor_data (simulation_id, time DESC);

-- ============================================================
-- Events table
-- ============================================================
CREATE TABLE IF NOT EXISTS events (
    id SERIAL PRIMARY KEY,
    simulation_id UUID NOT NULL REFERENCES simulations(id),
    event_type VARCHAR(50) NOT NULL,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    severity VARCHAR(20) DEFAULT 'info',
    message TEXT,
    data JSONB
);

CREATE INDEX IF NOT EXISTS idx_events_sim_id ON events (simulation_id, timestamp DESC);

-- ============================================================
-- Scenarios table
-- ============================================================
CREATE TABLE IF NOT EXISTS scenarios (
    id VARCHAR(100) PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    initial_conditions JSONB,
    plant_type VARCHAR(50),
    difficulty VARCHAR(20) DEFAULT 'normal',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- Fermentation sensor data (time-series)
-- ============================================================
CREATE TABLE IF NOT EXISTS fermentation_sensor_data (
    id SERIAL,
    time TIMESTAMPTZ NOT NULL,
    simulation_id UUID NOT NULL,
    simulation_time FLOAT NOT NULL,
    vessel VARCHAR(50) NOT NULL,

    -- Fermentor sensors
    biomass FLOAT,
    substrate FLOAT,
    ph FLOAT,
    dissolved_oxygen FLOAT,
    temperature FLOAT,
    volume FLOAT,
    rpm FLOAT,
    aeration_vvm FLOAT,
    jacket_temp FLOAT,

    -- Sensor readings (with noise)
    sensor_ph FLOAT,
    sensor_do FLOAT,
    sensor_temp FLOAT,
    sensor_pressure FLOAT,

    -- Dosing
    valve_acid BOOLEAN,
    valve_base BOOLEAN,
    total_acid_added FLOAT,
    total_base_added FLOAT,

    -- Anomaly detection
    anomaly_detected BOOLEAN DEFAULT FALSE,
    anomaly_severity VARCHAR(20)
);

SELECT create_hypertable('fermentation_sensor_data', 'time', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_ferm_sensor_sim_id
    ON fermentation_sensor_data (simulation_id, time DESC);
CREATE INDEX IF NOT EXISTS idx_ferm_sensor_vessel
    ON fermentation_sensor_data (vessel, time DESC);

-- ============================================================
-- Compression & retention policies
-- ============================================================

-- Compress sensor_data older than 7 days
ALTER TABLE sensor_data SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'simulation_id'
);
SELECT add_compression_policy('sensor_data', INTERVAL '7 days', if_not_exists => TRUE);

-- Compress fermentation_sensor_data older than 7 days
ALTER TABLE fermentation_sensor_data SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'simulation_id,vessel'
);
SELECT add_compression_policy('fermentation_sensor_data', INTERVAL '7 days', if_not_exists => TRUE);

-- Retention: drop data older than 90 days
SELECT add_retention_policy('sensor_data', INTERVAL '90 days', if_not_exists => TRUE);
SELECT add_retention_policy('fermentation_sensor_data', INTERVAL '90 days', if_not_exists => TRUE);

-- ============================================================
-- Seed default scenarios
-- ============================================================
INSERT INTO scenarios (id, name, description, plant_type, difficulty, initial_conditions)
VALUES
    ('biogas_normal', 'Biogas Normal Operation', 'Standard biogas engine CHP operation at 80% load', 'biogas_engine', 'easy',
     '{"load_percent": 80, "feedstock": "mixed_waste", "temperature": 37}'),
    ('biogas_overload', 'Biogas Overload', 'Digester overloading scenario — VFA spike and pH drop', 'biogas_engine', 'hard',
     '{"load_percent": 100, "feedstock": "food_waste", "vfa_spike": true}'),
    ('biomass_startup', 'Biomass Boiler Startup', 'Cold start of biomass boiler from ambient temperature', 'biomass_boiler', 'normal',
     '{"load_percent": 0, "target_load": 80, "startup": true}'),
    ('combined_chp', 'Combined CHP Operation', 'Both biogas engine and biomass boiler in CHP mode', 'combined', 'normal',
     '{"biogas_load": 80, "biomass_load": 70, "feedstock": "mixed_waste"}')
ON CONFLICT (id) DO NOTHING;
