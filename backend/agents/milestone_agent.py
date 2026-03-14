"""
Milestone Agent — checks if a creator has reached tipping-worthy milestones.
Milestones trigger bonus tips regardless of content emotion score.
"""
import anthropic
from loguru import logger
from backend.config import config

MILESTONES = [
    {"type": "views_10k", "threshold": 10_000, "bonus": 0.50},
    {"type": "views_100k", "threshold": 100_000, "bonus": 1.00},
    {"type": "views_1m", "threshold": 1_000_000, "bonus": 2.00},
    {"type": "likes_1k", "threshold": 1_000, "bonus": 0.25},
    {"type": "likes_10k", "threshold": 10_000, "bonus": 0.75},
]


class MilestoneAgent:
    """
    Evaluates creator milestones and determines bonus tip amounts.
    Uses Claude to reason about whether a milestone is genuinely meaningful.
    """

    SYSTEM_PROMPT = """You are a creator economy analyst specializing in content milestones.
Given a creator's stats and their milestone history, determine:
1. Which milestones have been newly achieved (not previously rewarded)
2. The total bonus tip amount warranted

Respond with JSON:
{
  "new_milestones": [{"type": "...", "threshold": N, "bonus": X.XX}],
  "total_bonus": X.XX,
  "milestone_triggered": true/false,
  "reasoning": "..."
}

Only include milestones that are genuinely new achievements. Respond ONLY with valid JSON."""

    def __init__(self):
        self._client = anthropic.AsyncAnthropic(api_key=config.anthropic_api_key)

    async def evaluate(
        self,
        video_metadata: dict,
        previously_rewarded: list[str],
    ) -> dict:
        """
        Evaluate milestone achievements for a creator.

        Args:
            video_metadata: Current video stats
            previously_rewarded: List of milestone types already rewarded for this creator

        Returns:
            dict with new_milestones, total_bonus, milestone_triggered, reasoning
        """
        view_count = video_metadata.get("view_count", 0)
        like_count = video_metadata.get("like_count", 0)

        # Determine which milestones could be newly achieved
        candidate_milestones = [
            m for m in MILESTONES
            if m["type"] not in previously_rewarded
            and (
                ("views" in m["type"] and view_count >= m["threshold"])
                or ("likes" in m["type"] and like_count >= m["threshold"])
            )
        ]

        if not candidate_milestones:
            return {
                "new_milestones": [],
                "total_bonus": 0.0,
                "milestone_triggered": False,
                "reasoning": "No new milestones achieved.",
            }

        user_message = f"""Creator stats:
- Video: {video_metadata.get('title', 'Unknown')}
- Views: {view_count:,}
- Likes: {like_count:,}
- Previously rewarded milestones: {previously_rewarded}

Candidate new milestones:
{candidate_milestones}

Determine which milestones are genuine new achievements and calculate the bonus."""

        logger.info(f"MilestoneAgent evaluating {len(candidate_milestones)} candidates")

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
        logger.info(f"MilestoneAgent: triggered={result.get('milestone_triggered')}, bonus={result.get('total_bonus', 0)}")
        return result
