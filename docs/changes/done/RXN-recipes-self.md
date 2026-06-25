---
spec: rxn-recipes-self
status: ready
token_profile: balanced
autonomy_level: L2
cross_model_review: true
---
<!-- Wave R · per-cluster reaction recipes (Self/Finance). Consumes the reaction infra (RXN-emit /
     RXN-rulestore / RXN-dispatcher / RXN-reconciler) + FIN-c (emit points + mark-paid + bill lifecycle)
     + CaptureService (A6 bill→task). Defines A1 settlement, A6 bill→task (Tier-A), A9 payment→mark-paid
     +complete (reconciler), B4c ~S$500 fraud-confirm (reconciler + X3 threshold), B-cluster bill
     lifecycle. Builds NONE of the infra/FIN-c it binds to. cross_model_review: true (finance + fraud). -->

# Spec: RXN-recipes-self — Self/Finance reaction recipes (A1 settlement · A6 bill→task · A9 payment→mark-paid · B4c fraud-confirm · bill lifecycle)

**Identity:** The Self/Finance-cluster reaction recipes: A1 (CC-bill statement → settlement, Tier-A extended), A6 (bill email → pay-bill task, Tier-A built-in — the finance "handling" verb, via `CaptureService`), A9 (payment → reconciler-matched mark-paid + complete the linked task), B4c (~S$500 charge-without-receipt → fraud-confirm via the shared reconciler, threshold from X3, owner-confirm Tier-B), and the B-cluster bill open→paid lifecycle sync. All finance reactions are internal local-ledger edits (no GATE); the fraud signal is a notification, not an external action.
→ why: see docs/technical/adr/ADR-021-cross-module-reactions.md (Decision 2 Tier-A A6 + extended A1/A9-link · Decision 4 shared reconciler) · docs/findings/cluster-decisions/DECISIONS-LOG.md (F-a handling verb · I-3 fraud ~S$500 ±7d · I-7 reconciler) · docs/technical/modules/finance.md (transfers/settlements not spend · bill lifecycle).

## Assumptions

- **RXN-emit** complete: frozen `DomainEvent{event_type: EventType, source_module, entity_refs, payload: dict[str, str|int|float|bool], occurred_at, dedup_key}` (ids + scalars only, validated). Bound `EventType` values used here (all registered): FIN-c emits `TXN_RECORDED` (txn id + `amount` str + `txn_type` + `instrument_account_id` + a `has_receipt: bool` scalar), `BILL_RECORDED` (bill id + payee + due_date + amount), `SUBSCRIPTION_DETECTED`, and `PAYMENT_RECORDED` (a settlement/payment txn id + the bill/statement it may settle — **A1 settlement binds to `PAYMENT_RECORDED`**, matching the rulestore `cc_settlement_marker` binding; there is NO separate `statement-recorded` event). This spec PRODUCES `EventType.BILL_PAID` (now registered) at the A1/A9 mark-paid call-site, which its own bill-lifecycle reaction consumes. → impact: Stop (Self rules bind to these registered `EventType`s; FIN-c/this spec are the producers).
- **RXN-rulestore** complete: the canonical `ReactionRule` is a frozen dataclass `{name: str, event_type: EventType, tier: ReactionTier, external_effect: bool, reaction_ref: str (fq tool/recipe id), dedup_key_fields: tuple[str, ...], stateful: bool = False}` with the Tier-A gate (`tier==A ⇒ external_effect is False`). The Tier-A built-in table declares A6 (`bill_to_task`), A1 (`cc_settlement_marker`), A9-link (`payment_bill_link`). B4c is Tier-B (judgment/precision-risk → owner-confirm). → impact: Stop (this spec builds the callables the canonical `reaction_ref` fq-ids point to + a `register_self_reactions` that registers them as tools and returns the matching `ReactionRule`s; `reaction_ref` is a STRING, idempotency is `dedup_key_fields`, NEVER an `idempotency_key_fn`/`Callable`).
- **RXN-dispatcher** complete: dispatches via `await get_tool(rule.reaction_ref).callable_ref(args)` (ADR-016), idempotency from `dedup_key_fields` + `event.dedup_key`, internal/reversible (`external_effect=False`) → auto + undoable notice. The fraud-confirm B4c surfaces a notification (an inert confirm suggestion), NOT an external action. → impact: Stop.
- **RXN-reconciler** complete: the ONE shared fuzzy-match primitive — `class Reconciler(*, date_window_days: int, amount_exact: bool, amount_tol: Decimal = Decimal("0"))` constructed from X3 windows at composition; `match(self, target: ReconcileRecord, candidates: Sequence[ReconcileRecord]) -> MatchResult` (outcome `EXACT`/`AMBIGUOUS`/`NONE`). There is **NO `key_fields` param and NO per-call window/tol** — the window/tol are `__init__` config; the matcher keys on amount + date-window + `normalize_merchant`. A9/B4c map their domain rows into `ReconcileRecord{id, amount: Decimal, currency, date, merchant}` and call `reconciler.match(target, candidates)`; auto-merge only `MatchOutcome.EXACT` (single high-confidence), `AMBIGUOUS` → inert suggestion, `NONE` → no-op. A9 (payment↔bill) and B4c (charge↔receipt) BOTH use the ONE injected `Reconciler` (Decision 4). → impact: Stop (A9/B4c construct `ReconcileRecord`s + call `match(target, candidates)`; they implement no matching and pass no `key_fields`/window/tol per call).
- **FIN-c** complete: exposes `mark_bill_paid(bill_id)`, the bill open→paid lifecycle, the subscription/bill derivation, and the 4 finance hooks. The A1 settlement maps a CC-bill payment to the statement period it clears (`settles_period` on the txn — FIN-a schema). → impact: Stop (A1/A9/lifecycle call FIN-c tools via the ToolRegistry, never the finance store — ADR-011; always-local — no cloud).
- **CaptureService** (M8-d-c2) complete: A6 (bill email → pay-bill task) reuses `CaptureService` to create the pay-bill task — but A6 is a **Tier-A built-in** (universal: every bill wants a pay task; internal; reversible; zero-judgment given a confirmed bill). A6 may auto-create the task (Tier-A) OR suggest (if the bill itself is uncertain) — default Tier-A auto with an undoable notice + the always-linked Calendar due-date marker (Decision 8). The task carries `source = finance:bill:<id>`; the bill carries `linked_task` (the FIN-a `linked_task_ref`). → impact: Stop.
- **X3 runtime-config** complete: `get_runtime_config().reaction.fraud_confirm_amount_sgd` (500.0) + `fraud_confirm_window_days` (7) — B4c reads these; re-tunable on Mac (I-3). → impact: Stop (the threshold is a tunable, not hardcoded).
- **Always-local (ADR-022/F-D13):** no finance reaction routes ledger data to cloud. The reaction callables call FIN-c tools (local) + the reconciler (local) — no model/cloud import. → impact: Stop.
- **Decision 8:** the A6 pay-bill task is dated (the due date) → it MUST wire a Calendar due-date marker (the always-linked contract; C1 from RXN-recipes-planning fires on the task's `task-created` event). → impact: Caution (A6 creates the task; the Task⇄Calendar link is C1's job, triggered by the task-created emit — A6 does not re-implement it).
- Off-hardware: fakes for emit/dispatcher/reconciler + the FIN-c tools + CaptureService. → impact: Low.

Simplicity check: A1/A6/A9/lifecycle are thin event→FIN-c-tool delegations; A9/B4c are thin reconciler calls + a follow-up tool call. The matching logic (reconciler) and the ledger edits (FIN-c) already exist — this spec is the routing table + the fraud threshold read + the idempotency keys. No new matcher, no new store, no model call (always-local, no model here at all).

## Prerequisites

- Specs complete: **RXN-emit** (`DomainEvent`/`EventType` incl. `BILL_PAID`), **RXN-rulestore** (canonical `ReactionRule` + `TIER_A_BUILTINS`), **RXN-dispatcher**, **RXN-reconciler** (`Reconciler(date_window_days=…, amount_exact=…)` + `match(target, candidates)` + `ReconcileRecord`/`MatchOutcome`), **FIN-c** (emit points + mark-paid + bill lifecycle), **FIN-a** (schema: `linked_task_ref`, `settles_period`), **CaptureService (M8-d-c2)**, **X3-runtime-config** (fraud threshold/window), **RXN-recipes-planning** (C1 wires the A6 task's Calendar marker).
- Environment: no new PyPI deps.

## Files to Change

| File | Operation | Notes |
|------|-----------|-------|
| `/Users/artemis-build/artemis/src/artemis/reactions/recipes/self.py` | create | A1/A6/A9/B4c/lifecycle async reaction callables (fq tool/recipe-ids) + `bill_paid_event` builder + `register_self_reactions(registry, *, capture_service, mark_bill_paid_fn, complete_task_fn, reconciler, fraud_notify_fn, emit) -> tuple[ReactionRule, ...]` |
| `/Users/artemis-build/artemis/src/artemis/reactions/recipes/__init__.py` | modify | re-export `register_self_reactions` |
| `/Users/artemis-build/artemis/tests/test_reactions_self.py` | create | A1 settlement, A6 bill→task, A9 reconciler match+mark-paid+complete, B4c fraud threshold, lifecycle, idempotency, tier assignment, no-cloud-import |

All paths under `/Users/artemis-build/artemis/`.

## Tasks

- [ ] **Task 1: A1 — CC-bill statement → settlement (Tier-A extended)** — files: `/Users/artemis-build/artemis/src/artemis/reactions/recipes/self.py` —

  `async def react_statement_to_settlement(event: DomainEvent, *, mark_bill_paid_fn, emit) -> ReactionResult` (ADR-016 async). Invoked on an `EventType.PAYMENT_RECORDED` event where the txn type is `settlement` (a CC-bill payment that settles individual charges already booked — there is NO `statement-recorded` event; A1 binds to `PAYMENT_RECORDED`, matching the rulestore `cc_settlement_marker`):
  1. The settlement txn (already recorded by FIN-b/manual as `txn_type="settlement"`, excluded from spend per FIN-a) maps to the statement period it clears (`settles_period`). A1 marks the corresponding bill (the CC statement bill) as paid via `await mark_bill_paid_fn(bill_id)`, then **emits `BILL_PAID`**: `emit(bill_paid_event(bill_id=bill_id, payee=...))` (the producer of the registered `EventType.BILL_PAID` the lifecycle reaction consumes; `emit` is the injected canonical `Callable[[DomainEvent], None]`, default no-op).
  2. The settlement does NOT count as new spend (FIN-a already excludes `settlement` from spend totals — A1 does not touch spend; it only flips the bill's lifecycle to paid).
  3. Return `ReactionResult(status="settled", ref=bill_id, undoable=True)`.

  **Tier-A extended:** internal ledger edit (mark a bill paid), reversible, zero-judgment given the settlement↔statement mapping. The matching canonical `ReactionRule` is the rulestore's `cc_settlement_marker` (`event_type=EventType.PAYMENT_RECORDED`, `tier=ReactionTier.A`, `external_effect=False`, `reaction_ref="finance.mark_settlement"`, `dedup_key_fields=("txn_id",)`, `stateful=True`).

  — done when: `uv run mypy --strict src` passes; `await react_statement_to_settlement(event, mark_bill_paid_fn=fake, emit=spy)` on a settlement `PAYMENT_RECORDED` event marks the statement bill paid once + the `emit` spy receives one `DomainEvent(event_type=EventType.BILL_PAID, ...)`; does not alter spend; re-fire on a paid bill is a no-op.

- [ ] **Task 2: A6 — bill email → pay-bill task (Tier-A built-in, the handling verb)** — files: `/Users/artemis-build/artemis/src/artemis/reactions/recipes/self.py` —

  `async def react_bill_to_task(event: DomainEvent, *, capture_service) -> ReactionResult` (ADR-016 async). Invoked on a `bill-recorded` event:
  1. Create a pay-bill task via `CaptureService` (the handling verb). Because A6 is **Tier-A** (a confirmed bill universally wants a pay task), it auto-creates the task (with an undoable notice) rather than a bare suggestion — but routes through the CaptureService path so the task carries `source=finance:bill:<id>` and the bill carries `linked_task_ref`. Title: "Pay <payee> by <due_date>", `due_at = bill.due_date`.
  2. The task is dated → the `task-created` emit fires → **C1 (RXN-recipes-planning) wires the Calendar due-date marker** (Decision 8 always-linked). A6 does NOT re-implement the Calendar link — it just creates the dated task; C1 handles the marker.
  3. Return `ReactionResult(status="task_created", ref=<task_id>, undoable=True)` (undo = delete the task + clear the bill's `linked_task_ref`).

  **Tier-A built-in** (ADR-021 Decision 2 names A6 explicitly). The matching canonical `ReactionRule` is the rulestore's `bill_to_task` (`event_type=EventType.BILL_RECORDED`, `tier=ReactionTier.A`, `external_effect=False`, `reaction_ref="tasks.create_from_bill"`, `dedup_key_fields=("bill_id",)`) — one bill yields one pay-task even on re-fire.

  — done when: `uv run mypy --strict src` passes; `await react_bill_to_task(event, capture_service=fake)` creates one pay-bill task with `due_at=bill.due_date` and `source=finance:bill:<id>`, writes `linked_task_ref` on the bill, returns `status="task_created"`; re-fire on the same bill yields one task (deduped); the task is dated (so C1 will link Calendar — assert the task has `due_at`).

- [ ] **Task 3: A9 — payment → reconciler match → mark-paid + complete linked task** — files: `/Users/artemis-build/artemis/src/artemis/reactions/recipes/self.py` —

  `async def react_payment_reconcile(event: DomainEvent, *, reconciler, mark_bill_paid_fn, complete_task_fn, emit) -> ReactionResult` (ADR-016 async; `reconciler` is the ONE shared `Reconciler` constructed from X3 windows at composition). Invoked on an `EventType.PAYMENT_RECORDED` event (a payment txn that may settle an open bill):
  1. Map the payment txn → a `ReconcileRecord{id, amount: Decimal, currency, date, merchant=<payee>}` (the `target`) and the open bills → `list[ReconcileRecord]` (the `candidates`), then `result = reconciler.match(target, candidates)` (canonical signature — NO `key_fields`/per-call window/tol; the window/`amount_exact` are the Reconciler's `__init__` config from X3).
  2. **`result.outcome == MatchOutcome.EXACT` (single high-confidence):** `bill_id = result.matched_id`; `await mark_bill_paid_fn(bill_id)`; if the bill has a `linked_task_ref`, `await complete_task_fn(task_id)` (completing the pay-bill task — which then fires C4 to clear its block); then `emit(bill_paid_event(bill_id=bill_id, payee=...))`. Return `ReactionResult(status="reconciled", ref=bill_id, undoable=True)`.
  3. **`MatchOutcome.AMBIGUOUS` (below auto-merge bar):** surface an inert "is this the payment for <bill>?" suggestion (owner confirms) — do NOT auto-mark. Return `ReactionResult(status="ambiguous", ref=None, undoable=False)`.
  4. **`MatchOutcome.NONE`:** no-op. Return `ReactionResult(status="unmatched", ref=None, undoable=False)`.

  **Tier-A (the link/mark) but precision-first on the match:** the mark-paid+complete is Tier-A *given a high-confidence `EXACT` match*; the reconciler's precision-first gate means `AMBIGUOUS` becomes an inert suggestion (never a silent auto-mark). The matching canonical `ReactionRule` is the rulestore's `payment_bill_link` (`event_type=EventType.PAYMENT_RECORDED`, `tier=ReactionTier.A`, `external_effect=False`, `reaction_ref="finance.link_payment_bill"`, `dedup_key_fields=("txn_id","bill_id")`, `stateful=True`).

  — done when: `uv run mypy --strict src` passes; a `MatchOutcome.EXACT` result marks the bill paid + completes the linked task + emits `BILL_PAID` (assert all three); an `AMBIGUOUS` result surfaces a suggestion and does NOT mark-paid; a `NONE` result is a no-op; `reconciler.match` is called as `match(target, candidates)` with `ReconcileRecord`s (no `key_fields`); re-fire on the same payment is deduped.

- [ ] **Task 4: B4c — ~S$500 charge-without-receipt → fraud-confirm (Tier-B, threshold from X3)** — files: `/Users/artemis-build/artemis/src/artemis/reactions/recipes/self.py` —

  `async def react_fraud_confirm(event: DomainEvent, *, reconciler, fraud_notify_fn) -> ReactionResult` (ADR-016 async). Invoked on a `txn-recorded` event where the txn is a `purchase` with `has_receipt == False`:
  1. Read the fraud threshold from X3: `cfg = get_runtime_config().reaction`; `threshold = cfg.fraud_confirm_amount_sgd` (500.0), `window = cfg.fraud_confirm_window_days` (7).
  2. If the txn amount `< threshold` → no fraud signal (return `status="below_threshold"`). (Small unmatched charges are noise.)
  3. Else use the shared reconciler to look for a matching receipt: map the charge txn → a `ReconcileRecord` (`target`) and the recent receipt extracts → `list[ReconcileRecord]` (`candidates`), then `result = reconciler.match(target, candidates)` (canonical signature — the `±window` date tolerance is the Reconciler's `__init__` config; **for the fraud window** the composition root injects a Reconciler constructed with `date_window_days=cfg.fraud_confirm_window_days` — a fraud-specific instance — since `match` takes no per-call window). A receipt found → `MatchOutcome.EXACT`/`AMBIGUOUS`; none → `MatchOutcome.NONE`.
  4. **no receipt match (`MatchOutcome.NONE` — a ≥S$500 charge with no receipt in the window):** surface a fraud-confirm NOTIFICATION (an inert "did you make this S$X charge at <merchant>?" confirm — NOT an external action, NOT a card block; Artemis never moves money). Call `await fraud_notify_fn(<charge ref + amount + merchant>)`. Return `ReactionResult(status="fraud_signal", ref=<txn id>, undoable=False)`.
  5. **receipt matched (`EXACT`/`AMBIGUOUS`):** no signal (the charge is accounted for). Return `status="receipt_matched"`.

  **Tier-B (judgment/precision-risk → owner-confirm):** B4c is NOT in the rulestore Tier-A table — it registers a `ReactionRule(name="reaction:fraud_confirm", event_type=EventType.TXN_RECORDED, tier=ReactionTier.B, external_effect=False, reaction_ref="reaction:fraud_confirm", dedup_key_fields=("txn_id",), stateful=True)`. The fraud signal surfaces a confirm, never auto-acts. The threshold/window are tunables (X3), re-tuned on Mac (I-3). `stateful=True` (Decision 5): a receipt arriving later clears the signal (re-fire updates, not duplicates).

  — done when: `uv run mypy --strict src` passes; a ≥S$500 purchase with no receipt (reconciler `NONE`) → `fraud_notify_fn` called once → `status="fraud_signal"`; a charge below the X3 threshold → `status="below_threshold"` (no notify, no reconciler call); a charge with a receipt match (`EXACT`/`AMBIGUOUS`) → `status="receipt_matched"` (no notify); the threshold reads from X3 (assert changing `fraud_confirm_amount_sgd` changes the boundary); `reconciler.match` is called as `match(target, candidates)` (no `key_fields`); re-fire deduped; a later receipt clears the signal (windowed/stateful).

- [ ] **Task 5: B-cluster bill lifecycle sync + `register_self_reactions`** — files: `/Users/artemis-build/artemis/src/artemis/reactions/recipes/self.py`, `/Users/artemis-build/artemis/src/artemis/reactions/recipes/__init__.py` —

  **`BILL_PAID` builder (this spec produces the event):** `def bill_paid_event(*, bill_id: str, payee: str) -> DomainEvent` returns `DomainEvent(event_type=EventType.BILL_PAID, source_module="finance", payload={"bill_id": bill_id, "payee": payee}, occurred_at=now_iso(), dedup_key=f"bill-paid:{bill_id}")` (scalar-only payload — Seam 5). A1/A9 call `emit(bill_paid_event(...))` after marking a bill paid (the injected canonical `Callable[[DomainEvent], None]`). `from artemis.reactions import DomainEvent, EventType`.

  **Bill lifecycle:** `async def react_bill_paid_lifecycle(event: DomainEvent, *, complete_task_fn) -> ReactionResult` invoked on `EventType.BILL_PAID` (registered; emitted by A1/A9 at the mark-paid call-site) — syncs the linked task (complete it if still open — the reverse of A6) and clears any orphaned link (delegated to RXN-reconciler's link-integrity sweep for stragglers). This is the open→paid lifecycle sync (finance.md). Keep it thin — the mark-paid already happened; this closes the linked task. The `ReactionRule` is `ReactionRule(name="reaction:bill_lifecycle", event_type=EventType.BILL_PAID, tier=ReactionTier.A, external_effect=False, reaction_ref="reaction:bill_lifecycle", dedup_key_fields=("bill_id",))`.

  `def register_self_reactions(registry: ToolRegistry, *, capture_service, mark_bill_paid_fn, complete_task_fn, reconciler, fraud_notify_fn, emit) -> tuple[ReactionRule, ...]`: registers each async reaction callable in the `ToolRegistry` under its fq `reaction_ref` id (A1=`finance.mark_settlement`, A6=`tasks.create_from_bill`, A9=`finance.link_payment_bill` — existing canonical rulestore fq-ids this spec supplies callables for; B4c=`reaction:fraud_confirm`, lifecycle=`reaction:bill_lifecycle` — new Tier-B/Tier-A reaction-recipe tools) via `functools.partial` (injecting `reconciler`/the FIN-c tool handles/`emit`), and returns the canonical `ReactionRule`s: A1 (`cc_settlement_marker`), A6 (`bill_to_task`), A9 (`payment_bill_link`) — aligned field-for-field with `TIER_A_BUILTINS` (`ReactionTier.A`); B4c (`reaction:fraud_confirm`, `ReactionTier.B`); lifecycle (`reaction:bill_lifecycle`, `ReactionTier.A`). Document the event_type→reaction map + `dedup_key_fields` + the always-local invariant. Re-export from `recipes/__init__.py`.

  — done when: `uv run mypy --strict src` passes; `register_self_reactions(...)` registers the 5 reaction callables as tools and returns 5 `ReactionRule`s; A1/A6/A9 carry `tier=ReactionTier.A` and match the rulestore `TIER_A_BUILTINS` entries (name/event_type/reaction_ref/dedup_key_fields), lifecycle `ReactionTier.A`, B4c `ReactionTier.B`; every `reaction_ref` is a `str`; `from artemis.reactions.recipes import register_self_reactions` succeeds.

- [ ] **Task 6: Tests** — files: `/Users/artemis-build/artemis/tests/test_reactions_self.py` — typed pytest, async.

  Fakes: `FakeCaptureService`, `FakeMarkBillPaidFn`, `FakeCompleteTaskFn`, `FakeReconciler` (configurable to return a `MatchResult` with `outcome` `EXACT`/`AMBIGUOUS`/`NONE` from `match(target, candidates)`), `FakeFraudNotifyFn`, an `emit` spy (`Callable[[DomainEvent], None]`), `FakeToolRegistry` with idempotency ledger. Use a `Settings(data_root=tmp_path)` + a temp `policy.json` to drive the X3 fraud threshold/window.

  - **A1 settlement:** a `PAYMENT_RECORDED` settlement event → marks the statement bill paid + emits one `BILL_PAID` `DomainEvent`; spend unaffected; re-fire no-op.
  - **A6 bill→task:** a `BILL_RECORDED` event → one pay-bill task with `due_at=bill.due_date`, `source=finance:bill:<id>`, `linked_task_ref` written; dated task (so C1 can link Calendar); re-fire deduped.
  - **A9 reconcile — `EXACT`:** `match(target, candidates)` returns `MatchOutcome.EXACT` → mark-paid + complete linked task + emit `BILL_PAID` (all asserted); assert `match` called with `ReconcileRecord`s and no `key_fields` kwarg.
  - **A9 reconcile — `AMBIGUOUS`:** below-bar match → inert suggestion, NO mark-paid.
  - **A9 reconcile — `NONE`:** no-op.
  - **B4c fraud — over threshold, no receipt:** ≥S$500 purchase, reconciler `NONE` → `fraud_notify_fn` once → `status="fraud_signal"`; assert NO external action / card block (notification only).
  - **B4c — below threshold:** a S$50 charge → `status="below_threshold"`, no notify, no reconciler call.
  - **B4c — threshold from X3:** set `policy.json` `reaction.fraud_confirm_amount_sgd=100` → a S$120 no-receipt charge now signals (proves the threshold is read from X3, not hardcoded).
  - **B4c — receipt matched:** a reconciler `EXACT`/`AMBIGUOUS` → `status="receipt_matched"`, no notify; a receipt arriving later clears a prior signal (windowed/stateful).
  - **Lifecycle:** a `BILL_PAID` event completes the linked task if open.
  - **Tier assignment + canonical rule shape:** A1/A6/A9 `tier=ReactionTier.A` (equal field-for-field to the `TIER_A_BUILTINS` entries), lifecycle `ReactionTier.A`, B4c `ReactionTier.B`; every returned rule's `reaction_ref` is a `str` resolvable in the registry; no rule carries a `Callable`/`idempotency_key_fn`.
  - **No-cloud-import guard:** assert `artemis.reactions.recipes.self` imports no `ModelPort`/cloud adapter (always-local — the finance reactions never touch cloud).
  - **ADR-011:** A1/A6/A9 call FIN-c tools (the injected fns), never a direct finance store write.

  — done when: `uv run pytest -q tests/test_reactions_self.py` passes AND `uv run mypy --strict src tests/test_reactions_self.py` passes AND `uv run ruff check . && uv run ruff format --check .` both exit 0.

- [ ] **Task 7 (GATED — on-hardware):** On the Mini with the real reaction infra + FIN-a/b/c + the real fraud threshold: a bill email → A6 pay-bill task (+ C1 Calendar marker); a payment → A9 reconciler match → bill paid + task completed (+ C4 clears its block); a real ≥S$500 charge with no receipt in ±7d → a fraud-confirm notification (no external action); a CC statement payment → A1 settlement. — done when: recorded in handoff.

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | `/Users/artemis-build/artemis/src/artemis/reactions/recipes/self.py` |
| Modify | `/Users/artemis-build/artemis/src/artemis/reactions/recipes/__init__.py` |
| Create | `/Users/artemis-build/artemis/tests/test_reactions_self.py` |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict src tests/test_reactions_self.py` | Type gate |
| `uv run ruff check . && uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q tests/test_reactions_self.py` | Test gate (fakes only) |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | `src/artemis/reactions/recipes/self.py`, `src/artemis/reactions/recipes/__init__.py`, `tests/test_reactions_self.py` |
| `git commit` | `"feat: RXN-recipes-self — A1 settlement, A6 bill→task, A9 reconcile, B4c fraud-confirm, bill lifecycle"` |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_ENV_FILE` | Settings + X3 policy.json resolution (off-hardware: tmp_path fixture) |

### Network
| Action | Purpose |
|--------|---------|
| (none) | Always-local: no model, no cloud, no network (finance reactions) |

## Specialist Context

### Security

- **Always-local (ADR-022/F-D13):** no finance reaction imports a model/cloud port — the structural wall. The acceptance criteria assert no cloud import. Ledger data never reaches cloud, here or via any reaction.
- **No external-effect / Artemis never moves money:** A1/A6/A9/lifecycle are internal local-ledger edits (mark-paid, create task, complete task) — no GATE staging (finance has no external-effect surface). B4c's fraud signal is a NOTIFICATION (an inert confirm), NOT a card block / payment / external action. The ~S$500 figure is the fraud-*alert* threshold, never a UI/action gate (DECISIONS-LOG confirms).
- **ADR-011 — tool not store:** every finance reaction calls a FIN-c *tool* via the ToolRegistry (the injected `mark_bill_paid_fn`/`complete_task_fn`/`fraud_notify_fn`), never the finance/productivity store directly.
- **Precision-first (reconciler):** A9 auto-marks only on a high-confidence exact match; ambiguous → inert suggestion (owner confirms). B4c surfaces a confirm, never auto-acts. The shared reconciler's precision-first gate is the safety boundary.
- **Threshold tunability (I-3):** the fraud threshold + window read from X3 `reaction.*` — re-tunable on the Mac without a rebuild; never hardcoded.
- **Payload privacy (Seam 5/7):** events carry txn/bill ids + amount/merchant scalars — never raw email/statement text (the extraction already quarantined upstream in FIN-b).

[apex-security/apex-data review (cross_model_review): confirm no model/cloud import in the self-reactions module (always-local wall); confirm B4c is notification-only (no external action); confirm A1/A6/A9 use ToolRegistry tools not direct store writes; confirm the fraud threshold is read from X3 not hardcoded; confirm the reconciler's precision-first gate (ambiguous → suggestion, never auto-mark).]

### Performance

- Each reaction is a thin async tool/reconciler delegation off the heartbeat/interactive turn. The reconciler match is a bounded fuzzy scan over open bills/recent receipts (small at personal scale). No model call (always-local, no LLM in these reactions). B4c is windowed (re-fires update one signal).

### Accessibility

(none — headless reaction recipes; the fraud-confirm/bill surfaces are the client Finance/Review views, Wave U)

## Documentation

| Doc type | File | Action |
|----------|------|--------|
| Inline | `src/artemis/reactions/recipes/self.py` | Document each reaction's cluster letter + Tier + idempotency key + the delegated FIN-c tool; document the always-local wall, the no-external-effect / Artemis-never-moves-money posture, the B4c notification-only + X3-threshold + windowed-clear, the A9 reconciler precision-first gate, and the A6→C1 always-linked handoff |

## Acceptance Criteria

- [ ] `uv run mypy --strict src tests/test_reactions_self.py` → verify: exit 0.
- [ ] `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.
- [ ] `uv run pytest -q tests/test_reactions_self.py` → verify: A1 settlement marks the statement bill paid + emits `BILL_PAID` (spend unaffected); A6 creates a dated pay-bill task with `source=finance:bill:<id>` + `linked_task_ref` (deduped); A9 `match(target, candidates)` `EXACT` → mark-paid + complete task + emit `BILL_PAID`, `AMBIGUOUS` → inert suggestion, `NONE` → no-op; B4c ≥threshold no-receipt → fraud notification (notification-only), below-threshold → no signal, threshold read from X3, receipt-matched → no signal, later receipt clears signal; lifecycle completes linked task on `BILL_PAID`; rules use canonical `ReactionRule` (str `reaction_ref` + `dedup_key_fields`); tier assignment (A1/A6/A9/lifecycle=`ReactionTier.A` matching `TIER_A_BUILTINS`, B4c=`ReactionTier.B`); no model/cloud import; ADR-011 tool-not-store.
- [ ] `uv run python -c "from artemis.reactions.recipes import register_self_reactions; print('ok')"` → verify: prints `ok`.
- [ ] (GATED, on Mini) A6 bill→task + C1 marker; A9 reconcile → paid + task complete + C4 clear; ≥S$500 no-receipt → fraud notification (no external action); A1 settlement → recorded in handoff.

## Progress
_(Coding mode writes here — do not edit manually)_
