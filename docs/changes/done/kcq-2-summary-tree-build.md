---
status: ready
coder_effort: medium
cross_model_review: false
---
# kcq-2-summary-tree-build

**Identity:** RAPTOR-style background pass that builds summary-tree nodes for a document over the reserved `ChunkRecord` fields, behind a fake-testable `Summariser` seam. Wave KCQ spec **2 of 6** (kcq-3 whole-doc route reads these summary nodes). Design: `docs/findings/query-shape-retrieval-design-2026-06-29.md` (D2 build-time RAPTOR summary tree, D4 background build).

## Files to change

| # | Path | Op | What |
|---|---|---|---|
| 1 | `src/artemis/ingest/summary_tree.py` | create | `Summariser` protocol + `ModelSummariser` adapter + `LeafSummaryStore` protocol + `build_summary_tree` + `make_summary_build_step`. |
| 2 | `tests/test_summary_tree.py` | create | Fake summariser/embedder/store; builds correct nodes; idempotent re-run. |
| 3 | `src/artemis/gateway.py` | modify | In `compose_brain`'s memory try-block (where `store_for`, `embedder`, `model`, `OWNER_PRIVATE`/`GENERAL` are in scope — alongside the `AdaptiveRetriever` build, ~line 426), construct `summary_build_step = make_summary_build_step(store_for=store_for, scopes=[OWNER_PRIVATE, GENERAL], embedder=embedder, summariser=ModelSummariser(model), is_unlocked=key_provider.is_owner_unlocked, logger=logger)` and attach it to the returned `Brain` as `brain.summary_build_step` (additive attribute, default `None` when memory is unavailable / the except-branch runs). |
| 4 | `src/artemis/main.py` | modify | At the `compose_proactive(...)` call (~line 118), pass `pre_tick_steps=[s for s in [getattr(brain, "summary_build_step", None)] if s is not None]`. |

Ingest (`chunking.py`, `pipeline.py`) is **UNCHANGED** — still writes level-0 leaves only. `compose_proactive`/`proactive/__init__.py` are **unedited** — they already forward `pre_tick_steps`.

> **BUILD-ORDER NB:** File 3 edits the same `compose_brain` memory-block that **kcq-3** rewrites (the `retrieve_fn` region). kcq-2 and kcq-3 both touch `gateway.py compose_brain` → **build serially, kcq-2 before kcq-3** (kcq-3 already depends on kcq-2 for the summary nodes). The build step is constructed where the knowledge `store_for` + `embedder` + `model` live (only inside `compose_brain`); `main.py` cannot build it directly because `store_for` is not exposed there.

## Exact changes

### File 1 — `src/artemis/ingest/summary_tree.py` (new)

Grounded imports (real symbols):
```python
"""RAPTOR-style background summary-tree build over reserved ChunkRecord fields.

Ingest writes level-0 leaves only (chunking.chunk_document). This module is the
D4 background pass: it finds documents that have leaves but no current summary
nodes and writes higher-level summary ChunkRecords (is_summary=True, node_level>0,
parent_chunk_id set). Embedded + stored through the same VectorStore.add path as
leaves. Designed to run as a pre_tick_step via compose_proactive(pre_tick_steps=...).
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Protocol, runtime_checkable

from artemis.ingest.chunking import ChunkRecord
from artemis.ports.model import ModelPort
from artemis.ports.retrieval import EmbeddingModel
from artemis.ports.types import Message, Scope, Vector
from artemis.sensitivity import Sensitivity

DEFAULT_GROUP_SIZE = 8
_LOG = logging.getLogger(__name__)
```

**Summariser seam** (narrow, co-located — single consumer; not added to `ports/`):
```python
@runtime_checkable
class Summariser(Protocol):
    """Faithful-summary seam over a set of passages (network I/O → async)."""

    async def summarise(self, texts: Sequence[str]) -> str:
        ...


class ModelSummariser:
    """Concrete Summariser wrapping the swappable ModelPort (fake in tests)."""

    def __init__(self, model: ModelPort, *, role: str = "summary", max_tokens: int = 512) -> None:
        self._model = model
        self._role = role
        self._max_tokens = max_tokens

    async def summarise(self, texts: Sequence[str]) -> str:
        body = "\n\n---\n\n".join(texts)
        prompt = (
            "Summarise the following passages faithfully and concisely. "
            "Preserve concrete facts; do not invent.\n\n" + body
        )
        resp = await self._model.complete(
            role=self._role,
            messages=[Message("user", prompt)],
            temperature=0.2,
            max_tokens=self._max_tokens,
        )
        return resp.text.strip()
```

**Store seam** (structural — `LanceDBVectorStore` already satisfies both `rows()` and `add()`):
```python
@runtime_checkable
class LeafSummaryStore(Protocol):
    def rows(self) -> list[Mapping[str, object]]:
        """All stored rows for this scope (LanceDBVectorStore.rows shape)."""
        ...

    def add(
        self,
        scope: Scope,
        ids: Sequence[str],
        vectors: Sequence[Vector],
        metadata: Sequence[Mapping[str, object]],
    ) -> None:
        ...
```

**Build function** — deterministic sequential grouping (no embedding-cluster model in v1):
```python
async def build_summary_tree(
    *,
    store: LeafSummaryStore,
    scope: Scope,
    embedder: EmbeddingModel,
    summariser: Summariser,
    group_size: int = DEFAULT_GROUP_SIZE,
) -> int:
    """Build summary nodes for every document in this scope with leaves but no
    current summary. Returns the count of summary nodes written.

    Idempotent: a document whose leaves already have matching (same content_hash)
    summary rows is skipped; summary chunk_ids are content-independent so a rebuild
    upserts in place. Staleness across content changes is handled upstream by
    re-ingest (delete_document wipes leaves AND summaries, then this pass rebuilds).
    """
    rows = list(store.rows())
    by_doc: dict[str, list[Mapping[str, object]]] = {}
    for row in rows:
        by_doc.setdefault(str(row.get("document_id", "")), []).append(row)

    new_records: list[ChunkRecord] = []
    for document_id, doc_rows in by_doc.items():
        if not document_id:
            continue
        leaves = [r for r in doc_rows if not bool(r.get("is_summary", False))]
        if not leaves:
            continue
        content_hash = str(leaves[0].get("content_hash", ""))
        already = any(
            bool(r.get("is_summary", False)) and str(r.get("content_hash", "")) == content_hash
            for r in doc_rows
        )
        if already:
            continue
        leaves.sort(key=_leaf_ordinal)
        new_records.extend(_summary_records_for(document_id, leaves, summariser, group_size))

    if not new_records:
        return 0

    vectors = await embedder.embed_documents([rec.text for rec in new_records])
    store.add(
        scope,
        ids=[rec.chunk_id for rec in new_records],
        vectors=vectors,
        metadata=[_summary_metadata(rec) for rec in new_records],
    )
    return len(new_records)
```

Helpers (signatures + behaviour):
```python
def _leaf_ordinal(row: Mapping[str, object]) -> int:
    cid = str(row.get("id", ""))
    tail = cid.rsplit(":", 1)[-1]
    return int(tail) if tail.isdigit() else 0


async def _summary_records_for(
    document_id: str,
    leaves: list[Mapping[str, object]],
    summariser: Summariser,
    group_size: int,
) -> list[ChunkRecord]:
    # NOTE: make build_summary_tree await this; declared async because it calls summariser.
    ...
```
Implement `_summary_records_for` inline within `build_summary_tree` (or as an async helper — the coder may inline to keep one await site). Logic:
- Partition `leaves` into consecutive groups of `group_size`.
- For each group `g` (ordinal `i`): `text = await summariser.summarise([str(r.get("text","")) for r in g])`; build a **level-1** `ChunkRecord` via `_make_summary_record(document_id, level=1, ordinal=i, text=text, leaf_rows=g, parent_chunk_id=<root id or None>)`.
- If exactly one level-1 node → it is the root: `parent_chunk_id=None`.
- If more than one level-1 node → build a single **level-2** root: `root_text = await summariser.summarise([n.text for n in level1])`; `root` chunk_id `{document_id}:summary:2:0`, `parent_chunk_id=None`; set each level-1 node's `parent_chunk_id` to the root id.
- Return root + level-1 nodes (or the single level-1 node).

```python
def _make_summary_record(
    document_id: str,
    *,
    level: int,
    ordinal: int,
    text: str,
    leaf_rows: Sequence[Mapping[str, object]],
    parent_chunk_id: str | None,
) -> ChunkRecord:
    first = leaf_rows[0]
    return ChunkRecord(
        chunk_id=f"{document_id}:summary:{level}:{ordinal}",
        document_id=document_id,
        text=text,
        scope=str(first.get("scope", "")),
        content_hash=str(first.get("content_hash", "")),
        source_id=str(first.get("source_id", "")),
        page=None,
        bbox=None,
        char_start=min(int(r.get("char_start", 0) or 0) for r in leaf_rows),
        char_end=max(int(r.get("char_end", 0) or 0) for r in leaf_rows),
        node_level=level,
        is_summary=True,
        parent_chunk_id=parent_chunk_id,
        sensitivity=_sensitivity(first.get("sensitivity")),
        category=_opt_str(first.get("category")),
    )
```
For the level-2 root, pass `leaf_rows` = the union of all leaves so char span / inherited fields cover the whole doc.

Metadata mirror of `pipeline._metadata_for` (same keys the LanceDB schema expects — do not import the private fn):
```python
def _summary_metadata(rec: ChunkRecord) -> Mapping[str, object]:
    return {
        "text": rec.text, "scope": rec.scope, "content_hash": rec.content_hash,
        "source_id": rec.source_id, "document_id": rec.document_id,
        "page": rec.page, "bbox": rec.bbox,
        "char_start": rec.char_start, "char_end": rec.char_end,
        "node_level": rec.node_level, "is_summary": rec.is_summary,
        "parent_chunk_id": rec.parent_chunk_id,
        "sensitivity": rec.sensitivity, "category": rec.category,
    }


def _sensitivity(value: object) -> Sensitivity:
    return "general" if value == "general" else "sensitive"


def _opt_str(value: object) -> str | None:
    return None if value is None else str(value)
```

**Background step factory** (returns the `Callable[[], Awaitable[None]]` that `pre_tick_steps` expects):
```python
def make_summary_build_step(
    *,
    store_for: Callable[[Scope], LeafSummaryStore],
    scopes: Sequence[Scope],
    embedder: EmbeddingModel,
    summariser: Summariser,
    is_unlocked: Callable[[], bool],
    group_size: int = DEFAULT_GROUP_SIZE,
    logger: logging.Logger | None = None,
) -> Callable[[], Awaitable[None]]:
    """Build a no-arg async step for compose_proactive(pre_tick_steps=[...])."""
    log = logger or _LOG

    async def _step() -> None:
        if not is_unlocked():
            return
        for scope in scopes:
            try:
                await build_summary_tree(
                    store=store_for(scope), scope=scope,
                    embedder=embedder, summariser=summariser, group_size=group_size,
                )
            except Exception:
                log.exception("summary-tree build failed for scope=%s", scope)

    return _step
```

### Files 3 & 4 — wiring the step into the live heartbeat
`compose_proactive` already accepts `pre_tick_steps: list[Callable[[], Awaitable[None]]] | None` and forwards it through `attach_to_heartbeat` — so `proactive/__init__.py` needs **no** change. The step must actually be constructed and passed in, or the summary tree never builds in production (and kcq-3's whole-doc route always falls back to pinpoint).

**File 3 — `src/artemis/gateway.py` (`compose_brain`).** Inside the memory try-block where `store_for`, `embedder`, `model`, `OWNER_PRIVATE`/`GENERAL` are in scope (alongside the `AdaptiveRetriever(...)` construction, ~line 426), add:
```python
summary_build_step = make_summary_build_step(
    store_for=store_for,
    scopes=[OWNER_PRIVATE, GENERAL],
    embedder=embedder,
    summariser=ModelSummariser(model),
    is_unlocked=key_provider.is_owner_unlocked,
    logger=logger,
)
```
Attach it to the `Brain` returned at the end of `compose_brain` as an additive `summary_build_step` attribute. When the memory block fails (the `except` branch) or memory is unavailable, leave it `None`. Import `make_summary_build_step` + `ModelSummariser` from `artemis.ingest.summary_tree`. (`key_provider` is already a `compose_brain` parameter.)

**File 4 — `src/artemis/main.py` (~line 118).** Change the `compose_proactive(...)` call to pass:
```python
pre_tick_steps=[s for s in [getattr(brain, "summary_build_step", None)] if s is not None],
```
Keep all existing positional args unchanged.

### File 2 — `tests/test_summary_tree.py` (new)
Fakes:
- `FakeSummariser.summarise(texts)` → `f"SUM[{len(texts)}]:" + " | ".join(t[:8] for t in texts)`; record call count.
- `FakeEmbedder.embed_documents(texts)` → `[[float(len(t)), 0.0, 1.0] for t in texts]`; `embed_query`/`dimension` per `EmbeddingModel`.
- `InMemoryLeafStore`: `add()` upserts by `id` into a dict keyed on chunk id (delete-then-set), storing `{**metadata, "id": chunk_id}`; `rows()` returns `list(self._rows.values())`. Seed leaves with a helper that writes rows shaped like LanceDB output (`id`, `text`, `document_id`, `content_hash`, `scope`, `is_summary=False`, `node_level=0`, `char_start`, `char_end`, `source_id`, `sensitivity`, `category`).

Tests (async, `@pytest.mark.asyncio` if used elsewhere — match repo convention; else `asyncio.run`):
1. `test_builds_two_level_tree`: seed 6 leaves (`doc1:0..doc1:5`, same content_hash), `group_size=3`. Run `build_summary_tree` → returns 3. Assert summary rows: two `node_level==1, is_summary=True, parent_chunk_id == "doc1:summary:2:0"` with ids `doc1:summary:1:0/1`; one root `id=="doc1:summary:2:0", node_level==2, parent_chunk_id is None`. Assert `FakeSummariser` was called.
2. `test_single_group_single_root`: seed 2 leaves, `group_size=5` → returns 1; the one node is `id=="doc1:summary:1:0", node_level==1, parent_chunk_id is None`.
3. `test_idempotent_rerun`: run build twice on the same store/content_hash. Second call returns `0`; total `is_summary` row count unchanged; summary ids identical (no duplicates).
4. `test_step_skips_when_locked`: `make_summary_build_step(..., is_unlocked=lambda: False)` → awaiting the step writes nothing (store unchanged).

## Acceptance criteria
1. `src/artemis/ingest/summary_tree.py` exposes `Summariser`, `ModelSummariser`, `LeafSummaryStore`, `build_summary_tree`, `make_summary_build_step` → `uv run pytest tests/test_summary_tree.py -q` passes.
2. 6 leaves + `group_size=3` produce exactly 3 summary nodes with reserved fields set (`is_summary=True`, `node_level` 1/1/2, level-1 `parent_chunk_id` = root id, root `parent_chunk_id=None`), ids `{doc}:summary:{level}:{ordinal}` → verify in `test_builds_two_level_tree`.
3. Re-running on unchanged content writes 0 new nodes and creates no duplicate summary rows → verify in `test_idempotent_rerun`.
4. `make_summary_build_step(...)` returns a `Callable[[], Awaitable[None]]` that is a no-op when locked → verify in `test_step_skips_when_locked`.
5. The build step is wired live: `compose_brain` constructs it and attaches `brain.summary_build_step`; `main.py` passes it into `compose_proactive(pre_tick_steps=...)` → verify by reading the diff (the heartbeat now runs the step) and `uv run pytest tests/test_main*.py -q` (or the brain-composition test) stays green.
6. Ingest unchanged; `proactive/__init__.py` unedited → `uv run mypy` clean and `uv run pytest -q` green.

## Commands to run
```
uv run pytest tests/test_summary_tree.py -q
uv run mypy
uv run pytest -q
```
