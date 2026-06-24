"""SQLite schema for the owner-private productivity module.

The productivity model is two-level: Projects own Tasks, and tasks without a
project float independently. Areas were removed in schema version 2.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from enum import StrEnum

SCHEMA_VERSION = "2"


class TaskStatus(StrEnum):
    """Task lifecycle states."""

    TODO = "todo"
    DOING = "doing"
    DONE = "done"
    CANCELLED = "cancelled"


class TaskPriority(StrEnum):
    """Task priority labels."""

    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ProjectStatus(StrEnum):
    """Project lifecycle states."""

    ACTIVE = "active"
    ON_HOLD = "on_hold"
    DONE = "done"


class RecurrenceMode(StrEnum):
    """Supported recurrence scheduling modes."""

    FIXED = "fixed"
    AFTER_COMPLETION = "after_completion"


def now_iso() -> str:
    """Return an ISO-8601 UTC timestamp."""
    return datetime.now(UTC).isoformat()


def create_schema(conn: sqlite3.Connection) -> None:
    """Create the productivity schema idempotently with FK checks enabled."""
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active'
                CHECK(status IN ('active', 'on_hold', 'done')),
            target_date TEXT,
            notes TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN (0, 1)),
            project_goal_entity_id TEXT
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            notes TEXT,
            status TEXT NOT NULL DEFAULT 'todo'
                CHECK(status IN ('todo', 'doing', 'done', 'cancelled')),
            priority TEXT NOT NULL DEFAULT 'none'
                CHECK(priority IN ('none', 'low', 'medium', 'high')),
            tags TEXT NOT NULL DEFAULT '[]',
            project_id TEXT REFERENCES projects(id),
            estimate_minutes INTEGER,
            due_at TEXT,
            scheduled_block TEXT,
            calendar_event_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            completed_at TEXT
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_project_id ON tasks(project_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)")
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_tasks_due_at
        ON tasks(due_at)
        WHERE status NOT IN ('done', 'cancelled')
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS task_subtasks (
            id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            done INTEGER NOT NULL DEFAULT 0 CHECK(done IN (0, 1)),
            position INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_task_subtasks_task_id ON task_subtasks(task_id)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS task_recurrence (
            task_id TEXT PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE,
            mode TEXT NOT NULL CHECK(mode IN ('fixed', 'after_completion')),
            rule TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS suggestions (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            notes TEXT,
            source TEXT NOT NULL DEFAULT 'manual',
            raw_context TEXT,
            commitment_shape TEXT,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('pending', 'accepted', 'rejected')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_suggestions_status ON suggestions(status)")
    created_at = now_iso()
    conn.execute(
        "INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)",
        ("schema_version", SCHEMA_VERSION),
    )
    conn.execute(
        "INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)",
        ("created_at", created_at),
    )
    conn.commit()
