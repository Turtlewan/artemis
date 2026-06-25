---
spec: R3-linked-task-ref
status: draft
cross_model_review: false
token_profile: balanced
autonomy_level: L2
---

# Spec: R3 — `linked_task_ref` propagation (unblock `react_bill_paid_lifecycle`)

**Identity:** Propagate a bill's `linked_task_ref` from the FIN-c mark-paid path through A1/A9 into the `BILL_PAID` event so `react_bill_paid_lifecycle` completes the linked task in production instead of returning "skipped".
→ why: see docs/technical/adr/ADR-032-reactions-runtime-composition.md (Decision 5).

## Assumptions
<!-- Coding mode verifies each item before executing. -->
- `bill_paid_event()` lives in `src/artemis/reactions/recipes/self.py` (NOT finance/events.py) with signature `bill_paid_event(*, bill_id: str, payee: str)`; only A1 (`react_statement_to_settlement`) and A9 (`react_payment_reconcile`) call it. → impact: Stop (changes which files are touched).
- `react_bill_paid_lifecycle` already reads `linked_task_ref` from the BILL_PAID payload (self.py L252) and returns `status="skipped"` when absent — no change needed to the consumer, only to the producer. → impact: Stop.
- `DomainEvent.payload` is scalar-only (`dict[str, str | int | float | bool]`, `extra="forbid"`, validator rejects non-scalars) — a `str | None` ref must be omitted from the payload dict when `None`, never set to `None`. → impact: Stop (a `None` value would raise at construction).
- The bill row already carries `linked_task_ref` (schema.py L154, `bill` table column) and `_bill_row` (repository.py L646) returns it via `dict(row)` from `SELECT *`, so a `get_bill(id)` read exposes it with no schema change. → impact: Stop (if column were absent, scope balloons to a migration).
- `mark_bill_paid(id)` returns `None` (store.py L257, repository.py L445); it does NOT expose the bill record. A1/A9 therefore cannot source the ref from the mark-paid return — a separate read seam is required. → impact: Caution. Minimal viable approach (chosen): add a `get_bill(id)` read to store+repo and inject a `get_linked_task_ref_fn: Callable[[str], Awaitable[str | None]]` into A1/A9 (recipes stay store-agnostic). Rejected: changing `mark_bill_paid` to return the row (churns the existing FIN-c signature + its callers/tests for no other benefit).
- `tests/test_reactions_self.py` (L518-520) asserts `self.py` source contains no `FinanceStore`, `repository`, or `store.` — so A1/A9 MUST source the ref via the injected callable, never by importing the store. → impact: Stop (a direct store import fails the existing guard test).
- No `compose.py` exists yet (R1 builds it); `register_self_reactions` is the only wiring point today and is exercised only by tests. This spec adds the `get_linked_task_ref_fn` parameter to `register_self_reactions` and its A1/A9 partials; R1/R2/R4 do not touch self.py. → impact: Low.

Simplicity check: considered simpler approach? yes — making `mark_bill_paid` return the bill row would avoid a new read method, but it churns the existing FIN-c signature and all its callers/tests; the injected read seam is more surgical and keeps the recipe store-agnostic (required by the L518-520 guard test). This version chosen.

## Prerequisites
- Specs that must be complete first: none (independent of R1/R2/R4 per ADR-032 build plan).
- Environment setup required: none.

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| src/artemis/modules/finance/repository.py | modify | Add `get_bill(self, id: str) -> dict[str, object] | None` returning `_bill_row(row)` or `None`. |
| src/artemis/modules/finance/store.py | modify | Add `get_bill(self, id: str) -> dict[str, object] | None` delegating to `self._repo().get_bill(id)`. |
| src/artemis/reactions/recipes/self.py | modify | Add `linked_task_ref` param to `bill_paid_event`; add `GetLinkedTaskRefFn` type + param to A1, A9, their tool partials, and `register_self_reactions`; source + pass the ref. |
| tests/test_reactions_self.py | modify | New tests: A1/A9 carry the ref in the BILL_PAID payload; lifecycle completes the linked task end-to-end; no-ref bill still works. |
| tests/test_finance_store.py | modify | Test `get_bill` returns the row incl. `linked_task_ref`, and `None` for a missing id. |

## Tasks
- [ ] Task 1: Add `get_bill(id)` read to the finance store + repository — files: src/artemis/modules/finance/repository.py, src/artemis/modules/finance/store.py — done when: `FinanceStore.get_bill(bill_id)` returns the bill dict including `linked_task_ref`, or `None` for an unknown id; `uv run mypy` clean.
- [ ] Task 2: Propagate `linked_task_ref` through `bill_paid_event` + A1/A9 + registration — files: src/artemis/reactions/recipes/self.py — done when: `bill_paid_event(*, bill_id, payee, linked_task_ref=None)` includes the ref in the payload only when set; A1 and A9 accept an injected `get_linked_task_ref_fn`, call it after a successful mark-paid, and pass the result into `bill_paid_event`; `register_self_reactions` takes and threads `get_linked_task_ref_fn`; the L518-520 guard test still passes (no `store.`/`FinanceStore`/`repository` in self.py).
- [ ] Task 3: Tests for the read seam + end-to-end propagation — files: tests/test_finance_store.py, tests/test_reactions_self.py — done when: all new tests pass under `uv run pytest -q`.

## Wave plan
Wave 1: [Task 1, Task 2] | Wave 2: [Task 3]

## Exact changes

### Task 1 — `get_bill` read seam

`repository.py` — add next to `list_bills` / `mark_bill_paid`:
```python
def get_bill(self, id: str) -> dict[str, object] | None:
    row = self.conn.execute("SELECT * FROM bill WHERE id = ?", (id,)).fetchone()
    return _bill_row(row) if row is not None else None
```

`store.py` — add next to `list_bills` / `mark_bill_paid`:
```python
def get_bill(self, id: str) -> dict[str, object] | None:
    return self._repo().get_bill(id)
```

### Task 2 — propagate the ref (`self.py`)

Add the injected read type alongside the existing aliases (near `MarkBillPaidFn`):
```python
GetLinkedTaskRefFn = Callable[[str], Awaitable[str | None]]
```

`bill_paid_event` — add optional param, include in payload only when present (payload is scalar-only; never set `None`):
```python
def bill_paid_event(
    *, bill_id: str, payee: str, linked_task_ref: str | None = None
) -> DomainEvent:
    """Build the scalar-only BILL_PAID event consumed by lifecycle reactions."""
    payload: dict[str, str | int | float | bool] = {"bill_id": bill_id, "payee": payee}
    if linked_task_ref is not None:
        payload["linked_task_ref"] = linked_task_ref
    return DomainEvent(
        event_type=EventType.BILL_PAID,
        source_module="finance",
        payload=payload,
        occurred_at=datetime.now(UTC).isoformat(),
        dedup_key=f"bill-paid:{bill_id}",
    )
```

`react_statement_to_settlement` (A1) — add `get_linked_task_ref_fn: GetLinkedTaskRefFn` kw-only param; after the successful mark-paid emit, source the ref:
```python
    mark_result = await mark_bill_paid_fn(bill_id)
    if not _tool_changed(mark_result):
        return ReactionResult(status="settled", ref=bill_id, undoable=True)
    linked_task_ref = await get_linked_task_ref_fn(bill_id)
    emit(bill_paid_event(bill_id=bill_id, payee=_payee(event), linked_task_ref=linked_task_ref))
    return ReactionResult(status="settled", ref=bill_id, undoable=True)
```

`react_payment_reconcile` (A9) — add `get_linked_task_ref_fn: GetLinkedTaskRefFn` kw-only param; source the ref for the emit (the existing `task_ref` from the payload still drives the inline `complete_task_fn` call — leave that branch unchanged):
```python
    mark_result = await mark_bill_paid_fn(bill_id)
    if not _tool_changed(mark_result):
        return ReactionResult(status="reconciled", ref=bill_id, undoable=True)
    task_ref = _payload_str(event, "linked_task_ref")
    if task_ref is not None:
        await complete_task_fn(_task_id_from_ref(task_ref))
    linked_task_ref = await get_linked_task_ref_fn(bill_id)
    emit(bill_paid_event(bill_id=bill_id, payee=_payee(event), linked_task_ref=linked_task_ref))
    return ReactionResult(status="reconciled", ref=bill_id, undoable=True)
```

Thread the new param through the tool partials (`_statement_to_settlement_tool`, `_payment_reconcile_tool`) and `register_self_reactions` (add `get_linked_task_ref_fn: GetLinkedTaskRefFn` kw-only param; include it in the `partial(...)` for `settlement_callable` and `payment_callable`).

### Task 3 — tests (`self.py` recipe tests + `store` test)

In `tests/test_reactions_self.py`:
- A fake `get_linked_task_ref_fn` returning `"tasks:task:task-bill-1"`; assert A1 and A9 emit a BILL_PAID event whose payload includes `linked_task_ref`.
- End-to-end: feed that emitted event into `react_bill_paid_lifecycle` with a spy `complete_task_fn`; assert `status == "task_completed"` and the spy was called with `"task-bill-1"` (vs the current "skipped").
- No-ref regression: fake returns `None`; assert the emitted payload has no `linked_task_ref` key and lifecycle returns `status="skipped"` without calling `complete_task_fn`.
- Update existing `register_self_reactions` call sites in this test to pass the new `get_linked_task_ref_fn`.

In `tests/test_finance_store.py`: insert a bill with a `linked_task_ref`, assert `store.get_bill(id)["linked_task_ref"]` matches, and `store.get_bill("missing")` is `None`.

## Permissions

The following actions will run autonomously during build. Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Modify | src/artemis/modules/finance/repository.py, src/artemis/modules/finance/store.py, src/artemis/reactions/recipes/self.py, tests/test_reactions_self.py, tests/test_finance_store.py |
| Create | (none) |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy` | Full-project type check. |
| `uv run ruff check . && uv run ruff format --check .` | Lint + format gate. |
| `uv run pytest -q` | Full test suite. |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | The five files listed above (by name). |
| `git commit` | "feat: R3 propagate bill linked_task_ref into BILL_PAID (unblock bill-paid lifecycle)" |

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
(none — local owner-private ledger read only; no new external surface.)

### Performance
(none — `get_bill` is an indexed primary-key lookup.)

### Accessibility
(none — no frontend change.)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | src/artemis/modules/finance/{store,repository}.py, src/artemis/reactions/recipes/self.py | Docstrings on `get_bill` and the updated `bill_paid_event`. |
| ADR | docs/technical/adr/ADR-032-reactions-runtime-composition.md | None — already records Decision 5; do not edit. |

## Acceptance Criteria
- [ ] Add `get_bill(id)` to store + repo → verify: `uv run pytest -q tests/test_finance_store.py` passes the new `get_bill` returns-row / returns-None tests.
- [ ] `bill_paid_event(..., linked_task_ref="tasks:task:task-1")` includes the key; `bill_paid_event(...)` (no ref) omits it → verify: new builder tests pass and `test_bill_paid_event_builder_shape` (no-ref) still asserts `payload == {"bill_id":..., "payee":...}`.
- [ ] A1 and A9 emit BILL_PAID carrying `linked_task_ref` sourced from `get_linked_task_ref_fn` → verify: new A1/A9 payload tests pass.
- [ ] An A1/A9-emitted BILL_PAID with a ref drives `react_bill_paid_lifecycle` to `status="task_completed"` and completes the task → verify: end-to-end test passes (was "skipped").
- [ ] A bill with no `linked_task_ref` regresses cleanly → verify: no-ref test shows lifecycle `status="skipped"`, `complete_task_fn` not called.
- [ ] `self.py` store-agnostic guard holds → verify: `test_no_cloud_import_guard_and_adr_011_tool_injection` still passes (no `store.`/`FinanceStore`/`repository` in self.py).
- [ ] Whole project clean → verify: `uv run mypy`, `uv run ruff check . && uv run ruff format --check .`, and `uv run pytest -q` all pass.

## Progress
_(Coding mode writes here — do not edit manually)_
