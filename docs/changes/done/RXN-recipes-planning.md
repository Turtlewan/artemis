---
spec: rxn-recipes-planning
status: ready
token_profile: balanced
autonomy_level: L2
---
<!-- Wave R · per-cluster reaction recipes (Planning). Consumes the reaction infra (RXN-emit /
     RXN-rulestore / RXN-dispatcher) + capabilities (TRIP-entity, MAPS-connector) + the M8-d-b
     Task↔Calendar seam (task.schedule / clear_task_schedule_link). Defines the Tier-A Task⇄Calendar
     link reactions (C1/C4 always-linked, Decision 8) + C2 task-done→mark-paid + Trip-assembly blocks.
     Builds NONE of the infra/capabilities/seams it binds to. -->

# Spec: RXN-recipes-planning — Planning reaction recipes (C1/C4 Task⇄Calendar link · C2 task-done→mark-paid · Trip blocks)

**Identity:** The Planning-cluster reaction recipes: registers the Tier-A Task⇄Calendar link reactions (C1 task-with-deadline → focus block; C4 complete-task → clear block — the always-linked, bidirectional Task⇄Calendar of ADR-021 Decision 8), C2 (task-done → mark-paid, Tier-A extended), and the Trip-assembly airport-leave focus blocks. All reactions here are internal/reversible (self-only blocks, link writes) → Tier-A auto with an undoable notice; none has an external effect.
→ why: see docs/technical/adr/ADR-021-cross-module-reactions.md (Decision 2 Tier-A built-ins C1/C4 + extended C2 · Decision 8 Task⇄Calendar always-linked) · docs/findings/cluster-decisions/DECISIONS-LOG.md (Planning reactions).

## Assumptions

- **RXN-emit** complete: frozen `DomainEvent{event_type: EventType, source_module, entity_refs, payload: dict[str, str|int|float|bool], occurred_at, dedup_key}` (payload scalars only — validated). Bound `EventType` values used here: `TASK_CREATED` (payload carries `task_id` + a `due_at` scalar when the task is dated), `TASK_DONE` (payload carries `task_id` + `linked_event_id`/`linked_bill_ref` scalars when present — confirmed against the Tasks emit contract; a reaction that needs a field reads it from the scalar payload, and the rule's `dedup_key_fields` reference those payload keys), and `TRIP_ASSEMBLED` (now in the registry; produced by TRIP-entity's `TripAssembler.assemble`, payload `trip_id`/`destination_place_id`/`start_dt`/`end_dt`/`leg_count`). → impact: Stop (Planning rules bind to these registered `EventType`s; the emit points are RXN-emit/TRIP-entity's contract — referenced, not built). C1 binds to `TASK_CREATED` (the canonical rulestore `task_block_create` binding) — there is NO separate `task-scheduled` event type.
- **RXN-rulestore** complete: the canonical `ReactionRule` is a frozen dataclass `{name: str, event_type: EventType, tier: ReactionTier, external_effect: bool, reaction_ref: str (fq tool/recipe id), dedup_key_fields: tuple[str, ...], stateful: bool = False}` with the Tier-A structural gate (`tier==A ⇒ external_effect is False`). The Tier-A built-in table already declares C1 (`task_block_create`), C4 (`task_block_clear`), C2 (`task_done_mark_paid`). → impact: Stop (this spec builds the reaction CALLABLES those `reaction_ref` fq-ids point to + a `register_planning_reactions` that registers them as tools and returns the matching `ReactionRule`s; the dispatcher resolves `get_tool(reaction_ref).callable_ref`, so `reaction_ref` is a STRING fq id — never a `Callable` — and idempotency is `dedup_key_fields`, never an `idempotency_key_fn`).
- **RXN-dispatcher** complete: dispatches via `await get_tool(rule.reaction_ref).callable_ref(args)` (async, ADR-016), composes the stable key from `rule.dedup_key_fields` over the event payload + `event.dedup_key`, internal/reversible (`external_effect=False`) → auto + undoable notice. → impact: Stop (the dispatcher owns idempotency + dispatch; recipes provide the fq-id'd callables + the rules).
- **M8-d-b Task↔Calendar seam** complete: `task.schedule` / the `calendar.schedule_task` primitive create a self-only focus block + write `task.calendar_event_id` / `task.scheduled_block`; `clear_task_schedule_link(task_id)` clears the link; `task.complete` already clears the link of a completed time-blocked task. → impact: Stop (C1 calls the schedule primitive; C4 reuses the clear path; this spec wires them as event reactions rather than re-implementing the block logic).
- **TRIP-entity** + **MAPS-connector** complete: `TripAssembler.assemble` emits `EventType.TRIP_ASSEMBLED` (registered) with a scalar payload (`trip_id`/`destination_place_id`/`start_dt`/`end_dt`/`leg_count`); `TripRepository.get_trip` exposes assembled `Trip`s with legs; `MapsConnector.travel_time` / `FixedBufferFallback` give the airport buffer. The A5 flight held-event is created in RXN-recipes-comms; the Trip-assembly *focus block* (airport-leave block as an owned task/block) is wired here as a Planning reaction on the `TRIP_ASSEMBLED` event. → impact: Caution (the Trip block is a self-only focus block — internal; degrades to fixed buffer on dev).
- **FIN-c** complete (for C2): emits `bill-recorded` and exposes a `mark_bill_paid` path; C2 (task-done → mark-paid) reacts to a `task-done` whose task is linked to a finance bill (`linked_bill_ref`), marking the bill paid. → impact: Stop (C2 calls the FIN-c mark-paid tool via the ToolRegistry, never the finance store directly — ADR-011).
- **Decision 8 (always-linked):** any reaction that creates/links a dated task MUST also wire it into Calendar (due-date marker and/or focus block), bidirectional (complete→clear). C1/C4 ARE this contract expressed as reactions. → impact: Stop.
- Off-hardware: fakes for emit/dispatcher + the M8-d-b schedule/clear seam + Trip/Maps + the FIN-c mark-paid tool. → impact: Low.

Simplicity check: C1/C4/C2 are thin event→tool delegations (schedule a block / clear a block / mark a bill paid) — the block logic and the mark-paid logic already exist (M8-d-b, FIN-c). This spec is the routing table + idempotency keys, not new behaviour. The Trip block reuses the same self-only focus-block path. No new store, no new model call.

## Prerequisites

- Specs complete: **RXN-emit**, **RXN-rulestore**, **RXN-dispatcher**, **M8-d-b** (Task↔Calendar seam, post-F0 `tasks_manifest`/areas-drop), **TRIP-entity**, **MAPS-connector**, **FIN-c** (mark-bill-paid for C2).
- Environment: no new PyPI deps.

## Files to Change

| File | Operation | Notes |
|------|-----------|-------|
| `/Users/artemis-build/artemis/src/artemis/reactions/recipes/planning.py` | create | C1/C4/C2/Trip-block async reaction callables (fq tool-ids) + `register_planning_reactions(registry, *, schedule_task_fn, clear_link_fn, mark_bill_paid_fn, trip_assembler, maps) -> tuple[ReactionRule, ...]` |
| `/Users/artemis-build/artemis/src/artemis/reactions/recipes/__init__.py` | modify | re-export `register_planning_reactions` |
| `/Users/artemis-build/artemis/tests/test_reactions_planning.py` | create | C1 block-on-deadline, C4 clear-on-complete (bidirectional), C2 mark-paid, Trip block, idempotency, Tier-A enabled-day-one |

All paths under `/Users/artemis-build/artemis/`.

## Tasks

- [ ] **Task 1: C1 — task-with-deadline → focus block (Tier-A, always-linked)** — files: `/Users/artemis-build/artemis/src/artemis/reactions/recipes/planning.py` —

  `async def react_task_deadline_to_block(event: DomainEvent, *, schedule_task_fn) -> ReactionResult` (ADR-016 async). Invoked on `task-created`/`task-scheduled` where `event.payload.get("due_at")` is set:
  1. Call `result = await schedule_task_fn(TaskScheduleArgs(task_id=event.payload["task_id"]))` (the M8-d-b `task.schedule` primitive — finds a slot, creates a self-only focus block, writes the Task↔Event link). The block is self-only → AUTO (no GATE), internal/reversible.
  2. If no slot was found (`result.event_id is None`): return `ReactionResult(status="no_slot", ref=None, undoable=False)` (degrade — no block, no error).
  3. Else return `ReactionResult(status="linked", ref=result.event_id, undoable=True)` (the undo = clearing the block; C4 also fires on completion).

  **Tier-A:** C1 is a day-one built-in (universal: every deadlined task wants a block; internal: self-only block; reversible: clear; zero-judgment: deterministic). The matching `ReactionRule` is the rulestore's `task_block_create` (`name="task_block_create"`, `event_type=EventType.TASK_CREATED`, `tier=ReactionTier.A`, `external_effect=False`, `reaction_ref="tasks.schedule"`, `dedup_key_fields=("task_id",)`). The dispatcher composes the stable key from `dedup_key_fields` over the payload — re-firing on the same `task_id` re-schedules (the M8-d-b primitive auto-cancels the old block before creating a new one), never duplicates. The "only when `due_at` is set" condition is a guard inside the reaction callable (no slot/no `due_at` → degrade), since the canonical `ReactionRule` has no per-rule match-predicate field.

  — done when: `uv run mypy --strict src` passes; `await react_task_deadline_to_block(event, schedule_task_fn=fake)` on a `task-created` with `due_at` calls `schedule_task_fn` once and returns `status="linked"`; a `task-created` WITHOUT `due_at` does not schedule (the rule's match predicate excludes it); no-slot returns `status="no_slot"` without error; re-fire on the same task_id is deduped.

- [ ] **Task 2: C4 — complete task → clear block (Tier-A, bidirectional)** — files: `/Users/artemis-build/artemis/src/artemis/reactions/recipes/planning.py` —

  `async def react_task_complete_clear_block(event: DomainEvent, *, clear_link_fn) -> ReactionResult` (ADR-016 async). Invoked on `task-done` where `event.payload.get("linked_event_id")` is set:
  1. Call `clear_link_fn(event.payload["task_id"])` (the M8-d-b `clear_task_schedule_link` — sets `calendar_event_id`/`scheduled_block` to NULL). Note: `task.complete` in M8-d-b already clears the link on the *direct* tool path; this reaction covers the case where the completion arrives as a domain event from another path (and is idempotent with the direct clear).
  2. The Google focus-block event itself is NOT deleted (M8-d-b posture: the block stands — Artemis does not auto-cancel a focus block on completion). C4 clears only the *link*, matching the M8-d-b contract.
  3. Return `ReactionResult(status="cleared", ref=event.payload["task_id"], undoable=False)`.

  **Tier-A + Decision 8 bidirectionality:** C4 is the reverse half of C1 (complete→clear), making the Task⇄Calendar link bidirectional per Decision 8. The matching `ReactionRule` is the rulestore's `task_block_clear` (`event_type=EventType.TASK_DONE`, `tier=ReactionTier.A`, `external_effect=False`, `reaction_ref="tasks.schedule"`, `dedup_key_fields=("task_id",)`, `stateful=True`). Clearing an already-cleared link is a safe no-op. The "only when `linked_event_id` is set" condition is a guard inside the callable.

  — done when: `uv run mypy --strict src` passes; `await react_task_complete_clear_block(event, clear_link_fn=fake)` on a `task-done` with `linked_event_id` calls `clear_link_fn(task_id)` once; a `task-done` WITHOUT a linked event does not call clear (match predicate); re-fire is a safe no-op; the Google event is not deleted (assert no cancel/delete call).

- [ ] **Task 3: C2 — task-done → mark-paid (Tier-A extended)** — files: `/Users/artemis-build/artemis/src/artemis/reactions/recipes/planning.py` —

  `async def react_task_done_mark_paid(event: DomainEvent, *, mark_bill_paid_fn) -> ReactionResult` (ADR-016 async). Invoked on `task-done` where `event.payload.get("linked_bill_ref")` is set (the task is a pay-bill task linked to a finance bill):
  1. Resolve the bill id from `linked_bill_ref` (a `{module}:{id}` logical ref — `finance:bill:<id>`).
  2. Call `await mark_bill_paid_fn(bill_id)` (the FIN-c mark-bill-paid tool via the ToolRegistry — ADR-011: never the finance store directly). This is an internal local-ledger edit (no GATE — finance has no external-effect surface).
  3. Return `ReactionResult(status="bill_paid", ref=bill_id, undoable=True)` (undo = re-open the bill).

  **Tier-A extended:** C2 is in the ratified extended Tier-A list (internal ledger edit, reversible, zero-judgment given the explicit task↔bill link). The matching `ReactionRule` is the rulestore's `task_done_mark_paid` (`event_type=EventType.TASK_DONE`, `tier=ReactionTier.A`, `external_effect=False`, `reaction_ref="finance.mark_bill_paid"`, `dedup_key_fields=("task_id",)`, `stateful=True`). Marking an already-paid bill paid is a safe no-op. The "only when `linked_bill_ref` is set" condition is a guard inside the callable.

  — done when: `uv run mypy --strict src` passes; `await react_task_done_mark_paid(event, mark_bill_paid_fn=fake)` on a `task-done` with `linked_bill_ref="finance:bill:b1"` calls `mark_bill_paid_fn("b1")` once; a `task-done` without a bill ref does not call mark-paid; re-fire on a paid bill is a no-op.

- [ ] **Task 4: Trip-assembly airport-leave block** — files: `/Users/artemis-build/artemis/src/artemis/reactions/recipes/planning.py` —

  `async def react_trip_assembled_block(event: DomainEvent, *, schedule_task_fn, trip_assembler, maps) -> ReactionResult` (ADR-016 async). Invoked on a `TRIP_ASSEMBLED` event (emitted by the TripAssembler when a Trip is assembled/revised):
  1. Read the assembled `Trip` (by `event.payload["trip_id"]`).
  2. Compute the airport-leave time: `buffer = maps.travel_time(home, airport, mode="driving")` if available, else `FixedBufferFallback` (intl/domestic buffer from X3 `reaction.maps_*_buffer_minutes`).
  3. Create a self-only focus block "Leave for airport" at `flight_departure − buffer` via `schedule_task_fn`/the self-only block path (internal, reversible — NOT external).
  4. Return `ReactionResult(status="block_created", ref=<block id>, undoable=True)`.

  **Tier-B (internal self-only block, but a judgment-ish travel estimate → precision-first):** the leave-block is a self-only focus block (internal/reversible), but the buffer is an uncertain travel estimate, so the reaction is **Tier-B** (not in the rulestore Tier-A table). It registers a `ReactionRule(name="trip_airport_block", event_type=EventType.TRIP_ASSEMBLED, tier=ReactionTier.B, external_effect=False, reaction_ref="reaction:trip_airport_block", dedup_key_fields=("trip_id",), stateful=True)` — `stateful=True` so re-firing on an updated Trip updates the SAME block (Decision 5 windowed revision) rather than duplicating. Document the tier choice.

  — done when: `uv run mypy --strict src` passes; `await react_trip_assembled_block(...)` computes the buffer (fixed fallback when Maps fake has no key), creates a self-only block, returns `status="block_created"`; re-fire on the same `trip_id` updates the same block (no duplicate); the tier choice (B by default) is documented.

- [ ] **Task 5: `register_planning_reactions` wiring** — files: `/Users/artemis-build/artemis/src/artemis/reactions/recipes/planning.py`, `/Users/artemis-build/artemis/src/artemis/reactions/recipes/__init__.py` —

  `def register_planning_reactions(registry: ToolRegistry, *, schedule_task_fn, clear_link_fn, mark_bill_paid_fn, trip_assembler, maps) -> tuple[ReactionRule, ...]`: registers each reaction callable in the `ToolRegistry` under its fq `reaction_ref` id (`tasks.schedule` / `finance.mark_bill_paid` are existing M8-d-b/FIN-c tools the canonical rules already reference; `reaction:trip_airport_block` is the new Tier-B reaction-recipe tool this spec registers), injecting the capability handles via `functools.partial` so each registered `callable_ref` has the ADR-016 `async (args) -> BaseModel` shape. Returns the `ReactionRule`s for C1 (`task_block_create`, `ReactionTier.A`), C4 (`task_block_clear`, `ReactionTier.A`), C2 (`task_done_mark_paid`, `ReactionTier.A`) — which align field-for-field with the rulestore's `TIER_A_BUILTINS` — plus the Tier-B `trip_airport_block` (`ReactionTier.B`); the Tier-A three are already in `TIER_A_BUILTINS` (this spec supplies the callables they bind to), so registration is the tool wiring + the Tier-B rule. Document the event_type→reaction map + the `dedup_key_fields` + the Decision-8 always-linked invariant (C1+C4 are the link's two halves). Re-export from `recipes/__init__.py`.

  — done when: `uv run mypy --strict src` passes; `register_planning_reactions(...)` registers the 4 reaction callables as tools and returns 4 `ReactionRule`s; C1/C4/C2 carry `tier=ReactionTier.A` and match the rulestore `TIER_A_BUILTINS` entries (name/event_type/reaction_ref/dedup_key_fields), Trip-block `tier=ReactionTier.B`; `from artemis.reactions.recipes import register_planning_reactions` succeeds.

- [ ] **Task 6: Tests** — files: `/Users/artemis-build/artemis/tests/test_reactions_planning.py` — typed pytest, async.

  Fakes: `FakeScheduleTaskFn` (records calls; returns a `TaskScheduleResult` with/without an event_id), `FakeClearLinkFn` (records), `FakeMarkBillPaidFn` (records), `FakeTripAssembler`, `FakeMaps` (no-key → fixed buffer), `FakeDispatcher` with an idempotency ledger.

  - **C1 block on deadline:** a `task-created` with `due_at` → `schedule_task_fn` called once → `status="linked"`; a `task-created` without `due_at` → not scheduled; no-slot → `status="no_slot"` (no error); re-fire deduped.
  - **C4 clear on complete (bidirectional):** a `task-done` with `linked_event_id` → `clear_link_fn(task_id)` called once → `status="cleared"`; the Google event is NOT deleted (no cancel/delete call); a `task-done` without a linked event → no clear; re-fire is a safe no-op.
  - **C1+C4 round-trip:** schedule then complete → block linked then link cleared (the Decision-8 bidirectional pair).
  - **C2 mark-paid:** a `task-done` with `linked_bill_ref="finance:bill:b1"` → `mark_bill_paid_fn("b1")` once → `status="bill_paid"`; no bill ref → no call; re-fire on paid bill → no-op.
  - **C2 uses the tool, not the store:** assert the reaction calls `mark_bill_paid_fn` (a ToolRegistry-mediated path), never a direct finance store write (ADR-011).
  - **Trip block:** buffer via fixed fallback (Maps fake no key); self-only block created; re-fire updates one block.
  - **Tier assignment + canonical rule shape:** C1/C4/C2 `tier=ReactionTier.A` (and equal field-for-field to the rulestore `TIER_A_BUILTINS` entries — `name`/`event_type`/`reaction_ref` str/`dedup_key_fields`/`external_effect is False`), Trip-block `tier=ReactionTier.B`; every returned rule's `reaction_ref` is a `str` resolvable in the `ToolRegistry`.

  — done when: `uv run pytest -q tests/test_reactions_planning.py` passes AND `uv run mypy --strict src tests/test_reactions_planning.py` passes AND `uv run ruff check . && uv run ruff format --check .` both exit 0.

- [ ] **Task 7 (GATED — on-hardware):** On the Mini with the real reaction infra + M8-d-b seam + FIN-c: a deadlined task → real focus block created + link written (C1); completing it → link cleared, Google block stands (C4); a pay-bill task completed → the linked finance bill marked paid (C2); a real Trip assembled → an airport-leave block at departure−buffer (real Maps key). — done when: recorded in handoff.

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | `/Users/artemis-build/artemis/src/artemis/reactions/recipes/planning.py` |
| Modify | `/Users/artemis-build/artemis/src/artemis/reactions/recipes/__init__.py` |
| Create | `/Users/artemis-build/artemis/tests/test_reactions_planning.py` |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict src tests/test_reactions_planning.py` | Type gate |
| `uv run ruff check . && uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q tests/test_reactions_planning.py` | Test gate (fakes only) |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | `src/artemis/reactions/recipes/planning.py`, `src/artemis/reactions/recipes/__init__.py`, `tests/test_reactions_planning.py` |
| `git commit` | `"feat: RXN-recipes-planning — C1/C4 Task⇄Calendar link, C2 task-done→mark-paid, Trip blocks"` |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_ENV_FILE` | Settings + scope resolution (off-hardware: tmp_path fixture) |

### Network
| Action | Purpose |
|--------|---------|
| (none off-hardware) | Real Maps + Google block writes are GATED on-hardware |

## Specialist Context

### Security

- **All internal/reversible:** C1 (self-only focus block), C4 (clear link), C2 (local-ledger mark-paid), Trip block (self-only block) — none has an external effect. No GATE staging needed (self-only blocks are AUTO per the CAL-b classifier; finance mark-paid is an internal ledger edit). The reactions act with an undoable notice (Tier-A internal posture).
- **ADR-011 — never reach into another spoke's store:** C2 calls the FIN-c mark-bill-paid *tool* via the ToolRegistry, never the finance store; C1/C4 call the M8-d-b *primitives*, never the productivity/calendar stores directly.
- **Decision 8 bidirectionality:** C1 (link) + C4 (clear) are the two halves of the always-linked Task⇄Calendar contract — a task is never left with a stale/dangling block (the link-integrity reconciler, RXN-reconciler, sweeps any that slip through).
- **Payload privacy (Seam 5/7):** events carry ids + scalars (task_id, due_at, linked_event_id, linked_bill_ref) — no titles/bodies.

[apex-security review: confirm C2 uses the ToolRegistry mark-paid path not a direct store write; confirm C4 clears only the link and does not delete the Google event; confirm no external-effect surface in any Planning reaction.]

### Performance

- Each reaction is a thin async tool delegation dispatched off the interactive turn. C1's `schedule_task` is one cache read + one block write (M8-d-b cost). C4/C2 are single local writes. The Trip block is one Maps call (Mac) or a constant (dev). Negligible.

### Accessibility

(none — headless reaction recipes; the block/link surfaces are the client Calendar/Tasks views, Wave U)

## Documentation

| Doc type | File | Action |
|----------|------|--------|
| Inline | `src/artemis/reactions/recipes/planning.py` | Document each reaction's cluster letter + Tier + idempotency key + the delegated tool; document the Decision-8 always-linked bidirectional pair (C1+C4), the no-Google-delete-on-complete posture (C4), and the ADR-011 tool-not-store rule (C2) |

## Acceptance Criteria

- [ ] `uv run mypy --strict src tests/test_reactions_planning.py` → verify: exit 0.
- [ ] `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.
- [ ] `uv run pytest -q tests/test_reactions_planning.py` → verify: C1 schedules a block on a deadlined task (and not without a deadline; no-slot degrades); C4 clears the link on completion (Google event not deleted) and is a safe no-op on re-fire; C1+C4 bidirectional round-trip; C2 marks the linked bill paid via the tool (not the store) and no-ops on a paid bill; Trip block uses the fixed buffer fallback; rules use canonical `ReactionRule` (str `reaction_ref` + `dedup_key_fields`, no `Callable`/`idempotency_key_fn`); tier assignment correct (C1/C4/C2=`ReactionTier.A` matching `TIER_A_BUILTINS`, Trip=`ReactionTier.B`).
- [ ] `uv run python -c "from artemis.reactions.recipes import register_planning_reactions; print('ok')"` → verify: prints `ok`.
- [ ] (GATED, on Mini) C1 block + C4 clear + C2 mark-paid + Trip airport block round-trip → recorded in handoff.

## Progress
_(Coding mode writes here — do not edit manually)_
