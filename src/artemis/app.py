"""Compose and run the Artemis proactivity loop."""

from __future__ import annotations

import argparse
import asyncio
import os
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from artemis.ingress import InboundRouter
from artemis.intent import IntentRouter
from artemis.model.claude_code_provider import ClaudeCodeProvider
from artemis.model.compose import build_model_router
from artemis.model.client import ModelClient
from artemis.ports.model import ModelPort
from artemis.ports.secrets import SecretStorePort
from artemis.ports.transport import TransportPort
from artemis.proactivity import ProactiveWorker, build_proactive_worker
from artemis.reachout.web_tool import build_web_tool
from artemis.scheduler import DurableScheduler, ScheduleLedger, build_scheduler
from artemis.secrets_store import KeyringSecretStore
from artemis.secrets_store import resolve_secret
from artemis.transport import ConsoleTransport, telegram_from_env
from artemis.types import ScheduledJob


@dataclass
class App:
    scheduler: DurableScheduler
    worker: ProactiveWorker
    ingress: InboundRouter | None = None

    async def run(self) -> None:
        """Start the always-on heartbeat (runs until cancelled)."""
        if self.ingress is None:
            await self.scheduler.run()
            return

        tasks = [
            asyncio.create_task(self.scheduler.run()),
            asyncio.create_task(self.ingress.run()),
        ]
        try:
            await asyncio.gather(*tasks)
        except BaseException:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise


def build_app(
    *,
    db_path: str = ":memory:",
    owner_identity: str = "console",
    model: ModelPort | None = None,
    transport: TransportPort | None = None,
    secrets: SecretStorePort | None = None,
    anthropic_api_key: str | None = None,
    tick_seconds: float = 1.0,
    enable_ingress: bool = True,
) -> App:
    router = model if model is not None else build_model_router(anthropic_api_key=anthropic_api_key)
    surface = transport if transport is not None else ConsoleTransport()
    worker = build_proactive_worker(model=router, transport=surface, owner_identity=owner_identity)
    scheduler = build_scheduler(dispatch=worker.run_job, db_path=db_path, tick_seconds=tick_seconds)
    ingress = _build_ingress(
        model=router,
        transport=surface,
        owner_identity=owner_identity,
        secrets=secrets,
        enable_ingress=enable_ingress,
    )
    return App(scheduler=scheduler, worker=worker, ingress=ingress)


def _build_ingress(
    *,
    model: ModelPort,
    transport: TransportPort,
    owner_identity: str,
    secrets: SecretStorePort | None,
    enable_ingress: bool,
) -> InboundRouter | None:
    if (
        not enable_ingress
        or isinstance(transport, ConsoleTransport)
        or not hasattr(transport, "receive")
    ):
        return None

    tavily_api_key = (resolve_secret("TAVILY_API_KEY", secrets=secrets) or "").strip()
    return InboundRouter(
        intent=IntentRouter(ModelClient(ClaudeCodeProvider(), model_default="haiku")),
        model=model,
        web_tool=build_web_tool(tavily_api_key=tavily_api_key),
        transport=transport,
        owner_identity=owner_identity,
    )


async def _noop_dispatch(payload: dict) -> None:  # type: ignore[type-arg]
    """Dispatch sink for ledger-only CLI commands (add) that never run a job."""


def cmd_run(args: argparse.Namespace) -> None:
    """Start the always-on heartbeat. Pushes to Telegram if configured, else the console."""
    # Same keychain the brain + keys panel use (keyring lookups are by service+name, so the
    # index path only affects listing) — the bot token resolves keychain-first, env as fallback.
    secrets = KeyringSecretStore(
        Path(os.environ.get("ARTEMIS_DATA_DIR", ".")) / "secrets_index.json"
    )
    telegram = telegram_from_env(os.environ, secrets=secrets)
    if telegram is not None:
        owner_identity = os.environ.get("TELEGRAM_OWNER_CHAT_ID", "")
        app = build_app(
            db_path=args.db,
            transport=telegram,
            owner_identity=owner_identity,
            secrets=secrets,
        )
    else:
        app = build_app(db_path=args.db)
    asyncio.run(app.run())


def cmd_serve(args: argparse.Namespace) -> None:
    """Run the brain HTTP API the Tauri client connects to."""
    import uvicorn

    from artemis.api import create_app

    uvicorn.run(create_app(enable_sync=True), host="127.0.0.1", port=args.port)


def cmd_add(args: argparse.Namespace) -> None:
    if not args.cron and not args.at:
        raise SystemExit("add requires --cron or --at")
    payload: dict[str, str] = {"goal": args.goal}
    if args.context:
        payload["context"] = args.context
    if args.title:
        payload["title"] = args.title
    job = ScheduledJob(id=args.id or uuid4().hex, cron=args.cron, run_at=args.at, payload=payload)
    scheduler = build_scheduler(dispatch=_noop_dispatch, db_path=args.db)
    asyncio.run(scheduler.schedule(job))
    print(f"scheduled {job.id}")


def cmd_list(args: argparse.Namespace) -> None:
    ledger = ScheduleLedger(args.db)
    rows = ledger.active()
    ledger.close()
    if not rows:
        print("(no active jobs)")
        return
    for row in rows:
        when = row.cron or row.run_at or "?"
        label = row.payload.get("title") or row.payload.get("goal") or ""
        print(f"{row.id}  when={when}  next_fire={row.next_fire:.0f}  {label}")


def cmd_cancel(args: argparse.Namespace) -> None:
    ledger = ScheduleLedger(args.db)
    ledger.deactivate(args.id)
    ledger.close()
    print(f"cancelled {args.id}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="artemis", description="Artemis proactivity hub")
    parser.add_argument("--db", default=os.environ.get("ARTEMIS_DB", "scheduler.db"))
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("run", help="start the always-on heartbeat").set_defaults(func=cmd_run)

    p_serve = sub.add_parser("serve", help="run the brain HTTP API (for the desktop client)")
    p_serve.add_argument(
        "--port", type=int, default=int(os.environ.get("ARTEMIS_BRAIN_PORT", "8030"))
    )
    p_serve.set_defaults(func=cmd_serve)

    p_add = sub.add_parser("add", help="schedule a proactive job")
    p_add.add_argument("--goal", required=True, help="what the job asks Artemis to do")
    p_add.add_argument("--cron", help='cron expression, e.g. "0 7 * * *"')
    p_add.add_argument("--at", help="one-shot ISO datetime, e.g. 2026-07-01T07:00:00")
    p_add.add_argument("--title", help="optional message label")
    p_add.add_argument("--context", help="optional extra context")
    p_add.add_argument("--id", help="optional explicit job id")
    p_add.set_defaults(func=cmd_add)

    sub.add_parser("list", help="list active jobs").set_defaults(func=cmd_list)

    p_cancel = sub.add_parser("cancel", help="deactivate a job")
    p_cancel.add_argument("id", help="job id to cancel")
    p_cancel.set_defaults(func=cmd_cancel)

    args = parser.parse_args(argv)
    func = getattr(args, "func", cmd_run)  # bare `artemis` -> run (back-compat)
    func(args)
