"""Async productivity tool callables."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable

from pydantic import BaseModel, ConfigDict, Field

from artemis import paths
from artemis.config import Settings
from artemis.identity.scope import OWNER_PRIVATE
from artemis.ingest.connectors import Source
from artemis.ingest.pipeline import IngestPipeline
from artemis.memory import MemoryWriteQueue
from artemis.modules.calendar.schedule_task import ScheduleTaskArgs, ScheduleTaskResult
from artemis.modules.calendar.write_tools import CalendarWriteTools, CancelEventArgs
from artemis.modules.productivity.capture import CaptureService
from artemis.modules.productivity.store import ProductivityStore

LOGGER = logging.getLogger(__name__)

_store: ProductivityStore | None = None
_schedule_fn: Callable[[ScheduleTaskArgs], Awaitable[ScheduleTaskResult]] | None = None
_write_tools: CalendarWriteTools | None = None
_capture_service: CaptureService | None = None
_ingest_pipeline: IngestPipeline | None = None
_memory_queue: MemoryWriteQueue | None = None
_settings: Settings | None = None


class EmptyArgs(BaseModel):
    """Tool args for no-argument tools."""


class OkResult(BaseModel):
    """Generic success result."""

    ok: bool = True


class TaskListArgs(BaseModel):
    status: str | None = None
    project_id: str | None = None


class TaskGetArgs(BaseModel):
    id: str


class TaskSearchArgs(BaseModel):
    query: str


class TaskUpcomingArgs(BaseModel):
    days: int = 7


class ProjectListArgs(BaseModel):
    status: str | None = None


class ProjectGetArgs(BaseModel):
    id: str


class ProjectTasksArgs(BaseModel):
    id: str


class TaskCreateArgs(BaseModel):
    title: str
    notes: str | None = None
    priority: str = "none"
    tags: list[str] = Field(default_factory=list)
    project_id: str | None = None
    estimate_minutes: int | None = None
    due_at: str | None = None


class TaskUpdateArgs(BaseModel):
    id: str
    title: str | None = None
    notes: str | None = None
    priority: str | None = None
    tags: list[str] | None = None
    project_id: str | None = None
    estimate_minutes: int | None = None
    due_at: str | None = None


class TaskCompleteArgs(BaseModel):
    id: str


class TaskScheduleArgs(BaseModel):
    model_config = ConfigDict(frozen=True)

    task_id: str
    window_start: str | None = None
    window_end: str | None = None


class TaskCancelArgs(BaseModel):
    id: str


class TaskSetRecurrenceArgs(BaseModel):
    task_id: str
    mode: str
    rule: str


class TaskAssignToProjectArgs(BaseModel):
    task_id: str
    project_id: str


class ProjectCreateArgs(BaseModel):
    title: str
    notes: str | None = None
    target_date: str | None = None


class ProjectUpdateArgs(BaseModel):
    id: str
    title: str | None = None
    status: str | None = None
    notes: str | None = None
    target_date: str | None = None


class ProjectArchiveArgs(BaseModel):
    id: str


class ProjectCompleteArgs(BaseModel):
    id: str


class SuggestionCreateArgs(BaseModel):
    title: str
    notes: str | None = None
    source: str = "manual"


class SuggestionListArgs(BaseModel):
    status: str = "pending"


class SuggestionAcceptArgs(BaseModel):
    suggestion_id: str
    project_id: str | None = None
    due_at: str | None = None


class SuggestionRejectArgs(BaseModel):
    suggestion_id: str


class TaskListResult(BaseModel):
    tasks: list[dict[str, object]]


class TaskResult(BaseModel):
    task: dict[str, object] | None


class ProjectListResult(BaseModel):
    projects: list[dict[str, object]]


class ProjectResult(BaseModel):
    project: dict[str, object] | None


class TaskCreatedResult(BaseModel):
    task_id: str


class TaskCompleteResult(BaseModel):
    spawned_task: dict[str, object] | None


class TaskScheduleResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    task_id: str
    event_id: str | None
    scheduled_block: str | None
    message: str


class ProjectCreatedResult(BaseModel):
    project_id: str


class SuggestionCreatedResult(BaseModel):
    suggestion_id: str


class SuggestionListResult(BaseModel):
    suggestions: list[dict[str, object]]


def init_tools(store: ProductivityStore) -> None:
    """Set the productivity store used by module-level tool callables."""
    global _store
    _store = store


def init_schedule_fn(fn: Callable[[ScheduleTaskArgs], Awaitable[ScheduleTaskResult]]) -> None:
    """Set the calendar scheduling callable used by task scheduling."""
    global _schedule_fn
    _schedule_fn = fn


def init_write_tools(write_tools: CalendarWriteTools) -> None:
    """Set calendar write tools used to cancel prior task focus blocks."""
    global _write_tools
    _write_tools = write_tools


def init_capture(
    capture_service: CaptureService,
    ingest_pipeline: IngestPipeline,
    memory_queue: MemoryWriteQueue,
    settings: Settings,
) -> None:
    """Set capture and knowledge-push services used by productivity tools."""
    global _capture_service, _ingest_pipeline, _memory_queue, _settings
    _capture_service = capture_service
    _ingest_pipeline = ingest_pipeline
    _memory_queue = memory_queue
    _settings = settings


def _get_store() -> ProductivityStore:
    if _store is None:
        raise RuntimeError("productivity store not initialised")
    return _store


def _get_schedule_fn() -> Callable[[ScheduleTaskArgs], Awaitable[ScheduleTaskResult]]:
    if _schedule_fn is None:
        raise RuntimeError("schedule_fn not initialised")
    return _schedule_fn


def _get_write_tools() -> CalendarWriteTools:
    if _write_tools is None:
        raise RuntimeError("write_tools not initialised")
    return _write_tools


async def task_list(args: TaskListArgs) -> TaskListResult:
    store = _get_store()
    return TaskListResult(tasks=store.list_tasks(status=args.status, project_id=args.project_id))


async def task_get(args: TaskGetArgs) -> TaskResult:
    return TaskResult(task=_get_store().get_task(args.id))


async def task_search(args: TaskSearchArgs) -> TaskListResult:
    return TaskListResult(tasks=_get_store().search_tasks(args.query))


async def task_today(args: EmptyArgs) -> TaskListResult:
    del args
    return TaskListResult(tasks=_get_store().today_tasks())


async def task_upcoming(args: TaskUpcomingArgs) -> TaskListResult:
    return TaskListResult(tasks=_get_store().upcoming_tasks(args.days))


async def task_overdue(args: EmptyArgs) -> TaskListResult:
    del args
    return TaskListResult(tasks=_get_store().overdue_tasks())


async def project_list(args: ProjectListArgs) -> ProjectListResult:
    return ProjectListResult(projects=_get_store().list_projects(status=args.status))


async def project_get(args: ProjectGetArgs) -> ProjectResult:
    return ProjectResult(project=_get_store().get_project(args.id))


async def project_tasks(args: ProjectTasksArgs) -> TaskListResult:
    return TaskListResult(tasks=_get_store().project_tasks(args.id))


async def task_create(args: TaskCreateArgs) -> TaskCreatedResult:
    task_id = _get_store().create_task(
        args.title,
        notes=args.notes,
        priority=args.priority,
        tags=args.tags,
        project_id=args.project_id,
        estimate_minutes=args.estimate_minutes,
        due_at=args.due_at,
    )
    return TaskCreatedResult(task_id=task_id)


async def task_update(args: TaskUpdateArgs) -> OkResult:
    _get_store().update_task(
        args.id,
        title=args.title,
        notes=args.notes,
        priority=args.priority,
        tags=args.tags,
        project_id=args.project_id,
        estimate_minutes=args.estimate_minutes,
        due_at=args.due_at,
    )
    return OkResult()


async def task_complete(args: TaskCompleteArgs) -> TaskCompleteResult:
    """Complete a task and clear its consumed Task-Event link without deleting the event."""
    store = _get_store()
    pre_state = store.get_task(args.id)
    spawned = store.complete_task(args.id)
    if pre_state and pre_state.get("calendar_event_id"):
        store.clear_task_schedule_link(args.id)
    return TaskCompleteResult(spawned_task=spawned)


async def task_schedule(args: TaskScheduleArgs) -> TaskScheduleResult:
    """Schedule a task after confirmed calendar write, then persist the Task-Event link."""
    store = _get_store()
    schedule_fn = _get_schedule_fn()
    write_tools = _get_write_tools()

    task = store.get_task(args.task_id)
    if task is None:
        return TaskScheduleResult(
            task_id=args.task_id,
            event_id=None,
            scheduled_block=None,
            message=f"Task {args.task_id} not found.",
        )

    old_event_id = task.get("calendar_event_id")
    if isinstance(old_event_id, str) and old_event_id:
        await write_tools.cancel_event(
            CancelEventArgs(event_id=old_event_id, recurrence_scope="THIS_EVENT")
        )

    task_title = str(task["title"])
    estimate = task.get("estimate_minutes")
    result = await schedule_fn(
        ScheduleTaskArgs(
            task_id=args.task_id,
            task_title=task_title,
            estimate_minutes=estimate if isinstance(estimate, int) else None,
            window_start=args.window_start,
            window_end=args.window_end,
        )
    )
    if result.scheduled is None:
        return TaskScheduleResult(
            task_id=args.task_id,
            event_id=None,
            scheduled_block=None,
            message=result.message,
        )

    store.update_task(
        args.task_id,
        calendar_event_id=result.scheduled.event_id,
        scheduled_block=result.scheduled.start_dt,
    )
    return TaskScheduleResult(
        task_id=args.task_id,
        event_id=result.scheduled.event_id,
        scheduled_block=result.scheduled.start_dt,
        message=result.message,
    )


async def task_cancel(args: TaskCancelArgs) -> OkResult:
    _get_store().cancel_task(args.id)
    return OkResult()


async def task_set_recurrence(args: TaskSetRecurrenceArgs) -> OkResult:
    _get_store().set_recurrence(args.task_id, args.mode, args.rule)
    return OkResult()


async def task_assign_to_project(args: TaskAssignToProjectArgs) -> OkResult:
    _get_store().assign_task_to_project(args.task_id, args.project_id)
    return OkResult()


async def project_create(args: ProjectCreateArgs) -> ProjectCreatedResult:
    project_id = _get_store().create_project(
        args.title,
        notes=args.notes,
        target_date=args.target_date,
    )
    return ProjectCreatedResult(project_id=project_id)


async def project_update(args: ProjectUpdateArgs) -> OkResult:
    _get_store().update_project(
        args.id,
        title=args.title,
        status=args.status,
        notes=args.notes,
        target_date=args.target_date,
    )
    return OkResult()


async def project_archive(args: ProjectArchiveArgs) -> OkResult:
    store = _get_store()
    store.archive_project(args.id)
    await _push_knowledge(store.get_project(args.id))
    return OkResult()


async def project_complete(args: ProjectCompleteArgs) -> OkResult:
    store = _get_store()
    store.update_project(args.id, status="done")
    await _push_knowledge(store.get_project(args.id))
    return OkResult()


async def suggestion_create(args: SuggestionCreateArgs) -> SuggestionCreatedResult:
    suggestion_id = _get_store().create_suggestion(args.title, notes=args.notes, source=args.source)
    return SuggestionCreatedResult(suggestion_id=suggestion_id)


async def suggestion_list(args: SuggestionListArgs) -> SuggestionListResult:
    return SuggestionListResult(suggestions=_get_store().list_suggestions(status=args.status))


async def suggestion_accept(args: SuggestionAcceptArgs) -> TaskCreatedResult:
    if _capture_service is not None:
        task_id = await _capture_service.accept_with_graduation(
            args.suggestion_id,
            project_id=args.project_id,
            due_at=args.due_at,
        )
    else:
        task_id = _get_store().accept_suggestion(
            args.suggestion_id,
            project_id=args.project_id,
            due_at=args.due_at,
        )
    return TaskCreatedResult(task_id=task_id)


async def suggestion_reject(args: SuggestionRejectArgs) -> OkResult:
    _get_store().reject_suggestion(args.suggestion_id)
    return OkResult()


async def _push_knowledge(project: dict[str, object] | None) -> None:
    """Best-effort project completion push into knowledge and memory."""
    if project is None or _ingest_pipeline is None or _memory_queue is None or _settings is None:
        return
    try:
        title = str(project.get("title") or "")
        notes = project.get("notes")
        status = str(project.get("status") or "")
        project_id = str(project.get("id") or "")
        text = "\n".join(
            part
            for part in (
                f"Completed project: {title}",
                f"Status: {status}",
                f"Notes: {notes}" if isinstance(notes, str) and notes else "",
            )
            if part
        )
        staging = paths.scope_dir(_settings, OWNER_PRIVATE) / "staging" / "productivity"
        staging.mkdir(parents=True, exist_ok=True)
        path = staging / f"project-{project_id or uuid.uuid4().hex}.txt"
        path.write_text(text, encoding="utf-8")
        await _ingest_pipeline.ingest(Source(kind="file", uri=str(path), scope=OWNER_PRIVATE))
        _memory_queue.enqueue(text, turn_id=f"project_complete:{project_id or uuid.uuid4().hex}")
    except Exception as exc:
        LOGGER.warning("Productivity knowledge push failed (%s)", type(exc).__name__)
