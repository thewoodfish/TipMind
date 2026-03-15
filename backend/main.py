from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from backend.config import config
from backend.data.database import create_all_tables
from backend.api.routes import router
from backend.api.websocket import websocket_endpoint, ws_feed_endpoint, register_event_handlers
from backend.core.orchestrator import orchestrator
from backend.core.poller import poller
from backend.demo.seed import run_seed


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting TipMind...")
    await create_all_tables()
    await run_seed()
    register_event_handlers()
    orchestrator.start()

    # Start autonomous YouTube poller
    channel_ids = [
        cid.strip()
        for cid in config.youtube_channel_ids.split(",")
        if cid.strip()
    ]
    poller.configure(channel_ids)
    poller.start()

    logger.info("TipMind ready — listening on http://0.0.0.0:8000")
    yield

    poller.stop()
    logger.info("TipMind shutting down")


app = FastAPI(
    title="TipMind",
    description="AI-powered autonomous crypto tipping for video creators",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")
app.add_api_websocket_route("/ws/feed", ws_feed_endpoint)
app.add_api_websocket_route("/ws", websocket_endpoint)           # legacy


@app.get("/")
async def root():
    return {
        "name":    "TipMind",
        "version": "0.1.0",
        "status":  "running",
        "docs":    "/docs",
        "ws_feed": "ws://localhost:8000/ws/feed",
        "poller":  poller.status(),
    }


if __name__ == "__main__":
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
