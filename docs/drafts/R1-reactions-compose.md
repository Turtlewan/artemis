---
spec: R1-reactions-compose
status: draft
cross_model_review: true
token_profile: balanced
autonomy_level: L2
---

# Spec: R1 — Reactions composition root + observe-mode go-live gate

**Identity:** Builds the `compose_reactions` composition root that wires `EventBus → ReactionLedger → ReactionRuleStore → ReactionDispatcher` and registers all three recipe packs, adds an `observe`/`live` mode gate to the dispatcher, adds `reactions_mode` to `RuntimeConfig`, and exposes a heartbeat `pre_tick_step`. Foundation for R2/R3/R4.
<!-- → why: see docs/technical/adr/ADR-032-reactions-runtime-composition.md (Decisions 1, 2, 4). -->

## Assumptions
- No app-root function calls both `compose_proactive` and `compose_reactions` today — `compose_proactive` is referenced only inside `src/artemis/proactive/__init__.py` (and docs/tests), no daemon mount exists. This spec therefore produces `compose_reactions` returning `(bus, pre_tick_step)` and documents the intended `compose_proactive(pre_tick_steps=[pre_tick_step])` wiring in a module docstring; it does NOT invent a new app-root file. → impact: Stop (if an app-root exists, the wiring task target changes).
- `reactions_mode` belongs on the existing `ReactionConfig` sub-model (not a new `ReactionsConfig`) — `runtime_config.py` already has `ReactionConfig` carrying reaction tunables (`fraud_confirm_*`, `maps_*_buffer_minutes`), accessed as `get_runtime_config().reaction` in `recipes/self.py`. Adding `reactions_mode` there matches the file's pattern and avoids a redundant sub-model. → impact: Caution (a new sub-model would mean a different access path and an extra `RuntimeConfig` field).
- In `observe` mode the dispatcher STILL records the dedup claim/ledger (calls `try_claim` / `record_refire` exactly as `live`) and only suppresses the *effect* (stage / tool-execute / A4 suggest / internal-reversible execute), routing each suppressed effect to `notice_sink` as `WOULD <action>: <rule>`. Rationale: without recording, observe would re-fire the same event every tick forever and flood `notice_sink`; recording makes observe a faithful one-shot dry-run of live dedup behaviour. → impact: Stop (alternative — not recording — changes observe semantics and breaks the "no endless replay" requirement).
- `compose_reactions` is a wiring root, not a service factory: the recipe packs require many domain seam callables (`schedule_task_fn`, `clear_link_fn`, `mark_bill_paid_fn`, `trip_assembler`, `maps`, `capture_service`, `calendar_from_extract_fn`, `reconciler`, `fraud_notify_fn`, `complete_task_fn`, `emit`) that compose cannot build itself. These are accepted as injected params and threaded into the three `register_*` calls. compose itself constructs only `EventBus`, `ReactionLedger`, `ReactionRuleStore`, and `ReactionDispatcher`. → impact: Caution (if a caller is expected to pass fewer seams, the signature shrinks).
- The dispatcher reads `mode` from a constructor param (`mode: Literal["observe","live"] = "observe"`), NOT from `get_runtime_config()` directly — keeps the dispatcher unit-testable without a runtime config file; `compose_reactions` reads `get_runtime_config().reaction.reactions_mode` and passes it in. → impact: Caution (reading config inside the dispatcher would couple it to the slot config and complicate the existing dispatcher tests).
- The `emit` seam passed to `register_self_reactions` is `bus.emit` (so finance reactions can emit `BILL_PAID` back onto the same bus). Wiring of the *producer-side* emitters (gmail/calendar/finance/trips) is R2's job and is out of scope here. → impact: Low (R2 owns producer emit; R1 only needs the self-pack `emit` seam satisfied).

Simplicity check: considered making `compose_reactions` build the domain seams internally (no params) — rejected: those seams live in finance/tasks/calendar/trips modules and pulling them all into compose would make this spec touch >3 files and duplicate wiring R2/R3 own. This version keeps compose a thin wiring root with injected seams.

## Prerequisites
- Specs that must be complete first: none (this is the foundation spec).
- Environment setup required: none (uses existing `uv` toolchain).

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| `src/artemis/reactions/compose.py` | create | `compose_reactions(...)` wiring root; returns `(EventBus, pre_tick_step)`. |
| `src/artemis/reactions/dispatcher.py` | modify | Add `mode: Literal["observe","live"]` param + observe-mode gate in `_fire`. |
| `src/artemis/runtime_config.py` | modify | Add `reactions_mode: Literal["observe","live"] = "observe"` to `ReactionConfig`. |
| `src/artemis/reactions/__init__.py` | modify | Re-export `compose_reactions` (lazy, matching existing `__getattr__` pattern). |
| `tests/test_reactions_compose.py` | create | observe/live/compose tests. |

## Tasks
- [ ] Task 1: Add `reactions_mode: Literal["observe","live"] = "observe"` field to `ReactionConfig` (import `Literal` from `typing`; place field after `maps_domestic_buffer_minutes`, with a one-line `description`). — files: `src/artemis/runtime_config.py` — done when: `RuntimeConfig().reaction.reactions_mode == "observe"` and `ReactionConfig` rejects values other than `observe`/`live`.
- [ ] Task 2: Add observe-mode gate to the dispatcher. Add `mode: Literal["observe","live"] = "observe"` as a keyword-only `__init__` param stored on `self._mode`; import `Literal` from `typing`. In `_fire`, after the dedup claim/state-hash block (which runs UNCHANGED in both modes) and after the stateful `record_refire`, branch on `self._mode`: in `observe`, route each effect branch (A4 suggest / external stage / internal-reversible execute) to `self._notice_sink(f"WOULD <action>: {rule.name}")` and perform NO stage/execute/suggest; in `live`, keep today's behaviour verbatim. Ensure `record_refire` for stateful rules still runs in observe. — files: `src/artemis/reactions/dispatcher.py` — done when: in `observe`, no `_stage`/`spec.callable_ref`/`_suggest_email_task` call occurs but a `WOULD …` notice is emitted and the ledger is still written; in `live`, behaviour is byte-identical to before.
- [ ] Task 3: Create `compose_reactions(...)` in a new `src/artemis/reactions/compose.py`. It constructs `EventBus`, `ReactionLedger(settings, key_provider)`, `ReactionRuleStore(recipe_store, promoter, builtins=TIER_A_BUILTINS)`, and `ReactionDispatcher(bus, rule_store, ledger, registry, staging, capture_service=…, notice_sink=…, mode=get_runtime_config().reaction.reactions_mode)`; calls `register_planning_reactions`, `register_comms_reactions`, `register_self_reactions(emit=bus.emit, …)` threading the injected seams; returns `(bus, dispatcher.drain_once)`. Add a module docstring documenting the intended `compose_proactive(pre_tick_steps=[pre_tick_step])` wiring. — files: `src/artemis/reactions/compose.py` — done when: `compose_reactions(...)` returns an `EventBus` and an `async`-callable `pre_tick_step`, and all three packs have registered their tools on the registry.
- [ ] Task 4: Re-export `compose_reactions` from the package via the existing lazy `__getattr__` (add to `__all__` and a branch). — files: `src/artemis/reactions/__init__.py` — done when: `from artemis.reactions import compose_reactions` succeeds.
- [ ] Task 5: Write `tests/test_reactions_compose.py` covering: (a) observe mode — a matching event drains with no stage/execute/suggest but a `WOULD …` notice and a ledger row; (b) live mode — the same event performs the real effect (e.g. internal-reversible execute records `Auto: … (undoable)`); (c) `compose_reactions` builds the graph, registers all three packs (assert the recipe tool refs are present on the registry), and returns a usable `(bus, pre_tick_step)` where `bus.emit(event)` then `await pre_tick_step()` processes the event. — files: `tests/test_reactions_compose.py` — done when: `uv run pytest -q tests/test_reactions_compose.py` passes.

## Wave plan
Wave 1: [Task 1, Task 2] | Wave 2: [Task 3, Task 4] | Wave 3: [Task 5]

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | `src/artemis/reactions/compose.py`, `tests/test_reactions_compose.py` |
| Modify | `src/artemis/reactions/dispatcher.py`, `src/artemis/runtime_config.py`, `src/artemis/reactions/__init__.py` |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy` | Full-project type check. |
| `uv run ruff check . && uv run ruff format --check .` | Lint + format check. |
| `uv run pytest -q` | Full test suite. |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | `src/artemis/reactions/compose.py src/artemis/reactions/dispatcher.py src/artemis/runtime_config.py src/artemis/reactions/__init__.py tests/test_reactions_compose.py` |
| `git commit` | "feat: R1 reactions composition root + observe-mode go-live gate" |

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
`cross_model_review: true` — first time reactions are composed end-to-end toward acting on live email/finance. Observe mode is the safety wall: default `reactions_mode="observe"` means no stage/write/suggest until an explicit config flip. Reviewer must confirm: (1) observe suppresses ALL four effect paths (stage / tool-execute / A4 suggest / internal-reversible execute); (2) A4-inert invariant is preserved in `live` (email_to_task can never stage/execute); (3) the real staging/capture/notice services are injected, never fakes, in production callers.

### Performance
(none — emit is sync/enqueue-cheap; drain runs on the heartbeat tick per ADR-032 Decision 2.)

### Accessibility
(none — no frontend change.)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | `src/artemis/reactions/compose.py` | Module docstring documenting the intended heartbeat `pre_tick_steps` wiring; docstring on `compose_reactions`. |
| ADR | docs/technical/adr/ADR-032-reactions-runtime-composition.md | Already written (this spec implements Decisions 1, 2, 4). No change. |

## Acceptance Criteria
- [ ] Add `reactions_mode` to `ReactionConfig` → verify: `RuntimeConfig().reaction.reactions_mode == "observe"`; constructing `ReactionConfig(reactions_mode="bogus")` raises a validation error.
- [ ] Observe-mode gate → verify: with `mode="observe"`, draining a matching internal-reversible event makes no `_stage`/`callable_ref`/`_suggest_email_task` call, emits exactly one `WOULD …: <rule>` notice, and writes the ledger row (a second drain of the same event emits no further notice).
- [ ] Live-mode unchanged → verify: with `mode="live"`, the same event performs the real effect and emits `Auto: <rule> fired (undoable)` (or stages, for an external-effect rule) — identical to pre-change behaviour.
- [ ] `compose_reactions` graph → verify: returns `(EventBus, pre_tick_step)`; after `bus.emit(event); await pre_tick_step()` the event is processed; the registry contains the recipe tool refs from all three packs (e.g. `reaction:email_to_held_event`, `tasks.create_from_bill`, `reaction:trip_airport_block`).
- [ ] `uv run mypy` → verify: no new errors.
- [ ] `uv run ruff check . && uv run ruff format --check .` → verify: clean.
- [ ] `uv run pytest -q` → verify: full suite green.

## Progress
_(Coding mode writes here — do not edit manually)_
