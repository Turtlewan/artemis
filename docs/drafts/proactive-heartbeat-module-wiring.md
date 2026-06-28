---
spec: proactive-heartbeat-module-wiring
status: draft
risk: medium
coder: codex
coder_effort: high
cross_model_review: true
autonomy_level: L5
origin: system-check 2026-06-28 (decision B) — drafted in coding mode, NEEDS A PLANNING REVIEW PASS before build
---

# Spec (DRAFT): Wire the proactive hooks + read modules into the live heartbeat

**Identity:** The proactive heartbeat runs but is functionally starved — `_register_modules`
(`gateway.py:500-520`) registers ONLY the read-only `time` module, and `compose_proactive` is
called with no `pre_tick_steps`, so the built briefing/digest/review hooks never fire. This spec
registers the proactive hooks and the read-tool modules they depend on so proactivity actually does
something. **Read + notify only — no external-effect (write) tools, so the GATE/staging path is out
of scope (see § Boundary).**
→ why: system-check 2026-06-28 composition audit (finding #3); carried FLAGs in status.md In-Flight
(CAL-d `pre_tick_steps` "composition target unspecified"; M8-d-c1 wake-digest hooks; M6-c attach).

## Boundary (the critical scoping decision — DO NOT cross)
The heartbeat hooks registered here are **read-and-notify**: morning digest, weekend review,
week-ahead, calendar overlay pre-flight launderers, finance unusual-spend. They read owner data and
emit ntfy notifications. They do **NOT** call external-effect write tools (calendar.create,
gmail.send, tasks write). Registering external-effect WRITE tools into a live dispatch path is
**decision A (GATE + agentic-action composition)** and is explicitly OUT OF SCOPE here — wiring a
write tool without the staging/approval GATE would let proactivity take un-approved external actions.
If any hook here is found to need a write, STOP and escalate to the A decision.

## Assumptions
- All referenced hooks/modules are already built and unit-tested (M6-b/c, M8-d-c1 wake-digest,
  CAL-c overlay hooks, FIN-c finance hooks) — this is composition only, no new behaviour.
- `compose_proactive` accepts a `pre_tick_steps` list (per M6-c `attach_to_heartbeat`); the heartbeat
  scans the registry returned by `_register_modules`.
- The hooks are read-only/notify and need only owner-private READ scope (gated on Hello-unlock, same
  as retriever/memory) — a locked vault degrades them to no-op, not a crash.

## Open questions for the planning review (resolve before build)
1. **Which modules' read-tools must be registered** for the hooks to function (calendar read,
   finance read, productivity read)? Enumerate exactly — registering more than the hooks need widens
   the reactive tool surface unnecessarily.
2. **Attach point for CAL-c `pre_tick_steps`** — the CAL-d FLAG said the composition target was
   "unspecified". Confirm it is `compose_proactive(pre_tick_steps=[...])` in `gateway.py`/`main.py`.
3. **Sensitivity:** finance hooks touch owner-private finance — confirm the notify payload honours
   the sensitivity wall (no sensitive content in the ntfy body; IDs/counts only, per M6-b design).

## Files to change (provisional — confirm in review)
| File | Operation | Notes |
|------|-----------|-------|
| `src/artemis/gateway.py` | modify | `_register_modules`: register the read modules the hooks need; `compose_proactive`: pass `pre_tick_steps` built from the proactive hooks. |
| `src/artemis/main.py` | modify (maybe) | If hook construction belongs in lifespan rather than compose. |
| `tests/test_*` | modify/create | Assert the heartbeat tick fires the registered hooks against a populated registry. |

## Tasks (provisional)
- [ ] Task 1: Register the hook-required read modules in `_register_modules` (enumerated in Q1).
- [ ] Task 2: Build the `pre_tick_steps`/hook list and pass it to `compose_proactive`.
- [ ] Task 3: Test — a heartbeat tick with a populated registry fires each hook; locked vault → no-op.

## Acceptance criteria (provisional)
- [ ] A heartbeat tick test shows the morning-digest/weekend-review/week-ahead hooks evaluated (not an empty registry scan).
- [ ] Finance/calendar hooks fire on their triggers and emit ntfy with no sensitive content in the body.
- [ ] No external-effect WRITE tool is registered into the reactive path (grep the registered manifests).
- [ ] Host re-verify: full `uv run mypy` clean + `uv run pytest -q` green.

## Notes
This is the highest-value "make proactivity real" step and is mostly mechanical, but the module
enumeration + sensitivity check make it a genuine (small) design pass — hence status: draft, not ready.
