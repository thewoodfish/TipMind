"""
backend/core/youtube_client.py — YouTube Data API v3 Client

Fetches real video statistics (views, likes, duration) and computes a
genuine engagement score to replace the random watch-percentage simulation.

Engagement score formula:
  - Like/view ratio is the primary signal (YouTube average ≈ 2-4%)
  - View velocity (views per day since publish) adds momentum weight
  - Mapped to 0–100 scale so it slots into the existing WatchTimeTipAgent pipeline

Falls back to a conservative fixed score if no API key is configured.

API quota cost: 1 unit per videos.list call (free quota: 10,000/day).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

import httpx
from loguru import logger


YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"


class YouTubeDataClient:
    """
    Thin async wrapper around YouTube Data API v3.
    Use get_video_stats() to fetch real engagement data for a video.
    """

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def get_video_stats(self, video_id: str) -> dict[str, Any] | None:
        """
        Fetch statistics + contentDetails for a video.

        Returns a dict with:
          view_count, like_count, duration_seconds,
          days_since_publish, engagement_score (0–100)

        Returns None if the request fails or video isn't found.
        """
        url = f"{YOUTUBE_API_BASE}/videos"
        params = {
            "part": "statistics,contentDetails,snippet",
            "id": video_id,
            "key": self._api_key,
        }

        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            logger.warning(f"[YOUTUBE CLIENT] API request failed for {video_id}: {exc}")
            return None

        items = data.get("items", [])
        if not items:
            logger.debug(f"[YOUTUBE CLIENT] No data returned for video {video_id}")
            return None

        item = items[0]
        stats   = item.get("statistics", {})
        details = item.get("contentDetails", {})
        snippet = item.get("snippet", {})

        view_count = int(stats.get("viewCount", 0))
        like_count = int(stats.get("likeCount", 0))
        duration_seconds = _parse_iso8601_duration(details.get("duration", "PT0S"))

        published_at_str = snippet.get("publishedAt", "")
        days_since_publish = _days_since(published_at_str)

        engagement_score = _compute_engagement_score(
            view_count=view_count,
            like_count=like_count,
            days_since_publish=days_since_publish,
        )

        result = {
            "video_id":           video_id,
            "view_count":         view_count,
            "like_count":         like_count,
            "duration_seconds":   duration_seconds,
            "days_since_publish": days_since_publish,
            "engagement_score":   engagement_score,
        }

        logger.info(
            f"[YOUTUBE CLIENT] {video_id} — "
            f"views={view_count:,} likes={like_count:,} "
            f"like_ratio={like_count/max(view_count,1)*100:.2f}% "
            f"engagement_score={engagement_score}"
        )
        return result


# ---------------------------------------------------------------------------
# Engagement score computation
# ---------------------------------------------------------------------------

def _compute_engagement_score(
    view_count: int,
    like_count: int,
    days_since_publish: float,
) -> float:
    """
    Maps real YouTube statistics to a 0–100 engagement score.

    Like/view ratio benchmarks (YouTube averages):
      < 1%  → weak engagement   → score 20–35
      1–3%  → average           → score 35–60
      3–5%  → strong            → score 60–80
      5%+   → exceptional       → score 80–95

    View velocity adds up to +10 bonus points for fast-growing content.
    Minimum score is 20 (video exists = some interest).
    """
    if view_count == 0:
        return 20.0

    like_ratio = like_count / view_count  # 0.0 – 1.0

    # Base score from like ratio: maps [0, 0.06] → [20, 92]
    base = 20.0 + min(like_ratio / 0.06 * 72.0, 72.0)

    # View velocity bonus: >10K views/day = +8 pts
    if days_since_publish > 0:
        views_per_day = view_count / days_since_publish
        velocity_bonus = min(views_per_day / 10_000 * 8.0, 8.0)
    else:
        velocity_bonus = 8.0  # brand new video — give benefit of the doubt

    score = round(min(base + velocity_bonus, 95.0), 1)
    return score


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_iso8601_duration(duration: str) -> int:
    """Convert ISO 8601 duration (PT4M13S) to total seconds."""
    match = re.match(
        r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?",
        duration or "PT0S",
    )
    if not match:
        return 0
    hours   = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    return hours * 3600 + minutes * 60 + seconds


def _days_since(published_at: str) -> float:
    """Return fractional days since a YouTube publishedAt timestamp."""
    if not published_at:
        return 1.0
    try:
        pub = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - pub
        return max(delta.total_seconds() / 86400, 0.01)
    except ValueError:
        return 1.0
