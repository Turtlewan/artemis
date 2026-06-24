---
spec: rxn-dispatcher
status: ready
token_profile: balanced
autonomy_level: L2
cross_model_review: true
---
<!-- Wave R · reaction infra piece (iii) — Decision 3-iii. The dispatcher: subscribes to emitted events,
     matches rules, fires reaction callables (async, ADR-016). Thin idempotency/last-fire ledger (I-8=C).
     GATE posture (I-10): internal/reversible → auto + undoable notice; external-effect → ActionStagingService.
     A4 (email→task suggestion via CaptureService) = the first/proof consumer. cross_model_review: true. -->

# Spec: RXN-dispatcher — reaction dispatcher (event→rule match → fire, idempotency ledger, GATE routing)

**Identity:** The reaction layer's runtime — an async dispatcher that drains emitted `DomainEvent`s, resolves matching `ReactionRule`s from the rule store, and fires each reaction exactly-once-per-stable-key: internal/reversible reactions run directly (with a passive undoable notice), external-effect reactions route through `ActionStagingService` (GATE). It keeps ONLY a thin idempotency/last-fire ledger; the spoke owns domain state.
→ why: see docs/technical/adr/ADR-021-cross-module-reactions.md (Decision 3-iii dispatcher · Decision 5 stateful/windowed · GATE posture I-10 · I-8=C ledger) · docs/changes/GATE-a-action-staging.md (ActionStagingService).

<!-- ONE logical phase: the dispatcher loop + the idempotency ledger + the GATE/auto routing branch. 2 src
     files (dispatcher + ledger) + 1 test. Depends on RXN-emit + RXN-rulestore + GATE-a + M8-d-c2 CaptureService.
     A4 (email→task inert suggestion) is the first consumer — the zero-risk proof reaction (R3 mitigation). -->

## Assumptions

- **RXN-emit** complete: `DomainEvent`, `EventType`, `EventBus` (`subscribe(sink)`). The dispatcher registers a sync enqueue shim with the bus that `put_nowait`s onto an `asyncio.Queue`; a drain coroutine consumes it. → impact: Stop (this is the sync-emit → async-dispatch bridge named in RXN-emit's assumptions).
- **RXN-rulestore** complete: `ReactionRule` (`tier`, `external_effect`, `reaction_ref`, `dedup_key_fields`, `stateful`), `ReactionRuleStore.rules_for(event_type)`. The dispatcher calls `rules_for` per event. → impact: Stop.
- **GATE-a** complete: `ActionStagingService.stage(module, tool, args, summary, *, ttl) -> PendingAction`. External-effect reactions stage here (the owner approves in Review). → impact: Stop (the dispatcher NEVER executes an external effect directly — it stages).
- **M1-a** complete: `ToolRegistry.get_tool(fq_id) -> ToolSpec`, `ToolSpec.callable_ref: Callable[..., Awaitable[BaseModel]]` (async, ADR-016), `ToolSpec.args_schema`. Internal/reversible reactions dispatch via `await get_tool(rule.reaction_ref).callable_ref(args)`. → impact: Stop.
- **M8-d-c2** complete: `CaptureService` (`suggest_from_text`/`accept_with_graduation`) — **A4 (email→task) reuses CaptureService** to produce an inert task suggestion (ADR-021 I-1: email→task = inert suggestion via the existing CaptureService, owner accepts). The dispatcher's A4 reaction callable calls `CaptureService.suggest_from_text` — it does NOT create a task directly. → impact: Stop (A4 is the proof consumer; it is structurally inert).
- **M2-b/c** complete (stub on dev): the idempotency ledger is a small owner-private SQLCipher table (`reaction_ledger`) opened via the M8-d-a `_connect()` pattern (`key.as_hex()` local-only, plain-sqlite fallback off-hardware). It stores ONLY dedup keys + last-fire timestamps + a stateful-reaction state hash — NOT domain rows (I-8=C: the spoke owns domain state). → impact: Stop.
- **X3 runtime-config** complete: the dispatcher reads no tunables directly; the reconciler (RXN-reconciler) reads X3. The dispatcher's only timing is event-driven. → impact: Low.
- **Idempotency (load-bearing — agent-loop-reliability):** a reaction fires at most once per `(rule.name, stable_key)` where `stable_key` is built from `rule.dedup_key_fields` over the event payload/entity-refs. The ledger's `INSERT OR IGNORE` on the composite key is the dedup wall — an overlapping/re-delivered event never double-fires (the named 2026 failure mode). For a `stateful` rule (Decision 5), re-fire is allowed but is an UPDATE keyed on the stable key (re-fire updates the windowed state hash, never duplicates a row/effect). → impact: Stop (this is the correctness core; the test suite asserts both the dedup and the stateful-update paths).
- Off-hardware: in-process `EventBus` + `FakeRuleStore` + `FakeToolRegistry` (async spy callables) + `FakeActionStagingService` (records `stage` calls) + `FakeCaptureService` + ledger over a temp sqlite. Deterministic, no model, no network. → impact: Low.

Simplicity check: considered the dispatcher owning domain state for stateful reactions (e.g. holding the Trip assembly) — rejected per I-8=C; the spoke owns domain state, the dispatcher keeps only a dedup/last-fire ledger keyed by stable key. Considered a separate gate for reactions — rejected; external-effect reactions reuse the GATE `ActionStagingService` (ADR-021: GATE is wired but rarely hit since today's set is almost all internal/reversible). The minimum is: a drain loop + a `_fire(rule, event)` that branches auto-vs-GATE + a thin ledger.

## Prerequisites

- Specs complete: **RXN-emit**, **RXN-rulestore**, **GATE-a**, **M1-a** (ToolRegistry), **M2-b/c** (stub), **M8-d-c2** (CaptureService).
- Environment: no new PyPI deps (stdlib `asyncio` + the SQLCipher binding via M2-c). An async test runner (`anyio`/`pytest-asyncio`) — flag if absent (same note as GATE-a).

## Files to Change

| File | Operation | Notes |
|------|-----------|-------|
| `/Users/artemis-build/artemis/src/artemis/reactions/ledger.py` | create | `ReactionLedger` — owner-private SQLCipher dedup/last-fire/state table + `try_claim`/`record_fire`/`update_state` |
| `/Users/artemis-build/artemis/src/artemis/reactions/dispatcher.py` | create | `ReactionDispatcher` — bus shim + drain loop + `_fire` (auto-vs-GATE branch) + stable-key builder |
| `/Users/artemis-build/artemis/src/artemis/reactions/__init__.py` | modify | re-export `ReactionDispatcher`, `ReactionLedger` |
| `/Users/artemis-build/artemis/tests/test_reactions_dispatcher.py` | create | dedup (no double-fire), stateful re-fire-as-update, auto-vs-GATE routing, A4 CaptureService proof, degrade-don't-crash |

All paths under `/Users/artemis-build/artemis/`.

## Tasks

- [ ] **Task 1: Implement `ReactionLedger`** — files: `/Users/artemis-build/artemis/src/artemis/reactions/ledger.py` —

  `class ReactionLedger(settings, key_provider)` — owner-private SQLCipher, M8-d-a `_connect()` pattern exactly (`key = key_provider.dek_for_scope(OWNER_PRIVATE)`, `key_hex` local-only, plain-sqlite fallback off-hardware). Schema:
  ```sql
  CREATE TABLE IF NOT EXISTS reaction_ledger (
      rule_name TEXT NOT NULL,
      stable_key TEXT NOT NULL,
      first_fired_at TEXT NOT NULL,
      last_fired_at TEXT NOT NULL,
      fire_count INTEGER NOT NULL DEFAULT 1,
      state_hash TEXT,                       -- windowed/stateful reaction state digest (NULL for fire-once)
      PRIMARY KEY (rule_name, stable_key)
  );
  ```
  Methods (all sync SQLCipher — called inside the dispatcher's async `_fire`):
  - `def try_claim(self, rule_name: str, stable_key: str, *, now: str) -> bool`: `INSERT OR IGNORE` the `(rule_name, stable_key)` row with `first_fired_at=last_fired_at=now, fire_count=1`. Return `True` if the row was newly inserted (claim won → fire), `False` if it already existed (already fired → skip). This is the **fire-once dedup wall**.
  - `def record_refire(self, rule_name: str, stable_key: str, *, now: str, state_hash: str | None = None) -> None`: for a `stateful` rule — `UPDATE ... SET last_fired_at=now, fire_count=fire_count+1, state_hash=? WHERE rule_name=? AND stable_key=?` (re-fire = update, never a new row). If the row doesn't exist yet, insert it (the first occurrence of a stateful reaction).
  - `def state_hash(self, rule_name: str, stable_key: str) -> str | None`: read the current state hash (so a stateful reaction can detect "no change → skip the update").

  — done when: `uv run mypy --strict src` passes; `try_claim` returns `True` the first time and `False` the second time for the same key; `record_refire` increments `fire_count` + updates `state_hash` without adding a row; `ScopeLockedError` propagates from a locked provider.

- [ ] **Task 2: Implement `ReactionDispatcher`** — files: `/Users/artemis-build/artemis/src/artemis/reactions/dispatcher.py` —

  ```python
  class ReactionDispatcher:
      def __init__(self, bus: EventBus, rule_store: ReactionRuleStore, ledger: ReactionLedger,
                   tool_registry: ToolRegistry, staging: ActionStagingService,
                   *, capture_service: CaptureService | None = None,
                   notice_sink: Callable[[str], None] | None = None,
                   logger: logging.Logger | None = None) -> None:
          self._queue: asyncio.Queue[DomainEvent] = asyncio.Queue()
          bus.subscribe(self._enqueue)        # the sync shim RXN-emit's bus calls
          ...

      def _enqueue(self, event: DomainEvent) -> None:
          """Sync shim registered with the EventBus — non-blocking put."""
          self._queue.put_nowait(event)

      def _stable_key(self, rule: ReactionRule, event: DomainEvent) -> str:
          """Compose the dedup key from rule.dedup_key_fields over the event payload + entity_refs +
          the event's own dedup_key. Deterministic, order-stable."""
          parts = [rule.name]
          for f in rule.dedup_key_fields:
              parts.append(str(event.payload.get(f, "")) or _entity_ref_value(event, f))
          parts.append(event.dedup_key)       # the producer's own idempotency value
          return ":".join(parts)

      async def drain_once(self) -> int:
          """Drain all currently-queued events, firing matched reactions. Returns # events processed.
          (run_forever loops this; tests call it directly for determinism.)"""

      async def _fire(self, rule: ReactionRule, event: DomainEvent) -> None: ...
  ```

  **`_fire` logic (the core):**
  1. `key = self._stable_key(rule, event)`; `now = now_iso()`.
  2. **Idempotency:**
     - non-stateful rule: `if not self._ledger.try_claim(rule.name, key, now=now): return` (already fired → skip).
     - stateful rule: compute the new `state_hash` from the event; `if self._ledger.state_hash(rule.name, key) == new_hash: return` (no change → skip); else proceed and `record_refire(..., state_hash=new_hash)` AFTER the effect.
  3. **Build the reaction args** from the event (payload + entity_refs — the per-recipe specs define the exact mapping per `reaction_ref`; the dispatcher passes a typed `dict[str, object]`).
  4. **Route by `external_effect`:**
     - **internal/reversible (`external_effect=False`):** `spec = self._registry.get_tool(rule.reaction_ref)`; `await spec.callable_ref(spec.args_schema.model_validate(args))` (ADR-016 async). On success, emit a **passive undoable notice** via `notice_sink(f"Auto: {rule.name} fired (undoable)")` (I-10: internal/reversible acts automatically with an undoable notice — NOT a blocking gate). For the **A4 special case** (`rule.reaction_ref` is the capture path), call `self._capture_service.suggest_from_text(...)` instead — the reaction produces an INERT suggestion, never a direct write (ADR-021 I-1).
     - **external-effect (`external_effect=True`):** `self._staging.stage(module=rule.reaction_ref.split(".")[0], tool=rule.reaction_ref, args=args, summary=<deterministic summary>)` — the reaction is STAGED for owner approval in Review (GATE), NEVER executed directly (I-10).
  5. **Record:** for a non-stateful rule the `try_claim` already recorded the fire; for a stateful rule call `record_refire(..., state_hash=new_hash)`.
  6. **Degrade-don't-crash:** wrap `_fire` body in try/except → log + continue; one failing reaction never aborts the drain or other reactions. If a reaction raised AFTER `try_claim` for a non-stateful rule, leave the claim (at-most-once — a retried reaction must not re-fire; the failure is surfaced via the notice/log, recovered by the link-integrity reconciler, RXN-reconciler).

  `drain_once`: pop every queued event; for each, `for rule in rule_store.rules_for(event.event_type): await self._fire(rule, event)`.
  `async def run_forever(self)`: loop `await self._queue.get()` → process; graceful-shutdown on `CancelledError` (clean log + re-raise), mirroring M6-a's `run_forever`.

  — done when: `uv run mypy --strict src` passes; a single event matching one Tier-A internal rule fires the tool callable once; a re-delivered identical event does NOT re-fire (try_claim returns False); a stateful rule re-fires as an update (fire_count increments, no new effect when state unchanged); an external-effect rule calls `staging.stage` (NOT the tool callable); an A4 rule calls `CaptureService.suggest_from_text` (not a direct task write).

- [ ] **Task 3: A4 proof consumer wiring** — files: `/Users/artemis-build/artemis/src/artemis/reactions/dispatcher.py` (inline) —

  Document the A4 reaction as the first/proof consumer: `EMAIL_INGESTED` event with a commitment signal → a Tier-B reaction-recipe `reaction:email_to_task` whose `reaction_ref` routes to `CaptureService.suggest_from_text(source="email", text=<extract summary, already quarantined>, untrusted=True)`. The result is an INERT `suggestions` row (M8-d-c2) — zero external effect, zero direct task write. This validates the emit→rule→dispatch path on a zero-risk reaction before any external-effect reaction is wired (R3 mitigation). The dispatcher reads the already-quarantined extract from the event payload reference (NEVER raw email — the quarantine happened upstream at ingest; the event carries only the extract/ids per Seam 7).

  — done when: a test fires an `EMAIL_INGESTED` event through the dispatcher with an A4 rule and asserts a `FakeCaptureService.suggest_from_text` call (inert), zero `staging.stage` calls, zero direct task creates.

- [ ] **Task 4: Tests** — files: `/Users/artemis-build/artemis/tests/test_reactions_dispatcher.py` — typed pytest (async tests `@pytest.mark.anyio`).

  Fixtures: in-process `EventBus`; a `FakeRuleStore` (returns configured `ReactionRule`s per event_type); `FakeToolRegistry` with async spy callables; `FakeActionStagingService` (records `stage` calls); `FakeCaptureService` (records `suggest_from_text`); `ReactionLedger` over a temp sqlite (`FakeKeyProvider(owner_unlocked=True)`); a `notice_sink` spy.

  - **Fire-once dedup:** emit the same event twice (same stable key) → the Tier-A internal tool callable fires EXACTLY once; `try_claim` returned False the second time.
  - **Stateful re-fire as update:** a `stateful=True` rule; emit two events with the same stable key but different state → `fire_count == 2`, no duplicate effect; a third identical-state event → skipped (state_hash unchanged).
  - **Auto routing (internal/reversible):** an `external_effect=False` rule → the tool callable is awaited once; `staging.stage` NOT called; `notice_sink` received the undoable notice.
  - **GATE routing (external-effect):** an `external_effect=True` rule → `staging.stage` called with the fq `reaction_ref` and a deterministic summary; the tool callable NOT awaited directly.
  - **A4 proof:** an `EMAIL_INGESTED` event + the `reaction:email_to_task` rule → `FakeCaptureService.suggest_from_text` called once (inert); zero `staging.stage`; zero direct task writes.
  - **Degrade-don't-crash:** a reaction callable that raises → `drain_once` does not raise; other matched reactions for the same event still fire; the claim persists (no re-fire on retry).
  - **Privacy:** the dispatcher reads only the event's scalar payload + entity-refs (no raw text available to it) — assert the args built for a reaction contain no title/body string (only ids/scalars from the event).
  - **ScopeLockedError:** a locked ledger provider → `_fire` surfaces the lock cleanly (degrade), never silently double-fires.

  — done when: `uv run pytest -q tests/test_reactions_dispatcher.py` passes AND `uv run mypy --strict src tests/test_reactions_dispatcher.py` passes AND `uv run ruff check . && uv run ruff format --check .` both exit 0.

- [ ] **Task 5 (GATED — on-hardware):** On the Mini (vault mounted): real `ReactionLedger` keyed SQLCipher; emit a real `TXN_RECORDED` event → a Tier-A internal reaction fires once and the ledger row is encrypted-at-rest; an external-effect reaction stages a real `PendingAction` visible in Review; re-emitting the same event does not double-fire. — done when: recorded in handoff.

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | `/Users/artemis-build/artemis/src/artemis/reactions/ledger.py` |
| Create | `/Users/artemis-build/artemis/src/artemis/reactions/dispatcher.py` |
| Modify | `/Users/artemis-build/artemis/src/artemis/reactions/__init__.py` |
| Create | `/Users/artemis-build/artemis/tests/test_reactions_dispatcher.py` |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict src tests/test_reactions_dispatcher.py` | Type gate |
| `uv run ruff check . && uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q tests/test_reactions_dispatcher.py` | Test gate |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | `src/artemis/reactions/ledger.py`, `src/artemis/reactions/dispatcher.py`, `src/artemis/reactions/__init__.py`, `tests/test_reactions_dispatcher.py` |
| `git commit` | `"feat: RXN-dispatcher — event→rule dispatch + idempotency ledger + GATE/auto routing (A4 proof)"` |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_ENV_FILE` | Settings + scope_dir (ledger DB path; off-hardware: tmp_path) |

### Network
| Action | Purpose |
|--------|---------|
| (none off-hardware) | Reactions call local tools / stage locally; no network in the dispatcher itself |

## Specialist Context

### Security

- **Idempotency wall (I-8=C):** the `(rule_name, stable_key)` `INSERT OR IGNORE` claim guarantees at-most-once for non-stateful reactions even under re-delivered/overlapping events (the named 2026 failure mode). A reaction that raises after claiming is NOT retried (the claim persists) — recovery is the link-integrity reconciler's job, not a re-fire (which could double an effect). Stateful reactions re-fire as an UPDATE keyed on the same stable key — never a duplicate.
- **GATE posture (I-10):** external-effect reactions NEVER execute directly — they `stage` to `ActionStagingService` for owner approval in Review. Only internal/reversible reactions auto-run, and those emit a passive undoable notice (not a silent action). The Tier-A gate (RXN-rulestore) already guarantees no external-effect rule is Tier-A; the dispatcher's `external_effect` branch is the second wall.
- **A4 is structurally inert:** the email→task proof reaction calls `CaptureService.suggest_from_text` → an inert `suggestions` row the owner accepts. The dispatcher cannot create a task directly via A4. The event carries only the already-quarantined extract/ids (Seam 7) — raw email never reaches the dispatcher.
- **Ledger is owner-private:** SQLCipher, M8-d-a keyed pattern, `key.as_hex()` local-only, `ScopeLockedError` propagates. The ledger stores only dedup keys + timestamps + state hashes — no domain content.

[apex-security review (cross_model_review): confirm (a) the `try_claim` dedup cannot be bypassed (the composite PK + INSERT OR IGNORE is the only fire gate); (b) external-effect reactions only ever `stage`, never dispatch; (c) the A4 path is inert (CaptureService, no direct write); (d) a raised reaction does not re-fire on retry (claim persists); (e) no raw text reaches the dispatcher (scalar-only event payloads from RXN-emit).]

### Performance

- The drain loop is O(events × matching-rules); each `_fire` is one ledger claim (indexed PK lookup) + one local tool dispatch or one `stage` insert. No model, no network in the dispatcher. At single-owner event rates (a handful per minute) this is trivially cheap. The ledger PK keeps dedup O(1).

### Accessibility

(none — headless infra; the undoable-notice surface is ntfy/Review, Wave U)

## Documentation

| Doc type | File | Action |
|----------|------|--------|
| Inline | `src/artemis/reactions/dispatcher.py` | Document the stable-key dedup, the stateful-re-fire-as-update rule, the auto-vs-GATE branch (I-10), the A4-inert-via-CaptureService path, and the degrade-don't-crash + no-re-fire-on-error recovery posture |
| Inline | `src/artemis/reactions/ledger.py` | Document that the ledger holds ONLY dedup/last-fire/state (I-8=C — spoke owns domain state), the keyed-SQLCipher pattern |

## Acceptance Criteria

- [ ] `uv run mypy --strict src tests/test_reactions_dispatcher.py` → verify: exit 0.
- [ ] `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.
- [ ] `uv run pytest -q tests/test_reactions_dispatcher.py` → verify: fire-once dedup (no double-fire on re-delivery); stateful re-fire-as-update (fire_count increments, no dup, unchanged-state skip); auto routing awaits the tool + emits undoable notice; external-effect routing calls `staging.stage` not the tool; A4 calls `CaptureService.suggest_from_text` inert; degrade-don't-crash + no-re-fire-on-error; scalar-only args; ScopeLockedError clean.
- [ ] `uv run python -c "from artemis.reactions import ReactionDispatcher, ReactionLedger; print('ok')"` → verify: prints `ok`.
- [ ] (GATED, on Mini) real keyed ledger; one fire per event; external-effect stages a PendingAction; no double-fire on re-emit → recorded in handoff.

## Progress
_(Coding mode writes here — do not edit manually)_
