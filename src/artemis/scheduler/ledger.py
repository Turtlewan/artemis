"""SQLite ledger for durable scheduled jobs."""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import cast

from artemis.types import ScheduledJob


@dataclass(frozen=True)
class JobRow:
    id: str
    cron: str | None
    run_at: str | None
    payload: dict  # type: ignore[type-arg]
    next_fire: float


class ScheduleLedger:
    """Per-job schedule state in SQLite.

    sqlite3 is sync; calls are local + low-volume, invoked from the async scheduler. Jobs are
    never deleted — cancel and one-shot-fire flip ``active=0`` (durable audit trail).
    """

    def __init__(
        self,
        db_path: str = ":memory:",
        *,
        now: Callable[[], float] = time.time,
        check_same_thread: bool = True,
    ) -> None:
        self._now = now
        self._conn = sqlite3.connect(db_path, check_same_thread=check_same_thread)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS jobs ("
            " id TEXT PRIMARY KEY, cron TEXT, run_at TEXT, payload TEXT,"
            " next_fire REAL, active INTEGER DEFAULT 1, created_at REAL)"
        )
        self._conn.commit()

    def upsert(self, job: ScheduledJob, *, next_fire: float) -> None:
        self._conn.execute(
            "INSERT INTO jobs(id, cron, run_at, payload, next_fire, active, created_at)"
            " VALUES(?,?,?,?,?,1,?)"
            " ON CONFLICT(id) DO UPDATE SET"
            " cron=excluded.cron, run_at=excluded.run_at, payload=excluded.payload,"
            " next_fire=excluded.next_fire, active=1",
            (job.id, job.cron, job.run_at, json.dumps(job.payload), next_fire, self._now()),
        )
        self._conn.commit()

    def due(self, now: float) -> list[JobRow]:
        rows = cast(
            Iterable[tuple[str, str | None, str | None, str, float]],
            self._conn.execute(
                "SELECT id, cron, run_at, payload, next_fire FROM jobs"
                " WHERE active=1 AND next_fire<=? ORDER BY next_fire",
                (now,),
            ),
        )
        return [JobRow(i, c, r, json.loads(p), nf) for (i, c, r, p, nf) in rows]

    def reschedule(self, job_id: str, *, next_fire: float) -> None:
        self._conn.execute("UPDATE jobs SET next_fire=? WHERE id=?", (next_fire, job_id))
        self._conn.commit()

    def deactivate(self, job_id: str) -> None:
        """One-shot fired or job cancelled — never delete the row."""
        self._conn.execute("UPDATE jobs SET active=0 WHERE id=?", (job_id,))
        self._conn.commit()

    def active(self) -> list[JobRow]:
        rows = cast(
            Iterable[tuple[str, str | None, str | None, str, float]],
            self._conn.execute(
                "SELECT id, cron, run_at, payload, next_fire FROM jobs WHERE active=1"
            ),
        )
        return [JobRow(i, c, r, json.loads(p), nf) for (i, c, r, p, nf) in rows]

    def close(self) -> None:
        self._conn.close()
