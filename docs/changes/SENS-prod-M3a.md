---
spec: sens-prod-m3a
status: ready
token_profile: balanced
autonomy_level: L2
cross_model_review: true
---
<!-- amended for ADR-029 §1 (producer stage). AMENDS M3-a (ingestion). Per-source on-box sensitivity
     classification stamped onto Document + every ChunkRecord + the LanceDB row. CANONICAL HOME of the
     ingestion-gate sensitivity field contract — SENS-prod-M8b1 and SENS-prod-M4b reference it. -->

# Spec: SENS-prod-M3a — tag ingested documents with `sensitivity` at ingestion (per-source, on-box)

**Identity:** Classify each ingested document **once, on-box, per-source** (not per-chunk) via the existing `SensitivityClassifier`, stamp a `sensitivity: Literal["general","sensitive"]` + a reserved nullable `category: str | None` onto the normalized `Document`, propagate it to **every** `ChunkRecord`, and persist both as columns on the LanceDB row — the PRODUCER half of the ADR-029 privacy wall.
→ why: see docs/technical/adr/ADR-029-sensitivity-ingestion-gate.md §1 (producer / tag-at-ingestion, per-source, fail-closed) · reuses the classifier from docs/changes/brain-sensitivity-routing.md (no second resident model).

<!-- Execution script. AMENDS the frozen M3-a ingestion spec. Per-source classify is load-bearing: per-chunk
     would be N× local-model calls and brutal during the bounded Gmail backfill on the 8 GB dev box (ADR-029
     §1). The tag rides provenance the chunks already carry — surfacing it is nearly free downstream (Wave-P
     carrier specs). This spec ONLY produces the tag; the carrier (SENS-carry-M3b) and the enforcer
     (SENS-enforce-ragcompose) are separate Wave-P specs. -->

## Canonical sensitivity field contract (ADR-029 — referenced by SENS-prod-M8b1 + SENS-prod-M4b)

```python
# from artemis.sensitivity import Sensitivity  (already defined by brain-sensitivity-routing)
Sensitivity = Literal["general", "sensitive"]
```

Every producer (M3-a docs, M8-b1 emails, M4-b facts) stamps the SAME two values onto its produced rows:
- `sensitivity: Sensitivity` — **fail-closed default `"sensitive"`** whenever classification fails / is unavailable.
- `category: str | None = None` — **reserved, written-but-unconsumed in v1** (ADR-029: a future specialized-reasoner-routing + owner-transparency field). brain-sensitivity-routing's `SensitivityClassifier.classify(text) -> Sensitivity` returns ONLY the label; there is no category method, so **producers always write `category=None` in v1**. Do NOT invent a classifier method that returns a category.

Classification is **per-source, on-box, fail-closed**, via `SensitivityClassifier` (loopback-guarded; reuses the `sensitivity_classifier` role + the small local model — no extra resident model).

## Assumptions

- **brain-sensitivity-routing** complete: `artemis.sensitivity` exports `Sensitivity = Literal["general","sensitive"]`, `SensitivityClassifier` (`async def classify(self, request_text: str) -> Sensitivity`, loopback-guarded, fail-closed at every layer), and `SensitivityClassifierProtocol`. The `sensitivity_classifier` role is in `config/roles.toml` pointed at the loopback endpoint. → impact: Stop (M3-a reuses this exact classifier; no second model; the classify call is the SAME async loopback-guarded gate).
- **M3-a** complete (the spec amended): `IngestPipeline(connector_for, parser, embedder, store_for, is_unlocked)` with `async def ingest(self, source: Source) -> IngestResult`; `Document` (M0-d, carries `document_id`/`source_id`/`content_hash`/`scope`/`text`); `ChunkRecord` (frozen dataclass with `chunk_id`/`document_id`/`text`/`scope`/`content_hash`/`source_id`/`page`/`bbox`/`char_start`/`char_end`/`node_level`/`is_summary`/`parent_chunk_id`); `LanceDBVectorStore.add(scope, ids, vectors, metadata)` writing a row dict per chunk; `chunk_document(parsed, document, ...) -> list[ChunkRecord]`. → impact: Stop (this amendment adds two fields to `Document` + `ChunkRecord`, two columns to the LanceDB row, and one classify call in `ingest`).
- The classifier is injected into `IngestPipeline` (a new constructor param `classifier: SensitivityClassifierProtocol | None = None`) at the composition root — same pattern as `embedder`/`store_for`. When `None` (off-hardware default or classifier unavailable), the pipeline **fails closed**: every document is tagged `"sensitive"`. → impact: Stop (degrade-don't-crash AND fail-closed — a missing classifier never silently marks content general).
- The classify runs on the **normalized source text** (`Document.text` / the parsed text) ONCE per `ingest` call, BEFORE chunking — the resulting `(sensitivity, category)` is threaded into `chunk_document` so every chunk inherits it. → impact: Stop (per-source, not per-chunk — the ADR-029 cost invariant).
- Off-hardware: a `FakeSensitivityClassifier` (`async def classify` returning a configured label) drives the tests deterministically; the real classifier round-trip against Ollama is dev-box-runnable (no Mac gate — the classifier reuses the small local model). → impact: Low.

Simplicity check: considered classifying each chunk (richer per-chunk granularity) — rejected by ADR-029 (N× local calls, backfill-prohibitive; per-source whole-document tagging is fail-safe + cheap). Considered a new classifier method returning a category — rejected (brain-sensitivity-routing's classifier returns only the label; `category` is reserved/None in v1). The minimum is one classify call per source + two additive fields threaded through the existing chunk/row vocabulary.

## Prerequisites

- Specs complete: **brain-sensitivity-routing** (`SensitivityClassifier`/`Sensitivity`), **M3-a** (the ingestion pipeline amended).
- Environment: no new PyPI deps (reuses the local model already served).

## Files to Change

| File | Operation | Notes |
|------|-----------|-------|
| `/Users/artemis-build/artemis/src/artemis/ingest/connectors.py` (or wherever `Document` is defined — M0-d `ports`) | modify | add `sensitivity: Sensitivity = "sensitive"` + `category: str \| None = None` to `Document` (additive, fail-closed default) |
| `/Users/artemis-build/artemis/src/artemis/ingest/chunking.py` | modify | thread `sensitivity`/`category` into `chunk_document(...)` → each `ChunkRecord` carries them (additive fields, defaulted `"sensitive"`/`None`) |
| `/Users/artemis-build/artemis/src/artemis/adapters/lancedb_store.py` | modify | `add(...)` writes `sensitivity TEXT` + `category TEXT` (nullable) columns from `metadata`; row dict gains the two keys |
| `/Users/artemis-build/artemis/src/artemis/ingest/pipeline.py` | modify | `IngestPipeline.__init__` gains `classifier: SensitivityClassifierProtocol \| None = None`; `ingest` classifies the source text once (fail-closed) and threads the tag into `chunk_document` + the row metadata |
| `/Users/artemis-build/artemis/tests/test_ingest_pipeline.py` | modify | add `FakeSensitivityClassifier`; assert per-source tag propagates to all chunks + LanceDB rows; assert fail-closed when classifier is None or raises |

All paths under `/Users/artemis-build/artemis/`.

## Tasks

- [ ] **Task 1: Add the sensitivity fields to `Document` + `ChunkRecord`** — files: `/Users/artemis-build/artemis/src/artemis/ingest/connectors.py` (Document), `/Users/artemis-build/artemis/src/artemis/ingest/chunking.py` (ChunkRecord) —

  **NOTE (on-disk reality):** `Document` in `artemis.ports.types` is a **plain class with an explicit `__init__`**, NOT a `@dataclass` (so `dataclasses.replace()` does NOT work on it — see Task 3). Add the two new fields as **defaulted `__init__` parameters** (appended after the existing params) and assign them to `self`:
  ```python
  def __init__(
      self, ...,                               # existing Document params unchanged
      sensitivity: "Sensitivity" = "sensitive",   # ADR-029 §1 — fail-closed default
      category: str | None = None,                # reserved (unconsumed in v1)
  ) -> None:
      ...                                      # existing assignments unchanged
      self.sensitivity = sensitivity
      self.category = category
  ```
  `ChunkRecord` is a real `@dataclass` (M3-a base) — add the SAME two additive fields to it as defaulted dataclass fields, identically. `import` `Sensitivity` from `artemis.sensitivity`. (Do NOT convert `Document` to a dataclass — keep its existing class style.)

  `chunk_document(parsed, document, *, contextual=False, context_fn=None) -> list[ChunkRecord]` — propagate: each produced `ChunkRecord` copies `document.sensitivity` and `document.category` (the per-source tag rides every chunk). Add no new classify call here (chunking does NOT classify — the tag is already on the `Document`).

  — done when: `uv run mypy --strict src` passes; `Document(...).sensitivity == "sensitive"` by default; a `Document(sensitivity="general")` produces `ChunkRecord`s all carrying `sensitivity == "general"` via `chunk_document`; `ChunkRecord` defaults are `"sensitive"`/`None`.

- [ ] **Task 2: Persist the tag on the LanceDB row** — files: `/Users/artemis-build/artemis/src/artemis/adapters/lancedb_store.py` (modify) —

  In `LanceDBVectorStore.add(scope, ids, vectors, metadata)`: the per-chunk row dict gains `"sensitivity"` and `"category"` keys taken from `metadata` (the pipeline supplies them per chunk). The LanceDB table schema gains `sensitivity` (string) + `category` (nullable string) columns. On table CREATE, include the two columns; on an existing table without them (a pre-ADR-029 table), the column is added on next write or via a migration note (document: a fresh dev-box table includes them from creation; an on-hardware pre-existing table needs a one-shot re-index — see § Migration). Default-write `"sensitive"` if a row's metadata omits the key (fail-closed).

  — done when: `uv run mypy --strict src` passes; `add(...)` writes rows whose `sensitivity`/`category` columns reflect the supplied metadata; a row whose metadata omits `sensitivity` is written as `"sensitive"`; the table schema query shows both columns.

- [ ] **Task 3: Classify per-source in `ingest`, fail-closed** — files: `/Users/artemis-build/artemis/src/artemis/ingest/pipeline.py` (modify) —

  `IngestPipeline.__init__` gains `classifier: SensitivityClassifierProtocol | None = None` (last param, defaulted — existing call sites stay valid).

  In `async def ingest(self, source) -> IngestResult`, AFTER the parse → `Document` build (`to_document`) and BEFORE chunking:
  ```python
  # ADR-029 §1: per-source classify, once, on-box, fail-closed.
  sensitivity: Sensitivity = "sensitive"
  if self._classifier is not None:
      try:
          sensitivity = await self._classifier.classify(doc.text)
      except Exception:
          logger.warning("sensitivity classify failed (%s) — failing closed to sensitive", "exc")
          sensitivity = "sensitive"
  doc.sensitivity = sensitivity   # Document is a plain class (NOT a dataclass) — set attrs directly; do NOT use dataclasses.replace
  doc.category = None              # category reserved (None in v1)
  ```
  Thread `doc` (now tagged) into `chunk_document(parsed, doc, ...)` so every chunk inherits the tag; include `sensitivity`/`category` in each chunk's `metadata` dict passed to `store.add(...)`. The idempotency check (`has_document`) is unaffected (the tag is not part of `content_hash` — re-classifying an unchanged source is acceptable but the skip path short-circuits before classify if the content_hash already matches; place the classify AFTER the idempotency skip so an unchanged re-ingest does NOT re-run the local model — document this ordering).

  **NEVER log `doc.text` or any chunk text** at any level (it may be sensitive) — log only the source_id + the resulting label at debug.

  — done when: `uv run mypy --strict src` passes; `await ingest(file_source)` with a `FakeSensitivityClassifier(label="general")` writes chunks all tagged `"general"`; with `classifier=None` all chunks are `"sensitive"`; a classifier that raises → `"sensitive"` (no exception propagates); an idempotent re-ingest (same content_hash) does NOT call `classify` again (skip-before-classify ordering).

- [ ] **Task 4: Tests** — files: `/Users/artemis-build/artemis/tests/test_ingest_pipeline.py` (modify) —

  Add a `FakeSensitivityClassifier` (`async def classify(self, text) -> Sensitivity`, returns a configured label; a variant that raises).

  - **Per-source propagation:** ingest a file source with `FakeSensitivityClassifier("sensitive")` → every LanceDB row + every `ChunkRecord` has `sensitivity == "sensitive"`; `classify` was called exactly ONCE (per-source, not per-chunk — assert call count == 1 even though N>1 chunks were written).
  - **General path:** `FakeSensitivityClassifier("general")` → all chunks `"general"`.
  - **Fail-closed — no classifier:** `IngestPipeline(..., classifier=None)` → all chunks `"sensitive"`.
  - **Fail-closed — classifier raises:** the raising fake → all chunks `"sensitive"`; no exception propagates from `ingest`.
  - **category reserved:** every row's `category is None` in v1.
  - **Idempotent re-ingest skips classify:** ingest the same unchanged source twice → the second call returns `skipped=True` and `classify` was NOT called a second time (assert call count stays 1).

  — done when: `uv run pytest -q tests/test_ingest_pipeline.py` passes AND `uv run mypy --strict src tests/test_ingest_pipeline.py` passes.

- [ ] **Task 5 (GATED — on-hardware):** Real classifier round-trip — on the Mini/dev box with the served `sensitivity_classifier` model: ingest a known-sensitive document (e.g. a medical PDF) → all its chunks tagged `"sensitive"` on the real LanceDB table; ingest a newsletter → `"general"`. Confirm one classify call per document during a small backfill (not per-chunk). — done when: recorded in handoff. (Dev-box runnable — no Mac gate.)

## Migration

A pre-ADR-029 LanceDB table lacks the two columns. On the dev box the table is created post-amendment (columns present from creation — no migration). On-hardware with an existing corpus: a one-shot re-index (re-ingest, which now classifies + writes the columns) OR a LanceDB `add_columns` defaulting all existing rows to `"sensitive"` (fail-closed) then a background re-classify. Document the chosen path; the cross_model_review covers the live-data re-index.

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Modify | `/Users/artemis-build/artemis/src/artemis/ingest/connectors.py` |
| Modify | `/Users/artemis-build/artemis/src/artemis/ingest/chunking.py` |
| Modify | `/Users/artemis-build/artemis/src/artemis/adapters/lancedb_store.py` |
| Modify | `/Users/artemis-build/artemis/src/artemis/ingest/pipeline.py` |
| Modify | `/Users/artemis-build/artemis/tests/test_ingest_pipeline.py` |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict src tests/test_ingest_pipeline.py` | Type gate |
| `uv run ruff check . && uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q tests/test_ingest_pipeline.py` | Test gate |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | `src/artemis/ingest/connectors.py`, `src/artemis/ingest/chunking.py`, `src/artemis/adapters/lancedb_store.py`, `src/artemis/ingest/pipeline.py`, `tests/test_ingest_pipeline.py` |
| `git commit` | `"feat: SENS-prod-M3a — per-source sensitivity tag at ingestion (ADR-029 §1)"` |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_ENV_FILE` | Settings + roles (sensitivity_classifier endpoint) |

### Network
| Action | Purpose |
|--------|---------|
| local `127.0.0.1` (GATED on-hardware) | the loopback classifier model call; off-hardware uses the fake |

## Specialist Context

### Security

- **Fail-closed is load-bearing:** a false "general" leaks an owner document to the cloud (unrecoverable per ADR-029); a false "sensitive" only keeps a benign doc local (a quality cost). Every failure path — `classifier=None`, classify raises, metadata omits the key — resolves to `"sensitive"`. The classifier itself is loopback-guarded (brain-sensitivity-routing); M3-a does not weaken that.
- **No content logging:** `doc.text` and chunk text are NEVER logged (they may be sensitive). Log source_id + label only, at debug.
- **Per-source classify reads raw content on-box** (loopback only) and emits only a label — same posture as the conversation gate; sensitivity is the THIRD axis (orthogonal to untrusted/quarantine — ADR-029). This spec does not touch the quarantine machinery.

[apex-security review: confirm the fail-closed default at all three sites (None classifier, raise, missing metadata key); confirm no doc/chunk text reaches a log; confirm the classify is on the loopback `SensitivityClassifier`, never the composite/cloud port. cross_model_review covers the live-data re-index migration.]

### Performance

- ONE local-model classify call per source document (per-source, not per-chunk — the ADR-029 cost decision). Heaviest during the bounded Gmail/document backfill; incremental thereafter. The skip-before-classify ordering means an unchanged re-ingest costs zero model calls. The two extra LanceDB columns are negligible storage.

### Accessibility

(none — no frontend; the held-back surfacing is Wave-P enforcer + Wave-U client)

## Documentation

| Doc type | File | Action |
|----------|------|--------|
| Inline | `src/artemis/ingest/pipeline.py` | Document the per-source-not-per-chunk classify, the fail-closed default, the skip-before-classify ordering, and that `category` is reserved/None in v1 |
| Data model | `docs/technical/architecture/data-model.md` | Note the `sensitivity`/`category` columns on the doc-corpus LanceDB row |

## Acceptance Criteria

- [ ] `uv run mypy --strict src tests/test_ingest_pipeline.py` → verify: exit 0.
- [ ] `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.
- [ ] `uv run pytest -q tests/test_ingest_pipeline.py` → verify: per-source tag propagates to all chunks + rows with exactly ONE classify call; general path tags general; fail-closed on None classifier / raising classifier / missing metadata → "sensitive"; category is None; idempotent re-ingest does not re-classify.
- [ ] `uv run python -c "from artemis.sensitivity import Sensitivity; from artemis.ingest.pipeline import IngestPipeline; print('ok')"` → verify: prints `ok`.
- [ ] (GATED) real classifier tags a medical doc sensitive / a newsletter general; one call per document → recorded in handoff.

## Progress
_(Coding mode writes here — do not edit manually)_
