"""
backend/core/mock_claude.py — Pre-computed Claude response simulator

Replaces live Anthropic API calls with realistic JSON responses loaded from
backend/data/claude_responses.json. Activated by USE_MOCK_CLAUDE=true in .env.

Responses are varied (not static) — selection is deterministic but distributed
across the response pool using a hash of the input so the same scenario always
returns the same result, while different inputs return different responses.

Swap back to real Claude: set USE_MOCK_CLAUDE=false in .env. Zero other changes needed.
"""
from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Any

from loguru import logger

_RESPONSES_PATH = Path(__file__).parent.parent / "data" / "claude_responses.json"


def _load() -> dict:
    with open(_RESPONSES_PATH) as f:
        return json.load(f)


_data: dict = _load()


def _pick(pool: list, seed: str) -> dict:
    """Pick deterministically from a pool using a string seed, then add slight noise."""
    idx = int(hashlib.md5(seed.encode()).hexdigest(), 16) % len(pool)
    return pool[idx].copy()


# ---------------------------------------------------------------------------
# Public API — one function per agent
# ---------------------------------------------------------------------------

def watch_decision(
    engagement_score: float,
    creator_name: str = "",
    already_tipped_today: float = 0.0,
) -> dict:
    """
    Return a tip decision for a watch-time event.
    engagement_score maps to the same percentage_watched scale (0–100).
    """
    if engagement_score >= 70:
        tier = "high"
    elif engagement_score >= 35:
        tier = "medium"
    else:
        tier = "low"

    pool = _data["watch"][tier]
    result = _pick(pool, f"{creator_name}-{tier}-{int(engagement_score)}")

    # Apply slight amount variation within tier for realism
    if result["should_tip"] and result["amount"] > 0:
        variation = random.uniform(0.9, 1.1)
        result["amount"] = round(result["amount"] * variation, 2)

    logger.info(
        f"[MOCK CLAUDE][WATCH] {creator_name} engagement={engagement_score:.1f}% → "
        f"should_tip={result['should_tip']} amount=${result['amount']}"
    )
    return result


def emotion_decision(
    excitement_level: float,
    creator_name: str = "",
) -> dict:
    """Return a tip decision for a chat emotion event (excitement_level 0–10)."""
    if excitement_level >= 7:
        tier = "high"
    elif excitement_level >= 4:
        tier = "medium"
    else:
        tier = "low"

    pool = _data["emotion"][tier]
    result = _pick(pool, f"{creator_name}-emotion-{tier}-{int(excitement_level)}")

    logger.info(
        f"[MOCK CLAUDE][EMOTION] {creator_name} excitement={excitement_level:.1f} → "
        f"should_tip={result['should_tip']}"
    )
    return result


def milestone_decision(
    milestone_type: str,
    creator_name: str = "",
    base_tip_hint: float = 1.0,
) -> dict:
    """Return a tip decision for a milestone event."""
    pool = _data["milestone"].get(milestone_type, _data["milestone"]["CUSTOM"])
    result = _pick(pool, f"{creator_name}-{milestone_type}")

    logger.info(
        f"[MOCK CLAUDE][MILESTONE] {creator_name} {milestone_type} → "
        f"amount=${result['tip_amount']} swarm={result['trigger_swarm']}"
    )
    return result


def swarm_announcement(swarm_id: str = "") -> str:
    """Return a one-sentence swarm announcement."""
    pool = _data["swarm"]["announcements"]
    idx = int(hashlib.md5(swarm_id.encode()).hexdigest(), 16) % len(pool)
    msg = pool[idx]
    logger.info(f"[MOCK CLAUDE][SWARM] announcement selected for swarm {swarm_id}")
    return msg
