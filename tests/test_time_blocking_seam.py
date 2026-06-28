from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import cast

import pytest

from artemis.config import Settings
from artemis.identity.key_provider import FakeKeyProvider
from artemis.identity.scope import OWNER_PRIVATE
from artemis.modules.calendar.preferences import CalPrefs
from artemis.modules.calendar.read_tools import FindTimeArgs, FindTimeResult, FreeSlot
from artemis.modules.calendar.schedule_task import (
    ScheduledBlock,
    ScheduleTaskArgs,
    ScheduleTaskResult,
    schedule_task,
)
from artemis.modules.calendar.write_tools import (
    BlockFocusTimeArgs,
    CalendarWriteTools,
    CancelEventArgs,
    WriteResult,
)
from artemis.modules.productivity import tools
from artemis.modules.productivity.manifest import tasks_manifest
from artemis.modules.productivity.store import ProductivityStore


class FakeCalendarWriteTools:
    def __init__(self, calls: list[str] | None = None) -> None:
        self.block_focus_time_calls: list[BlockFocusTimeArgs] = []
        self.cancel_event_calls: list[CancelEventArgs] = []
        self.calls = calls if calls is not None else []

    async def block_focus_time(self, args: BlockFocusTimeArgs) -> WriteResult:
        self.calls.append("block_focus_time")
        self.block_focus_time_calls.append(args)
        return WriteResult(
            event_id="evt-123",
            summary=args.title,
            status="executed",
            tool_name="calendar.block_focus_time",
        )

    async def cancel_event(self, args: CancelEventArgs) -> WriteResult:
        self.calls.append("cancel_event")
        self.cancel_event_calls.append(args)
        return WriteResult(
            event_id=args.event_id,
            summary=args.event_id,
            status="executed",
            tool_name="calendar.cancel_event",
        )


async def test_schedule_task_happy_path() -> None:
    prefs = _prefs()
    fake_wt = FakeCalendarWriteTools()

    async def find_time_fn(args: FindTimeArgs) -> FindTimeResult:
        assert args.duration_minutes == 60
        return FindTimeResult(slots=[_slot()])

    result = await schedule_task(
        ScheduleTaskArgs(task_id="t1", task_title="Buy milk"),
        write_tools=cast(CalendarWriteTools, fake_wt),
        find_time_fn=find_time_fn,
        prefs=prefs,
    )

    assert result.scheduled is not None
    assert result.scheduled.event_id == "evt-123"
    assert result.scheduled.start_dt == "2026-06-10T10:00:00Z"
    assert result.scheduled.calendar_id == "primary"
    assert result.message
    assert len(fake_wt.block_focus_time_calls) == 1
    assert fake_wt.block_focus_time_calls[0].title == "[Task] Buy milk"


async def test_schedule_task_no_slot_does_not_write() -> None:
    fake_wt = FakeCalendarWriteTools()

    async def find_time_fn(args: FindTimeArgs) -> FindTimeResult:
        del args
        return FindTimeResult(slots=[])

    result = await schedule_task(
        ScheduleTaskArgs(task_id="t1", task_title="Buy milk"),
        write_tools=cast(CalendarWriteTools, fake_wt),
        find_time_fn=find_time_fn,
        prefs=_prefs(),
    )

    assert result.scheduled is None
    assert result.message
    assert fake_wt.block_focus_time_calls == []


async def test_schedule_task_prefers_earliest_slot_within_focus_window() -> None:
    fake_wt = FakeCalendarWriteTools()

    async def find_time_fn(args: FindTimeArgs) -> FindTimeResult:
        del args
        return FindTimeResult(
            slots=[
                _slot_at("2026-06-10T08:30:00Z", "2026-06-10T09:30:00Z"),
                _slot_at("2026-06-10T10:00:00Z", "2026-06-10T11:00:00Z"),
                _slot_at("2026-06-10T14:00:00Z", "2026-06-10T15:00:00Z"),
            ]
        )

    result = await schedule_task(
        ScheduleTaskArgs(task_id="t1", task_title="Buy milk"),
        write_tools=cast(CalendarWriteTools, fake_wt),
        find_time_fn=find_time_fn,
        prefs=_prefs(preferred_focus_window=("09:00", "12:00")),
    )

    assert result.scheduled is not None
    assert result.scheduled.start_dt == "2026-06-10T10:00:00Z"
    assert fake_wt.block_focus_time_calls[0].start_datetime == "2026-06-10T10:00:00Z"


async def test_schedule_task_falls_back_to_earliest_slot_when_none_in_focus_window() -> None:
    fake_wt = FakeCalendarWriteTools()

    async def find_time_fn(args: FindTimeArgs) -> FindTimeResult:
        del args
        return FindTimeResult(
            slots=[
                _slot_at("2026-06-10T14:00:00Z", "2026-06-10T15:00:00Z"),
                _slot_at("2026-06-10T16:00:00Z", "2026-06-10T17:00:00Z"),
            ]
        )

    result = await schedule_task(
        ScheduleTaskArgs(task_id="t1", task_title="Buy milk"),
        write_tools=cast(CalendarWriteTools, fake_wt),
        find_time_fn=find_time_fn,
        prefs=_prefs(preferred_focus_window=("09:00", "12:00")),
    )

    assert result.scheduled is not None
    assert result.scheduled.start_dt == "2026-06-10T14:00:00Z"
    assert fake_wt.block_focus_time_calls[0].start_datetime == "2026-06-10T14:00:00Z"


async def test_schedule_task_estimate_overrides_prefs() -> None:
    seen: list[FindTimeArgs] = []

    async def find_time_fn(args: FindTimeArgs) -> FindTimeResult:
        seen.append(args)
        return FindTimeResult(slots=[_slot()])

    await schedule_task(
        ScheduleTaskArgs(task_id="t1", task_title="Buy milk", estimate_minutes=45),
        write_tools=cast(CalendarWriteTools, FakeCalendarWriteTools()),
        find_time_fn=find_time_fn,
        prefs=_prefs(),
    )

    assert seen[0].duration_minutes == 45


async def test_task_schedule_writes_task_event_link(tmp_path: Path) -> None:
    store = _store(tmp_path)
    task_id = store.create_task("Buy milk", estimate_minutes=60)
    tools.init_tools(store)
    tools.init_write_tools(cast(CalendarWriteTools, FakeCalendarWriteTools()))
    tools.init_schedule_fn(_fake_schedule_fn())

    result = await tools.task_schedule(tools.TaskScheduleArgs(task_id=task_id))
    task = store.get_task(task_id)

    assert task is not None
    assert result.event_id == "evt-456"
    assert result.scheduled_block == "2026-06-10T10:00:00Z"
    assert task["calendar_event_id"] == "evt-456"
    assert task["scheduled_block"] == "2026-06-10T10:00:00Z"


async def test_task_schedule_reschedule_cancels_old_block_first(tmp_path: Path) -> None:
    calls: list[str] = []
    store = _store(tmp_path)
    task_id = store.create_task("Buy milk", estimate_minutes=60)
    store.update_task(
        task_id,
        calendar_event_id="evt-old",
        scheduled_block="2026-06-10T09:00:00Z",
    )
    fake_wt = FakeCalendarWriteTools(calls)

    async def schedule_fn(args: ScheduleTaskArgs) -> ScheduleTaskResult:
        del args
        calls.append("schedule_fn")
        return _scheduled_result()

    tools.init_tools(store)
    tools.init_write_tools(cast(CalendarWriteTools, fake_wt))
    tools.init_schedule_fn(schedule_fn)

    await tools.task_schedule(tools.TaskScheduleArgs(task_id=task_id))
    task = store.get_task(task_id)

    assert task is not None
    assert calls[:2] == ["cancel_event", "schedule_fn"]
    assert fake_wt.cancel_event_calls[0].event_id == "evt-old"
    assert task["calendar_event_id"] == "evt-456"


async def test_task_schedule_without_prior_link_does_not_cancel(tmp_path: Path) -> None:
    store = _store(tmp_path)
    task_id = store.create_task("Buy milk", estimate_minutes=60)
    fake_wt = FakeCalendarWriteTools()
    tools.init_tools(store)
    tools.init_write_tools(cast(CalendarWriteTools, fake_wt))
    tools.init_schedule_fn(_fake_schedule_fn())

    await tools.task_schedule(tools.TaskScheduleArgs(task_id=task_id))

    assert fake_wt.cancel_event_calls == []


async def test_task_schedule_task_not_found(tmp_path: Path) -> None:
    store = _store(tmp_path)
    tools.init_tools(store)
    tools.init_write_tools(cast(CalendarWriteTools, FakeCalendarWriteTools()))
    tools.init_schedule_fn(_fake_schedule_fn())

    result = await tools.task_schedule(tools.TaskScheduleArgs(task_id="missing"))

    assert result.event_id is None
    assert result.scheduled_block is None
    assert "not found" in result.message


async def test_task_complete_clears_task_event_link(tmp_path: Path) -> None:
    store = _store(tmp_path)
    task_id = store.create_task("Buy milk")
    store.update_task(
        task_id,
        calendar_event_id="evt-789",
        scheduled_block="2026-06-10T10:00:00Z",
    )
    tools.init_tools(store)

    await tools.task_complete(tools.TaskCompleteArgs(id=task_id))
    task = store.get_task(task_id)

    assert task is not None
    assert task["calendar_event_id"] is None
    assert task["scheduled_block"] is None


async def test_task_complete_without_link_has_no_error(tmp_path: Path) -> None:
    store = _store(tmp_path)
    task_id = store.create_task("Buy milk")
    tools.init_tools(store)

    await tools.task_complete(tools.TaskCompleteArgs(id=task_id))

    task = store.get_task(task_id)
    assert task is not None
    assert task["status"] == "done"


async def test_task_schedule_uninitialised_schedule_fn_raises(tmp_path: Path) -> None:
    store = _store(tmp_path)
    task_id = store.create_task("Buy milk")
    tools.init_tools(store)
    tools._schedule_fn = None
    tools._write_tools = None

    with pytest.raises(RuntimeError, match="schedule_fn not initialised"):
        await tools.task_schedule(tools.TaskScheduleArgs(task_id=task_id))


def test_tasks_manifest_adds_schedule_tool_only_when_wired(tmp_path: Path) -> None:
    store = _store(tmp_path)
    unwired = tasks_manifest(store)
    full_unwired = tasks_manifest(store, include_write_surface=True)
    wired = tasks_manifest(
        store,
        schedule_fn=_fake_schedule_fn(),
        write_tools=cast(CalendarWriteTools, FakeCalendarWriteTools()),
        include_write_surface=True,
    )
    unwired_names = [tool.name for tool in unwired.tools]
    full_unwired_names = [tool.name for tool in full_unwired.tools]
    wired_names = [tool.name for tool in wired.tools]
    unwired_fq_ids = {f"{unwired.name}.{name}" for name in unwired_names}
    full_unwired_fq_ids = {f"{full_unwired.name}.{name}" for name in full_unwired_names}
    wired_fq_ids = {f"{wired.name}.{name}" for name in wired_names}

    assert "schedule" not in unwired_names
    assert "schedule" not in full_unwired_names
    assert "schedule" in wired_names
    assert "complete" in wired_names
    assert "tasks.schedule" not in unwired_fq_ids
    assert "tasks.schedule" not in full_unwired_fq_ids
    assert "tasks.schedule" in wired_fq_ids
    assert "tasks.complete" in wired_fq_ids
    assert all("area" not in name for name in wired_names)
    assert len(wired.tools) == len(full_unwired.tools) + 1
    assert len(wired_names) == len(set(wired_names))


def _fake_schedule_fn() -> Callable[[ScheduleTaskArgs], Awaitable[ScheduleTaskResult]]:
    async def schedule_fn(args: ScheduleTaskArgs) -> ScheduleTaskResult:
        assert args.task_title == "Buy milk"
        return _scheduled_result()

    return schedule_fn


def _scheduled_result() -> ScheduleTaskResult:
    return ScheduleTaskResult(
        scheduled=ScheduledBlock(
            event_id="evt-456",
            start_dt="2026-06-10T10:00:00Z",
            end_dt="2026-06-10T11:00:00Z",
            calendar_id="primary",
        ),
        message="Scheduled.",
    )


def _slot() -> FreeSlot:
    return _slot_at("2026-06-10T10:00:00Z", "2026-06-10T11:00:00Z")


def _slot_at(start_dt: str, end_dt: str) -> FreeSlot:
    return FreeSlot(start_dt=start_dt, end_dt=end_dt, duration_minutes=60)


def _prefs(
    *,
    preferred_focus_window: tuple[str, str] = ("09:00", "12:00"),
) -> CalPrefs:
    return CalPrefs(
        focus_block_duration_minutes=60,
        default_write_calendar="primary",
        owner_email="me@test.com",
        preferred_focus_window=preferred_focus_window,
    )


def _store(tmp_path: Path) -> ProductivityStore:
    return ProductivityStore(
        Settings(data_root=tmp_path, slot="dev"),
        FakeKeyProvider({OWNER_PRIVATE: os.urandom(32)}, owner_unlocked=True),
    )
