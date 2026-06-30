"""SQLite metadata ledger for memory facts."""

from __future__ import annotations

import math
import sqlite3
import time
from collections.abc import Callable, Iterable, Sequence
from typing import cast


def decay_rank(
    *,
    age_days: float,
    access_count: int,
    salience: float,
    half_life_days: float = 30.0,
) -> float:
    """Composite recency x salience x access score. Higher = keep."""
    recency = math.exp(-max(0.0, age_days) / max(1e-6, half_life_days))
    return salience * (access_count + 1) * recency


class MemoryLedger:
    """Per-fact metadata in SQLite.

    key = normalized fact content. sqlite3 is sync; calls are local and low-volume, invoked from
    async memory methods.
    """

    def __init__(self, db_path: str = ":memory:", *, now: Callable[[], float] = time.time) -> None:
        self._now = now
        self._conn = sqlite3.connect(db_path)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS facts ("
            " key TEXT PRIMARY KEY, first_seen REAL, last_access REAL,"
            " access_count INTEGER, salience REAL, archived INTEGER DEFAULT 0)"
        )
        self._conn.commit()

    def record(self, key: str, *, salience: float = 1.0) -> None:
        t = self._now()
        self._conn.execute(
            "INSERT INTO facts(key, first_seen, last_access, access_count, salience, archived)"
            " VALUES(?,?,?,0,?,0) ON CONFLICT(key) DO NOTHING",
            (key, t, t, salience),
        )
        self._conn.commit()

    def touch(self, keys: Sequence[str]) -> None:
        t = self._now()
        self._conn.executemany(
            "UPDATE facts SET last_access=?, access_count=access_count+1 WHERE key=?",
            [(t, key) for key in keys],
        )
        self._conn.commit()

    def archived_keys(self) -> set[str]:
        rows = cast(
            Iterable[tuple[str]],
            self._conn.execute("SELECT key FROM facts WHERE archived=1"),
        )
        return {key for (key,) in rows}

    def archive(self, keys: Sequence[str]) -> None:
        self._conn.executemany("UPDATE facts SET archived=1 WHERE key=?", [(key,) for key in keys])
        self._conn.commit()

    def decay(self, *, max_age_days: float | None, min_salience: float | None) -> list[str]:
        """Archive old or low-salience active facts and return their keys; never delete rows."""
        now = self._now()
        archived: list[str] = []
        rows = cast(
            Iterable[tuple[str, float, float]],
            self._conn.execute("SELECT key, first_seen, salience FROM facts WHERE archived=0"),
        )
        for key, first_seen, salience in rows:
            age_days = (now - first_seen) / 86400.0
            if (max_age_days is not None and age_days > max_age_days) or (
                min_salience is not None and salience < min_salience
            ):
                archived.append(key)
        self.archive(archived)
        return archived

    def close(self) -> None:
        self._conn.close()
