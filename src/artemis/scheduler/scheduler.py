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


def _cron_next(cron: str, base: float) -> float:
    """Next epoch fire time for a cron expr, from ``base`` (epoch seconds).

    croniter is fed a timezone-aware *local* datetime so cron is evaluated against the local wall
    clock ("0 7 * * *" = 07:00 local) and ``get_next(float)`` returns a correct epoch; a naive base
    would desync the returned timestamp by the UTC offset.
    """
    itr = croniter(cron, datetime.fromtimestamp(base).astimezone())
    return float(itr.get_next(float))


def _next_fire(job: ScheduledJob, *, base: float) -> float:
    """Next epoch fire time for a job, from ``base`` (epoch seconds)."""
    if job.cron is not None:
        return _cron_next(job.cron, base)
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
        """Heartbeat: each tick fire due jobs + drain the event queue.

        ``iterations`` bounds the loop for tests; ``None`` runs forever.
        """
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
            self._ledger.reschedule(row.id, next_fire=_cron_next(row.cron, now))
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
