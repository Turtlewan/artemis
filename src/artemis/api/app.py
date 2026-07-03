"""FastAPI application factory for the Artemis brain."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from pydantic import BaseModel

from artemis.api import ask_routes, bless_routes, capability_routes, domain_routes, oauth_routes
from artemis.api import secret_routes
from artemis.api.auth import AppAuth, ChallengeStore, DeviceRegistry, Principal, SessionStore
from artemis.api.auth import require_session
from artemis.api.auth_routes import PairingCodeStore, RateLimiter, app_router
from artemis.api.layout_store import LayoutDTO, LayoutStore, default_layout
from artemis.capabilities.bless import BlessStore
from artemis.capabilities.fetch_sandbox import FetchSandbox
from artemis.capabilities.forge import CapabilityForge
from artemis.capabilities.sandbox import SandboxRunner
from artemis.capabilities.sandbox_wsl2 import default_sandbox
from artemis.capabilities.select import build_capability_selector
from artemis.capabilities.store import FileCapabilityStore, builtin_capabilities_root
from artemis.data.fetcher import FetcherRunner
from artemis.data.ingest import IngestService
from artemis.data.store import DataStore
from artemis.model.claude_code_provider import ClaudeCodeProvider
from artemis.model.client import ModelClient
from artemis.model.compose import build_model_router
from artemis.oauth.broker import OAuthBroker
from artemis.ports.model import ModelPort
from artemis.ports.secrets import SecretStorePort
from artemis.scheduler.ledger import ScheduleLedger
from artemis.scheduler.scheduler import DurableScheduler
from artemis.secrets_store import KeyringSecretStore
from artemis.types import ScheduledJob


_CALENDAR_SYNC_CRON = "*/15 * * * *"


class HealthResponse(BaseModel):
    status: str


def _calendar_sync_job() -> ScheduledJob:
    return ScheduledJob(
        id="calendar-sync",
        cron=_CALENDAR_SYNC_CRON,
        run_at=None,
        payload={"kind": "fetch", "capability": "calendar-sync", "args": {}},
    )


def _build_sync(app: FastAPI, resolved_data_dir: Path) -> None:
    """Construct the background sync components onto app.state (no async work here)."""
    reader = ModelClient(ClaudeCodeProvider(), model_default="haiku")
    ingest = IngestService(app.state.data_store, reader=reader)
    fetcher = FetcherRunner(
        capability_store=app.state.capability_store,
        secrets_store=app.state.secrets,
        sandbox=app.state.fetch_sandbox,
        ingest=ingest,
        oauth_broker=app.state.oauth_broker,
    )
    app.state.ingest_service = ingest
    app.state.fetcher_runner = fetcher
    app.state.sync_scheduler = DurableScheduler(
        ScheduleLedger(str(resolved_data_dir / "schedule.db"), check_same_thread=False),
        dispatch=fetcher.dispatch,
        tick_seconds=30.0,
    )


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    task: asyncio.Task[None] | None = None
    scheduler = getattr(app.state, "sync_scheduler", None)
    if scheduler is not None:
        await scheduler.schedule(_calendar_sync_job())
        task = asyncio.create_task(scheduler.run())
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


def create_app(
    *,
    data_dir: str | Path | None = None,
    model: ModelPort | None = None,
    sandbox: SandboxRunner | None = None,
    secrets: SecretStorePort | None = None,
    enable_sync: bool = False,
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
    app.state.secrets = (
        secrets
        if secrets is not None
        else KeyringSecretStore(resolved_data_dir / "secrets_index.json")
    )
    # Default opener (webbrowser.open): the brain runs on the local desktop and opens the
    # consent browser itself. The client (oauth-4) has no opener plugin and does not open URLs.
    app.state.oauth_broker = OAuthBroker(secrets_store=app.state.secrets)
    app.state.oauth_connect_task = None
    resolved_sandbox: SandboxRunner = sandbox if sandbox is not None else default_sandbox()
    capability_store = FileCapabilityStore(
        resolved_data_dir / "capabilities", builtin_root=builtin_capabilities_root()
    )
    app.state.capability_store = capability_store
    app.state.bless = BlessStore(resolved_data_dir / "bless.json")
    app.state.forge = CapabilityForge(app.state.model, capability_store, resolved_sandbox)
    app.state.builds = {}  # build_id -> capability_routes.BuildState (in-memory, interim)
    app.state.capability_selector = build_capability_selector(capability_store)
    app.state.fetch_sandbox = FetchSandbox()
    app.state.invokes = {}  # invoke_id -> invoke.InvokeState (in-memory, interim)
    app.state.data_store = DataStore(str(resolved_data_dir / "spine.db"))
    if enable_sync:
        _build_sync(app, resolved_data_dir)

    @app.get("/healthz", response_model=HealthResponse)
    async def healthz() -> HealthResponse:
        return HealthResponse(status="ok")

    app.include_router(app_router)
    app.include_router(ask_routes.router)
    app.include_router(bless_routes.router)
    app.include_router(capability_routes.router)
    app.include_router(domain_routes.router)
    app.include_router(oauth_routes.router)
    app.include_router(secret_routes.router)
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
