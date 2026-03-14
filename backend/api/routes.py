from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from backend.core.event_bus import EventType
from backend.core.orchestrator import orchestrator
from backend.core.swarm_pool import swarm_pool
from backend.core.wallet import WalletFactory
from backend.data.database import get_db
from backend.data.models import AgentDecisionLogORM, TipTransactionORM

router = APIRouter()
_wallet = WalletFactory.create()


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class InjectEventRequest(BaseModel):
    event_type: str
    payload: dict[str, Any] = {}


class DemoScenarioRequest(BaseModel):
    scenario: str   # 'watch' | 'hype' | 'milestone' | 'swarm'


class PreferenceRequest(BaseModel):
    key: str
    value: Any


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
# Orchestrator / System routes
# ---------------------------------------------------------------------------

@router.get("/status")
async def system_status():
    """Full system snapshot: agent states, wallet, active swarms, tips today."""
    return await orchestrator.get_system_status()


@router.post("/events/inject")
async def inject_event(body: InjectEventRequest):
    """Push any event into the event bus (for API & demo use)."""
    try:
        await orchestrator.inject_event(body.event_type, body.payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "event_type": body.event_type}


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


@router.get("/preferences")
async def get_preferences():
    """Get current user preferences."""
    return orchestrator.get_user_preferences()


@router.post("/preferences")
async def set_preference(body: PreferenceRequest):
    """Update a single user preference."""
    orchestrator.set_user_preference(body.key, body.value)
    return {"ok": True, "key": body.key, "value": body.value}


# ---------------------------------------------------------------------------
# Event injection shortcuts
# ---------------------------------------------------------------------------

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
# Tips history
# ---------------------------------------------------------------------------

@router.get("/tips")
async def list_tips(
    limit: int = 20,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """List recent tip transactions."""
    stmt = (
        select(TipTransactionORM)
        .order_by(desc(TipTransactionORM.created_at))
        .limit(limit)
        .offset(offset)
    )
    rows = await db.execute(stmt)
    tips = rows.scalars().all()
    return [
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
    ]


@router.get("/tips/{tip_id}")
async def get_tip(tip_id: int, db: AsyncSession = Depends(get_db)):
    tip = await db.get(TipTransactionORM, tip_id)
    if not tip:
        raise HTTPException(status_code=404, detail="Tip not found")
    return {
        "id":           tip.id,
        "tx_hash":      tip.tx_hash,
        "from_wallet":  tip.from_wallet,
        "to_wallet":    tip.to_wallet,
        "amount":       tip.amount,
        "token":        tip.token,
        "creator_id":   tip.creator_id,
        "trigger_type": tip.trigger_type,
        "status":       tip.status,
        "created_at":   tip.created_at.isoformat() if tip.created_at else None,
    }


# ---------------------------------------------------------------------------
# Swarms
# ---------------------------------------------------------------------------

@router.get("/swarms")
async def list_active_swarms(db: AsyncSession = Depends(get_db)):
    """List all currently active swarm goals."""
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
        }
        for g in goals
    ]


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


# ---------------------------------------------------------------------------
# Agent decision log
# ---------------------------------------------------------------------------

@router.get("/decisions")
async def list_decisions(
    limit: int = 20,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """List recent agent decisions."""
    stmt = (
        select(AgentDecisionLogORM)
        .order_by(desc(AgentDecisionLogORM.created_at))
        .limit(limit)
        .offset(offset)
    )
    rows = await db.execute(stmt)
    decisions = rows.scalars().all()
    return [
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
    ]


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@router.get("/health")
async def health():
    return {"status": "ok"}
