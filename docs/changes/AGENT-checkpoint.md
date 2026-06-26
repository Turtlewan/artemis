---
spec: AGENT-checkpoint
status: ready
cross_model_review: true
token_profile: balanced
autonomy_level: L2
---

# Spec: AGENT-checkpoint — owner-private SQLite checkpoint / resume store

**Identity:** Concrete `CheckpointStore` for the executor: one owner-private row per `task_id`
(state + plan + step index + last-verified-output) enabling resume across sessions (ADR-031 D/F).
<!-- → why: docs/technical/adr/ADR-031-...md (D engine checkpoint, F reliability) + docs/drafts/AGENT-engine-design.md (seam #2). -->

## Assumptions
<!-- Coding mode verifies each item against the codebase before executing. -->
- The `CheckpointStore` Protocol + `CheckpointRow`/`Plan`/`ExecutorState` types come from `artemis.agentic.types` (AGENT-types) — declare it a Prerequisite; import, do not redefine. → impact: Stop.
- Owner-private SQLCipher construction mirrors `ReactionLedger` (`src/artemis/reactions/ledger.py`): `Settings` + `KeyProvider`, `sqlcipher_open(db_path, key.as_hex())` via `artemis.data.sqlcipher`, `paths.scope_dir(settings, OWNER_PRIVATE)`. Verify the exact ctor + `_connect`/`_db_path` pattern and copy it. → impact: Stop (a different construction breaks the privacy-wall convention).
- Dev uses the plain-sqlite shim (`artemis.data.sqlcipher.sqlcipher_open`) — no real encryption until Mac; same as every owner-private store today. → impact: Low.
- Timestamps (if any) use `artemis.memory.schema.now_iso` (UTC ISO, the shared function) for lexicographic ordering parity. → impact: Caution.
- The `Plan` is persisted as JSON (`Plan.model_dump_json()` / `Plan.model_validate_json`); `state` stores the `ExecutorState` value. → impact: Stop (storing the model object, not JSON, breaks the SQLite write).

Simplicity check: considered a generic key-value blob store — rejected: a typed one-row-per-task schema with explicit columns (`state`, `step_index`, `last_verified_output`) makes resume queries and the read-back contract explicit; the plan is the only JSON blob. Minimal and legible.

## Prerequisites
- Specs that must be complete first: **AGENT-types** (Protocol + row types).
- Environment setup required: none (existing toolchain; no new deps).

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| `src/artemis/agentic/checkpoint.py` | create | `SqliteCheckpointStore` implementing `CheckpointStore`; owner-private SQLCipher; `save`/`load`. |
| `tests/test_agent_checkpoint.py` | create | round-trip, unknown-task→None, resume-after-reconstruct, owner-private path. |

- Table `agent_checkpoint(task_id TEXT PRIMARY KEY, state TEXT NOT NULL, plan_json TEXT NOT NULL, step_index INTEGER NOT NULL, last_verified_output TEXT)`.
- `save(task_id, state, plan, step_index, last_verified_output)` = `INSERT OR REPLACE` (`state=state.value`, `plan_json=plan.model_dump_json()`).
- `load(task_id) -> CheckpointRow | None` = `SELECT *` → `CheckpointRow(task_id=…, state=ExecutorState(row["state"]), plan=Plan.model_validate_json(row["plan_json"]), step_index=…, last_verified_output=…)` or `None`.
- **Parameterised SQL only (BLOCK):** every statement uses DB-API `?` bound parameters — f-string/`%` interpolation of `task_id`/`plan_json`/`step_index`/`last_verified_output` is prohibited (`task_id` traces to `Task.goal`, `last_verified_output` is adversarial-capable tool output).
- **No content logging (FLAG):** `save()`/`load()` must NOT log or print `plan_json` or `last_verified_output` at any level (they carry owner-task goal text + tool stdout).
- **Corrupted-row fails clean (FLAG):** if `Plan.model_validate_json` raises `ValidationError`, `load()` raises `CheckpointCorruptedError(task_id)` (message = task_id only, NO pydantic field detail) and logs the raw error at WARNING internally — never propagates pydantic schema detail upward.
- Construction + `_connect()` + `_db_path()` copied from `ReactionLedger`; DB filename `agent_checkpoint.db` under `scope_dir(settings, OWNER_PRIVATE)/agentic/`.

## Tasks
- [ ] Task 1: Implement `SqliteCheckpointStore` per Exact changes (mirror `ReactionLedger` construction). — files: `src/artemis/agentic/checkpoint.py` — done when: `save` then `load` round-trips `state`/`plan`/`step_index`/`last_verified_output`; `load("missing")` is `None`; a freshly-reconstructed store `load`s a previously-saved task (durability); `uv run mypy` clean.
- [ ] Task 2: Tests. — files: `tests/test_agent_checkpoint.py` — done when: round-trip, None-on-missing, durability-across-reconstruct, owner-private-path, **locked-scope-raises (degrades closed, no fallback open)**, **no-content-in-logs (caplog: no plan_json/last_verified_output)**, and **corrupted-plan_json → CheckpointCorruptedError (task_id only, no pydantic detail)** assertions pass under `uv run pytest -q`.

## Wave plan
Wave 1: [Task 1] | Wave 2: [Task 2]

## Permissions
The following actions will run autonomously during build. Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | `src/artemis/agentic/checkpoint.py`, `tests/test_agent_checkpoint.py` |
| Modify | (none) |
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
| `git add` | The two files above, by name. |
| `git commit` | "feat: AGENT-checkpoint owner-private SQLite checkpoint/resume store (ADR-031)" |

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
`cross_model_review: true` — owner-private task-state persistence. Reviewer confirms: (1) the store is owner-private SQLCipher under the OWNER_PRIVATE scope dir (same construction as ReactionLedger), never a general/cloud path; (2) plan/output content lives only in that owner-private DB; (3) the scope-locked provider degrades closed (a locked scope raises, mirroring the ledger).

### Performance
(none — single-row PK upsert/lookup.)

### Accessibility
(none — no frontend change.)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | `src/artemis/agentic/checkpoint.py` | Docstring: owner-private, one-row-per-task, resume contract. |
| Reconcile | docs/technical/architecture/data-model.md | Add the owner-private `agent_checkpoint` table (conceptual). |

## Acceptance Criteria
- [ ] Round-trip → verify: `save` then `load` returns equal state/plan/step_index/last_verified_output.
- [ ] Unknown task → verify: `load("missing")` is `None`.
- [ ] Durable resume → verify: reconstructing the store and calling `load` returns the prior row.
- [ ] Owner-private → verify: the DB sits under the OWNER_PRIVATE scope dir; locked scope degrades closed.
- [ ] Whole project clean → verify: `uv run mypy`, `uv run ruff check . && uv run ruff format --check .`, `uv run pytest -q` all pass.

## Progress
_(Coding mode writes here — do not edit manually)_
