"""Artemis brain FastAPI application — health + brain surfaces.

M0-b: health stub endpoints (``/healthz``, ``/readyz``).
M1-c: mounts the HTTP API router (``/ask``, ``/ask/stream``)
       and initialises the shared ``Gateway`` on startup.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from artemis.api import router as m1c_router
from artemis.config import get_settings
from artemis.gateway import Gateway, compose_brain


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialise the shared Gateway on startup."""
    settings = get_settings()
    brain = compose_brain(settings)
    app.state.gateway = Gateway(brain)
    yield


app = FastAPI(lifespan=lifespan)

# Mount M1-c surfaces
app.include_router(m1c_router)


@app.get("/healthz")
async def healthz() -> dict[str, object]:
    """Liveness probe — no dependencies."""
    settings = get_settings()
    return {"status": "ok", "slot": settings.slot}


@app.get("/readyz")
async def readyz() -> dict[str, object]:
    """Readiness probe — stub for M0.

    Returns ``ok`` with an empty checks dict until real engines exist.
    """
    return {"status": "ok", "checks": {}}
