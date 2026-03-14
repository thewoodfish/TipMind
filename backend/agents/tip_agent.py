"""
Watch-Time Tip Agent
--------------------
Subscribes to WATCH_TIME_UPDATE events and decides whether to tip a creator
based on how much of a video the user actually watched.

Pipeline:
  1. Rule-based pre-filter (avoids unnecessary API calls)
  2. Claude claude-sonnet-4-20250514 makes the final tip/amount decision
  3. Daily budget check
  4. Execute tip via WalletFactory
  5. Log TipDecision to database
  6. Publish AGENT_DECISION event

All logs prefixed [WATCH AGENT].
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

import anthropic
from loguru import logger
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import config
from backend.core.event_bus import event_bus, EventType
from backend.core.wallet import WalletFactory
from backend.data.models import (
    TipDecision,
    TipTransactionORM,
    AgentDecisionLogORM,
    WatchEvent,
)


# ---------------------------------------------------------------------------
# Pre-filter thresholds
# ---------------------------------------------------------------------------

class _Tier:
    SKIP_BELOW   = 20.0   # watch% — don't even call Claude
    SMALL_MIN    = 20.0
    SMALL_MAX    = 50.0
    SMALL_HINT   = 0.25   # hint passed to Claude
    MEDIUM_MIN   = 50.0
    MEDIUM_MAX   = 80.0
    MEDIUM_HINT  = 0.75
    FULL_MIN     = 80.0
    FULL_HINT    = 1.50


def _tip_hint(watch_pct: float) -> float | None:
    """Return a suggested tip amount for Claude, or None to skip."""
    if watch_pct < _Tier.SKIP_BELOW:
        return None
    if watch_pct < _Tier.SMALL_MAX:
        return _Tier.SMALL_HINT
    if watch_pct < _Tier.MEDIUM_MAX:
        return _Tier.MEDIUM_HINT
    return _Tier.FULL_HINT


# ---------------------------------------------------------------------------
# Watch-Time Tip Agent
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You are a fan tipping agent. Based on watch engagement, decide whether to tip "
    "and how much. Be generous for high engagement, conservative for low. "
    "Always return JSON."
)


class WatchTimeTipAgent:
    """
    Listens for WATCH_TIME_UPDATE events and executes micro-tips based on
    how long a user watched a video.
    """

    def __init__(self, db_session_factory) -> None:
        """
        Args:
            db_session_factory: async_sessionmaker — used to open DB sessions
                                 inside the event handler.
        """
        self._client = anthropic.AsyncAnthropic(api_key=config.anthropic_api_key)
        self._db_factory = db_session_factory
        self._wallet = WalletFactory.create()

    # ------------------------------------------------------------------
    # Event bus subscription
    # ------------------------------------------------------------------

    def subscribe(self) -> None:
        """Register this agent's handler with the event bus."""
        event_bus.subscribe(EventType.WATCH_TIME_UPDATE, self._handle_watch_event)
        logger.info("[WATCH AGENT] Subscribed to WATCH_TIME_UPDATE events")

    # ------------------------------------------------------------------
    # Event handler
    # ------------------------------------------------------------------

    async def _handle_watch_event(self, payload: dict[str, Any]) -> None:
        """
        Entry point called by the event bus for every WATCH_TIME_UPDATE.

        Expected payload keys (matches WatchEvent pydantic model):
          user_id, video_id, watch_seconds, total_duration, percentage_watched,
          creator_id, creator_name, user_max_per_video
        """
        try:
            event = WatchEvent(
                user_id=payload["user_id"],
                video_id=payload["video_id"],
                watch_seconds=payload["watch_seconds"],
                total_duration=payload["total_duration"],
                percentage_watched=payload["percentage_watched"],
            )
        except Exception as exc:
            logger.warning(f"[WATCH AGENT] Invalid payload: {exc}")
            return

        creator_id   = payload.get("creator_id", payload.get("video_id"))
        creator_name = payload.get("creator_name", "Creator")
        user_max     = float(payload.get("user_max_per_video", config.max_tip_per_video))
        watch_pct    = event.percentage_watched

        logger.info(
            f"[WATCH AGENT] user={event.user_id} video={event.video_id} "
            f"watched={watch_pct:.1f}%"
        )

        # ── Step 1: rule-based pre-filter ────────────────────────────
        hint = _tip_hint(watch_pct)
        if hint is None:
            logger.info(
                f"[WATCH AGENT] Skipping — watch {watch_pct:.1f}% < {_Tier.SKIP_BELOW}%"
            )
            return

        # ── Step 2: Claude decides ───────────────────────────────────
        async with self._db_factory() as db:
            already_tipped_today = await self._tipped_today(db, event.user_id)

        decision = await self._ask_claude(
            watch_percentage=watch_pct,
            video_duration=event.total_duration,
            creator_name=creator_name,
            user_max_per_video=user_max,
            already_tipped_today=already_tipped_today,
            hint=hint,
        )

        if not decision.get("should_tip"):
            logger.info(
                f"[WATCH AGENT] Claude declined tip — {decision.get('reasoning', '')}"
            )
            return

        amount = float(decision.get("amount", 0))
        if amount <= 0:
            return

        # ── Step 3: daily budget check ───────────────────────────────
        async with self._db_factory() as db:
            spent_today = await self._spent_today(db, event.user_id)

        if spent_today + amount > user_max:
            logger.info(
                f"[WATCH AGENT] Daily budget exhausted "
                f"(spent={spent_today:.2f}, max={user_max:.2f})"
            )
            return

        # ── Step 4: execute tip ──────────────────────────────────────
        try:
            tx = await self._wallet.send_tip(
                to_address=creator_id,
                amount=amount,
                token=config.default_token,
            )
            logger.info(
                f"[WATCH AGENT] Tip sent — {amount} {config.default_token} "
                f"→ {creator_id} | tx={tx.tx_hash}"
            )
        except Exception as exc:
            logger.error(f"[WATCH AGENT] Wallet error: {exc}")
            return

        # ── Step 5: persist to database ──────────────────────────────
        tip_decision_model = TipDecision(
            agent_type="WatchTimeTipAgent",
            trigger=EventType.WATCH_TIME_UPDATE.value,
            amount_usd=amount,
            token=config.default_token,
            creator_id=creator_id,
            reasoning=decision.get("reasoning", ""),
            confidence_score=float(decision.get("confidence", 0.0)),
        )

        async with self._db_factory() as db:
            db.add(TipTransactionORM(
                tx_hash=tx.tx_hash,
                from_wallet=await self._wallet.get_wallet_address(),
                to_wallet=creator_id,
                amount=amount,
                token=config.default_token,
                creator_id=creator_id,
                trigger_type="WATCH_TIME",
                status=tx.status,
            ))
            db.add(AgentDecisionLogORM(
                agent_type=tip_decision_model.agent_type,
                trigger=tip_decision_model.trigger,
                creator_id=creator_id,
                amount_usd=amount,
                reasoning=tip_decision_model.reasoning,
                confidence_score=tip_decision_model.confidence_score,
            ))
            await db.commit()

        # ── Step 6: publish event ─────────────────────────────────────
        await event_bus.publish(EventType.AGENT_DECISION, {
            "agent": "WatchTimeTipAgent",
            "user_id": event.user_id,
            "video_id": event.video_id,
            "creator_id": creator_id,
            "amount": amount,
            "token": config.default_token,
            "tx_hash": tx.tx_hash,
            "reasoning": tip_decision_model.reasoning,
            "confidence": tip_decision_model.confidence_score,
        })

    # ------------------------------------------------------------------
    # Claude call
    # ------------------------------------------------------------------

    async def _ask_claude(
        self,
        watch_percentage: float,
        video_duration: int,
        creator_name: str,
        user_max_per_video: float,
        already_tipped_today: float,
        hint: float,
    ) -> dict:
        user_message = json.dumps({
            "watch_percentage": round(watch_percentage, 1),
            "video_duration": video_duration,
            "creator_name": creator_name,
            "user_max_per_video": user_max_per_video,
            "already_tipped_today": already_tipped_today,
            "suggested_tip_hint": hint,
        })

        logger.debug(f"[WATCH AGENT] Asking Claude — {user_message}")

        async with self._client.messages.stream(
            model="claude-sonnet-4-20250514",
            max_tokens=256,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        ) as stream:
            response = await stream.get_final_message()

        text = next((b.text for b in response.content if b.type == "text"), "{}")
        result = json.loads(text)

        # Safety cap
        if result.get("amount", 0) > user_max_per_video:
            result["amount"] = user_max_per_video

        logger.debug(
            f"[WATCH AGENT] Claude → should_tip={result.get('should_tip')} "
            f"amount={result.get('amount')} confidence={result.get('confidence')}"
        )
        return result

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------

    async def _tipped_today(self, db: AsyncSession, user_id: str) -> float:
        """Total amount tipped by this user today."""
        today_start = datetime.combine(date.today(), datetime.min.time())
        stmt = select(func.coalesce(func.sum(TipTransactionORM.amount), 0)).where(
            TipTransactionORM.from_wallet == user_id,
            TipTransactionORM.timestamp >= today_start,
            TipTransactionORM.status == "confirmed",
        )
        result = await db.execute(stmt)
        return float(result.scalar() or 0)

    async def _spent_today(self, db: AsyncSession, user_id: str) -> float:
        return await self._tipped_today(db, user_id)
