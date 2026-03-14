"""
Tip Agent — makes the final tipping decision by synthesizing inputs from other agents.
Determines whether to tip, the exact amount, and the reason.
"""
import anthropic
from loguru import logger
from backend.config import config


class TipAgent:
    """
    The final decision-maker in the tipping swarm.
    Synthesizes emotion score + milestone data into a concrete tip decision.
    """

    SYSTEM_PROMPT = """You are TipMind's final decision agent for crypto tipping.

You receive:
- Emotional resonance score (0.0-1.0) from the EmotionAgent
- Milestone bonus data from the MilestoneAgent
- Video metadata

Your job: make the final tip decision.

Rules:
- Only tip if emotion score >= 0.4 OR milestone_triggered is true
- Base tip = emotion_score * max_tip_per_video (rounded to 2dp)
- Total tip = base_tip + milestone_bonus (capped at max_tip_per_video)
- If no tip warranted, set should_tip=false and amount=0

Respond with JSON:
{
  "should_tip": true/false,
  "amount": X.XX,
  "reason": "short human-readable reason for this tip",
  "confidence": 0.0-1.0
}

Respond ONLY with valid JSON."""

    def __init__(self):
        self._client = anthropic.AsyncAnthropic(api_key=config.anthropic_api_key)

    async def decide(
        self,
        video_metadata: dict,
        emotion_result: dict,
        milestone_result: dict,
    ) -> dict:
        """
        Make the final tip decision.

        Args:
            video_metadata: Video info
            emotion_result: Output from EmotionAgent.analyze()
            milestone_result: Output from MilestoneAgent.evaluate()

        Returns:
            dict with should_tip, amount, reason, confidence
        """
        user_message = f"""Make a tip decision for this video:

Video: {video_metadata.get('title', 'Unknown')}
Creator: {video_metadata.get('creator_address', 'unknown')}

EmotionAgent report:
- Score: {emotion_result.get('score', 0)}
- Sentiment: {emotion_result.get('sentiment', 'neutral')}
- Key emotions: {emotion_result.get('key_emotions', [])}
- Reasoning: {emotion_result.get('reasoning', '')}

MilestoneAgent report:
- Milestone triggered: {milestone_result.get('milestone_triggered', False)}
- New milestones: {milestone_result.get('new_milestones', [])}
- Milestone bonus: {milestone_result.get('total_bonus', 0)}
- Reasoning: {milestone_result.get('reasoning', '')}

Max tip per video: {config.max_tip_per_video} {config.default_token}

Make your final tip decision."""

        logger.info(f"TipAgent deciding for: {video_metadata.get('title', 'unknown')}")

        async with self._client.messages.stream(
            model="claude-opus-4-6",
            max_tokens=512,
            thinking={"type": "adaptive"},
            system=self.SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        ) as stream:
            response = await stream.get_final_message()

        import json
        text = next(
            (b.text for b in response.content if b.type == "text"), "{}"
        )
        result = json.loads(text)

        # Safety cap
        if result.get("should_tip") and result.get("amount", 0) > config.max_tip_per_video:
            result["amount"] = config.max_tip_per_video

        logger.info(
            f"TipAgent decision: should_tip={result.get('should_tip')}, "
            f"amount={result.get('amount')}"
        )
        return result
