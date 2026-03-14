"""
WebSocket handler for real-time TipMind event streaming.

Endpoint: ws://localhost:8000/ws/feed

Every event published on the EventBus is broadcast to all connected clients
in the format:
  {
    "type":      "<EVENT_TYPE>",
    "agent":     "<agent name or null>",
    "message":   "<human-readable summary>",
    "amount":    <float or null>,
    "token":     "<USDT|XAUT|BTC or null>",
    "timestamp": "<ISO-8601>",
    "metadata":  { ...full event payload... }
  }

Clients may send "ping" and receive a "pong" heartbeat.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from loguru import logger

from backend.core.event_bus import event_bus


def _format_event(raw_event: str) -> str:
    """
    Transform the EventBus raw JSON `{"event": ..., "data": ...}`
    into the public WS feed format.
    """
    try:
        envelope = json.loads(raw_event)
    except Exception:
        return raw_event

    event_type: str = envelope.get("event", "UNKNOWN")
    data: dict[str, Any] = envelope.get("data") or {}

    # Extract common fields
    agent   = data.get("agent") or data.get("source") or _infer_agent(event_type)
    amount  = _extract_float(data, ("amount", "tip_amount", "pledged_amount", "total_sent"))
    token   = data.get("token") or data.get("preferred_token")
    message = _build_message(event_type, data, amount, token)

    formatted = {
        "type":      event_type,
        "agent":     agent,
        "message":   message,
        "amount":    amount,
        "token":     token,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "metadata":  data,
    }
    return json.dumps(formatted, default=str)


def _extract_float(data: dict, keys: tuple[str, ...]) -> float | None:
    for k in keys:
        v = data.get(k)
        if v is not None:
            try:
                return round(float(v), 4)
            except (TypeError, ValueError):
                pass
    return None


def _infer_agent(event_type: str) -> str:
    mapping = {
        "WATCH_TIME_UPDATE":  "WatchTimeTipAgent",
        "CHAT_MESSAGE":       "EmotionChatAgent",
        "MILESTONE_REACHED":  "MilestoneTipAgent",
        "SWARM_TRIGGERED":    "SwarmAgent",
        "TIP_EXECUTED":       "Wallet",
        "AGENT_DECISION":     "Orchestrator",
    }
    return mapping.get(event_type, "System")


def _build_message(
    event_type: str,
    data: dict[str, Any],
    amount: float | None,
    token: str | None,
) -> str:
    creator = data.get("creator_id") or data.get("creator_name") or "creator"
    tok = token or "USDT"

    if event_type == "AGENT_DECISION":
        ev = data.get("event", "")
        if ev == "SWARM_RELEASED":
            n = data.get("participant_count", "?")
            return data.get("broadcast") or f"SWARM RELEASED: {n} fans tipped ${amount or 0:.2f} simultaneously"
        if amount:
            return f"{data.get('agent', 'Agent')} tipped {creator} ${amount:.2f} {tok}"
        return data.get("announcement") or f"Agent decision for {creator}"

    if event_type == "TIP_EXECUTED":
        if amount:
            return f"Tip of ${amount:.2f} {tok} sent to {creator}"
        return f"Tip executed for {creator}"

    if event_type == "SWARM_TRIGGERED":
        return f"Fan swarm triggered for {creator}"

    if event_type == "MILESTONE_REACHED":
        mtype = data.get("milestone_type", "milestone")
        return f"Milestone reached: {mtype} for {creator}"

    if event_type == "CHAT_MESSAGE":
        msg = data.get("message", "")
        return f"Chat: {msg[:60]}"

    if event_type == "WATCH_TIME_UPDATE":
        pct = data.get("watch_percentage", 0)
        return f"Watch event: {pct}% watched for {creator}"

    return f"Event: {event_type}"


async def ws_feed_endpoint(ws: WebSocket) -> None:
    """
    Main WebSocket endpoint at /ws/feed.

    Wraps each EventBus broadcast in the standard feed format before
    forwarding to the client.
    """
    await ws.accept()
    logger.info("[WS FEED] Client connected")

    async def formatted_send(raw_message: str) -> None:
        await ws.send_text(_format_event(raw_message))

    event_bus.add_ws_client(formatted_send)

    try:
        while True:
            data = await ws.receive_text()
            if data.strip() == "ping":
                await ws.send_text(json.dumps({
                    "type": "PONG",
                    "agent": None,
                    "message": "pong",
                    "amount": None,
                    "token": None,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "metadata": {},
                }))
    except WebSocketDisconnect:
        event_bus.remove_ws_client(formatted_send)
        logger.info("[WS FEED] Client disconnected")


# ---------------------------------------------------------------------------
# Legacy endpoint kept for backwards compatibility (/ws)
# ---------------------------------------------------------------------------

async def websocket_endpoint(ws: WebSocket) -> None:
    """Legacy /ws endpoint — redirects to the same feed logic."""
    await ws_feed_endpoint(ws)


def register_event_handlers() -> None:
    """
    App-level event handler registration.
    WS broadcast is handled automatically by event_bus.publish().
    """
    logger.info("[WS FEED] Event handlers registered")
