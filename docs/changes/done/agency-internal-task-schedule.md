---
spec: agency-internal-task-schedule
status: ready
risk: high
coder: codex
coder_effort: high
cross_model_review: true
autonomy_level: L5
origin: design discussion 2026-06-28 (decision A, Option 2 due-date) — security-reviewed; build scoped to CORE (Tasks 1-5), digest-suggestion deferred to spec B.
---

# Spec: Agency v0 — internal task scheduling via due-date (no GATE, no calendar)

**Identity:** Switch on Artemis's first action-taking capability, scoped to ONE internal-reversible
action: **set a task's due date by accepting a suggestion**. Artemis may *propose* task suggestions;
the owner *accepts* one (providing a `due_at`) → a task is created/scheduled with that due date. No
Google Calendar, no `scheduled_block` time-blocking (that needs a schema change — deferred lever), no
GATE. "Never auto" is enforced structurally: the accept action is owner-only, never model-reachable.
→ why: `docs/findings/cluster-decisions/DECISIONS-LOG.md` § "Agency & Proactivity scope" (LOCKED 2026-06-28, Option B1 + Option 2 due-date).

## Grounding facts (verified in code 2026-06-28)
- `suggestion.accept(suggestion_id, project_id?, due_at?)` (`tools.py:152` `SuggestionAcceptArgs`) already
  creates a task from a suggestion with an optional `due_at`. **This is the "schedule" action** — reused
  as-is, NO new tool, NO schema change. It is productivity-store-only — it does NOT import or call the
  calendar client.
- `_task_tool_specs()` (`manifest.py:150-299`) unconditionally registers the full write surface
  (`tasks.cancel/complete/update/set_recurrence/assign_to_project`, `suggestion.accept/reject`) — all
  `ActionRisk.WRITE`. `tasks.cancel` is NOT reversible. (Security BLOCK-1.)
- The calendar-coupled `tasks.schedule` only exists when a `schedule_fn` is injected (`manifest.py:52`);
  absent without it. Stays OFF.
- `_register_modules` (`gateway.py:500-520`) registers ONLY the read-only `time` module today — no task
  tool is live. The reactive Brain dispatches any registered front-door tool directly (`brain.py:266`,
  no approval step) — so a WRITE tool in the registry = model can call it un-gated.

## Invariants (hard rules)
1. **No external effect reachable.** Nothing registered or wired here imports/calls the calendar client
   or any `schedule_fn`; `tasks_manifest` is registered WITHOUT `schedule_fn`. `due_at`/task writes stay
   in the owned productivity store.
2. **"Never auto" is structural.** The consequential writes — `suggestion.accept` (creates the task /
   sets `due_at`) and `suggestion.reject` — are **NOT in the reactive tool registry** the model selects
   from (`brain.py:266`). They are reachable ONLY via dedicated owner-authenticated brain routes invoked
   by the client. The model MAY call `suggestion.create` / `suggestion.list` / read tools (proposing &
   listing are inert). No model turn can accept/schedule.
3. **Owner-private scope.** Task store is owner-private (SQLCipher); tools gated on Hello-unlock — a
   locked vault degrades to 423/no-op, not a crash.

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| `src/artemis/modules/productivity/manifest.py` | modify | Add `include_write_surface: bool = False` to `tasks_manifest`/`_task_tool_specs`. When False: register ONLY `suggestion.create`, `suggestion.list`, and the read tools into the manifest's reactive tool list — EXCLUDE all `tasks.*` writes AND `suggestion.accept`/`suggestion.reject`. |
| `src/artemis/gateway.py` | modify | In `_register_modules`, register `tasks_manifest(store, include_write_surface=False)` so the owner task store is live; reachable only when owner-unlocked. |
| `src/artemis/api_app.py` | modify | Add two owner-authenticated routes behind `require_unlocked`: `POST /app/tasks/suggestion/accept` (body: suggestion_id, due_at?, project_id?) and `POST /app/tasks/suggestion/reject` (body: suggestion_id) — each calls the productivity store's accept/reject directly (NOT via the model/reactive dispatch). Carry `Depends(rate_limited)`. |
| `client/src-tauri/src/gateway.rs` | modify | Add `task_suggestion_accept` / `task_suggestion_reject` commands posting those routes. |
| `client/src-tauri/src/lib.rs` | modify | Register the two new commands in `generate_handler!`. |
| `client/src/api/gateway.ts` | modify | Add `acceptSuggestion(id, dueAt?)` / `rejectSuggestion(id)` transports. |
| `client/src/screens/TasksDetail.tsx` | modify | Wire the accept-suggestion (with a due-date input) + reject buttons to the new transports. **Guard/disable the external `calendar.schedule_task` button** (its command stays unregistered — finding C external half). |
| `tests/test_*` (Python) + client vitest | create/modify | Per Acceptance Criteria. |

## Tasks
- [ ] Task 1: `include_write_surface=False` gate — files: `src/artemis/modules/productivity/manifest.py` — done when: with the default (False), `tasks_manifest(store).tools` contains `suggestion.create`, `suggestion.list`, and read tools, and contains NONE of `tasks.cancel/complete/update/set_recurrence/assign_to_project`, `suggestion.accept`, `suggestion.reject`, `tasks.schedule`; with `include_write_surface=True` the prior full set is unchanged (back-compat). `uv run mypy` clean.
- [ ] Task 2: Register the task store live — files: `src/artemis/gateway.py` — done when: `_register_modules` registers `tasks_manifest(store, include_write_surface=False)` (no `schedule_fn`); a locked-vault path leaves the task tools degrading to 423/no-op (mirror the memory/retriever unlock gating); `uv run mypy` clean.
- [ ] Task 3: Owner-only accept/reject routes — files: `src/artemis/api_app.py` — done when: `POST /app/tasks/suggestion/accept` and `/reject` exist behind `require_unlocked` + `Depends(rate_limited)`, call the productivity store's accept/reject directly, return the created task / status, and import no calendar code; a test asserts accept with a `due_at` creates a task carrying that `due_at`, and that a locked vault returns 423.
- [ ] Task 4: Client wiring — files: `client/src-tauri/src/gateway.rs`, `client/src-tauri/src/lib.rs`, `client/src/api/gateway.ts`, `client/src/screens/TasksDetail.tsx` — done when: the accept (with due-date input) and reject buttons call the new commands; the external `calendar.schedule_task` button is disabled/guarded (no unregistered `invoke`); `cargo check` + `cargo test` + `tsc` + `vitest` + `npm run lint` green in `client`.
- [ ] Task 5: Tests / invariants — files: `tests/test_productivity_*.py` (+ a gateway registry test) — done when: a test asserts the live reactive registry from `_register_modules` exposes `suggestion.create`/`list` + read tools but NOT `suggestion.accept`/`reject` nor any `tasks.*` write (Invariant 2); accept sets `due_at` and touches no calendar (grep + behavioural); locked-vault no-op (Invariant 3). Full `uv run pytest -q` green.

## Wave plan
Wave 1: [Task 1] | Wave 2: [Task 2, Task 3] | Wave 3: [Task 4, Task 5]
(Task 2/3 both depend on Task 1's flag; Task 4 client + Task 5 tests depend on the routes.)

## Acceptance Criteria
- [ ] Live reactive registry (from `_register_modules`) exposes `suggestion.create`, `suggestion.list`, read tools — and NONE of `tasks.cancel/complete/update`, `tasks.schedule`, `suggestion.accept`, `suggestion.reject`. (Invariant 2 — assert on registered tool names.)
- [ ] `POST /app/tasks/suggestion/accept` with a `due_at` creates a task carrying that `due_at`; no calendar import on the path (grep + test).
- [ ] Locked vault → task tools + the accept/reject routes return 423/no-op, no crash. (Invariant 3.)
- [ ] External `calendar.schedule_task` button invokes no unregistered command (guarded). (Finding C external half.)
- [ ] Host re-verify: full `uv run mypy` + `uv run pytest -q` green; client `cargo check`/`cargo test`/`tsc`/`vitest`/`npm run lint` green.

## Deferred (not this build)
- **Task: suggest-during-digest** (Artemis proposes suggestions proactively) → folded into spec
  `proactive-heartbeat-module-wiring` (B); requires FLAG-4 sanitization of externally-sourced suggestion
  fields (truncate/strip) before a real source feeds `suggestion.create`.
- **Time-block scheduling** (`scheduled_block`) → needs a suggestions-schema extension; deferred lever.

## Permissions
### File Operations
| Action | Paths |
|--------|-------|
| Modify | `src/artemis/modules/productivity/manifest.py`, `src/artemis/gateway.py`, `src/artemis/api_app.py`, `client/src-tauri/src/gateway.rs`, `client/src-tauri/src/lib.rs`, `client/src/api/gateway.ts`, `client/src/screens/TasksDetail.tsx` |
| Create | `tests/` Python tests + client vitest as needed |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run --no-sync mypy` / `uv run --no-sync pytest -q` | Host verify (use `--no-sync` if a live brain holds artemis-brain.exe). |
| `cargo check` / `cargo test` / `tsc` / `vitest` / `npm run lint` (in `client`) | Client verify. |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` (by name) + `git commit` | "feat(agency): internal task scheduling via due-date (suggest/accept, no GATE)" |

## Security Context (folded from review 2026-06-28)
- BLOCK-1 → `include_write_surface=False` keeps the irreversible writes (`tasks.cancel` etc.) off the
  live path. BLOCK-2 → resolved by Invariant 2 (accept/reject owner-route-only, never model-reachable).
- FLAG-3 → the accept/reject routes import no calendar code; `tasks_manifest` registered without
  `schedule_fn`. FLAG-4 → suggestion-field sanitization travels with the deferred digest task (no
  external suggestion source in this build). Hello-unlock no-op is an explicit acceptance criterion.

## Progress
_(Coding mode writes here — do not edit manually)_

### 2026-06-28 — built by Codex (gpt-5.5, high effort), host-verified + cross-model reviewed
- [x] Task 1 — `include_write_surface=False` filters `tasks_manifest` to `suggestion.create`/`suggestion.list` + read tools only (no write surface, no accept/reject). `True` preserves the full set.
- [x] Task 2 — `_register_modules` registers `tasks_manifest(store, include_write_surface=False)` without `schedule_fn`; Hello-unlock no-op preserved.
- [x] Task 3 — owner routes `POST /app/tasks/suggestion/accept` (sets `due_at`, `scheduled_block` null, 404 on unknown) + `/reject` (idempotent) behind `require_unlocked` + `rate_limited`; no calendar import.
- [x] Task 4 — Tauri commands `task_suggestion_accept`/`reject` + TS transports + `screens/TasksDetail.tsx` accept(due-date)/reject wiring; external time-block button disabled.
- [x] Task 5 — registry-invariant test (accept/reject/writes absent from reactive index), accept-due_at, locked-423, client tests.

**Deviations / notes:** spec path `world/TasksDetail.tsx` was wrong → real path `screens/TasksDetail.tsx` (Codex adapted; spec corrected). Codex's sandbox blocked vitest → host fixed 1 test bug (React native value-setter) + ran vitest (84). Cross-model (Opus) review = PASS-WITH-FLAGS: FLAG-2 `suggestion.list`→READ applied (rippled `test_productivity_core` counts 9/13→10/12); FLAG-1 (reject→500) was a review misread — `reject_suggestion` is an idempotent no-op, reverted speculative handler; FLAG-3 (`complete`/`reschedule` dead buttons) = pre-existing finding C, deferred to `client-detail-action-wiring`.

**Host verify:** full mypy clean (343) · targeted pytest 48 · vitest 84 · eslint · cargo check/test · full pytest (final-state run in progress at write time).
