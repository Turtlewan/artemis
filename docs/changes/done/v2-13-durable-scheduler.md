---
slice: 3
status: ready
coder_effort: medium
---

# v2-13 — Durable scheduler (time-based + heartbeat)

**Identity:** First Slice-3 spec — a durable, restart-surviving `Scheduler` over a SQLite job ledger + an always-on heartbeat loop that fires due jobs and drains an event queue. Implements `ports/scheduler.py` against architecture.md §6. (Watchers, transport adapters, and wiring the heartbeat to a real spine worker are later Slice-3 specs; this one delivers the clock + the durable store + the loop, with `dispatch` injected as a seam.)

Architecture §6 non-negotiables honored here: **durable** (jobs + next-fire persisted, fire-once catch-up after reboot) · **quota-budgeted** (optional `should_fire` gate before any dispatch) · **gated** (this spec only *dispatches a payload* to an injected sink — it never touches the outside world itself).

## Files to change

1. `pyproject.toml` — **modify**: add the cron-math dependency + its stubs.
2. `src/artemis/scheduler/__init__.py` — **create**: module exports.
3. `src/artemis/scheduler/ledger.py` — **create**: `ScheduleLedger` (SQLite, mirrors `memory/ledger.py`).
4. `src/artemis/scheduler/scheduler.py` — **create**: `DurableScheduler` (implements the port) + `build_scheduler` factory.
5. `tests/test_scheduler.py` — **create**: ledger + scheduler + durability/catch-up + event + budget-gate tests.

One cohesive new module (`scheduler/`) + its test + a one-line dep add → a single logical phase.

## Exact changes

### 1. `pyproject.toml`

- Append `"croniter>=2"` to `[project].dependencies` (core — proactivity is core, not optional).
- Append `"types-croniter"` to the `dev` list under `[dependency-groups]` (keeps `mypy --strict` clean; no per-module override needed).

Resulting lines:
```toml
dependencies = ["jsonschema>=4", "pydantic>=2", "pyyaml>=6", "anthropic>=0.40", "httpx>=0.27", "croniter>=2"]
...
dev = ["mypy", "ruff", "pytest", "pytest-asyncio", "types-PyYAML", "types-croniter"]
```

### 2. `src/artemis/scheduler/__init__.py`
```python
"""Durable scheduler: SQLite job ledger + heartbeat loop."""

from __future__ import annotations

from artemis.scheduler.ledger import JobRow, ScheduleLedger
from artemis.scheduler.scheduler import DurableScheduler, build_scheduler

__all__ = ["DurableScheduler", "JobRow", "ScheduleLedger", "build_scheduler"]
```

### 3. `src/artemis/scheduler/ledger.py`

Mirror `memory/ledger.py`: sync `sqlite3`, injectable `now`, never delete (cancel/one-shot-fire flip `active=0`). `payload` stored as JSON text.

```python
"""SQLite ledger for durable scheduled jobs."""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import cast

from artemis.types import ScheduledJob


@dataclass(frozen=True)
class JobRow:
    id: str
    cron: str | None
    run_at: str | None
    payload: dict  # type: ignore[type-arg]
    next_fire: float


class ScheduleLedger:
    """Per-job schedule state in SQLite. sqlite3 is sync; calls are local + low-volume,
    invoked from the async scheduler."""

    def __init__(self, db_path: str = ":memory:", *, now: Callable[[], float] = time.time) -> None:
        self._now = now
        self._conn = sqlite3.connect(db_path)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS jobs ("
            " id TEXT PRIMARY KEY, cron TEXT, run_at TEXT, payload TEXT,"
            " next_fire REAL, active INTEGER DEFAULT 1, created_at REAL)"
        )
        self._conn.commit()

    def upsert(self, job: ScheduledJob, *, next_fire: float) -> None:
        self._conn.execute(
            "INSERT INTO jobs(id, cron, run_at, payload, next_fire, active, created_at)"
            " VALUES(?,?,?,?,?,1,?)"
            " ON CONFLICT(id) DO UPDATE SET"
            " cron=excluded.cron, run_at=excluded.run_at, payload=excluded.payload,"
            " next_fire=excluded.next_fire, active=1",
            (job.id, job.cron, job.run_at, json.dumps(job.payload), next_fire, self._now()),
        )
        self._conn.commit()

    def due(self, now: float) -> list[JobRow]:
        rows = cast(
            Iterable[tuple[str, str | None, str | None, str, float]],
            self._conn.execute(
                "SELECT id, cron, run_at, payload, next_fire FROM jobs"
                " WHERE active=1 AND next_fire<=? ORDER BY next_fire",
                (now,),
            ),
        )
        return [JobRow(i, c, r, json.loads(p), nf) for (i, c, r, p, nf) in rows]

    def reschedule(self, job_id: str, *, next_fire: float) -> None:
        self._conn.execute("UPDATE jobs SET next_fire=? WHERE id=?", (next_fire, job_id))
        self._conn.commit()

    def deactivate(self, job_id: str) -> None:
        """One-shot fired or job cancelled — never delete the row."""
        self._conn.execute("UPDATE jobs SET active=0 WHERE id=?", (job_id,))
        self._conn.commit()

    def active(self) -> list[JobRow]:
        rows = cast(
            Iterable[tuple[str, str | None, str | None, str, float]],
            self._conn.execute(
                "SELECT id, cron, run_at, payload, next_fire FROM jobs WHERE active=1"
            ),
        )
        return [JobRow(i, c, r, json.loads(p), nf) for (i, c, r, p, nf) in rows]

    def close(self) -> None:
        self._conn.close()
```

### 4. `src/artemis/scheduler/scheduler.py`

Implements `ports/scheduler.py`. `dispatch` is the injected sink that runs a job payload (wired to the spine worker in a later spec). `should_fire` is the optional quota-budget gate. `next-fire` is computed by croniter (cron) or ISO parse (`run_at`).

```python
"""Durable, restart-surviving scheduler with an always-on heartbeat loop."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from uuid import uuid4

from croniter import croniter

from artemis.scheduler.ledger import JobRow, ScheduleLedger
from artemis.types import EventTrigger, ScheduledJob

Handler = Callable[[dict], Awaitable[None]]  # type: ignore[type-arg]
Dispatch = Callable[[dict], Awaitable[None]]  # type: ignore[type-arg]
Budget = Callable[[dict], bool]  # type: ignore[type-arg]


def _next_fire(job: ScheduledJob, *, base: float) -> float:
    """Next epoch fire time for a job, from `base` (epoch seconds)."""
    if job.cron is not None:
        itr = croniter(job.cron, datetime.fromtimestamp(base))
        return float(itr.get_next(float))
    if job.run_at is not None:
        return datetime.fromisoformat(job.run_at).timestamp()
    raise ValueError(f"job {job.id} has neither cron nor run_at")


class DurableScheduler:
    """One engine, two trigger types (time-based jobs + events) feeding one heartbeat loop."""

    def __init__(
        self,
        ledger: ScheduleLedger,
        *,
        dispatch: Dispatch,
        now: Callable[[], float] = time.time,
        tick_seconds: float = 1.0,
        should_fire: Budget | None = None,
    ) -> None:
        self._ledger = ledger
        self._dispatch = dispatch
        self._now = now
        self._tick = tick_seconds
        self._should_fire = should_fire
        self._handlers: list[tuple[EventTrigger, Handler]] = []
        self._events: asyncio.Queue[dict] = asyncio.Queue()  # type: ignore[type-arg]

    async def schedule(self, job: ScheduledJob) -> str:
        self._ledger.upsert(job, next_fire=_next_fire(job, base=self._now()))
        return job.id

    async def on_event(self, trigger: EventTrigger, handler: Handler) -> str:
        self._handlers.append((trigger, handler))
        return uuid4().hex

    async def emit(self, event: dict) -> None:  # type: ignore[type-arg]
        """Ingress seam for watchers (built in a later spec) to inject events."""
        await self._events.put(event)

    def cancel(self, job_id: str) -> None:
        self._ledger.deactivate(job_id)

    async def run(self, *, iterations: int | None = None) -> None:
        """Heartbeat: each tick fire due jobs + drain the event queue. `iterations`
        bounds the loop for tests; None = run forever."""
        count = 0
        while iterations is None or count < iterations:
            await self._tick_once()
            count += 1
            if iterations is None or count < iterations:
                await asyncio.sleep(self._tick)

    async def _tick_once(self) -> None:
        now = self._now()
        for row in self._ledger.due(now):
            await self._fire(row, now=now)
        while not self._events.empty():
            event = self._events.get_nowait()
            for trigger, handler in self._handlers:
                if _matches(trigger, event):
                    await handler(event)

    async def _fire(self, row: JobRow, *, now: float) -> None:
        if self._should_fire is None or self._should_fire(row.payload):
            await self._dispatch(row.payload)
        if row.cron is not None:
            # Recurring: advance to the next future slot (fire-once catch-up after downtime).
            itr = croniter(row.cron, datetime.fromtimestamp(now))
            self._ledger.reschedule(row.id, next_fire=float(itr.get_next(float)))
        else:
            self._ledger.deactivate(row.id)  # one-shot run_at


def _matches(trigger: EventTrigger, event: dict) -> bool:  # type: ignore[type-arg]
    if event.get("kind") != trigger.kind:
        return False
    return all(event.get(k) == v for k, v in trigger.match.items())


def build_scheduler(
    *,
    dispatch: Dispatch,
    db_path: str = ":memory:",
    tick_seconds: float = 1.0,
    should_fire: Budget | None = None,
) -> DurableScheduler:
    """Factory: wire a file-backed ledger to a heartbeat scheduler."""
    return DurableScheduler(
        ScheduleLedger(db_path),
        dispatch=dispatch,
        tick_seconds=tick_seconds,
        should_fire=should_fire,
    )
```

Notes for the coder:
- `DurableScheduler` structurally satisfies `ports.scheduler.Scheduler` (`schedule`/`on_event`/`run`/`cancel`); `cancel` stays **sync** to match the port. Do not add an explicit `Scheduler` base — the port is a `runtime_checkable` Protocol (duck-typed), consistent with the other engines.
- Catch-up semantics: a job whose persisted `next_fire` is in the past (e.g. the box was off) is returned by `due()` on the first tick and fires **once**, then a cron job advances to the next future slot — we do **not** replay every missed occurrence. Document this inline.
- `tick_seconds` defaults to 1.0 for production; tests pass a controllable `now` and `iterations=1` (no real sleep on the bounded path because the final iteration skips the `asyncio.sleep`).

### 5. `tests/test_scheduler.py`

A mutable clock drives time; `dispatch` records payloads. Cover: ledger round-trip, one-shot fire+deactivate, cron recurrence advance, **durability/catch-up across a simulated restart (file DB reopened)**, cancel, event match, and the budget gate.

```python
"""Tests for the durable scheduler."""

from __future__ import annotations

from artemis.scheduler import DurableScheduler, ScheduleLedger
from artemis.types import EventTrigger, ScheduledJob


class Clock:
    def __init__(self, t: float) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def _collector() -> tuple[list[dict], object]:
    seen: list[dict] = []

    async def dispatch(payload: dict) -> None:
        seen.append(payload)

    return seen, dispatch


async def test_oneshot_fires_once_then_inactive() -> None:
    clock = Clock(1000.0)
    led = ScheduleLedger(":memory:", now=clock)
    seen, dispatch = _collector()
    sch = DurableScheduler(led, dispatch=dispatch, now=clock)  # type: ignore[arg-type]
    await sch.schedule(ScheduledJob(id="j1", cron=None, run_at="2024-01-01T00:00:00", payload={"k": 1}))
    clock.t = 1_900_000_000.0  # well past run_at
    await sch.run(iterations=1)
    assert seen == [{"k": 1}]
    await sch.run(iterations=1)
    assert seen == [{"k": 1}]  # not fired again


async def test_cron_recurs() -> None:
    clock = Clock(1000.0)
    led = ScheduleLedger(":memory:", now=clock)
    seen, dispatch = _collector()
    sch = DurableScheduler(led, dispatch=dispatch, now=clock)  # type: ignore[arg-type]
    await sch.schedule(ScheduledJob(id="d", cron="* * * * *", run_at=None, payload={"d": 1}))
    clock.t += 120  # two minutes later
    await sch.run(iterations=1)
    assert seen == [{"d": 1}]
    clock.t += 120
    await sch.run(iterations=1)
    assert seen == [{"d": 1}, {"d": 1}]  # fired again on next tick


async def test_survives_restart_and_catches_up(tmp_path) -> None:  # type: ignore[no-untyped-def]
    db = str(tmp_path / "sched.db")
    clock = Clock(1000.0)
    led = ScheduleLedger(db, now=clock)
    led.close.__self__  # noqa: B018  (keep ref legible)
    seen1, dispatch1 = _collector()
    sch1 = DurableScheduler(ScheduleLedger(db, now=clock), dispatch=dispatch1, now=clock)  # type: ignore[arg-type]
    await sch1.schedule(ScheduledJob(id="cron", cron="0 7 * * *", run_at=None, payload={"digest": True}))
    # Simulate downtime: reopen the DB later, past the next 07:00.
    clock.t += 24 * 3600
    seen2, dispatch2 = _collector()
    sch2 = DurableScheduler(ScheduleLedger(db, now=clock), dispatch=dispatch2, now=clock)  # type: ignore[arg-type]
    await sch2.run(iterations=1)
    assert seen2 == [{"digest": True}]  # overdue job caught up after "restart"


async def test_cancel() -> None:
    clock = Clock(1000.0)
    led = ScheduleLedger(":memory:", now=clock)
    seen, dispatch = _collector()
    sch = DurableScheduler(led, dispatch=dispatch, now=clock)  # type: ignore[arg-type]
    await sch.schedule(ScheduledJob(id="x", cron="* * * * *", run_at=None, payload={}))
    clock.t += 120
    sch.cancel("x")
    await sch.run(iterations=1)
    assert seen == []


async def test_event_match() -> None:
    clock = Clock(1000.0)
    led = ScheduleLedger(":memory:", now=clock)
    _, dispatch = _collector()
    sch = DurableScheduler(led, dispatch=dispatch, now=clock)  # type: ignore[arg-type]
    got: list[dict] = []

    async def handler(e: dict) -> None:
        got.append(e)

    await sch.on_event(EventTrigger(kind="email", match={"from": "vip"}), handler)
    await sch.emit({"kind": "email", "from": "spam"})
    await sch.emit({"kind": "email", "from": "vip", "subj": "hi"})
    await sch.run(iterations=1)
    assert got == [{"kind": "email", "from": "vip", "subj": "hi"}]


async def test_budget_gate_skips_dispatch_but_reschedules() -> None:
    clock = Clock(1000.0)
    led = ScheduleLedger(":memory:", now=clock)
    seen, dispatch = _collector()
    sch = DurableScheduler(led, dispatch=dispatch, now=clock, should_fire=lambda _p: False)  # type: ignore[arg-type]
    await sch.schedule(ScheduledJob(id="g", cron="* * * * *", run_at=None, payload={"x": 1}))
    clock.t += 120
    await sch.run(iterations=1)
    assert seen == []
    # still advanced (not stuck re-firing): next tick at same clock is not due
    await sch.run(iterations=1)
    assert seen == []
```

> Coder: drop the stray `led.close.__self__` debug line in `test_survives_restart_and_catches_up` — it's noise from drafting; the test only needs the two reopened `ScheduleLedger(db)` instances. Keep the first `led` only if a clean `led.close()` is wanted before reopen (optional on sqlite).

## Acceptance criteria

1. `croniter` resolves and imports — `uv run python -c "import croniter"` exits 0.
2. **One-shot fires exactly once** → `test_oneshot_fires_once_then_inactive` passes.
3. **Cron recurs** across ticks → `test_cron_recurs` passes.
4. **Durable + catch-up after restart** (the slice's headline proof, scoped to scheduler) → `test_survives_restart_and_catches_up` passes.
5. **Cancel** stops a job → `test_cancel` passes.
6. **Event trigger matches on kind + match dict** → `test_event_match` passes.
7. **Budget gate** skips dispatch yet advances the schedule → `test_budget_gate_skips_dispatch_but_reschedules` passes.
8. `DurableScheduler` satisfies the port: `isinstance(DurableScheduler(...), Scheduler)` is `True` (runtime_checkable).
9. Full-project verify green: `uv run mypy` (strict, 0 errors) + `uv run pytest -q` (all pass) + `uv run ruff check` clean + `uv run ruff format --check` clean on the new files.

## Commands to run

```bash
uv sync
uv run ruff format src/artemis/scheduler tests/test_scheduler.py
uv run ruff check src/artemis/scheduler tests/test_scheduler.py
uv run mypy
uv run pytest -q
```
