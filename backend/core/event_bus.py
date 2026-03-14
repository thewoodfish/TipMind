"""
TipMind Event Bus — the nervous system connecting all agents together.

- Async pub/sub backed by asyncio queues (one queue per subscriber)
- Supports multiple subscribers per event type
- Broadcasts all events to connected WebSocket clients as JSON
- Singleton: import `event_bus` anywhere in the app
- All activity logged with [EVENT BUS] prefix via loguru
"""
from __future__ import annotations

import asyncio
import enum
import json
from collections import defaultdict
from typing import Any, Callable, Coroutine

from loguru import logger


# ---------------------------------------------------------------------------
# Event type enum
# ---------------------------------------------------------------------------

class EventType(str, enum.Enum):
    WATCH_TIME_UPDATE  = "WATCH_TIME_UPDATE"
    CHAT_MESSAGE       = "CHAT_MESSAGE"
    MILESTONE_REACHED  = "MILESTONE_REACHED"
    SWARM_TRIGGERED    = "SWARM_TRIGGERED"
    TIP_EXECUTED       = "TIP_EXECUTED"
    AGENT_DECISION     = "AGENT_DECISION"


# ---------------------------------------------------------------------------
# Event Bus
# ---------------------------------------------------------------------------

class EventBus:
    """
    Async pub/sub event bus backed by asyncio queues.

    Each subscriber gets its own queue so slow handlers never block others.
    WebSocket clients are tracked separately and receive a JSON broadcast
    on every published event.
    """

    def __init__(self) -> None:
        # event_type -> list of (handler, queue) pairs
        self._subscribers: dict[str, list[tuple[Callable, asyncio.Queue]]] = defaultdict(list)
        # Connected WebSocket send-callables (async ws.send_text)
        self._ws_clients: list[Callable[[str], Coroutine]] = []
        self._worker_tasks: list[asyncio.Task] = []

    # ------------------------------------------------------------------
    # Subscriber management
    # ------------------------------------------------------------------

    def subscribe(self, event_type: EventType | str, handler: Callable[..., Coroutine]) -> asyncio.Queue:
        """
        Register an async handler for an event type.

        A dedicated queue is created for this handler; a background worker
        drains it so each subscriber is decoupled from the publish call.

        Returns the queue (useful for testing).
        """
        key = event_type.value if isinstance(event_type, EventType) else event_type
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers[key].append((handler, queue))

        task = asyncio.ensure_future(self._worker(handler, queue, key))
        self._worker_tasks.append(task)

        logger.debug(f"[EVENT BUS] Subscribed handler '{handler.__name__}' to '{key}'")
        return queue

    def unsubscribe(self, event_type: EventType | str, handler: Callable) -> None:
        """Remove a handler (and stop its worker queue)."""
        key = event_type.value if isinstance(event_type, EventType) else event_type
        self._subscribers[key] = [
            (h, q) for h, q in self._subscribers[key] if h != handler
        ]
        logger.debug(f"[EVENT BUS] Unsubscribed handler '{handler.__name__}' from '{key}'")

    # ------------------------------------------------------------------
    # WebSocket client management
    # ------------------------------------------------------------------

    def add_ws_client(self, send_fn: Callable[[str], Coroutine]) -> None:
        """Register a WebSocket send callable for broadcast."""
        self._ws_clients.append(send_fn)
        logger.debug(f"[EVENT BUS] WS client added. Total: {len(self._ws_clients)}")

    def remove_ws_client(self, send_fn: Callable[[str], Coroutine]) -> None:
        """Deregister a WebSocket send callable."""
        if send_fn in self._ws_clients:
            self._ws_clients.remove(send_fn)
        logger.debug(f"[EVENT BUS] WS client removed. Total: {len(self._ws_clients)}")

    # ------------------------------------------------------------------
    # Publishing
    # ------------------------------------------------------------------

    async def publish(self, event_type: EventType | str, payload: Any = None) -> None:
        """
        Publish an event to all subscribers and broadcast to WS clients.

        Enqueues payload for each subscriber's worker; does not wait for
        handlers to complete (fire-and-forget per subscriber).
        """
        key = event_type.value if isinstance(event_type, EventType) else event_type
        logger.info(f"[EVENT BUS] Publishing '{key}' | payload={payload}")

        # Enqueue for each subscriber's dedicated worker
        pairs = self._subscribers.get(key, [])
        for _, queue in pairs:
            await queue.put(payload)

        # Broadcast to all WebSocket clients
        await self.broadcast(key, payload)

    async def broadcast(self, event_type: str, payload: Any = None) -> None:
        """Send a JSON message to every connected WebSocket client."""
        if not self._ws_clients:
            return

        message = json.dumps({"event": event_type, "data": payload}, default=str)
        dead: list[Callable] = []

        for send_fn in self._ws_clients:
            try:
                await send_fn(message)
            except Exception as exc:
                logger.warning(f"[EVENT BUS] WS broadcast failed, removing client: {exc}")
                dead.append(send_fn)

        for send_fn in dead:
            self.remove_ws_client(send_fn)

    # ------------------------------------------------------------------
    # Internal worker
    # ------------------------------------------------------------------

    @staticmethod
    async def _worker(
        handler: Callable[..., Coroutine],
        queue: asyncio.Queue,
        event_key: str,
    ) -> None:
        """Drain a subscriber's queue and invoke its handler for each item."""
        while True:
            payload = await queue.get()
            try:
                await handler(payload)
            except Exception as exc:
                logger.error(
                    f"[EVENT BUS] Handler '{handler.__name__}' raised on '{event_key}': {exc}"
                )
            finally:
                queue.task_done()


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

event_bus = EventBus()
