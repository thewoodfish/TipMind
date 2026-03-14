"""
Emotion / Chat Tip Agent
------------------------
Subscribes to CHAT_MESSAGE events and detects hype moments in live streams.

Pipeline:
  1. Buffer incoming chat messages in a 30-second sliding window
  2. Instant keyword trigger — no Claude needed (fires $0.25 immediately)
  3. Every 30 s: send window to Claude for excitement analysis
  4. On excitement >= 7 → tip $0.50-$1; >= 9 → tip $2 + notify swarm
  5. Execute tip via wallet, log decision, publish AGENT_DECISION

All logs prefixed [EMOTION AGENT].
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from collections import deque
from typing import Any

import anthropic
from loguru import logger

from backend.config import config
from backend.core.event_bus import event_bus, EventType
from backend.core.wallet import WalletFactory
from backend.data.models import AgentDecisionLogORM, TipTransactionORM, ChatMessage


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WINDOW_SECONDS   = 30
MAX_WINDOW_MSGS  = 20       # messages passed to Claude
ANALYSIS_INTERVAL = 30.0   # seconds between Claude calls

EXCITEMENT_MEDIUM_MIN = 7
EXCITEMENT_MEDIUM_MAX = 8
EXCITEMENT_HIGH_MIN   = 9

TIP_MEDIUM = 0.75   # excitement 7-8
TIP_HIGH   = 2.00   # excitement 9-10

# Instant-trigger keywords (case-insensitive)
INSTANT_KEYWORDS = re.compile(
    r"\b(insane|lets\s+go|let's\s+go|clip\s+it)\b|(\bW\b)|🔥🔥🔥",
    re.IGNORECASE,
)
INSTANT_TIP = 0.25

# Hype boosters that add to excitement score hint
HYPE_PHRASES = ["insane", "lets go", "let's go", "clip it", "🔥", "goat", "pog", "omg"]

SYSTEM_PROMPT = (
    "You are an emotion analyzer for live streams. "
    "Detect hype, excitement, and viral moments from chat patterns. "
    "Return JSON only."
)


# ---------------------------------------------------------------------------
# Sliding window buffer
# ---------------------------------------------------------------------------

class _ChatWindow:
    """Thread-safe sliding window of chat messages."""

    def __init__(self, max_age: float = WINDOW_SECONDS) -> None:
        self._msgs: deque[dict] = deque()
        self._max_age = max_age

    def add(self, msg: dict) -> None:
        self._msgs.append({**msg, "_ts": time.monotonic()})

    def snapshot(self) -> list[dict]:
        """Return messages within the window, pruning old ones."""
        cutoff = time.monotonic() - self._max_age
        while self._msgs and self._msgs[0]["_ts"] < cutoff:
            self._msgs.popleft()
        return list(self._msgs)

    def emoji_counts(self, snapshot: list[dict]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for m in snapshot:
            for ch in m.get("message", ""):
                if ord(ch) > 0x1F300:          # rough emoji range
                    counts[ch] = counts.get(ch, 0) + 1
        return counts

    def message_rate(self, snapshot: list[dict]) -> float:
        """Messages per second over the window."""
        if len(snapshot) < 2:
            return 0.0
        span = snapshot[-1]["_ts"] - snapshot[0]["_ts"]
        return len(snapshot) / span if span > 0 else len(snapshot)


# ---------------------------------------------------------------------------
# Emotion / Chat Tip Agent
# ---------------------------------------------------------------------------

class EmotionChatAgent:
    """
    Listens to CHAT_MESSAGE events, buffers them, and periodically triggers
    tips when excitement thresholds are crossed.
    """

    def __init__(self, db_session_factory) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=config.anthropic_api_key)
        self._db_factory = db_session_factory
        self._wallet = WalletFactory.create()
        # Per-video windows: video_id → _ChatWindow
        self._windows: dict[str, _ChatWindow] = {}
        self._analysis_tasks: dict[str, asyncio.Task] = {}

    # ------------------------------------------------------------------
    # Subscription
    # ------------------------------------------------------------------

    def subscribe(self) -> None:
        event_bus.subscribe(EventType.CHAT_MESSAGE, self._handle_chat)
        logger.info("[EMOTION AGENT] Subscribed to CHAT_MESSAGE events")

    # ------------------------------------------------------------------
    # Event handler
    # ------------------------------------------------------------------

    async def _handle_chat(self, payload: dict[str, Any]) -> None:
        try:
            msg = ChatMessage(
                user_id=payload["user_id"],
                video_id=payload["video_id"],
                message=payload["message"],
                sentiment_score=payload.get("sentiment_score"),
            )
        except Exception as exc:
            logger.warning(f"[EMOTION AGENT] Bad payload: {exc}")
            return

        creator_id = payload.get("creator_id", msg.video_id)

        # Ensure window exists
        if msg.video_id not in self._windows:
            self._windows[msg.video_id] = _ChatWindow()

        window = self._windows[msg.video_id]
        window.add({"user_id": msg.user_id, "message": msg.message})

        logger.debug(f"[EMOTION AGENT] Chat buffered — video={msg.video_id} msg='{msg.message[:40]}'")

        # ── Instant keyword trigger ───────────────────────────────────
        if INSTANT_KEYWORDS.search(msg.message):
            logger.info(
                f"[EMOTION AGENT] Instant trigger on '{msg.message[:40]}' — tipping ${INSTANT_TIP}"
            )
            await self._execute_tip(
                creator_id=creator_id,
                video_id=msg.video_id,
                amount=INSTANT_TIP,
                excitement=5,
                detected_moment="instant_keyword",
                reasoning=f"Hype keyword detected: '{msg.message[:60]}'",
                confidence=0.85,
            )
            return

        # ── Start periodic analysis loop if not running ───────────────
        if msg.video_id not in self._analysis_tasks or self._analysis_tasks[msg.video_id].done():
            task = asyncio.create_task(
                self._analysis_loop(msg.video_id, creator_id)
            )
            self._analysis_tasks[msg.video_id] = task

    # ------------------------------------------------------------------
    # Periodic Claude analysis loop
    # ------------------------------------------------------------------

    async def _analysis_loop(self, video_id: str, creator_id: str) -> None:
        """Runs until the window stays empty for a full interval."""
        logger.info(f"[EMOTION AGENT] Analysis loop started for video={video_id}")
        idle_cycles = 0

        while idle_cycles < 3:
            await asyncio.sleep(ANALYSIS_INTERVAL)

            window = self._windows.get(video_id)
            if not window:
                break

            snapshot = window.snapshot()
            if not snapshot:
                idle_cycles += 1
                continue
            idle_cycles = 0

            await self._analyze_window(video_id, creator_id, window, snapshot)

        logger.info(f"[EMOTION AGENT] Analysis loop ended for video={video_id}")
        self._windows.pop(video_id, None)

    async def _analyze_window(
        self,
        video_id: str,
        creator_id: str,
        window: _ChatWindow,
        snapshot: list[dict],
    ) -> None:
        recent = snapshot[-MAX_WINDOW_MSGS:]
        emoji_counts = window.emoji_counts(snapshot)
        msg_rate = window.message_rate(snapshot)

        # Hype phrase boost hint
        all_text = " ".join(m["message"] for m in recent).lower()
        hype_hits = sum(all_text.count(p) for p in HYPE_PHRASES)

        payload_for_claude = {
            "last_messages": [m["message"] for m in recent],
            "emoji_counts": emoji_counts,
            "message_frequency_per_second": round(msg_rate, 2),
            "hype_phrase_count": hype_hits,
            "window_seconds": WINDOW_SECONDS,
        }

        logger.info(
            f"[EMOTION AGENT] Analyzing window — video={video_id} "
            f"msgs={len(recent)} rate={msg_rate:.2f}/s hype={hype_hits}"
        )

        result = await self._ask_claude(payload_for_claude)

        excitement = int(result.get("excitement_level", 0))
        should_tip = result.get("should_tip", False)
        suggested  = float(result.get("suggested_amount", 0))
        detected   = result.get("detected_moment", "")
        reasoning  = result.get("reasoning", "")

        logger.info(
            f"[EMOTION AGENT] excitement={excitement} should_tip={should_tip} "
            f"moment='{detected}'"
        )

        if not should_tip or excitement < EXCITEMENT_MEDIUM_MIN:
            return

        # Determine tip amount from excitement band
        if excitement >= EXCITEMENT_HIGH_MIN:
            amount = TIP_HIGH
            # Notify swarm agent
            await event_bus.publish(EventType.SWARM_TRIGGERED, {
                "source": "EmotionChatAgent",
                "video_id": video_id,
                "creator_id": creator_id,
                "excitement": excitement,
                "detected_moment": detected,
            })
            logger.info(f"[EMOTION AGENT] excitement={excitement} — swarm notified")
        else:
            amount = suggested if INSTANT_TIP < suggested <= TIP_HIGH else TIP_MEDIUM

        await self._execute_tip(
            creator_id=creator_id,
            video_id=video_id,
            amount=amount,
            excitement=excitement,
            detected_moment=detected,
            reasoning=reasoning,
            confidence=min(excitement / 10.0, 1.0),
        )

    # ------------------------------------------------------------------
    # Claude call
    # ------------------------------------------------------------------

    async def _ask_claude(self, payload: dict) -> dict:
        async with self._client.messages.stream(
            model="claude-sonnet-4-20250514",
            max_tokens=256,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": json.dumps(payload)}],
        ) as stream:
            response = await stream.get_final_message()

        text = next((b.text for b in response.content if b.type == "text"), "{}")
        return json.loads(text)

    # ------------------------------------------------------------------
    # Tip execution + logging
    # ------------------------------------------------------------------

    async def _execute_tip(
        self,
        creator_id: str,
        video_id: str,
        amount: float,
        excitement: int,
        detected_moment: str,
        reasoning: str,
        confidence: float,
    ) -> None:
        amount = min(amount, config.max_tip_per_video)

        try:
            tx = await self._wallet.send_tip(
                to_address=creator_id,
                amount=amount,
                token=config.default_token,
            )
            logger.info(
                f"[EMOTION AGENT] Tip sent — {amount} {config.default_token} "
                f"→ {creator_id} | tx={tx.tx_hash} | moment='{detected_moment}'"
            )
        except Exception as exc:
            logger.error(f"[EMOTION AGENT] Wallet error: {exc}")
            return

        async with self._db_factory() as db:
            db.add(TipTransactionORM(
                tx_hash=tx.tx_hash,
                from_wallet=await self._wallet.get_wallet_address(),
                to_wallet=creator_id,
                amount=amount,
                token=config.default_token,
                creator_id=creator_id,
                trigger_type="CHAT_EMOTION",
                status=tx.status,
            ))
            db.add(AgentDecisionLogORM(
                agent_type="EmotionChatAgent",
                trigger=f"excitement={excitement}|moment={detected_moment}",
                creator_id=creator_id,
                amount_usd=amount,
                reasoning=f"{reasoning} | video={video_id}",
                confidence_score=confidence,
            ))
            await db.commit()

        await event_bus.publish(EventType.AGENT_DECISION, {
            "agent": "EmotionChatAgent",
            "video_id": video_id,
            "creator_id": creator_id,
            "excitement_level": excitement,
            "detected_moment": detected_moment,
            "amount": amount,
            "token": config.default_token,
            "tx_hash": tx.tx_hash,
            "reasoning": reasoning,
        })


# ---------------------------------------------------------------------------
# Legacy thin wrapper kept for swarm_agent compatibility
# ---------------------------------------------------------------------------

class EmotionAgent:
    """
    Thin wrapper used by SwarmAgent for one-shot video metadata analysis.
    Kept separate from the event-driven EmotionChatAgent above.
    """

    SYSTEM_PROMPT = """You are an expert in emotional intelligence and content analysis.
Given metadata about a video, analyze emotional resonance and quality.
Return JSON only:
{"score": 0.0-1.0, "sentiment": "positive|neutral|negative",
 "key_emotions": [...], "reasoning": "..."}"""

    def __init__(self) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=config.anthropic_api_key)

    async def analyze(self, video_metadata: dict) -> dict:
        user_message = (
            f"Title: {video_metadata.get('title', 'Unknown')}\n"
            f"Description: {video_metadata.get('description', 'N/A')}\n"
            f"Views: {video_metadata.get('view_count', 0):,}\n"
            f"Likes: {video_metadata.get('like_count', 0):,}\n"
            "Provide emotional analysis as JSON."
        )
        logger.info(f"[EMOTION AGENT] Analyzing video: {video_metadata.get('title', 'unknown')}")

        async with self._client.messages.stream(
            model="claude-opus-4-6",
            max_tokens=512,
            thinking={"type": "adaptive"},
            system=self.SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        ) as stream:
            response = await stream.get_final_message()

        text = next((b.text for b in response.content if b.type == "text"), "{}")
        result = json.loads(text)
        logger.info(f"[EMOTION AGENT] Score: {result.get('score', 0)}")
        return result
