from __future__ import annotations

import inspect
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from artemis.config import Settings
from artemis.identity.key_provider import FakeKeyProvider, ScopeLockedError
from artemis.identity.scope import OWNER_PRIVATE
from artemis.manifest import DataScope
from artemis.memory.entities import EntityRef, EntityType
from artemis.modules.productivity import ProductivityStore, productivity_manifest, tools
from artemis.modules.productivity.repository import ProductivityRepository
from artemis.modules.productivity.schema import create_schema


class FakeEntityRepository:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def resolve_or_create_entity(
        self, *, name: str, entity_type: EntityType, entity_id: str
    ) -> EntityRef:
        self.calls.append({"name": name, "entity_type": entity_type, "entity_id": entity_id})
        return EntityRef(module="productivity", entity_id=entity_id)


def test_schema_creates_tables_indexes_and_is_idempotent() -> None:
    conn = sqlite3.connect(":memory:")
    create_schema(conn)
    create_schema(conn)

    tables = _sqlite_names(conn, "table")
    indexes = _sqlite_names(conn, "index")

    assert tables == {
        "meta",
        "projects",
        "tasks",
        "task_subtasks",
        "task_recurrence",
        "suggestions",
    }
    assert {
        "idx_projects_status",
        "idx_tasks_project_id",
        "idx_tasks_status",
        "idx_tasks_due_at",
        "idx_task_subtasks_task_id",
        "idx_suggestions_status",
    } <= indexes
    assert "areas" not in tables
    assert "area_id" not in _table_columns(conn, "projects")
    assert "area_id" not in _table_columns(conn, "tasks")
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_project_and_goal_entity_crud() -> None:
    repo = _repo()
    project_id = repo.create_project("Q3 budget")
    project = repo.get_project(project_id)
    assert project is not None
    assert project["project_goal_entity_id"] is None
    assert [project["id"] for project in repo.list_projects(status="active")] == [project_id]
    assert repo.project_tasks(project_id) == []

    fake_entities = FakeEntityRepository()
    goal_project_id = repo.create_project("Build feature", entity_repo=fake_entities)
    goal_project = repo.get_project(goal_project_id)
    assert goal_project is not None
    assert goal_project["project_goal_entity_id"] == f"goal:{goal_project_id}"
    assert fake_entities.calls == [
        {
            "name": "Build feature",
            "entity_type": EntityType.GOAL,
            "entity_id": f"goal:{goal_project_id}",
        }
    ]


def test_task_crud_filters_subtasks_and_fk_enforcement() -> None:
    repo = _repo()
    project_id = repo.create_project("Reports")
    today = datetime.now(UTC).date()

    due_today_id = repo.create_task("Send report", project_id=project_id, due_at=today.isoformat())
    overdue_id = repo.create_task("Old report", due_at=(today - timedelta(days=1)).isoformat())
    upcoming_id = repo.create_task("Next report", due_at=(today + timedelta(days=3)).isoformat())
    subtask_id = repo.add_subtask(due_today_id, "Draft", position=1)
    repo.complete_subtask(subtask_id)

    task = repo.get_task(due_today_id)
    assert task is not None
    assert task["title"] == "Send report"
    assert task["tags"] == []
    assert task["subtasks"] == [
        {
            "id": subtask_id,
            "task_id": due_today_id,
            "title": "Draft",
            "done": 1,
            "position": 1,
            "created_at": task["subtasks"][0]["created_at"],  # type: ignore[index]
        }
    ]
    assert [item["id"] for item in repo.today_tasks()] == [overdue_id, due_today_id]
    assert overdue_id in {item["id"] for item in repo.overdue_tasks()}
    assert upcoming_id in {item["id"] for item in repo.upcoming_tasks(days=7)}
    assert due_today_id in {item["id"] for item in repo.search_tasks("Send")}

    with pytest.raises(sqlite3.IntegrityError):
        repo.create_task("Bad FK", project_id="missing")
    with pytest.raises(TypeError):
        inspect.signature(repo.create_task).bind("Bad arg", area_id="missing")


def test_recurrence_fixed_mode_spawns_once_and_carries_rule() -> None:
    repo = _repo()
    task_id = repo.create_task("Weekly review")
    repo.set_recurrence(task_id, "fixed", "every monday")

    spawned = repo.complete_task(task_id)
    assert spawned is not None
    assert spawned["status"] == "todo"
    assert spawned["due_at"] == _next_monday()
    assert spawned["recurrence"] is not None
    assert spawned["recurrence"]["rule"] == "every monday"  # type: ignore[index]
    assert repo.complete_task(task_id) is None
    assert len(repo.list_tasks(status="todo")) == 1


def test_recurrence_after_completion_spawns_from_completed_at() -> None:
    repo = _repo()
    task_id = repo.create_task("Water plants")
    repo.set_recurrence(task_id, "after_completion", "7 days after completion")

    spawned = repo.complete_task(task_id)
    completed = repo.get_task(task_id)

    assert spawned is not None
    assert completed is not None
    completed_at = datetime.fromisoformat(str(completed["completed_at"]))
    assert spawned["due_at"] == (completed_at + timedelta(days=7)).isoformat()
    assert repo.complete_task(task_id) is None


def test_fixed_interval_monthly_clamps_and_spawn_guard_uses_completed_at_or_later() -> None:
    repo = _repo()
    task_id = repo.create_task("Month end", due_at="2026-01-31")
    repo.set_recurrence(task_id, "fixed", "every 1 months")

    spawned = repo.complete_task(task_id)
    original = repo.get_task(task_id)

    assert spawned is not None
    assert original is not None
    assert isinstance(spawned["due_at"], str)
    assert spawned["due_at"] > datetime.now(UTC).date().isoformat()
    assert repo.spawn_next_recurrence(task_id)["id"] == spawned["id"]


def test_suggestion_flow() -> None:
    repo = _repo()
    suggestion_id = repo.create_suggestion("Call dentist", source="chat")

    assert [item["id"] for item in repo.list_suggestions(status="pending")] == [suggestion_id]
    task_id = repo.accept_suggestion(suggestion_id)
    assert repo.get_task(task_id)["title"] == "Call dentist"  # type: ignore[index]
    assert repo.list_suggestions(status="pending") == []
    rejected_id = repo.create_suggestion("Skip it")
    repo.reject_suggestion(rejected_id)
    assert repo.list_suggestions(status="rejected")[0]["id"] == rejected_id


def test_store_lazy_open_round_trip_and_scope_locked_error(tmp_path: Path) -> None:
    store = _store(tmp_path)
    project_id = store.create_project("Health")
    task_id = store.create_task("Plan workout", project_id=project_id)
    assert store.get_project(project_id)["title"] == "Health"  # type: ignore[index]
    assert store.get_task(task_id)["project_id"] == project_id  # type: ignore[index]
    store.close()

    locked = ProductivityStore(_settings(tmp_path), FakeKeyProvider(owner_unlocked=False))
    with pytest.raises(ScopeLockedError):
        locked._get_conn()


async def test_tools_are_async_and_uninitialised_store_raises() -> None:
    tools._store = None
    assert inspect.iscoroutinefunction(tools.task_create)
    with pytest.raises(RuntimeError, match="productivity store not initialised"):
        await tools.task_create(tools.TaskCreateArgs(title="No store"))


async def test_tools_smoke_with_store(tmp_path: Path) -> None:
    productivity_manifest(_store(tmp_path))

    project = await tools.project_create(tools.ProjectCreateArgs(title="Admin"))
    task = await tools.task_create(
        tools.TaskCreateArgs(title="File paperwork", project_id=project.project_id)
    )
    tasks = await tools.task_list(tools.TaskListArgs(project_id=project.project_id))

    assert tasks.tasks[0]["id"] == task.task_id


def test_manifest_shape(tmp_path: Path) -> None:
    manifest = productivity_manifest(_store(tmp_path))
    names = [tool.name for tool in manifest.tools]

    assert manifest.name == "productivity"
    assert len(manifest.tools) == 22
    assert len(names) == len(set(names))
    assert {
        "area.create",
        "area.update",
        "area.archive",
        "area.list",
        "area.get",
        "area.contents",
        "task.assign_to_area",
        "project.assign_to_area",
    }.isdisjoint(names)
    assert "area_id" not in tools.TaskCreateArgs.model_fields
    assert "area_id" not in tools.TaskUpdateArgs.model_fields
    assert "area_id" not in tools.ProjectCreateArgs.model_fields
    assert manifest.data_scope == DataScope.OWNER_PRIVATE
    assert manifest.proactive_hooks == []
    assert sum(tool.action_risk == "read" for tool in manifest.tools) == 9
    assert sum(tool.action_risk == "write" for tool in manifest.tools) == 13


def _repo() -> ProductivityRepository:
    conn = sqlite3.connect(":memory:")
    create_schema(conn)
    return ProductivityRepository(conn)


def _settings(tmp_path: Path) -> Settings:
    return Settings(data_root=tmp_path, slot="dev")


def _store(tmp_path: Path) -> ProductivityStore:
    return ProductivityStore(
        _settings(tmp_path),
        FakeKeyProvider({OWNER_PRIVATE: b"0" * 32}, owner_unlocked=True),
    )


def _sqlite_names(conn: sqlite3.Connection, kind: str) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = ?", (kind,)).fetchall()
    return {str(row[0]) for row in rows}


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {str(row[1]) for row in rows}


def _next_monday() -> str:
    today = datetime.now(UTC).date()
    days_ahead = (0 - today.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return (today + timedelta(days=days_ahead)).isoformat()
