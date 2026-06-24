"""Owner-private SQLCipher activity log for unattended calendar auto-actions."""

from __future__ import annotations

import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from artemis import paths
from artemis.config import Settings
from artemis.data.sqlcipher import sqlcipher_open
from artemis.identity.key_provider import KeyProvider
from artemis.identity.scope import OWNER_PRIVATE
from artemis.modules.calendar.write_tools import WriteResult


@dataclass(frozen=True)
class ActivityLogEntry:
    """One encrypted audit row for an unattended calendar write."""

    ts_ms: int
    tool_name: str
    event_id: str
    event_summary: str
    result_status: str


class ActivityLog:
    """Append-only owner-private activity log using the token-store SQLCipher pattern."""

    def __init__(self, settings: Settings, key_provider: KeyProvider) -> None:
        self.settings = settings
        self.key_provider = key_provider

    def _db_path(self) -> Path:
        return paths.scope_dir(self.settings, OWNER_PRIVATE) / "calendar" / "activity_log.db"

    def _connect(self) -> sqlite3.Connection:
        key = self.key_provider.dek_for_scope(OWNER_PRIVATE)
        key_hex = key.as_hex()
        self._db_path().parent.mkdir(parents=True, exist_ok=True)
        conn = sqlcipher_open(self._db_path(), key_hex)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS activity_log (
                ts_ms INTEGER NOT NULL,
                tool_name TEXT NOT NULL,
                event_id TEXT NOT NULL,
                event_summary TEXT NOT NULL,
                result_status TEXT NOT NULL
            )
            """
        )
        conn.commit()
        return conn

    def record(self, result: WriteResult) -> None:
        """Append an auto-action result; ``ScopeLockedError`` propagates."""
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO activity_log (
                    ts_ms, tool_name, event_id, event_summary, result_status
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    time.time_ns() // 1_000_000,
                    result.tool_name,
                    result.event_id,
                    result.summary,
                    result.status,
                ),
            )
            conn.commit()

    def recent(self, limit: int = 50) -> list[ActivityLogEntry]:
        """Return recent activity rows newest first; ``ScopeLockedError`` propagates."""
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT ts_ms, tool_name, event_id, event_summary, result_status
                FROM activity_log
                ORDER BY ts_ms DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            ActivityLogEntry(
                ts_ms=cast(int, row[0]),
                tool_name=cast(str, row[1]),
                event_id=cast(str, row[2]),
                event_summary=cast(str, row[3]),
                result_status=cast(str, row[4]),
            )
            for row in rows
        ]
