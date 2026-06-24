# CAL-b — build progress

## BLOCKED at pre-flight (Task 5 / classifier+twin contract) — 2026-06-24

**Spec says:** gated calendar writes stage a `PendingAction`; owner approval → GATE-a
`ActionStagingService.approve()` dispatches a `{tool}_execute` twin that performs the RAW
Google write with **no classification** (CAL-b Task 5, B1 / Seam 3 D1; security invariant #2:
"GATED path NEVER calls the write API" until approved, then executes once).

**Why it can't be done as-is:** the live registry (`src/artemis/registry/registry.py:60-62`)
auto-registers the `_execute` twin for every WRITE/HIGH_STAKES tool pointing at the **same
front-door `callable_ref`**. CAL-b's front-door callable is the classify+dispatch method (correct,
since the brain calls `spec.callable_ref` directly — `brain.py:208` — with no upstream
action_risk staging, so in-tool classification is the only gate). Therefore approve() →
`calendar.create_event_execute` → re-runs `classify()` on the attendee event → GATED → re-stages.
Result: approval marks the original action APPROVED, executes nothing, and creates a dangling new
PendingAction. = the "GATE-a approval re-dispatch loop" (2026-06-10 sweep B1), resurfaced because
CAL-b is the first external-effect *runtime-gated* module (productivity writes are internal-
reversible auto, never staged).

A distinct raw twin callable is required. It cannot live in CAL-b's stated files:
- registry forces twin == front-door callable (M1-a, not in CAL-b Files to Change);
- a separate raw tool placed in the manifest would be indexed → brain-visible → bypasses the
  classifier = security hole (violates spec invariant "brain must never see/call `*_execute`").

**The decision planning/owner must make:** how to give a runtime-gated module a distinct,
brain-invisible raw execute callable. Recommended (R1): add optional `execute_callable_ref` to
`ToolSpec` (`manifest.py`); registry uses it for the twin when present, else falls back to
`callable_ref` (backward-compatible — existing modules unaffected). Then CAL-b: front-door =
classify, `execute_callable_ref` = raw. Touches frozen contracts.md Seams 2/3 → planning's call.

Everything else in CAL-b (write schemas, `classify()` truth table, activity log, AUTO path) is
buildable as written; only the gated-twin wiring is blocked on this contract decision.
