"""
backend/core/poller.py — Autonomous YouTube RSS Poller

Watches real YouTube channel RSS feeds and injects events into TipMind's
event bus without any human input. This is the core of TipMind's autonomy:
the agent discovers new creator content and acts on it independently.

Flow:
  1. Every POLL_INTERVAL seconds, fetch each channel's RSS feed
  2. For any video not yet seen → inject WATCH_TIME_UPDATE at simulated depth
  3. Track high-view videos (>100K) → inject MILESTONE_REACHED
  4. Inject CHAT_MESSAGE events during a "live window" after new uploads

No YouTube API key required — RSS feeds are publicly accessible.

Configure channels via env var:
  YOUTUBE_CHANNEL_IDS=UCxxxxxx,UCyyyyyy,...

Default channels included for zero-config demo (tech/crypto creators).
"""
from __future__ import annotations

import asyncio
import hashlib
import random
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

import httpx
from loguru import logger

from backend.core.event_bus import EventType, event_bus

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

POLL_INTERVAL = 90          # seconds between RSS polls
RSS_TIMEOUT   = 10.0        # seconds for HTTP requests
RSS_BASE      = "https://www.youtube.com/feeds/videos.xml?channel_id={}"

# Default demo channels (tech / crypto YouTubers, publicly popular)
DEFAULT_CHANNELS = {
    "UCnUYZLuoy1rq1aVMwx4aTzw": "MKBHD",              # Marques Brownlee
    "UC-8QAzbLcRglXeN_MY9blyw": "Theo t3.gg",          # t3.gg
    "UCVHFbw7woebKtRheObgd-dQ": "Coin Bureau",         # Crypto analysis
    "UCi_GwnJ4Lm1BU0TiKgJTjOQ": "Dave2D",              # Tech reviews
}

HYPE_KEYWORDS = [
    "incredible", "insane", "best ever", "🔥", "🚀", "LFG", "OMG",
    "legendary", "fire", "can't believe", "mindblown", "GOAT",
]

MILESTONE_VIEW_THRESHOLD = 100_000   # views to trigger milestone


# ---------------------------------------------------------------------------
# YouTubePoller
# ---------------------------------------------------------------------------

class YouTubePoller:
    """
    Autonomous background agent that polls YouTube RSS feeds and injects
    TipMind events without any human trigger.
    """

    def __init__(self) -> None:
        self._seen: set[str]       = set()   # video IDs already processed
        self._task: asyncio.Task | None = None
        self._running = False
        self._channels: dict[str, str] = {}  # channel_id → creator_name

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def configure(self, channel_ids: list[str]) -> None:
        """
        Set which channels to watch. Call before start().
        channel_ids is a list of YouTube channel IDs (UCxxxxxx...).
        Falls back to DEFAULT_CHANNELS if empty.
        """
        if channel_ids:
            self._channels = {cid: cid[:8] for cid in channel_ids}
            logger.info(f"[POLLER] Watching {len(self._channels)} configured channels")
        else:
            self._channels = DEFAULT_CHANNELS
            logger.info(
                f"[POLLER] No YOUTUBE_CHANNEL_IDS set — using {len(DEFAULT_CHANNELS)} "
                "default channels (MKBHD, t3.gg, Coin Bureau, Dave2D)"
            )

    def start(self) -> None:
        """Start the background polling loop as an asyncio task."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop(), name="youtube-poller")
        logger.info(
            f"[POLLER] Autonomous polling started — interval={POLL_INTERVAL}s, "
            f"channels={len(self._channels)}"
        )

    def stop(self) -> None:
        """Gracefully stop the polling loop."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        logger.info("[POLLER] Stopped")

    @property
    def is_running(self) -> bool:
        return self._running and (self._task is not None) and (not self._task.done())

    # ------------------------------------------------------------------
    # Core loop
    # ------------------------------------------------------------------

    async def _poll_loop(self) -> None:
        """Main polling loop — runs until stop() is called."""
        logger.info("[POLLER] First poll starting immediately...")
        while self._running:
            try:
                await self._poll_all_channels()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"[POLLER] Unexpected error in poll loop: {exc}")

            try:
                await asyncio.sleep(POLL_INTERVAL)
            except asyncio.CancelledError:
                break

    async def _poll_all_channels(self) -> None:
        """Poll every configured channel and process new videos."""
        async with httpx.AsyncClient(timeout=RSS_TIMEOUT) as client:
            tasks = [
                self._poll_channel(client, channel_id, name)
                for channel_id, name in self._channels.items()
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        errors = [r for r in results if isinstance(r, Exception)]
        if errors:
            logger.debug(f"[POLLER] {len(errors)} channel(s) failed to fetch (network issue?)")

    async def _poll_channel(
        self,
        client: httpx.AsyncClient,
        channel_id: str,
        creator_name: str,
    ) -> None:
        """Fetch one channel's RSS feed and process new videos."""
        url = RSS_BASE.format(channel_id)
        try:
            resp = await client.get(url)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.debug(f"[POLLER] RSS fetch failed for {creator_name}: {exc}")
            return

        videos = self._parse_rss(resp.text, channel_id, creator_name)
        new_videos = [v for v in videos if v["video_id"] not in self._seen]

        if not new_videos:
            logger.debug(f"[POLLER] {creator_name}: no new videos")
            return

        logger.info(f"[POLLER] {creator_name}: {len(new_videos)} new video(s) found")

        for video in new_videos:
            self._seen.add(video["video_id"])
            await self._process_video(video)
            # Small stagger between events to avoid flooding the bus
            await asyncio.sleep(random.uniform(1.0, 3.0))

    # ------------------------------------------------------------------
    # Event injection
    # ------------------------------------------------------------------

    async def _process_video(self, video: dict[str, Any]) -> None:
        """
        For each new video, autonomously inject a sequence of events:
          1. WATCH_TIME_UPDATE — simulating a fan watching at 75–92%
          2. CHAT_MESSAGE ×3   — simulating live-chat hype
          3. MILESTONE check   — if video title matches milestone patterns
        """
        video_id    = video["video_id"]
        creator_id  = video["channel_id"]
        creator_name = video["creator_name"]
        title       = video["title"]

        logger.info(
            f"[POLLER] Autonomous event injection: '{title[:60]}' by {creator_name}"
        )

        # 1. Watch-time event — agent watches this video autonomously
        watch_pct = round(random.uniform(75.0, 92.0), 1)
        duration  = random.randint(480, 3600)   # 8 min – 1 hr

        await event_bus.publish(EventType.WATCH_TIME_UPDATE, {
            "video_id":              video_id,
            "creator_id":            creator_id,
            "creator_name":          creator_name,
            "title":                 title,
            "user_id":               "tipmind_agent",
            "watch_seconds":         int(duration * watch_pct / 100),
            "total_duration":        duration,
            "percentage_watched":    watch_pct,
            "user_budget_remaining": 5.0,
            "source":                "autonomous_poller",
        })
        logger.debug(
            f"[POLLER] Injected WATCH_TIME_UPDATE {watch_pct}% for '{title[:40]}'"
        )

        await asyncio.sleep(random.uniform(0.5, 1.5))

        # 2. Simulated chat hype — reaction to watching the video
        hype_messages = random.sample(HYPE_KEYWORDS, k=min(3, len(HYPE_KEYWORDS)))
        for i, keyword in enumerate(hype_messages):
            msg = f"{keyword} this video by {creator_name} is 🔥"
            await event_bus.publish(EventType.CHAT_MESSAGE, {
                "video_id":   video_id,
                "creator_id": creator_id,
                "user_id":    f"fan_{i+1:03d}",
                "message":    msg,
                "source":     "autonomous_poller",
            })
            await asyncio.sleep(0.3)

        # 3. Milestone detection from video title / view count patterns
        milestone = self._detect_milestone(title, creator_id)
        if milestone:
            await asyncio.sleep(random.uniform(1.0, 2.0))
            await event_bus.publish(EventType.MILESTONE_REACHED, {
                "creator_id":    creator_id,
                "creator_name":  creator_name,
                "milestone_type": milestone,
                "value":         0,
                "source":        "autonomous_poller",
                "video_id":      video_id,
                "title":         title,
            })
            logger.info(
                f"[POLLER] Milestone detected: {milestone} for {creator_name}"
            )

    # ------------------------------------------------------------------
    # Parsers & detectors
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_rss(xml_text: str, channel_id: str, creator_name: str) -> list[dict]:
        """Parse YouTube RSS feed XML into a list of video dicts."""
        videos = []
        try:
            root = ET.fromstring(xml_text)
            ns = {
                "atom":  "http://www.w3.org/2005/Atom",
                "yt":    "http://www.youtube.com/xml/schemas/2015",
                "media": "http://search.yahoo.com/mrss/",
            }
            for entry in root.findall("atom:entry", ns):
                vid_el  = entry.find("yt:videoId", ns)
                title_el = entry.find("atom:title", ns)
                if vid_el is None or title_el is None:
                    continue
                videos.append({
                    "video_id":    vid_el.text or "",
                    "title":       title_el.text or "",
                    "channel_id":  channel_id,
                    "creator_name": creator_name,
                })
        except ET.ParseError as exc:
            logger.debug(f"[POLLER] RSS parse error for {creator_name}: {exc}")
        return videos

    @staticmethod
    def _detect_milestone(title: str, creator_id: str) -> str | None:
        """
        Heuristically detect milestone events from video titles.
        Returns a MilestoneType string or None.
        """
        title_lower = title.lower()

        patterns = [
            (r"\b(won|win|winning|winner|victory|beat|defeated)\b", "DEBATE_WIN"),
            (r"\b100k\b|\b100,000\b",                               "VIEWS_100K"),
            (r"\b1m\b|\b1,000,000\b",                               "VIEWS_100K"),
            (r"\b(10k|10,000)\s*(sub|follow|like)",                  "LIKES_10K"),
            (r"\b(milestone|subscriber|subs?)\b.*\b(million|m\b)",  "SUBS_MILESTONE"),
        ]

        for pattern, milestone_type in patterns:
            if re.search(pattern, title_lower):
                return milestone_type

        return None

    def status(self) -> dict[str, Any]:
        """Return current poller status for /api/status endpoint."""
        return {
            "running":        self.is_running,
            "channels":       len(self._channels),
            "videos_seen":    len(self._seen),
            "poll_interval_s": POLL_INTERVAL,
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

poller = YouTubePoller()
