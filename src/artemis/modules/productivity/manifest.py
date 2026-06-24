"""Productivity module manifests.

Tasks and Projects are separate tool/UI surfaces over one ProductivityStore and
one productivity.db. Registry ids are ``{manifest.name}.{tool.name}``, so project
tools use bare names like ``create`` to become ``projects.create``; task tools do
the same for ``tasks.create``. Suggestion tools keep their prefix on the tasks
manifest to avoid colliding with task ``create``/``list``.
"""

from __future__ import annotations

from pydantic import BaseModel

from artemis.manifest import ActionRisk, DataScope, ModuleManifest, Permissions, ToolSpec, UiSurface
from artemis.modules.productivity import tools
from artemis.modules.productivity.hooks import build_productivity_hooks
from artemis.modules.productivity.store import ProductivityStore


def projects_manifest(store: ProductivityStore) -> ModuleManifest:
    """Return the projects surface manifest and initialise the shared store."""
    tools.init_tools(store)
    return ModuleManifest(
        name="projects",
        version="0.1.0",
        description="Owned projects - goals with linked tasks. Artemis is the source of truth.",
        tools=_project_tool_specs(),
        data_scope=DataScope.OWNER_PRIVATE,
        permissions=Permissions(owner=True, guest=False),
        proactive_hooks=[],
        ui=UiSurface(kind="card"),
    )


def tasks_manifest(store: ProductivityStore) -> ModuleManifest:
    """Return the tasks surface manifest and initialise the shared store."""
    tools.init_tools(store)
    hooks = build_productivity_hooks(store)
    return ModuleManifest(
        name="tasks",
        version="0.1.0",
        description="Owned tasks - capture, schedule, recurrence. Artemis is the source of truth.",
        tools=_task_tool_specs(),
        data_scope=DataScope.OWNER_PRIVATE,
        permissions=Permissions(owner=True, guest=False),
        proactive_hooks=hooks,
        ui=UiSurface(kind="card"),
    )


productivity_manifest = tasks_manifest


def _project_tool_specs() -> list[ToolSpec]:
    return [
        _spec(
            "list",
            "List projects.",
            tools.ProjectListArgs,
            tools.ProjectListResult,
            tools.project_list,
        ),
        _spec(
            "get",
            "Get a project.",
            tools.ProjectGetArgs,
            tools.ProjectResult,
            tools.project_get,
        ),
        _spec(
            "tasks",
            "List project tasks.",
            tools.ProjectTasksArgs,
            tools.TaskListResult,
            tools.project_tasks,
        ),
        _spec(
            "create",
            "Create a project.",
            tools.ProjectCreateArgs,
            tools.ProjectCreatedResult,
            tools.project_create,
            ActionRisk.WRITE,
        ),
        _spec(
            "update",
            "Update a project.",
            tools.ProjectUpdateArgs,
            tools.OkResult,
            tools.project_update,
            ActionRisk.WRITE,
        ),
        _spec(
            "archive",
            "Archive a project.",
            tools.ProjectArchiveArgs,
            tools.OkResult,
            tools.project_archive,
            ActionRisk.WRITE,
        ),
    ]


def _task_tool_specs() -> list[ToolSpec]:
    read_tools = [
        _spec("list", "List tasks.", tools.TaskListArgs, tools.TaskListResult, tools.task_list),
        _spec("get", "Get a task.", tools.TaskGetArgs, tools.TaskResult, tools.task_get),
        _spec(
            "search",
            "Search tasks.",
            tools.TaskSearchArgs,
            tools.TaskListResult,
            tools.task_search,
        ),
        _spec(
            "today", "List today's tasks.", tools.EmptyArgs, tools.TaskListResult, tools.task_today
        ),
        _spec(
            "upcoming",
            "List upcoming tasks.",
            tools.TaskUpcomingArgs,
            tools.TaskListResult,
            tools.task_upcoming,
        ),
        _spec(
            "overdue",
            "List overdue tasks.",
            tools.EmptyArgs,
            tools.TaskListResult,
            tools.task_overdue,
        ),
    ]
    write_tools = [
        _spec(
            "create",
            "Create a task.",
            tools.TaskCreateArgs,
            tools.TaskCreatedResult,
            tools.task_create,
            ActionRisk.WRITE,
        ),
        _spec(
            "update",
            "Update a task.",
            tools.TaskUpdateArgs,
            tools.OkResult,
            tools.task_update,
            ActionRisk.WRITE,
        ),
        _spec(
            "complete",
            "Complete a task.",
            tools.TaskCompleteArgs,
            tools.TaskCompleteResult,
            tools.task_complete,
            ActionRisk.WRITE,
        ),
        _spec(
            "cancel",
            "Cancel a task.",
            tools.TaskCancelArgs,
            tools.OkResult,
            tools.task_cancel,
            ActionRisk.WRITE,
        ),
        _spec(
            "set_recurrence",
            "Set task recurrence.",
            tools.TaskSetRecurrenceArgs,
            tools.OkResult,
            tools.task_set_recurrence,
            ActionRisk.WRITE,
        ),
        _spec(
            "assign_to_project",
            "Assign a task to a project.",
            tools.TaskAssignToProjectArgs,
            tools.OkResult,
            tools.task_assign_to_project,
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
