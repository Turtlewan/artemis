---
spec: agency-internal-task-schedule
status: draft
risk: high
coder: codex
coder_effort: high
cross_model_review: true
autonomy_level: L5
origin: design discussion 2026-06-28 (decision A) — coding-mode-authored, NEEDS the security review folded + a planning confirm before build
---

# Spec (DRAFT): Agency v0 — internal task scheduling (no GATE, no calendar)

**Identity:** Switch on Artemis's first action-taking capability, scoped to ONE internal-reversible
action: schedule a task into a time slot in its **own owned productivity store** (`scheduled_block`),
never touching Google Calendar. Suggest/ask-driven, never silent-auto. This is the minimal "agency"
slice; the GATE, the agentic executor, and all external-effect actions stay deferred levers.
→ why: `docs/findings/cluster-decisions/DECISIONS-LOG.md` § "Agency & Proactivity scope" (LOCKED 2026-06-28).

## The grounding facts (verified in code 2026-06-28)
- Task schema (`modules/productivity/schema.py`) has **separate** fields: `scheduled_block TEXT`
  (the internal time block) and `calendar_event_id TEXT` (the external Google link). Internal-only
  scheduling sets `scheduled_block` and leaves `calendar_event_id` **null**.
- The built `tasks.schedule` tool (`modules/productivity/manifest.py:211`, `tools.task_schedule`)
  is **calendar-coupled**: it only exists when a `schedule_fn` (from `calendar/schedule_task.py`,
  returns an `event_id`) is injected, and it creates a real calendar block. **This tool stays OFF.**
- The `suggestion.{create,list,accept,reject}` tools (`manifest.py:253-281`) are already **internal**
  (owned store only).
- `_register_modules` (`gateway.py:500-520`) currently registers ONLY the read-only `time` module —
  so NO task tool is live today.

## Why no GATE (the safety argument — security review must confirm)
Setting `scheduled_block` on an owned-store task is **internal-reversible** (no external system is
mutated; the owner can re-schedule/clear freely). By the owner autonomy boundary (internal auto /
external gated, per the owner-rules capture + ADR-022), internal-reversible actions do not require the
action-staging GATE. The GATE remains uncomposed and is NOT needed here **provided** the registered
tools cannot transitively cause an external effect — see Invariant 1.

## Invariants (the spec's hard rules)
1. **No external effect reachable.** The task tools registered into the live path must NOT create a
   calendar event or call any `schedule_fn`. Concretely: `tasks_manifest` is registered **without**
   `schedule_fn` (so the calendar-coupled `tasks.schedule` is absent), and the new internal schedule
   tool writes `scheduled_block` only, never `calendar_event_id`, never the calendar client.
2. **Never silent-auto.** Artemis schedules only (a) on an explicit owner ask, or (b) when the owner
   accepts a proposed suggestion. No code path schedules a task without one of those two triggers.
3. **Owner-private scope.** The task store is owner-private (SQLCipher); the tools are gated on
   Hello-unlock like memory/retriever — a locked vault degrades to no-op, not a crash.

## Files to change (provisional — confirm in planning + after security review)
| File | Operation | Notes |
|------|-----------|-------|
| `src/artemis/modules/productivity/tools.py` | modify | Add an internal-only `schedule_block` tool fn: set `scheduled_block` on a task, `calendar_event_id` untouched. No calendar import. |
| `src/artemis/modules/productivity/manifest.py` | modify | Expose the internal schedule tool in `tasks_manifest` independent of `schedule_fn`; keep the calendar-coupled `tasks.schedule` behind `schedule_fn` (absent here). |
| `src/artemis/gateway.py` | modify | Register `tasks_manifest` (NO `schedule_fn`) into `_register_modules` so the internal task + suggestion tools are live. |
| `src/artemis/...heartbeat/digest` | modify | Morning-digest may emit a schedule **suggestion** for an unscheduled task (ties to the proactive-heartbeat-module-wiring spec B). Suggestion only — no scheduling. |
| `client/src/world/TasksDetail.tsx` (+ Tauri command + brain route) | modify | Wire the internal reschedule/accept-suggestion buttons (finding C internal half); the external `calendar.schedule_task` button stays guarded. |
| tests | create/modify | Internal-schedule sets `scheduled_block` only; calendar_event_id stays null; no calendar client touched; suggest→accept flow; locked-vault no-op. |

## Tasks (B1 — provisional, pending planning confirm)
- [ ] Task 1: Add `include_write_surface: bool = False` to `tasks_manifest`/`_task_tool_specs`; when False, expose ONLY `suggestion.*` + read tools (no schedule, cancel, complete, update). (BLOCK-1)
- [ ] Task 2: `suggestion.accept` handler performs the internal `scheduled_block` write in-process — assert `_schedule_fn is None`, no calendar import, `calendar_event_id` stays null. (FLAG-3, Invariant 1)
- [ ] Task 3: Register `tasks_manifest(include_write_surface=False)` into `_register_modules`; Hello-unlock gating verified (locked vault → 423/no-op).
- [ ] Task 4: Suggest-during-digest emits a `suggestion.create` (proposal only); truncate/strip externally-sourced suggestion fields. (FLAG-4; coordinate with spec B)
- [ ] Task 5: Client — wire the accept-suggestion button (→ `suggestion.accept`); guard the external `calendar.schedule_task` button (finding C).
- [ ] Task 6: Tests — schedule-write reachable ONLY via `suggestion.accept` (absent from reactive tool index); invariants 1–3; locked-vault no-op.

## Acceptance criteria (provisional)
- [ ] Internal schedule sets `scheduled_block`, leaves `calendar_event_id` null, and never imports/calls the calendar client (grep + test).
- [ ] The live registry exposes the internal task + suggestion tools but NOT a calendar-coupled `tasks.schedule` (assert on registered tool names).
- [ ] Suggest→accept flow schedules; no path schedules without ask-or-accept.
- [ ] Locked vault → task tools no-op (423/degrade), not crash.
- [ ] Host re-verify: full `uv run mypy` + `uv run pytest -q` green.

## Open questions for the planning confirm
1. Should the internal schedule tool be a NEW tool name (e.g. `tasks.set_block`) or the `tasks.schedule`
   name reused in an internal-only mode? (Naming + avoiding confusion with the calendar-coupled one.)
2. Does registering write-capable task tools into the *reactive* path need any per-tool confirm even
   though it's internal? (Owner-rules says internal auto — likely no — but security review to confirm.)
3. Exact digest suggestion trigger (which unscheduled tasks, how many) — coordinate with spec B.

## Security review (folded 2026-06-28) — verdict: SAFE-WITH-CONDITIONS

The core claim (scheduled_block writes are internal-reversible; the calendar-coupled tool is absent
without `schedule_fn`) HOLDS. But two BLOCKs must be resolved before build:

**BLOCK-1 — registering `tasks_manifest` opens the WHOLE write surface, not just scheduling.**
`_task_tool_specs()` unconditionally registers `tasks.cancel`, `tasks.complete`, `tasks.update`,
`tasks.set_recurrence`, `tasks.assign_to_project` (all `ActionRisk.WRITE`). `tasks.cancel` is NOT
internal-reversible (no `task_uncancel`). The "no GATE" argument only covered `scheduled_block`.
→ **FOLD (required):** register ONLY the minimal tool set this slice needs (internal schedule +
suggestion tools) via a new `include_write_surface=False` flag on `tasks_manifest`; cancel/complete/
update stay OFF until a separate GATE-gated spec. Task 2 + an acceptance criterion updated accordingly.

**BLOCK-2 — "never silent-auto" has ZERO code enforcement (the open fork — see below).**
`brain.py:266` dispatches any registered front-door callable immediately, no approval step. Convention
is not enough for the first action-taking capability. → **OWNER DECISION REQUIRED** (§ Open fork).

**FLAG-3 (fold):** the new schedule callable must `assert _schedule_fn is None` and import nothing
from `calendar.schedule_task` — the module-level `_schedule_fn` global (`tools.py:25`) must not be
reachable. Acceptance criterion's grep/test must verify this.
**FLAG-4 (fold):** define a truncation + control-char-strip policy for externally-sourced suggestion
fields (`title`/`notes`/`source`) before the digest wiring (Task 3) ships — pre-empts injection once a
real source feeds suggestions.
**Hello-unlock (fold):** add an explicit acceptance criterion — locked vault → task tools degrade to
423/no-op at the gateway registration site, verified by test.

## BLOCK-2 resolution — Option B1 (LOCKED 2026-06-28, owner)
**Suggest/accept ONLY — no GATE, "never auto" enforced by construction.**
- The internal `schedule_block` action is **NOT registered as a front-door reactive tool** (it is
  absent from the tool index `brain.py:266` selects from), so the model can never call it directly.
- The ONLY path that sets `scheduled_block` is the handler behind `suggestion.accept` — an explicit
  owner action. Artemis may `suggestion.create` a proposed slot (during the digest or on request);
  nothing schedules until the owner accepts.
- This makes Invariant 2 structural, not conventional: there is no code path from a model turn to a
  schedule write. Free-form "just schedule X for tomorrow" is intentionally deferred to the future
  GATE lever.

### Enforcement design (B1)
- `_register_modules` registers `tasks_manifest(include_write_surface=False)` → exposes ONLY the
  suggestion tools (`suggestion.create/list/accept/reject`) + read tools. NO `tasks.schedule`,
  NO cancel/complete/update (BLOCK-1 fold).
- `suggestion.accept`'s handler performs the internal `scheduled_block` write directly (in-process,
  not via a registered tool callable). It asserts `_schedule_fn is None` and imports no calendar code
  (FLAG-3).
- Acceptance criterion: grep the registered reactive tool names → the schedule-write callable is
  absent; the only way to reach a `scheduled_block` write in a test is through `suggestion.accept`.
