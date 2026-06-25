---
spec: sens-carry-m3b
status: ready
token_profile: lean
autonomy_level: L2
depends_on: sens-prod-m3a
---
<!-- ADR-029 §2 (carrier). Surfaces the per-source `sensitivity`/`category` tag (written by SENS-prod-M3a
     onto the LanceDB row) up onto `RetrievedChunk` so the RAG-compose enforcer (SENS-enforce-ragcompose)
     can filter sensitive chunks out of the cloud-bound prompt. M3-b's own security FLAG already reserved
     this: "the consumer enforces it; M3-b does not." This is a ~one-line materialization, not new logic. -->

# Spec: SENS-carry-M3b — surface the `sensitivity` tag on `RetrievedChunk`

**Identity:** Materialize the `sensitivity` (and reserved `category`) LanceDB column written by SENS-prod-M3a onto the `Chunk`/`RetrievedChunk` shape that `AdaptiveRetriever.retrieve` returns, so the cloud-boundary enforcer can read each chunk's tag. Carry-only — M3-b still performs NO enforcement.
→ why: see docs/technical/adr/ADR-029-sensitivity-ingestion-gate.md §2 (carrier) · M3-b § Security FLAG ("consumer enforces; M3-b does not").

## Assumptions

- **SENS-prod-M3a** complete: every LanceDB doc row carries a `sensitivity TEXT` column (`"general"`/`"sensitive"`, fail-closed to `"sensitive"`) and a nullable `category TEXT` column, written per-source at ingestion (one classify per document, propagated to all chunks). The columns exist on every row M3-b reads. → impact: Stop (this spec reads those columns; if the column is absent on an old row, default to `"sensitive"` — fail-closed, never `"general"`).
- **M0-d** `Chunk` is the frozen dataclass `Chunk {chunk_id, document_id, text, scope}` and `RetrievedChunk {chunk, score}` in `artemis.ports.types`. This spec adds two fields to `Chunk`: `sensitivity: Sensitivity = "sensitive"` and `category: str | None = None` (fail-closed default). `Sensitivity = Literal["general","sensitive"]` is imported from `artemis.sensitivity` (brain-sensitivity-routing). → impact: Stop (adding a defaulted field to a frozen dataclass is backward-compatible — existing constructors that omit it get the fail-closed default).
- **M3-b** `LanceDBVectorStore._to_chunk` / `hybrid_search` / `search` materialize rows into `RetrievedChunk`s (the slice-3a `_to_chunk(row, score)` helper is the single materialization point). This spec extends that one helper to read the two columns. → impact: Stop (one materialization site; no other change to the hybrid/RRF/rerank path).
- The reranker scores chunk text and does not touch the tag; the tag rides through rerank unchanged (a `RetrievedChunk` reordered by rerank keeps its `chunk.sensitivity`). → impact: Low.
- Off-hardware: seed a temp LanceDB with rows carrying `sensitivity="sensitive"`/`"general"` + assert the tag surfaces on the returned `RetrievedChunk`s. → impact: Low.

Simplicity check: the minimal change is two defaulted fields on `Chunk` + reading two columns in the one `_to_chunk` materialization helper. No new method, no enforcement, no change to the retrieve signature. Defaulting the new fields keeps every existing `Chunk(...)` call site valid.

## Prerequisites

- Specs complete: **SENS-prod-M3a** (writes the LanceDB columns), **M3-b** (`AdaptiveRetriever`/`LanceDBVectorStore` materialization), **brain-sensitivity-routing** (`Sensitivity` literal).
- Environment: no new PyPI deps.

## Files to Change

| File | Operation | Notes |
|------|-----------|-------|
| `/Users/artemis-build/artemis/src/artemis/ports/types.py` | modify | add `sensitivity: Sensitivity = "sensitive"` + `category: str | None = None` to `Chunk` (defaulted, fail-closed) |
| `/Users/artemis-build/artemis/src/artemis/adapters/lancedb_store.py` | modify | `_to_chunk(row, score)` reads `row.get("sensitivity")` (default `"sensitive"`) + `row.get("category")` into the `Chunk` |
| `/Users/artemis-build/artemis/tests/test_retriever.py` | modify | assert the tag surfaces on returned `RetrievedChunk`s (general + sensitive + missing-column-defaults-sensitive) |

All paths under `/Users/artemis-build/artemis/`.

## Tasks

- [ ] **Task 1: Add the tag fields to `Chunk`** — files: `/Users/artemis-build/artemis/src/artemis/ports/types.py` (modify) —

  **NOTE (on-disk reality):** `Chunk` in `artemis.ports.types` is a **plain class with an explicit `__init__`**, NOT a `@dataclass`. Add the two new fields as **defaulted `__init__` parameters** (after the existing `scope` param, so existing positional/keyword call sites stay valid) and assign them to `self`:
  ```python
  def __init__(
      self, chunk_id: str, document_id: str, text: str, scope: Scope,
      sensitivity: "Sensitivity" = "sensitive",   # ADR-029 carrier — fail-closed default; set from the LanceDB row
      category: str | None = None,                # reserved (written by SENS-prod, unconsumed in v1)
  ) -> None:
      ...                                          # existing assignments unchanged
      self.sensitivity = sensitivity
      self.category = category
  ```
  Import `Sensitivity` from `artemis.sensitivity` (a `Literal["general","sensitive"]`). Use a `TYPE_CHECKING` guard only if an import cycle arises; the literal is a runtime-cheap alias so a direct import is fine. The defaults make the params additive — every existing `Chunk(chunk_id=..., document_id=..., text=..., scope=...)` call stays valid and gets `sensitivity="sensitive"` (fail-closed). (Do NOT convert `Chunk` to a dataclass — keep the existing class style; this is a surgical two-param add.)

  — done when: `uv run mypy --strict src` passes; `Chunk(chunk_id="c", document_id="d", text="t", scope="owner-private").sensitivity == "sensitive"`; `Chunk(..., sensitivity="general").sensitivity == "general"`.

- [ ] **Task 2: Read the columns in materialization** — files: `/Users/artemis-build/artemis/src/artemis/adapters/lancedb_store.py` (modify) —

  In the single `_to_chunk(row, score) -> RetrievedChunk` helper (slice-3a), read the two columns:
  ```python
  raw_sens = row.get("sensitivity")
  sensitivity: Sensitivity = "general" if raw_sens == "general" else "sensitive"   # fail-closed: anything not "general" → sensitive
  category = row.get("category")  # str | None
  return RetrievedChunk(
      chunk=Chunk(chunk_id=..., document_id=..., text=..., scope=..., sensitivity=sensitivity, category=category),
      score=score,
  )
  ```
  This is the ONLY materialization site (both `hybrid_search` and `search` route through `_to_chunk`). No change to RRF/rerank/retrieve flow — the tag rides on the returned chunks.

  — done when: `uv run mypy --strict src` passes; a row with `sensitivity="general"` → returned `RetrievedChunk.chunk.sensitivity == "general"`; a row with `sensitivity="sensitive"` or a row missing the column → `"sensitive"` (fail-closed).

- [ ] **Task 3: Tests** — files: `/Users/artemis-build/artemis/tests/test_retriever.py` (modify) — add to the existing async retriever tests:

  - Seed a temp LanceDB with three rows: one `sensitivity="general"`, one `sensitivity="sensitive"`, one with NO `sensitivity` column written. `await retrieve("query", scope, k=3)` → the returned `RetrievedChunk`s carry `chunk.sensitivity` matching the row, and the column-less row defaults to `"sensitive"` (fail-closed).
  - Assert `chunk.category` round-trips (a row with `category="health"` → `chunk.category == "health"`; a row with NULL category → `None`).
  - Regression: the existing RRF/rerank/mode-seam tests still pass (the tag does not alter ordering).

  — done when: `uv run pytest -q tests/test_retriever.py` passes AND `uv run mypy --strict src tests/test_retriever.py` passes.

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Modify | `/Users/artemis-build/artemis/src/artemis/ports/types.py` |
| Modify | `/Users/artemis-build/artemis/src/artemis/adapters/lancedb_store.py` |
| Modify | `/Users/artemis-build/artemis/tests/test_retriever.py` |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict src tests/test_retriever.py` | Type gate |
| `uv run ruff check . && uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q tests/test_retriever.py` | Test gate |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | `src/artemis/ports/types.py`, `src/artemis/adapters/lancedb_store.py`, `tests/test_retriever.py` |
| `git commit` | `"feat: ADR-029 carrier — surface sensitivity tag on RetrievedChunk (M3-b)"` |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_DATA_ROOT` | temp LanceDB path (`vault_dir`) for tests |

### Network
| Action | Purpose |
|--------|---------|
| (none) | Pure column-read + dataclass field |

## Specialist Context

### Security

- **Fail-closed at the carrier too:** any row whose `sensitivity` value is not exactly `"general"` (including a missing/NULL column from a pre-ADR-029 row) materializes as `"sensitive"`. There is no path where an untagged chunk surfaces as `"general"` — the enforcer (SENS-enforce-ragcompose) therefore never sees a sensitive item mislabelled general due to a missing tag.
- M3-b still does NOT enforce — it carries the tag for the consumer (the RAG-compose enforcer), exactly as M3-b's existing security FLAG reserved. No chunk reaches a model in this spec.

### Performance

- Two extra column reads per materialized row — negligible. No change to the hybrid/RRF/rerank cost.

### Accessibility

(none — no frontend)

## Documentation

| Doc type | File | Action |
|----------|------|--------|
| Inline | `src/artemis/ports/types.py` | Document the two carrier fields on `Chunk` (fail-closed default; written by SENS-prod-M3a; read by the enforcer) |

## Acceptance Criteria

- [ ] `uv run mypy --strict src tests/test_retriever.py` → verify: exit 0.
- [ ] `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.
- [ ] `uv run pytest -q tests/test_retriever.py` → verify: tag surfaces on `RetrievedChunk` for general/sensitive rows; missing column defaults to `"sensitive"`; `category` round-trips; existing retriever tests still green.
- [ ] `uv run python -c "from artemis.ports.types import Chunk; print(Chunk(chunk_id='c', document_id='d', text='t', scope='owner-private').sensitivity)"` → verify: prints `sensitive`.

## Progress
_(Coding mode writes here — do not edit manually)_
