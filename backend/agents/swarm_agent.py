"""
Swarm Agent
-----------
Subscribes to SWARM_TRIGGERED events and executes collective fan tip swarms.

Pipeline:
  1. Receive SWARM_TRIGGERED event
  2. Find all participants in the swarm (via SwarmPool / DB)
  3. Use Claude to generate an exciting swarm release announcement
  4. Execute ALL participant tips simultaneously via asyncio.gather()
  5. Broadcast swarm completion to all WebSocket clients
     → "SWARM RELEASED: 47 fans tipped $94 simultaneously"

System prompt: 'You are announcing a fan tip swarm completing.
               Generate an exciting 1-sentence announcement.'

All logs prefixed [SWARM AGENT].
"""
from __future__ import annotations

import json
from typing import Any

import anthropic
from loguru import logger
from sqlalchemy import select

from backend.config import config
from backend.core.event_bus import event_bus, EventType
from backend.core.swarm_pool import swarm_pool
from backend.core.wallet import WalletFactory
from backend.data.database import AsyncSessionLocal
from backend.data.models import SwarmGoalORM, SwarmParticipantORM, SwarmStatus


SYSTEM_PROMPT = (
    "You are announcing a fan tip swarm completing. "
    "Generate an exciting 1-sentence announcement."
)


class SwarmAgent:
    """
    Listens for SWARM_TRIGGERED events, finds participants,
    generates a Claude announcement, releases all tips in parallel,
    and broadcasts completion.
    """

    def __init__(self) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=config.anthropic_api_key)
        self._wallet = WalletFactory.create()

    # ------------------------------------------------------------------
    # Subscription
    # ------------------------------------------------------------------

    def subscribe(self) -> None:
        event_bus.subscribe(EventType.SWARM_TRIGGERED, self._handle_swarm_triggered)
        logger.info("[SWARM AGENT] Subscribed to SWARM_TRIGGERED events")

    # ------------------------------------------------------------------
    # Event handler
    # ------------------------------------------------------------------

    async def _handle_swarm_triggered(self, payload: dict[str, Any]) -> None:
        """
        Expected payload keys (published by MilestoneTipAgent / EmotionChatAgent):
          swarm_id  (optional — if absent, find any active triggered swarm)
          creator_id, source, ...
        """
        swarm_id: str | None = payload.get("swarm_id")
        creator_id: str = payload.get("creator_id", "")

        logger.info(
            f"[SWARM AGENT] SWARM_TRIGGERED received — "
            f"swarm_id={swarm_id or 'auto'} creator={creator_id}"
        )

        async with AsyncSessionLocal() as db:
            # If no explicit swarm_id, look up a triggered swarm for this creator
            if not swarm_id:
                stmt = select(SwarmGoalORM).where(
                    SwarmGoalORM.status == SwarmStatus.TRIGGERED.value,
                    SwarmGoalORM.creator_id == creator_id,
                )
                row = await db.execute(stmt)
                goal = row.scalar_one_or_none()
                if not goal:
                    logger.warning(
                        f"[SWARM AGENT] No triggered swarm found for creator={creator_id}"
                    )
                    return
                swarm_id = goal.swarm_id
            else:
                row = await db.execute(
                    select(SwarmGoalORM).where(SwarmGoalORM.swarm_id == swarm_id)
                )
                goal = row.scalar_one_or_none()
                if not goal:
                    logger.warning(f"[SWARM AGENT] Swarm {swarm_id} not found in DB")
                    return

            # Fetch participants for announcement metadata
            parts_row = await db.execute(
                select(SwarmParticipantORM).where(
                    SwarmParticipantORM.swarm_id == swarm_id
                )
            )
            participants = parts_row.scalars().all()

            participant_count = len(participants)
            total_amount = sum(p.committed_amount_usd for p in participants)

            logger.info(
                f"[SWARM AGENT] Swarm {swarm_id}: "
                f"{participant_count} participants, ${total_amount:.2f} total"
            )

            # ── Generate Claude announcement ──────────────────────────
            announcement = await self._generate_announcement(
                goal_description=goal.goal_description,
                participant_count=participant_count,
                total_amount=total_amount,
                creator_id=goal.creator_id,
            )

            # ── Release all tips simultaneously ───────────────────────
            result = await swarm_pool.release_swarm(
                db=db,
                swarm_id=swarm_id,
                wallet=self._wallet,
                token=config.default_token,
            )

        if not result.get("ok"):
            logger.error(
                f"[SWARM AGENT] release_swarm failed: {result.get('reason')}"
            )
            return

        successful = result["successful_tips"]
        total_sent = result["total_sent"]

        # ── Broadcast completion ──────────────────────────────────────
        broadcast_msg = (
            f"SWARM RELEASED: {successful} fans tipped "
            f"${total_sent:.2f} simultaneously"
        )

        logger.info(f"[SWARM AGENT] {broadcast_msg}")
        logger.info(f"[SWARM AGENT] Announcement: {announcement}")

        await event_bus.publish(EventType.AGENT_DECISION, {
            "agent": "SwarmAgent",
            "event": "SWARM_RELEASED",
            "swarm_id": swarm_id,
            "creator_id": goal.creator_id,
            "participant_count": successful,
            "total_sent": total_sent,
            "announcement": announcement,
            "broadcast": broadcast_msg,
            "results": result.get("results", []),
        })

    # ------------------------------------------------------------------
    # Claude announcement
    # ------------------------------------------------------------------

    async def _generate_announcement(
        self,
        goal_description: str,
        participant_count: int,
        total_amount: float,
        creator_id: str,
    ) -> str:
        user_message = json.dumps({
            "goal_description": goal_description,
            "participant_count": participant_count,
            "total_amount_usd": round(total_amount, 2),
            "creator_id": creator_id,
        })

        if config.effective_mock:
            from backend.core.mock_claude import swarm_announcement
            return swarm_announcement(swarm_id=creator_id)

        logger.debug(f"[SWARM AGENT] Asking Groq for announcement — {user_message}")

        from backend.core.groq_client import chat as groq_chat
        announcement = await groq_chat(system=SYSTEM_PROMPT, user=user_message, max_tokens=128)
        return announcement or f"SWARM RELEASED: {participant_count} fans tipped ${total_amount:.2f} simultaneously!"

    # ------------------------------------------------------------------
    # Demo helper
    # ------------------------------------------------------------------

    async def seed_and_trigger_demo(self) -> None:
        """
        Pre-built demo: seed a swarm → trigger it → release.
        'Goal: Tip $100 if creator wins the debate' with 20 mock participants.
        """
        async with AsyncSessionLocal() as db:
            goal = await swarm_pool.seed_demo_swarm(db)
            logger.info(
                f"[SWARM AGENT] Demo swarm seeded — swarm_id={goal.swarm_id}"
            )
            triggered = await swarm_pool.check_trigger(db, "DEBATE_WIN")
            logger.info(
                f"[SWARM AGENT] Demo trigger check — {len(triggered)} swarms triggered"
            )

        if triggered:
            await event_bus.publish(EventType.SWARM_TRIGGERED, {
                "source": "SwarmAgent.demo",
                "swarm_id": goal.swarm_id,
                "creator_id": goal.creator_id,
            })


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

swarm_agent = SwarmAgent()
