from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from backend.core.event_bus import EventType
from backend.core.orchestrator import orchestrator
from backend.core.swarm_pool import swarm_pool
from backend.core.wallet import WalletFactory
from backend.data.database import get_db
from backend.data.models import (
    AgentDecisionLogORM,
    SwarmGoalORM,
    TipTransactionORM,
)

router = APIRouter()
_wallet = WalletFactory.create()


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class InjectEventRequest(BaseModel):
    event_type: str
    payload: dict[str, Any] = {}


class CreateSwarmRequest(BaseModel):
    creator_id: str
    goal_description: str
    trigger_event: str
    target_amount: float


class JoinSwarmRequest(BaseModel):
    user_id: str
    pledged_amount: float


class PreferenceRequest(BaseModel):
    key: str
    value: Any


class PreferenceBulkRequest(BaseModel):
    preferences: dict[str, Any]


class WatchEventRequest(BaseModel):
    video_id: str
    creator_id: str
    creator_name: str = ""
    user_id: str = "user_001"
    watch_percentage: float
    watch_duration: int = 0
    total_duration: int = 0
    user_budget_remaining: float = 5.0


class ChatMessageRequest(BaseModel):
    video_id: str
    creator_id: str
    user_id: str
    message: str


class MilestoneRequest(BaseModel):
    creator_id: str
    creator_name: str = ""
    milestone_type: str
    value: int = 1
    user_budget_remaining: float = 5.0


# ---------------------------------------------------------------------------
# System status
# ---------------------------------------------------------------------------

@router.get("/status")
async def system_status():
    """Full system snapshot: agent states, wallet balance, active swarms, tips today."""
    return await orchestrator.get_system_status()


@router.get("/health")
async def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Swarms
# ---------------------------------------------------------------------------

@router.get("/swarms")
async def list_active_swarms(db: AsyncSession = Depends(get_db)):
    """List all currently active swarm goals with participant counts."""
    goals = await swarm_pool.get_active_swarms(db)
    return [
        {
            "swarm_id":           g.swarm_id,
            "creator_id":         g.creator_id,
            "goal_description":   g.goal_description,
            "trigger_event":      g.trigger_event,
            "target_amount_usd":  g.target_amount_usd,
            "current_amount_usd": g.current_amount_usd,
            "participant_count":  g.participant_count,
            "status":             g.status,
            "created_at":         g.created_at.isoformat() if g.created_at else None,
        }
        for g in goals
    ]


@router.post("/swarms")
async def create_swarm(body: CreateSwarmRequest, db: AsyncSession = Depends(get_db)):
    """Create a new swarm goal."""
    goal = await swarm_pool.create_swarm(
        db=db,
        creator_id=body.creator_id,
        goal_description=body.goal_description,
        trigger_event=body.trigger_event,
        target_amount=body.target_amount,
    )
    logger.info(f"[API] Created swarm {goal.swarm_id} for creator={body.creator_id}")
    return {
        "swarm_id":           goal.swarm_id,
        "creator_id":         goal.creator_id,
        "goal_description":   goal.goal_description,
        "trigger_event":      goal.trigger_event,
        "target_amount_usd":  goal.target_amount_usd,
        "current_amount_usd": goal.current_amount_usd,
        "participant_count":  goal.participant_count,
        "status":             goal.status,
    }


@router.post("/swarms/{swarm_id}/join")
async def join_swarm(
    swarm_id: str,
    body: JoinSwarmRequest,
    db: AsyncSession = Depends(get_db),
):
    """Join a swarm with a pledged tip amount."""
    result = await swarm_pool.join_swarm(
        db=db,
        swarm_id=swarm_id,
        user_id=body.user_id,
        pledged_amount=body.pledged_amount,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("reason", "Could not join swarm"))
    return result


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------

@router.get("/transactions")
async def list_transactions(
    limit: int = 20,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """Recent tip transactions with pagination."""
    stmt = (
        select(TipTransactionORM)
        .order_by(desc(TipTransactionORM.created_at))
        .limit(limit)
        .offset(offset)
    )
    rows = await db.execute(stmt)
    tips = rows.scalars().all()

    total_row = await db.execute(select(func.count(TipTransactionORM.id)))
    total = int(total_row.scalar() or 0)

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [
            {
                "id":           t.id,
                "tx_hash":      t.tx_hash,
                "from_wallet":  t.from_wallet,
                "to_wallet":    t.to_wallet,
                "amount":       t.amount,
                "token":        t.token,
                "creator_id":   t.creator_id,
                "trigger_type": t.trigger_type,
                "status":       t.status,
                "created_at":   t.created_at.isoformat() if t.created_at else None,
            }
            for t in tips
        ],
    }


# ---------------------------------------------------------------------------
# Agent decisions
# ---------------------------------------------------------------------------

@router.get("/decisions")
async def list_decisions(
    limit: int = 20,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """Recent agent decisions with reasoning."""
    stmt = (
        select(AgentDecisionLogORM)
        .order_by(desc(AgentDecisionLogORM.created_at))
        .limit(limit)
        .offset(offset)
    )
    rows = await db.execute(stmt)
    decisions = rows.scalars().all()

    total_row = await db.execute(select(func.count(AgentDecisionLogORM.id)))
    total = int(total_row.scalar() or 0)

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [
            {
                "id":               d.id,
                "agent_type":       d.agent_type,
                "trigger":          d.trigger,
                "creator_id":       d.creator_id,
                "amount_usd":       d.amount_usd,
                "reasoning":        d.reasoning,
                "confidence_score": d.confidence_score,
                "created_at":       d.created_at.isoformat() if d.created_at else None,
            }
            for d in decisions
        ],
    }


# ---------------------------------------------------------------------------
# Preferences
# ---------------------------------------------------------------------------

@router.get("/preferences")
async def get_preferences():
    """Get current user tip preferences."""
    return orchestrator.get_user_preferences()


@router.put("/preferences")
async def update_preferences(body: PreferenceBulkRequest):
    """Update one or more user preferences."""
    for key, value in body.preferences.items():
        orchestrator.set_user_preference(key, value)
    return orchestrator.get_user_preferences()


# ---------------------------------------------------------------------------
# Demo scenarios
# ---------------------------------------------------------------------------

@router.post("/demo/{scenario}")
async def demo_scenario(scenario: str):
    """
    Trigger a pre-built demo scenario.

    - watch     → 80% watch event
    - hype      → 20 excited chat messages
    - milestone → DEBATE_WIN milestone
    - swarm     → seed + trigger $100 fan swarm
    """
    result = await orchestrator.inject_demo_scenario(scenario)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("reason", "Unknown scenario"))
    return result


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

@router.get("/metrics")
async def get_metrics(db: AsyncSession = Depends(get_db)):
    """Aggregate metrics: total tipped today, this week, top creators tipped."""
    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=now.weekday())

    # Total tipped today
    today_row = await db.execute(
        select(func.sum(TipTransactionORM.amount)).where(
            TipTransactionORM.created_at >= today_start,
            TipTransactionORM.status == "confirmed",
        )
    )
    tipped_today_usd = float(today_row.scalar() or 0.0)

    today_count_row = await db.execute(
        select(func.count(TipTransactionORM.id)).where(
            TipTransactionORM.created_at >= today_start,
            TipTransactionORM.status == "confirmed",
        )
    )
    tips_today_count = int(today_count_row.scalar() or 0)

    # Total tipped this week
    week_row = await db.execute(
        select(func.sum(TipTransactionORM.amount)).where(
            TipTransactionORM.created_at >= week_start,
            TipTransactionORM.status == "confirmed",
        )
    )
    tipped_week_usd = float(week_row.scalar() or 0.0)

    week_count_row = await db.execute(
        select(func.count(TipTransactionORM.id)).where(
            TipTransactionORM.created_at >= week_start,
            TipTransactionORM.status == "confirmed",
        )
    )
    tips_week_count = int(week_count_row.scalar() or 0)

    # Top creators tipped (by total amount, all time)
    top_creators_rows = await db.execute(
        select(
            TipTransactionORM.creator_id,
            func.sum(TipTransactionORM.amount).label("total_usd"),
            func.count(TipTransactionORM.id).label("tip_count"),
        )
        .where(TipTransactionORM.status == "confirmed")
        .group_by(TipTransactionORM.creator_id)
        .order_by(desc("total_usd"))
        .limit(10)
    )
    top_creators = [
        {
            "creator_id": row.creator_id,
            "total_usd":  round(float(row.total_usd), 2),
            "tip_count":  row.tip_count,
        }
        for row in top_creators_rows.fetchall()
    ]

    # Active swarms count
    active_swarms_row = await db.execute(
        select(func.count(SwarmGoalORM.swarm_id)).where(
            SwarmGoalORM.status == "ACTIVE"
        )
    )
    active_swarms_count = int(active_swarms_row.scalar() or 0)

    return {
        "today": {
            "total_usd":  round(tipped_today_usd, 2),
            "tip_count":  tips_today_count,
        },
        "this_week": {
            "total_usd":  round(tipped_week_usd, 2),
            "tip_count":  tips_week_count,
        },
        "top_creators":        top_creators,
        "active_swarms_count": active_swarms_count,
        "generated_at":        now.isoformat(),
    }


# ---------------------------------------------------------------------------
# Event injection shortcuts
# ---------------------------------------------------------------------------

@router.post("/events/inject")
async def inject_event(body: InjectEventRequest):
    """Push any event into the event bus."""
    try:
        await orchestrator.inject_event(body.event_type, body.payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "event_type": body.event_type}


@router.post("/events/watch")
async def inject_watch_event(body: WatchEventRequest):
    """Shorthand: inject a WATCH_TIME_UPDATE event."""
    await orchestrator.inject_event(EventType.WATCH_TIME_UPDATE, body.model_dump())
    return {"ok": True}


@router.post("/events/chat")
async def inject_chat_event(body: ChatMessageRequest):
    """Shorthand: inject a CHAT_MESSAGE event."""
    await orchestrator.inject_event(EventType.CHAT_MESSAGE, body.model_dump())
    return {"ok": True}


@router.post("/events/milestone")
async def inject_milestone_event(body: MilestoneRequest):
    """Shorthand: inject a MILESTONE_REACHED event."""
    await orchestrator.inject_event(EventType.MILESTONE_REACHED, body.model_dump())
    return {"ok": True}


# ---------------------------------------------------------------------------
# Wallet
# ---------------------------------------------------------------------------

@router.get("/wallet/balance")
async def get_wallet_balance():
    """Get the current TipMind wallet balance."""
    try:
        balance = await _wallet.get_balance()
        address = await _wallet.get_wallet_address()
        return {"balance": balance, "address": address, "token": "USDT"}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Wallet unavailable: {exc}")
