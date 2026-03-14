---
name: TipMind Project
description: AI-powered crypto tipping system for videos — uses Anthropic agents + WDK wallet
type: project
---

TipMind is an AI-powered tipping system for video content.

**Stack:**
- Backend: FastAPI + Python, Anthropic SDK (claude-opus-4-6)
- Frontend: Next.js
- DB: SQLite via SQLAlchemy + aiosqlite
- Payments: Tether WDK (WDK_ENDPOINT, USDT)

**Agent architecture:**
- `tip_agent.py` — decides tip amount based on content quality
- `emotion_agent.py` — analyzes video sentiment/emotion
- `milestone_agent.py` — tracks creator milestones (views, subs, etc.)
- `swarm_agent.py` — coordinates sub-agents into a unified tip decision

**How to apply:** Always reference https://docs.wdk.tether.io/ when modifying wallet.py or payment flows. Use `claude-opus-4-6` with adaptive thinking for all agent work.
