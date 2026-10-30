"""FastAPI application entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api import decisions, events, investigations
from app.config import get_settings
from app.database.session import init_db
from app.graph.builder import get_compiled_graph, reset_compiled_graph

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("paintops")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.getLogger().setLevel(settings.log_level.upper())
    init_db()
    # Warm the compiled graph / checkpointer for single-worker MVP.
    try:
        get_compiled_graph()
    except Exception:  # noqa: BLE001
        logger.exception("Failed to warm LangGraph checkpointer")
    logger.info(
        "PaintOps API started (demo_mode=%s, version=%s)",
        settings.demo_mode,
        __version__,
    )
    yield
    reset_compiled_graph()


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
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(events.router)
app.include_router(investigations.router)
app.include_router(decisions.router)


@app.get("/health")
def health() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "demo_mode": settings.demo_mode,
        "version": __version__,
        "notice": "Synthetic decision-support demo only.",
    }
