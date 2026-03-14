"""
Swarm Agent — orchestrates EmotionAgent, MilestoneAgent, and TipAgent in parallel.
This is the top-level entry point for analyzing a video and deciding on a tip.
"""
import asyncio
from loguru import logger

from backend.agents.emotion_agent import EmotionAgent
from backend.agents.milestone_agent import MilestoneAgent
from backend.agents.tip_agent import TipAgent
from backend.core.event_bus import event_bus, EventType


class SwarmAgent:
    """
    Coordinates the multi-agent tipping pipeline:

    1. EmotionAgent + MilestoneAgent run in parallel
    2. TipAgent synthesizes their outputs into a final decision
    3. Events are published throughout for real-time UI updates
    """

    def __init__(self):
        self.emotion_agent = EmotionAgent()
        self.milestone_agent = MilestoneAgent()
        self.tip_agent = TipAgent()

    async def analyze_and_decide(
        self,
        video_metadata: dict,
        previously_rewarded_milestones: list[str] | None = None,
    ) -> dict:
        """
        Full pipeline: analyze video → decide tip.

        Args:
            video_metadata: dict with title, description, creator_address, view_count, like_count, etc.
            previously_rewarded_milestones: Milestone types already rewarded for this creator

        Returns:
            dict with tip_decision, emotion_result, milestone_result
        """
        previously_rewarded = previously_rewarded_milestones or []
        video_id = video_metadata.get("id", "unknown")

        await event_bus.publish(EventType.SWARM_TRIGGERED, {"video_id": video_id})
        logger.info(f"SwarmAgent starting analysis for video: {video_id}")

        # Phase 1: Run emotion and milestone agents in parallel
        emotion_task = asyncio.create_task(
            self.emotion_agent.analyze(video_metadata)
        )
        milestone_task = asyncio.create_task(
            self.milestone_agent.evaluate(video_metadata, previously_rewarded)
        )

        emotion_result, milestone_result = await asyncio.gather(
            emotion_task, milestone_task
        )

        await event_bus.publish(EventType.AGENT_DECISION, {
            "video_id": video_id,
            "score": emotion_result.get("score"),
        })

        if milestone_result.get("milestone_triggered"):
            await event_bus.publish(EventType.MILESTONE_REACHED, {
                "video_id": video_id,
                "milestones": milestone_result.get("new_milestones", []),
            })

        # Phase 2: TipAgent makes final decision
        tip_decision = await self.tip_agent.decide(
            video_metadata, emotion_result, milestone_result
        )

        await event_bus.publish(EventType.AGENT_DECISION, {
            "video_id": video_id,
            "decision": tip_decision,
        })

        result = {
            "video_id": video_id,
            "tip_decision": tip_decision,
            "emotion_result": emotion_result,
            "milestone_result": milestone_result,
        }

        await event_bus.publish(EventType.TIP_EXECUTED, {
            "video_id": video_id,
            "should_tip": tip_decision.get("should_tip"),
        })

        logger.info(
            f"SwarmAgent completed for {video_id}: "
            f"should_tip={tip_decision.get('should_tip')}, "
            f"amount={tip_decision.get('amount')}"
        )
        return result
