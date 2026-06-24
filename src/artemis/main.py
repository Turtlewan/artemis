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
from artemis.api_app import DefaultDomainReadSource, PairingCodeStore, RateLimiter, app_router
from artemis.app_layout_store import LayoutStore
from artemis.config import get_settings
from artemis.gateway import Gateway, compose_brain
from artemis.identity.app_auth import AppAuth, ChallengeStore, DeviceRegistry, SessionStore
from artemis.identity.broker_client import BrokerClient, BrokerKeyProvider
from artemis.paths import devices_file, identity_dir
from artemis.recipes.promotion import Promoter, RecurrenceStore
from artemis.recipes.review import ReviewSurface
from artemis.recipes.store import RecipeStore, recipes_dir


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialise the shared Gateway on startup."""
    settings = get_settings()
    from artemis.adapters.model_adapters import OpenAIEmbeddingModel

    embedder = OpenAIEmbeddingModel(settings)
    brain = compose_brain(settings, embedder=embedder)
    registry = DeviceRegistry(devices_file(settings))
    recurrence = RecurrenceStore(recipes_dir(settings) / "recurrence.json")
    store = RecipeStore(embedder, recipes_dir(settings))
    promoter = Promoter(store, recurrence)
    broker_client = BrokerClient(identity_dir(settings) / "broker.sock")
    key_provider = BrokerKeyProvider(broker_client, _relay_prover)
    if settings.slot == "prod" and not isinstance(key_provider, BrokerKeyProvider):
        raise RuntimeError("production app requires the real BrokerKeyProvider")

    app.state.gateway = Gateway(brain)
    app.state.app_auth = AppAuth(registry, ChallengeStore(), SessionStore())
    app.state.broker_client = broker_client
    app.state.key_provider = key_provider
    app.state.review_surface = ReviewSurface(store, promoter)
    app.state.pairing_codes = PairingCodeStore()
    app.state.rate_limiter = RateLimiter()
    app.state.layout_store = LayoutStore(identity_dir(settings) / "layout.json")
    app.state.domain_read_source = DefaultDomainReadSource()
    yield


def _relay_prover(*_args: object) -> dict[str, object]:
    """Placeholder because vault unlock proofs are relayed through `/app/unlock/*`."""
    raise NotImplementedError("vault unlock is relayed via /app/unlock/*")


app = FastAPI(lifespan=lifespan)

# Mount M1-c surfaces
app.include_router(m1c_router)
app.include_router(app_router)


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
