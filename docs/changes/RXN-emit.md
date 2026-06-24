---
spec: rxn-emit
status: ready
token_profile: balanced
autonomy_level: L2
---
<!-- Wave R · reaction infra piece (i) — Decision 3-i. The emit seam: modules publish domain events
     at write points; a thin, uniform, observable bus the dispatcher subscribes to. Payloads carry
     ids + scalars + entity-refs ONLY (Seam 5/7 privacy). NEW package src/artemis/reactions/. -->

# Spec: RXN-emit — domain-event emit seam (DomainEvent + EventBus + subscriber registry)

**Identity:** The reaction layer's publish side — a thin `DomainEvent` value type, an `EventBus` with `emit`/`subscribe`, and the canonical event-type registry that spokes publish at their write points (`email-ingested`, `txn-recorded`, `bill-recorded`, `subscription-detected`, `task-done`, `fact-added`, …). Every emit is observable (loggable) and carries IDs + scalars + entity-refs only — never raw text/titles.
→ why: see docs/technical/adr/ADR-021-cross-module-reactions.md (Decision 3-i: emit events) · docs/technical/contracts.md Seam 5/7 (payload = ids/timestamps/counts only; no raw text).

<!-- ONE logical phase: the event value type + the bus + the event-type constants. 1 new package + 2 src files + 1 test. The dispatcher (RXN-dispatcher) consumes DomainEvent; the rule store (RXN-rulestore) binds rules to event_type strings. Spokes ADD emit() calls at their write points — those edits are per-recipe wiring (RXN-recipes-*), NOT this spec; this spec lists the canonical emit points as a wiring contract. -->

## Assumptions

- **M1-a** complete: `EntityRef` is NOT defined here — `EntityRef{module, entity_id}` comes from M4-d-1 (contracts.md Seam 6). RXN-emit imports it for the `entity_refs` field. → impact: Stop (the event references entities by `EntityRef`, never by raw name or a cross-store join).
- **M0-a** complete: `Settings`, `get_settings`, logging conventions. The bus uses the stdlib `logging` module for observability (one log line per emit at debug, content-free — event_type + source_module + entity_ref ids + payload KEYS only, never payload values that might carry a scalar the privacy rule still wants summarised). → impact: Low.
- The bus is **in-process, synchronous-dispatch-to-async-subscribers**: `emit(event)` is a plain method that appends to a subscriber's queue / calls each subscriber. Subscribers (the dispatcher) are `async` callables; `emit` itself does not block on them — it schedules. To keep RXN-emit dependency-free and testable, `emit` is **sync** and records the event + invokes each registered sync sink; the async dispatcher registers a **sync shim** that enqueues onto an `asyncio.Queue` the dispatcher drains (the shim is provided by RXN-dispatcher, not here). → impact: Stop (this keeps the producer side — spoke write points — sync and non-blocking; the async work is the dispatcher's).
- **Payload privacy (Seam 5/7 — load-bearing):** a `DomainEvent.payload` is `dict[str, str | int | float | bool]` — scalars only. NO `list`/`dict`/raw-text values. Titles, subjects, bodies, notes NEVER enter a payload. Cross-module references ride `entity_refs: tuple[EntityRef, ...]`; domain-row identity rides scalar `*_id` fields in the payload. The model **validates** that every payload value is a scalar (raise `ValueError` on a non-scalar). → impact: Stop (this is the privacy wall — reactions are observable but the event stream never leaks owner content).
- Off-hardware: pure in-process, deterministic, no I/O, no model. → impact: Low.

Simplicity check: considered a persistent event log (durable queue) — rejected for v1; the dispatcher's idempotency ledger (RXN-dispatcher) provides the durability where it matters (de-dup), and an in-process bus is the minimum that lets spokes publish + the dispatcher subscribe. A full pub/sub broker is premature on a single-owner appliance. The scalar-only payload constraint is enforced by the model so privacy is structural, not by-convention.

## Prerequisites

- Specs complete: **M0-a** (Settings/logging), **M4-d-1** (`EntityRef`).
- Environment: no new PyPI deps (stdlib only). `uv sync` suffices off-hardware.

## Files to Change

| File | Operation | Notes |
|------|-----------|-------|
| `/Users/artemis-build/artemis/src/artemis/reactions/__init__.py` | create | package marker + re-exports (`DomainEvent`, `EventType`, `EventBus`) |
| `/Users/artemis-build/artemis/src/artemis/reactions/emit.py` | create | `EventType` constants, `DomainEvent` model, `EventBus` (`emit`/`subscribe`) |
| `/Users/artemis-build/artemis/tests/test_reactions_emit.py` | create | event construction + scalar-payload validation, bus emit→subscriber fan-out, observability log, privacy rejection |

All paths under `/Users/artemis-build/artemis/`.

## Tasks

- [ ] **Task 1: Define `EventType` + `DomainEvent`** — files: `/Users/artemis-build/artemis/src/artemis/reactions/emit.py`, `/Users/artemis-build/artemis/src/artemis/reactions/__init__.py` —

  `EventType` — a `StrEnum` of the canonical domain events (the contract the rule store binds to):
  ```python
  class EventType(StrEnum):
      EMAIL_INGESTED = "email-ingested"
      TXN_RECORDED = "txn-recorded"
      BILL_RECORDED = "bill-recorded"
      SUBSCRIPTION_DETECTED = "subscription-detected"
      TASK_DONE = "task-done"
      TASK_CREATED = "task-created"
      FACT_ADDED = "fact-added"
      EVENT_INGESTED = "event-ingested"        # calendar/email-derived event extract
      PAYMENT_RECORDED = "payment-recorded"    # A9 settlement signal
      TRIP_ASSEMBLED = "trip-assembled"        # TRIP-entity: a Trip was assembled/revised
      BILL_PAID = "bill-paid"                  # a bill's lifecycle flipped open→paid (A1/A9 settlement)
  ```
  (New event types are added here as recipes need them — this enum is the single registry.)

  **Producer + payload contract for the added event types** (the binding the per-spec emit call-sites honour):
  - **`TRIP_ASSEMBLED`** — producer: **TRIP-entity** (`TripAssembler.assemble`), source_module `"travel"`. entity_refs: the `trip:<id>` EntityRef. payload scalars: `trip_id`, `destination_place_id` (str, may be `""`), `start_dt`, `end_dt`, `leg_count` (int). Consumed by RXN-recipes-planning (airport-leave block). dedup_key: `f"trip-assembled:{trip_id}"`.
  - **`BILL_PAID`** — producer: **RXN-recipes-self** (A1 settlement / A9 reconcile), emitted at the point a bill is marked paid (around the injected `mark_bill_paid_fn` call-site in `reactions/recipes/self.py`), source_module `"finance"`. payload scalars: `bill_id`, `payee`. Consumed by RXN-recipes-self's bill-lifecycle reaction (completes the linked task). dedup_key: `f"bill-paid:{bill_id}"`.

  `DomainEvent` (frozen Pydantic, `extra="forbid"`):
  ```python
  class DomainEvent(BaseModel):
      model_config = ConfigDict(frozen=True, extra="forbid")
      event_type: EventType
      source_module: str                              # e.g. "gmail", "finance", "tasks"
      entity_refs: tuple[EntityRef, ...] = ()         # cross-module references (Seam 6)
      payload: dict[str, str | int | float | bool] = {}  # SCALARS ONLY (ids/dates/counts/amounts-as-str)
      occurred_at: str                                # ISO-8601 UTC
      dedup_key: str                                  # stable idempotency key (dispatcher dedups on this)
  ```
  `model_validator(mode="after")`: assert every `payload` value `isinstance(v, (str, int, float, bool))` (a `list`/`dict`/`None` value raises `ValueError("DomainEvent payload values must be scalars — no raw text/structures")`); assert `dedup_key` is non-empty. (Booleans are ints in Python — accept; the constraint is "no containers".)

  Re-export `DomainEvent`, `EventType`, `EventBus` from `__init__.py` with `__all__`.

  — done when: `uv run mypy --strict src` passes; `DomainEvent(event_type=EventType.TXN_RECORDED, source_module="finance", payload={"txn_id":"x","amount":"19.99"}, occurred_at="2026-06-23T00:00:00+00:00", dedup_key="txn:x")` constructs; a payload with a `list` value raises `ValidationError`; an empty `dedup_key` raises.

- [ ] **Task 2: Implement `EventBus`** — files: `/Users/artemis-build/artemis/src/artemis/reactions/emit.py` —

  ```python
  Subscriber = Callable[[DomainEvent], None]   # sync sink; the async dispatcher registers a sync enqueue shim

  class EventBus:
      def __init__(self, *, logger: logging.Logger | None = None) -> None:
          self._subscribers: list[Subscriber] = []
          self._log = logger or logging.getLogger("artemis.reactions.emit")

      def subscribe(self, sink: Subscriber) -> None:
          """Register a sink. The dispatcher registers a sync shim that enqueues onto its asyncio.Queue."""
          self._subscribers.append(sink)

      def emit(self, event: DomainEvent) -> None:
          """Publish a domain event to all subscribers. Non-blocking: each sink is a sync enqueue.
          Observability: logs event_type + source_module + entity-ref ids + payload KEYS (never values)."""
          self._log.debug(
              "emit %s from %s refs=%s keys=%s dedup=%s",
              event.event_type, event.source_module,
              [r.entity_id for r in event.entity_refs], sorted(event.payload.keys()), event.dedup_key,
          )
          for sink in self._subscribers:
              try:
                  sink(event)
              except Exception:
                  # A failing subscriber must NOT break the emitting spoke's write path (degrade-don't-crash).
                  self._log.warning("reaction subscriber failed for %s", event.event_type, exc_info=True)
  ```

  **Observability invariant (inline comment):** the emit log line carries event_type + source_module + entity-ref IDs + payload KEYS — NEVER payload VALUES (a scalar value could still be a sensitive amount/date the privacy posture wants kept out of logs) and NEVER any raw text.

  — done when: `uv run mypy --strict src` passes; `bus.subscribe(spy); bus.emit(event)` calls `spy` once with the event; a raising subscriber does NOT propagate out of `emit` (other subscribers still called); the emit log line contains the event_type but not any payload value.

- [ ] **Task 3: Tests** — files: `/Users/artemis-build/artemis/tests/test_reactions_emit.py` — typed pytest.

  - **DomainEvent construction:** valid scalar payload constructs; `entity_refs` round-trips.
  - **Scalar-payload privacy:** `DomainEvent(..., payload={"titles": ["a","b"]})` raises `ValidationError`; `payload={"note": {"x":1}}` raises.
  - **Empty dedup_key:** raises.
  - **Bus fan-out:** two subscribers; `emit` calls both once with the same event.
  - **Subscriber failure isolation:** a subscriber that raises does not stop `emit` from calling the other; no exception propagates.
  - **Observability:** capture the bus logger at DEBUG; assert the emit log record contains the `event_type` string and the payload KEY names but NOT a payload value (e.g. the amount string `"19.99"` is absent from the formatted record).

  — done when: `uv run pytest -q tests/test_reactions_emit.py` passes AND `uv run mypy --strict src tests/test_reactions_emit.py` passes AND `uv run ruff check . && uv run ruff format --check .` both exit 0.

## Canonical emit-point wiring contract (consumed by RXN-recipes-*, not built here)

Spokes add `bus.emit(DomainEvent(...))` at these write points (the per-recipe specs apply these edits; RXN-emit only fixes the contract):
- **Gmail (M8-b1):** after a signal email is ingested → `EMAIL_INGESTED` (payload: `message_id`, `category`; entity_refs: sender PERSON).
- **Finance (FIN-c):** `add_transaction` → `TXN_RECORDED` (payload: `txn_id`, `txn_type`, `amount`, `instrument_account_id`); bill detect → `BILL_RECORDED`; subscription detect → `SUBSCRIPTION_DETECTED`; payment/settlement → `PAYMENT_RECORDED`.
- **Tasks (M8-d-a):** `complete_task` → `TASK_DONE` (payload: `task_id`); `create_task` → `TASK_CREATED`.
- **Memory (M4-b):** module-pushed fact-add → `FACT_ADDED` (payload: `fact_id`; entity_refs: subject).
- **Calendar/email-event-extract (CAL-create-from-extract):** held tentative event built → `EVENT_INGESTED`.
- **Travel (TRIP-entity):** `TripAssembler.assemble` → `TRIP_ASSEMBLED` (payload: `trip_id`, `destination_place_id`, `start_dt`, `end_dt`, `leg_count`; entity_refs: the `trip:<id>` ref).
- **Self/Finance reactions (RXN-recipes-self):** a bill marked paid (A1/A9) → `BILL_PAID` (payload: `bill_id`, `payee`).

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | `/Users/artemis-build/artemis/src/artemis/reactions/__init__.py` |
| Create | `/Users/artemis-build/artemis/src/artemis/reactions/emit.py` |
| Create | `/Users/artemis-build/artemis/tests/test_reactions_emit.py` |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict src tests/test_reactions_emit.py` | Type gate |
| `uv run ruff check . && uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q tests/test_reactions_emit.py` | Test gate |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | `src/artemis/reactions/__init__.py`, `src/artemis/reactions/emit.py`, `tests/test_reactions_emit.py` |
| `git commit` | `"feat: RXN-emit — domain-event emit seam (DomainEvent + EventBus, scalar-only payloads)"` |

### Environment Access
| Variable | Purpose |
|----------|---------|
| (none) | Pure in-process |

### Network
| Action | Purpose |
|--------|---------|
| (none) | No deps; no network |

## Specialist Context

### Security

- **Payload privacy is structural (Seam 5/7):** the `DomainEvent` model validates that payloads are scalars only — titles/subjects/bodies/notes cannot enter the event stream by construction. Cross-module references are `EntityRef` (logical pointers), never names or cross-store joins (ADR-013 D2). The emit log carries keys + ids, never values.
- **Degrade-don't-crash:** a failing subscriber never breaks the emitting spoke's owned-write path — `emit` swallows + logs subscriber exceptions. A spoke's source-of-truth write is never coupled to a reaction's success.
- **No external effect here:** `emit` is publish-only; it dispatches nothing. The GATE/external-effect routing is the dispatcher's job (RXN-dispatcher). [apex-security note: confirm no payload value is ever logged; confirm the scalar-only validator rejects nested structures.]

### Performance

- In-process synchronous fan-out to a handful of sinks — O(subscribers) per emit, negligible. The single subscriber in practice is the dispatcher's enqueue shim (an `asyncio.Queue.put_nowait`). No I/O on the emit path → the spoke write point pays ~nothing.

### Accessibility

(none — headless infra)

## Documentation

| Doc type | File | Action |
|----------|------|--------|
| Inline | `src/artemis/reactions/emit.py` | Docstring the scalar-only payload privacy rule, the sync-emit/async-subscriber split, the observability-log content rule, and the canonical event-type registry |

## Acceptance Criteria

- [ ] `uv run mypy --strict src tests/test_reactions_emit.py` → verify: exit 0.
- [ ] `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.
- [ ] `uv run pytest -q tests/test_reactions_emit.py` → verify: DomainEvent constructs with scalar payload; non-scalar payload + empty dedup_key raise; bus fan-out calls all subscribers once; a raising subscriber is isolated; emit log carries keys not values.
- [ ] `uv run python -c "from artemis.reactions import DomainEvent, EventType, EventBus; print('ok')"` → verify: prints `ok`.

## Progress
_(Coding mode writes here — do not edit manually)_
