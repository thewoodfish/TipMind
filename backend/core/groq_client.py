"""
LLM client — xAI Grok (primary) or Groq Llama (fallback).

Both APIs are OpenAI-compatible, so the same openai.AsyncOpenAI client
works for both — just different base_url and model names.

Priority:
  1. xAI Grok  (XAI_API_KEY set)  → grok-3-mini
  2. Groq       (GROQ_API_KEY set) → llama-3.3-70b-versatile
  3. Mock JSON  (neither key set)  → pre-computed responses
"""
from __future__ import annotations

from openai import AsyncOpenAI
from loguru import logger

from backend.config import config


_client: AsyncOpenAI | None = None
MODEL: str = "grok-3-mini"


def get_client() -> AsyncOpenAI:
    global _client, MODEL
    if _client is not None:
        return _client

    if config.xai_api_key:
        MODEL = "grok-3-mini"
        _client = AsyncOpenAI(
            api_key=config.xai_api_key,
            base_url="https://api.x.ai/v1",
        )
        logger.info(f"[LLM] Using xAI Grok — model={MODEL}")
    elif config.groq_api_key:
        MODEL = "llama-3.3-70b-versatile"
        _client = AsyncOpenAI(
            api_key=config.groq_api_key,
            base_url="https://api.groq.com/openai/v1",
        )
        logger.info(f"[LLM] Using Groq — model={MODEL}")
    else:
        raise RuntimeError("No LLM API key set (XAI_API_KEY or GROQ_API_KEY)")

    return _client


async def chat(
    system: str,
    user: str,
    max_tokens: int = 256,
) -> str:
    """
    Send a chat completion and return the text response.
    """
    client = get_client()
    logger.debug(f"[LLM] {MODEL} — user={user[:80]!r}")

    response = await client.chat.completions.create(
        model=MODEL,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.7,
    )
    text = response.choices[0].message.content or ""
    logger.debug(f"[LLM] response={text[:80]!r}")
    return text
