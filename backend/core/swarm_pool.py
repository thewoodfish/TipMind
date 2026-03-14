import asyncio
from dataclasses import dataclass, field
from typing import Any
from loguru import logger


@dataclass
class SwarmTask:
    task_id: str
    video_id: str
    payload: dict[str, Any]
    result: dict[str, Any] | None = None
    status: str = "pending"  # pending | running | done | failed
    error: str | None = None


class SwarmPool:
    """
    Manages a pool of concurrent swarm tasks.
    Limits parallelism to avoid overwhelming the Anthropic API.
    """

    def __init__(self, max_concurrent: int = 5):
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._tasks: dict[str, SwarmTask] = {}

    def register(self, task: SwarmTask) -> None:
        self._tasks[task.task_id] = task
        logger.debug(f"Registered swarm task: {task.task_id}")

    def get(self, task_id: str) -> SwarmTask | None:
        return self._tasks.get(task_id)

    def list_tasks(self) -> list[SwarmTask]:
        return list(self._tasks.values())

    async def run(self, task: SwarmTask, coro) -> SwarmTask:
        """Run a coroutine under the semaphore and update task status."""
        self.register(task)
        async with self._semaphore:
            task.status = "running"
            try:
                task.result = await coro
                task.status = "done"
                logger.info(f"Swarm task {task.task_id} completed")
            except Exception as exc:
                task.status = "failed"
                task.error = str(exc)
                logger.error(f"Swarm task {task.task_id} failed: {exc}")
        return task


# Singleton pool
swarm_pool = SwarmPool(max_concurrent=5)
