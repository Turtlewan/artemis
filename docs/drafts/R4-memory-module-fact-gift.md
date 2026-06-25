---
spec: R4-memory-module-fact-gift
status: draft
cross_model_review: true
token_profile: balanced
autonomy_level: L2
---

# Spec: R4 — Memory module-fact-push + register reaction:gift_signal

**Identity:** Adds a module-initiated STRUCTURED fact-push to the memory write path (no LLM
re-extraction; explicit category + sensitivity + provenance) and registers `reaction:gift_signal`
in comms to write a general-tagged gift fact through it.
→ why: see docs/technical/adr/ADR-032-reactions-runtime-composition.md (Decision 6) and ADR-029 (sensitivity wall).

## Assumptions
<!-- Coding mode verifies each item before executing. -->
- The new push lives as a method on `MemoryWritePath` (`add_module_fact`), NOT on `SqliteMemoryStore` or the `MemoryStore` Protocol. Rationale: `MemoryWritePath` already owns the `BitemporalRepository` + embedder + entity-resolution seam and the `repo.add(...)` provenance/sensitivity/category kwargs; `SqliteMemoryStore.add_fact` deliberately ignores `person_id`, drops sensitivity/category, and has no provenance arg, so it is the wrong seam. → impact: Caution (if reviewer prefers a store-level seam, the surface moves but the invariants below are unchanged).
- `repo.add(...)` is the persistence primitive: positional `(subject, relation, object_, confidence, embedding)` + keyword `source_turn_id`, `sensitivity`, `category`, `subject_entity_id`. Provenance field name is `source_turn_id` (confirmed in repository.py:233). The module `source_ref` is passed as `source_turn_id`. → impact: Stop (wrong field name breaks the build).
- `add_module_fact` does NOT construct an `ExtractedFact` and does NOT call `self._extractor` — it embeds the structured triple directly and calls `repo.add` once (no AUDN decide loop; module facts are pre-decided ADD-only). → impact: Stop (calling the extractor violates the ADR-032 Decision 6 contract).
- Default `sensitivity` for `add_module_fact` is fail-closed `"sensitive"` when the caller passes nothing explicit; gifts pass `"general"` explicitly. The signature makes `sensitivity` a keyword with default `"sensitive"`. → impact: Stop (silent default-to-general is the security failure this spec exists to prevent).
- `reaction:gift_signal` is a NEW comms rule bound to `EventType.EMAIL_INGESTED` (alongside A4/A5/A7), reaction_ref `reaction:gift_signal`, `tier=B`, `external_effect=False`. It is distinct from the pre-existing `TIER_A_BUILTINS` `"gift_signal"` rule (rulestore.py:129, bound to `FACT_ADDED` → `memory.note_gift_signal`), which is a downstream reaction-to-a-fact and is OUT OF SCOPE here. → impact: Caution (conflating the two would mis-wire the trigger).
- The comms gift event carries scalar payload fields `gift_signal_detected: bool`, `gift_item: str`, and a person `EntityRef` in `entity_refs` (module/entity_id). `person_id` for the fact is derived from that EntityRef's `entity_id`; `subject` is the same person ref string, `relation="interested_in"`, `object=gift_item`. → impact: Caution (payload key names are set here and must match R2's gmail emit when it lands; tests use these names).
- `MemoryWritePath` is reachable from `register_comms_reactions` via the existing `memory: object | None` param (currently `del memory`); the registration casts it to `MemoryWritePath`. → impact: Caution.

Simplicity check: considered adding the push to `SqliteMemoryStore.add_fact` (smallest signature change) — rejected because that seam discards sensitivity/category/provenance and ignores person_id, so it cannot carry the ADR-029 tag or the module source_ref. `MemoryWritePath.add_module_fact` is the minimal seam that already holds every dependency.

## Prerequisites
- Specs that must be complete first: none. This spec is independently buildable and testable against fakes (FakeExtractor must remain UNCALLED; a fake/in-memory `BitemporalRepository` + embedder back the test).
- Note (not a build prerequisite): the registered `reaction:gift_signal` only FIRES live once R1 composes the reactions runtime and R2 adds the gmail `EMAIL_INGESTED` emit seam. R4 does not depend on R1/R2/R3 to build or test.
- Environment setup required: none.

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| src/artemis/memory/write_path.py | modify | Add `MemoryWritePath.add_module_fact(...)` structured push (no extractor). |
| src/artemis/reactions/recipes/comms.py | modify | Add `react_gift_signal` recipe + `_gift_signal_tool` wrapper; register `reaction:gift_signal` rule in `register_comms_reactions`; stop `del memory`. |
| tests/test_memory_write_path.py | modify | Tests: structured push writes Fact w/ given category+sensitivity, extractor NOT invoked, no-explicit-sensitivity fails closed to sensitive. |
| tests/test_reactions_comms.py | modify | Test: gift_signal reaction produces a general-tagged `category="gift_signal"` person fact via the push. |

## Tasks
- [ ] Task 1: Add `add_module_fact` to `MemoryWritePath` — files: src/artemis/memory/write_path.py — done when: an async method `add_module_fact(self, *, person_id: PersonId, subject: str, relation: str, object: str, category: str, source_ref: str, confidence: float = 1.0, sensitivity: Sensitivity = "sensitive") -> str` embeds the `f"{subject} {relation} {object}"` triple, calls `self._repo.add(subject, relation, object, confidence, embedding, source_turn_id=source_ref, sensitivity=sensitivity, category=category, subject_entity_id=<resolved-or-None>)`, returns the new fact_id, and NEVER touches `self._extractor`/`self._decider`. Subject-entity resolution reuses the existing `entity_repo.resolve_or_create_entity(subject, EntityType.PERSON)` in a try/except → None on failure (mirrors process_turn).
- [ ] Task 2: Add the gift recipe + register the rule in comms — files: src/artemis/reactions/recipes/comms.py — done when: (a) `react_gift_signal(event, *, memory: MemoryWritePath) -> ReactionResult` returns `skipped` unless `event.event_type is EventType.EMAIL_INGESTED and _payload_bool(event, "gift_signal_detected")` and a `gift_item` string + a person EntityRef are present; otherwise derives `person_id`/`subject` from the first `entity_refs` entry and calls `memory.add_module_fact(person_id=..., subject=..., relation="interested_in", object=gift_item, category="gift_signal", source_ref=<message_id or dedup_key>, sensitivity="general")`, returning `ReactionResult(status="noted", ref=<fact_id>, undoable=True)`; (b) `register_comms_reactions` removes `del memory`, casts `memory` to `MemoryWritePath`, registers tool `reaction:gift_signal`, and appends a third `ReactionRule(name="reaction:gift_signal", event_type=EventType.EMAIL_INGESTED, tier=ReactionTier.B, external_effect=False, reaction_ref="reaction:gift_signal", dedup_key_fields=("message_id",))` to the returned tuple.
- [ ] Task 3: Write/extend write-path tests — files: tests/test_memory_write_path.py — done when: three tests pass — (i) `add_module_fact(category="gift_signal", sensitivity="general", ...)` persists a row whose recalled/`get_fact` Fact has `category=="gift_signal"` and `sensitivity=="general"`; (ii) a spy/`FakeExtractor` wired into the `MemoryWritePath` records ZERO `extract` calls after `add_module_fact`; (iii) `add_module_fact(...)` with NO `sensitivity` kwarg persists a row whose Fact has `sensitivity=="sensitive"`.
- [ ] Task 4: Write comms gift-reaction test — files: tests/test_reactions_comms.py — done when: a DomainEvent with `event_type=EMAIL_INGESTED`, `payload={"gift_signal_detected": True, "gift_item": "noise-cancelling headphones", "message_id": "m1"}`, and one person `EntityRef` drives `react_gift_signal` (with a fake `MemoryWritePath`) to call `add_module_fact` once with `category="gift_signal"`, `sensitivity="general"`, `relation="interested_in"`, `object="noise-cancelling headphones"`, and the result status is `"noted"`.

## Wave plan
Wave 1: [Task 1, Task 2] | Wave 2: [Task 3, Task 4]

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | (none) |
| Modify | src/artemis/memory/write_path.py, src/artemis/reactions/recipes/comms.py, tests/test_memory_write_path.py, tests/test_reactions_comms.py |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy` | Type-check the whole project (host re-verify). |
| `uv run ruff check . && uv run ruff format --check .` | Lint + format gate. |
| `uv run pytest -q` | Run the full test suite. |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | src/artemis/memory/write_path.py src/artemis/reactions/recipes/comms.py tests/test_memory_write_path.py tests/test_reactions_comms.py |
| `git commit` | "feat: R4 memory module-fact-push + register reaction:gift_signal (ADR-032 Decision 6)" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| (none) | — |

### Network
| Action | Purpose |
|--------|---------|
| (none) | No package installation. |

## Specialist Context
### Security
cross_model_review required (ADR-029 sensitivity wall; first non-owner, non-extractor writer to memory). Tested invariants:
- `add_module_fact` carries an EXPLICIT sensitivity; the default is fail-closed `"sensitive"` (no silent default-to-general). Only the gift recipe passes `"general"` (owner decision 2026-06-25, ADR-032 Decision 6).
- Every other (future) module-fact caller that omits sensitivity MUST land `"sensitive"` — covered by test (iii).
- The push does NOT invoke the LLM extractor/classifier — detection already happened in the reaction; re-extraction is forbidden — covered by test (ii).

### Performance
(none)

### Accessibility
(none — no frontend change)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | src/artemis/memory/write_path.py | Docstring on `add_module_fact` stating: structured push, no extractor, explicit sensitivity (fail-closed sensitive), source_ref→source_turn_id provenance. |
| Inline | src/artemis/reactions/recipes/comms.py | Update the module docstring's "gift-signal recipe intentionally not registered" note to reflect that it is now registered via `add_module_fact`. |
| ADR | (none) | ADR-032 already records the decision; no new ADR. |

## Acceptance Criteria
- [ ] `add_module_fact` persists a structured Fact with the caller's `category` + `sensitivity` → verify: test (i) reads back `category=="gift_signal"`, `sensitivity=="general"`.
- [ ] `add_module_fact` never runs the LLM extractor → verify: test (ii) — spy extractor `.extract` call count is 0 after the push.
- [ ] Module fact with no explicit sensitivity fails closed → verify: test (iii) reads back `sensitivity=="sensitive"`.
- [ ] `reaction:gift_signal` produces a general-tagged `category="gift_signal"` person fact → verify: test in tests/test_reactions_comms.py asserts the single `add_module_fact` call args (category/sensitivity/relation/object) and `status=="noted"`.
- [ ] `register_comms_reactions` returns a 3-rule tuple including `reaction:gift_signal` bound to `EMAIL_INGESTED`, tier B, `external_effect=False` → verify: assertion on the returned tuple in tests/test_reactions_comms.py.
- [ ] Whole-project gates green → verify: `uv run mypy` clean, `uv run ruff check . && uv run ruff format --check .` clean, `uv run pytest -q` passes.

## Progress
_(Coding mode writes here — do not edit manually)_
