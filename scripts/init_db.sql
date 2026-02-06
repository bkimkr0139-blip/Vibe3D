-- BIO Database Initialization
-- Run after PostgreSQL + TimescaleDB container starts

-- Enable TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Create hypertable for sensor data (time-series optimization)
-- Note: Tables are created by SQLAlchemy (alembic migrate), this converts to hypertable
-- SELECT create_hypertable('sensor_data', 'time', if_not_exists => TRUE);

-- Compression policy (compress data older than 7 days)
-- ALTER TABLE sensor_data SET (
--     timescaledb.compress,
--     timescaledb.compress_segmentby = 'simulation_id'
-- );
-- SELECT add_compression_policy('sensor_data', INTERVAL '7 days');

-- Retention policy (drop data older than 90 days)
-- SELECT add_retention_policy('sensor_data', INTERVAL '90 days');
