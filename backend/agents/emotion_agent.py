"""
Emotion Agent — analyzes video metadata/description to produce an emotional resonance score.
Uses Claude with adaptive thinking for nuanced sentiment analysis.
"""
import anthropic
from loguru import logger
from backend.config import config


class EmotionAgent:
    """
    Analyzes video content for emotional impact.
    Returns a score from 0.0 (neutral/negative) to 1.0 (highly positive/impactful).
    """

    SYSTEM_PROMPT = """You are an expert in emotional intelligence and content analysis.
Given metadata about a video (title, description, tags, engagement stats), you analyze
the emotional resonance and quality of the content.

You output a JSON object with:
- score: float 0.0-1.0 (emotional resonance — higher means more worthy of a tip)
- sentiment: one of "positive", "neutral", "negative"
- key_emotions: list of dominant emotions detected (e.g., ["inspiring", "educational", "joyful"])
- reasoning: brief explanation of your assessment

Respond ONLY with valid JSON, no markdown fences."""

    def __init__(self):
        self._client = anthropic.AsyncAnthropic(api_key=config.anthropic_api_key)

    async def analyze(self, video_metadata: dict) -> dict:
        """
        Analyze video metadata for emotional content.

        Args:
            video_metadata: dict with keys: title, description, tags, view_count, like_count

        Returns:
            dict with score, sentiment, key_emotions, reasoning
        """
        user_message = f"""Analyze the emotional resonance of this video:

Title: {video_metadata.get('title', 'Unknown')}
Description: {video_metadata.get('description', 'N/A')}
Tags: {', '.join(video_metadata.get('tags', []))}
Views: {video_metadata.get('view_count', 0):,}
Likes: {video_metadata.get('like_count', 0):,}

Provide your emotional analysis as JSON."""

        logger.info(f"EmotionAgent analyzing: {video_metadata.get('title', 'unknown')}")

        async with self._client.messages.stream(
            model="claude-opus-4-6",
            max_tokens=1024,
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
        logger.info(f"EmotionAgent score: {result.get('score', 0)}")
        return result
