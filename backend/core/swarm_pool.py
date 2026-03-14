"""
SwarmPool — manages collective tip swarm goals in memory and database.

A "swarm" is a group of fans who pledge to tip a creator simultaneously
when a trigger event fires (e.g. "Tip $100 if creator wins the debate").

Public API:
  create_swarm(...)     → SwarmGoalORM
  join_swarm(...)       → dict confirmation
  check_trigger(event)  → list[SwarmGoalORM] that fired
  release_swarm(id)     → executes all pooled tips simultaneously
  get_active_swarms()   → list[SwarmGoalORM]
  seed_demo_swarm()     → pre-built demo with 20 mock participants

Also re-exports SwarmTask / task runner used by the orchestrator.
All logs prefixed [SWARM POOL].
"""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from loguru import logger
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.data.models import (
    SwarmGoalORM,
    SwarmParticipantORM,
    SwarmStatus,
    TipTransactionORM,
)


# ---------------------------------------------------------------------------
# SwarmTask — internal concurrency token used by the Orchestrator
# ---------------------------------------------------------------------------

@dataclass
class SwarmTask:
    task_id: str
    video_id: str
    payload: dict[str, Any]
    result: dict[str, Any] | None = None
    status: str = "pending"   # pending | running | done | failed
    error: str | None = None


# ---------------------------------------------------------------------------
# SwarmPool
# ---------------------------------------------------------------------------

SWARM_TTL_HOURS = 24


class SwarmPool:
    """
    Manages active swarm goals (collective tip pools) and the task runner
    semaphore used by the Orchestrator for concurrency control.
    """

    def __init__(self, max_concurrent: int = 5) -> None:
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._tasks: dict[str, SwarmTask] = {}

    # ------------------------------------------------------------------
    # Orchestrator task runner (unchanged interface)
    # ------------------------------------------------------------------

    def register(self, task: SwarmTask) -> None:
        self._tasks[task.task_id] = task
        logger.debug(f"[SWARM POOL] Registered task: {task.task_id}")

    def get_task(self, task_id: str) -> SwarmTask | None:
        return self._tasks.get(task_id)

    def list_tasks(self) -> list[SwarmTask]:
        return list(self._tasks.values())

    async def run(self, task: SwarmTask, coro) -> SwarmTask:
        """Run a coroutine under the semaphore; update task status."""
        self.register(task)
        async with self._semaphore:
            task.status = "running"
            try:
                task.result = await coro
                task.status = "done"
                logger.info(f"[SWARM POOL] Task {task.task_id} done")
            except Exception as exc:
                task.status = "failed"
                task.error = str(exc)
                logger.error(f"[SWARM POOL] Task {task.task_id} failed: {exc}")
        return task

    # ------------------------------------------------------------------
    # Swarm goal management
    # ------------------------------------------------------------------

    async def create_swarm(
        self,
        db: AsyncSession,
        creator_id: str,
        goal_description: str,
        trigger_event: str,
        target_amount: float,
    ) -> SwarmGoalORM:
        """Create a new swarm goal and persist it."""
        swarm_id = str(uuid.uuid4())
        goal = SwarmGoalORM(
            swarm_id=swarm_id,
            creator_id=creator_id,
            goal_description=goal_description,
            trigger_event=trigger_event,
            target_amount_usd=target_amount,
            current_amount_usd=0.0,
            participant_count=0,
            status=SwarmStatus.ACTIVE.value,
        )
        db.add(goal)
        await db.commit()
        await db.refresh(goal)
        logger.info(
            f"[SWARM POOL] Created swarm {swarm_id} — "
            f"'{goal_description}' target=${target_amount}"
        )
        return goal

    async def join_swarm(
        self,
        db: AsyncSession,
        swarm_id: str,
        user_id: str,
        pledged_amount: float,
    ) -> dict:
        """Add a participant to an active swarm."""
        goal = await self._get_active_goal(db, swarm_id)
        if not goal:
            return {"ok": False, "reason": "Swarm not found or not active"}

        if await self._is_expired(goal):
            await self._expire_swarm(db, goal)
            return {"ok": False, "reason": "Swarm has expired"}

        db.add(SwarmParticipantORM(
            swarm_id=swarm_id,
            user_id=user_id,
            committed_amount_usd=pledged_amount,
        ))
        await db.execute(
            update(SwarmGoalORM)
            .where(SwarmGoalORM.swarm_id == swarm_id)
            .values(
                current_amount_usd=SwarmGoalORM.current_amount_usd + pledged_amount,
                participant_count=SwarmGoalORM.participant_count + 1,
            )
        )
        await db.commit()

        logger.info(
            f"[SWARM POOL] user={user_id} joined swarm={swarm_id} "
            f"pledging ${pledged_amount:.2f}"
        )
        return {
            "ok": True,
            "swarm_id": swarm_id,
            "user_id": user_id,
            "pledged_amount": pledged_amount,
        }

    async def check_trigger(self, db: AsyncSession, event: str) -> list[SwarmGoalORM]:
        """Return active swarms whose trigger_event matches and mark them TRIGGERED."""
        stmt = select(SwarmGoalORM).where(
            SwarmGoalORM.trigger_event == event,
            SwarmGoalORM.status == SwarmStatus.ACTIVE.value,
        )
        rows = await db.execute(stmt)
        goals = rows.scalars().all()

        triggered = []
        for goal in goals:
            if await self._is_expired(goal):
                await self._expire_swarm(db, goal)
                continue
            await db.execute(
                update(SwarmGoalORM)
                .where(SwarmGoalORM.swarm_id == goal.swarm_id)
                .values(status=SwarmStatus.TRIGGERED.value)
            )
            triggered.append(goal)
            logger.info(f"[SWARM POOL] Swarm {goal.swarm_id} triggered by event '{event}'")

        if triggered:
            await db.commit()
        return triggered

    async def release_swarm(
        self,
        db: AsyncSession,
        swarm_id: str,
        wallet,
        token: str = "USDT",
    ) -> dict:
        """
        Execute all participant tips simultaneously via asyncio.gather().
        Returns summary dict.
        """
        stmt = select(SwarmParticipantORM).where(
            SwarmParticipantORM.swarm_id == swarm_id
        )
        rows = await db.execute(stmt)
        participants = rows.scalars().all()

        goal_stmt = select(SwarmGoalORM).where(SwarmGoalORM.swarm_id == swarm_id)
        goal_row = await db.execute(goal_stmt)
        goal = goal_row.scalar_one_or_none()

        if not goal or not participants:
            return {"ok": False, "reason": "Swarm or participants not found"}

        logger.info(
            f"[SWARM POOL] Releasing swarm {swarm_id} — "
            f"{len(participants)} participants, total ${goal.current_amount_usd:.2f}"
        )

        async def _tip_one(p: SwarmParticipantORM):
            try:
                tx = await wallet.send_tip(
                    to_address=goal.creator_id,
                    amount=p.committed_amount_usd,
                    token=token,
                )
                db.add(TipTransactionORM(
                    tx_hash=tx.tx_hash,
                    from_wallet=p.user_id,
                    to_wallet=goal.creator_id,
                    amount=p.committed_amount_usd,
                    token=token,
                    creator_id=goal.creator_id,
                    trigger_type="SWARM_RELEASE",
                    status=tx.status,
                ))
                return {"user_id": p.user_id, "amount": p.committed_amount_usd, "tx_hash": tx.tx_hash}
            except Exception as exc:
                logger.error(f"[SWARM POOL] Tip failed for {p.user_id}: {exc}")
                return {"user_id": p.user_id, "error": str(exc)}

        results = await asyncio.gather(*[_tip_one(p) for p in participants])

        await db.execute(
            update(SwarmGoalORM)
            .where(SwarmGoalORM.swarm_id == swarm_id)
            .values(status=SwarmStatus.COMPLETED.value)
        )
        await db.commit()

        successful = [r for r in results if "tx_hash" in r]
        total_sent = sum(r["amount"] for r in successful)

        logger.info(
            f"[SWARM POOL] Swarm {swarm_id} RELEASED — "
            f"{len(successful)}/{len(participants)} tips sent, ${total_sent:.2f} total"
        )
        return {
            "ok": True,
            "swarm_id": swarm_id,
            "participant_count": len(participants),
            "successful_tips": len(successful),
            "total_sent": total_sent,
            "results": results,
        }

    async def get_active_swarms(self, db: AsyncSession) -> list[SwarmGoalORM]:
        """Return all currently active (non-expired) swarm goals."""
        stmt = select(SwarmGoalORM).where(
            SwarmGoalORM.status == SwarmStatus.ACTIVE.value
        )
        rows = await db.execute(stmt)
        goals = rows.scalars().all()
        # Lazily expire
        active = []
        for g in goals:
            if await self._is_expired(g):
                await self._expire_swarm(db, g)
            else:
                active.append(g)
        return active

    async def seed_demo_swarm(self, db: AsyncSession) -> SwarmGoalORM:
        """
        Pre-built demo swarm: 'Tip $100 if creator wins the debate'
        with 20 mock participants contributing $5 each.
        """
        goal = await self.create_swarm(
            db=db,
            creator_id="demo_creator_001",
            goal_description="Tip $100 if creator wins the debate",
            trigger_event="DEBATE_WIN",
            target_amount=100.0,
        )
        for i in range(20):
            await self.join_swarm(
                db=db,
                swarm_id=goal.swarm_id,
                user_id=f"demo_fan_{i+1:02d}",
                pledged_amount=5.0,
            )
        logger.info(
            f"[SWARM POOL] Demo swarm seeded — swarm_id={goal.swarm_id} "
            "| 20 participants × $5 = $100 target"
        )
        return goal

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_active_goal(self, db: AsyncSession, swarm_id: str) -> SwarmGoalORM | None:
        stmt = select(SwarmGoalORM).where(
            SwarmGoalORM.swarm_id == swarm_id,
            SwarmGoalORM.status == SwarmStatus.ACTIVE.value,
        )
        row = await db.execute(stmt)
        return row.scalar_one_or_none()

    @staticmethod
    async def _is_expired(goal: SwarmGoalORM) -> bool:
        if goal.created_at is None:
            return False
        return datetime.utcnow() > goal.created_at + timedelta(hours=SWARM_TTL_HOURS)

    @staticmethod
    async def _expire_swarm(db: AsyncSession, goal: SwarmGoalORM) -> None:
        await db.execute(
            update(SwarmGoalORM)
            .where(SwarmGoalORM.swarm_id == goal.swarm_id)
            .values(status=SwarmStatus.EXPIRED.value)
        )
        await db.commit()
        logger.info(f"[SWARM POOL] Swarm {goal.swarm_id} expired")


# ---------------------------------------------------------------------------
# Singletons
# ---------------------------------------------------------------------------

swarm_pool = SwarmPool(max_concurrent=5)
