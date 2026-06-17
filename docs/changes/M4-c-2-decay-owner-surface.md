<!-- amended 2026-06-11 per contracts.md (Seam 6) + m3-m4-knowledge-memory.md BLOCK B4 · split from M4-c 2026-06-11 (owner decision) -->
<!-- amended 2026-06-17: EmbeddingModel port split embed→embed_documents/embed_query (embedding-layer decision; research/2026-06-17-embedding-implementation.md) -->
---
spec: m4-c-2-decay-owner-surface
status: ready
token_profile: balanced
autonomy_level: L2
---

# Spec: M4-c-2 — Decay tombstone sweep (demote-below-floor, never-hard-delete) + owner view/edit/delete/purge surface with provenance

**Identity:** Completes the memory engine's WRITE-CONTROL/forgetting path on top of M4-a/M4-b and M4-c-1: the decay tombstone sweep (`sweep_tombstone_candidates` — demote-below-threshold candidates, **never hard-delete**) and the owner view/edit (= bitemporal UPDATE) / delete (tombstone) / explicit-purge surface with provenance. Schema/repository = M4-a; write-path decisioning = M4-b; the decay scorer + inject/recall path = M4-c-1.
→ why: see docs/technical/adr/ADR-004-memory-engine.md (decay never-hard-delete, owner true-purge separate; owner view/edit=UPDATE/delete=tombstone with provenance) · docs/technical/architecture/brain.md § Memory (forgetting/decay; owner control) · docs/research/memory-engine-research.md (owner-edit human-in-the-loop).

<!-- A spec is an EXECUTION SCRIPT, not a design doc. DeepSeek executes literally. -->

## Assumptions
- **M4-c-1 complete first** (the dependency edge for this split): `memory/decay.py` exists carrying `decay_score`, `rank_for_inject`, `recall_multiplier`, and the constants `HALF_LIFE_DAYS`/`INJECT_THRESHOLD`. M4-c-2 ADDS `sweep_tombstone_candidates` + `TOMBSTONE_FLOOR` to that file (distinct symbols; no edit to M4-c-1's functions). M4-c-2 reuses `decay_score` from M4-c-1 inside the sweep. → impact: Stop (the sweep is computed with M4-c-1's `decay_score`; this spec must not redefine it).
- M4-a + M4-b complete: `memory/repository.py` `BitemporalRepository` (`as_of`, `history`, `update`, `tombstone`, `purge`, `semantic_candidates`, `FactRow` carrying `salience`/`access_count`/`last_access`/`valid_from`/`confidence`/provenance fields `source_turn_id`/`extracted_at`/`extractor_model`); M0-d `MemoryStore`/`Fact`/`AsOf`/`PersonId`/`Scope`; the M4-a `EmbeddingModel` embedder port (owner-edit re-embeds the new triple). → impact: Stop (owner edit/delete/purge call the M4-a repo primitives; the sweep reads `FactRow` decay inputs).
- **Decay tombstone floor:** facts whose decay score (M4-c-1's `decay_score`) falls far below the inject threshold are candidates for tombstone by an on-demand sweep — but **never hard-deleted**. → impact: Caution. [RESOLVED — drafted default `tombstone_floor = 0.02` as a config-tunable constant; does NOT change the code shape, only the constant. Tuned alongside M4-c-1's GATED decay sweep if traces warrant; code-shape unchanged.]
- **Owner control** (ADR-004): the owner can view a fact's full history + provenance, edit it (= a bitemporal `repo.update` — a NEW version, auditable, the old version preserved), delete it (tombstone), or **explicitly purge** it (the ONLY hard-delete path — a separate, explicit owner action that removes the version rows + vec/fts rows for a `fact_key`, distinct from tombstone). Owner edit is **human-in-the-loop** (the research-required mitigation) — the surface returns the current fact + asks the owner to confirm the new value; no automatic owner-edit. → impact: Stop (view/edit/delete/purge with provenance; purge is the only hard-delete and is explicit; edit is human-in-the-loop).
- The owner surface is a **Python API on the memory package** (functions/class methods), NOT an HTTP/UI surface (no frontend in M4; the app surface is a later milestone). It is callable from a future owner UI / a CLI. → impact: Low (M4-c-2 ships the callable surface + tests; the UI wiring is deferred).
- Off-hardware: everything is deterministic (FakeEmbedder, the M4-a DB fixture). → impact: Caution.

Simplicity check: considered a background decay daemon — rejected for M4: decay is computed lazily at inject time (M4-c-1) + a simple on-demand `sweep_tombstone_candidates` the owner/maintenance can call; a scheduled sweep is a later concern. Considered making owner-edit automatic — rejected: research requires human-in-the-loop. This is the minimum that satisfies the decay forgetting sweep + owner-control.

## Prerequisites
- Specs that must be complete first: **M4-c-1** (the `decay.py` scorer + the inject/recall path — this split's dependency edge), **M4-a** (repository/store/`FactRow`/`update`/`tombstone`/`purge`), **M0-d** (`MemoryStore`/`Fact`/`AsOf`/`PersonId`).
- Environment setup required: none new off-hardware. Off-hardware tests use the M4-a DB fixture + `FakeEmbedder`.

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| /Users/artemis-build/artemis/src/artemis/memory/decay.py | modify | ADD `TOMBSTONE_FLOOR = 0.02` + `sweep_tombstone_candidates` (the never-hard-delete demotion logic). **(M4-c-1 created this file with `decay_score`/`rank_for_inject`/`recall_multiplier` — M4-c-2 only adds the sweep symbols, reusing `decay_score`.)** |
| /Users/artemis-build/artemis/src/artemis/memory/owner.py | create | `OwnerMemory` surface: `list_current`/`view_fact`/`history`/`edit_fact` (human-in-loop UPDATE) / `delete_fact` (tombstone) / `purge_fact` (the only hard-delete, explicit) — all with provenance; `OwnerConfirmationRequired(Exception)` |
| /Users/artemis-build/artemis/src/artemis/memory/__init__.py | modify | re-export `OwnerMemory`, `OwnerConfirmationRequired`, `sweep_tombstone_candidates`. **(M4-c-1 added the `decay_score`/`render_inject_block` re-exports — M4-c-2 only adds the owner/sweep symbols.)** |
| /Users/artemis-build/artemis/tests/test_memory_owner_decay.py | create | tombstone-sweep (sub-floor flagged, never-hard-delete), owner view/edit/delete/purge with provenance |

## Tasks
- [ ] Task 1: Add the tombstone sweep to the decay module — files: `/Users/artemis-build/artemis/src/artemis/memory/decay.py` (modify) — add module constant `TOMBSTONE_FLOOR = 0.02` (config-tunable; drafted default). `def sweep_tombstone_candidates(rows: Sequence[FactRow], *, now: str, floor: float = TOMBSTONE_FLOOR) -> list[str]`: score each row with M4-c-1's `decay_score`, return `fact_key`s whose score `< floor` (candidates to DEMOTE via tombstone — **the caller tombstones, never hard-deletes**; document that this only returns candidates, no DB writes). Pure function, no DB. Re-export `sweep_tombstone_candidates` from `memory/__init__.py`. — done when: `uv run mypy --strict src` passes; `sweep_tombstone_candidates` flags only sub-floor facts and performs no deletion. Acceptance command: `uv run pytest -q tests/test_memory_owner_decay.py -k "sweep or tombstone_candidate"`.

- [ ] Task 2: Implement the owner view/edit/delete/purge surface — files: `/Users/artemis-build/artemis/src/artemis/memory/owner.py` (create) (+ re-export from `memory/__init__.py`) — `class OwnerMemory` constructed with `(repo: BitemporalRepository, embedder: EmbeddingModel)`. Methods:
  - `def list_current(self, *, limit: int = 100) -> list[FactRow]`: current (`as_of=now`) facts with their provenance (`source_turn_id`, `extracted_at`, `extractor_model`, `confidence`) for the owner to review.
  - `def view_fact(self, fact_key: str) -> FactRow`: the current version of a fact + its provenance.
  - `def history(self, fact_key: str) -> list[FactRow]`: ALL versions (the bitemporal audit trail — what was believed when).
  - `async def edit_fact(self, fact_key: str, new_object: str, *, confirm: bool, new_confidence: float = 1.0, salience: float = 2.0) -> str` (ASYNC — embeds the new STORED triple via the async `EmbeddingModel.embed_documents`): **human-in-the-loop** — REQUIRE `confirm is True` else raise `OwnerConfirmationRequired` (the research-required safety net; an owner UI calls `view_fact` first, then `await edit_fact(confirm=True)`); on confirm, `embedding = (await self.embedder.embed_documents([f"{...} {new_object}"]))[0]` (the edited triple is STORED text → `embed_documents`, NO query prefix; await the async port) and call `repo.update(fact_key, new_object, new_confidence, embedding, source_turn_id="owner-edit", extractor_model="owner")` (SYNC local-DB write — not awaited; an auditable bitemporal UPDATE; the prior version preserved; salience boosted so owner-stated facts persist). Returns the new `fact_id`.
  - `def delete_fact(self, fact_key: str) -> None` (STAYS SYNC — `repo.tombstone` maps to the M4-a sync `delete_fact`/tombstone; no embed, no await): `repo.tombstone(fact_key)` (soft delete — history preserved; the default owner-delete).
  - `def purge_fact(self, fact_key: str, *, confirm: bool) -> int` (STAYS SYNC — no embed): the **ONLY hard-delete** — REQUIRE `confirm is True` else raise `OwnerConfirmationRequired`; permanently remove ALL version rows + the `facts_vec`/`facts_fts` rows for the `fact_key` (the ADR-004 "owner-driven true purge is a separate explicit action") by CALLING `repo.purge(fact_key) -> int` (SYNC; DEFINED in M4-a's repository.py — the only hard-delete primitive in the codebase, irreversible + owner-only; M4-c-2 only calls it). Returns rows removed.
  Define `OwnerConfirmationRequired(Exception)`. — done when: `uv run mypy --strict src` passes; `await edit_fact(confirm=False)` raises (the confirm guard runs before the embed/await); `await edit_fact(confirm=True)` produces an auditable new version (old preserved); `delete_fact` (sync) tombstones (history survives); `purge_fact(confirm=True)` (sync) removes all rows for the key; `purge_fact(confirm=False)` raises. Acceptance command: `uv run pytest -q tests/test_memory_owner_decay.py -k "owner or edit or delete or purge"`.

- [ ] Task 3: Write the decay-sweep + owner tests — files: `/Users/artemis-build/artemis/tests/test_memory_owner_decay.py` — typed pytest using the M4-a DB fixture + `FakeEmbedder` (implements BOTH `async def embed_documents` and `async def embed_query` per the split port — `edit_fact` calls `embed_documents`). The owner-edit test is an `async def` test fn under `@pytest.mark.asyncio` and `await`s `edit_fact` (async-port cascade); the sweep + delete/purge/list/view/history assertions stay sync:
  - tombstone sweep: `sweep_tombstone_candidates` flags only facts whose `decay_score` is below `TOMBSTONE_FLOOR`; a healthy fact is NOT flagged; the function performs NO deletion (rows unchanged after calling it — never-hard-delete).
  - owner edit (human-in-loop): `await edit_fact(confirm=False)` raises `OwnerConfirmationRequired`; `await edit_fact(confirm=True, new_object="London")` → `view_fact` shows London, `history` has the prior Paris version (auditable, preserved), provenance `extractor_model=="owner"`.
  - owner list/view/history: `list_current` returns current facts with provenance fields populated; `view_fact` returns the current version; `history` returns all versions in order.
  - owner delete vs purge: `delete_fact` → `view_fact`/`as_of(now)` empty but `history` non-empty (soft); `purge_fact(confirm=True)` → `history` empty + `facts_vec`/`facts_fts` rows gone (the only hard-delete); `purge_fact(confirm=False)` raises.
  — done when: `uv run pytest -q` passes AND `uv run mypy --strict src tests/test_memory_owner_decay.py` passes. Acceptance command: `uv run pytest -q tests/test_memory_owner_decay.py`.

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | /Users/artemis-build/artemis/src/artemis/memory/owner.py, /Users/artemis-build/artemis/tests/test_memory_owner_decay.py |
| Modify | /Users/artemis-build/artemis/src/artemis/memory/decay.py, /Users/artemis-build/artemis/src/artemis/memory/__init__.py |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict src tests/test_memory_owner_decay.py` | Type gate |
| `uv run ruff check . ; uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q` | Test gate (fakes + M4-a DB fixture) |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | src/artemis/memory/decay.py, src/artemis/memory/owner.py, src/artemis/memory/__init__.py, tests/test_memory_owner_decay.py |
| `git commit` | "feat: M4-c-2 decay tombstone sweep (never-hard-delete) + owner view/edit/delete/purge surface" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_ENV_FILE` | Slot Settings (embedder role, paths) |

### Network
| Action | Purpose |
|--------|---------|
| (none off-hardware) | Sweep + owner surface are local |

## Specialist Context
### Security
**never-hard-delete** is preserved everywhere EXCEPT the explicit, confirm-gated owner `purge_fact` (the single, documented, irreversible hard-delete) — every other "delete" is a tombstone with history intact; the tombstone sweep only returns CANDIDATES (no writes). Owner-edit is human-in-the-loop (confirm-gated). [FLAG for apex-security (M4 gate): confirm `purge_fact` is the only hard-delete and is confirm-gated; confirm `edit_fact` is confirm-gated; confirm the sweep performs no deletion; review the owner-edit provenance (`extractor_model="owner"`) so owner-stated facts are distinguishable from extracted ones.]

### Performance
The tombstone sweep is **on-demand** (no scheduler, no background daemon in M4) — O(current facts), called by the owner/maintenance, not per turn. Owner edit/delete/purge are single bitemporal operations on the M4-a repo. The tombstone floor is the only empirical knob (tuned alongside M4-c-1's decay sweep if traces warrant).

### Accessibility
(none — the owner surface is a Python API; the eventual owner-memory UI is a later milestone and inherits apex-accessibility then)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | src/artemis/memory/decay.py, owner.py | Type + docstring all exports; document the never-hard-delete rule + the tombstone-floor constant, owner edit=UPDATE (auditable, human-in-loop) / delete=tombstone / purge=the only hard-delete (explicit, confirm-gated) |

## Acceptance Criteria
- [ ] Run `uv run mypy --strict src tests/test_memory_owner_decay.py` → verify: exit 0.
- [ ] Run `uv run pytest -q tests/test_memory_owner_decay.py` → verify: tombstone sweep (sub-floor flagged, no deletion), owner edit human-in-loop (confirm gate + auditable history), list/view/history with provenance, delete=tombstone vs purge=hard-delete (confirm gate) all pass.
- [ ] Run `uv run python -c "from artemis.memory import OwnerMemory, OwnerConfirmationRequired; from artemis.memory.decay import sweep_tombstone_candidates; print('ok')"` → verify: prints `ok`.
- [ ] Run `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.

## Progress
_(Coding mode writes here — do not edit manually)_
