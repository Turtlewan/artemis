"""Repository and recurrence engine for owner-private productivity data.

Supported recurrence rules:
- ``every <N> days|weeks|months``
- ``every <weekday>``
- ``monthly on <N>``
- ``<N> days|weeks after completion``
"""

from __future__ import annotations

import calendar
import json
import logging
import re
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from typing import Protocol, cast

from artemis.data.sqlcipher import set_row_factory
from artemis.memory.entities import EntityRef, EntityType
from artemis.modules.productivity.schema import (
    ProjectStatus,
    RecurrenceMode,
    TaskPriority,
    TaskStatus,
    now_iso,
)

LOGGER = logging.getLogger(__name__)
WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


class GoalEntityRepo(Protocol):
    """Small seam needed to link projects to GOAL entities."""

    def resolve_or_create_entity(
        self, *, name: str, entity_type: EntityType, entity_id: str
    ) -> EntityRef:
        """Resolve or create a cross-module GOAL entity reference."""
        ...


class ProductivityRepository:
    """CRUD repository for projects, tasks, subtasks, and suggestions."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        set_row_factory(self._conn)

    def create_project(
        self,
        title: str,
        *,
        notes: str | None = None,
        target_date: str | None = None,
        entity_repo: GoalEntityRepo | None = None,
    ) -> str:
        project_id = _new_id()
        now = now_iso()
        with self._conn:
            self._conn.execute(
                """INSERT INTO projects (
                    id, title, status, target_date, notes, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    project_id,
                    title,
                    ProjectStatus.ACTIVE.value,
                    target_date,
                    notes,
                    now,
                    now,
                ),
            )
            if entity_repo is not None:
                ref = entity_repo.resolve_or_create_entity(
                    name=title,
                    entity_type=EntityType.GOAL,
                    entity_id=f"goal:{project_id}",
                )
                self._conn.execute(
                    "UPDATE projects SET project_goal_entity_id = ? WHERE id = ?",
                    (ref.entity_id, project_id),
                )
        return project_id

    def get_project(self, id: str) -> dict[str, object] | None:
        row = self._conn.execute("SELECT * FROM projects WHERE id = ?", (id,)).fetchone()
        return _row_to_dict(row)

    def list_projects(
        self,
        *,
        status: str | None = None,
        include_archived: bool = False,
    ) -> list[dict[str, object]]:
        clauses: list[str] = []
        params: list[object] = []
        if status is not None:
            ProjectStatus(status)
            clauses.append("status = ?")
            params.append(status)
        if not include_archived:
            clauses.append("archived = 0")
        sql = "SELECT * FROM projects"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at ASC"
        rows = self._conn.execute(sql, tuple(params)).fetchall()
        return [_require_dict(row) for row in rows]

    def update_project(
        self,
        id: str,
        *,
        title: str | None = None,
        notes: str | None = None,
        status: str | None = None,
        target_date: str | None = None,
    ) -> None:
        updates: dict[str, object] = {"updated_at": now_iso()}
        if title is not None:
            updates["title"] = title
        if notes is not None:
            updates["notes"] = notes
        if status is not None:
            updates["status"] = ProjectStatus(status).value
        if target_date is not None:
            updates["target_date"] = target_date
        self._update("projects", id, updates)

    def archive_project(self, id: str) -> None:
        self._update("projects", id, {"archived": 1, "updated_at": now_iso()})

    def project_tasks(self, project_id: str) -> list[dict[str, object]]:
        rows = self._conn.execute(
            """SELECT * FROM tasks
               WHERE project_id = ? AND status NOT IN ('done', 'cancelled')
               ORDER BY due_at IS NULL, due_at, created_at""",
            (project_id,),
        ).fetchall()
        return [_task_dict(row, self._conn) for row in rows]

    def create_task(
        self,
        title: str,
        *,
        notes: str | None = None,
        status: str = "todo",
        priority: str = "none",
        tags: list[str] | None = None,
        project_id: str | None = None,
        estimate_minutes: int | None = None,
        due_at: str | None = None,
    ) -> str:
        task_id = _new_id()
        now = now_iso()
        status_value = TaskStatus(status).value
        priority_value = TaskPriority(priority).value
        with self._conn:
            self._conn.execute(
                """INSERT INTO tasks (
                    id, title, notes, status, priority, tags, project_id,
                    estimate_minutes, due_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    task_id,
                    title,
                    notes,
                    status_value,
                    priority_value,
                    json.dumps(tags or []),
                    project_id,
                    estimate_minutes,
                    due_at,
                    now,
                    now,
                ),
            )
        return task_id

    def get_task(self, id: str) -> dict[str, object] | None:
        row = self._conn.execute("SELECT * FROM tasks WHERE id = ?", (id,)).fetchone()
        if row is None:
            return None
        return _task_dict(row, self._conn)

    def list_tasks(
        self,
        *,
        status: str | None = None,
        project_id: str | None = None,
    ) -> list[dict[str, object]]:
        clauses: list[str] = []
        params: list[object] = []
        if status is not None:
            TaskStatus(status)
            clauses.append("status = ?")
            params.append(status)
        if project_id is not None:
            clauses.append("project_id = ?")
            params.append(project_id)
        sql = "SELECT * FROM tasks"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY due_at IS NULL, due_at, created_at"
        rows = self._conn.execute(sql, tuple(params)).fetchall()
        return [_task_dict(row, self._conn) for row in rows]

    def search_tasks(self, query: str) -> list[dict[str, object]]:
        rows = self._conn.execute(
            """SELECT * FROM tasks
               WHERE title || ' ' || COALESCE(notes, '') LIKE ?
               ORDER BY created_at DESC
               LIMIT 50""",
            (f"%{query}%",),
        ).fetchall()
        return [_task_dict(row, self._conn) for row in rows]

    def today_tasks(self) -> list[dict[str, object]]:
        today = datetime.now(UTC).date().isoformat()
        rows = self._conn.execute(
            """SELECT * FROM tasks
               WHERE due_at <= ? AND status NOT IN ('done', 'cancelled')
               ORDER BY due_at, created_at""",
            (today,),
        ).fetchall()
        return [_task_dict(row, self._conn) for row in rows]

    def upcoming_tasks(self, days: int = 7) -> list[dict[str, object]]:
        start = datetime.now(UTC).date().isoformat()
        end = (datetime.now(UTC).date() + timedelta(days=days)).isoformat()
        rows = self._conn.execute(
            """SELECT * FROM tasks
               WHERE due_at >= ? AND due_at <= ? AND status NOT IN ('done', 'cancelled')
               ORDER BY due_at, created_at""",
            (start, end),
        ).fetchall()
        return [_task_dict(row, self._conn) for row in rows]

    def overdue_tasks(self) -> list[dict[str, object]]:
        today = datetime.now(UTC).date().isoformat()
        rows = self._conn.execute(
            """SELECT * FROM tasks
               WHERE due_at < ? AND status NOT IN ('done', 'cancelled')
               ORDER BY due_at, created_at""",
            (today,),
        ).fetchall()
        return [_task_dict(row, self._conn) for row in rows]

    def complete_task(self, id: str) -> dict[str, object] | None:
        task = self.get_task(id)
        if task is None:
            raise KeyError(id)
        if task["status"] in {TaskStatus.DONE.value, TaskStatus.CANCELLED.value}:
            return None
        completed_at = now_iso()
        with self._conn:
            self._conn.execute(
                """UPDATE tasks
                   SET status = ?, completed_at = ?, updated_at = ?
                   WHERE id = ?""",
                (TaskStatus.DONE.value, completed_at, completed_at, id),
            )
        recurrence = self._recurrence_row(id)
        if recurrence is None:
            return None
        return self.spawn_next_recurrence(id)

    def cancel_task(self, id: str) -> None:
        self._update("tasks", id, {"status": TaskStatus.CANCELLED.value, "updated_at": now_iso()})

    def update_task(
        self,
        id: str,
        *,
        title: str | None = None,
        notes: str | None = None,
        priority: str | None = None,
        tags: list[str] | None = None,
        project_id: str | None = None,
        estimate_minutes: int | None = None,
        due_at: str | None = None,
        scheduled_block: str | None = None,
        calendar_event_id: str | None = None,
    ) -> None:
        updates: dict[str, object] = {"updated_at": now_iso()}
        if title is not None:
            updates["title"] = title
        if notes is not None:
            updates["notes"] = notes
        if priority is not None:
            updates["priority"] = TaskPriority(priority).value
        if tags is not None:
            updates["tags"] = json.dumps(tags)
        if project_id is not None:
            updates["project_id"] = project_id
        if estimate_minutes is not None:
            updates["estimate_minutes"] = estimate_minutes
        if due_at is not None:
            updates["due_at"] = due_at
        if scheduled_block is not None:
            updates["scheduled_block"] = scheduled_block
        if calendar_event_id is not None:
            updates["calendar_event_id"] = calendar_event_id
        self._update("tasks", id, updates)

    def assign_task_to_project(self, task_id: str, project_id: str) -> None:
        self._update("tasks", task_id, {"project_id": project_id, "updated_at": now_iso()})

    def set_recurrence(self, task_id: str, mode: str, rule: str) -> None:
        mode_value = RecurrenceMode(mode).value
        now = now_iso()
        with self._conn:
            self._conn.execute(
                """INSERT INTO task_recurrence (task_id, mode, rule, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(task_id) DO UPDATE SET
                       mode = excluded.mode,
                       rule = excluded.rule,
                       updated_at = excluded.updated_at""",
                (task_id, mode_value, rule, now, now),
            )

    def clear_recurrence(self, task_id: str) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM task_recurrence WHERE task_id = ?", (task_id,))

    def clear_task_schedule_link(self, task_id: str) -> None:
        with self._conn:
            self._conn.execute(
                """UPDATE tasks
                   SET calendar_event_id = NULL, scheduled_block = NULL, updated_at = ?
                   WHERE id = ?""",
                (now_iso(), task_id),
            )

    def spawn_next_recurrence(self, completed_task_id: str) -> dict[str, object]:
        row = self._conn.execute(
            "SELECT * FROM tasks WHERE id = ?", (completed_task_id,)
        ).fetchone()
        recurrence = self._recurrence_row(completed_task_id)
        if row is None or recurrence is None:
            raise KeyError(completed_task_id)
        task = _require_dict(row)
        completed_at = cast(str | None, task["completed_at"])
        if completed_at is None:
            raise ValueError("completed task has no completed_at timestamp")
        existing = self._existing_spawn(task, completed_at)
        if existing is not None:
            return existing
        next_due_at = _next_due_at(
            mode=cast(str, recurrence["mode"]),
            rule=cast(str, recurrence["rule"]),
            due_at=cast(str | None, task["due_at"]),
            completed_at=completed_at,
        )
        new_task_id = self.create_task(
            cast(str, task["title"]),
            notes=cast(str | None, task["notes"]),
            priority=cast(str, task["priority"]),
            tags=cast(list[str], json.loads(cast(str, task["tags"]))),
            project_id=cast(str | None, task["project_id"]),
            estimate_minutes=cast(int | None, task["estimate_minutes"]),
            due_at=next_due_at,
        )
        self.set_recurrence(
            new_task_id, cast(str, recurrence["mode"]), cast(str, recurrence["rule"])
        )
        spawned = self.get_task(new_task_id)
        if spawned is None:
            raise KeyError(new_task_id)
        return spawned

    def add_subtask(self, task_id: str, title: str, position: int = 0) -> str:
        subtask_id = _new_id()
        with self._conn:
            self._conn.execute(
                """INSERT INTO task_subtasks (id, task_id, title, position, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (subtask_id, task_id, title, position, now_iso()),
            )
        return subtask_id

    def complete_subtask(self, subtask_id: str) -> None:
        with self._conn:
            self._conn.execute("UPDATE task_subtasks SET done = 1 WHERE id = ?", (subtask_id,))

    def list_subtasks(self, task_id: str) -> list[dict[str, object]]:
        rows = self._conn.execute(
            "SELECT * FROM task_subtasks WHERE task_id = ? ORDER BY position, created_at",
            (task_id,),
        ).fetchall()
        return [_require_dict(row) for row in rows]

    def delete_subtask(self, subtask_id: str) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM task_subtasks WHERE id = ?", (subtask_id,))

    def create_suggestion(
        self,
        title: str,
        *,
        notes: str | None = None,
        source: str = "manual",
        raw_context: str | None = None,
        commitment_shape: str | None = None,
    ) -> str:
        suggestion_id = _new_id()
        now = now_iso()
        with self._conn:
            self._conn.execute(
                """INSERT INTO suggestions (
                    id, title, notes, source, raw_context, commitment_shape,
                    status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)""",
                (
                    suggestion_id,
                    title,
                    notes,
                    source,
                    raw_context,
                    commitment_shape,
                    now,
                    now,
                ),
            )
        return suggestion_id

    def list_suggestions(self, *, status: str = "pending") -> list[dict[str, object]]:
        rows = self._conn.execute(
            "SELECT * FROM suggestions WHERE status = ? ORDER BY created_at ASC",
            (status,),
        ).fetchall()
        return [_require_dict(row) for row in rows]

    def get_suggestion(self, suggestion_id: str) -> dict[str, object] | None:
        row = self._conn.execute(
            "SELECT * FROM suggestions WHERE id = ?",
            (suggestion_id,),
        ).fetchone()
        return _row_to_dict(row)

    def accept_suggestion(
        self,
        suggestion_id: str,
        *,
        project_id: str | None = None,
        due_at: str | None = None,
    ) -> str:
        suggestion = self._suggestion(suggestion_id)
        task_id = self.create_task(
            cast(str, suggestion["title"]),
            notes=cast(str | None, suggestion["notes"]),
            project_id=project_id,
            due_at=due_at,
        )
        with self._conn:
            self._conn.execute(
                "UPDATE suggestions SET status = 'accepted', updated_at = ? WHERE id = ?",
                (now_iso(), suggestion_id),
            )
        return task_id

    def reject_suggestion(self, suggestion_id: str) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE suggestions SET status = 'rejected', updated_at = ? WHERE id = ?",
                (now_iso(), suggestion_id),
            )

    def _suggestion(self, suggestion_id: str) -> dict[str, object]:
        row = self._conn.execute(
            "SELECT * FROM suggestions WHERE id = ?", (suggestion_id,)
        ).fetchone()
        if row is None:
            raise KeyError(suggestion_id)
        return _require_dict(row)

    def _recurrence_row(self, task_id: str) -> dict[str, object] | None:
        row = self._conn.execute(
            "SELECT * FROM task_recurrence WHERE task_id = ?", (task_id,)
        ).fetchone()
        return _row_to_dict(row)

    def _existing_spawn(
        self, completed_task: dict[str, object], completed_at: str
    ) -> dict[str, object] | None:
        rows = self._conn.execute(
            """SELECT * FROM tasks
               WHERE title = ?
                 AND (project_id IS ? OR project_id = ?)
                 AND status = 'todo'
                 AND created_at >= ?
               ORDER BY created_at ASC
               LIMIT 1""",
            (
                completed_task["title"],
                completed_task["project_id"],
                completed_task["project_id"],
                completed_at,
            ),
        ).fetchall()
        if not rows:
            return None
        return _task_dict(rows[0], self._conn)

    def _update(self, table: str, id: str, updates: dict[str, object]) -> None:
        columns = ", ".join(f"{column} = ?" for column in updates)
        params = tuple(updates.values()) + (id,)
        with self._conn:
            self._conn.execute(f"UPDATE {table} SET {columns} WHERE id = ?", params)


def _next_due_at(*, mode: str, rule: str, due_at: str | None, completed_at: str) -> str | None:
    try:
        if mode == RecurrenceMode.AFTER_COMPLETION.value:
            return _after_completion_due(rule, completed_at)
        if mode == RecurrenceMode.FIXED.value:
            return _fixed_due(rule, due_at)
    except ValueError:
        LOGGER.warning("Could not parse recurrence rule: %s", rule)
    return None


def _after_completion_due(rule: str, completed_at: str) -> str:
    match = re.fullmatch(r"(\d+)\s+(days|weeks)\s+after completion", rule.strip().lower())
    if match is None:
        raise ValueError(rule)
    count = int(match.group(1))
    unit = match.group(2)
    completed = _parse_datetime(completed_at)
    return (completed + timedelta(days=count * (7 if unit == "weeks" else 1))).isoformat()


def _fixed_due(rule: str, due_at: str | None) -> str:
    lowered = rule.strip().lower()
    now = datetime.now(UTC)
    weekday_match = re.fullmatch(r"every\s+([a-z]+)", lowered)
    if weekday_match is not None and weekday_match.group(1) in WEEKDAYS:
        return _next_weekday(now, WEEKDAYS[weekday_match.group(1)]).date().isoformat()
    monthly_match = re.fullmatch(r"monthly\s+on\s+(\d{1,2})", lowered)
    if monthly_match is not None:
        return _next_monthly_boundary(now, int(monthly_match.group(1))).date().isoformat()
    interval_match = re.fullmatch(r"every\s+(\d+)\s+(days|weeks|months)", lowered)
    if interval_match is None:
        raise ValueError(rule)
    count = int(interval_match.group(1))
    unit = interval_match.group(2)
    current = _parse_datetime(due_at) if due_at is not None else now
    while current <= now:
        current = _add_interval(current, count, unit)
    return current.date().isoformat()


def _next_weekday(now: datetime, weekday: int) -> datetime:
    days_ahead = (weekday - now.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return now + timedelta(days=days_ahead)


def _next_monthly_boundary(now: datetime, day: int) -> datetime:
    if day < 1:
        raise ValueError(str(day))
    year = now.year
    month = now.month
    while True:
        candidate = now.replace(
            year=year,
            month=month,
            day=min(day, calendar.monthrange(year, month)[1]),
        )
        if candidate > now:
            return candidate
        month += 1
        if month > 12:
            month = 1
            year += 1


def _add_interval(value: datetime, count: int, unit: str) -> datetime:
    if unit == "days":
        return value + timedelta(days=count)
    if unit == "weeks":
        return value + timedelta(weeks=count)
    if unit == "months":
        return _add_months(value, count)
    raise ValueError(unit)


def _add_months(value: datetime, count: int) -> datetime:
    month_index = value.month - 1 + count
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _task_dict(row: sqlite3.Row, conn: sqlite3.Connection) -> dict[str, object]:
    task = _require_dict(row)
    task["tags"] = json.loads(cast(str, task["tags"]))
    task["subtasks"] = [
        _require_dict(subtask)
        for subtask in conn.execute(
            "SELECT * FROM task_subtasks WHERE task_id = ? ORDER BY position, created_at",
            (task["id"],),
        ).fetchall()
    ]
    recurrence = conn.execute(
        "SELECT * FROM task_recurrence WHERE task_id = ?", (task["id"],)
    ).fetchone()
    task["recurrence"] = _row_to_dict(recurrence)
    return task


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, object] | None:
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}


def _require_dict(row: sqlite3.Row) -> dict[str, object]:
    return {key: row[key] for key in row.keys()}


def _new_id() -> str:
    return uuid.uuid4().hex
