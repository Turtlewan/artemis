<!-- amended 2026-06-17 per apex-data + apex-search spec reviews: FTS rebuild on incremental add (A), scope input guard (B), dimension-lock on reopen (C), cosine metric-contract test (D), Windows-safe FTS fallback (E), withdrew false M3-a forward-compat claim → test-only (F), search_text scope-isolation test (G) -->
---
spec: slice-3a-lancedb-vectorstore
status: ready
token_profile: lean
autonomy_level: L3
coder_tier: pro
---

# Spec: slice-3a — LanceDB `VectorStore` core (dense KNN + FTS round-trip, dimension-lock) on a plain dir

**Identity:** A reduced, pre-Mini-buildable, **test-only** proof that the M0-d `VectorStore` port round-trips on a real LanceDB table: dense cosine KNN via `search`, an FTS/BM25 `search_text` method, and a hard dimension-lock (enforced on write **and** re-open), proven by deterministic-vector golden tests on a **plain directory** (no M2 encrypted volume). This is NOT the production store — full M3-a replaces this module with an ingestion-backed `LanceDBVectorStore` that has a richer schema (per-scope tables, `content_hash` + locator columns, metadata dimension-lock, encrypted-volume binding). This slice exists to get LanceDB execution signal on Windows now.
→ why: validation-slice continuation (status.md Open Question 2026-06-17 "Slice 2 on-deck"; mirrors slice 2a's reduced bitemporal core). Grows pre-Mini execution signal on the knowledge subsystem.

<!-- A spec is an EXECUTION SCRIPT, not a design doc. DeepSeek executes literally. -->
<!-- Split rule: ONE phase (the VectorStore round-trip) across 1 create (knowledge/__init__.py) + 1 create (knowledge/vector_store.py) + 1 create (tests/test_vector_store.py). The `lancedb` dependency is added via `uv add` (Commands), not a hand-edited 4th source file. Within the 3-file limit. -->

## Assumptions
- Slice 1 built M0-d: `src/artemis/ports/retrieval.py` defines `VectorStore` (`add(scope, ids, vectors, metadata) -> None`; `search(scope, query, k) -> list[RetrievedChunk]`, both **sync** — local-disk per ADR-015) and `src/artemis/ports/types.py` defines `Chunk(chunk_id, document_id, text, scope)`, `RetrievedChunk(chunk, score)`, `Vector = Sequence[float]`, `Scope = str`. → impact: Stop (verified against current code 2026-06-17; `LanceDBVectorStore` must structurally satisfy `VectorStore`).
- **(F) This slice is TEST-ONLY and its on-disk DB is NOT forward-compatible with M3-a.** M3-a's production `LanceDBVectorStore` (Task 5) uses one table per scope (`docs_{scope}`), extra columns (`content_hash`, `source_id`, page/bbox/char-span locators), and stores `dimension` + `embedder_model_id` in table metadata. This slice deliberately uses a SINGLE `"chunks"` table with a scope column and a minimal 5-field schema. The slice DB MUST therefore only ever be created at a throwaway path (tests use `tmp_path`); it must NEVER be created at a path M3-a will later open. M3-a **replaces** `knowledge/vector_store.py` with the full store — the slice's class is a stepping-stone, not a base M3-a extends. → impact: Stop (the earlier "MUST be forward-compatible with M3-a's LanceDBVectorStore" claim is WITHDRAWN; do not point M3-a at a slice DB).
- **Reductions vs full M3-a (deliberate, documented):** (1) plain dir, not the M2 encrypted volume. (2) single `"chunks"` table + scope column, not per-scope tables (the cross-scope wall is M2's job). (3) no ingestion (no connector/Docling/chunking/`content_hash`; callers pass `(ids, vectors, metadata)` directly). (4) no reranker / hybrid RRF (M3-b). → impact: Caution (same kind of fallback slice 2a accepted; full M3-a is the Mini build, unpolluted).
- `lancedb` is added as a project dependency (`uv add lancedb`). LanceDB's Python API: `lancedb.connect(str(path))` → `db`; `db.create_table(name, data=rows)` infers a `FixedSizeList(float32, dim)` vector column from the first row's vector length; `db.table_names()` / `db.open_table(name)`; `table.add(rows)`; `table.schema` is a PyArrow schema (the `vector` field's `.type.list_size` gives the stored dimension); dense search `table.search(list(vec)).metric("cosine").where(sql, prefilter=True).limit(k).to_list()` (rows carry `_distance`); native FTS `table.create_fts_index("text", use_tantivy=False)` then `table.search(text, query_type="fts").where(sql, prefilter=True).limit(k).to_list()` (rows carry `_score`). → impact: Caution (confirm the FTS-result score key + `use_tantivy=False` availability against the installed lancedb version at build).
- **(E) Windows-safe FTS fallback:** if native FTS (`use_tantivy=False`) is unavailable on the installed lancedb version, OMIT `create_fts_index` and have `search_text` return `[]` with a logged warning. Do NOT fall back to `use_tantivy=True` — that requires a separately-installed tantivy binary not confirmed on this Windows host. The dense `search` path + the dimension-lock are the load-bearing acceptance criteria; FTS is best-effort. → impact: Caution.
- **(D) Cosine score = cosine similarity ∈ [−1, 1].** `score = 1.0 - _distance` where LanceDB cosine `_distance = 1 - cosine_similarity`, so the returned score IS the cosine similarity — identical vector ≈ 1.0, orthogonal ≈ 0.0, opposite ≈ −1.0. This matches the existing `InMemoryToolIndex` convention (which returns the normalised dot product, also [−1, 1]); do **not** clamp (clamping would diverge from the in-memory store and lose ordering). A metric-contract test pins the actual LanceDB range at build. → impact: Stop (verify the metric contract — do not assume; the test below asserts the three reference angles).
- **(C) Dimension-lock enforced on write AND re-open.** `add` raises a typed `DimensionMismatchError(ValueError)` if any vector length ≠ the constructor `dimension`. On re-open of an existing table, the constructor reads back the `FixedSizeList` width from `table.schema` and raises `DimensionMismatchError` if it ≠ the constructor `dimension` (prevents silent schema drift). → impact: Stop (dimension-lock is an ADR-007/brain.md invariant; M3-a Task 5 requires the re-open guard).
- **(B) Scope is validated before interpolation.** `Scope` is `str` and the search filter interpolates it into a LanceDB SQL `where` clause; every public method validates `re.fullmatch(r"[\w-]+", scope)` and raises `ValueError` on a non-conforming scope (the scope column is the ONLY isolation wall in this reduction, so a broken/injected filter is a data-isolation failure). → impact: Stop.
- `pytest` runs from repo root with `asyncio_mode=auto`; LanceDB writes under `tmp_path` so tests are isolated. Fully off-hardware (no model, no network, no encrypted volume). → impact: Low.

## Files to change
1. **create** `src/artemis/knowledge/__init__.py` — package init exporting `LanceDBVectorStore`, `DimensionMismatchError`.
2. **create** `src/artemis/knowledge/vector_store.py` — the store.
3. **create** `tests/test_vector_store.py` — deterministic-vector golden tests.

## Exact changes

### 1. `src/artemis/knowledge/__init__.py` (new)
```python
"""Knowledge subsystem (M3) — document storage + retrieval.

Slice 3a ships a TEST-ONLY LanceDB ``VectorStore`` round-trip; full M3-a
replaces this module with the ingestion-backed production store.
"""

from __future__ import annotations

from artemis.knowledge.vector_store import DimensionMismatchError, LanceDBVectorStore

__all__ = ["DimensionMismatchError", "LanceDBVectorStore"]
```

### 2. `src/artemis/knowledge/vector_store.py` (new)
```python
"""LanceDB-backed ``VectorStore`` — reduced TEST-ONLY slice (plain dir, scope column).

Implements the M0-d ``VectorStore`` port: dense cosine KNN (``search``) +
an FTS/BM25 path (``search_text``), with a hard dimension-lock enforced on
write and on re-open. NOT forward-compatible with M3-a's on-disk schema —
full M3-a replaces this module (see the spec Assumptions). Never create this
store at a path M3-a will later open.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from artemis.ports.types import Chunk, RetrievedChunk, Scope, Vector

logger = logging.getLogger(__name__)

_SCOPE_RE = re.compile(r"[\w-]+")


class DimensionMismatchError(ValueError):
    """Raised when a vector's length (or a reopened table's width) != the store dimension."""


def _validate_scope(scope: str) -> None:
    """Reject a scope that is not a safe identifier (it is interpolated into SQL)."""
    if not _SCOPE_RE.fullmatch(scope):
        raise ValueError(f"Invalid scope (must match [\\w-]+): {scope!r}")


class LanceDBVectorStore:
    """LanceDB ``VectorStore`` (dense KNN + FTS) — structurally satisfies the port.

    .. code:: python

        store: VectorStore = LanceDBVectorStore(path, dimension=1024)  # type-checks
    """

    def __init__(
        self, db_path: Path, *, dimension: int, table_name: str = "chunks"
    ) -> None:
        import lancedb

        self._dimension = dimension
        self._table_name = table_name
        self._db = lancedb.connect(str(db_path))
        self._table: Any | None = None
        self._fts_ok = True
        if table_name in self._db.table_names():
            self._table = self._db.open_table(table_name)
            self._assert_table_dimension()

    def _assert_table_dimension(self) -> None:
        """Re-open guard: stored FixedSizeList width must match the store dimension."""
        assert self._table is not None
        field = self._table.schema.field("vector")
        stored_dim = getattr(field.type, "list_size", None)
        if stored_dim is not None and stored_dim != self._dimension:
            raise DimensionMismatchError(
                f"Table dimension {stored_dim} != store dimension {self._dimension}"
            )

    def _build_fts_index(self) -> None:
        """Build/refresh the native FTS index; degrade gracefully if unavailable."""
        assert self._table is not None
        try:
            self._table.create_fts_index("text", use_tantivy=False, replace=True)
        except (TypeError, ValueError, NotImplementedError) as exc:
            self._fts_ok = False
            logger.warning("LanceDB native FTS unavailable; search_text disabled: %s", exc)

    def add(
        self,
        scope: Scope,
        ids: Sequence[str],
        vectors: Sequence[Vector],
        metadata: Sequence[Mapping[str, object]],
    ) -> None:
        """Store vectors under a scope. Raises on a length, dimension, or scope error."""
        _validate_scope(scope)
        if len(ids) != len(vectors) or len(vectors) != len(metadata):
            raise ValueError(
                f"Mismatched lengths: ids={len(ids)}, vectors={len(vectors)}, "
                f"metadata={len(metadata)}"
            )
        for vec in vectors:
            if len(vec) != self._dimension:
                raise DimensionMismatchError(
                    f"Vector length {len(vec)} != store dimension {self._dimension}"
                )

        rows = [
            {
                "id": entry_id,
                "vector": list(vec),
                "scope": scope,
                "text": str(meta.get("text", "")),
                "document_id": str(meta.get("document_id", "")),
            }
            for entry_id, vec, meta in zip(ids, vectors, metadata)
        ]

        if self._table is None:
            self._table = self._db.create_table(self._table_name, data=rows)
        else:
            self._table.add(rows)
        # Native FTS is a static snapshot — rebuild after every write so newly
        # added rows are searchable (M3-a uses incremental optimize at scale).
        self._build_fts_index()

    def search(self, scope: Scope, query: Vector, k: int) -> list[RetrievedChunk]:
        """Dense cosine KNN within a scope (the ``VectorStore`` port method)."""
        _validate_scope(scope)
        if self._table is None:
            return []
        rows = (
            self._table.search(list(query))
            .metric("cosine")
            .where(f"scope = '{scope}'", prefilter=True)
            .limit(k)
            .to_list()
        )
        # score = cosine similarity ∈ [-1, 1] (LanceDB cosine _distance = 1 - sim).
        return [self._to_chunk(r, score=1.0 - float(r["_distance"])) for r in rows]

    def search_text(self, scope: Scope, query_text: str, k: int) -> list[RetrievedChunk]:
        """FTS/BM25 search within a scope (returns [] if native FTS is unavailable)."""
        _validate_scope(scope)
        if self._table is None or not self._fts_ok:
            return []
        rows = (
            self._table.search(query_text, query_type="fts")
            .where(f"scope = '{scope}'", prefilter=True)
            .limit(k)
            .to_list()
        )
        return [self._to_chunk(r, score=float(r.get("_score", 0.0))) for r in rows]

    @staticmethod
    def _to_chunk(row: Mapping[str, object], score: float) -> RetrievedChunk:
        return RetrievedChunk(
            chunk=Chunk(
                chunk_id=str(row["id"]),
                document_id=str(row.get("document_id", "")),
                text=str(row.get("text", "")),
                scope=str(row.get("scope", "")),
            ),
            score=score,
        )
```

### 3. `tests/test_vector_store.py` (new)
```python
"""Golden round-trip tests for the LanceDB VectorStore (deterministic vectors)."""

from __future__ import annotations

import math

import pytest

from artemis.knowledge import DimensionMismatchError, LanceDBVectorStore

_DIM = 8


def _unit(values: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in values)) or 1.0
    return [x / norm for x in values]


def _store(tmp_path, dim: int = _DIM) -> LanceDBVectorStore:
    return LanceDBVectorStore(tmp_path / "kb", dimension=dim)


def test_dense_round_trip(tmp_path) -> None:
    store = _store(tmp_path)
    texts = ["alpha doc", "beta doc", "gamma doc"]
    vecs = [_unit([1, 0, 0, 0, 0, 0, 0, 0]), _unit([0, 1, 0, 0, 0, 0, 0, 0]),
            _unit([0, 0, 1, 0, 0, 0, 0, 0])]
    store.add("owner-private", ["c0", "c1", "c2"], vecs,
              [{"text": t, "document_id": "d1"} for t in texts])
    results = store.search("owner-private", vecs[0], k=3)
    assert results[0].chunk.text == "alpha doc"  # identical vector ranks top
    assert results[0].score == pytest.approx(1.0, abs=1e-4)


def test_cosine_metric_contract(tmp_path) -> None:
    """Pin the distance->score contract: identical~1, orthogonal~0, opposite~-1."""
    store = _store(tmp_path)
    base = _unit([1, 0, 0, 0, 0, 0, 0, 0])
    opposite = [-x for x in base]
    orthogonal = _unit([0, 1, 0, 0, 0, 0, 0, 0])
    store.add("owner-private", ["same", "opp", "orth"], [base, opposite, orthogonal],
              [{"text": "same"}, {"text": "opp"}, {"text": "orth"}])
    by_id = {r.chunk.chunk_id: r.score for r in store.search("owner-private", base, k=3)}
    assert by_id["same"] == pytest.approx(1.0, abs=1e-3)
    assert by_id["orth"] == pytest.approx(0.0, abs=1e-3)
    assert by_id["opp"] == pytest.approx(-1.0, abs=1e-3)


def test_fts_round_trip(tmp_path) -> None:
    store = _store(tmp_path)
    store.add("owner-private", ["c0", "c1"],
              [_unit([1, 0, 0, 0, 0, 0, 0, 0]), _unit([0, 1, 0, 0, 0, 0, 0, 0])],
              [{"text": "the quarterly revenue report"}, {"text": "a recipe for sourdough bread"}])
    results = store.search_text("owner-private", "sourdough", k=5)
    if not store._fts_ok:  # native FTS unavailable on this host — acceptable
        pytest.skip("native FTS unavailable")
    assert [r.chunk.text for r in results] == ["a recipe for sourdough bread"]


def test_fts_incremental_add_is_searchable(tmp_path) -> None:
    """Rows added in a SECOND add() must be findable via FTS (index refreshed)."""
    store = _store(tmp_path)
    store.add("owner-private", ["c0"], [_unit([1, 0, 0, 0, 0, 0, 0, 0])],
              [{"text": "first batch about turbines"}])
    store.add("owner-private", ["c1"], [_unit([0, 1, 0, 0, 0, 0, 0, 0])],
              [{"text": "second batch about dolphins"}])
    if not store._fts_ok:
        pytest.skip("native FTS unavailable")
    results = store.search_text("owner-private", "dolphins", k=5)
    assert [r.chunk.chunk_id for r in results] == ["c1"]


def test_scope_isolation_dense_and_fts(tmp_path) -> None:
    store = _store(tmp_path)
    store.add("owner-private", ["c0"], [_unit([1, 0, 0, 0, 0, 0, 0, 0])],
              [{"text": "private dolphins note"}])
    store.add("general", ["c1"], [_unit([1, 0, 0, 0, 0, 0, 0, 0])],
              [{"text": "general dolphins note"}])
    dense = store.search("owner-private", _unit([1, 0, 0, 0, 0, 0, 0, 0]), k=10)
    assert {r.chunk.chunk_id for r in dense} == {"c0"}
    if store._fts_ok:
        fts = store.search_text("owner-private", "dolphins", k=10)
        assert {r.chunk.chunk_id for r in fts} == {"c0"}  # no cross-scope FTS leak


def test_dimension_lock_on_write(tmp_path) -> None:
    store = _store(tmp_path)
    with pytest.raises(DimensionMismatchError):
        store.add("owner-private", ["c0"], [[0.1, 0.2, 0.3]], [{"text": "wrong dim"}])


def test_dimension_lock_on_reopen(tmp_path) -> None:
    store = _store(tmp_path, dim=8)
    store.add("owner-private", ["c0"], [_unit([1, 0, 0, 0, 0, 0, 0, 0])], [{"text": "x"}])
    with pytest.raises(DimensionMismatchError):
        LanceDBVectorStore(tmp_path / "kb", dimension=4)  # same path, wrong dim


def test_invalid_scope_rejected(tmp_path) -> None:
    store = _store(tmp_path)
    with pytest.raises(ValueError):
        store.search("owner' OR '1'='1", _unit([1, 0, 0, 0, 0, 0, 0, 0]), k=5)


def test_empty_store_returns_nothing(tmp_path) -> None:
    store = _store(tmp_path)
    assert store.search("owner-private", _unit([1, 0, 0, 0, 0, 0, 0, 0]), k=5) == []
    assert store.search_text("owner-private", "anything", k=5) == []
```

## Acceptance criteria
1. Dense + metric-contract + FTS + incremental-FTS + scope-isolation + dimension-lock (write & reopen) + scope-guard round-trip → `uv run pytest tests/test_vector_store.py -q` passes (all tests; FTS-dependent tests `skip` cleanly if native FTS is unavailable on the host).
2. Port conformance → `LanceDBVectorStore` is usable where `artemis.ports.retrieval.VectorStore` is expected; `uv run mypy src` clean confirms structural satisfaction.
3. No regression → `uv run pytest -q` still green (all prior 106 tests pass).
4. Lint/type clean → `uv run mypy src` and `uv run ruff check src tests` report no new errors.

## Commands to run
```bash
uv add lancedb
uv run pytest tests/test_vector_store.py -q
uv run pytest -q
uv run mypy src
uv run ruff check src tests
```
