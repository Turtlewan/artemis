"""Async productivity tool callables."""

from __future__ import annotations

from pydantic import BaseModel, Field

from artemis.modules.productivity.store import ProductivityStore

_store: ProductivityStore | None = None


class EmptyArgs(BaseModel):
    """Tool args for no-argument tools."""


class OkResult(BaseModel):
    """Generic success result."""

    ok: bool = True


class TaskListArgs(BaseModel):
    status: str | None = None
    project_id: str | None = None
    area_id: str | None = None


class TaskGetArgs(BaseModel):
    id: str


class TaskSearchArgs(BaseModel):
    query: str


class TaskUpcomingArgs(BaseModel):
    days: int = 7


class ProjectListArgs(BaseModel):
    status: str | None = None
    area_id: str | None = None


class ProjectGetArgs(BaseModel):
    id: str


class ProjectTasksArgs(BaseModel):
    id: str


class AreaListArgs(BaseModel):
    include_archived: bool = False


class AreaGetArgs(BaseModel):
    id: str


class AreaContentsArgs(BaseModel):
    id: str


class TaskCreateArgs(BaseModel):
    title: str
    notes: str | None = None
    priority: str = "none"
    tags: list[str] = Field(default_factory=list)
    project_id: str | None = None
    area_id: str | None = None
    estimate_minutes: int | None = None
    due_at: str | None = None


class TaskUpdateArgs(BaseModel):
    id: str
    title: str | None = None
    notes: str | None = None
    priority: str | None = None
    tags: list[str] | None = None
    project_id: str | None = None
    area_id: str | None = None
    estimate_minutes: int | None = None
    due_at: str | None = None


class TaskCompleteArgs(BaseModel):
    id: str


class TaskCancelArgs(BaseModel):
    id: str


class TaskSetRecurrenceArgs(BaseModel):
    task_id: str
    mode: str
    rule: str


class TaskAssignToProjectArgs(BaseModel):
    task_id: str
    project_id: str


class TaskAssignToAreaArgs(BaseModel):
    task_id: str
    area_id: str


class ProjectCreateArgs(BaseModel):
    title: str
    notes: str | None = None
    area_id: str | None = None
    target_date: str | None = None


class ProjectUpdateArgs(BaseModel):
    id: str
    title: str | None = None
    status: str | None = None
    notes: str | None = None
    target_date: str | None = None


class ProjectArchiveArgs(BaseModel):
    id: str


class ProjectAssignToAreaArgs(BaseModel):
    project_id: str
    area_id: str


class AreaCreateArgs(BaseModel):
    title: str
    notes: str | None = None


class AreaUpdateArgs(BaseModel):
    id: str
    title: str | None = None
    notes: str | None = None


class AreaArchiveArgs(BaseModel):
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
    area_id: str | None = None
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


class AreaListResult(BaseModel):
    areas: list[dict[str, object]]


class AreaResult(BaseModel):
    area: dict[str, object] | None


class AreaContentsResult(BaseModel):
    area: dict[str, object] | None
    projects: list[dict[str, object]]
    tasks: list[dict[str, object]]


class TaskCreatedResult(BaseModel):
    task_id: str


class TaskCompleteResult(BaseModel):
    spawned_task: dict[str, object] | None


class ProjectCreatedResult(BaseModel):
    project_id: str


class AreaCreatedResult(BaseModel):
    area_id: str


class SuggestionCreatedResult(BaseModel):
    suggestion_id: str


class SuggestionListResult(BaseModel):
    suggestions: list[dict[str, object]]


def init_tools(store: ProductivityStore) -> None:
    """Set the productivity store used by module-level tool callables."""
    global _store
    _store = store


def _get_store() -> ProductivityStore:
    if _store is None:
        raise RuntimeError("productivity store not initialised")
    return _store


async def task_list(args: TaskListArgs) -> TaskListResult:
    store = _get_store()
    return TaskListResult(
        tasks=store.list_tasks(status=args.status, project_id=args.project_id, area_id=args.area_id)
    )


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
    return ProjectListResult(
        projects=_get_store().list_projects(status=args.status, area_id=args.area_id)
    )


async def project_get(args: ProjectGetArgs) -> ProjectResult:
    return ProjectResult(project=_get_store().get_project(args.id))


async def project_tasks(args: ProjectTasksArgs) -> TaskListResult:
    return TaskListResult(tasks=_get_store().project_tasks(args.id))


async def area_list(args: AreaListArgs) -> AreaListResult:
    return AreaListResult(areas=_get_store().list_areas(include_archived=args.include_archived))


async def area_get(args: AreaGetArgs) -> AreaResult:
    return AreaResult(area=_get_store().get_area(args.id))


async def area_contents(args: AreaContentsArgs) -> AreaContentsResult:
    contents = _get_store().area_contents(args.id)
    return AreaContentsResult(
        area=contents["area"] if isinstance(contents["area"], dict) else None,
        projects=list(contents["projects"]) if isinstance(contents["projects"], list) else [],
        tasks=list(contents["tasks"]) if isinstance(contents["tasks"], list) else [],
    )


async def task_create(args: TaskCreateArgs) -> TaskCreatedResult:
    task_id = _get_store().create_task(
        args.title,
        notes=args.notes,
        priority=args.priority,
        tags=args.tags,
        project_id=args.project_id,
        area_id=args.area_id,
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
        area_id=args.area_id,
        estimate_minutes=args.estimate_minutes,
        due_at=args.due_at,
    )
    return OkResult()


async def task_complete(args: TaskCompleteArgs) -> TaskCompleteResult:
    return TaskCompleteResult(spawned_task=_get_store().complete_task(args.id))


async def task_cancel(args: TaskCancelArgs) -> OkResult:
    _get_store().cancel_task(args.id)
    return OkResult()


async def task_set_recurrence(args: TaskSetRecurrenceArgs) -> OkResult:
    _get_store().set_recurrence(args.task_id, args.mode, args.rule)
    return OkResult()


async def task_assign_to_project(args: TaskAssignToProjectArgs) -> OkResult:
    _get_store().assign_task_to_project(args.task_id, args.project_id)
    return OkResult()


async def task_assign_to_area(args: TaskAssignToAreaArgs) -> OkResult:
    _get_store().assign_task_to_area(args.task_id, args.area_id)
    return OkResult()


async def project_create(args: ProjectCreateArgs) -> ProjectCreatedResult:
    project_id = _get_store().create_project(
        args.title,
        notes=args.notes,
        area_id=args.area_id,
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
    _get_store().archive_project(args.id)
    return OkResult()


async def project_assign_to_area(args: ProjectAssignToAreaArgs) -> OkResult:
    _get_store().assign_project_to_area(args.project_id, args.area_id)
    return OkResult()


async def area_create(args: AreaCreateArgs) -> AreaCreatedResult:
    return AreaCreatedResult(area_id=_get_store().create_area(args.title, args.notes))


async def area_update(args: AreaUpdateArgs) -> OkResult:
    _get_store().update_area(args.id, title=args.title, notes=args.notes)
    return OkResult()


async def area_archive(args: AreaArchiveArgs) -> OkResult:
    _get_store().archive_area(args.id)
    return OkResult()


async def suggestion_create(args: SuggestionCreateArgs) -> SuggestionCreatedResult:
    suggestion_id = _get_store().create_suggestion(args.title, notes=args.notes, source=args.source)
    return SuggestionCreatedResult(suggestion_id=suggestion_id)


async def suggestion_list(args: SuggestionListArgs) -> SuggestionListResult:
    return SuggestionListResult(suggestions=_get_store().list_suggestions(status=args.status))


async def suggestion_accept(args: SuggestionAcceptArgs) -> TaskCreatedResult:
    task_id = _get_store().accept_suggestion(
        args.suggestion_id,
        project_id=args.project_id,
        area_id=args.area_id,
        due_at=args.due_at,
    )
    return TaskCreatedResult(task_id=task_id)


async def suggestion_reject(args: SuggestionRejectArgs) -> OkResult:
    _get_store().reject_suggestion(args.suggestion_id)
    return OkResult()
