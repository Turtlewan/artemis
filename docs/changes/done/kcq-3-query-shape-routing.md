---
status: ready
coder_effort: medium
cross_model_review: true
---
# kcq-3-query-shape-routing

**Identity:** Wire the kcq-1 shape classifier into the retrieval entry and implement the WHOLE_DOC (retrieve-then-read summary node) and AGGREGATE (honest-decline + domain hint) routes behind the existing `retrieve_fn` seam. Design: `docs/findings/query-shape-retrieval-design-2026-06-29.md`. Wave KCQ spec **3 of 6**. **DEPENDS ON kcq-1 (shape classifier) + kcq-2 (summary-tree build) — build after both.**

## Dependency contract (provided by kcq-1 / kcq-2 — do not build here)
- **kcq-1** exposes:
  - `class QueryShape(StrEnum)` with members `PINPOINT`, `WHOLE_DOC`, `AGGREGATE` — defined in **`src/artemis/ports/types.py`** (co-located with `Mode`); import it from there.
  - `def classify_query_shape(query: str, *, fallback=None) -> QueryShape` in **`src/artemis/retrieval/shape.py`** (deterministic gate + LLM fallback seam).
  - NOTE: a different `classify_shape` already exists in `artemis.speakable` (imported by `gateway.py` line 27). Use the **`classify_query_shape`** name from the retrieval module — do not shadow the speakable one.
- **kcq-2** has written summary nodes into the LanceDB tables: rows with `is_summary == True`, `node_level > 0`, `parent_chunk_id` set. Read them through the **existing** `LanceDBVectorStore.rows()` accessor (no new store method).

## Files to change
1. **create** `src/artemis/retrieval/shape_router.py` — the `ShapeRouter`, the AGGREGATE decline-chunk builder, the domain-hint map, and the injected dependency type aliases.
2. **modify** `src/artemis/gateway.py` — replace the `retrieve_fn` body inside `compose_brain` (lines ~433-447): keep the existing dual-scope merge as `_pinpoint_retrieve`, add a `_summary_lookup` closure over `stores`, construct a `ShapeRouter`, and set `retrieve_fn = router.route`.
3. **create** `tests/test_shape_router.py` — per-shape dispatch against fakes.

## Exact changes

### 1. `src/artemis/retrieval/shape_router.py` (new)

```python
"""Query-shape routing in front of retrieval.

Design: docs/findings/query-shape-retrieval-design-2026-06-29.md
PINPOINT -> existing hybrid retrieve (unchanged).
WHOLE_DOC -> retrieve-then-read: top document_id from a normal retrieve, then that
doc's summary node(s); fall back to pinpoint when no summary node exists yet.
AGGREGATE -> honest-decline sentinel chunk (+ a domain-tool routing hint).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Final

from artemis.identity.scope import GENERAL
from artemis.ports.types import Chunk, RetrievedChunk, Scope
from artemis.ports.types import QueryShape  # kcq-1 (enum lives in ports/types.py)

ShapeClassifier = Callable[[str], QueryShape]
PinpointRetrieve = Callable[[str], Awaitable[list[RetrievedChunk]]]
SummaryLookup = Callable[[str], Awaitable[list[RetrievedChunk]]]

AGGREGATE_DECLINE_CHUNK_ID: Final = "__artemis_aggregate_decline__"

# Minimal keyword -> domain routing hint (a hint, not a tool-selection engine).
_DOMAIN_HINTS: Final[tuple[tuple[tuple[str, ...], str], ...]] = (
    (("spend", "spent", "budget", "expense", "cost", "income", "ledger"), "Finance"),
    (("meeting", "calendar", "schedule", "appointment", "event"), "Calendar"),
    (("task", "todo", "to-do", "deadline", "due"), "Tasks"),
)


def _domain_hint(query: str) -> str | None:
    low = query.lower()
    for keywords, domain in _DOMAIN_HINTS:
        if any(k in low for k in keywords):
            return domain
    return None


def build_decline_chunk(query: str, scope: Scope = GENERAL) -> RetrievedChunk:
    """Sentinel RetrievedChunk the brain renders as an honest aggregate decline."""
    notice = (
        "I can't reliably aggregate or total free-text documents -- "
        "sums, averages, and counts over notes are not trustworthy."
    )
    hint = _domain_hint(query)
    if hint is not None:
        notice += f" This looks like a {hint} question -- prefer the {hint} query tool."
    chunk = Chunk(
        chunk_id=AGGREGATE_DECLINE_CHUNK_ID,
        document_id="",
        text=notice,
        scope=scope,
    )
    return RetrievedChunk(chunk, score=1.0)


class ShapeRouter:
    """Classify a query's shape and dispatch to the matching retrieval strategy."""

    def __init__(
        self,
        classify: ShapeClassifier,
        pinpoint: PinpointRetrieve,
        summary_lookup: SummaryLookup,
    ) -> None:
        self._classify = classify
        self._pinpoint = pinpoint
        self._summary_lookup = summary_lookup

    async def route(self, query: str) -> list[RetrievedChunk]:
        shape = self._classify(query)
        if shape is QueryShape.WHOLE_DOC:
            return await self._whole_doc(query)
        if shape is QueryShape.AGGREGATE:
            return [build_decline_chunk(query)]
        # PINPOINT and any unrecognised shape: existing hybrid retrieve, unchanged.
        return await self._pinpoint(query)

    async def _whole_doc(self, query: str) -> list[RetrievedChunk]:
        results = await self._pinpoint(query)
        if not results:
            return results
        top_doc = results[0].chunk.document_id
        summary = await self._summary_lookup(top_doc)
        return summary if summary else results
```

### 2. `src/artemis/gateway.py` — `compose_brain` retrieve_fn wiring

Add module-level imports near the other `artemis.retrieval` import (top-of-file import block is fine; `Chunk` joins the existing `RetrievedChunk` TYPE_CHECKING/runtime usage — import it for runtime use in the closure):

```python
from artemis.ports.types import Chunk  # runtime use in _summary_lookup
from artemis.retrieval.shape import classify_query_shape  # kcq-1
from artemis.retrieval.shape_router import ShapeRouter
```

Replace the existing `async def retrieve_fn(query: str) -> list[RetrievedChunk]:` block (lines ~433-447) with:

```python
            async def _pinpoint_retrieve(query: str) -> list[RetrievedChunk]:
                owner_chunks, general_chunks = await asyncio.gather(
                    retriever.retrieve(query, OWNER_PRIVATE),
                    retriever.retrieve(query, GENERAL),
                )
                seen: set[str] = set()
                merged: list[RetrievedChunk] = []
                for chunk in owner_chunks + general_chunks:
                    if chunk.chunk.chunk_id in seen:
                        continue
                    seen.add(chunk.chunk.chunk_id)
                    merged.append(chunk)
                return merged

            async def _summary_lookup(document_id: str) -> list[RetrievedChunk]:
                """Highest-level summary node(s) for a document across both scopes."""
                if not document_id:
                    return []
                out: list[RetrievedChunk] = []
                for scope, store in stores.items():
                    rows = [
                        r
                        for r in store.rows()
                        if str(r.get("document_id", "")) == document_id
                        and bool(r.get("is_summary", False))
                    ]
                    if not rows:
                        continue
                    top_level = max(int(r.get("node_level", 0)) for r in rows)
                    for r in rows:
                        if int(r.get("node_level", 0)) != top_level:
                            continue
                        out.append(
                            RetrievedChunk(
                                Chunk(
                                    chunk_id=str(r["id"]),
                                    document_id=document_id,
                                    text=str(r.get("text", "")),
                                    scope=scope,
                                    category=_summary_category(r.get("category")),
                                ),
                                score=1.0,
                            )
                        )
                return out

            _shape_router = ShapeRouter(
                classify=classify_query_shape,
                pinpoint=_pinpoint_retrieve,
                summary_lookup=_summary_lookup,
            )
            retrieve_fn = _shape_router.route
```

Where `_summary_category` is a tiny local helper (or inline) returning `str(v)` when `v` is a non-empty str else `None`; `Chunk.sensitivity` is left at its fail-closed `"sensitive"` default (do not relax). Keep `retrieve_fn` typed compatibly with the existing `Brain(retrieve_fn=...)` call at line ~494 — `ShapeRouter.route` already has signature `(str) -> Awaitable[list[RetrievedChunk]]`.

NOTE: `stores`, `retriever`, `OWNER_PRIVATE`, `GENERAL`, and `asyncio` are all already in scope at this point inside the `try` block — do not re-import or rebuild them.

## Acceptance criteria
1. PINPOINT passthrough → `ShapeRouter` with a fake classify returning `QueryShape.PINPOINT` returns the fake pinpoint result unchanged. **verify:** `uv run pytest tests/test_shape_router.py -q` (test `test_pinpoint_passthrough`).
2. WHOLE_DOC reads summary → fake classify `WHOLE_DOC`, pinpoint returns a chunk with `document_id="docA"`, summary_lookup returns a known summary chunk → router returns the **summary** chunk, not the pinpoint chunk. **verify:** same pytest run (`test_whole_doc_reads_summary`).
3. WHOLE_DOC fallback → summary_lookup returns `[]` → router returns the pinpoint result. **verify:** `test_whole_doc_falls_back_when_no_summary`.
4. WHOLE_DOC empty pinpoint → pinpoint returns `[]` → router returns `[]` (no crash, no summary_lookup needed). **verify:** `test_whole_doc_empty_pinpoint`.
5. AGGREGATE decline → fake classify `AGGREGATE`, finance-keyword query ("what was my total spend") → router returns exactly one chunk with `chunk_id == AGGREGATE_DECLINE_CHUNK_ID`, text contains "can't reliably aggregate" and "Finance". **verify:** `test_aggregate_returns_decline_with_domain_hint`.
6. AGGREGATE no-domain → a non-domain aggregate query returns the decline chunk with no domain-hint sentence. **verify:** `test_aggregate_decline_without_domain_hint`.
7. Whole project green. **verify:** `uv run mypy` and `uv run pytest -q` both pass.

### Test sketch (`tests/test_shape_router.py`)
```python
import pytest

from artemis.ports.types import Chunk, RetrievedChunk
from artemis.ports.types import QueryShape
from artemis.retrieval.shape_router import AGGREGATE_DECLINE_CHUNK_ID, ShapeRouter


def _rc(chunk_id: str, document_id: str = "docA", text: str = "t") -> RetrievedChunk:
    return RetrievedChunk(Chunk(chunk_id=chunk_id, document_id=document_id, text=text, scope="general"), 1.0)


def _router(shape, pinpoint_result, summary_result):
    async def pinpoint(_q):
        return list(pinpoint_result)

    async def summary(_doc):
        return list(summary_result)

    return ShapeRouter(classify=lambda _q: shape, pinpoint=pinpoint, summary_lookup=summary)


@pytest.mark.asyncio
async def test_pinpoint_passthrough():
    r = _router(QueryShape.PINPOINT, [_rc("c1")], [])
    out = await r.route("what did the memo say about X")
    assert [c.chunk.chunk_id for c in out] == ["c1"]
# ... remaining tests per acceptance criteria 2-6 ...
```
(Use the repo's existing async-test convention — match how other `tests/test_*.py` mark coroutine tests, e.g. `anyio`/`asyncio` marker.)

## Commands to run
```
uv run pytest tests/test_shape_router.py -q
uv run mypy
uv run pytest -q
```
