"""
Orchestrator — coordinates the full tip lifecycle:
analyze → decide → send → record → confirm
"""
import uuid
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.agents.swarm_agent import SwarmAgent
from backend.core.wallet import wallet_client
from backend.core.event_bus import event_bus, Events
from backend.core.swarm_pool import swarm_pool, SwarmTask
from backend.data.models import TipEvent, CreatorMilestone, AgentLog


class Orchestrator:
    def __init__(self):
        self.swarm = SwarmAgent()

    async def process_video(self, video_metadata: dict, db: AsyncSession) -> dict:
        """
        Full pipeline for a single video:
        1. Fetch previously rewarded milestones for the creator
        2. Run SwarmAgent
        3. If tip decided, send via WDK
        4. Persist TipEvent and milestone records

        Args:
            video_metadata: dict with id, title, creator_address, view_count, like_count, etc.
            db: Async SQLAlchemy session

        Returns:
            Full pipeline result dict
        """
        video_id = video_metadata.get("id", str(uuid.uuid4()))
        creator_address = video_metadata.get("creator_address", "")

        # Fetch previously rewarded milestones
        stmt = select(CreatorMilestone.milestone_type).where(
            CreatorMilestone.creator_address == creator_address,
            CreatorMilestone.rewarded == True,
        )
        rows = await db.execute(stmt)
        previously_rewarded = [r[0] for r in rows.fetchall()]

        # Create swarm task
        task = SwarmTask(
            task_id=str(uuid.uuid4()),
            video_id=video_id,
            payload=video_metadata,
        )

        # Run swarm under concurrency control
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

        # Log agent outputs
        await self._log_agents(db, video_id, swarm_result)

        tip_event = TipEvent(
            video_id=video_id,
            creator_address=creator_address,
            amount=tip_decision.get("amount", 0),
            reason=tip_decision.get("reason"),
            emotion_score=emotion_result.get("score"),
            milestone_triggered=milestone_result.get("milestone_triggered", False),
            status="skipped",
        )

        if tip_decision.get("should_tip") and tip_decision.get("amount", 0) > 0:
            tip_event.status = "pending"
            db.add(tip_event)
            await db.flush()  # get the id

            try:
                tx = await wallet_client.send_tip(
                    recipient_address=creator_address,
                    amount=tip_decision["amount"],
                    memo=tip_decision.get("reason", "TipMind tip"),
                )
                tip_event.tx_hash = tx.get("tx_hash")
                tip_event.status = "confirmed"
                await event_bus.publish(Events.TIP_SENT, {
                    "video_id": video_id,
                    "amount": tip_event.amount,
                    "tx_hash": tip_event.tx_hash,
                })
            except Exception as exc:
                tip_event.status = "failed"
                logger.error(f"Wallet send failed for {video_id}: {exc}")
                await event_bus.publish(Events.TIP_FAILED, {"video_id": video_id, "error": str(exc)})
        else:
            db.add(tip_event)

        # Record new milestones
        for milestone in milestone_result.get("new_milestones", []):
            db.add(CreatorMilestone(
                creator_address=creator_address,
                milestone_type=milestone["type"],
                threshold=milestone["threshold"],
                rewarded=True,
            ))

        await db.commit()

        return {
            "video_id": video_id,
            "tip_event_id": tip_event.id,
            "tip_decision": tip_decision,
            "emotion_result": emotion_result,
            "milestone_result": milestone_result,
            "tx_hash": tip_event.tx_hash,
            "status": tip_event.status,
        }

    async def _log_agents(self, db: AsyncSession, video_id: str, swarm_result: dict) -> None:
        agents = [
            ("EmotionAgent", swarm_result.get("emotion_result")),
            ("MilestoneAgent", swarm_result.get("milestone_result")),
            ("TipAgent", swarm_result.get("tip_decision")),
        ]
        import json
        for name, output in agents:
            db.add(AgentLog(
                agent_name=name,
                video_id=video_id,
                output_summary=json.dumps(output, default=str)[:500] if output else None,
            ))


orchestrator = Orchestrator()
