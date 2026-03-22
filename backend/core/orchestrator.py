"""
TipMind Orchestrator
--------------------
Central coordinator that initialises and wires all agents, manages user
preferences, exposes inject_event() for the API layer, and provides a
demo-mode that fires pre-built event sequences.

Public API:
  orchestrator.start()                  → subscribe all agents to event bus
  orchestrator.inject_event(type, data) → push any event into the bus
  orchestrator.get_system_status()      → agent states, wallet, swarms, tips
  orchestrator.inject_demo_scenario(s)  → 'watch' | 'hype' | 'milestone' | 'swarm'
  orchestrator.set_user_preference(k,v) → update session preferences
  orchestrator.get_user_preferences()   → current preference dict

All logs prefixed [ORCHESTRATOR].
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from loguru import logger
from sqlalchemy import func, select

from backend.agents.emotion_agent import EmotionChatAgent
from backend.agents.milestone_agent import MilestoneTipAgent
from backend.agents.swarm_agent import SwarmAgent
from backend.agents.tip_agent import WatchTimeTipAgent
from backend.config import config
from backend.core.event_bus import event_bus, EventType
from backend.core.swarm_pool import swarm_pool
from backend.core.wallet import WalletFactory
from backend.data.database import AsyncSessionLocal
from backend.data.models import MilestoneType, SwarmStatus, TipTransactionORM


# ---------------------------------------------------------------------------
# Default user preferences
# ---------------------------------------------------------------------------

DEFAULT_PREFERENCES: dict[str, Any] = {
    "auto_tip_enabled": True,
    "max_per_video": 5.0,
    "max_per_day": 20.0,
    "preferred_token": "USDT",
    "enabled_triggers": [
        "WATCH_TIME_UPDATE",
        "CHAT_MESSAGE",
        "MILESTONE_REACHED",
        "SWARM_TRIGGERED",
    ],
}


# ---------------------------------------------------------------------------
# Demo event sequences
# ---------------------------------------------------------------------------

DEMO_CREATOR_ID  = "demo_creator_001"
DEMO_VIDEO_ID    = "demo_video_001"
DEMO_USER_PREFIX = "demo_fan_"


class Orchestrator:
    """
    Single entry point for starting agents, injecting events, querying
    system status, and running demo scenarios.
    """

    def __init__(self) -> None:
        self._db_factory = AsyncSessionLocal
        self._wallet = WalletFactory.create()

        # Agent instances
        self._watch_agent     = WatchTimeTipAgent(db_session_factory=self._db_factory)
        self._emotion_agent   = EmotionChatAgent(db_session_factory=self._db_factory)
        self._milestone_agent = MilestoneTipAgent(db_session_factory=self._db_factory)
        self._swarm_agent     = SwarmAgent()

        # Agent alive flags (True once subscribed)
        self._agent_states: dict[str, str] = {
            "WatchTimeTipAgent":  "idle",
            "EmotionChatAgent":   "idle",
            "MilestoneTipAgent":  "idle",
            "SwarmAgent":         "idle",
        }

        # Per-session user preferences
        self._preferences: dict[str, Any] = dict(DEFAULT_PREFERENCES)

    # ------------------------------------------------------------------
    # Start-up
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Subscribe all agents to the event bus."""
        self._watch_agent.subscribe()
        self._agent_states["WatchTimeTipAgent"] = "listening"

        self._emotion_agent.subscribe()
        self._agent_states["EmotionChatAgent"] = "listening"

        self._milestone_agent.subscribe()
        self._agent_states["MilestoneTipAgent"] = "listening"

        self._swarm_agent.subscribe()
        self._agent_states["SwarmAgent"] = "listening"

        logger.info("[ORCHESTRATOR] All agents started and listening on event bus")

    # ------------------------------------------------------------------
    # Event injection
    # ------------------------------------------------------------------

    async def inject_event(self, event_type: str | EventType, payload: dict) -> None:
        """Push any event into the event bus (used by API routes and demo mode)."""
        if isinstance(event_type, str):
            event_type = EventType(event_type)
        logger.info(f"[ORCHESTRATOR] inject_event → {event_type.value}")
        await event_bus.publish(event_type, payload)

    # ------------------------------------------------------------------
    # User preferences
    # ------------------------------------------------------------------

    def set_user_preference(self, key: str, value: Any) -> None:
        if key not in DEFAULT_PREFERENCES:
            logger.warning(f"[ORCHESTRATOR] Unknown preference key: {key}")
            return
        self._preferences[key] = value
        logger.info(f"[ORCHESTRATOR] Preference set: {key}={value}")

    def get_user_preferences(self) -> dict[str, Any]:
        return dict(self._preferences)

    # ------------------------------------------------------------------
    # System status
    # ------------------------------------------------------------------

    async def get_system_status(self) -> dict[str, Any]:
        """
        Returns a snapshot of:
          - agent states
          - wallet balance
          - active swarms
          - tips sent today
        """
        # Wallet balance
        try:
            balance = await self._wallet.get_balance(self._preferences["preferred_token"])
        except Exception as exc:
            logger.warning(f"[ORCHESTRATOR] Could not fetch wallet balance: {exc}")
            balance = None

        # Active swarms
        try:
            async with self._db_factory() as db:
                active_swarms = await swarm_pool.get_active_swarms(db)
                swarm_summaries = [
                    {
                        "swarm_id":          g.swarm_id,
                        "creator_id":        g.creator_id,
                        "goal_description":  g.goal_description,
                        "trigger_event":     g.trigger_event,
                        "target_amount_usd": g.target_amount_usd,
                        "current_amount_usd":g.current_amount_usd,
                        "participant_count": g.participant_count,
                        "status":            g.status,
                    }
                    for g in active_swarms
                ]

                # Tips sent today
                today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
                tips_today_row = await db.execute(
                    select(func.sum(TipTransactionORM.amount)).where(
                        TipTransactionORM.timestamp >= today_start,
                        TipTransactionORM.status == "confirmed",
                    )
                )
                tips_today_usd = float(tips_today_row.scalar() or 0.0)

                tips_count_row = await db.execute(
                    select(func.count(TipTransactionORM.id)).where(
                        TipTransactionORM.timestamp >= today_start,
                        TipTransactionORM.status == "confirmed",
                    )
                )
                tips_today_count = int(tips_count_row.scalar() or 0)

        except Exception as exc:
            logger.warning(f"[ORCHESTRATOR] DB query error in get_system_status: {exc}")
            swarm_summaries = []
            tips_today_usd  = 0.0
            tips_today_count = 0

        return {
            "agents": dict(self._agent_states),
            "wallet": {
                "balance": balance,
                "token":   self._preferences["preferred_token"],
                "address": await self._wallet.get_wallet_address(),
            },
            "active_swarms":     swarm_summaries,
            "tips_today_usd":    tips_today_usd,
            "tips_today_count":  tips_today_count,
            "preferences":       self.get_user_preferences(),
        }

    # ------------------------------------------------------------------
    # Demo mode
    # ------------------------------------------------------------------

    async def inject_demo_scenario(self, scenario: str) -> dict[str, Any]:
        """
        Fire a pre-built event sequence.

        Scenarios
        ---------
        'watch'     → simulates watching 80% of a video
        'hype'      → injects 20 excited chat messages
        'milestone' → fires a DEBATE_WIN milestone
        'swarm'     → seeds + triggers the pre-built $100 swarm
        """
        scenario = scenario.lower().strip()
        logger.info(f"[ORCHESTRATOR] Demo scenario: '{scenario}'")

        if scenario == "watch":
            return await self._demo_watch()
        elif scenario == "hype":
            return await self._demo_hype()
        elif scenario == "milestone":
            return await self._demo_milestone()
        elif scenario == "swarm":
            return await self._demo_swarm()
        else:
            logger.warning(f"[ORCHESTRATOR] Unknown demo scenario: {scenario}")
            return {"ok": False, "reason": f"Unknown scenario '{scenario}'"}

    # ------------------------------------------------------------------
    # Demo helpers
    # ------------------------------------------------------------------

    async def _demo_watch(self) -> dict:
        """Simulate a fan watching 80% of a video → triggers WatchTimeTipAgent."""
        payload = {
            "video_id":        DEMO_VIDEO_ID,
            "creator_id":      DEMO_CREATOR_ID,
            "creator_name":    "DemoCreator",
            "user_id":         "demo_fan_01",
            "percentage_watched": 80.0,
            "watch_seconds":      480,
            "total_duration":     600,
            "user_budget_remaining": self._preferences["max_per_video"],
        }
        await self.inject_event(EventType.WATCH_TIME_UPDATE, payload)
        logger.info("[ORCHESTRATOR] Demo 'watch' injected — 80% watch event")
        return {"ok": True, "scenario": "watch", "payload": payload}

    async def _demo_hype(self) -> dict:
        """Inject 20 excited chat messages → triggers EmotionChatAgent."""
        hype_messages = [
            "insane play bro 🔥🔥🔥",
            "lets go!!!",
            "W W W W W",
            "clip it clip it!!",
            "this is insane omg",
            "let's go legend",
            "🔥🔥🔥🔥🔥",
            "GOAT behaviour",
            "POG POG POG",
            "insane stream today",
            "let's go!! best creator",
            "clip it now!!!",
            "W moment fr fr",
            "🔥 insane energy",
            "lets go lets go lets go",
            "omg omg omg",
            "GOAT GOAT GOAT",
            "insane W",
            "clip it!!!! 🔥",
            "lets gooooo 🔥🔥🔥",
        ]
        for i, msg in enumerate(hype_messages):
            await self.inject_event(EventType.CHAT_MESSAGE, {
                "user_id":   f"{DEMO_USER_PREFIX}{i+1:02d}",
                "video_id":  DEMO_VIDEO_ID,
                "creator_id": DEMO_CREATOR_ID,
                "message":   msg,
            })
        logger.info("[ORCHESTRATOR] Demo 'hype' injected — 20 hype chat messages")
        return {"ok": True, "scenario": "hype", "messages_injected": len(hype_messages)}

    async def _demo_milestone(self) -> dict:
        """Fire a DEBATE_WIN milestone → triggers MilestoneTipAgent + swarm."""
        payload = {
            "creator_id":           DEMO_CREATOR_ID,
            "creator_name":         "DemoCreator",
            "milestone_type":       MilestoneType.DEBATE_WIN.value,
            "value":                1,
            "creator_history":      ["Won 3 debates this month"],
            "user_budget_remaining": self._preferences["max_per_video"],
        }
        await self.inject_event(EventType.MILESTONE_REACHED, payload)
        logger.info("[ORCHESTRATOR] Demo 'milestone' injected — DEBATE_WIN milestone")
        return {"ok": True, "scenario": "milestone", "payload": payload}

    async def _demo_swarm(self) -> dict:
        """Seed the pre-built demo swarm and trigger it."""
        await self._swarm_agent.seed_and_trigger_demo()
        logger.info("[ORCHESTRATOR] Demo 'swarm' triggered — 20 fans × $5 = $100")
        return {
            "ok": True,
            "scenario": "swarm",
            "description": "Tip $100 if creator wins the debate",
            "participants": 20,
            "target_usd": 100.0,
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

orchestrator = Orchestrator()
