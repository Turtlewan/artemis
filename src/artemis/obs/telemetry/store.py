"""SQLCipher-backed telemetry event store.

All timestamps are stored as integer epoch milliseconds. The schema is managed
with ``PRAGMA user_version`` from its first migration, and ``prune`` provides
the retention primitive later maintenance jobs can schedule.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from sqlite3 import Connection

from artemis.config import Settings
from artemis.data.sqlcipher import sqlcipher_open
from artemis.identity.key_provider import SecretKey
from artemis.paths import scope_dir


@dataclass(frozen=True)
class CallTrace:
    """One model completion trace with token, latency, and attribution data."""

    role: str
    model_id: str | None
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: int
    cost_micros: int
    trace_id: str | None
    at: datetime


@dataclass(frozen=True)
class UsageRow:
    """Aggregated usage totals for one role."""

    role: str
    calls: int
    total_tokens: int
    cost_micros: int


def telemetry_db_path(s: Settings) -> Path:
    """Return the owner-private telemetry database path without creating it."""

    return scope_dir(s, "owner-private") / "relational" / "telemetry.db"


def open_telemetry_db(path: Path, key: SecretKey) -> Connection:
    """Open a keyed SQLCipher telemetry database and set runtime pragmas."""

    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlcipher_open(path, key.as_hex())
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _to_ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _from_ms(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, UTC)


class TelemetryStore:
    """Owner-private telemetry store for routes, escalations, and model calls."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn
        self._migrate()

    def record_route(
        self,
        task_class_key: str,
        confidence: float,
        path: str,
        *,
        trace_id: str | None = None,
        at: datetime,
    ) -> None:
        """Insert one route decision event."""

        self._conn.execute(
            """
            INSERT INTO route_events(task_class_key, confidence, path, trace_id, at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (task_class_key, confidence, path, trace_id, _to_ms(at)),
        )
        self._conn.commit()

    def record_escalation(
        self,
        task_class_key: str,
        is_cloud_safe: bool,
        *,
        trace_id: str | None = None,
        at: datetime,
    ) -> None:
        """Insert one escalation event."""

        self._conn.execute(
            """
            INSERT INTO escalations(task_class_key, is_cloud_safe, trace_id, at)
            VALUES (?, ?, ?, ?)
            """,
            (task_class_key, int(is_cloud_safe), trace_id, _to_ms(at)),
        )
        self._conn.commit()

    def record_call(self, trace: CallTrace) -> None:
        """Insert one model-call trace."""

        self._conn.execute(
            """
            INSERT INTO call_traces(
                role, model_id, prompt_tokens, completion_tokens, total_tokens,
                latency_ms, cost_micros, trace_id, at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trace.role[:64],
                trace.model_id,
                trace.prompt_tokens,
                trace.completion_tokens,
                trace.total_tokens,
                trace.latency_ms,
                trace.cost_micros,
                trace.trace_id,
                _to_ms(trace.at),
            ),
        )
        self._conn.commit()

    def route_events(self) -> list[tuple[str, float, str, datetime]]:
        """Return all route events as confidence observations."""

        rows = self._conn.execute(
            """
            SELECT task_class_key, confidence, path, at
            FROM route_events
            ORDER BY id
            """
        ).fetchall()
        return [
            (str(key), float(conf), str(path), _from_ms(int(at))) for key, conf, path, at in rows
        ]

    def escalation_events(self) -> list[tuple[str, datetime]]:
        """Return all escalation events."""

        rows = self._conn.execute(
            """
            SELECT task_class_key, at
            FROM escalations
            ORDER BY id
            """
        ).fetchall()
        return [(str(key), _from_ms(int(at))) for key, at in rows]

    def topic_counts(self) -> dict[str, int]:
        """Return route counts grouped by task class key."""

        rows = self._conn.execute(
            """
            SELECT task_class_key, COUNT(*)
            FROM route_events
            GROUP BY task_class_key
            """
        ).fetchall()
        return {str(key): int(count) for key, count in rows}

    def usage_summary(self, *, since: datetime) -> list[UsageRow]:
        """Return model usage grouped by role for traces at or after ``since``."""

        rows = self._conn.execute(
            """
            SELECT role, COUNT(*), SUM(total_tokens), SUM(cost_micros)
            FROM call_traces
            WHERE at >= ?
            GROUP BY role
            ORDER BY role
            """,
            (_to_ms(since),),
        ).fetchall()
        return [
            UsageRow(
                role=str(role),
                calls=int(calls),
                total_tokens=int(total_tokens or 0),
                cost_micros=int(cost_micros or 0),
            )
            for role, calls, total_tokens, cost_micros in rows
        ]

    def prune(self, *, older_than: datetime) -> int:
        """Delete events older than ``older_than`` and return the rows removed."""

        cutoff = _to_ms(older_than)
        deleted = 0
        for table in ("route_events", "escalations", "call_traces"):
            cursor = self._conn.execute(f"DELETE FROM {table} WHERE at < ?", (cutoff,))
            deleted += cursor.rowcount
        self._conn.commit()
        return deleted

    def _migrate(self) -> None:
        version = int(self._conn.execute("PRAGMA user_version").fetchone()[0])
        if version >= 1:
            return
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS route_events(
                id INTEGER PRIMARY KEY,
                task_class_key TEXT NOT NULL,
                confidence REAL NOT NULL,
                path TEXT NOT NULL,
                trace_id TEXT,
                at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS escalations(
                id INTEGER PRIMARY KEY,
                task_class_key TEXT NOT NULL,
                is_cloud_safe INTEGER NOT NULL,
                trace_id TEXT,
                at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS call_traces(
                id INTEGER PRIMARY KEY,
                role TEXT NOT NULL,
                model_id TEXT,
                prompt_tokens INTEGER NOT NULL,
                completion_tokens INTEGER NOT NULL,
                total_tokens INTEGER NOT NULL,
                latency_ms INTEGER NOT NULL,
                cost_micros INTEGER NOT NULL,
                trace_id TEXT,
                at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_route_events_task_class_key
                ON route_events(task_class_key);
            CREATE INDEX IF NOT EXISTS idx_route_events_at
                ON route_events(at);
            CREATE INDEX IF NOT EXISTS idx_escalations_at
                ON escalations(at);
            CREATE INDEX IF NOT EXISTS idx_call_traces_at
                ON call_traces(at);
            CREATE INDEX IF NOT EXISTS idx_call_traces_at_role
                ON call_traces(at, role);
            PRAGMA user_version = 1;
            """
        )
        self._conn.commit()
