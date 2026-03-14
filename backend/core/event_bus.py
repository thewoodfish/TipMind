import asyncio
from collections import defaultdict
from typing import Any, Callable, Coroutine
from loguru import logger


class EventBus:
    """Simple async pub/sub event bus for inter-agent communication."""

    def __init__(self):
        self._subscribers: dict[str, list[Callable]] = defaultdict(list)

    def subscribe(self, event: str, handler: Callable[..., Coroutine]) -> None:
        self._subscribers[event].append(handler)
        logger.debug(f"Subscribed to event: {event}")

    def unsubscribe(self, event: str, handler: Callable) -> None:
        self._subscribers[event] = [
            h for h in self._subscribers[event] if h != handler
        ]

    async def publish(self, event: str, data: Any = None) -> None:
        logger.debug(f"Publishing event: {event}")
        handlers = self._subscribers.get(event, [])
        if handlers:
            await asyncio.gather(*[h(data) for h in handlers], return_exceptions=True)


# Global event bus instance
event_bus = EventBus()


# Event name constants
class Events:
    VIDEO_ANALYZED = "video.analyzed"
    EMOTION_SCORED = "emotion.scored"
    MILESTONE_REACHED = "milestone.reached"
    TIP_DECIDED = "tip.decided"
    TIP_SENT = "tip.sent"
    TIP_CONFIRMED = "tip.confirmed"
    TIP_FAILED = "tip.failed"
    SWARM_STARTED = "swarm.started"
    SWARM_COMPLETED = "swarm.completed"
