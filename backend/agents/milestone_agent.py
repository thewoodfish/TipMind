"""
Milestone Tip Agent
-------------------
Subscribes to MILESTONE_REACHED events and sends celebration tips sized by
the milestone type and magnitude.

Pipeline:
  1. Receive MILESTONE_REACHED event payload
  2. Look up base tip amount for the milestone type
  3. Ask Claude for final tip amount, message, and swarm trigger decision
  4. If trigger_swarm=true → publish SWARM_TRIGGERED event
  5. Execute tip via wallet, persist records, publish AGENT_DECISION

All logs prefixed [MILESTONE AGENT].
"""
from __future__ import annotations

import json
import re
from typing import Any

import anthropic
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import config
from backend.core.event_bus import event_bus, EventType
from backend.core.wallet import WalletFactory
from backend.data.models import (
    AgentDecisionLogORM,
    MilestoneEvent,
    MilestoneType,
    TipTransactionORM,
)


# ---------------------------------------------------------------------------
# Base tip amounts per milestone type
# ---------------------------------------------------------------------------

BASE_TIPS: dict[MilestoneType, float] = {
    MilestoneType.LIKES_10K:       0.50,
    MilestoneType.VIEWS_100K:      1.00,
    MilestoneType.SUBS_MILESTONE:  2.00,
    MilestoneType.DEBATE_WIN:      3.00,
    MilestoneType.CUSTOM:          0.00,   # Claude decides fully
}

# DEBATE_WIN always triggers swarm check
ALWAYS_SWARM = {MilestoneType.DEBATE_WIN}

SYSTEM_PROMPT = (
    "You are a fan celebrating creator milestones. "
    "Determine an appropriate tip to celebrate. "
    "Be more generous for bigger milestones. "
    "Return JSON only."
)


# ---------------------------------------------------------------------------
# Milestone Tip Agent
# ---------------------------------------------------------------------------

class MilestoneTipAgent:
    """
    Listens for MILESTONE_REACHED events and sends appropriately sized tips.
    """

    def __init__(self, db_session_factory) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=config.anthropic_api_key)
        self._db_factory = db_session_factory
        self._wallet = WalletFactory.create()

    # ------------------------------------------------------------------
    # Subscription
    # ------------------------------------------------------------------

    def subscribe(self) -> None:
        event_bus.subscribe(EventType.MILESTONE_REACHED, self._handle_milestone)
        logger.info("[MILESTONE AGENT] Subscribed to MILESTONE_REACHED events")

    # ------------------------------------------------------------------
    # Event handler
    # ------------------------------------------------------------------

    async def _handle_milestone(self, payload: dict[str, Any]) -> None:
        """
        Expected payload keys (matches MilestoneEvent pydantic model):
          creator_id, milestone_type, value, creator_name,
          creator_history (list[str]), user_budget_remaining (float)
        """
        try:
            event = MilestoneEvent(
                creator_id=payload["creator_id"],
                milestone_type=MilestoneType(payload["milestone_type"]),
                value=int(payload["value"]),
            )
        except Exception as exc:
            logger.warning(f"[MILESTONE AGENT] Invalid payload: {exc}")
            return

        creator_name     = payload.get("creator_name", event.creator_id)
        creator_history  = payload.get("creator_history", [])
        budget_remaining = float(payload.get("user_budget_remaining", config.max_tip_per_video))

        logger.info(
            f"[MILESTONE AGENT] {event.milestone_type.value} for '{creator_name}' "
            f"(value={event.value:,})"
        )

        base_tip = BASE_TIPS.get(event.milestone_type, 0.50)

        # ── Ask Claude (or mock) ──────────────────────────────────────
        async with self._db_factory() as db:
            recent_decisions = await self._recent_decisions(db, event.creator_id)

        if config.effective_mock:
            from backend.core.mock_claude import milestone_decision
            decision = milestone_decision(
                milestone_type=event.milestone_type.value,
                creator_name=creator_name,
                base_tip_hint=base_tip,
            )
        else:
            decision = await self._ask_claude(
                milestone_type=event.milestone_type.value,
                milestone_value=event.value,
                creator_name=creator_name,
                creator_history=creator_history,
                user_budget_remaining=budget_remaining,
                base_tip_hint=base_tip,
                recent_decisions=recent_decisions,
            )

        tip_amount   = min(float(decision.get("tip_amount", base_tip)), config.max_tip_per_video)
        message      = decision.get("message", "")
        trigger_swarm = decision.get("trigger_swarm", False) or event.milestone_type in ALWAYS_SWARM
        reasoning    = decision.get("reasoning", "")

        logger.info(
            f"[MILESTONE AGENT] Claude → amount={tip_amount} "
            f"trigger_swarm={trigger_swarm} | {reasoning[:80]}"
        )

        # ── Swarm trigger ─────────────────────────────────────────────
        if trigger_swarm:
            await event_bus.publish(EventType.SWARM_TRIGGERED, {
                "source": "MilestoneTipAgent",
                "creator_id": event.creator_id,
                "milestone_type": event.milestone_type.value,
                "milestone_value": event.value,
                "message": message,
            })
            logger.info(
                f"[MILESTONE AGENT] SWARM_TRIGGERED for milestone "
                f"{event.milestone_type.value} — {creator_name}"
            )

        # ── Execute tip ───────────────────────────────────────────────
        if tip_amount <= 0:
            logger.info("[MILESTONE AGENT] Tip amount is 0 — skipping wallet call")
            return

        try:
            tx = await self._wallet.send_tip(
                to_address=event.creator_id,
                amount=tip_amount,
                token=config.default_token,
            )
            logger.info(
                f"[MILESTONE AGENT] Tip sent — {tip_amount} {config.default_token} "
                f"→ {event.creator_id} | tx={tx.tx_hash}"
            )
        except Exception as exc:
            logger.error(f"[MILESTONE AGENT] Wallet error: {exc}")
            return

        # ── Persist ───────────────────────────────────────────────────
        async with self._db_factory() as db:
            db.add(TipTransactionORM(
                tx_hash=tx.tx_hash,
                from_wallet=await self._wallet.get_wallet_address(),
                to_wallet=event.creator_id,
                amount=tip_amount,
                token=config.default_token,
                creator_id=event.creator_id,
                trigger_type=f"MILESTONE:{event.milestone_type.value}",
                status=tx.status,
            ))
            db.add(AgentDecisionLogORM(
                agent_type="MilestoneTipAgent",
                trigger=f"MILESTONE:{event.milestone_type.value}:{event.value}",
                creator_id=event.creator_id,
                amount_usd=tip_amount,
                reasoning=f"{reasoning} | msg: {message}",
                confidence_score=0.95,
            ))
            await db.commit()

        # ── Publish AGENT_DECISION ────────────────────────────────────
        await event_bus.publish(EventType.AGENT_DECISION, {
            "agent": "MilestoneTipAgent",
            "creator_id": event.creator_id,
            "creator_name": creator_name,
            "milestone_type": event.milestone_type.value,
            "milestone_value": event.value,
            "amount": tip_amount,
            "token": config.default_token,
            "tx_hash": tx.tx_hash,
            "message": message,
            "trigger_swarm": trigger_swarm,
            "reasoning": reasoning,
        })

    # ------------------------------------------------------------------
    # Claude call
    # ------------------------------------------------------------------

    async def _ask_claude(
        self,
        milestone_type: str,
        milestone_value: int,
        creator_name: str,
        creator_history: list[str],
        user_budget_remaining: float,
        base_tip_hint: float,
        recent_decisions: list[dict] | None = None,
    ) -> dict:
        user_message = json.dumps({
            "milestone_type": milestone_type,
            "milestone_value": milestone_value,
            "creator_name": creator_name,
            "creator_history": creator_history,
            "user_budget_remaining": user_budget_remaining,
            "base_tip_hint": base_tip_hint,
            "max_tip": config.max_tip_per_video,
            "recent_decisions": recent_decisions or [],
        })

        logger.debug(f"[MILESTONE AGENT] Asking Groq — {user_message}")

        from backend.core.groq_client import chat as groq_chat
        text = await groq_chat(system=SYSTEM_PROMPT, user=user_message, max_tokens=256)
        text = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.MULTILINE)
        text = re.sub(r"```\s*$", "", text.strip(), flags=re.MULTILINE)
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            logger.warning(f"[MILESTONE AGENT] Claude non-JSON: {text[:80]!r}")
            return {"tip_amount": base_tip_hint if base_tip_hint else 0.5, "trigger_swarm": False, "reasoning": "parse error", "message": ""}

    async def _recent_decisions(self, db: AsyncSession, creator_id: str) -> list[dict]:
        """Last 3 decisions for this creator to give Claude historical context."""
        stmt = (
            select(AgentDecisionLogORM)
            .where(AgentDecisionLogORM.creator_id == creator_id)
            .order_by(AgentDecisionLogORM.id.desc())
            .limit(3)
        )
        rows = await db.execute(stmt)
        return [
            {
                "amount_usd": r.amount_usd,
                "trigger": r.trigger,
                "reasoning": r.reasoning[:120] if r.reasoning else "",
            }
            for r in rows.scalars()
        ]


# ---------------------------------------------------------------------------
# Legacy thin wrapper kept for SwarmAgent compatibility
# ---------------------------------------------------------------------------

class MilestoneAgent:
    """Used by SwarmAgent for inline milestone evaluation (not event-driven)."""

    SYSTEM_PROMPT = """You are a creator economy analyst specializing in content milestones.
Determine which milestones are genuinely new and calculate the total bonus tip.
Respond with JSON:
{"new_milestones": [...], "total_bonus": X.XX, "milestone_triggered": true/false, "reasoning": "..."}
Respond ONLY with valid JSON."""

    def __init__(self) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=config.anthropic_api_key)

    async def evaluate(self, video_metadata: dict, previously_rewarded: list[str]) -> dict:
        view_count = video_metadata.get("view_count", 0)
        like_count = video_metadata.get("like_count", 0)

        candidates = []
        if view_count >= 100_000 and "VIEWS_100K" not in previously_rewarded:
            candidates.append({"type": "VIEWS_100K", "threshold": 100_000, "bonus": 1.00})
        if like_count >= 10_000 and "LIKES_10K" not in previously_rewarded:
            candidates.append({"type": "LIKES_10K", "threshold": 10_000, "bonus": 0.50})

        if not candidates:
            return {"new_milestones": [], "total_bonus": 0.0, "milestone_triggered": False, "reasoning": "No new milestones."}

        user_message = (
            f"Views: {view_count:,}, Likes: {like_count:,}\n"
            f"Previously rewarded: {previously_rewarded}\n"
            f"Candidates: {candidates}"
        )
        logger.info(f"[MILESTONE AGENT] Evaluating {len(candidates)} candidates (inline)")

        from backend.core.groq_client import chat as groq_chat
        text = await groq_chat(system=self.SYSTEM_PROMPT, user=user_message, max_tokens=512)
        result = json.loads(text)
        logger.info(f"[MILESTONE AGENT] triggered={result.get('milestone_triggered')} bonus={result.get('total_bonus', 0)}")
        return result
