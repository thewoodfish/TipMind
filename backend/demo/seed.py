"""
backend/demo/seed.py — Seed realistic demo data into TipMind's database.

Called automatically on startup if the database is empty.
Can also be run directly: python -m backend.demo.seed
"""
from __future__ import annotations

import asyncio
import random
import uuid
from datetime import datetime, timedelta
from random import choice, randint, uniform

from loguru import logger
from sqlalchemy import func, select

from backend.data.database import AsyncSessionLocal, create_all_tables
from backend.data.models import (
    AgentDecisionLogORM,
    SwarmGoalORM,
    SwarmParticipantORM,
    SwarmStatus,
    TipTransactionORM,
)

# ---------------------------------------------------------------------------
# Mock data
# ---------------------------------------------------------------------------

CREATORS = [
    {"id": "creator_001", "name": "Alex Rivera",   "niche": "Tech Reviews",    "followers": 250_000},
    {"id": "creator_002", "name": "Maya Chen",     "niche": "Debate Champion", "followers": 180_000},
    {"id": "creator_003", "name": "Sam Johnson",   "niche": "Gaming Streams",  "followers": 320_000},
    {"id": "creator_004", "name": "Jordan Lee",    "niche": "Crypto Analysis", "followers": 95_000},
    {"id": "creator_005", "name": "Taylor Kim",    "niche": "Music Producer",  "followers": 410_000},
]

TOKENS = ["USDT", "USDT", "USDT", "XAUT", "BTC"]   # weighted toward USDT

TRIGGER_TYPES = ["WATCH_TIME", "EMOTION", "MILESTONE", "SWARM_RELEASE"]

AGENT_TYPES = {
    "WATCH_TIME":     "WatchTimeTipAgent",
    "EMOTION":        "EmotionChatAgent",
    "MILESTONE":      "MilestoneTipAgent",
    "SWARM_RELEASE":  "SwarmAgent",
}

REASONING = {
    "WATCH_TIME": [
        "User watched {pct}% of the video — above engagement threshold. Micro-tip dispatched.",
        "Watch completion at {pct}% signals high content quality. Small tip fired.",
        "Sustained {pct}% watch-through detected on a 45-min video. Rewarding creator.",
        "Watch-time engagement score: {pct}%. Auto-tipping at configured rate.",
    ],
    "EMOTION": [
        "Chat hype velocity: 18 positive messages in 30 s. Emotion threshold crossed.",
        "Sentiment spike detected — crowd energy 0.87/1.0. Firing emotion tip.",
        "Live chat eruption: 'LFG!' ×8, 'PogChamp' ×12. Collective hype confirmed.",
        "Rolling 60 s chat sentiment: +0.91. High engagement reward triggered.",
        "Emotional peak detected mid-stream — viewers reacting strongly to creator moment.",
    ],
    "MILESTONE": [
        "Creator hit DEBATE_WIN milestone — commemorating with premium tip.",
        "100K views crossed — milestone tip dispatched automatically.",
        "LIKES_10K milestone reached. Celebration tip fired per user preference.",
        "SUBS_MILESTONE event: creator crossed a major subscriber threshold.",
        "Milestone VIEWS_100K verified — AI agent rewarding creator achievement.",
    ],
    "SWARM_RELEASE": [
        "SWARM RELEASED: {n} fans tipped ${amt} simultaneously.",
        "Collective tip pool reached target. ${amt} released to creator instantly.",
        "Swarm trigger fired — {n} participants tipped in parallel via asyncio.gather().",
        "Fan swarm complete: {n} micro-tips totalling ${amt} sent in one atomic burst.",
    ],
}


def _tx_hash() -> str:
    return "0x" + uuid.uuid4().hex + uuid.uuid4().hex[:8]


def _ts(hours_ago: float) -> datetime:
    return datetime.utcnow() - timedelta(hours=hours_ago)


# ---------------------------------------------------------------------------
# Individual seeders
# ---------------------------------------------------------------------------

async def seed_transactions(session) -> None:
    """Insert 20 realistic tip transactions spanning the last 24 hours."""
    random.seed(42)
    rows: list[TipTransactionORM] = []

    for _ in range(20):
        creator = choice(CREATORS)
        trigger = choice(TRIGGER_TYPES)
        token = choice(TOKENS)

        if trigger == "SWARM_RELEASE":
            amount = round(uniform(4.0, 10.0), 2)
        elif trigger == "MILESTONE":
            amount = round(uniform(2.0, 8.0), 2)
        elif trigger == "EMOTION":
            amount = round(uniform(0.5, 3.0), 2)
        else:  # WATCH_TIME
            amount = round(uniform(0.10, 1.00), 2)

        rows.append(TipTransactionORM(
            tx_hash=_tx_hash(),
            from_wallet="0xTipMindAgent001",
            to_wallet=f"0x{creator['id']}wallet",
            amount=amount,
            token=token,
            creator_id=creator["id"],
            trigger_type=trigger,
            status="confirmed",
            timestamp=_ts(uniform(0.2, 23.5)),
        ))

    # One pending tx for live drama
    rows.append(TipTransactionORM(
        tx_hash=_tx_hash(),
        from_wallet="0xTipMindAgent001",
        to_wallet="0xcreator_001wallet",
        amount=5.00,
        token="USDT",
        creator_id="creator_001",
        trigger_type="SWARM_RELEASE",
        status="pending",
        timestamp=_ts(0.03),
    ))

    session.add_all(rows)
    logger.info(f"[SEED] {len(rows)} tip transactions inserted")


async def seed_swarms(session) -> None:
    """Insert 2 active swarm goals — one at 80% for demo drama."""

    # Swarm 1: 80% funded — primed to pop during demo
    s1_id = "demo-swarm-alpha-001"
    session.add(SwarmGoalORM(
        swarm_id=s1_id,
        creator_id="creator_001",
        goal_description="Tip $50 if Alex Rivera wins the live tech debate tonight",
        trigger_event="DEBATE_WIN",
        target_amount_usd=50.0,
        current_amount_usd=40.0,   # 80%
        participant_count=8,
        status=SwarmStatus.ACTIVE.value,
        created_at=_ts(2.0),
    ))
    for i in range(8):
        session.add(SwarmParticipantORM(
            swarm_id=s1_id,
            user_id=f"fan_{i+1:03d}",
            committed_amount_usd=5.0,
            joined_at=_ts(uniform(0.5, 2.0)),
        ))

    # Swarm 2: ~31% funded — building momentum
    s2_id = "demo-swarm-beta-002"
    session.add(SwarmGoalORM(
        swarm_id=s2_id,
        creator_id="creator_002",
        goal_description="$200 fan pool if Maya Chen hits 200K subscribers",
        trigger_event="SUBS_MILESTONE",
        target_amount_usd=200.0,
        current_amount_usd=62.0,   # 31%
        participant_count=12,
        status=SwarmStatus.ACTIVE.value,
        created_at=_ts(5.0),
    ))
    for i in range(12):
        session.add(SwarmParticipantORM(
            swarm_id=s2_id,
            user_id=f"fan_{i+20:03d}",
            committed_amount_usd=round(uniform(3.0, 8.0), 2),
            joined_at=_ts(uniform(0.5, 5.0)),
        ))

    logger.info("[SEED] 2 active swarm goals inserted (80% + 31% funded)")


async def seed_agent_decisions(session) -> None:
    """Insert 50 agent decisions with realistic reasoning snippets."""
    random.seed(99)
    rows: list[AgentDecisionLogORM] = []

    for _ in range(50):
        creator = choice(CREATORS)
        trigger = choice(TRIGGER_TYPES)
        template = choice(REASONING[trigger])

        reasoning = template
        if "{pct}" in reasoning:
            reasoning = reasoning.format(pct=randint(75, 98))
        if "{n}" in reasoning:
            reasoning = reasoning.format(n=randint(8, 25), amt=round(uniform(20, 120), 0))
        if "{amt}" in reasoning:
            reasoning = reasoning.format(amt=round(uniform(20, 120), 0))

        rows.append(AgentDecisionLogORM(
            agent_type=AGENT_TYPES[trigger],
            trigger=trigger,
            creator_id=creator["id"],
            amount_usd=round(uniform(0.10, 8.0), 2),
            token=choice(TOKENS),
            reasoning=reasoning,
            confidence_score=round(uniform(0.65, 0.99), 2),
            created_at=_ts(uniform(0.0, 23.9)),
        ))

    session.add_all(rows)
    logger.info(f"[SEED] {len(rows)} agent decisions inserted")


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------

async def run_seed() -> None:
    """Seed database if empty. Safe to call on every startup."""
    await create_all_tables()

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(func.count()).select_from(TipTransactionORM)
        )
        count = result.scalar() or 0

        if count > 0:
            logger.info(f"[SEED] DB already has {count} transactions — skipping seed")
            return

        logger.info("[SEED] Empty database detected — seeding demo data...")
        await seed_transactions(session)
        await seed_swarms(session)
        await seed_agent_decisions(session)
        await session.commit()
        logger.info("[SEED] Demo data seeded successfully ✓")


if __name__ == "__main__":
    asyncio.run(run_seed())
