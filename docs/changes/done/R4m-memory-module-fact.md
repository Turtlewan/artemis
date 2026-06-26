---
spec: R4m-memory-module-fact
status: ready
cross_model_review: true
token_profile: balanced
autonomy_level: L2
---

# Spec: R4m — Memory module-fact-push (`add_module_fact`)

**Identity:** Adds a module-initiated STRUCTURED fact push to `MemoryWritePath` — no LLM re-extraction, explicit category + sensitivity (fail-closed `sensitive`) + module-source provenance. This is the first non-owner, non-extractor writer to memory. The gift reaction that USES it lands in R6c.
<!-- → why: see docs/technical/adr/ADR-032-reactions-runtime-composition.md (Decision 6) and ADR-029 (sensitivity wall). -->

## Assumptions
<!-- Coding mode verifies each item against the codebase before executing. -->
- The push is a method on `MemoryWritePath` (`add_module_fact`), NOT on `SqliteMemoryStore` / the `MemoryStore` Protocol. `MemoryWritePath` already holds the `BitemporalRepository` (`self._repo`), embedder (`self._embedder`), and entity-resolution seam (`self.entity_repo`), and `repo.add(...)` takes the provenance/sensitivity/category/`subject_entity_id` kwargs (`write_path.py:143-155`). `SqliteMemoryStore.add_fact` drops sensitivity/category/provenance — wrong seam. → impact: Caution (a store-level seam can't carry the ADR-029 tag).
- `repo.add(...)` = positional `(subject, relation, object_, confidence, embedding)` + kwargs `source_turn_id`, `extractor_model`, `sensitivity`, `category`, `subject_entity_id` (confirmed `write_path.py:143-155`). The module `source_ref` is passed as `source_turn_id`; `extractor_model="module"`. → impact: Stop (wrong field name breaks the build).
- `add_module_fact` does NOT construct an `ExtractedFact`, does NOT call `self._extractor`/`self._decider`, and runs NO AUDN decide loop — module facts are pre-decided ADD-only. It embeds the triple and calls `repo.add` once. → impact: Stop (calling the extractor violates the Decision-6 contract).
- Default `sensitivity` is fail-closed `"sensitive"` when the caller passes nothing; callers wanting cloud-injectable facts (gifts, R6c) pass `"general"` EXPLICITLY. → impact: Stop (silent default-to-general is the exact failure this guards).
- Subject-entity resolution reuses `self.entity_repo.resolve_or_create_entity(subject, EntityType.PERSON)` in a try/except → `None` on failure (mirrors `process_turn` `write_path.py:91-99`). → impact: Low.

Simplicity check: considered `SqliteMemoryStore.add_fact` (smaller signature) — rejected: it discards sensitivity/category/provenance and ignores `person_id`, so it cannot carry the ADR-029 tag or the module `source_ref`. `MemoryWritePath.add_module_fact` is the minimal seam that already holds every dependency.

## Prerequisites
- Specs that must be complete first: none (Wave 1; testable against fakes — `FakeExtractor` must remain UNCALLED).
- Environment setup required: none.

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| `src/artemis/memory/write_path.py` | modify | Add `MemoryWritePath.add_module_fact(...)` structured push (no extractor). |
| `tests/test_memory_write_path.py` | modify | structured push writes Fact w/ given category+sensitivity; extractor NOT invoked; no-explicit-sensitivity fails closed to sensitive. |

## Exact changes
```python
async def add_module_fact(
    self,
    *,
    subject: str,
    relation: str,
    object_: str,            # object_ (trailing underscore) — matches repo.add's 3rd positional + avoids shadowing the builtin (ruff A002)
    category: str,
    source_ref: str,
    confidence: float = 1.0,
    sensitivity: Sensitivity = "sensitive",
) -> str:
    """Structured module-initiated fact push: no extractor, explicit sensitivity (fail-closed
    sensitive), source_ref -> source_turn_id provenance. The detecting module already decided this
    fact; memory never re-extracts from text here."""
    embedding = (await self._embedder.embed_documents([f"{subject} {relation} {object_}"]))[0]
    try:
        subject_entity_id = self.entity_repo.resolve_or_create_entity(subject, EntityType.PERSON)
    except Exception:
        subject_entity_id = None
    return self._repo.add(
        subject, relation, object_, confidence, embedding,
        source_turn_id=source_ref,
        extractor_model="module",
        sensitivity=sensitivity,
        category=category,
        subject_entity_id=subject_entity_id,
    )
```
(`BitemporalRepository.add` returns the new `fact_id: str` (confirmed by data review) and its 3rd positional param is `object_` — call positionally; `add_module_fact` returns that `fact_id` directly.)

## Tasks
- [ ] Task 1: Add `add_module_fact` to `MemoryWritePath` per Exact changes — files: `src/artemis/memory/write_path.py` — done when: the method embeds the triple, resolves the subject PERSON entity (try/except→None), calls `repo.add` once with `source_turn_id=source_ref`, `sensitivity`, `category`, `subject_entity_id`, and NEVER touches `self._extractor`/`self._decider`.
- [ ] Task 2: Tests — files: `tests/test_memory_write_path.py` — done when: (i) `add_module_fact(category="gift_signal", sensitivity="general", …)` persists a row whose `get_fact` Fact has `category=="gift_signal"` and `sensitivity=="general"`; (ii) a spy/`FakeExtractor` on the `MemoryWritePath` records ZERO `extract` calls after `add_module_fact`; (iii) `add_module_fact(…)` with NO `sensitivity` kwarg persists `sensitivity=="sensitive"`.

## Wave plan
Wave 1: [Task 1] | Wave 2: [Task 2]

## Permissions

The following actions will run autonomously during build. Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | (none) |
| Modify | `src/artemis/memory/write_path.py`, `tests/test_memory_write_path.py` |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy` | Full-project type check. |
| `uv run ruff check . && uv run ruff format --check .` | Lint + format gate. |
| `uv run pytest -q` | Full test suite. |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | `src/artemis/memory/write_path.py tests/test_memory_write_path.py` |
| `git commit` | "feat: R4m memory module-fact-push (add_module_fact, ADR-032 Decision 6)" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| (none) | — |

### Network
| Action | Purpose |
|--------|---------|
| (none) | No package installs. |

## Specialist Context
### Security
`cross_model_review: true` (ADR-029 wall; first non-owner, non-extractor memory writer). Tested invariants: explicit sensitivity with fail-closed `"sensitive"` default (no silent general); the push never invokes the LLM extractor/classifier (detection already happened upstream); only explicit callers (R6c gift) pass `"general"`.

### Performance
(none.)

### Accessibility
(none — no frontend change.)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | `src/artemis/memory/write_path.py` | Docstring on `add_module_fact` (structured push, no extractor, fail-closed sensitive, source_ref→source_turn_id). |
| Reconcile | docs/technical/architecture/data-model.md | No new entity (writes the existing fact entity); verify the `extractor_model="module"` provenance value + module-source-fact case is reflected. |
| ADR | (none) | ADR-032 already records Decision 6. |

## Acceptance Criteria
- [ ] Persists structured Fact with caller's category + sensitivity → verify: test (i) reads back `category=="gift_signal"`, `sensitivity=="general"`.
- [ ] Never runs the LLM extractor → verify: test (ii) spy `.extract` count is 0.
- [ ] No explicit sensitivity fails closed → verify: test (iii) reads back `sensitivity=="sensitive"`.
- [ ] Whole project clean → verify: `uv run mypy`, `uv run ruff check . && uv run ruff format --check .`, `uv run pytest -q` all pass.

## Progress
_(Coding mode writes here — do not edit manually)_
