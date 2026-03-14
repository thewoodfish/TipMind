from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from backend.data.database import create_all_tables, AsyncSessionLocal
from backend.api.routes import router
from backend.api.websocket import websocket_endpoint, register_event_handlers
from backend.agents.tip_agent import WatchTimeTipAgent
from backend.agents.emotion_agent import EmotionChatAgent


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting TipMind...")
    await create_all_tables()
    register_event_handlers()
    WatchTimeTipAgent(db_session_factory=AsyncSessionLocal).subscribe()
    EmotionChatAgent(db_session_factory=AsyncSessionLocal).subscribe()
    logger.info("TipMind ready")
    yield
    logger.info("TipMind shutting down")


app = FastAPI(
    title="TipMind",
    description="AI-powered crypto tipping for video creators",
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

app.include_router(router, prefix="/api/v1")
app.add_api_websocket_route("/ws", websocket_endpoint)


@app.get("/")
async def root():
    return {"name": "TipMind", "version": "0.1.0", "status": "running"}
