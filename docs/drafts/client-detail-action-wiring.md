---
spec: client-detail-action-wiring
status: draft
risk: medium
coder: codex
coder_effort: high
cross_model_review: true
autonomy_level: L5
origin: system-check 2026-06-28 (decision C) — drafted in coding mode, NEEDS A PLANNING REVIEW PASS before build
---

# Spec (DRAFT): Wire (or guard) the dead detail-view action buttons

**Identity:** Two client detail-view action surfaces invoke Tauri commands that do not exist, so the
buttons are silent no-ops at runtime: `app_stage_pending_action` (`CalendarDetail.tsx:29`) and the
dynamic task actions (`tasks.reschedule`, `tasks.accept_suggestion`, `calendar.schedule_task` —
`TasksDetail.tsx:56,62,67`). The detail views were built ahead of their transport (the known
"CLIENT-screens richer DTOs vs CLIENT-b wire" follow-up).
→ why: system-check 2026-06-28 transport audit (finding #4).

## The dependency that shapes this spec
These buttons stage **external-effect actions** (create/reschedule a calendar event, accept a task
suggestion). Wiring them to actually execute requires the **action-staging GATE + agentic-action
composition (decision A)** — which is currently NOT composed (the staging queue is never populated;
`brain.py:266` dispatches front-door callables only, and only the read-only `time` module is
registered). **You cannot safely wire these to real execution until decision A is resolved.**

Therefore this spec is **two phases**, and Phase 2 is BLOCKED on A:

### Phase 1 — Guard the dead buttons (UNBLOCKED, safe, do now)
Stop the silent no-op: disable/hide the action buttons (or show a "not yet available" affordance)
whenever the backing command is absent, so a live demo never presents a button that does nothing.
- Files: `client/src/world/CalendarDetail.tsx`, `client/src/world/TasksDetail.tsx` (+ vitest).
- Done when: the stage-action and task-action controls are disabled/hidden with a clear affordance;
  vitest asserts they are not rendered as active buttons; `npm run lint` + `tsc` + `vitest` green.

### Phase 2 — Wire command → route → staging (BLOCKED on decision A)
Once the GATE/staging path is composed, add the Tauri commands + brain routes that stage these
actions for owner approval (NOT direct execution):
- `app_stage_pending_action` Tauri command → brain route that calls `ActionStagingService.stage()`.
- Task domain action commands (`tasks.reschedule` etc.) → brain routes → stage.
- The existing approve/reject/list routes (already live at `api_app.py:812-842`) then surface and
  resolve the staged actions.
- Files: `client/src-tauri/src/gateway.rs` + `lib.rs` (new commands), `src/artemis/api_app.py`
  (new stage routes), `client/src/api/gateway.ts`, the two detail views, tests both sides.
- Done when: clicking an action stages a pending action visible to the approve/reject surface; no
  external effect occurs without approval; full host + client verify green.

## Open questions for the planning review
1. **Phase-1 form:** disable-in-place vs hide entirely vs "coming soon" tooltip? (UX call.)
2. **Confirm Phase 2 is gated on A** — or does owner want A + this wired together as one larger build?
3. The dynamic `invoke(name, …)` pattern in `TasksDetail.tsx` is stringly-typed — Phase 2 should
   replace it with explicit named commands (each registered in `generate_handler!`) so the audit class
   that found this (unregistered invoke) can't recur silently.

## Acceptance criteria (Phase 1 only — Phase 2 deferred to post-A)
- [ ] No detail-view button invokes an unregistered command at runtime (grep `invoke(` in the two views vs `generate_handler!`).
- [ ] Disabled/guarded affordance rendered instead; vitest covers it.
- [ ] Client gates green: `npm run lint`, `tsc`, `vitest`.

## Recommendation
Build **Phase 1 now** (quick, removes broken-button UX), and fold **Phase 2 into the decision-A
build** (GATE + agentic-action composition) so the staging path and its UI land together and verified
end-to-end.
