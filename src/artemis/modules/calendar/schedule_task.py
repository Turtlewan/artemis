"""Task-focused calendar scheduling primitive.

``schedule_task`` can only create self-only focus blocks: the args schema has no
attendee field, and creation delegates to ``block_focus_time``. Empty slot
searches return a typed result instead of raising so callers can surface a
useful brain message. Re-schedule orphan cleanup is owned by the productivity
tool before it calls this primitive.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, ConfigDict

from artemis.modules.calendar.preferences import CalPrefs
from artemis.modules.calendar.read_tools import FindTimeArgs, FindTimeResult, Window
from artemis.modules.calendar.write_tools import BlockFocusTimeArgs, CalendarWriteTools


class ScheduleTaskArgs(BaseModel):
    """Inputs for scheduling a task as a self-only focus block."""

    model_config = ConfigDict(frozen=True)

    task_id: str
    task_title: str
    estimate_minutes: int | None = None
    window_start: str | None = None
    window_end: str | None = None
    calendar_id: str | None = None


class ScheduledBlock(BaseModel):
    """Created task focus block metadata."""

    model_config = ConfigDict(frozen=True)

    event_id: str
    start_dt: str
    end_dt: str
    calendar_id: str


class ScheduleTaskResult(BaseModel):
    """Result for a task scheduling attempt."""

    model_config = ConfigDict(frozen=True)

    scheduled: ScheduledBlock | None
    message: str


async def schedule_task(
    args: ScheduleTaskArgs,
    *,
    write_tools: CalendarWriteTools,
    find_time_fn: Callable[[FindTimeArgs], Awaitable[FindTimeResult]],
    prefs: CalPrefs,
) -> ScheduleTaskResult:
    """Find a slot for a task and create a self-only focus block."""
    duration_minutes = args.estimate_minutes or prefs.focus_block_duration_minutes
    window_start, window_end = _resolve_window(args)
    result = await find_time_fn(
        FindTimeArgs(
            duration_minutes=duration_minutes,
            window=Window(start=window_start, end=window_end),
        )
    )
    if not result.slots:
        return ScheduleTaskResult(
            scheduled=None,
            message=f"No open slot found for '{args.task_title}' in the requested window.",
        )

    slot = result.slots[0]
    write_result = await write_tools.block_focus_time(
        BlockFocusTimeArgs(
            start_datetime=slot.start_dt,
            end_datetime=slot.end_dt,
            title=f"[Task] {args.task_title}",
            calendar_id=args.calendar_id,
        )
    )
    return ScheduleTaskResult(
        scheduled=ScheduledBlock(
            event_id=write_result.event_id,
            start_dt=slot.start_dt,
            end_dt=slot.end_dt,
            calendar_id=args.calendar_id or prefs.default_write_calendar,
        ),
        message=f"Scheduled '{args.task_title}' on {slot.start_dt} -> {slot.end_dt}.",
    )


def _resolve_window(args: ScheduleTaskArgs) -> tuple[str, str]:
    if args.window_start is not None and args.window_end is not None:
        return args.window_start, args.window_end
    now = datetime.now(UTC)
    return now.isoformat(), (now + timedelta(days=7)).isoformat()
