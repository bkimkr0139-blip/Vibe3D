"""CRUD operations for database models."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Simulation, SensorData, Event


async def create_simulation(session: AsyncSession, **kwargs) -> Simulation:
    sim = Simulation(**kwargs)
    session.add(sim)
    await session.commit()
    await session.refresh(sim)
    return sim


async def get_simulation(session: AsyncSession, sim_id: UUID) -> Simulation | None:
    result = await session.execute(select(Simulation).where(Simulation.id == sim_id))
    return result.scalar_one_or_none()


async def insert_sensor_batch(session: AsyncSession, records: list[dict]):
    """Batch insert sensor data records."""
    objects = [SensorData(**r) for r in records]
    session.add_all(objects)
    await session.commit()


async def log_event(session: AsyncSession, simulation_id: UUID,
                    event_type: str, message: str, severity: str = "info"):
    event = Event(
        simulation_id=simulation_id,
        event_type=event_type,
        message=message,
        severity=severity,
    )
    session.add(event)
    await session.commit()
