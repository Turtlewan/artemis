"""Lazy SQLCipher-backed store for productivity data."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from artemis import paths
from artemis.config import Settings
from artemis.data.sqlcipher import sqlcipher_open
from artemis.identity.key_provider import KeyProvider
from artemis.identity.scope import OWNER_PRIVATE
from artemis.modules.productivity.repository import GoalEntityRepo, ProductivityRepository
from artemis.modules.productivity.schema import create_schema


class ProductivityStore:
    """Owner-private productivity store with lazy SQLCipher connection setup."""

    def __init__(self, settings: Settings, key_provider: KeyProvider) -> None:
        self.settings = settings
        self.key_provider = key_provider
        self._conn: sqlite3.Connection | None = None

    def _db_path(self) -> Path:
        return paths.scope_dir(self.settings, OWNER_PRIVATE) / "relational" / "productivity.db"

    def _connect(self) -> sqlite3.Connection:
        """Open the productivity DB and ensure schema exists.

        ``key_hex`` stays local to this method and is never stored on ``self``
        or at module scope.
        """
        key = self.key_provider.dek_for_scope(OWNER_PRIVATE)
        key_hex = key.as_hex()
        db_path = self._db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlcipher_open(db_path, key_hex)
        conn.execute("PRAGMA foreign_keys = ON")
        create_schema(conn)
        return conn

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = self._connect()
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _repo(self) -> ProductivityRepository:
        return ProductivityRepository(self._get_conn())

    def create_project(
        self,
        title: str,
        *,
        notes: str | None = None,
        target_date: str | None = None,
        entity_repo: GoalEntityRepo | None = None,
    ) -> str:
        return self._repo().create_project(
            title,
            notes=notes,
            target_date=target_date,
            entity_repo=entity_repo,
        )

    def get_project(self, id: str) -> dict[str, object] | None:
        return self._repo().get_project(id)

    def list_projects(
        self,
        *,
        status: str | None = None,
        include_archived: bool = False,
    ) -> list[dict[str, object]]:
        return self._repo().list_projects(
            status=status,
            include_archived=include_archived,
        )

    def update_project(
        self,
        id: str,
        *,
        title: str | None = None,
        notes: str | None = None,
        status: str | None = None,
        target_date: str | None = None,
    ) -> None:
        self._repo().update_project(
            id,
            title=title,
            notes=notes,
            status=status,
            target_date=target_date,
        )

    def archive_project(self, id: str) -> None:
        self._repo().archive_project(id)

    def project_tasks(self, project_id: str) -> list[dict[str, object]]:
        return self._repo().project_tasks(project_id)

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
        return self._repo().create_task(
            title,
            notes=notes,
            status=status,
            priority=priority,
            tags=tags,
            project_id=project_id,
            estimate_minutes=estimate_minutes,
            due_at=due_at,
        )

    def get_task(self, id: str) -> dict[str, object] | None:
        return self._repo().get_task(id)

    def list_tasks(
        self,
        *,
        status: str | None = None,
        project_id: str | None = None,
    ) -> list[dict[str, object]]:
        return self._repo().list_tasks(status=status, project_id=project_id)

    def search_tasks(self, query: str) -> list[dict[str, object]]:
        return self._repo().search_tasks(query)

    def today_tasks(self) -> list[dict[str, object]]:
        return self._repo().today_tasks()

    def upcoming_tasks(self, days: int = 7) -> list[dict[str, object]]:
        return self._repo().upcoming_tasks(days)

    def overdue_tasks(self) -> list[dict[str, object]]:
        return self._repo().overdue_tasks()

    def complete_task(self, id: str) -> dict[str, object] | None:
        return self._repo().complete_task(id)

    def cancel_task(self, id: str) -> None:
        self._repo().cancel_task(id)

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
        self._repo().update_task(
            id,
            title=title,
            notes=notes,
            priority=priority,
            tags=tags,
            project_id=project_id,
            estimate_minutes=estimate_minutes,
            due_at=due_at,
            scheduled_block=scheduled_block,
            calendar_event_id=calendar_event_id,
        )

    def assign_task_to_project(self, task_id: str, project_id: str) -> None:
        self._repo().assign_task_to_project(task_id, project_id)

    def set_recurrence(self, task_id: str, mode: str, rule: str) -> None:
        self._repo().set_recurrence(task_id, mode, rule)

    def clear_recurrence(self, task_id: str) -> None:
        self._repo().clear_recurrence(task_id)

    def clear_task_schedule_link(self, task_id: str) -> None:
        self._repo().clear_task_schedule_link(task_id)

    def spawn_next_recurrence(self, completed_task_id: str) -> dict[str, object]:
        return self._repo().spawn_next_recurrence(completed_task_id)

    def add_subtask(self, task_id: str, title: str, position: int = 0) -> str:
        return self._repo().add_subtask(task_id, title, position)

    def complete_subtask(self, subtask_id: str) -> None:
        self._repo().complete_subtask(subtask_id)

    def list_subtasks(self, task_id: str) -> list[dict[str, object]]:
        return self._repo().list_subtasks(task_id)

    def delete_subtask(self, subtask_id: str) -> None:
        self._repo().delete_subtask(subtask_id)

    def create_suggestion(
        self,
        title: str,
        *,
        notes: str | None = None,
        source: str = "manual",
        raw_context: str | None = None,
        commitment_shape: str | None = None,
    ) -> str:
        return self._repo().create_suggestion(
            title,
            notes=notes,
            source=source,
            raw_context=raw_context,
            commitment_shape=commitment_shape,
        )

    def list_suggestions(self, *, status: str = "pending") -> list[dict[str, object]]:
        return self._repo().list_suggestions(status=status)

    def get_suggestion(self, suggestion_id: str) -> dict[str, object] | None:
        return self._repo().get_suggestion(suggestion_id)

    def accept_suggestion(
        self,
        suggestion_id: str,
        *,
        project_id: str | None = None,
        due_at: str | None = None,
    ) -> str:
        return self._repo().accept_suggestion(
            suggestion_id,
            project_id=project_id,
            due_at=due_at,
        )

    def reject_suggestion(self, suggestion_id: str) -> None:
        self._repo().reject_suggestion(suggestion_id)
