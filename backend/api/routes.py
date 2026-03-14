from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from loguru import logger

from backend.data.database import get_db
from backend.data.models import TipEvent, Video, CreatorMilestone
from backend.core.orchestrator import orchestrator
from backend.core.wallet import wallet_client

router = APIRouter()


# --- Request / Response schemas ---

class VideoAnalyzeRequest(BaseModel):
    id: str
    title: str
    creator_address: str
    url: str
    description: str = ""
    tags: list[str] = []
    view_count: int = 0
    like_count: int = 0


class TipEventResponse(BaseModel):
    id: int
    video_id: str
    creator_address: str
    amount: float
    token: str
    tx_hash: str | None
    reason: str | None
    emotion_score: float | None
    milestone_triggered: bool
    status: str
    created_at: str


# --- Routes ---

@router.post("/videos/analyze")
async def analyze_video(
    body: VideoAnalyzeRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Analyze a video with the AI swarm and decide/send a tip.
    This is the main endpoint that triggers the full pipeline.
    """
    logger.info(f"Received analyze request for video: {body.id}")

    # Upsert video record
    existing = await db.get(Video, body.id)
    if not existing:
        db.add(Video(
            id=body.id,
            title=body.title,
            creator_address=body.creator_address,
            url=body.url,
            view_count=body.view_count,
            like_count=body.like_count,
        ))
        await db.flush()

    result = await orchestrator.process_video(body.model_dump(), db)

    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])

    return result


@router.get("/tips", response_model=list[TipEventResponse])
async def list_tips(
    limit: int = 20,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """List recent tip events."""
    stmt = select(TipEvent).order_by(desc(TipEvent.created_at)).limit(limit).offset(offset)
    rows = await db.execute(stmt)
    tips = rows.scalars().all()
    return [
        TipEventResponse(
            id=t.id,
            video_id=t.video_id,
            creator_address=t.creator_address,
            amount=t.amount,
            token=t.token,
            tx_hash=t.tx_hash,
            reason=t.reason,
            emotion_score=t.emotion_score,
            milestone_triggered=t.milestone_triggered,
            status=t.status,
            created_at=t.created_at.isoformat(),
        )
        for t in tips
    ]


@router.get("/tips/{tip_id}", response_model=TipEventResponse)
async def get_tip(tip_id: int, db: AsyncSession = Depends(get_db)):
    """Get a specific tip event by ID."""
    tip = await db.get(TipEvent, tip_id)
    if not tip:
        raise HTTPException(status_code=404, detail="Tip not found")
    return TipEventResponse(
        id=tip.id,
        video_id=tip.video_id,
        creator_address=tip.creator_address,
        amount=tip.amount,
        token=tip.token,
        tx_hash=tip.tx_hash,
        reason=tip.reason,
        emotion_score=tip.emotion_score,
        milestone_triggered=tip.milestone_triggered,
        status=tip.status,
        created_at=tip.created_at.isoformat(),
    )


@router.get("/wallet/balance")
async def get_wallet_balance():
    """Get the current TipMind wallet balance."""
    try:
        balance = await wallet_client.get_balance()
        return balance
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Wallet unavailable: {exc}")


@router.get("/milestones/{creator_address}")
async def get_creator_milestones(
    creator_address: str,
    db: AsyncSession = Depends(get_db),
):
    """Get all rewarded milestones for a creator."""
    stmt = select(CreatorMilestone).where(
        CreatorMilestone.creator_address == creator_address
    ).order_by(desc(CreatorMilestone.achieved_at))
    rows = await db.execute(stmt)
    milestones = rows.scalars().all()
    return [
        {
            "id": m.id,
            "milestone_type": m.milestone_type,
            "threshold": m.threshold,
            "achieved_at": m.achieved_at.isoformat(),
            "rewarded": m.rewarded,
        }
        for m in milestones
    ]


@router.get("/health")
async def health():
    return {"status": "ok"}
