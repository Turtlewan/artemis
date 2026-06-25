---
spec: R1-reactions-compose
status: ready
cross_model_review: true
token_profile: balanced
autonomy_level: L2
---

# Spec: R1 — Reactions composition root + dispatcher safety rework (worker / observe / at-least-once / cascade-depth)

**Identity:** Builds the `compose_reactions` root that wires `EventBus → ReactionLedger → ReactionRuleStore → ReactionDispatcher`, registers all three recipe packs, and owns the continuous bounded worker. Reworks the dispatcher to the ADR-032 amendment: observe-mode gate (Fork 3), effect-then-claim at-least-once delivery + ledger TTL (Fork 4), and a `DomainEvent.depth` cascade guard (Fork 6). Adds `reactions_mode` + `max_reaction_depth` to `RuntimeConfig`. Foundation for R2/R5d/R6c.
<!-- → why: see docs/technical/adr/ADR-032-reactions-runtime-composition.md (§ Amendment: Forks 2/3/4/6; Decisions 1,2,4). -->

## Assumptions
<!-- Coding mode verifies each item against the codebase before executing. -->
- `ReactionConfig` (`runtime_config.py:193`) is the home for the two new fields — it already carries reaction tunables (`fraud_confirm_*`, `maps_*_buffer_minutes`), is frozen with `extra="forbid"`, and uses the `Field(default=…, description=…)` + `@field_validator` pattern. Add `reactions_mode` and `max_reaction_depth` there, after `maps_domestic_buffer_minutes`. → impact: Stop (a new sub-model would change the access path `get_runtime_config().reaction.*`).
- The dispatcher already exposes BOTH `drain_once` and `run_forever` over an `asyncio.Queue`, and `_enqueue` is the sync `EventBus` subscriber shim (`dispatcher.py:49-61,74-114`). Fork 2's "continuous bounded worker" therefore = (a) bound the queue with `maxsize`, (b) make `_enqueue` catch `QueueFull` (drop+log, never block the emitter), (c) keep `run_forever` as the worker body, (d) have `compose_reactions` own the worker task (create/cancel) + expose a `start()/stop()` or return the coroutine for an owner to mount. → impact: Caution (if a caller already mounts `run_forever`, compose only needs to construct + return it).
- The current `_fire` claims BEFORE the effect (`try_claim` at `dispatcher.py:132`, claim retained even if the callable raises = at-most-once). Fork 4 inverts this to **effect-then-claim** for fire-once rules: read whether already fired → skip if so; run the effect; commit the claim only AFTER the effect returns without raising. Stateful rules already record AFTER the effect (`record_refire` at `:149-150`) — that ordering is kept. → impact: Stop (this is the core delivery-semantics change; getting the order wrong reintroduces silent drops or double-claims).
- Single-consumer invariant holds: exactly one worker drains the queue (compose owns the one worker task), so the effect-then-claim read/commit pair has no concurrent racer — the research pass confirmed the stateful-atomicity TOCTOU is a non-issue under single-consumer. → impact: Stop (a multi-worker deployment would need an atomic claim; out of scope, single-owner hub).
- `DomainEvent` is frozen (`emit.py:39`), so depth stamping must use `model_copy(update={"depth": …})`, never in-place mutation. Producers construct events at the default `depth=0`. → impact: Stop.
- Depth is stamped via a `ContextVar` set by the dispatcher around each handler invocation + a stamping `emit` wrapper installed by `compose_reactions` (see Exact changes). The recipe packs keep their existing registration-time `emit=` seam — no per-call signature change. → impact: Caution (the alternative, threading `emit` into every recipe call, churns every recipe signature; rejected).
- `compose_reactions` is a thin wiring root with INJECTED domain seams (the recipe packs need `capture_service`, `calendar_from_extract_fn`, `trip_assembler`, `get_linked_task_ref_fn`, `fetch_extract`, `memory`, `complete_task_fn`, etc.); compose itself constructs only `EventBus`, `ReactionLedger`, `ReactionRuleStore`, `ReactionDispatcher`, the stamping emit, and the worker. Producer-emit wiring (gmail/calendar/finance/trips) is R2's job; comms fetch-via-ref + gift is R6c. → impact: Caution (this spec satisfies the self-pack `emit` seam with the stamping emit; it does not wire producers).
- In `observe` mode the dispatcher does NOT write the durable ledger. Writing fire-once claims during a dry-run would permanently dedup those reactions out of `live` — they would never fire after the flip (security-review BLOCK). Observe uses an in-memory `self._observed: set[str]` (keyed by the stable key, discarded on restart) ONLY to avoid duplicate `WOULD` notices within a session, runs NO handler effect, and routes each would-be effect to `notice_sink` as `WOULD <action>: <rule>` (Fork 3 guardrail b: one stream, WOULD/DID tags). The durable claim/refire commits ONLY in `live`. → impact: Stop (committing the ledger in observe poisons live).
- `reaction_depth` is an asyncio `ContextVar`; a child task created via `asyncio.create_task` inside a handler INHERITS the parent's depth (context copy), so a re-emit from a spawned task is stamped at the inherited depth — depth is preserved, not bypassed. The AUTHORITATIVE cascade guard is the queue-level check on the dequeued `event.depth` (events at/over `max_reaction_depth` are dropped before rule lookup); the contextvar is a best-effort stamp. Handlers invoked from `_fire` SHOULD use direct `await`, not detached fire-and-forget `create_task`, so the `finally` reset scopes correctly. → impact: Caution (documents the create_task interaction; the queue-level guard is the real wall).

Simplicity check: considered (a) a separate `ReactionsConfig` sub-model — rejected, `ReactionConfig` already exists and is the right home; (b) per-call `emit` injection for depth — rejected, churns every recipe; (c) a config field for the ledger TTL — rejected for now, TTL is a ledger-internal constant (`_LEDGER_TTL_DAYS`) with a `prune_older_than` method, surfaced as config only if the owner later wants to tune it.

## Prerequisites
- Specs that must be complete first: none (foundation).
- Environment setup required: none (existing `uv` toolchain).

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| `src/artemis/runtime_config.py` | modify | Add `reactions_mode: Literal["observe","live"] = "observe"` + `max_reaction_depth: int = 5` to `ReactionConfig` (+ validators). |
| `src/artemis/reactions/emit.py` | modify | Add `depth: int = 0` to `DomainEvent`; add a module-level `reaction_depth` `ContextVar`; add a `depth_stamping_emit(bus)` factory. |
| `src/artemis/reactions/ledger.py` | modify | Add `has_fired(rule, key) -> bool` (fire-once read) + `prune_older_than(cutoff_iso)` (TTL prune) + `_LEDGER_TTL_DAYS` constant. |
| `src/artemis/reactions/dispatcher.py` | modify | Bounded queue + `QueueFull` catch; observe-mode gate; effect-then-claim in `_fire`; depth guard + contextvar set around handler; per-wake TTL prune. |
| `src/artemis/reactions/compose.py` | create | `compose_reactions(...)` wiring root; constructs the graph, stamping emit, and the bounded worker; returns `(bus, dispatcher, worker_coro)`. |
| `src/artemis/reactions/__init__.py` | modify | Lazy re-export `compose_reactions` (existing `__getattr__` pattern). |
| `tests/test_reactions_compose.py` | create | observe/live, effect-then-claim retry, depth-guard, bounded-queue, compose-graph tests. |

## Tasks
- [ ] Task 1: Add config fields. In `ReactionConfig` add `reactions_mode: Literal["observe","live"] = Field(default="observe", description="ADR-032 Fork 3 go-live gate: observe = dry-run (WOULD only), live = act.")` and `max_reaction_depth: int = Field(default=5, description="ADR-032 Fork 6 cascade guard: max reaction event-hops before drop.")`; import `Literal`; add a `@field_validator("max_reaction_depth")` rejecting `< 1`. — files: `src/artemis/runtime_config.py` — done when: `RuntimeConfig().reaction.reactions_mode == "observe"`, `.max_reaction_depth == 5`; `ReactionConfig(reactions_mode="bogus")` and `ReactionConfig(max_reaction_depth=0)` both raise.
- [ ] Task 2: `DomainEvent.depth` + stamping primitives. In `emit.py`: add `depth: int = 0` field to `DomainEvent` (after `dedup_key`); add module-level `reaction_depth: ContextVar[int | None] = ContextVar("reaction_depth", default=None)`; add `def depth_stamping_emit(bus: EventBus) -> Callable[[DomainEvent], None]` that reads `reaction_depth.get()` and, when not `None`, re-emits `event.model_copy(update={"depth": current + 1})`, else emits unchanged. — files: `src/artemis/reactions/emit.py` — done when: a producer `bus.emit(ev)` outside any fire leaves `depth==0`; `depth_stamping_emit` stamps `current+1` when the contextvar is set.
- [ ] Task 3: Ledger at-least-once support + TTL. In `ledger.py`: add `_LEDGER_TTL_DAYS = 90`; add `has_fired(self, rule_name, stable_key) -> bool` (SELECT 1 … fire-once existence); add `prune_older_than(self, cutoff_iso: str) -> int` (DELETE WHERE last_fired_at < ? ; return rowcount). — files: `src/artemis/reactions/ledger.py` — done when: `has_fired` returns False before / True after `try_claim`; `prune_older_than` deletes only rows older than the cutoff and returns the count.
- [ ] Task 4: Dispatcher rework. (a) Bounded queue: `asyncio.Queue(maxsize=…)` (maxsize from a `max_queue` ctor param, default 1000); `_enqueue` wraps `put_nowait` in `try/except asyncio.QueueFull` → log warning + drop (never block). (b) Depth guard (AUTHORITATIVE): in the per-event loop of `drain_once` and `run_forever`, if `event.depth >= self._max_depth` → log + skip (do not look up rules). (c) Effect-then-claim in `_fire` (LIVE, fire-once branch): `if self._ledger.has_fired(rule.name, key): return` BEFORE the effect, and call `self._ledger.try_claim(rule.name, key, now=now)` AFTER the effect block completes without raising; on exception the claim is NOT written (re-fires next time). Stateful branch: state-hash compare before, `record_refire` after. (d) Contextvar: wrap the LIVE effect dispatch in `token = reaction_depth.set(event.depth)` / `reaction_depth.reset(token)` (finally) so any handler re-emit is stamped `depth+1`. (e) Observe gate: kw-only ctor params `mode: Literal["observe","live"] = "observe"`, `max_depth: int = 5`, `max_queue: int = 1000`; ctor RAISES `ValueError` if `mode=="observe" and notice_sink is None`. In `observe`, run NO handler effect and write NO durable ledger row — use an in-memory `self._observed: set[str]` (keyed by stable key) for intra-session WOULD dedup, and emit one `WOULD <suggest|stage|execute>: {rule.name}` per first sighting. (f) Per-wake TTL prune: module constant `_PRUNE_EVERY_N_WAKES = 500`; at the top of `drain_once` and once every `_PRUNE_EVERY_N_WAKES` `run_forever` wakes, call `self._ledger.prune_older_than((datetime.now(UTC) - timedelta(days=_LEDGER_TTL_DAYS)).isoformat())` (UTC ISO cutoff, matching how `last_fired_at` is written). (g) Single-consumer guard: a `_worker_started` flag; `run_forever`/`start` raises `RuntimeError` if a second worker is started against the same dispatcher. — files: `src/artemis/reactions/dispatcher.py` — done when: see Acceptance Criteria; `live` behaviour matches the prior effect set EXCEPT the claim now lands after a successful effect (retry test), and observe writes nothing durable.
- [ ] Task 5: `compose_reactions`. Create `src/artemis/reactions/compose.py` with `compose_reactions(*, recipe_store, promoter, registry, staging, capture_service, calendar_from_extract_fn, trip_assembler, get_linked_task_ref_fn, fetch_extract, memory, complete_task_fn, settings, key_provider) -> tuple[EventBus, ReactionDispatcher, Coroutine]`. It: builds `EventBus`; `stamped_emit = depth_stamping_emit(bus)`; `ledger = ReactionLedger(settings, key_provider)`; `rule_store = ReactionRuleStore(recipe_store, promoter, builtins=TIER_A_BUILTINS)`; `cfg = get_runtime_config().reaction`; `dispatcher = ReactionDispatcher(bus, rule_store, ledger, registry, staging, capture_service=capture_service, notice_sink=…, mode=cfg.reactions_mode, max_depth=cfg.max_reaction_depth)`; calls `register_planning_reactions(...)`, `register_comms_reactions(..., fetch_extract=fetch_extract, memory=memory)`, `register_self_reactions(..., emit=stamped_emit, get_linked_task_ref_fn=get_linked_task_ref_fn, complete_task_fn=complete_task_fn)`; returns `(bus, dispatcher, dispatcher.run_forever())`. Module docstring documents the intended app-root mount (run the worker coro as a task; pass `bus.emit`/`stamped_emit` to producers — R2). Use the EXACT registration signatures the live packs expose; thread only the seams each pack actually takes. — files: `src/artemis/reactions/compose.py` — done when: `compose_reactions(...)` returns a 3-tuple, all three packs register their tools on the registry, and the returned worker coro processes an emitted event when awaited/driven.
- [ ] Task 6: Re-export. Add `compose_reactions` to `__all__` + a lazy `__getattr__` branch in `reactions/__init__.py`. — files: `src/artemis/reactions/__init__.py` — done when: `from artemis.reactions import compose_reactions` succeeds.
- [ ] Task 7: Tests. `tests/test_reactions_compose.py`: (a) observe — matching internal-reversible event → no execute/stage/suggest, exactly one `WOULD …: <rule>` notice, and NO durable ledger row (`has_fired` stays False), second drain of same event = no further notice (in-memory dedup); (b) live — same event executes the real effect + `Auto: <rule> fired (undoable)` and `has_fired` becomes True; (c) effect-then-claim retry — a handler that raises on first drain leaves NO claim (`has_fired` False) and re-fires + succeeds on the second drain; (d) depth guard — an event at `depth == max_depth` is dropped (no rules fire) + logged; a self-pack re-emit during a fire is stamped `depth+1`; (e) bounded queue — `QueueFull` on overflow is caught (emit never raises); (f) compose graph — `compose_reactions(...)` registers all three packs and the worker processes `bus.emit(event)`; (g) ctor guards — `mode="observe"` with `notice_sink=None` raises `ValueError`; starting a second worker on one dispatcher raises `RuntimeError`. — files: `tests/test_reactions_compose.py` — done when: `uv run pytest -q tests/test_reactions_compose.py` passes.

## Wave plan
Wave 1: [Task 1, Task 2, Task 3] | Wave 2: [Task 4] | Wave 3: [Task 5, Task 6] | Wave 4: [Task 7]

## Exact changes (subtle mechanisms)

### `_fire` — observe (no ledger) vs live (effect-then-claim) (dispatcher.py)
```python
key = self._stable_key(rule, event)
now = _now_iso()
try:
    args = _reaction_args(event)

    # OBSERVE: dry-run only. NEVER touch the durable ledger (writing would poison live).
    if self._mode == "observe":
        if key in self._observed:          # in-memory, discarded on restart
            return
        self._observed.add(key)
        self._notice_would(rule)           # WOULD <suggest|stage|execute>: <rule>
        return                             # no handler runs in observe -> no re-emit

    # LIVE: effect-then-claim (at-least-once).
    state_hash: str | None = None
    if rule.stateful:
        state_hash = _state_hash(args)
        if self._ledger.state_hash(rule.name, key) == state_hash:
            return
    elif self._ledger.has_fired(rule.name, key):   # read first
        return

    token = reaction_depth.set(event.depth)         # stamp any handler re-emit to depth+1
    try:
        if rule.reaction_ref == _A4_REACTION_REF:
            await self._suggest_email_task(args)
        elif rule.external_effect:
            self._stage(rule, args)
        else:
            spec = self._registry.get_tool(rule.reaction_ref)
            await spec.callable_ref(spec.args_schema.model_validate(args))
            if self._notice_sink is not None:
                self._notice_sink(f"Auto: {rule.name} fired (undoable)")
    finally:
        reaction_depth.reset(token)

    # commit the claim ONLY after the effect returned without raising (at-least-once on failure)
    if rule.stateful:
        self._ledger.record_refire(rule.name, key, now=now, state_hash=state_hash)
    else:
        self._ledger.try_claim(rule.name, key, now=now)
except Exception:
    self._log.warning("reaction %s failed for %s", rule.name, event.event_type, exc_info=True)
```
(`_notice_would` emits `WOULD <action>: {rule.name}` where `<action>` is `suggest`/`stage`/`execute` per the rule's branch, so the WOULD/DID stream tags effect type. Observe writes NO durable ledger row — only the in-memory `_observed` set.)

### ctor guards + constants (dispatcher.py)
```python
# in __init__ (kw-only): mode, max_depth, max_queue=1000
if mode == "observe" and notice_sink is None:
    raise ValueError("notice_sink is required when mode='observe' (the WOULD audit trail)")
self._observed: set[str] = set()
self._worker_started = False     # single-consumer guard (see run_forever)
# run_forever / start: refuse a second worker on the same dispatcher
if self._worker_started:
    raise RuntimeError("ReactionDispatcher worker already started (single-consumer invariant)")
self._worker_started = True
```
TTL prune cadence: module constant `_PRUNE_EVERY_N_WAKES = 500`; the worker calls `self._ledger.prune_older_than((datetime.now(UTC) - timedelta(days=_LEDGER_TTL_DAYS)).isoformat())` once every `_PRUNE_EVERY_N_WAKES` wakes (and once at the top of `drain_once`). The cutoff is computed in UTC ISO to match how `try_claim`/`record_refire` write `last_fired_at`.

### depth stamping (emit.py)
```python
reaction_depth: ContextVar[int | None] = ContextVar("reaction_depth", default=None)

def depth_stamping_emit(bus: EventBus) -> Callable[[DomainEvent], None]:
    def _emit(event: DomainEvent) -> None:
        current = reaction_depth.get()
        if current is not None:
            event = event.model_copy(update={"depth": current + 1})
        bus.emit(event)
    return _emit
```

### bounded enqueue (dispatcher.py)
```python
def _enqueue(self, event: DomainEvent) -> None:
    try:
        self._queue.put_nowait(event)
    except asyncio.QueueFull:
        self._log.warning("reaction queue full; dropping %s", event.event_type)
```

## Permissions

The following actions will run autonomously during build. Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | `src/artemis/reactions/compose.py`, `tests/test_reactions_compose.py` |
| Modify | `src/artemis/runtime_config.py`, `src/artemis/reactions/emit.py`, `src/artemis/reactions/ledger.py`, `src/artemis/reactions/dispatcher.py`, `src/artemis/reactions/__init__.py` |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy` | Full-project type check (host re-verify). |
| `uv run ruff check . && uv run ruff format --check .` | Lint + format gate. |
| `uv run pytest -q` | Full test suite. |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | The seven files above, by name. |
| `git commit` | "feat: R1 reactions composition root + dispatcher safety rework (worker/observe/at-least-once/depth)" |

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
`cross_model_review: true` — this spec changes reaction delivery semantics and is the go-live safety wall. Reviewer must confirm: (1) `observe` (default) suppresses ALL four effect paths (stage / tool-execute / A4 suggest / internal-reversible execute) while still recording dedup; (2) the A4-inert invariant holds in `live` (email_to_task can never stage/execute — only inert suggest); (3) effect-then-claim never double-acts a fire-once reaction under the single-consumer worker, and never permanently swallows a failed one (at-least-once); (4) the depth guard cannot be bypassed by a handler re-emit (stamping happens inside the fire's contextvar scope); (5) the bounded-queue overflow drops + logs and never blocks the emitter.

### Performance
(none — emit is sync enqueue; the worker drains async; TTL prune is gated to once-per-N-wakes.)

### Accessibility
(none — no frontend change.)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | `src/artemis/reactions/compose.py` | Module docstring documenting the app-root worker mount + producer-emit wiring (R2). |
| Inline | `src/artemis/reactions/dispatcher.py` | Update the class docstring: at-most-once → effect-then-claim at-least-once; observe gate; depth guard. |
| ADR | docs/technical/adr/ADR-032-reactions-runtime-composition.md | Already amended (this spec implements § Amendment Forks 2/3/4/6). No change. |
| Reconcile | docs/technical/architecture/data-model.md | Verify the reaction ledger (now with TTL prune + `has_fired`) is reflected; no new entity expected (ledger ops only). |

## Acceptance Criteria
- [ ] Config fields → verify: `RuntimeConfig().reaction.reactions_mode == "observe"` and `.max_reaction_depth == 5`; `ReactionConfig(reactions_mode="bogus")` and `ReactionConfig(max_reaction_depth=0)` raise.
- [ ] Observe gate → verify: `mode="observe"` draining a matching internal-reversible event makes no execute/stage/suggest call, emits exactly one `WOULD …: <rule>` notice, and writes NO durable ledger row (`has_fired` stays False so `live` can still fire it); a second drain emits no further notice (in-memory dedup). `mode="observe"` + `notice_sink=None` raises `ValueError`; a second worker on one dispatcher raises `RuntimeError`.
- [ ] Live unchanged (except claim timing) → verify: `mode="live"` performs the real effect + `Auto: <rule> fired (undoable)`.
- [ ] Effect-then-claim at-least-once → verify: a handler raising on the first drain leaves `has_fired` False; re-draining the same event re-fires and (on success) commits the claim.
- [ ] Cascade depth guard → verify: an event with `depth == max_reaction_depth` fires no rules and is logged; a self-pack re-emit inside a fire is stamped `depth+1`.
- [ ] Bounded queue → verify: enqueuing past `maxsize` is caught (emit raises nothing) and logged.
- [ ] Ledger TTL → verify: `prune_older_than(cutoff)` deletes only older rows; `has_fired` reflects claims.
- [ ] `compose_reactions` graph → verify: returns `(bus, dispatcher, worker_coro)`; all three packs' tool refs are on the registry; driving the worker after `bus.emit(event)` processes the event.
- [ ] Whole project clean → verify: `uv run mypy`, `uv run ruff check . && uv run ruff format --check .`, `uv run pytest -q` all pass.

## Progress
_(Coding mode writes here — do not edit manually)_
