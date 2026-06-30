---
slice: 3
status: ready
coder_effort: medium
---

# v2-17 — Schedule-management CLI (add / list / cancel / run)

**Identity:** Fifth Slice-3 spec — makes the stack usable from the command line. Turns the `artemis` entry point from "only starts the loop" into a small argparse CLI: `artemis add` schedules a cron/one-shot proactive job into the durable ledger, `artemis list` shows active jobs, `artemis cancel <id>` deactivates one, `artemis run` (and bare `artemis`, for back-compat) starts the heartbeat. This unblocks the Telegram go-live demo (you can now schedule a near-future job without writing Python).

All in `app.py` — the console-script already points at `artemis.app:main`, so no `pyproject` change. The CLI reuses the existing `ScheduleLedger` / `DurableScheduler` / `build_app`; no new engine code.

## Files to change

1. `src/artemis/app.py` — **modify**: replace `main()` with an argparse CLI + `cmd_run/cmd_add/cmd_list/cmd_cancel` + a no-op dispatch helper; add imports. Leave `App` and `build_app` unchanged.
2. `tests/test_cli.py` — **create**: add→list→cancel round-trip + validation tests against a temp DB.

Two files, one cohesive "CLI" vertical → a single logical phase.

## Exact changes

### 1. `src/artemis/app.py`

Keep `App` and `build_app` exactly as they are. Update the import block and replace the `main()` function (the current `main()` is fully superseded by `cmd_run` + the argparse `main`).

Replace the import block (lines ~3–14) with:
```python
from __future__ import annotations

import argparse
import asyncio
import os
from dataclasses import dataclass
from uuid import uuid4

from artemis.model.compose import build_model_router
from artemis.ports.model import ModelPort
from artemis.ports.transport import TransportPort
from artemis.proactivity import ProactiveWorker, build_proactive_worker
from artemis.scheduler import DurableScheduler, ScheduleLedger, build_scheduler
from artemis.transport import ConsoleTransport, telegram_from_env
from artemis.types import ScheduledJob
```
(`argparse`, `uuid4`, `ScheduleLedger`, `ScheduledJob` are the additions; `ScheduleLedger` is added to the existing `artemis.scheduler` import.)

Replace `def main() -> None:` and its body with:
```python
async def _noop_dispatch(payload: dict) -> None:  # type: ignore[type-arg]
    """Dispatch sink for ledger-only CLI commands (add) that never run a job."""


def cmd_run(args: argparse.Namespace) -> None:
    """Start the always-on heartbeat. Pushes to Telegram if configured, else the console."""
    telegram = telegram_from_env(os.environ)
    if telegram is not None:
        owner_identity = os.environ.get("TELEGRAM_OWNER_CHAT_ID", "")
        app = build_app(db_path=args.db, transport=telegram, owner_identity=owner_identity)
    else:
        app = build_app(db_path=args.db)
    asyncio.run(app.run())


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
```

Notes for the coder:
- `App` and `build_app` are unchanged — only the import block and `main()` region are touched.
- `cmd_add` uses a `DurableScheduler` with a no-op dispatch purely to reuse `schedule()` (which computes `next_fire` via croniter / ISO and persists to the ledger) — the dispatch is never invoked by `add`.
- `--db` is a top-level argument; place it before the subcommand on the command line (`artemis --db X add ...`). Do not duplicate it per-subcommand.
- mypy: `argparse.Namespace` attributes are `Any`, so `args.goal` etc. need no annotations; `getattr(args, "func", cmd_run)` gives the bare-`artemis` default.

### 2. `tests/test_cli.py`
```python
"""Tests for the artemis schedule-management CLI."""

from __future__ import annotations

from pathlib import Path

import pytest

from artemis.app import main


def test_add_list_cancel_roundtrip(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db = str(tmp_path / "s.db")
    main(["--db", db, "add", "--id", "j1", "--goal", "digest", "--cron", "0 7 * * *", "--title", "Morning"])
    assert "scheduled j1" in capsys.readouterr().out

    main(["--db", db, "list"])
    listed = capsys.readouterr().out
    assert "j1" in listed and "Morning" in listed

    main(["--db", db, "cancel", "j1"])
    assert "cancelled j1" in capsys.readouterr().out

    main(["--db", db, "list"])
    assert "j1" not in capsys.readouterr().out


def test_add_oneshot(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db = str(tmp_path / "s.db")
    main(["--db", db, "add", "--id", "once", "--goal", "g", "--at", "2030-01-01T07:00:00"])
    main(["--db", db, "list"])
    assert "once" in capsys.readouterr().out


def test_add_requires_cron_or_at(tmp_path: Path) -> None:
    db = str(tmp_path / "s.db")
    with pytest.raises(SystemExit):
        main(["--db", db, "add", "--goal", "no schedule"])


def test_list_empty(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["--db", str(tmp_path / "s.db"), "list"])
    assert "no active jobs" in capsys.readouterr().out
```

## Acceptance criteria

1. **add → list → cancel round-trip** persists, shows, and deactivates a cron job → `test_add_list_cancel_roundtrip` passes.
2. **One-shot `--at`** schedules and lists → `test_add_oneshot` passes.
3. **add with neither `--cron` nor `--at`** exits non-zero → `test_add_requires_cron_or_at` passes.
4. **Empty list** prints a friendly message → `test_list_empty` passes.
5. Bare `artemis` (no subcommand) defaults to `cmd_run` (verified by code review — it starts the forever-loop, not runtime-tested).
6. `App` / `build_app` are unchanged (no behavioural diff outside `main()` + imports); existing `tests/test_app.py` still passes.
7. Full-project verify green: `uv run mypy` (strict) + `uv run pytest -q` + `uv run ruff check` + `uv run ruff format --check`.

## Commands to run

```bash
uv run ruff format src/artemis/app.py tests/test_cli.py
uv run ruff check src/artemis/app.py tests/test_cli.py
uv run mypy
uv run pytest -q
```
