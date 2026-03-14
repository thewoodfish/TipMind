"""
Orchestrator — coordinates the full tip lifecycle:
analyze → decide → send → record → confirm
"""
import json
import uuid
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.agents.swarm_agent import SwarmAgent
from backend.core.wallet import wallet
from backend.core.event_bus import event_bus, EventType
from backend.core.swarm_pool import swarm_pool, SwarmTask
from backend.data.models import (
    TipTransactionORM,
    AgentDecisionLogORM,
)


class Orchestrator:
    def __init__(self):
        self.swarm = SwarmAgent()

    async def process_video(self, video_metadata: dict, db: AsyncSession) -> dict:
        """
        Full pipeline for a single video:
        1. Run SwarmAgent (emotion + milestone + tip agents)
        2. If tip decided, send via WDK wallet
        3. Persist TipTransactionORM and AgentDecisionLogORM records

        Args:
            video_metadata: dict with id, title, creator_id, creator_address, view_count, like_count, etc.
            db: Async SQLAlchemy session

        Returns:
            Full pipeline result dict
        """
        video_id = video_metadata.get("id", str(uuid.uuid4()))
        creator_id = video_metadata.get("creator_id", video_metadata.get("creator_address", ""))
        creator_address = video_metadata.get("creator_address", creator_id)

        # Fetch previously rewarded milestone types for this creator
        stmt = select(AgentDecisionLogORM.trigger).where(
            AgentDecisionLogORM.creator_id == creator_id,
            AgentDecisionLogORM.trigger.like("MILESTONE:%"),
        )
        rows = await db.execute(stmt)
        previously_rewarded = [r[0].replace("MILESTONE:", "") for r in rows.fetchall()]

        # Create and run swarm task under concurrency control
        task = SwarmTask(
            task_id=str(uuid.uuid4()),
            video_id=video_id,
            payload=video_metadata,
        )

        async def _run():
            return await self.swarm.analyze_and_decide(video_metadata, previously_rewarded)

        task = await swarm_pool.run(task, _run())
        if task.status == "failed":
            logger.error(f"Swarm failed for {video_id}: {task.error}")
            return {"error": task.error, "video_id": video_id}

        swarm_result = task.result
        tip_decision = swarm_result["tip_decision"]
        milestone_result = swarm_result["milestone_result"]
        emotion_result = swarm_result["emotion_result"]

        # Log all agent decisions
        await self._log_agents(db, video_id, creator_id, swarm_result)

        tip_tx = TipTransactionORM(
            from_wallet=video_metadata.get("from_wallet", "tipmind_vault"),
            to_wallet=creator_address,
            amount=tip_decision.get("amount", 0),
            token=tip_decision.get("token", "USDT"),
            creator_id=creator_id,
            trigger_type="SWARM",
            status="skipped",
        )

        if tip_decision.get("should_tip") and tip_decision.get("amount", 0) > 0:
            tip_tx.status = "pending"
            db.add(tip_tx)
            await db.flush()

            try:
                tx = await wallet.send_tip(
                    to_address=creator_address,
                    amount=tip_decision["amount"],
                    token=tip_decision.get("token", "USDT"),
                )
                tip_tx.tx_hash = tx.tx_hash
                tip_tx.status = tx.status
            except Exception as exc:
                tip_tx.status = "failed"
                logger.error(f"Wallet send failed for {video_id}: {exc}")
                await event_bus.publish(EventType.TIP_EXECUTED, {
                    "video_id": video_id,
                    "error": str(exc),
                    "status": "failed",
                })
        else:
            db.add(tip_tx)

        await db.commit()

        return {
            "video_id": video_id,
            "tip_tx_id": tip_tx.id,
            "tip_decision": tip_decision,
            "emotion_result": emotion_result,
            "milestone_result": milestone_result,
            "tx_hash": tip_tx.tx_hash,
            "status": tip_tx.status,
        }

    async def _log_agents(
        self, db: AsyncSession, video_id: str, creator_id: str, swarm_result: dict
    ) -> None:
        entries = [
            ("EmotionAgent",   "EMOTION",    swarm_result.get("emotion_result")),
            ("MilestoneAgent", "MILESTONE",  swarm_result.get("milestone_result")),
            ("TipAgent",       "SWARM",      swarm_result.get("tip_decision")),
        ]
        for agent_type, trigger, output in entries:
            decision = swarm_result.get("tip_decision", {})
            db.add(AgentDecisionLogORM(
                agent_type=agent_type,
                trigger=trigger,
                creator_id=creator_id,
                amount_usd=decision.get("amount", 0) if agent_type == "TipAgent" else 0,
                reasoning=json.dumps(output, default=str)[:500] if output else None,
                confidence_score=decision.get("confidence_score") if agent_type == "TipAgent" else None,
            ))


orchestrator = Orchestrator()
