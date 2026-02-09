"""Fermentation WebSocket route — real-time sensor streaming (~1 Hz)."""

import asyncio
import json
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.services.fermentation_manager import FermentationManager

router = APIRouter()
manager = FermentationManager()


@router.websocket("/{simulation_id}")
async def fermentation_stream(websocket: WebSocket, simulation_id: UUID):
    """Stream real-time fermentation sensor data at ~1 Hz."""
    await websocket.accept()

    try:
        while True:
            state = await manager.get_state(simulation_id)
            if state is None:
                await websocket.send_json({"error": "simulation not found"})
                break

            status = state.get("status", "stopped")
            if status == "stopped":
                await websocket.send_json({"event": "stopped"})
                break

            # Send current sensor readings and key state
            payload = {
                "simulation_time": state.get("simulation_time", 0),
                "status": status,
                "sensors": state.get("sensors", {}),
                "fermentors": {},
                "dosing": state.get("dosing", {}),
            }

            # Include compact fermentor state
            for name, ferm in state.get("fermentors", {}).items():
                payload["fermentors"][name] = {
                    "pH": ferm.get("pH"),
                    "DO": ferm.get("DO"),
                    "temperature": ferm.get("temperature"),
                    "X": ferm.get("X"),
                    "S": ferm.get("S"),
                    "rpm": ferm.get("rpm"),
                    "volume_L": ferm.get("volume_L"),
                }

            await websocket.send_json(payload)
            await asyncio.sleep(1.0)

    except WebSocketDisconnect:
        pass
    except Exception:
        await websocket.close()
