"""WebSocket endpoint for real-time sensor data streaming."""

from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


@router.websocket("/{simulation_id}")
async def simulation_stream(websocket: WebSocket, simulation_id: UUID):
    """Stream real-time sensor data for a simulation.

    Sends JSON frames at ~1Hz containing:
    - Digester: temperature, pH, biogas_flow, methane_content
    - Engine/Boiler: rpm, power_output, exhaust_temp, fuel_flow
    - Steam cycle: steam_pressure, steam_temp, feedwater_temp
    - Plant: total_power, efficiency, emissions
    """
    await websocket.accept()
    try:
        while True:
            # TODO: Integrate with SimulationManager to stream real data
            await websocket.receive_text()  # heartbeat
    except WebSocketDisconnect:
        pass
