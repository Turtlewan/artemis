"""FastAPI application factory for the Artemis brain."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from pydantic import BaseModel

from artemis.api import ask_routes, capability_routes, domain_routes
from artemis.api.auth import AppAuth, ChallengeStore, DeviceRegistry, Principal, SessionStore
from artemis.api.auth import require_session
from artemis.api.auth_routes import PairingCodeStore, RateLimiter, app_router
from artemis.api.layout_store import LayoutDTO, LayoutStore, default_layout
from artemis.capabilities.forge import CapabilityForge
from artemis.capabilities.sandbox import SandboxRunner, SubprocessSandbox
from artemis.capabilities.store import FileCapabilityStore
from artemis.model.compose import build_model_router
from artemis.ports.model import ModelPort


class HealthResponse(BaseModel):
    status: str


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Placeholder: later slices compose router/memory/scheduler onto app.state here.
    yield


def create_app(
    *,
    data_dir: str | Path | None = None,
    model: ModelPort | None = None,
    sandbox: SandboxRunner | None = None,
) -> FastAPI:
    resolved_data_dir = (
        Path(data_dir) if data_dir is not None else Path(os.environ.get("ARTEMIS_DATA_DIR", "."))
    )
    app = FastAPI(title="Artemis brain", lifespan=_lifespan)
    registry = DeviceRegistry(resolved_data_dir / "devices.json")
    app.state.app_auth = AppAuth(registry, ChallengeStore(), SessionStore())
    app.state.pairing_codes = PairingCodeStore()
    app.state.rate_limiter = RateLimiter()
    app.state.layout_store = LayoutStore(resolved_data_dir / "layout.json")
    app.state.model = model if model is not None else build_model_router()
    resolved_sandbox: SandboxRunner = sandbox if sandbox is not None else SubprocessSandbox()
    app.state.forge = CapabilityForge(
        app.state.model,
        FileCapabilityStore(resolved_data_dir / "capabilities"),
        resolved_sandbox,
    )
    app.state.builds = {}  # build_id -> capability_routes.BuildState (in-memory, interim)

    @app.get("/healthz", response_model=HealthResponse)
    async def healthz() -> HealthResponse:
        return HealthResponse(status="ok")

    app.include_router(app_router)
    app.include_router(ask_routes.router)
    app.include_router(capability_routes.router)
    app.include_router(domain_routes.router)
    return app


@app_router.get("/layout", response_model=LayoutDTO)
async def get_layout(request: Request, _p: Principal = Depends(require_session)) -> LayoutDTO:
    store: LayoutStore = request.app.state.layout_store
    return store.get() or default_layout()


@app_router.put("/layout", response_model=LayoutDTO)
async def put_layout(
    body: LayoutDTO, request: Request, _p: Principal = Depends(require_session)
) -> LayoutDTO:
    store: LayoutStore = request.app.state.layout_store
    return store.put(body)
