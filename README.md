# TipMind — Your Autonomous Fan Agent

TipMind is an AI-powered agent that watches video streams in real time and autonomously tips creators in crypto (USDT, XAUT, BTC) based on engagement signals — watch time, live-chat emotion, milestone achievements, and coordinated fan swarms. Built on Tether's WDK for on-chain payments.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        FRONTEND (Next.js 14)                    │
│  Dashboard · Live Feed · Swarm Cards · Demo Control Bar         │
│  SWR polling (5 s) ──► REST API    WebSocket ──► Live Feed      │
└───────────────────┬─────────────────────┬───────────────────────┘
                    │ HTTP /api/*          │ ws://localhost:8000/ws/feed
┌───────────────────▼─────────────────────▼───────────────────────┐
│                      BACKEND (FastAPI)                           │
│                                                                  │
│   ┌──────────────────────────────────────────────────────────┐  │
│   │                    Orchestrator                           │  │
│   │  start() · inject_event() · get_status() · demo_mode()  │  │
│   └──────────┬───────────┬──────────────┬────────────────────┘  │
│              │           │              │                        │
│   ┌──────────▼──┐  ┌─────▼──────┐  ┌───▼────────┐  ┌────────┐  │
│   │ WatchTime   │  │ Emotion    │  │ Milestone  │  │ Swarm  │  │
│   │ TipAgent    │  │ ChatAgent  │  │ TipAgent   │  │ Agent  │  │
│   └──────┬──────┘  └─────┬──────┘  └──────┬─────┘  └───┬────┘  │
│          │               │                │             │       │
│   ┌──────▼───────────────▼────────────────▼─────────────▼────┐  │
│   │              Claude (claude-opus-4-6) via Anthropic SDK   │  │
│   │           Tip sizing · Sentiment · Swarm announcements    │  │
│   └───────────────────────────────┬───────────────────────────┘  │
│                                   │                              │
│   ┌───────────────────────────────▼───────────────────────────┐  │
│   │        EventBus (asyncio pub/sub) + SwarmPool             │  │
│   └───────────────────────────────┬───────────────────────────┘  │
│                                   │                              │
│   ┌───────────────────────────────▼───────────────────────────┐  │
│   │     Tether WDK Wallet — on-chain USDT / XAUT / BTC tips   │  │
│   └───────────────────────────────┬───────────────────────────┘  │
│                                   │                              │
│   ┌───────────────────────────────▼───────────────────────────┐  │
│   │           SQLite (aiosqlite) — async SQLAlchemy            │  │
│   │  tip_transactions · swarm_goals · agent_decisions_log     │  │
│   └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Quick Start

### Prerequisites
- Python 3.11+
- Node.js 18+
- An Anthropic API key
- Tether WDK credentials (optional — mock wallet used if not set)

### 1. Clone & install
```bash
git clone https://github.com/ex-plo-rer/TipMind.git
cd TipMind
make install
```

### 2. Configure environment
```bash
cp .env.example .env
# Edit .env with your keys:
#   ANTHROPIC_API_KEY=sk-ant-...
#   WDK_API_KEY=...
#   WDK_WALLET_ADDRESS=0x...
```

### 3. Run the full stack
```bash
make dev
```

- **Backend API**: http://localhost:8000
- **Frontend Dashboard**: http://localhost:3000
- **API Docs (Swagger)**: http://localhost:8000/docs
- **WebSocket Feed**: ws://localhost:8000/ws/feed

### 4. Run the demo
```bash
make demo
```
Seeds the database with realistic data and opens the dashboard automatically.

---

## Agent Overview

| Agent | Trigger | Claude Role |
|---|---|---|
| **WatchTimeTipAgent** | `WATCH_TIME_UPDATE` — user watches ≥70% of video | Size the micro-tip based on engagement depth |
| **EmotionChatAgent** | `CHAT_MESSAGE` — rolling sentiment spike in live chat | Detect hype peaks; decide tip amount from crowd energy |
| **MilestoneTipAgent** | `MILESTONE_REACHED` — DEBATE_WIN, 100K views, etc. | Write a custom celebration message + premium tip amount |
| **SwarmAgent** | `SWARM_TRIGGERED` — fan pool reaches target | Generate exciting announcement; release all tips via asyncio.gather() |

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/status` | Full system status |
| GET | `/api/metrics` | Today's totals + top creators |
| GET | `/api/transactions` | Paginated tip history |
| GET | `/api/decisions` | Paginated agent decisions |
| GET | `/api/swarms` | Active swarm goals |
| POST | `/api/swarms` | Create a new swarm |
| POST | `/api/swarms/{id}/join` | Join a swarm |
| GET | `/api/preferences` | User preferences |
| PUT | `/api/preferences` | Update preferences |
| POST | `/api/demo/{scenario}` | Trigger demo: `watch` / `hype` / `milestone` / `swarm` |
| GET | `/ws/feed` | WebSocket — live agent decision feed |

---

## Demo Control Bar

The dashboard includes a **Demo Control Bar** (visible in development mode) with four buttons:

| Button | Action |
|---|---|
| **Simulate Watch** | Fires a WATCH_TIME_UPDATE at 80% completion |
| **Inject Hype** | Floods the event bus with 20 high-sentiment chat messages |
| **Fire Milestone** | Triggers a `DEBATE_WIN` milestone for creator_001 |
| **Release Swarm** | Seeds + triggers the fan swarm (the main demo moment) |

---

## WDK Integration

TipMind uses Tether's WDK (Wallet Development Kit) for on-chain payments:

- **Wallet abstraction** — `backend/core/wallet.py` wraps WDK behind a `WalletInterface` so the agents never touch raw crypto APIs
- **Token support** — USDT (primary), XAUT (gold-backed), BTC
- **Mock mode** — If `WDK_API_KEY` is not set, a mock wallet is used that simulates transactions with fake tx hashes (safe for demos without real funds)
- **Swarm execution** — The `SwarmPool.release_swarm()` method fires all participant tips in parallel via `asyncio.gather()` — every fan tips simultaneously in a single async burst

```python
# How a swarm tip release works (backend/core/swarm_pool.py)
results = await asyncio.gather(*[_tip_one(participant) for participant in participants])
```

---

## Project Structure

```
TipMind/
├── backend/
│   ├── agents/          # 4 AI agents (watch, emotion, milestone, swarm)
│   ├── api/             # FastAPI routes + WebSocket feed
│   ├── core/            # EventBus, Orchestrator, SwarmPool, Wallet
│   ├── data/            # SQLAlchemy models + async database
│   ├── demo/            # Database seeder for realistic demo data
│   └── main.py          # FastAPI app entry point
├── frontend/
│   └── app/
│       └── page.tsx     # Single-page dashboard (SWR + WebSocket + Framer Motion)
├── Makefile
└── DEMO_GUIDE.md        # Step-by-step judge demo script
```

---

## Make Commands

```bash
make install   # Install Python + Node dependencies
make dev       # Run FastAPI + Next.js concurrently
make demo      # Seed data + launch + open browser
make seed      # Seed database only
make test      # Run pytest
make clean     # Remove DB, .next, __pycache__
```
