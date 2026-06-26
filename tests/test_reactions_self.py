from __future__ import annotations

import inspect
from collections.abc import Sequence
from decimal import Decimal
from typing import cast

import pytest

from artemis.memory import EntityRef
from artemis.ports.types import Vector
from artemis.reactions.emit import DomainEvent, EventType
from artemis.reactions.recipes import register_self_reactions
from artemis.reactions.recipes import self as self_recipes
from artemis.reactions.recipes.self import (
    BillTaskResult,
    FraudSignal,
    ReactionArgs,
    ReactionResult,
    bill_paid_event,
    react_bill_paid_lifecycle,
    react_bill_to_task,
    react_fraud_confirm,
    react_payment_reconcile,
    react_statement_to_settlement,
)
from artemis.reactions.reconciler import MatchOutcome, MatchResult, ReconcileRecord
from artemis.reactions.rulestore import TIER_A_BUILTINS, ReactionRule, ReactionTier
from artemis.registry import ToolRegistry
from artemis.runtime_config import ReactionConfig, RuntimeConfig


class OkResult:
    def __init__(self, *, changed: bool = True) -> None:
        self.changed = changed


class FakeEmbedder:
    @property
    def dimension(self) -> int:
        return 2

    async def embed_documents(self, texts: Sequence[str]) -> list[Vector]:
        return [[1.0, 0.0] for _ in texts]

    async def embed_query(self, query: str) -> Vector:
        del query
        return [1.0, 0.0]


class FakeCaptureService:
    def __init__(self) -> None:
        self.tasks: dict[str, BillTaskResult] = {}
        self.calls: list[dict[str, str]] = []

    async def create_task_from_bill(
        self,
        *,
        bill_id: str,
        title: str,
        due_at: str,
        source: str,
    ) -> BillTaskResult:
        if bill_id not in self.tasks:
            task = BillTaskResult(
                task_id=f"task-{bill_id}",
                linked_task_ref=f"tasks:task:task-{bill_id}",
                due_at=due_at,
                source=source,
            )
            self.tasks[bill_id] = task
            self.calls.append(
                {"bill_id": bill_id, "title": title, "due_at": due_at, "source": source}
            )
        return self.tasks[bill_id]


class FakeMarkBillPaidFn:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.store_writes: list[str] = []
        self.spend_writes: list[str] = []
        self.paid: set[str] = set()

    async def __call__(self, bill_id: str) -> OkResult:
        if bill_id not in self.paid:
            self.calls.append(bill_id)
            self.paid.add(bill_id)
            return OkResult(changed=True)
        return OkResult(changed=False)


class FakeGetLinkedTaskRefFn:
    def __init__(self, linked_task_ref: str | None = "tasks:task:task-bill-1") -> None:
        self.linked_task_ref = linked_task_ref
        self.calls: list[str] = []

    async def __call__(self, bill_id: str) -> str | None:
        self.calls.append(bill_id)
        return self.linked_task_ref


class FakeCompleteTaskFn:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.open_tasks: set[str] = set()

    async def __call__(self, task_id: str) -> OkResult:
        if task_id not in self.calls:
            self.calls.append(task_id)
        self.open_tasks.discard(task_id)
        return OkResult()


class FakeReconciler:
    def __init__(self, outcome: MatchOutcome, *, matched_id: str | None = "bill-1") -> None:
        self.outcome = outcome
        self.matched_id = matched_id
        self.calls: list[tuple[ReconcileRecord, Sequence[ReconcileRecord]]] = []
        self.keyword_calls: list[dict[str, object]] = []

    def match(
        self,
        target: ReconcileRecord,
        candidates: Sequence[ReconcileRecord],
    ) -> MatchResult:
        self.calls.append((target, candidates))
        return MatchResult(
            outcome=self.outcome,
            target_id=target.id,
            matched_id=self.matched_id if self.outcome is MatchOutcome.EXACT else None,
            score=1.0 if self.outcome is MatchOutcome.EXACT else 0.0,
            reason=self.outcome.value,
        )


class FakeFraudNotifyFn:
    def __init__(self) -> None:
        self.calls: list[FraudSignal] = []
        self.card_block_calls: list[str] = []

    async def __call__(self, signal: FraudSignal) -> OkResult:
        self.calls.append(signal)
        return OkResult()


class EmitSpy:
    def __init__(self) -> None:
        self.events: list[DomainEvent] = []

    def __call__(self, event: DomainEvent) -> None:
        self.events.append(event)


class FakeDispatcher:
    def __init__(self) -> None:
        self.ledger: set[str] = set()

    async def fire_a1(
        self,
        rule: ReactionRule,
        event: DomainEvent,
        mark_paid: FakeMarkBillPaidFn,
        get_linked_task_ref: FakeGetLinkedTaskRefFn,
        emit: EmitSpy,
    ) -> None:
        if self._seen(rule, event):
            return
        await react_statement_to_settlement(
            event,
            mark_bill_paid_fn=mark_paid,
            get_linked_task_ref_fn=get_linked_task_ref,
            emit=emit,
        )

    async def fire_a6(
        self,
        rule: ReactionRule,
        event: DomainEvent,
        capture: FakeCaptureService,
    ) -> None:
        if self._seen(rule, event):
            return
        await react_bill_to_task(event, capture_service=capture)

    async def fire_a9(
        self,
        rule: ReactionRule,
        event: DomainEvent,
        reconciler: FakeReconciler,
        mark_paid: FakeMarkBillPaidFn,
        get_linked_task_ref: FakeGetLinkedTaskRefFn,
        complete: FakeCompleteTaskFn,
        emit: EmitSpy,
    ) -> None:
        if self._seen(rule, event):
            return
        await react_payment_reconcile(
            event,
            reconciler=reconciler,
            mark_bill_paid_fn=mark_paid,
            get_linked_task_ref_fn=get_linked_task_ref,
            complete_task_fn=complete,
            emit=emit,
        )

    async def fire_b4c(
        self,
        rule: ReactionRule,
        event: DomainEvent,
        reconciler: FakeReconciler,
        notify: FakeFraudNotifyFn,
    ) -> None:
        if self._seen(rule, event):
            return
        await react_fraud_confirm(event, reconciler=reconciler, fraud_notify_fn=notify)

    def _seen(self, rule: ReactionRule, event: DomainEvent) -> bool:
        key = _stable_key(rule, event)
        if key in self.ledger:
            return True
        self.ledger.add(key)
        return False


async def test_a1_settlement_marks_statement_bill_paid_emits_bill_paid_and_dedups() -> None:
    mark_paid = FakeMarkBillPaidFn()
    get_linked_task_ref = FakeGetLinkedTaskRefFn()
    emit = EmitSpy()
    event = _payment_event(txn_type="settlement")

    result = await react_statement_to_settlement(
        event,
        mark_bill_paid_fn=mark_paid,
        get_linked_task_ref_fn=get_linked_task_ref,
        emit=emit,
    )
    await react_statement_to_settlement(
        event,
        mark_bill_paid_fn=mark_paid,
        get_linked_task_ref_fn=get_linked_task_ref,
        emit=emit,
    )

    assert result.status == "settled"
    assert result.ref == "bill-1"
    assert mark_paid.calls == ["bill-1"]
    assert get_linked_task_ref.calls == ["bill-1"]
    assert mark_paid.spend_writes == []
    assert [emitted.event_type for emitted in emit.events] == [EventType.BILL_PAID]
    assert emit.events[0].payload == {
        "bill_id": "bill-1",
        "payee": "Utility Co",
        "linked_task_ref": "tasks:task:task-bill-1",
    }

    dispatcher_mark_paid = FakeMarkBillPaidFn()
    dispatcher_get_linked_task_ref = FakeGetLinkedTaskRefFn()
    dispatcher_emit = EmitSpy()
    dispatcher = FakeDispatcher()
    await dispatcher.fire_a1(
        _builtin("cc_settlement_marker"),
        event,
        dispatcher_mark_paid,
        dispatcher_get_linked_task_ref,
        dispatcher_emit,
    )
    await dispatcher.fire_a1(
        _builtin("cc_settlement_marker"),
        event,
        dispatcher_mark_paid,
        dispatcher_get_linked_task_ref,
        dispatcher_emit,
    )
    assert dispatcher_mark_paid.calls == ["bill-1"]
    assert dispatcher_get_linked_task_ref.calls == ["bill-1"]
    assert len(dispatcher_emit.events) == 1


async def test_a6_bill_to_task_creates_dated_pay_task_and_dedups() -> None:
    capture = FakeCaptureService()
    event = _bill_event()

    result = await react_bill_to_task(event, capture_service=capture)
    second = await react_bill_to_task(event, capture_service=capture)

    assert result.status == "task_created"
    assert result.ref == "task-bill-1"
    assert second.ref == "task-bill-1"
    assert capture.calls == [
        {
            "bill_id": "bill-1",
            "title": "Pay Utility Co by 2026-07-01",
            "due_at": "2026-07-01",
            "source": "finance:bill:bill-1",
        }
    ]
    task = capture.tasks["bill-1"]
    assert task.due_at == "2026-07-01"
    assert task.source == "finance:bill:bill-1"
    assert task.linked_task_ref == "tasks:task:task-bill-1"

    dispatcher = FakeDispatcher()
    capture_via_dispatcher = FakeCaptureService()
    await dispatcher.fire_a6(_builtin("bill_to_task"), event, capture_via_dispatcher)
    await dispatcher.fire_a6(_builtin("bill_to_task"), event, capture_via_dispatcher)
    assert len(capture_via_dispatcher.calls) == 1


async def test_a9_exact_match_marks_paid_completes_task_emits_and_uses_canonical_match() -> None:
    reconciler = FakeReconciler(MatchOutcome.EXACT)
    mark_paid = FakeMarkBillPaidFn()
    get_linked_task_ref = FakeGetLinkedTaskRefFn()
    complete = FakeCompleteTaskFn()
    emit = EmitSpy()

    result = await react_payment_reconcile(
        _payment_event(txn_type="payment"),
        reconciler=reconciler,
        mark_bill_paid_fn=mark_paid,
        get_linked_task_ref_fn=get_linked_task_ref,
        complete_task_fn=complete,
        emit=emit,
    )

    assert result.status == "reconciled"
    assert result.ref == "bill-1"
    assert mark_paid.calls == ["bill-1"]
    assert get_linked_task_ref.calls == ["bill-1"]
    assert complete.calls == ["task-1"]
    assert [event.event_type for event in emit.events] == [EventType.BILL_PAID]
    assert emit.events[0].payload["linked_task_ref"] == "tasks:task:task-bill-1"
    target, candidates = reconciler.calls[0]
    assert isinstance(target, ReconcileRecord)
    assert all(isinstance(candidate, ReconcileRecord) for candidate in candidates)
    assert target.id == "txn-1"
    assert candidates[0].id == "bill-1"
    assert reconciler.keyword_calls == []


async def test_a9_ambiguous_and_none_do_not_mark_paid() -> None:
    for outcome, expected_status in (
        (MatchOutcome.AMBIGUOUS, "ambiguous"),
        (MatchOutcome.NONE, "unmatched"),
    ):
        reconciler = FakeReconciler(outcome)
        mark_paid = FakeMarkBillPaidFn()
        complete = FakeCompleteTaskFn()
        emit = EmitSpy()

        result = await react_payment_reconcile(
            _payment_event(txn_type="payment"),
            reconciler=reconciler,
            mark_bill_paid_fn=mark_paid,
            get_linked_task_ref_fn=FakeGetLinkedTaskRefFn(),
            complete_task_fn=complete,
            emit=emit,
        )

        assert result.status == expected_status
        assert mark_paid.calls == []
        assert complete.calls == []
        assert emit.events == []


async def test_a9_refire_is_deduped_by_rule_key() -> None:
    event = _payment_event(txn_type="payment")
    reconciler = FakeReconciler(MatchOutcome.EXACT)
    mark_paid = FakeMarkBillPaidFn()
    get_linked_task_ref = FakeGetLinkedTaskRefFn()
    complete = FakeCompleteTaskFn()
    emit = EmitSpy()
    dispatcher = FakeDispatcher()

    await dispatcher.fire_a9(
        _builtin("payment_bill_link"),
        event,
        reconciler,
        mark_paid,
        get_linked_task_ref,
        complete,
        emit,
    )
    await dispatcher.fire_a9(
        _builtin("payment_bill_link"),
        event,
        reconciler,
        mark_paid,
        get_linked_task_ref,
        complete,
        emit,
    )

    assert len(reconciler.calls) == 1
    assert mark_paid.calls == ["bill-1"]
    assert get_linked_task_ref.calls == ["bill-1"]
    assert complete.calls == ["task-1"]
    assert len(emit.events) == 1


async def test_b4c_over_threshold_no_receipt_notifies_only_and_dedups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(self_recipes, "get_runtime_config", RuntimeConfig)
    reconciler = FakeReconciler(MatchOutcome.NONE, matched_id=None)
    notify = FakeFraudNotifyFn()
    # Clearly ABOVE the ~S$500 X3 threshold so the over-threshold path is proven
    # unambiguously (not sitting exactly on the boundary).
    event = _txn_event(amount="600.00", receipt=False)

    result = await react_fraud_confirm(event, reconciler=reconciler, fraud_notify_fn=notify)

    assert result.status == "fraud_signal"
    assert result.ref == "txn-1"
    assert len(notify.calls) == 1
    assert notify.calls[0].amount == Decimal("600.00")
    assert notify.card_block_calls == []
    target, candidates = reconciler.calls[0]
    assert isinstance(target, ReconcileRecord)
    assert candidates == ()
    assert reconciler.keyword_calls == []

    dispatcher = FakeDispatcher()
    notify_via_dispatcher = FakeFraudNotifyFn()
    await dispatcher.fire_b4c(
        _fraud_rule(),
        event,
        FakeReconciler(MatchOutcome.NONE, matched_id=None),
        notify_via_dispatcher,
    )
    await dispatcher.fire_b4c(
        _fraud_rule(),
        event,
        FakeReconciler(MatchOutcome.NONE, matched_id=None),
        notify_via_dispatcher,
    )
    assert len(notify_via_dispatcher.calls) == 1


async def test_b4c_below_threshold_skips_without_reconciler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(self_recipes, "get_runtime_config", RuntimeConfig)
    reconciler = FakeReconciler(MatchOutcome.NONE, matched_id=None)
    notify = FakeFraudNotifyFn()

    result = await react_fraud_confirm(
        _txn_event(amount="50.00", receipt=False),
        reconciler=reconciler,
        fraud_notify_fn=notify,
    )

    assert result.status == "below_threshold"
    assert notify.calls == []
    assert reconciler.calls == []


async def test_b4c_threshold_reads_x3_runtime_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        self_recipes,
        "get_runtime_config",
        lambda: RuntimeConfig(reaction=ReactionConfig(fraud_confirm_amount_sgd=100.0)),
    )
    notify = FakeFraudNotifyFn()

    result = await react_fraud_confirm(
        _txn_event(amount="120.00", receipt=False),
        reconciler=FakeReconciler(MatchOutcome.NONE, matched_id=None),
        fraud_notify_fn=notify,
    )

    assert result.status == "fraud_signal"
    assert len(notify.calls) == 1


@pytest.mark.parametrize("outcome", [MatchOutcome.EXACT, MatchOutcome.AMBIGUOUS])
async def test_b4c_receipt_matched_clears_prior_signal(
    monkeypatch: pytest.MonkeyPatch,
    outcome: MatchOutcome,
) -> None:
    monkeypatch.setattr(self_recipes, "get_runtime_config", RuntimeConfig)
    notify = FakeFraudNotifyFn()
    event = _txn_event(amount="700.00", receipt=False, receipt_id="receipt-1")

    result = await react_fraud_confirm(
        event,
        reconciler=FakeReconciler(outcome, matched_id="receipt-1"),
        fraud_notify_fn=notify,
    )

    assert result.status == "receipt_matched"
    assert result.ref == "txn-1"
    assert notify.calls == []


async def test_lifecycle_completes_linked_task() -> None:
    complete = FakeCompleteTaskFn()

    result = await react_bill_paid_lifecycle(_bill_paid_event(), complete_task_fn=complete)

    assert result.status == "task_completed"
    assert result.ref == "task-1"
    assert complete.calls == ["task-1"]


async def test_a1_emitted_bill_paid_completes_linked_task_end_to_end() -> None:
    complete = FakeCompleteTaskFn()
    emit = EmitSpy()

    result = await react_statement_to_settlement(
        _payment_event(txn_type="settlement"),
        mark_bill_paid_fn=FakeMarkBillPaidFn(),
        get_linked_task_ref_fn=FakeGetLinkedTaskRefFn("tasks:task:task-bill-1"),
        emit=emit,
    )
    lifecycle = await react_bill_paid_lifecycle(emit.events[0], complete_task_fn=complete)

    assert result.status == "settled"
    assert emit.events[0].payload["linked_task_ref"] == "tasks:task:task-bill-1"
    assert lifecycle.status == "task_completed"
    assert complete.calls == ["task-bill-1"]


async def test_a9_emitted_bill_paid_completes_linked_task_end_to_end() -> None:
    complete = FakeCompleteTaskFn()
    emit = EmitSpy()

    result = await react_payment_reconcile(
        _payment_event(txn_type="payment"),
        reconciler=FakeReconciler(MatchOutcome.EXACT),
        mark_bill_paid_fn=FakeMarkBillPaidFn(),
        get_linked_task_ref_fn=FakeGetLinkedTaskRefFn("tasks:task:task-bill-1"),
        complete_task_fn=complete,
        emit=emit,
    )
    lifecycle = await react_bill_paid_lifecycle(emit.events[0], complete_task_fn=complete)

    assert result.status == "reconciled"
    assert emit.events[0].payload["linked_task_ref"] == "tasks:task:task-bill-1"
    assert lifecycle.status == "task_completed"
    assert complete.calls == ["task-1", "task-bill-1"]


async def test_no_ref_bill_paid_payload_skips_lifecycle_without_completion() -> None:
    complete = FakeCompleteTaskFn()
    emit = EmitSpy()

    result = await react_statement_to_settlement(
        _payment_event(txn_type="settlement"),
        mark_bill_paid_fn=FakeMarkBillPaidFn(),
        get_linked_task_ref_fn=FakeGetLinkedTaskRefFn(None),
        emit=emit,
    )
    lifecycle = await react_bill_paid_lifecycle(emit.events[0], complete_task_fn=complete)

    assert result.status == "settled"
    assert "linked_task_ref" not in emit.events[0].payload
    assert lifecycle.status == "skipped"
    assert complete.calls == []


async def test_register_self_reactions_rules_registry_and_tool_wrappers() -> None:
    registry = ToolRegistry(FakeEmbedder())
    capture = FakeCaptureService()
    mark_paid = FakeMarkBillPaidFn()
    complete = FakeCompleteTaskFn()
    reconciler = FakeReconciler(MatchOutcome.EXACT)
    notify = FakeFraudNotifyFn()
    emit = EmitSpy()

    rules = register_self_reactions(
        registry,
        capture_service=capture,
        mark_bill_paid_fn=mark_paid,
        get_linked_task_ref_fn=FakeGetLinkedTaskRefFn(),
        complete_task_fn=complete,
        reconciler=reconciler,
        fraud_notify_fn=notify,
        emit=emit,
    )

    assert len(rules) == 5
    by_name = {rule.name: rule for rule in rules}
    for name in ("cc_settlement_marker", "bill_to_task", "payment_bill_link"):
        assert by_name[name] == _builtin(name)
        assert by_name[name].tier is ReactionTier.A
        assert isinstance(by_name[name].reaction_ref, str)

    assert by_name["reaction:bill_lifecycle"].tier is ReactionTier.A
    assert by_name["reaction:fraud_confirm"].tier is ReactionTier.B
    assert by_name["reaction:fraud_confirm"].stateful is True

    for rule in rules:
        assert isinstance(rule.reaction_ref, str)
        assert not hasattr(rule, "idempotency_key_fn")
        assert registry.get_tool(rule.reaction_ref).callable_ref is not None

    task_result = cast(
        ReactionResult,
        await registry.get_tool("tasks.create_from_bill").callable_ref(
            ReactionArgs(
                event_type=EventType.BILL_RECORDED.value,
                source_module="finance",
                occurred_at="2026-06-25T00:00:00+00:00",
                dedup_key="bill-recorded:bill-1",
                bill_id="bill-1",
                payee="Utility Co",
                due_date="2026-07-01",
                amount="100.00",
            )
        ),
    )
    assert task_result.status == "task_created"
    assert capture.calls[0]["source"] == "finance:bill:bill-1"


def test_import_reexport() -> None:
    from artemis.reactions.recipes import register_self_reactions as imported

    assert imported is register_self_reactions


def test_bill_paid_event_builder_shape() -> None:
    event = bill_paid_event(bill_id="bill-1", payee="Utility Co")
    linked = bill_paid_event(
        bill_id="bill-1",
        payee="Utility Co",
        linked_task_ref="tasks:task:task-1",
    )

    assert event.event_type is EventType.BILL_PAID
    assert event.source_module == "finance"
    assert event.payload == {"bill_id": "bill-1", "payee": "Utility Co"}
    assert event.dedup_key == "bill-paid:bill-1"
    assert linked.payload == {
        "bill_id": "bill-1",
        "payee": "Utility Co",
        "linked_task_ref": "tasks:task:task-1",
    }


def test_no_cloud_import_guard_and_adr_011_tool_injection() -> None:
    source = inspect.getsource(self_recipes)

    assert "ModelPort" not in source
    assert "model_adapters" not in source
    assert "OpenAI" not in source
    assert "FinanceStore" not in source
    assert "repository" not in source
    assert "store." not in source


def _payment_event(*, txn_type: str) -> DomainEvent:
    return DomainEvent(
        event_type=EventType.PAYMENT_RECORDED,
        source_module="finance",
        entity_refs=(EntityRef(module="finance", entity_id="txn-1"),),
        payload={
            "txn_id": "txn-1",
            "txn_type": txn_type,
            "bill_id": "bill-1",
            "amount": "100.00",
            "bill_amount": "100.00",
            "currency": "SGD",
            "date": "2026-06-25",
            "bill_due_date": "2026-06-25",
            "payee": "Utility Co",
            "linked_task_ref": "tasks:task:task-1",
            "settles_period": "2026-06",
        },
        occurred_at="2026-06-25T00:00:00+00:00",
        dedup_key="payment-recorded:txn-1",
    )


def _bill_event() -> DomainEvent:
    return DomainEvent(
        event_type=EventType.BILL_RECORDED,
        source_module="finance",
        entity_refs=(EntityRef(module="finance", entity_id="bill-1"),),
        payload={
            "bill_id": "bill-1",
            "payee": "Utility Co",
            "due_date": "2026-07-01",
            "amount": "100.00",
        },
        occurred_at="2026-06-25T00:00:00+00:00",
        dedup_key="bill-recorded:bill-1",
    )


def _txn_event(*, amount: str, receipt: bool, receipt_id: str | None = None) -> DomainEvent:
    payload: dict[str, str | int | float | bool] = {
        "txn_id": "txn-1",
        "txn_type": "purchase",
        "amount": amount,
        "currency": "SGD",
        "date": "2026-06-25",
        "merchant": "Electronics Shop",
        "has_receipt": receipt,
    }
    if receipt_id is not None:
        payload.update(
            {
                "receipt_id": receipt_id,
                "receipt_amount": amount,
                "receipt_date": "2026-06-25",
                "receipt_merchant": "Electronics Shop",
            }
        )
    return DomainEvent(
        event_type=EventType.TXN_RECORDED,
        source_module="finance",
        entity_refs=(EntityRef(module="finance", entity_id="txn-1"),),
        payload=payload,
        occurred_at="2026-06-25T00:00:00+00:00",
        dedup_key="txn-recorded:txn-1",
    )


def _bill_paid_event() -> DomainEvent:
    return DomainEvent(
        event_type=EventType.BILL_PAID,
        source_module="finance",
        entity_refs=(EntityRef(module="finance", entity_id="bill-1"),),
        payload={
            "bill_id": "bill-1",
            "payee": "Utility Co",
            "linked_task_ref": "tasks:task:task-1",
        },
        occurred_at="2026-06-25T00:00:00+00:00",
        dedup_key="bill-paid:bill-1",
    )


def _builtin(name: str) -> ReactionRule:
    for rule in TIER_A_BUILTINS:
        if rule.name == name:
            return rule
    raise AssertionError(name)


def _fraud_rule() -> ReactionRule:
    return ReactionRule(
        name="reaction:fraud_confirm",
        event_type=EventType.TXN_RECORDED,
        tier=ReactionTier.B,
        external_effect=False,
        reaction_ref="reaction:fraud_confirm",
        dedup_key_fields=("txn_id",),
        stateful=True,
    )


def _stable_key(rule: ReactionRule, event: DomainEvent) -> str:
    parts = [rule.name]
    for field in rule.dedup_key_fields:
        value = event.dedup_key if field == "dedup_key" else event.payload.get(field)
        parts.append(str(value or ""))
    parts.append(event.dedup_key)
    return ":".join(parts)
