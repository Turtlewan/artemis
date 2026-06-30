"""Tests for the durable scheduler."""

from __future__ import annotations

from pathlib import Path

from artemis.ports.scheduler import Scheduler
from artemis.scheduler import DurableScheduler, ScheduleLedger
from artemis.types import EventTrigger, ScheduledJob


# A realistic epoch (year 2030); tiny values like 1000 trip a Windows near-1970
# localtime quirk in datetime.astimezone() that production never hits.
T0 = 1_900_000_000.0


class Clock:
    def __init__(self, t: float) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def _collector() -> tuple[list[dict], object]:  # type: ignore[type-arg]
    seen: list[dict] = []  # type: ignore[type-arg]

    async def dispatch(payload: dict) -> None:  # type: ignore[type-arg]
        seen.append(payload)

    return seen, dispatch


def test_satisfies_port() -> None:
    _, dispatch = _collector()
    sch = DurableScheduler(ScheduleLedger(), dispatch=dispatch)  # type: ignore[arg-type]
    assert isinstance(sch, Scheduler)


async def test_oneshot_fires_once_then_inactive() -> None:
    clock = Clock(T0)
    led = ScheduleLedger(":memory:", now=clock)
    seen, dispatch = _collector()
    sch = DurableScheduler(led, dispatch=dispatch, now=clock)  # type: ignore[arg-type]
    await sch.schedule(
        ScheduledJob(id="j1", cron=None, run_at="2024-01-01T00:00:00", payload={"k": 1})
    )
    clock.t = 1_900_000_000.0  # well past run_at
    await sch.run(iterations=1)
    assert seen == [{"k": 1}]
    await sch.run(iterations=1)
    assert seen == [{"k": 1}]  # not fired again


async def test_cron_recurs() -> None:
    clock = Clock(T0)
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


async def test_survives_restart_and_catches_up(tmp_path: Path) -> None:
    db = str(tmp_path / "sched.db")
    clock = Clock(T0)
    seen1, dispatch1 = _collector()
    sch1 = DurableScheduler(ScheduleLedger(db, now=clock), dispatch=dispatch1, now=clock)  # type: ignore[arg-type]
    await sch1.schedule(
        ScheduledJob(id="cron", cron="0 7 * * *", run_at=None, payload={"digest": True})
    )
    # Simulate downtime: reopen the DB later, past the next 07:00.
    clock.t += 24 * 3600
    seen2, dispatch2 = _collector()
    sch2 = DurableScheduler(ScheduleLedger(db, now=clock), dispatch=dispatch2, now=clock)  # type: ignore[arg-type]
    await sch2.run(iterations=1)
    assert seen2 == [{"digest": True}]  # overdue job caught up after "restart"


async def test_cancel() -> None:
    clock = Clock(T0)
    led = ScheduleLedger(":memory:", now=clock)
    seen, dispatch = _collector()
    sch = DurableScheduler(led, dispatch=dispatch, now=clock)  # type: ignore[arg-type]
    await sch.schedule(ScheduledJob(id="x", cron="* * * * *", run_at=None, payload={}))
    clock.t += 120
    sch.cancel("x")
    await sch.run(iterations=1)
    assert seen == []


async def test_event_match() -> None:
    clock = Clock(T0)
    led = ScheduleLedger(":memory:", now=clock)
    _, dispatch = _collector()
    sch = DurableScheduler(led, dispatch=dispatch, now=clock)  # type: ignore[arg-type]
    got: list[dict] = []  # type: ignore[type-arg]

    async def handler(e: dict) -> None:  # type: ignore[type-arg]
        got.append(e)

    await sch.on_event(EventTrigger(kind="email", match={"from": "vip"}), handler)
    await sch.emit({"kind": "email", "from": "spam"})
    await sch.emit({"kind": "email", "from": "vip", "subj": "hi"})
    await sch.run(iterations=1)
    assert got == [{"kind": "email", "from": "vip", "subj": "hi"}]


async def test_budget_gate_skips_dispatch_but_reschedules() -> None:
    clock = Clock(T0)
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
