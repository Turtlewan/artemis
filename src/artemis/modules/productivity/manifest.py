"""Productivity module manifest."""

from __future__ import annotations

from pydantic import BaseModel

from artemis.manifest import ActionRisk, DataScope, ModuleManifest, Permissions, ToolSpec, UiSurface
from artemis.modules.productivity import tools
from artemis.modules.productivity.store import ProductivityStore


def productivity_manifest(store: ProductivityStore) -> ModuleManifest:
    """Return the productivity module manifest and initialise its tools."""
    tools.init_tools(store)
    return ModuleManifest(
        name="productivity",
        version="0.1.0",
        description="Owned tasks, projects, and areas - Artemis is the source of truth.",
        tools=_tool_specs(),
        data_scope=DataScope.OWNER_PRIVATE,
        permissions=Permissions(owner=True, guest=False),
        proactive_hooks=[],
        ui=UiSurface(kind="none"),
    )


def _tool_specs() -> list[ToolSpec]:
    read_tools = [
        _spec(
            "task.list", "List tasks.", tools.TaskListArgs, tools.TaskListResult, tools.task_list
        ),
        _spec("task.get", "Get a task.", tools.TaskGetArgs, tools.TaskResult, tools.task_get),
        _spec(
            "task.search",
            "Search tasks.",
            tools.TaskSearchArgs,
            tools.TaskListResult,
            tools.task_search,
        ),
        _spec(
            "task.today",
            "List today's tasks.",
            tools.EmptyArgs,
            tools.TaskListResult,
            tools.task_today,
        ),
        _spec(
            "task.upcoming",
            "List upcoming tasks.",
            tools.TaskUpcomingArgs,
            tools.TaskListResult,
            tools.task_upcoming,
        ),
        _spec(
            "task.overdue",
            "List overdue tasks.",
            tools.EmptyArgs,
            tools.TaskListResult,
            tools.task_overdue,
        ),
        _spec(
            "project.list",
            "List projects.",
            tools.ProjectListArgs,
            tools.ProjectListResult,
            tools.project_list,
        ),
        _spec(
            "project.get",
            "Get a project.",
            tools.ProjectGetArgs,
            tools.ProjectResult,
            tools.project_get,
        ),
        _spec(
            "project.tasks",
            "List project tasks.",
            tools.ProjectTasksArgs,
            tools.TaskListResult,
            tools.project_tasks,
        ),
        _spec(
            "area.list", "List areas.", tools.AreaListArgs, tools.AreaListResult, tools.area_list
        ),
        _spec("area.get", "Get an area.", tools.AreaGetArgs, tools.AreaResult, tools.area_get),
        _spec(
            "area.contents",
            "Get area contents.",
            tools.AreaContentsArgs,
            tools.AreaContentsResult,
            tools.area_contents,
        ),
    ]
    write_tools = [
        _spec(
            "task.create",
            "Create a task.",
            tools.TaskCreateArgs,
            tools.TaskCreatedResult,
            tools.task_create,
            ActionRisk.WRITE,
        ),
        _spec(
            "task.update",
            "Update a task.",
            tools.TaskUpdateArgs,
            tools.OkResult,
            tools.task_update,
            ActionRisk.WRITE,
        ),
        _spec(
            "task.complete",
            "Complete a task.",
            tools.TaskCompleteArgs,
            tools.TaskCompleteResult,
            tools.task_complete,
            ActionRisk.WRITE,
        ),
        _spec(
            "task.cancel",
            "Cancel a task.",
            tools.TaskCancelArgs,
            tools.OkResult,
            tools.task_cancel,
            ActionRisk.WRITE,
        ),
        _spec(
            "task.set_recurrence",
            "Set task recurrence.",
            tools.TaskSetRecurrenceArgs,
            tools.OkResult,
            tools.task_set_recurrence,
            ActionRisk.WRITE,
        ),
        _spec(
            "task.assign_to_project",
            "Assign a task to a project.",
            tools.TaskAssignToProjectArgs,
            tools.OkResult,
            tools.task_assign_to_project,
            ActionRisk.WRITE,
        ),
        _spec(
            "task.assign_to_area",
            "Assign a task to an area.",
            tools.TaskAssignToAreaArgs,
            tools.OkResult,
            tools.task_assign_to_area,
            ActionRisk.WRITE,
        ),
        _spec(
            "project.create",
            "Create a project.",
            tools.ProjectCreateArgs,
            tools.ProjectCreatedResult,
            tools.project_create,
            ActionRisk.WRITE,
        ),
        _spec(
            "project.update",
            "Update a project.",
            tools.ProjectUpdateArgs,
            tools.OkResult,
            tools.project_update,
            ActionRisk.WRITE,
        ),
        _spec(
            "project.archive",
            "Archive a project.",
            tools.ProjectArchiveArgs,
            tools.OkResult,
            tools.project_archive,
            ActionRisk.WRITE,
        ),
        _spec(
            "project.assign_to_area",
            "Assign a project to an area.",
            tools.ProjectAssignToAreaArgs,
            tools.OkResult,
            tools.project_assign_to_area,
            ActionRisk.WRITE,
        ),
        _spec(
            "area.create",
            "Create an area.",
            tools.AreaCreateArgs,
            tools.AreaCreatedResult,
            tools.area_create,
            ActionRisk.WRITE,
        ),
        _spec(
            "area.update",
            "Update an area.",
            tools.AreaUpdateArgs,
            tools.OkResult,
            tools.area_update,
            ActionRisk.WRITE,
        ),
        _spec(
            "area.archive",
            "Archive an area.",
            tools.AreaArchiveArgs,
            tools.OkResult,
            tools.area_archive,
            ActionRisk.WRITE,
        ),
        _spec(
            "suggestion.create",
            "Create a suggestion.",
            tools.SuggestionCreateArgs,
            tools.SuggestionCreatedResult,
            tools.suggestion_create,
            ActionRisk.WRITE,
        ),
        _spec(
            "suggestion.list",
            "List suggestions.",
            tools.SuggestionListArgs,
            tools.SuggestionListResult,
            tools.suggestion_list,
            ActionRisk.WRITE,
        ),
        _spec(
            "suggestion.accept",
            "Accept a suggestion.",
            tools.SuggestionAcceptArgs,
            tools.TaskCreatedResult,
            tools.suggestion_accept,
            ActionRisk.WRITE,
        ),
        _spec(
            "suggestion.reject",
            "Reject a suggestion.",
            tools.SuggestionRejectArgs,
            tools.OkResult,
            tools.suggestion_reject,
            ActionRisk.WRITE,
        ),
    ]
    return read_tools + write_tools


def _spec(
    name: str,
    description: str,
    args_schema: type[BaseModel],
    return_schema: type[BaseModel],
    callable_ref: object,
    action_risk: ActionRisk = ActionRisk.READ,
) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=description,
        args_schema=args_schema,
        return_schema=return_schema,
        callable_ref=callable_ref,
        action_risk=action_risk,
    )
