---
spec: sens-prod-m4b
status: ready
token_profile: balanced
autonomy_level: L2
cross_model_review: true
---
<!-- amended for ADR-029 §1 (producer stage). AMENDS M4-b (memory write path). Facts inherit
     source-derived sensitivity; if no source tag is available, the fact text is classified on-box
     (fail-closed). Uses the field contract canonicalised in SENS-prod-M3a. -->

# Spec: SENS-prod-M4b — memory facts carry source-derived `sensitivity` (ADR-029 §1)

**Identity:** Add the canonical `sensitivity`/`category` fields (from SENS-prod-M3a) to `ExtractedFact` and the persisted M4-a fact row, populated by **inheritance from the source** that produced the fact (turn/email/doc); when no source tag is available, classify the fact text **once, on-box, fail-closed** — the memory producer half of the ADR-029 wall.
→ why: see docs/technical/adr/ADR-029-sensitivity-ingestion-gate.md §1 · field contract in docs/changes/SENS-prod-M3a.md · reuses docs/changes/brain-sensitivity-routing.md classifier.

## Field contract (inherited from SENS-prod-M3a — do not redefine)

`sensitivity: Sensitivity` (fail-closed default `"sensitive"`) + `category: str | None = None` (reserved, `None` in v1). See SENS-prod-M3a § Canonical sensitivity field contract.

**ADR-029 §1 note (residual sensitive memory):** owner-rules already exclude finance/health from memory, so the residual sensitive memory is **journal / credentials / identity**. Most general turns produce `"general"` facts; the gate exists for that residual sensitive minority.

## Assumptions

- **brain-sensitivity-routing** complete: `artemis.sensitivity` exports `Sensitivity`, `SensitivityClassifier`, `SensitivityClassifierProtocol`. → impact: Stop.
- **M4-b** complete (the spec amended): `ExtractedFact { subject, relation, object, confidence, keywords, contextual_description }` (frozen) is produced by `FactExtractor.extract(text, *, context=None) -> list[ExtractedFact]` (async, on the local `sensitive_reasoner` role); the A.U.D.N. decider applies ADD/UPDATE/DELETE/NOOP via the M4-a repository, carrying provenance; the M4-a fact row (`FactRow`) is the persisted shape. → impact: Stop (this amendment adds two fields to `ExtractedFact` + the persisted row, and a source-tag inheritance / fallback-classify path).
- The fact's sensitivity is **inherited from the source** where available: a fact extracted from a signal email inherits the email's tag (SENS-prod-M8b1 supplies it); a fact extracted from an ingested doc inherits the doc's tag (SENS-prod-M3a). For facts extracted from a **conversational turn** (no upstream ingestion tag), the write path classifies the fact text on-box once (fail-closed). → impact: Stop (inheritance-first, classify-fallback — avoids re-classifying already-tagged sources).
- `FactExtractor.extract` gains an optional `source_sensitivity: Sensitivity | None = None` param: when the caller (M8-b1, M3-a-fed memory, or the turn write-path) knows the source tag, it passes it and the extracted facts inherit it; when `None`, the extractor classifies each fact's text (or the turn text) on-box. The classifier is injected into `FactExtractor` (a new param, defaulted `None` → fail-closed `"sensitive"` if it must classify but has no classifier). → impact: Stop.
- Off-hardware: `FakeSensitivityClassifier` + `FakeExtractor`. Dev-box-runnable with the real local model. → impact: Low.

Simplicity check: inheritance-first means most facts get their tag for free (the source already classified once). Only un-sourced turn facts incur a classify, and that's batched off the interactive turn (M4-b is already async/off-turn). The minimum is two additive fields + an inheritance param + a fail-closed fallback classify.

## Prerequisites

- Specs complete: **brain-sensitivity-routing**, **M4-b** (write path + extraction + A.U.D.N.), **M4-a** (the `FactRow` persisted shape), **SENS-prod-M3a** (field contract). **SENS-prod-M8b1** supplies the email-source tag (sibling producer).
- Environment: no new PyPI deps.

## Files to Change

| File | Operation | Notes |
|------|-----------|-------|
| `/Users/artemis-build/artemis/src/artemis/memory/extraction.py` | modify | add `sensitivity: Sensitivity = "sensitive"` + `category: str \| None = None` to `ExtractedFact`; `FactExtractor.__init__` gains `classifier: SensitivityClassifierProtocol \| None = None`; `extract(...)` gains `source_sensitivity: Sensitivity \| None = None` (inherit-or-classify) |
| `/Users/artemis-build/artemis/src/artemis/memory/repository.py` (M4-a `FactRow` + insert path) | modify | persist `sensitivity`/`category` columns on the fact row (additive, nullable `category`); the A.U.D.N. ADD/UPDATE carries them through |
| `/Users/artemis-build/artemis/src/artemis/memory/write_path.py` | modify | thread `source_sensitivity` from the enqueue caller into `extract(...)`; the turn write-path passes `None` (→ classify fallback) |
| `/Users/artemis-build/artemis/tests/test_memory_write_path.py` (or the M4-b test file) | modify | inheritance path, classify-fallback path, fail-closed, residual-sensitive (journal) tagging |

All paths under `/Users/artemis-build/artemis/`.

## Tasks

- [ ] **Task 1: Add sensitivity to `ExtractedFact` + inherit-or-classify in `extract`** — files: `/Users/artemis-build/artemis/src/artemis/memory/extraction.py` (modify) —

  Add to `ExtractedFact` (frozen): `sensitivity: Sensitivity = "sensitive"`, `category: str | None = None`.

  `FactExtractor.__init__(self, model, *, role="sensitive_reasoner", classifier: SensitivityClassifierProtocol | None = None)`.

  `async def extract(self, text, *, context=None, source_sensitivity: Sensitivity | None = None) -> list[ExtractedFact]`:
  - run the existing grammar-constrained extraction → `facts: list[ExtractedFact]`.
  - resolve the tag:
    ```python
    if source_sensitivity is not None:
        tag = source_sensitivity                      # inherit — no extra classify
    elif self._classifier is not None:
        try:
            tag = await self._classifier.classify(text)   # classify the source turn text once
        except Exception:
            tag = "sensitive"                          # fail-closed
    else:
        tag = "sensitive"                              # fail-closed (no classifier, no source tag)
    facts = [replace(f, sensitivity=tag, category=None) for f in facts]
    ```
  - classify ONCE per `extract` call (over the turn `text`), NOT per fact — all facts from one turn share the source tag (consistent with per-source). NEVER log `text` or fact `object`.

  — done when: `uv run mypy --strict src` passes; `extract(text, source_sensitivity="general")` returns facts all `"general"` (no classify call — assert); `extract(text)` with an injected `FakeSensitivityClassifier("sensitive")` and no `source_sensitivity` classifies once and tags all facts `"sensitive"`; `extract(text)` with `classifier=None` and no source tag → all `"sensitive"` (fail-closed).

- [ ] **Task 2: Persist the tag on the fact row through A.U.D.N.** — files: `/Users/artemis-build/artemis/src/artemis/memory/repository.py` (modify) —

  The M4-a `FactRow` + the ADD/UPDATE insert path gain `sensitivity` (TEXT) + `category` (nullable TEXT) columns. An ADD writes the `ExtractedFact.sensitivity`/`category`; an UPDATE (close-interval + insert) carries the new fact's tag; DELETE (tombstone) and NOOP are unaffected. The column is additive; existing rows default `"sensitive"` (fail-closed) on migration.

  — done when: `uv run mypy --strict src` passes; an ADD persists the fact's `sensitivity`; reading the row back via `as_of` returns the tag; an UPDATE carries the new tag; the schema query shows both columns.

- [ ] **Task 3: Thread source tag through the write path** — files: `/Users/artemis-build/artemis/src/artemis/memory/write_path.py` (modify) —

  `MemoryWriteQueue.enqueue(text, turn_id, *, source_sensitivity: Sensitivity | None = None)` — the enqueue caller passes the source tag when known (M8-b1 email facts pass the email tag; doc-derived facts pass the doc tag; a plain conversational turn passes `None` → classify fallback). The write path forwards `source_sensitivity` to `extract(...)`. Default `None` keeps existing call sites valid.

  — done when: `uv run mypy --strict src` passes; `enqueue(text, turn_id, source_sensitivity="general")` produces general facts (inheritance); `enqueue(text, turn_id)` (turn path) triggers the classify fallback.

- [ ] **Task 4: Tests** — files: the M4-b test file (modify) —

  `FakeSensitivityClassifier` (label / raising), `FakeExtractor`.

  - **Inheritance:** `extract(text, source_sensitivity="general")` → all facts `"general"`; classifier NOT called (assert call count 0).
  - **Classify fallback (turn path):** `extract(text)` with `FakeSensitivityClassifier("sensitive")`, no source tag → classify called once; all facts `"sensitive"`.
  - **Residual sensitive (journal):** a journal-style turn text → classifier returns `"sensitive"` → fact tagged sensitive (illustrates the residual-sensitive memory category per ADR-029).
  - **Fail-closed:** `classifier=None` + no source tag → all `"sensitive"`; raising classifier → `"sensitive"`.
  - **Persistence:** an ADD'd fact's `sensitivity` round-trips through `as_of`; `category is None`.
  - **One classify per extract:** N facts from one turn → classify called once, not N times.

  — done when: `uv run pytest -q tests/test_memory_write_path.py` (or the M4-b test) passes AND `uv run mypy --strict src <test>` passes.

- [ ] **Task 5 (GATED — on-hardware):** Real classifier — a journal turn → sensitive fact; a general fact-bearing turn → general fact; an email-sourced fact inherits the email tag (cross-check with SENS-prod-M8b1). — done when: recorded in handoff. (Dev-box runnable.)

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Modify | `/Users/artemis-build/artemis/src/artemis/memory/extraction.py` |
| Modify | `/Users/artemis-build/artemis/src/artemis/memory/repository.py` |
| Modify | `/Users/artemis-build/artemis/src/artemis/memory/write_path.py` |
| Modify | `/Users/artemis-build/artemis/tests/test_memory_write_path.py` |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict src tests/test_memory_write_path.py` | Type gate |
| `uv run ruff check . && uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q tests/test_memory_write_path.py` | Test gate |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | `src/artemis/memory/extraction.py`, `src/artemis/memory/repository.py`, `src/artemis/memory/write_path.py`, `tests/test_memory_write_path.py` |
| `git commit` | `"feat: SENS-prod-M4b — memory facts carry source-derived sensitivity (ADR-029 §1)"` |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_ENV_FILE` | Settings + roles (sensitivity_classifier endpoint) |

### Network
| Action | Purpose |
|--------|---------|
| local `127.0.0.1` (GATED) | loopback classifier (fallback path only); off-hardware uses the fake |

## Specialist Context

### Security

- **Inheritance-first prevents tag drift:** a fact from a sensitive email/doc inherits that tag, so a sensitive source cannot produce a general fact that later reaches the cloud via recall. Only un-sourced turn facts classify, and they fail closed.
- **Fail-closed** at every fallback site. A false "general" on a journal/credential fact would leak it via recall to a cloud prompt — unacceptable; the residual-sensitive memory (journal/credentials/identity) is exactly what this protects.
- **No content logging:** turn `text` and fact `object` are never logged (M4-b invariant preserved).
- Extraction + classify both run on the **local** `sensitive_reasoner`/`sensitivity_classifier` roles — the owner's turn text never leaves the box for memory tagging.

[apex-security review: confirm inheritance overrides classify (no double-classify of sourced facts); confirm fail-closed on the turn path with no classifier; confirm no general fact derives from a sensitive source; confirm no plaintext logged. cross_model_review covers the existing-facts re-tag migration.]

### Performance

- Sourced facts cost ZERO classify calls (inheritance). Un-sourced turn facts cost one classify per `extract` (per-source, not per-fact), batched off the interactive turn (M4-b is already async). Negligible added latency; the gate exists for the residual-sensitive minority.

### Accessibility

(none)

## Documentation

| Doc type | File | Action |
|----------|------|--------|
| Inline | `src/artemis/memory/extraction.py` | Document inherit-or-classify (one classify per extract, fail-closed), the residual-sensitive memory category, and that `category` is reserved/None |
| Data model | `docs/technical/architecture/data-model.md` | Note the `sensitivity`/`category` columns on the memory fact row |

## Acceptance Criteria

- [ ] `uv run mypy --strict src tests/test_memory_write_path.py` → verify: exit 0.
- [ ] `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.
- [ ] `uv run pytest -q tests/test_memory_write_path.py` → verify: inheritance tags without a classify call; turn-path classify fallback tags once per extract; residual-sensitive (journal) → sensitive; fail-closed on None/raising classifier; tag round-trips through as_of; category None; one classify per extract not per fact.
- [ ] `uv run python -c "from artemis.memory.extraction import ExtractedFact; print(ExtractedFact(subject='owner', relation='likes', object='x', confidence=1.0).sensitivity)"` → verify: prints `sensitive` (fail-closed default).
- [ ] (GATED) journal turn → sensitive fact; email-sourced fact inherits → recorded in handoff.

## Progress
_(Coding mode writes here — do not edit manually)_
