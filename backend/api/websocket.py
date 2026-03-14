"""
WebSocket handler for real-time tip event streaming.
Clients connect and receive every event the EventBus broadcasts.
"""
import json
from fastapi import WebSocket, WebSocketDisconnect
from loguru import logger

from backend.core.event_bus import event_bus, EventType


async def websocket_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    logger.info("[EVENT BUS] WS client connected")

    # Register this client's send callable directly with the event bus
    send_fn = ws.send_text
    event_bus.add_ws_client(send_fn)

    try:
        while True:
            data = await ws.receive_text()
            if data == "ping":
                await ws.send_text(json.dumps({"event": "pong"}))
    except WebSocketDisconnect:
        event_bus.remove_ws_client(send_fn)
        logger.info("[EVENT BUS] WS client disconnected")


def register_event_handlers() -> None:
    """
    Subscribe any app-level handlers to EventBus events.
    WS broadcast is handled automatically by event_bus.publish() —
    no extra wiring needed here.
    """
    logger.info("[EVENT BUS] Event handlers registered")
