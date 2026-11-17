"""FastAPI application entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api import decisions, events, investigations, plant
from app.config import DEFAULT_API_KEY, get_settings
from app.database.session import init_db
from app.graph.builder import open_graph
from app.services.run_manager import RunManager, set_run_manager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("paintops")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.getLogger().setLevel(settings.log_level.upper())
    init_db()
    if settings.paintops_api_key == DEFAULT_API_KEY:
        logger.warning("PAINTOPS_API_KEY is the built-in development default; set your own in .env.")
    # The async checkpointer's connection lives exactly as long as the app.
    async with open_graph():
        manager = RunManager()
        set_run_manager(manager)
        logger.info(
            "PaintOps API started (demo_mode=%s, version=%s)",
            settings.demo_mode,
            __version__,
        )
        try:
            yield
        finally:
            await manager.shutdown()
            set_run_manager(None)


app = FastAPI(
    title="PaintOps API",
    description=(
        "SYNTHETIC decision-support demo for automotive paint quality deviation "
        "investigation. Not for production industrial decisions."
    ),
    version=__version__,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-PaintOps-Key", "Last-Event-ID"],
)

app.include_router(events.router)
app.include_router(investigations.router)
app.include_router(decisions.router)
app.include_router(plant.router)


@app.get("/health")
def health() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "demo_mode": settings.demo_mode,
        "version": __version__,
        "notice": "Synthetic decision-support demo only.",
    }
