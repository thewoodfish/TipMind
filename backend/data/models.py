"""
TipMind data models.

Pydantic models: used for validation, API I/O, and agent communication.
SQLAlchemy models: persisted tables (tip_transactions, swarm_goals, etc.)
"""
from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase


# ---------------------------------------------------------------------------
# SQLAlchemy base
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Pydantic enums
# ---------------------------------------------------------------------------

class MilestoneType(str, enum.Enum):
    LIKES_10K = "LIKES_10K"
    VIEWS_100K = "VIEWS_100K"
    SUBS_MILESTONE = "SUBS_MILESTONE"
    DEBATE_WIN = "DEBATE_WIN"
    CUSTOM = "CUSTOM"


class SwarmStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    TRIGGERED = "TRIGGERED"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"


# ---------------------------------------------------------------------------
# Pydantic models  (validation / agent I/O)
# ---------------------------------------------------------------------------

class VideoEvent(BaseModel):
    """Fired when a new video is published or ingested into TipMind."""
    video_id: str
    creator_id: str
    creator_name: str
    title: str
    duration_seconds: int
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class WatchEvent(BaseModel):
    """Emitted as a user watches a video — drives engagement scoring."""
    user_id: str
    video_id: str
    watch_seconds: int
    total_duration: int
    percentage_watched: float = Field(ge=0.0, le=100.0)


class ChatMessage(BaseModel):
    """A live-chat message sent during a stream."""
    user_id: str
    video_id: str
    message: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    sentiment_score: Optional[float] = Field(default=None, ge=-1.0, le=1.0)


class MilestoneEvent(BaseModel):
    """Signals that a creator has crossed a notable threshold."""
    creator_id: str
    milestone_type: MilestoneType
    value: int  # The actual metric value at the time of milestone
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class SwarmGoal(BaseModel):
    """A collective tipping goal that multiple users contribute to."""
    swarm_id: str
    creator_id: str
    goal_description: str
    trigger_event: str  # e.g. "DEBATE_WIN", "VIEWS_100K"
    target_amount_usd: float = Field(gt=0)
    current_amount_usd: float = Field(default=0.0, ge=0)
    participant_count: int = Field(default=0, ge=0)
    status: SwarmStatus = SwarmStatus.ACTIVE


class TipDecision(BaseModel):
    """Output of an AI agent deciding whether/how much to tip."""
    agent_type: str  # e.g. "EmotionAgent", "MilestoneAgent", "SwarmAgent"
    trigger: str     # event or rule that caused the decision
    amount_usd: float = Field(ge=0.0)
    token: str = "USDT"
    creator_id: str
    reasoning: str
    confidence_score: float = Field(ge=0.0, le=1.0)


class TipTransaction(BaseModel):
    """Represents a completed (or attempted) on-chain tip payment."""
    tx_hash: Optional[str] = None
    from_wallet: str
    to_wallet: str
    amount: float = Field(gt=0)
    token: str = "USDT"
    creator_id: str
    trigger_type: str  # e.g. "MILESTONE", "EMOTION", "SWARM"
    status: str = "pending"  # pending | confirmed | failed
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# SQLAlchemy ORM tables
# ---------------------------------------------------------------------------

class TipTransactionORM(Base):
    __tablename__ = "tip_transactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tx_hash = Column(String, nullable=True, index=True)
    from_wallet = Column(String, nullable=False)
    to_wallet = Column(String, nullable=False)
    amount = Column(Float, nullable=False)
    token = Column(String, nullable=False, default="USDT")
    creator_id = Column(String, nullable=False, index=True)
    trigger_type = Column(String, nullable=False)
    status = Column(String, nullable=False, default="pending")
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)


class SwarmGoalORM(Base):
    __tablename__ = "swarm_goals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    swarm_id = Column(String, nullable=False, unique=True, index=True)
    creator_id = Column(String, nullable=False, index=True)
    goal_description = Column(Text, nullable=False)
    trigger_event = Column(String, nullable=False)
    target_amount_usd = Column(Float, nullable=False)
    current_amount_usd = Column(Float, nullable=False, default=0.0)
    participant_count = Column(Integer, nullable=False, default=0)
    status = Column(String, nullable=False, default=SwarmStatus.ACTIVE.value)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SwarmParticipantORM(Base):
    __tablename__ = "swarm_participants"

    id = Column(Integer, primary_key=True, autoincrement=True)
    swarm_id = Column(String, ForeignKey("swarm_goals.swarm_id"), nullable=False, index=True)
    user_id = Column(String, nullable=False)
    committed_amount_usd = Column(Float, nullable=False, default=0.0)
    joined_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class AgentDecisionLogORM(Base):
    __tablename__ = "agent_decisions_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_type = Column(String, nullable=False)
    trigger = Column(String, nullable=False)
    creator_id = Column(String, nullable=False, index=True)
    amount_usd = Column(Float, nullable=False)
    token = Column(String, nullable=False, default="USDT")
    reasoning = Column(Text, nullable=True)
    confidence_score = Column(Float, nullable=True)
    tip_tx_id = Column(Integer, ForeignKey("tip_transactions.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class UserPreferenceORM(Base):
    __tablename__ = "user_preferences"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, nullable=False, unique=True, index=True)
    auto_tip_enabled = Column(Boolean, nullable=False, default=True)
    max_tip_per_video_usd = Column(Float, nullable=False, default=1.00)
    preferred_token = Column(String, nullable=False, default="USDT")
    wallet_address = Column(String, nullable=True)
    tip_on_milestone = Column(Boolean, nullable=False, default=True)
    tip_on_emotion = Column(Boolean, nullable=False, default=True)
    tip_on_swarm = Column(Boolean, nullable=False, default=True)
    min_confidence_threshold = Column(Float, nullable=False, default=0.6)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
