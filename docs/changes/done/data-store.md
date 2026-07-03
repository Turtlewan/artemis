# data-store — generic local record store (data-spine Wave 0)

**Identity:** The native SQLite record store at the root of the local-first data spine — one generic
table, domains are labels not schemas. ADR-046 #7 · design note `docs/v2/local-data-spine.md`.

Dead-until-consumed: this spec adds the store module + tests only. No `app.state` wiring, no callers
— Wave 1 (`data-ingest`, `data-read`) consume it. Mirrors the `MemoryLedger` idiom
(`src/artemis/memory/ledger.py`): plain `sqlite3`, `CREATE TABLE IF NOT EXISTS` in `__init__`,
`?`-parameterized queries, injected `now` clock. No encryption (none exists in the repo yet).

## Files to change
| Op | Path |
|----|------|
| create | `src/artemis/data/__init__.py` |
| create | `src/artemis/data/store.py` |
| create | `tests/data/__init__.py` |
| create | `tests/data/test_store.py` |

## Exact changes

### Task 1 — `src/artemis/data/__init__.py` (create)
Empty package marker (one line docstring allowed):
```python
"""Local-first data spine (ADR-046)."""
```

### Task 2 — `src/artemis/data/store.py` (create)
A `Record` dataclass + `DataStore` over one generic `records` table. Full module:

```python
"""Generic local record store — root of the local-first data spine (ADR-046 #7).

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
        self._conn = sqlite3.connect(db_path)
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
        """Insert, or on (domain,kind,key) conflict update feed fields only — owner_fields survive."""
        self._conn.execute(
            "INSERT INTO records"
            " (domain, kind, key, payload, sanitized_text, source, fetched_at, owner_fields)"
            " VALUES (?,?,?,?,?,?,?,?)"
            " ON CONFLICT(domain, kind, key) DO UPDATE SET"
            "  payload=excluded.payload, sanitized_text=excluded.sanitized_text,"
            "  source=excluded.source, fetched_at=excluded.fetched_at",
            (
                record.domain,
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
        """Max fetched_at in a domain — the freshness-gate primitive (ADR-046 #5). None if empty."""
        row = self._conn.execute(
            "SELECT MAX(fetched_at) FROM records WHERE domain=?", (domain,)
        ).fetchone()
        if row is None:
            return None
        return cast("float | None", row[0])

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
```

### Task 3 — `tests/data/__init__.py` (create)
Empty file (package marker, matches `tests/memory/__init__.py`).

### Task 4 — `tests/data/test_store.py` (create)
Cover every acceptance criterion below. Use an in-`:memory:` store and a `FakeClock`-style counter
is NOT needed (records carry their own `fetched_at`). Suggested shape:

```python
from artemis.data.store import DataStore, Record


def _rec(**over: object) -> Record:
    base = dict(
        domain="calendar", kind="event", key="e1",
        payload={"title": "Standup"}, sanitized_text="Standup at 9am",
        source="today-calendar", fetched_at=100.0, owner_fields={},
    )
    base.update(over)
    return Record(**base)  # type: ignore[arg-type]


def test_upsert_get_roundtrip() -> None:
    s = DataStore()
    s.upsert(_rec(payload={"title": "Standup", "n": 3}, owner_fields={"note": "skip"}))
    got = s.get("calendar", "event", "e1")
    assert got is not None
    assert got.payload == {"title": "Standup", "n": 3}
    assert got.owner_fields == {"note": "skip"}


def test_upsert_preserves_owner_fields() -> None:
    s = DataStore()
    s.upsert(_rec(owner_fields={"note": "keep me"}))
    s.upsert(_rec(sanitized_text="Standup moved to 10am", fetched_at=200.0))  # re-pull, no owner_fields
    got = s.get("calendar", "event", "e1")
    assert got is not None
    assert got.sanitized_text == "Standup moved to 10am"  # feed field updated
    assert got.fetched_at == 200.0
    assert got.owner_fields == {"note": "keep me"}  # preserved


def test_query_newest_first_and_filters() -> None:
    s = DataStore()
    s.upsert(_rec(key="e1", sanitized_text="Standup", fetched_at=100.0))
    s.upsert(_rec(key="e2", sanitized_text="Lunch with Sam", fetched_at=200.0, kind="event"))
    s.upsert(_rec(key="t1", domain="calendar", kind="task", sanitized_text="File taxes", fetched_at=150.0))
    newest = s.query(domain="calendar")
    assert [r.key for r in newest] == ["e2", "t1", "e1"]  # fetched_at desc
    assert [r.key for r in s.query(domain="calendar", kinds=["task"])] == ["t1"]
    assert [r.key for r in s.query(domain="calendar", since=160.0)] == ["e2"]
    assert [r.key for r in s.query(domain="calendar", text="lunch")] == ["e2"]  # case-insensitive


def test_query_text_wildcards_are_literal() -> None:
    s = DataStore()
    s.upsert(_rec(key="a", sanitized_text="50% off"))
    s.upsert(_rec(key="b", sanitized_text="5000 off"))
    assert [r.key for r in s.query(domain="calendar", text="50%")] == ["a"]  # % is literal, not wildcard


def test_latest_fetched_at() -> None:
    s = DataStore()
    assert s.latest_fetched_at("calendar") is None
    s.upsert(_rec(key="e1", fetched_at=100.0))
    s.upsert(_rec(key="e2", fetched_at=250.0))
    assert s.latest_fetched_at("calendar") == 250.0


def test_delete() -> None:
    s = DataStore()
    s.upsert(_rec())
    s.delete("calendar", "event", "e1")
    assert s.get("calendar", "event", "e1") is None
```

## Acceptance criteria
1. `upsert` then `get` round-trips a record; `payload`/`owner_fields` dicts survive the JSON round-trip. → `test_upsert_get_roundtrip`
2. A second `upsert` on the same `(domain,kind,key)` updates feed fields (`sanitized_text`/`fetched_at`) but preserves the existing `owner_fields`. → `test_upsert_preserves_owner_fields`
3. `query(domain=...)` returns newest-first; `kinds`, `since`, and case-insensitive `text` substring filters work. → `test_query_newest_first_and_filters`
4. LIKE metacharacters in `text` (`%`, `_`) match literally, not as wildcards. → `test_query_text_wildcards_are_literal`
5. `latest_fetched_at` returns the max `fetched_at` for a domain and `None` for an empty domain. → `test_latest_fetched_at`
6. `delete` removes the row. → `test_delete`
7. Whole-project `uv run mypy src/` clean (strict) and `uv run ruff check` clean.

## Commands to run
```
uv run ruff check src/ tests/
uv run mypy src/
uv run pytest -q tests/data/
uv run pytest -q
```
