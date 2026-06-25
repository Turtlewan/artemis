---
spec: fin-c-recurring-reconciliation-hooks
status: ready
token_profile: balanced
autonomy_level: L2
---
<!-- Wave S · NEW · third in FIN-a→b→c→d. Implements recurring detection (2-occurrence suggestion,
     F-D8), the L0–L4 reconciliation ladder (F-D6), the 4 proactive hooks (ride M6 heartbeat,
     counts+IDs payload), and statistical unusual-spend (z-score, F-D9). Emits the domain events
     (txn-recorded/bill-recorded/subscription-detected) Wave R's dispatcher consumes — the bill→task
     + payment→mark-paid REACTIONS are Wave R (RXN-recipes-self), NOT built here. No budget envelopes
     (locked out). Thresholds from X3. Always-local. -->

# Spec: FIN-c — Recurring detection + L0–L4 reconciliation + 4 proactive hooks + unusual-spend

**Identity:** The Finance awareness-intelligence layer over the FIN-a/b ledger — recurring-pattern detection (subscription/bill) hardening from a 2-occurrence suggestion, the L0–L4 deduplication/reconciliation ladder (idempotency → economic-event fuzzy-merge → pending↔posted → inert duplicate-suggestion → recipe-learned), four Tier-1 proactive hooks (renewal+price-increase · new-recurring · bill-due · spending-summary+unusual-spend), and statistical unusual-spend flagging — emitting the domain events Wave R reactions consume.
→ why: see docs/technical/modules/finance.md (Dedup & reconciliation / Transfers / Proactive hooks) · docs/findings/cluster-decisions/finance.md (F-D6 reconcile, F-D8 recurring-at-2, F-D9 unusual-spend, F-a awareness) · docs/technical/adr/ADR-021-cross-module-reactions.md (the emit seam) · ADR-022 (always-local).

## Assumptions

- **FIN-a + FIN-b** complete: `FinanceStore`/`FinanceRepository` with `transaction`/`subscription`/`bill`/`category`/`fin_suggestion` tables; `add_transaction` L0-idempotent on `raw_ref`; `list_transactions(*, start, end, category_id, txn_type, limit)`; `spend_summary`/`total_spend` exclude transfers+settlements; `TransactionType`/`BillStatus`/`SubscriptionCadence`; `create_fin_suggestion(kind, payload_json, raw_ref)`. → impact: Stop (FIN-c reads the ledger + writes `subscription`/`bill` rows + `fin_suggestion(kind="possible_duplicate")` rows).
- **M6-a** complete: `HookSpec` (with `tier`, `interval_seconds`/`cron`, `check_ref: Callable[[], HookResult]`, `delivery`), `HookResult.of`/`.miss()`, the `OWNER_PRIVATE ⇒ tier==1` manifest validator. All four hooks are `tier=1` on the OWNER_PRIVATE finance module. `check_ref` is SYNC, LLM-free, degrade-don't-crash. → impact: Stop (Seam 5: a `check_ref` that calls a model violates the contract; payload = counts+IDs only).
- **X3 runtime-config** complete: `get_runtime_config().finance.{recurring_min_occurrences (2), reconcile_date_window_days (1), reconcile_amount_exact (True), unusual_spend_sigma (2.0)}` — read at composition. → impact: Caution (thresholds are tunables; read once, not per-tick).
- **Always-local (ADR-022/F-D13):** recurring detection, reconciliation, and unusual-spend are all DETERMINISTIC statistical/SQL passes (no model) OR run on the LOCAL `sensitive_reasoner` (recurring merchant-normalization may use the local model, never cloud). No cloud/Codex import in the finance package — asserted. → impact: Stop.
- **RXN-emit** complete (for the emit seam): `DomainEvent`, `EventType` importable from `artemis.reactions`. The canonical emit contract is `Subscriber = Callable[[DomainEvent], None]` (`EventBus.emit` IS such a callable) over a frozen `DomainEvent(event_type: EventType, source_module, entity_refs, payload: dict[str, str|int|float|bool], occurred_at, dedup_key)`. FIN-c constructs `DomainEvent`s and calls an **injected `Callable[[DomainEvent], None]`** (default no-op so FIN-c builds/tests standalone before RXN-dispatcher wires `EventBus.emit`). FIN-c imports `DomainEvent`/`EventType` ONLY — never the dispatcher. → impact: Stop (this replaces the earlier `emit_event(name, payload)` shape, which would NOT compose with the dispatcher's `Callable[[DomainEvent], None]` subscriber).
- **Reaction handoff (F-D12 / ADR-021):** the bill→task creation + payment→mark-paid lifecycle is a **Wave-R reaction**, NOT built here. FIN-c **emits its OWN domain events** at its real write-sites (recommended path — finance emits its own events, not deferred elsewhere): `bill-recorded` + `subscription-detected` from FIN-c's `recurring.py` (Task 2 — FIN-c owns the bill/subscription writes); `txn-recorded` is emitted from **FIN-b's `add_transaction` service-layer call-site** (FIN-b owns the txn write — `add_transaction` is FIN-a-FROZEN repository code, so the emit wraps FIN-b's service call AROUND it, never inside FIN-a). FIN-c's `events.py` defines the typed emitter + the `EventType` constants the finance events use; FIN-b imports it for the `txn-recorded` emit. → impact: Stop (no reaction-package import; an injected `Callable[[DomainEvent], None]` or a no-op).
- **No budget envelopes (LOCKED out):** FIN-c has no budget/envelope concept. Unusual-spend is a *statistical outlier flag*, not a budget breach. → impact: Stop.
- **M2-stub on dev:** plain-sqlite fallback + `FakeKeyProvider(owner_unlocked=True)`; hooks tested via the M6-a `Heartbeat` harness with a `FakeKeyProvider`. → impact: Low.

Simplicity check: considered an ML recurring-detector — rejected; "same merchant + ~amount + regular cadence over N occurrences" is a deterministic GROUP-BY + interval check, cheaper and explainable. Considered eager auto-merge on any fuzzy match — rejected; F-D6 precision-first means only L1 high-confidence exact matches auto-merge; everything below the bar is an inert L3 suggestion. Unusual-spend = a z-score over per-merchant/category history, not a model call. The minimum is: three deterministic analysis passes + four count-only hooks + an injected event emitter.

## Prerequisites

- Specs complete: **FIN-a** (ledger + subscription/bill tables), **FIN-b** (`fin_suggestion` + email txns; FIN-b wires the `txn-recorded` emit around its `add_transaction` service call), **M6-a** (HookSpec/HookResult/tier), **M6-b** (TemplateRegistry for `needs_llm=False` hooks), **X3-runtime-config**, **RXN-emit** (`DomainEvent`/`EventType` value types for the emit seam).
- Environment: no new PyPI deps (stdlib `statistics` for z-score; `decimal`). `uv sync` suffices off-hardware.

## Files to Change

| File | Operation | Notes |
|------|-----------|-------|
| `/Users/artemis-build/artemis/src/artemis/modules/finance/recurring.py` | create | recurring-pattern detection (subscription/bill) at the 2-occurrence suggestion + harden-on-confirm/3rd |
| `/Users/artemis-build/artemis/src/artemis/modules/finance/reconcile.py` | create | the L0–L4 reconciliation ladder (L1 fuzzy economic-event, L2 pending↔posted, L3 inert duplicate-suggestion) + unusual-spend z-score |
| `/Users/artemis-build/artemis/src/artemis/modules/finance/events.py` | create | the canonical `Callable[[DomainEvent], None]` emitter seam (default no-op) + `DomainEvent`-builders for the 3 finance events (`TXN_RECORDED`/`BILL_RECORDED`/`SUBSCRIPTION_DETECTED`) Wave R consumes |
| `/Users/artemis-build/artemis/src/artemis/modules/finance/hooks.py` | create | the 4 `check_ref` factories + `build_finance_hooks(store) -> list[HookSpec]` + template registration |
| `/Users/artemis-build/artemis/src/artemis/modules/finance/repository.py` | modify | additive: `upsert_subscription`/`list_subscriptions`/`upsert_bill`/`list_bills`/`merge_transactions`/`merchant_amount_history` reads |
| `/Users/artemis-build/artemis/src/artemis/modules/finance/manifest.py` | modify | wire `proactive_hooks=build_finance_hooks(store)` + the recurring/reconcile tools |
| `/Users/artemis-build/artemis/src/artemis/modules/finance/tools.py` | modify | add `subscription_list`/`bill_list`/`reconcile_run`/`recurring_scan`/`unusual_spend_list` + dup-merge accept callables |
| `/Users/artemis-build/artemis/tests/test_finance_recurring.py` | create | recurring at 2-occ, cadence inference, subscription/bill write |
| `/Users/artemis-build/artemis/tests/test_finance_reconcile.py` | create | L1 fuzzy merge, L2 pending↔posted, L3 inert suggestion, unusual-spend z-score |
| `/Users/artemis-build/artemis/tests/test_finance_hooks.py` | create | 4 hooks check_ref hit/miss, counts+IDs payload, tier=1, degrade |

All paths under `/Users/artemis-build/artemis/`.

## Tasks

- [ ] **Task 1: Repository additions** — files: `/Users/artemis-build/artemis/src/artemis/modules/finance/repository.py` (modify) —

  - `upsert_subscription(*, merchant, cadence, amount: Decimal, next_renewal=None, last_seen_price=None, last_seen_date=None) -> str` — UPSERT keyed on `(merchant, cadence)`; updates `last_seen_price`/`last_seen_date`/`next_renewal`.
  - `list_subscriptions(*, active=True) -> list[dict]`.
  - `upsert_bill(*, payee, due_date, amount=None, raw_ref=None) -> str` — UPSERT keyed on `(payee, due_date)`; status defaults `open`.
  - `list_bills(*, status=None) -> list[dict]`; `mark_bill_paid(id) -> None` (sets status `paid`, `paid_at=now`) — used by the Wave-R reaction later; defined here.
  - `merge_transactions(keep_id, drop_id) -> None` — L1 merge: keep the higher-confidence row, delete the other (both refer to the same economic event).
  - `merchant_amount_history(*, merchant, category_id=None, lookback_days=180) -> list[Decimal]` — the amount series for the unusual-spend z-score (purchase/refund only).
  - `recurring_candidates(*, min_occurrences) -> list[dict]` — GROUP BY normalized merchant + rounded amount over purchase txns; return groups with `>= min_occurrences` occurrences + their date series (for cadence inference).

  — done when: `uv run mypy --strict src` passes; each method round-trips against the fallback sqlite; `recurring_candidates(min_occurrences=2)` returns a group when 2+ same-merchant ~same-amount txns exist; `merchant_amount_history` returns a `Decimal` series.

- [ ] **Task 2: Recurring detection (2-occurrence suggestion → harden)** — files: `/Users/artemis-build/artemis/src/artemis/modules/finance/recurring.py` —

  `def detect_recurring(store: FinanceStore, *, min_occurrences: int, emit: Emit = _noop_emit) -> list[dict]` (`min_occurrences` from `RuntimeConfig.finance.recurring_min_occurrences`, default 2; `emit` is the injected canonical `Callable[[DomainEvent], None]`):
  - Call `store.recurring_candidates(min_occurrences=min_occurrences)`.
  - For each group: infer cadence from the date series (median inter-arrival days → `monthly` ~28–31, `weekly` ~7, `quarterly` ~90, `yearly` ~365; tolerance ±25%). If cadence is regular → propose a `subscription`.
  - **At exactly `min_occurrences` (2):** write an inert `fin_suggestion(kind="new_recurring")` (owner confirms) rather than a hard `subscription` row (F-D8 = suggest at 2). **On owner confirm OR a 3rd occurrence:** `store.upsert_subscription(...)` (harden). Track occurrence count to trigger the 3rd-hit auto-harden.
  - Due-date language (from FIN-b extracts / bill phrasing) → `bill_id = store.upsert_bill(...)` then `emit(bill_recorded_event(bill_id=bill_id, payee=..., due_date=..., amount=...))`.
  - On a hardened subscription → `emit(subscription_detected_event(subscription_id=..., merchant=...))` (Wave R consumes).
  - Returns the list of created suggestion/subscription ids.

  **NB (finance.md):** a subscription's monthly charge is NOT a duplicate — dedup keys on `raw_ref`/economic-event, so identical amounts in different months stay separate txns; the recurring detector reads them as a series. Document this.

  — done when: `uv run mypy --strict src` passes; 2 monthly same-merchant txns → a `new_recurring` suggestion (no hard subscription yet); a 3rd → `upsert_subscription` fires + the injected `emit` spy receives a `DomainEvent(event_type=EventType.SUBSCRIPTION_DETECTED, ...)`; a bill upsert emits a `BILL_RECORDED` `DomainEvent`; cadence inferred as `monthly`; identical amounts in different months are NOT treated as duplicates.

- [ ] **Task 3: Reconciliation ladder L0–L4 + unusual-spend** — files: `/Users/artemis-build/artemis/src/artemis/modules/finance/reconcile.py` —

  `def reconcile(store: FinanceStore, *, date_window_days: int, amount_exact: bool) -> dict` (defaults from `RuntimeConfig.finance.{reconcile_date_window_days, reconcile_amount_exact}`):
  - **L0** (already in FIN-a `raw_ref` UNIQUE) — no-op here, documented.
  - **L1 — economic-event dedup (cross-source):** fuzzy key = amount (exact if `amount_exact`, else ±1%) + currency + date-window (±`date_window_days`) + normalized merchant. A new extract matching an existing txn from a **different source** → **auto-merge** via `store.merge_transactions(keep, drop)` keeping the highest-confidence source (receipt > terse alert). Only HIGH-confidence exact matches auto-merge.
  - **L2 — pending↔posted:** CSV/statement import (`source="csv"`) is ground-truth; reconcile email-extracted (pending) against CSV (posted) — match by L1 key → mark the email txn reconciled (or merge, keeping the CSV row as authoritative).
  - **L3 — ambiguous → inert suggestion:** any match BELOW the auto-merge bar → `store.create_fin_suggestion(kind="possible_duplicate", payload_json=<the two txn ids + reason>)` (owner confirms; never silent merge).
  - **L4 — recipe-learned:** repeated owner merge/keep decisions graduate into a learned rule via the M7 recipe loop — FIN-c emits the graduation signal (reuse the M8-d-c2 `Promoter` pattern); the actual recipe write is the recipe system's job. Reference, don't re-implement.
  - Returns `{"auto_merged": int, "suggested_duplicates": int, "reconciled": int}`.

  `def unusual_spend(store: FinanceStore, *, sigma: float) -> list[dict]` (`sigma` from `RuntimeConfig.finance.unusual_spend_sigma`, default 2.0):
  - For recent purchase txns: compute the per-merchant (and per-category) mean + stdev from `merchant_amount_history`; flag a txn whose amount exceeds `mean + sigma*stdev` (z-score outlier). Requires a minimum history (e.g. ≥4 prior) to avoid flagging first-seen merchants.
  - Returns flagged txn ids + their z-scores. **This is a flag, not a budget breach** (no envelopes).

  — done when: `uv run mypy --strict src` passes; L1 auto-merges two high-confidence same-event txns from different sources (one row remains); L2 reconciles an email txn against a CSV txn; a below-bar match creates a `possible_duplicate` suggestion (no merge); `unusual_spend(sigma=2.0)` flags a 5× outlier and does NOT flag an in-pattern txn; a first-seen merchant is not flagged.

- [ ] **Task 4: Event emit seam (canonical `Callable[[DomainEvent], None]`)** — files: `/Users/artemis-build/artemis/src/artemis/modules/finance/events.py` —

  ```python
  from artemis.reactions import DomainEvent, EventType   # import the value types ONLY — never the dispatcher
  from artemis.shared.time import now_iso

  FINANCE_EVENT_TYPES = (EventType.TXN_RECORDED, EventType.BILL_RECORDED, EventType.SUBSCRIPTION_DETECTED)
  Emit = Callable[[DomainEvent], None]                    # the canonical RXN-emit Subscriber shape (EventBus.emit satisfies it)
  _noop_emit: Emit = lambda _e: None                      # default — FIN-c/FIN-b build + test standalone

  def txn_recorded_event(*, txn_id: str, txn_type: str, amount: str, instrument_account_id: str | None) -> DomainEvent:
      return DomainEvent(
          event_type=EventType.TXN_RECORDED, source_module="finance",
          payload={"txn_id": txn_id, "txn_type": txn_type, "amount": amount,
                   "instrument_account_id": instrument_account_id or ""},
          occurred_at=now_iso(), dedup_key=f"txn-recorded:{txn_id}")

  def bill_recorded_event(*, bill_id: str, payee: str, due_date: str, amount: str | None) -> DomainEvent:
      return DomainEvent(
          event_type=EventType.BILL_RECORDED, source_module="finance",
          payload={"bill_id": bill_id, "payee": payee, "due_date": due_date, "amount": amount or ""},
          occurred_at=now_iso(), dedup_key=f"bill-recorded:{bill_id}")

  def subscription_detected_event(*, subscription_id: str, merchant: str) -> DomainEvent:
      return DomainEvent(
          event_type=EventType.SUBSCRIPTION_DETECTED, source_module="finance",
          payload={"subscription_id": subscription_id, "merchant": merchant},
          occurred_at=now_iso(), dedup_key=f"subscription-detected:{subscription_id}")
  ```
  Each builder constructs a frozen `DomainEvent` with a **scalar-only payload** (ids + scalars; `None`→`""` to stay scalar — Seam 5; no raw email, no merchant PII beyond name) and a stable `dedup_key`. The emitter is **injected** (a `Callable[[DomainEvent], None]`, default `_noop_emit`) into the FIN-c analysis layer (`detect_recurring`) and the FIN-b txn service:
  - **`bill-recorded` / `subscription-detected`** — emitted in FIN-c's `recurring.py` (Task 2): `emit(bill_recorded_event(...))` when a bill is upserted, `emit(subscription_detected_event(...))` when a subscription hardens. FIN-c owns these write-sites.
  - **`txn-recorded`** — emitted by **FIN-b's `add_transaction` service-layer call** (FIN-b's spec wires `emit(txn_recorded_event(...))` AROUND its FIN-a `repo.add_transaction(...)` call — NOT inside FIN-a, which is frozen). FIN-c exports the builder; FIN-b imports it. (Named here so the producer call-site is explicit; the FIN-b file is not edited by FIN-c.)

  RXN-dispatcher later passes `EventBus.emit` as the injected emitter. FIN-c/FIN-b import NO reaction-dispatcher symbol — only `DomainEvent`/`EventType` value types from `artemis.reactions`.

  — done when: `uv run mypy --strict src` passes; `txn_recorded_event(...)`/`bill_recorded_event(...)`/`subscription_detected_event(...)` each build a frozen `DomainEvent` with the right `EventType`, scalar-only payload, and a `dedup_key`; the default `_noop_emit` does nothing; passing a spy `Callable[[DomainEvent], None]` receives the constructed event; the finance package imports `DomainEvent`/`EventType` but no reaction-dispatcher symbol.

- [ ] **Task 5: The 4 proactive hooks** — files: `/Users/artemis-build/artemis/src/artemis/modules/finance/hooks.py` —

  Four `make_*_check(store) -> Callable[[], HookResult]` factories (SYNC, LLM-free, degrade-don't-crash via `try/except → HookResult.miss()`; payload = counts+IDs+scalar values ONLY — Seam 5):
  1. **`make_renewal_check`** — subscriptions whose `next_renewal` is within N days (+ price-increase: `last_seen_price` rose). Payload `{"renewing_count", "price_increase_count", "subscription_ids"}`.
  2. **`make_new_recurring_check`** — pending `new_recurring` suggestions. Payload `{"new_recurring_count", "suggestion_ids"}`.
  3. **`make_bill_due_check`** — `bill` rows with `status="open"` and `due_date` within N days. Payload `{"due_count", "bill_ids"}`. Reminder-only (never auto-pays — documented).
  4. **`make_spending_summary_check`** — periodic categorized digest + unusual-spend flags (calls `unusual_spend`). Payload `{"period_total", "top_category", "unusual_count", "unusual_txn_ids"}` (period_total is a scalar string; no per-txn amounts beyond the flagged ids).

  `build_finance_hooks(store) -> list[HookSpec]`: four `HookSpec`s, all `tier=1`, sensible cadences (renewal/bill-due daily cron e.g. `"0 8 * * *"`; new-recurring + spending-summary `interval_seconds` or a weekly dedup). `needs_llm`: the renewal/bill-due/new-recurring can be `needs_llm=False` (template path — register templates); spending-summary `needs_llm=True` (the digest is composed by M6-b). `register_finance_templates(registry)` for the `needs_llm=False` hooks.

  **Payload-safety note (inline):** no merchant PII beyond the subscription/bill name, no amounts beyond a period total + flagged ids — Seam 5 boundary (the M6-b batched-LLM prompt receives the payload).

  — done when: `uv run mypy --strict src` passes; `build_finance_hooks(store)` returns 4 `HookSpec`s all `tier=1`; each `check_ref` returns `.miss()` on an empty store and a hit with the documented payload keys when seeded; `make_spending_summary_check` includes `unusual_count`; a `ScopeLockedError` degrades to `.miss()`.

- [ ] **Task 6: Tools + manifest wiring** — files: `/Users/artemis-build/artemis/src/artemis/modules/finance/tools.py`, `/Users/artemis-build/artemis/src/artemis/modules/finance/manifest.py` (modify) —

  Add callables (ADR-016 async): `subscription_list`, `bill_list`, `recurring_scan` (runs `detect_recurring`), `reconcile_run` (runs `reconcile`), `unusual_spend_list` (runs `unusual_spend`), `fin_suggestion_accept` extended for `kind="possible_duplicate"` (merges). The module-level `init_finance_tools(store, *, emit: Emit = _noop_emit)` threads the injected canonical `Callable[[DomainEvent], None]` into `detect_recurring(store, ..., emit=emit)` (default no-op; RXN-dispatcher passes `EventBus.emit` at composition). Wire `finance_manifest` to `proactive_hooks=build_finance_hooks(store)` + `register_finance_templates(registry)` (add the `registry` param to the manifest signature) — the `OWNER_PRIVATE ⇒ tier==1` validator passes (all four hooks tier=1). All tools AUTO (no GATE — internal local edits; the dup-merge confirm is an inert suggestion, NOT a GATE stage).

  — done when: `uv run mypy --strict src` passes; `finance_manifest(store, registry).proactive_hooks` has length 4; the validator does not raise; new tools present + async; no GATE/staging anywhere.

- [ ] **Task 7 (GATED — on-hardware):** real served model + real ledger: seed 3 monthly Netflix txns → a hardened `subscription` + `subscription-detected` emitted; a real CSV import reconciles against email txns (L2); an outlier purchase flags via `unusual_spend`; the 4 hooks fire via a real `Heartbeat.tick()` (Tier-1, payload counts+IDs). — done when: recorded in handoff.

- [ ] **Task 8: Tests** — files: the three test files above —

  **recurring:** 2 monthly txns → `new_recurring` suggestion (no hard subscription); 3rd → `upsert_subscription` + a `SUBSCRIPTION_DETECTED` `DomainEvent` delivered to the injected `emit` spy; a bill upsert → a `BILL_RECORDED` `DomainEvent`; the event builders construct frozen scalar-only-payload `DomainEvent`s with stable `dedup_key`s; the default `_noop_emit` is a safe no-op; cadence inference (monthly/weekly/yearly); different-month identical amounts NOT duplicates.
  **reconcile:** L1 auto-merge (high-confidence cross-source → one row); L2 email↔CSV reconcile; L3 below-bar → `possible_duplicate` suggestion (no merge); `unusual_spend` flags a 5× outlier, ignores in-pattern + first-seen.
  **hooks:** each of 4 `check_ref` hit/miss; payload keys are counts+IDs+scalars only (assert no raw amount-per-txn beyond flagged ids, no merchant PII beyond name); all `tier=1`; `ScopeLockedError` → miss; manifest validates; bill-due hook payload has `bill_ids`.
  **always-local guard:** assert the finance package imports no cloud/Codex port.

  — done when: `uv run pytest -q tests/test_finance_recurring.py tests/test_finance_reconcile.py tests/test_finance_hooks.py` passes AND `uv run mypy --strict src <those test files>` passes AND ruff clean.

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | `/Users/artemis-build/artemis/src/artemis/modules/finance/recurring.py` |
| Create | `/Users/artemis-build/artemis/src/artemis/modules/finance/reconcile.py` |
| Create | `/Users/artemis-build/artemis/src/artemis/modules/finance/events.py` |
| Create | `/Users/artemis-build/artemis/src/artemis/modules/finance/hooks.py` |
| Modify | `/Users/artemis-build/artemis/src/artemis/modules/finance/repository.py` |
| Modify | `/Users/artemis-build/artemis/src/artemis/modules/finance/manifest.py` |
| Modify | `/Users/artemis-build/artemis/src/artemis/modules/finance/tools.py` |
| Create | `/Users/artemis-build/artemis/tests/test_finance_recurring.py`, `/Users/artemis-build/artemis/tests/test_finance_reconcile.py`, `/Users/artemis-build/artemis/tests/test_finance_hooks.py` |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict src tests/test_finance_recurring.py tests/test_finance_reconcile.py tests/test_finance_hooks.py` | Type gate |
| `uv run ruff check . && uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q tests/test_finance_recurring.py tests/test_finance_reconcile.py tests/test_finance_hooks.py` | Test gate |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | `src/artemis/modules/finance/{recurring,reconcile,events,hooks,repository,manifest,tools}.py`, the 3 test files |
| `git commit` | `"feat: FIN-c recurring detection + L0–L4 reconciliation + 4 proactive hooks + unusual-spend"` |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_ENV_FILE` | Settings + scope_dir resolution |

### Network
| Action | Purpose |
|--------|---------|
| local `127.0.0.1` to mlx-openai-server (GATED) | optional local merchant-normalization on the LOCAL model (loopback only — never cloud) |

## Specialist Context

### Security

- **Always-local (ADR-022/F-D13):** all analysis is deterministic SQL/statistics or LOCAL-model merchant-normalization; no cloud/Codex import (asserted). Ledger data never egresses.
- **Tier-1 hooks (Seam 5):** all four hooks are `tier=1` on the OWNER_PRIVATE module → skipped-and-queued while locked (M6-a gate). `check_ref` is SYNC + LLM-free + degrade-don't-crash. Payloads carry counts + IDs + scalar totals ONLY — no raw amounts-per-txn beyond flagged ids, no merchant PII beyond the subscription/bill name (the M6-b batched-LLM prompt boundary).
- **Precision-first reconciliation (F-D6):** only L1 high-confidence exact cross-source matches auto-merge; everything below the bar is an inert L3 suggestion the owner confirms. No silent merge.
- **Reminder-only bills:** the bill-due hook never auto-pays; the bill→task handling is a Wave-R reaction (held-for-approval where external). FIN-c only emits the events.
- **No external-effect:** all writes are internal local-ledger edits — no GATE/staging.

[apex-security review: confirm no cloud import; confirm hook payloads are counts+IDs+scalars (no per-txn amounts beyond flagged ids); confirm the emit seam carries no raw email/PII; confirm L1 auto-merge is high-confidence-only and L3 is inert.]

### Performance

- Recurring detection + reconciliation are GROUP-BY/interval passes over the ledger (thousands of rows) — sub-second, run on a schedule (the hooks / a nightly pass), not the interactive turn. Unusual-spend is a per-merchant mean/stdev over a bounded lookback — cheap. `check_ref` is one indexed query per hook. The optional local merchant-normalization is the only model call, and only during detection (off the hot path).

### Accessibility

(none — no frontend in FIN-c; the subscriptions/bills/unusual-spend surfaces are Wave U / CLIENT)

## Documentation

| Doc type | File | Action |
|----------|------|--------|
| Inline | `src/artemis/modules/finance/{recurring,reconcile,hooks,events}.py` | Docstring the 2-occurrence-suggestion harden rule, the L0–L4 ladder, the unusual-spend z-score, the counts+IDs hook-payload boundary, the emit seam (events Wave R consumes), the always-local wall |

## Acceptance Criteria

- [ ] `uv run mypy --strict src tests/test_finance_recurring.py tests/test_finance_reconcile.py tests/test_finance_hooks.py` → verify: exit 0.
- [ ] `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.
- [ ] `uv run pytest -q tests/test_finance_recurring.py tests/test_finance_reconcile.py tests/test_finance_hooks.py` → verify: recurring at 2-occ-suggestion + 3rd-hardens + `SUBSCRIPTION_DETECTED`/`BILL_RECORDED` `DomainEvent` emit (canonical `Callable[[DomainEvent], None]` spy); cadence inference; non-duplicate cross-month; L1 auto-merge + L2 reconcile + L3 inert suggestion; unusual-spend z-score flags outlier / ignores in-pattern + first-seen; 4 hooks hit/miss with counts+IDs payload; all tier=1; ScopeLockedError → miss; emit seam default-no-op + spy + scalar-only payload; no cloud import; no budget concept.
- [ ] `uv run python -c "from artemis.modules.finance.recurring import detect_recurring; from artemis.modules.finance.reconcile import reconcile, unusual_spend; from artemis.modules.finance.events import txn_recorded_event, bill_recorded_event, subscription_detected_event, FINANCE_EVENT_TYPES; from artemis.modules.finance.hooks import build_finance_hooks; print('ok')"` → verify: prints `ok`.
- [ ] (GATED, on Mini) recurring harden + CSV reconcile + outlier flag + 4 hooks fire via real Heartbeat → recorded in handoff.

## Progress
_(Coding mode writes here — do not edit manually)_
