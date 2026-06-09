---
spec: m7-a3-dedupe-retire
status: ready
token_profile: balanced
autonomy_level: L2
---

# Spec: M7-a3 — Rule-based recipe dedupe/retire (no LLM at library time)

**Identity:** Implements rule-based dedupe/retire over the recipe store — exact-dupe, near-dupe (cosine over embedded descriptions), and superseded-version rules — setting losers to `RETIRED`. NO LLM at library time (brain.md). Operates on M7-a1's `RecipeStore` + `RecipeIndex`.
→ why: see docs/technical/architecture/brain.md § "Self-improvement" (rule-based dedupe/retire, no LLM at library time).

<!-- TERMINOLOGY: "recipe" not "skill". Sub-split of former M7-a (gate 2026-06-08): a3 = dedupe/retire. -->

## Assumptions
- **M7-a1 complete**: `Recipe`, `RecipeStatus`, `ActionClass`, `RecipeStore` (`list`/`set_status`), and the cosine `RecipeIndex` exist. → impact: Stop (M7-a3 only reads stored metadata + the index and flips `status` to `RETIRED`).
- Dedupe is **pure rules over stored metadata + the cosine index — never a model call** (brain.md "rule-based dedupe/retire, no LLM at library time"). → impact: Stop.

Simplicity check: considered an LLM to judge duplicates — rejected (brain.md locks rule-based library-time). Considered retiring by recency alone — rejected; three explicit rules (exact / near / superseded) with a deterministic tiebreaker are the minimum that is reproducible.

## Prerequisites
- Specs that must be complete first: **M7-a1** (`RecipeStore`/`RecipeIndex`/`Recipe`/`RecipeStatus`).
- Environment setup required: none beyond M7-a1. Fully deterministic; no on-hardware gate (no model calls).

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| /Users/artemis-build/artemis/src/artemis/recipes/dedupe.py | create | `dedupe_retire(store, *, similarity_threshold=0.92) -> list[str]` (exact/near/superseded rules + deterministic tiebreaker) |
| /Users/artemis-build/artemis/src/artemis/recipes/__init__.py | modify | re-export `dedupe_retire` + extend `__all__` |
| /Users/artemis-build/artemis/tests/test_recipes_dedupe.py | create | exact-dupe, near-dupe, superseded, deterministic tiebreaker |

## Tasks
- [ ] Task 1: Implement rule-based dedupe/retire — files: `/Users/artemis-build/artemis/src/artemis/recipes/dedupe.py` — `def dedupe_retire(store: RecipeStore, *, similarity_threshold: float = 0.92) -> list[str]` (NO LLM):
  - **exact-dupe:** two recipes with the same `task_class_key` AND identical canonical instructions → retire the lower-version/older.
  - **near-dupe:** two ENABLED recipes whose embedded descriptions have cosine ≥ `similarity_threshold` AND the same `action_class` → retire the one with the older `provenance["verified_at"]`.
  - **superseded:** a recipe with the same `task_class_key` but a higher `version` retires the lower.
  - **Deterministic tiebreaker (required):** when the retire-selection criterion ties (e.g. equal `verified_at`), break by `(lower version string, then lower name lexicographically)` so the outcome never depends on `store.list()` iteration order.
  - Returns the list of retired recipe names. Pure rules over stored metadata + the cosine index — never a model call. — done when: `uv run mypy --strict src` passes; given two recipes sharing a `task_class_key`, exactly one ends `RETIRED` and the other stays; two recipes with equal `verified_at` retire deterministically (same result across runs).

- [ ] Task 2: Re-export — files: `/Users/artemis-build/artemis/src/artemis/recipes/__init__.py` — add `dedupe_retire` to the re-exports + `__all__`. — done when: `uv run python -c "from artemis.recipes import dedupe_retire"` exits 0.

- [ ] Task 3: Write the dedupe tests (off-hardware, fakes) — files: `/Users/artemis-build/artemis/tests/test_recipes_dedupe.py` — typed pytest reusing the M7-a1 `FakeEmbedder` + `FakeKeyProvider`, a real `RecipeStore` over `tmp_path`:
  - exact-dupe: two recipes sharing `task_class_key` + identical instructions → exactly one `RETIRED`, the survivor non-RETIRED.
  - near-dupe: two ENABLED recipes with near-identical descriptions (cosine ≥ threshold via the deterministic `FakeEmbedder`) + same `action_class` → the older-`verified_at` one is RETIRED.
  - superseded: same `task_class_key`, `version` `0.2.0` retires `0.1.0`.
  - deterministic tiebreaker: two recipes with equal `verified_at` → the SAME one is retired across repeated runs (and regardless of insertion order).
  — done when: `uv run pytest -q tests/test_recipes_dedupe.py` passes AND `uv run mypy --strict src tests/test_recipes_dedupe.py` passes.

## Permissions
The following actions will run autonomously during build. Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | /Users/artemis-build/artemis/src/artemis/recipes/dedupe.py, /Users/artemis-build/artemis/tests/test_recipes_dedupe.py |
| Modify | /Users/artemis-build/artemis/src/artemis/recipes/__init__.py |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict src tests/test_recipes_dedupe.py` | Type gate |
| `uv run ruff check . ; uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q tests/test_recipes_dedupe.py` | Test gate |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | src/artemis/recipes/dedupe.py, src/artemis/recipes/__init__.py, tests/test_recipes_dedupe.py |
| `git commit` | "feat: M7-a3 rule-based recipe dedupe/retire (exact/near/superseded + deterministic tiebreaker)" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_ENV_FILE` | Slot Settings → recipes_dir resolution |

### Network
| Action | Purpose |
|--------|---------|
| (none) | Pure rules — no model, no network |

## Specialist Context
### Security
Dedupe/retire is rule-based (zero LLM at library time) — no poisoning surface via a model call. Retiring a recipe only ever RESTRICTS what RAG-for-recipes returns (RETIRED recipes are excluded from the ENABLED-scoped retrieve).

### Performance
Rule-based over stored metadata + the existing cosine index — negligible cost; no model call.

### Accessibility
(none — no frontend)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | src/artemis/recipes/dedupe.py | Type + docstring all exports; document the three rules + the deterministic tiebreaker |

## Acceptance Criteria
- [ ] Run `uv run mypy --strict src tests/test_recipes_dedupe.py` → verify: exit 0.
- [ ] Run `uv run pytest -q tests/test_recipes_dedupe.py` → verify: exact/near/superseded each retire exactly the intended recipe; the equal-`verified_at` tiebreaker is deterministic across runs.
- [ ] Run `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.

## Progress
_(Coding mode writes here — do not edit manually)_
