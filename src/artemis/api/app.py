"""FastAPI application factory for the Artemis brain."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str


class StatusResponse(BaseModel):
    """Authenticated app status (ported from v1; auth arrives in CR-2)."""

    connected: bool
    vault_unlocked: bool
    device_id: str


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Placeholder: later slices compose router/memory/scheduler onto app.state here.
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Artemis brain", lifespan=_lifespan)

    @app.get("/healthz", response_model=HealthResponse)
    async def healthz() -> HealthResponse:
        return HealthResponse(status="ok")

    app_router = APIRouter(prefix="/app")

    @app_router.get("/status", response_model=StatusResponse)
    async def status() -> StatusResponse:
        return StatusResponse(connected=False, vault_unlocked=False, device_id="")

    app.include_router(app_router)
    return app
