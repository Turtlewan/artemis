# v2-11 · forget() + decay/archive over a durable SQLite ledger

status: ready
slice: 2 (memory) — part 5 of 6: tiered demote/decay (archive ≠ delete)
coder: codex
coder_effort: high
autonomy: L5

## Identity

Implement `MemoryPort.forget()` (currently `NotImplementedError`) backed by a durable **SQLite
metadata ledger** tracking per-fact `{first_seen, last_access, access_count, salience}`. `write`
records a fact; `retrieve` bumps access + filters archived; `forget(max_age_days, min_salience)`
**archives** (marks cold, never deletes) facts past the age / below the salience threshold; retrieve
never surfaces archived facts. A pure `decay_rank` (recency × salience × access) is provided for
ranking. Design home: `docs/v2/architecture.md` §5 ("forgetting = demote to cold tier + decay rank;
ARCHIVE, never delete"). Owner chose the durable-SQLite ledger 2026-06-30.
DEFERRED: re-ranking retrieval by decay_rank; un-archive/restore; summarize-overflow (= v2-12).

## Prerequisites

v2-10 committed (`da3cfbe`). `_normalize_fact` exists in `cognee_backend.py` (reuse as the ledger key).

## Files to change

| File | Op | What |
|---|---|---|
| `src/artemis/memory/ledger.py` | create | `MemoryLedger` (stdlib `sqlite3`) + pure `decay_rank` |
| `src/artemis/memory/cognee_backend.py` | modify | wire ledger into `write`/`retrieve`/`forget`; fix stale forget docstring |
| `src/artemis/memory/config.py` | modify | add `decay_half_life_days: float = 30.0`, `default_salience: float = 1.0` |
| `src/artemis/memory/__init__.py` | modify | export `MemoryLedger`, `decay_rank` |
| `tests/memory/test_ledger.py` | create | ledger record/touch/archive + decay_rank (injected clock) |
| `tests/memory/test_cognee_backend.py` | modify | write records · retrieve bumps+filters archived · forget archives by age/salience |

> Scope lock: do NOT touch `ports/`, `types.py`, `model/`, `spine/`, `capabilities/`. Keep cognee
> lazy/injected. The ledger is OPTIONAL (injected); when absent, write/retrieve/forget behave as today
> except `forget` with no ledger raises a clear error (no silent no-op).

## Exact changes

### 1. `src/artemis/memory/ledger.py` (create)
```python
from __future__ import annotations
import math, sqlite3, time
from collections.abc import Callable, Sequence

def decay_rank(*, age_days: float, access_count: int, salience: float,
               half_life_days: float = 30.0) -> float:
    """Composite recency × salience × access score. Higher = keep."""
    recency = math.exp(-max(0.0, age_days) / max(1e-6, half_life_days))
    return salience * (access_count + 1) * recency

class MemoryLedger:
    """Per-fact metadata in SQLite. key = normalized fact content. sqlite3 is sync; calls are
    local + microsecond-scale, invoked from async memory methods (single-owner, low volume)."""
    def __init__(self, db_path: str = ":memory:", *, now: Callable[[], float] = time.time) -> None:
        self._now = now
        self._conn = sqlite3.connect(db_path)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS facts ("
            " key TEXT PRIMARY KEY, first_seen REAL, last_access REAL,"
            " access_count INTEGER, salience REAL, archived INTEGER DEFAULT 0)")
        self._conn.commit()

    def record(self, key: str, *, salience: float = 1.0) -> None:
        t = self._now()
        self._conn.execute(
            "INSERT INTO facts(key, first_seen, last_access, access_count, salience, archived)"
            " VALUES(?,?,?,0,?,0) ON CONFLICT(key) DO NOTHING", (key, t, t, salience))
        self._conn.commit()

    def touch(self, keys: Sequence[str]) -> None:
        t = self._now()
        self._conn.executemany(
            "UPDATE facts SET last_access=?, access_count=access_count+1 WHERE key=?",
            [(t, k) for k in keys])
        self._conn.commit()

    def archived_keys(self) -> set[str]:
        return {r[0] for r in self._conn.execute("SELECT key FROM facts WHERE archived=1")}

    def archive(self, keys: Sequence[str]) -> None:
        self._conn.executemany("UPDATE facts SET archived=1 WHERE key=?", [(k,) for k in keys])
        self._conn.commit()

    def decay(self, *, max_age_days: float | None, min_salience: float | None) -> list[str]:
        """Archive active facts older than max_age_days OR with salience < min_salience.
        Returns the archived keys. Never deletes rows."""
        now = self._now()
        archived: list[str] = []
        for key, first_seen, salience in self._conn.execute(
                "SELECT key, first_seen, salience FROM facts WHERE archived=0"):
            age_days = (now - first_seen) / 86400.0
            if (max_age_days is not None and age_days > max_age_days) or \
               (min_salience is not None and salience < min_salience):
                archived.append(key)
        self.archive(archived)
        return archived

    def close(self) -> None:
        self._conn.close()
```

### 2. `cognee_backend.py` (modify)
- `__init__` gains `*, ledger: MemoryLedger | None = None`; store it.
- `_add(item)` (or `write`): after adding to cognee, if ledger: `ledger.record(_normalize_fact(item.content), salience=config.default_salience)`. (Record on the actual store path — both plain and consolidating ADD/UPDATE.)
- `retrieve`: after producing the final `RetrievedContext`, if ledger: `ledger.touch([_normalize_fact(i.content) for i in ctx.items])`; AND extend the superseded filter to also drop candidates whose normalized key is in `ledger.archived_keys()`. (Compute archived set once per retrieve.)
- `forget`: replace the `NotImplementedError` with:
  ```python
  if self._ledger is None:
      raise RuntimeError("forget() requires a MemoryLedger; none configured")
  self._ledger.decay(max_age_days=max_age_days, min_salience=min_salience)
  ```
  Fix the stale docstring (drop the "v2-09" line).

### 3. `config.py` / `__init__.py` — add the two fields + exports.

## Acceptance criteria

1. **decay_rank (pure):** higher for fresher/more-accessed/more-salient; `age_days=0` > `age_days=60`
   (same other args); `access_count` and `salience` monotonically increase it. → `uv run pytest tests/memory/test_ledger.py -q`
2. **ledger record/touch:** `record("k")` then `touch(["k"])` → access_count 1, last_access advanced
   (use an injected fake clock for determinism). Duplicate `record("k")` is a no-op (ON CONFLICT).
3. **decay archives by threshold (injected clock):** two facts, one aged 100d one aged 1d; `decay(
   max_age_days=30, min_salience=None)` archives only the old one; `archived_keys()` reflects it; a
   low-salience fact is archived by `min_salience`.
4. **retrieve filters archived + bumps access:** ledger with one archived key; fake CHUNKS returns the
   archived + a live fact → retrieve returns only the live one, and `access_count` for the returned
   live fact incremented.
5. **write records:** `write` with a ledger inserts the normalized key (`access_count=0`).
6. **forget without ledger raises:** `CogneeMemory(...)` (no ledger) `.forget()` raises `RuntimeError`
   (explicit, not silent). With a ledger, `forget(max_age_days=...)` archives via the ledger.
7. **Green:** `uv run mypy` (strict, cognee absent) + `uv run pytest -q` (prior 79 + new) +
   `uv run ruff check/format` all pass.

## Commands to run
```bash
uv run ruff format --check src tests
uv run ruff check src tests
uv run mypy
uv run pytest -q
```

## Post-build (host) — live smoke (optional, light)
No Cognee needed: construct `MemoryLedger(tmp.db)`, record 2 facts with an injected clock, decay one by
age, confirm it survives reopen (durability) — proves the SQLite ledger persists across restart.
