---
spec: sens-carry-m4c1
status: ready
token_profile: lean
autonomy_level: L2
depends_on: sens-prod-m4b
---
<!-- ADR-029 §2 (carrier). Surfaces the per-fact `sensitivity`/`category` tag (written by SENS-prod-M4b
     onto the facts row) up onto the recalled/injected `Fact` shape, so the RAG-compose enforcer can
     filter sensitive recalled facts out of the cloud-bound prompt. Carry-only — M4-c-1 does NOT enforce. -->

# Spec: SENS-carry-M4c1 — surface the `sensitivity` tag on recalled/injected `Fact`s

**Identity:** Materialize the `sensitivity` (and reserved `category`) column written by SENS-prod-M4b onto the `Fact` shape returned by `MemoryStore.recall` and `inject_context`, so the cloud-boundary enforcer can read each recalled fact's tag. Carry-only — M4-c-1 performs NO enforcement.
→ why: see docs/technical/adr/ADR-029-sensitivity-ingestion-gate.md §2 (carrier).

## Assumptions

- **SENS-prod-M4b** complete: each `FactRow` (M4-a facts table) carries a `sensitivity TEXT` column (`"general"`/`"sensitive"`, fail-closed) + a nullable `category TEXT`, written at fact-write time (inherited from the source turn/doc, or classified on-box if no source sensitivity). → impact: Stop (this spec reads those columns; a missing/NULL `sensitivity` defaults to `"sensitive"` — fail-closed).
- **M0-d** `Fact` is the frozen dataclass `Fact {fact_id, person_id, subject, relation, object, confidence, valid_at, invalid_at}` in `artemis.ports.types`. This spec adds `sensitivity: Sensitivity = "sensitive"` + `category: str | None = None` (defaulted, fail-closed). `Sensitivity` from `artemis.sensitivity`. → impact: Stop (defaulted additive fields keep existing `Fact(...)` constructors valid).
- **M4-c-1** `SqliteMemoryStore.recall` / `inject_context` build `Fact`s from `FactRow`s (the M4-a→M0-d row→Fact mapping). This spec extends that mapping to copy the two columns. → impact: Stop (one mapping site, in the store's row→Fact conversion).
- The decay re-rank (`recall_multiplier`) and inject token-budget pack are unchanged — the tag rides on the returned facts without affecting ranking. → impact: Low.
- **Note (ADR-029):** owner-rules already exclude finance/health from memory, so the residual sensitive memory is journal/credentials/identity. Most recalled facts will be `"general"`; the carrier still fail-closes any untagged fact to `"sensitive"`. → impact: Low.
- Off-hardware: seed facts with `sensitivity="general"`/`"sensitive"` and assert the tag surfaces on recalled/injected `Fact`s. → impact: Low.

Simplicity check: two defaulted fields on `Fact` + reading two columns in the one row→Fact mapping. No new method, no enforcement, no signature change to `recall`/`inject_context`.

## Prerequisites

- Specs complete: **SENS-prod-M4b** (writes the column), **M4-c-1** (`recall`/`inject_context` materialization), **M4-a** (`FactRow`), **brain-sensitivity-routing** (`Sensitivity`).
- Environment: no new PyPI deps.

## Files to Change

| File | Operation | Notes |
|------|-----------|-------|
| `/Users/artemis-build/artemis/src/artemis/ports/types.py` | modify | add `sensitivity: Sensitivity = "sensitive"` + `category: str | None = None` to `Fact` |
| `/Users/artemis-build/artemis/src/artemis/memory/store.py` | modify | the row→`Fact` mapping (in `recall` + `inject_context`) reads `row.sensitivity` (default `"sensitive"`) + `row.category` |
| `/Users/artemis-build/artemis/tests/test_memory_inject_recall.py` | modify | assert the tag surfaces on recalled + injected `Fact`s (general + sensitive + missing-defaults-sensitive) |

All paths under `/Users/artemis-build/artemis/`.

## Tasks

- [ ] **Task 1: Add the tag fields to `Fact`** — files: `/Users/artemis-build/artemis/src/artemis/ports/types.py` (modify) —

  **NOTE (on-disk reality):** `Fact` in `artemis.ports.types` is a **plain class with an explicit `__init__`** (params end at `invalid_at: datetime | None = None`), NOT a `@dataclass`. Add the two new fields as **defaulted `__init__` parameters** (after `invalid_at`) and assign them to `self`:
  ```python
  def __init__(
      self, ...,                                   # existing params unchanged, through invalid_at
      invalid_at: datetime | None = None,
      sensitivity: "Sensitivity" = "sensitive",    # ADR-029 carrier — fail-closed default; set from the FactRow
      category: str | None = None,                 # reserved (written by SENS-prod-M4b, unconsumed in v1)
  ) -> None:
      ...                                          # existing assignments unchanged
      self.sensitivity = sensitivity
      self.category = category
  ```
  Import `Sensitivity` from `artemis.sensitivity`. Defaults make the params additive — existing `Fact(...)` call sites stay valid and get the fail-closed default. (Do NOT convert `Fact` to a dataclass — keep the existing class style; surgical two-param add.)

  — done when: `uv run mypy --strict src` passes; a `Fact(...)` omitting `sensitivity` has `.sensitivity == "sensitive"`; `Fact(..., sensitivity="general")` round-trips.

- [ ] **Task 2: Read the column in the row→Fact mapping** — files: `/Users/artemis-build/artemis/src/artemis/memory/store.py` (modify) —

  Wherever `recall` and `inject_context` convert a `FactRow` → `Fact` (the single mapping helper if one exists; otherwise both sites), read:
  ```python
  sensitivity: Sensitivity = "general" if row.sensitivity == "general" else "sensitive"   # fail-closed
  category = row.category
  ```
  and pass them into the `Fact(...)` construction. If M4-a's `FactRow` does not yet expose `sensitivity`/`category` attributes, this spec's prereq SENS-prod-M4b added them to the row + the SELECT — confirm the `FactRow` carries them before mapping (if absent, default to `"sensitive"`/`None`).

  — done when: `uv run mypy --strict src` passes; a recalled fact from a `sensitivity="general"` row has `.sensitivity == "general"`; a `"sensitive"` or untagged row → `"sensitive"`; `inject_context` carries the same tag on its returned facts.

- [ ] **Task 3: Tests** — files: `/Users/artemis-build/artemis/tests/test_memory_inject_recall.py` (modify) — add:

  - Seed facts: one `sensitivity="general"`, one `"sensitive"`, one untagged. `await store.recall(...)` → returned `Fact`s carry the matching tag; the untagged one defaults to `"sensitive"`.
  - `await store.inject_context(...)` → the injected `Fact`s carry the tag (so the enforcer can later filter sensitive injected facts from a cloud prompt).
  - `category` round-trips (`"journal"` → `"journal"`; NULL → `None`).
  - Regression: existing decay-rank / token-budget / access-bump tests still pass (the tag does not alter ranking).

  — done when: `uv run pytest -q tests/test_memory_inject_recall.py` passes AND `uv run mypy --strict src tests/test_memory_inject_recall.py` passes.

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Modify | `/Users/artemis-build/artemis/src/artemis/ports/types.py` |
| Modify | `/Users/artemis-build/artemis/src/artemis/memory/store.py` |
| Modify | `/Users/artemis-build/artemis/tests/test_memory_inject_recall.py` |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict src tests/test_memory_inject_recall.py` | Type gate |
| `uv run ruff check . && uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q tests/test_memory_inject_recall.py` | Test gate |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | `src/artemis/ports/types.py`, `src/artemis/memory/store.py`, `tests/test_memory_inject_recall.py` |
| `git commit` | `"feat: ADR-029 carrier — surface sensitivity tag on recalled/injected Facts (M4-c-1)"` |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_ENV_FILE` | Settings + scope_dir for the temp memory store |

### Network
| Action | Purpose |
|--------|---------|
| (none) | Pure column-read + dataclass field |

## Specialist Context

### Security

- **Fail-closed:** any fact whose `sensitivity` is not exactly `"general"` (including untagged pre-ADR-029 rows) surfaces as `"sensitive"`. The enforcer therefore never receives a sensitive recalled fact mislabelled general.
- M4-c-1 still does NOT enforce — it carries the tag. The inject block already goes ONLY to the local responder (M4-c-1's existing invariant); the enforcer adds the additional cloud-prompt filtering for the RAG path. No fact reaches a cloud model in this spec.
- NEVER log fact `object`/`subject` at info (M4-c-1 invariant unchanged) — the tag is a label, not content.

### Performance

- Two extra column reads per recalled/injected fact — negligible (per-person scale, lazy at recall/inject time).

### Accessibility

(none — no frontend)

## Documentation

| Doc type | File | Action |
|----------|------|--------|
| Inline | `src/artemis/ports/types.py` | Document the two carrier fields on `Fact` (fail-closed; written by SENS-prod-M4b; read by the enforcer) |

## Acceptance Criteria

- [ ] `uv run mypy --strict src tests/test_memory_inject_recall.py` → verify: exit 0.
- [ ] `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.
- [ ] `uv run pytest -q tests/test_memory_inject_recall.py` → verify: tag surfaces on recalled + injected facts; missing column defaults to `"sensitive"`; `category` round-trips; existing decay/inject tests still green.
- [ ] `uv run python -c "from artemis.ports.types import Fact; from datetime import datetime, timezone; f=Fact(fact_id='f', person_id='p', subject='s', relation='r', object='o', confidence=1.0, valid_at=datetime.now(timezone.utc), invalid_at=None); print(f.sensitivity)"` → verify: prints `sensitive`.

## Progress
_(Coding mode writes here — do not edit manually)_
