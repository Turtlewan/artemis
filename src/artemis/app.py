"""Compose and run the Artemis proactivity loop."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass

from artemis.model.compose import build_model_router
from artemis.ports.model import ModelPort
from artemis.ports.transport import TransportPort
from artemis.proactivity import ProactiveWorker, build_proactive_worker
from artemis.scheduler import DurableScheduler, build_scheduler
from artemis.transport import ConsoleTransport


@dataclass
class App:
    scheduler: DurableScheduler
    worker: ProactiveWorker

    async def run(self) -> None:
        """Start the always-on heartbeat (runs until cancelled)."""
        await self.scheduler.run()


def build_app(
    *,
    db_path: str = ":memory:",
    owner_identity: str = "console",
    model: ModelPort | None = None,
    transport: TransportPort | None = None,
    anthropic_api_key: str | None = None,
    tick_seconds: float = 1.0,
) -> App:
    router = model if model is not None else build_model_router(anthropic_api_key=anthropic_api_key)
    surface = transport if transport is not None else ConsoleTransport()
    worker = build_proactive_worker(model=router, transport=surface, owner_identity=owner_identity)
    scheduler = build_scheduler(dispatch=worker.run_job, db_path=db_path, tick_seconds=tick_seconds)
    return App(scheduler=scheduler, worker=worker)


def main() -> None:
    """Console-script entry: run the loop with a file-backed schedule + console transport."""
    db_path = os.environ.get("ARTEMIS_DB", "scheduler.db")
    app = build_app(db_path=db_path)
    asyncio.run(app.run())
