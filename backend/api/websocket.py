"""
WebSocket handler for real-time tip event streaming.
Clients subscribe to receive live updates as tips are processed.
"""
import json
from fastapi import WebSocket, WebSocketDisconnect
from loguru import logger

from backend.core.event_bus import event_bus, Events


class ConnectionManager:
    """Manages active WebSocket connections."""

    def __init__(self):
        self._connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.append(ws)
        logger.info(f"WebSocket connected. Total: {len(self._connections)}")

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self._connections:
            self._connections.remove(ws)
        logger.info(f"WebSocket disconnected. Total: {len(self._connections)}")

    async def broadcast(self, event_type: str, data: dict) -> None:
        message = json.dumps({"event": event_type, "data": data})
        dead = []
        for ws in self._connections:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()


def _make_handler(event_type: str):
    async def handler(data):
        await manager.broadcast(event_type, data or {})
    return handler


def register_event_handlers() -> None:
    """Wire EventBus events to WebSocket broadcasts."""
    broadcast_events = [
        Events.SWARM_STARTED,
        Events.EMOTION_SCORED,
        Events.MILESTONE_REACHED,
        Events.TIP_DECIDED,
        Events.TIP_SENT,
        Events.TIP_CONFIRMED,
        Events.TIP_FAILED,
        Events.SWARM_COMPLETED,
    ]
    for event in broadcast_events:
        event_bus.subscribe(event, _make_handler(event))

    logger.info("WebSocket event handlers registered")


async def websocket_endpoint(ws: WebSocket) -> None:
    await manager.connect(ws)
    try:
        while True:
            # Keep connection alive; client can send ping messages
            data = await ws.receive_text()
            if data == "ping":
                await ws.send_text(json.dumps({"event": "pong"}))
    except WebSocketDisconnect:
        manager.disconnect(ws)
