<div align="center">

# TipMind
### Your Autonomous Fan Agent

**An AI agent that watches video creators, feels the crowd, and tips in crypto — on its own.**

No buttons. No manual triggers. No human in the loop.

[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=flat-square&logo=fastapi)](https://fastapi.tiangolo.com)
[![Next.js](https://img.shields.io/badge/Next.js-15-black?style=flat-square&logo=next.js)](https://nextjs.org)
[![Claude](https://img.shields.io/badge/Claude-opus--4--6-cc785c?style=flat-square)](https://anthropic.com)
[![WDK](https://img.shields.io/badge/Tether-WDK-26A17B?style=flat-square)](https://docs.wdk.tether.io)
[![License](https://img.shields.io/badge/license-MIT-blue?style=flat-square)](LICENSE)

</div>

---

## The Problem

Fans want to support their favourite creators the moment something great happens — a debate win, a viral moment, a milestone crossed. But by the time they notice, open their wallet, and send a tip, the moment is gone.

## The Solution

TipMind is a **fully autonomous AI agent** that monitors creator content in real time, interprets what's happening, and executes crypto tips the moment they're deserved — faster than any human, every time.

It watches YouTube channels continuously. It reads crowd emotion from live chat. It celebrates milestones with custom Claude-written messages. And when a fan swarm goal triggers, it fires every participant's tip **simultaneously** via `asyncio.gather()` — a coordinated on-chain burst that no human could execute manually.

> Set it up once. It runs forever. Creators earn. Fans contribute. Zero friction.

---

## Live Demo

```
make demo
```

The agent starts polling real YouTube channels immediately. Watch tips appear in the live feed — autonomously, without touching a button.

---

## How It Works

```
┌──────────────────────────────────────────────────────────────────────┐
│  YouTube RSS Feeds (public, no API key)                               │
│  MKBHD · t3.gg · Coin Bureau · Dave2D  + your channels               │
└────────────────────────┬─────────────────────────────────────────────┘
                         │ polls every 90 s — zero human input
                         ▼
┌──────────────────────────────────────────────────────────────────────┐
│  Autonomous Poller  (backend/core/poller.py)                         │
│  Detects new videos → injects WATCH_TIME_UPDATE + CHAT_MESSAGE       │
│  Recognises milestone patterns in video titles (regex + heuristics)  │
└────────────────────────┬─────────────────────────────────────────────┘
                         │ asyncio pub/sub EventBus
          ┌──────────────┼───────────────┬─────────────────┐
          ▼              ▼               ▼                 ▼
   ┌────────────┐ ┌────────────┐ ┌─────────────┐ ┌────────────┐
   │ WatchTime  │ │ Emotion    │ │ Milestone   │ │   Swarm    │
   │ TipAgent   │ │ ChatAgent  │ │ TipAgent    │ │   Agent    │
   │            │ │            │ │             │ │            │
   │ ≥70% watch │ │ rolling    │ │ DEBATE_WIN  │ │ collective │
   │ triggers   │ │ sentiment  │ │ VIEWS_100K  │ │ fan pool   │
   │ micro-tip  │ │ spike      │ │ SUBS_MILE.. │ │ release    │
   └─────┬──────┘ └─────┬──────┘ └──────┬──────┘ └─────┬──────┘
         └──────────────┴───────────────┴──────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │   Claude (opus-4-6)      │
                    │                          │
                    │  · Sizes each tip        │
                    │  · Reads crowd energy    │
                    │  · Writes announcements  │
                    │  · Streaming responses   │
                    └────────────┬─────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │   Tether WDK Wallet      │
                    │                          │
                    │  @tetherto/wdk           │
                    │  wdk-wallet-evm          │
                    │  Polygon / Ethereum      │
                    │  USDT · XAUT · BTC       │
                    └────────────┬─────────────┘
                                 │ real on-chain tx
                    ┌────────────▼────────────┐
                    │   SQLite (async)         │
                    │   tip_transactions       │
                    │   swarm_goals            │
                    │   agent_decisions_log    │
                    └──────────────────────────┘
```

---

## The Four Agents

### 1. WatchTimeTipAgent
Fires when a user watches ≥70% of a video. Claude contextualises the tip amount based on depth of engagement — a 95% watch of a 45-minute video earns more than 70% of a 3-minute clip.

### 2. EmotionChatAgent
Maintains a rolling 60-second sentiment window over live chat. When crowd energy spikes above threshold (PogChamp × 12, "LFG!" × 8), Claude reads the room and rewards the creator proportionally.

### 3. MilestoneTipAgent
Intercepts structured milestone events — `DEBATE_WIN`, `VIEWS_100K`, `SUBS_MILESTONE`. Claude generates a custom celebration message and sizes a premium tip. The reasoning is logged and displayed in the live feed.

### 4. SwarmAgent
The headline feature. Fans collectively pledge toward a goal ("$100 if Alex wins the debate"). When the trigger fires, every participant's tip executes **simultaneously** via `asyncio.gather()`. One event. One announcement written by Claude. Every fan tips at once.

```python
# backend/core/swarm_pool.py
results = await asyncio.gather(*[_tip_one(participant) for participant in participants])
# → 20 fans, 20 on-chain transactions, fired in parallel in < 1 second
```

---

## Autonomy — What Runs Without You

Once `make dev` is executed, TipMind operates without any human input:

| What happens automatically | How |
|---|---|
| Polls 4+ YouTube channels every 90 s | `YouTubePoller` asyncio background task |
| Detects new videos and generates events | RSS XML parsing, no API key needed |
| Reads sentiment from simulated chat | `EmotionChatAgent` rolling window |
| Detects milestone keywords in video titles | Regex pattern matching |
| Sizes tips using Claude reasoning | `claude-opus-4-6` with streaming |
| Executes on-chain USDT transfers | Tether WDK → Polygon |
| Broadcasts decisions over WebSocket | Live dashboard updates in real time |
| Logs every decision with reasoning | `agent_decisions_log` table |

The only human action required: **`make dev`**.

---

## WDK Integration

TipMind uses a dedicated **Node.js microservice** (`wdk-service/`) to wrap Tether's `@tetherto/wdk` SDK, since WDK is a Node.js library and the backend is Python.

```
Python FastAPI  ──HTTP──►  wdk-service (Node.js :3001)  ──WDK──►  Polygon
```

The service initialises from a BIP39 seed phrase, derives the first EVM account, encodes ERC-20 USDT `transfer()` calls via `ethers.js`, and broadcasts signed transactions through WDK's `account.sendTransaction()`.

```javascript
// wdk-service/index.js
const wdk = new WDK(process.env.WDK_SEED_PHRASE)
  .registerWallet('polygon', WalletManagerEvm, { rpcUrl: RPC_URL });

const account = await wdk.getAccount('polygon', 0);
const { hash: txHash } = await account.sendTransaction({
  to:    USDT_CONTRACT,           // 0xc2132...e8F on Polygon
  data:  encodeUsdtTransfer(to, amount),
  value: '0',
});
```

**Mock mode** — If `WDK_SEED_PHRASE` is not set, the Python backend falls back to `MockWallet` which generates SHA-256 fake tx hashes and simulates 200–800 ms network delay. Safe for demos without real funds; the rest of the stack behaves identically.

---

## Fan Swarms — Economic Design

A swarm is a collective commitment mechanism:

1. **Create** — Anyone creates a swarm goal with a trigger event and USD target
2. **Join** — Fans pledge amounts; funds are committed (not yet sent)
3. **Trigger** — A real event fires (`DEBATE_WIN`, milestone, etc.)
4. **Release** — SwarmAgent calls `release_swarm()` → all tips execute simultaneously

This is economically sound because:
- Commitments are bounded by the fan's configured `max_per_video` setting
- The 24-hour TTL on swarms prevents indefinite fund lockup
- Claude's announcement runs before release, so the creator sees the collective moment
- Parallel execution means the creator receives all funds within the same block

---

## Quick Start

**Prerequisites:** Python 3.11+, Node.js 18+

```bash
# 1. Clone
git clone https://github.com/ex-plo-rer/TipMind.git
cd TipMind

# 2. Install everything
make install

# 3. Configure
cp .env.example .env
# Required: ANTHROPIC_API_KEY
# For live tips: WDK_SEED_PHRASE + WDK_RPC_URL
# Optional: YOUTUBE_CHANNEL_IDS (defaults to MKBHD, t3.gg, Coin Bureau, Dave2D)

# 4. Launch (all 3 services)
make dev
```

| Service | URL |
|---|---|
| Dashboard | http://localhost:3000 |
| Backend API + Swagger | http://localhost:8000/docs |
| WebSocket feed | ws://localhost:8000/ws/feed |
| WDK microservice | http://localhost:3001/health |

**For the full demo experience** (seeds data + opens browser automatically):
```bash
make demo
```

---

## Project Structure

```
TipMind/
├── backend/
│   ├── agents/
│   │   ├── tip_agent.py         # WatchTimeTipAgent — engagement-based micro-tips
│   │   ├── emotion_agent.py     # EmotionChatAgent — sentiment spike detection
│   │   ├── milestone_agent.py   # MilestoneTipAgent — celebration tips + Claude messages
│   │   └── swarm_agent.py       # SwarmAgent — parallel fan tip release
│   ├── api/
│   │   ├── routes.py            # REST endpoints (status, swarms, txns, prefs, demo)
│   │   └── websocket.py         # WebSocket feed with formatted event streaming
│   ├── core/
│   │   ├── event_bus.py         # asyncio pub/sub event bus
│   │   ├── orchestrator.py      # Agent coordinator + demo mode
│   │   ├── poller.py            # Autonomous YouTube RSS poller
│   │   ├── swarm_pool.py        # Swarm lifecycle management + asyncio.gather() release
│   │   └── wallet.py            # WalletInterface → WDKWallet / MockWallet
│   ├── data/
│   │   ├── models.py            # Pydantic + SQLAlchemy models
│   │   └── database.py          # Async SQLAlchemy engine + session factory
│   ├── demo/
│   │   └── seed.py              # Realistic seed: 21 txns, 2 swarms, 50 decisions
│   └── main.py                  # FastAPI app + lifespan (tables, seed, poller, agents)
├── frontend/
│   └── app/
│       └── page.tsx             # Dashboard: SWR polling + WebSocket + Framer Motion
├── wdk-service/
│   ├── index.js                 # Node.js WDK microservice (Express + ethers.js)
│   └── package.json             # @tetherto/wdk + wdk-wallet-evm + ethers + express
├── Makefile                     # install / dev / demo / seed / test / clean
├── DEMO_GUIDE.md                # 90-second judge demo script
└── .env.example                 # All environment variables documented
```

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/status` | Agent states, wallet balance, active swarms, tips today |
| `GET` | `/api/metrics` | Totals, top creators, weekly breakdown |
| `GET` | `/api/transactions` | Paginated tip history with tx hashes |
| `GET` | `/api/decisions` | Paginated agent decision log with Claude reasoning |
| `GET` | `/api/swarms` | Active swarm goals with progress |
| `POST` | `/api/swarms` | Create a swarm goal |
| `POST` | `/api/swarms/{id}/join` | Join a swarm with pledged amount |
| `GET` | `/api/preferences` | User agent configuration |
| `PUT` | `/api/preferences` | Update preferences (max tip, token, triggers) |
| `POST` | `/api/demo/{scenario}` | `watch` · `hype` · `milestone` · `swarm` |
| `WS` | `/ws/feed` | Live agent decision stream |

---

## Make Commands

```bash
make install   # pip install + npm install (backend + frontend + wdk-service)
make dev       # Run all 3 services concurrently — FastAPI :8000, Next.js :3000, WDK :3001
make demo      # Seed data → launch all services → open browser
make seed      # Seed database with demo data only
make test      # pytest
make clean     # Remove tipmind.db, .next, __pycache__
```

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | Claude API key — used by all 4 agents |
| `WDK_SEED_PHRASE` | For live tips | 12-word BIP39 mnemonic for WDK wallet |
| `WDK_RPC_URL` | For live tips | Polygon/Ethereum RPC (e.g. `https://polygon-rpc.com`) |
| `WDK_CHAIN` | No | `polygon` (default) or `ethereum` |
| `WDK_API_KEY` | No | Shared secret between Python backend and WDK service |
| `YOUTUBE_CHANNEL_IDS` | No | Comma-separated channel IDs; defaults to 4 public channels |
| `MAX_TIP_PER_VIDEO` | No | Per-video tip cap in USD (default: `5.00`) |
| `DEFAULT_TOKEN` | No | `USDT` (default), `XAUT`, or `BTC` |

---

<div align="center">

Built for the Tether WDK Hackathon · Powered by Claude · On-chain with WDK

</div>
