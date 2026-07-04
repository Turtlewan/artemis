"""Generic local record store -- root of the local-first data spine (ADR-046 #7).

Domains are labels, not schemas: a new capability introduces a new `domain` tag, never a
table/migration. Identity of a record is (domain, kind, key). Feed re-pulls update feed fields
only; `owner_fields` (owner annotations) are preserved across upserts (ADR-046 merge rule).
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, cast

_Row = tuple[str, str, str, str, str, str, float, str]


@dataclass(frozen=True)
class Record:
    """One stored record. Feed fields (payload/sanitized_text/source/fetched_at) come from the
    upstream pull; owner_fields hold owner annotations that re-pulls must never overwrite."""

    domain: str
    kind: str
    key: str
    payload: dict[str, Any]
    sanitized_text: str
    source: str
    fetched_at: float
    owner_fields: dict[str, Any] = field(default_factory=dict)


class DataStore:
    """Single generic SQLite record store. sqlite3 is sync; calls are local and low-volume."""

    def __init__(self, db_path: str = ":memory:", *, now: Callable[[], float] = time.time) -> None:
        self._now = now
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS records ("
            " domain TEXT, kind TEXT, key TEXT,"
            " payload TEXT, sanitized_text TEXT, source TEXT, fetched_at REAL,"
            " owner_fields TEXT DEFAULT '{}',"
            " PRIMARY KEY (domain, kind, key))"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_records_domain_fetched ON records(domain, fetched_at)"
        )
        self._conn.commit()

    def upsert(self, record: Record) -> None:
        """Insert, or on (domain,kind,key) conflict update feed fields only -- owner_fields survive.
        The domain label is normalized (strip+lower) HERE -- the one chokepoint every write path
        goes through, so labels cannot fragment (ADR-048 #5)."""
        domain = record.domain.strip().lower()
        self._conn.execute(
            "INSERT INTO records"
            " (domain, kind, key, payload, sanitized_text, source, fetched_at, owner_fields)"
            " VALUES (?,?,?,?,?,?,?,?)"
            " ON CONFLICT(domain, kind, key) DO UPDATE SET"
            "  payload=excluded.payload, sanitized_text=excluded.sanitized_text,"
            "  source=excluded.source, fetched_at=excluded.fetched_at",
            (
                domain,
                record.kind,
                record.key,
                json.dumps(record.payload),
                record.sanitized_text,
                record.source,
                record.fetched_at,
                json.dumps(record.owner_fields),
            ),
        )
        self._conn.commit()

    def get(self, domain: str, kind: str, key: str) -> Record | None:
        row = self._conn.execute(
            "SELECT domain, kind, key, payload, sanitized_text, source, fetched_at, owner_fields"
            " FROM records WHERE domain=? AND kind=? AND key=?",
            (domain, kind, key),
        ).fetchone()
        if row is None:
            return None
        return _row_to_record(cast(_Row, row))

    def query(
        self,
        *,
        domain: str,
        kinds: Sequence[str] | None = None,
        since: float | None = None,
        text: str | None = None,
        limit: int = 50,
    ) -> list[Record]:
        """Records in a domain, newest first. Optional kind filter, `fetched_at >= since`, and a
        case-insensitive substring match on sanitized_text (LIKE wildcards in `text` are escaped)."""
        sql = [
            "SELECT domain, kind, key, payload, sanitized_text, source, fetched_at, owner_fields"
            " FROM records WHERE domain=?"
        ]
        args: list[Any] = [domain]
        if kinds:
            placeholders = ",".join("?" * len(kinds))
            sql.append(f" AND kind IN ({placeholders})")
            args.extend(kinds)
        if since is not None:
            sql.append(" AND fetched_at >= ?")
            args.append(since)
        if text:
            sql.append(" AND sanitized_text LIKE ? ESCAPE '\\'")
            args.append(f"%{_like_escape(text)}%")
        sql.append(" ORDER BY fetched_at DESC LIMIT ?")
        args.append(limit)
        rows = cast(Iterable[_Row], self._conn.execute("".join(sql), tuple(args)))
        return [_row_to_record(row) for row in rows]

    def latest_fetched_at(self, domain: str) -> float | None:
        """Max fetched_at in a domain -- the freshness-gate primitive (ADR-046 #5). None if empty."""
        row = self._conn.execute(
            "SELECT MAX(fetched_at) FROM records WHERE domain=?", (domain,)
        ).fetchone()
        if row is None:
            return None
        return cast("float | None", row[0])

    def domains(self) -> list[str]:
        """Distinct domain labels present in the store -- the live domain list (ADR-048 #2).
        A domain exists iff it has rows; there is no registry."""
        rows = self._conn.execute("SELECT DISTINCT domain FROM records ORDER BY domain").fetchall()
        return [cast(str, row[0]) for row in rows]

    def has_foreign_source(self, domain: str, *, own_source: str = "curate") -> bool:
        """True iff `domain` holds any row written by a non-curate source -- the synced-domain
        guard (review BLOCK 2): curated CRUD must refuse such domains. A curated fetched_at=now()
        in a synced domain would fake-fresh a stale sync; a forget would silently resurrect on
        the next sync."""
        row = self._conn.execute(
            "SELECT 1 FROM records WHERE domain=? AND source != ? LIMIT 1", (domain, own_source)
        ).fetchone()
        return row is not None

    def delete(self, domain: str, kind: str, key: str) -> None:
        self._conn.execute(
            "DELETE FROM records WHERE domain=? AND kind=? AND key=?", (domain, kind, key)
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()


def _row_to_record(row: _Row) -> Record:
    domain, kind, key, payload, sanitized_text, source, fetched_at, owner_fields = row
    return Record(
        domain=domain,
        kind=kind,
        key=key,
        payload=cast("dict[str, Any]", json.loads(payload)),
        sanitized_text=sanitized_text,
        source=source,
        fetched_at=fetched_at,
        owner_fields=cast("dict[str, Any]", json.loads(owner_fields)),
    )


def _like_escape(text: str) -> str:
    """Escape LIKE metacharacters so `text` matches literally under `ESCAPE '\\'`."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
