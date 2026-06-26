"""Self/Finance reaction recipes.

A1/A6/A9 and the bill lifecycle are Tier-A local ledger/task edits delegated to
FIN-c and CaptureService tool handles. B4c is Tier-B and notification-only:
Artemis never moves money, blocks cards, calls a model, or opens a finance store
from this module. Matching stays behind the shared precision-first reconciler;
``AMBIGUOUS`` results are inert suggestions, never auto-paid bills.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from functools import partial
from typing import Protocol, cast

from pydantic import BaseModel, ConfigDict, Field

from artemis.manifest import ActionRisk, DataScope, ModuleManifest, Permissions, ToolSpec, UiSurface
from artemis.memory import EntityRef
from artemis.reactions.emit import DomainEvent, EventType
from artemis.reactions.reconciler import MatchOutcome, ReconcileRecord
from artemis.reactions.rulestore import TIER_A_BUILTINS, ReactionRule, ReactionTier
from artemis.registry import ToolRegistry
from artemis.runtime_config import get_runtime_config

_A1_MARK_SETTLEMENT_REF = "finance.mark_settlement"
_A6_CREATE_FROM_BILL_REF = "tasks.create_from_bill"
_A9_LINK_PAYMENT_BILL_REF = "finance.link_payment_bill"
_B4C_FRAUD_CONFIRM_REF = "reaction:fraud_confirm"
_BILL_LIFECYCLE_REF = "reaction:bill_lifecycle"


class ReactionResult(BaseModel):
    """Result returned by internal reaction recipes."""

    model_config = ConfigDict(frozen=True)

    status: str
    ref: str | None = None
    undoable: bool


class ReactionArgs(BaseModel):
    """Dispatcher-provided scalar event args for self/finance recipe wrappers."""

    model_config = ConfigDict(extra="allow")

    event_type: str
    source_module: str
    occurred_at: str
    dedup_key: str
    entity_refs: list[dict[str, str]] = Field(default_factory=list)


class BillTaskResult(BaseModel):
    """CaptureService result for the A6 pay-bill task creation seam."""

    model_config = ConfigDict(frozen=True)

    task_id: str
    linked_task_ref: str | None = None
    due_at: str | None = None
    source: str | None = None


class FraudSignal(BaseModel):
    """Notification payload for B4c; it is inert and has no external action."""

    model_config = ConfigDict(frozen=True)

    txn_id: str
    amount: Decimal
    currency: str
    merchant: str


class CaptureServiceLike(Protocol):
    """CaptureService surface used by A6."""

    async def create_task_from_bill(
        self,
        *,
        bill_id: str,
        title: str,
        due_at: str,
        source: str,
    ) -> BillTaskResult:
        """Create or return the idempotent pay-bill task for a confirmed bill."""
        ...


class ReconcilerLike(Protocol):
    """Shared reconciler surface used by A9 and B4c."""

    def match(
        self,
        target: ReconcileRecord,
        candidates: Sequence[ReconcileRecord],
    ) -> object:
        """Return the canonical MatchResult shape."""
        ...


MarkBillPaidFn = Callable[[str], Awaitable[object]]
GetLinkedTaskRefFn = Callable[[str], Awaitable[str | None]]
CompleteTaskFn = Callable[[str], Awaitable[object]]
FraudNotifyFn = Callable[[FraudSignal], Awaitable[object]]
EmitFn = Callable[[DomainEvent], None]


async def react_statement_to_settlement(
    event: DomainEvent,
    *,
    mark_bill_paid_fn: MarkBillPaidFn,
    get_linked_task_ref_fn: GetLinkedTaskRefFn,
    emit: EmitFn,
) -> ReactionResult:
    """A1 Tier-A extended: settlement payment marks its statement bill paid.

    Idempotency key: ``txn_id`` via the canonical ``cc_settlement_marker`` rule.
    This only delegates to FIN-c ``mark_bill_paid_fn`` and emits ``BILL_PAID``;
    spend totals are not touched here.
    """
    if event.event_type is not EventType.PAYMENT_RECORDED or _payload_str(event, "txn_type") != (
        "settlement"
    ):
        return ReactionResult(status="skipped", ref=None, undoable=False)
    bill_id = _payload_str(event, "bill_id") or _payload_str(event, "statement_bill_id")
    if bill_id is None:
        return ReactionResult(status="skipped", ref=None, undoable=False)

    mark_result = await mark_bill_paid_fn(bill_id)
    if not _tool_changed(mark_result):
        return ReactionResult(status="settled", ref=bill_id, undoable=True)
    linked_task_ref = await get_linked_task_ref_fn(bill_id)
    emit(bill_paid_event(bill_id=bill_id, payee=_payee(event), linked_task_ref=linked_task_ref))
    return ReactionResult(status="settled", ref=bill_id, undoable=True)


async def react_bill_to_task(
    event: DomainEvent,
    *,
    capture_service: CaptureServiceLike,
) -> ReactionResult:
    """A6 Tier-A built-in: confirmed bill -> dated pay-bill task.

    Idempotency key: ``bill_id`` via ``bill_to_task``. The dated task emits the
    normal task-created event upstream; C1 owns the Calendar marker.
    """
    if event.event_type is not EventType.BILL_RECORDED:
        return ReactionResult(status="skipped", ref=None, undoable=False)
    bill_id = _payload_str(event, "bill_id")
    payee = _payload_str(event, "payee")
    due_date = _payload_str(event, "due_date")
    if bill_id is None or payee is None or due_date is None:
        return ReactionResult(status="skipped", ref=None, undoable=False)

    result = await capture_service.create_task_from_bill(
        bill_id=bill_id,
        title=f"Pay {payee} by {due_date}",
        due_at=due_date,
        source=f"finance:bill:{bill_id}",
    )
    return ReactionResult(status="task_created", ref=result.task_id, undoable=True)


async def react_payment_reconcile(
    event: DomainEvent,
    *,
    reconciler: ReconcilerLike,
    mark_bill_paid_fn: MarkBillPaidFn,
    get_linked_task_ref_fn: GetLinkedTaskRefFn,
    complete_task_fn: CompleteTaskFn,
    emit: EmitFn,
) -> ReactionResult:
    """A9 Tier-A after precision-first exact payment->bill reconciliation."""
    if event.event_type is not EventType.PAYMENT_RECORDED:
        return ReactionResult(status="skipped", ref=None, undoable=False)
    target = _target_record(event)
    candidates = _candidate_records_from_event(event)
    if target is None or not candidates:
        return ReactionResult(status="unmatched", ref=None, undoable=False)

    match = reconciler.match(target, candidates)
    outcome = _match_outcome(match)
    if outcome is MatchOutcome.AMBIGUOUS:
        return ReactionResult(status="ambiguous", ref=None, undoable=False)
    if outcome is not MatchOutcome.EXACT:
        return ReactionResult(status="unmatched", ref=None, undoable=False)

    bill_id = _match_id(match)
    if bill_id is None:
        return ReactionResult(status="unmatched", ref=None, undoable=False)
    mark_result = await mark_bill_paid_fn(bill_id)
    if not _tool_changed(mark_result):
        return ReactionResult(status="reconciled", ref=bill_id, undoable=True)
    task_ref = _payload_str(event, "linked_task_ref")
    if task_ref is not None:
        await complete_task_fn(_task_id_from_ref(task_ref))
    linked_task_ref = await get_linked_task_ref_fn(bill_id)
    emit(bill_paid_event(bill_id=bill_id, payee=_payee(event), linked_task_ref=linked_task_ref))
    return ReactionResult(status="reconciled", ref=bill_id, undoable=True)


async def react_fraud_confirm(
    event: DomainEvent,
    *,
    reconciler: ReconcilerLike,
    fraud_notify_fn: FraudNotifyFn,
) -> ReactionResult:
    """B4c Tier-B: high-value purchase without receipt -> inert confirm notice.

    Idempotency key: ``txn_id``. Threshold/window are X3 runtime tunables; the
    injected reconciler is composed with the same fraud window because ``match``
    accepts no per-call tolerance. ``EXACT`` and ``AMBIGUOUS`` mean a receipt is
    accounted for, so any previous stateful signal can be cleared by the caller.
    """
    if event.event_type is not EventType.TXN_RECORDED or _payload_str(event, "txn_type") != (
        "purchase"
    ):
        return ReactionResult(status="skipped", ref=None, undoable=False)
    if event.payload.get("has_receipt") is True:
        return ReactionResult(status="receipt_matched", ref=None, undoable=False)
    target = _target_record(event)
    if target is None:
        return ReactionResult(status="skipped", ref=None, undoable=False)

    cfg = get_runtime_config().reaction
    if target.amount < Decimal(str(cfg.fraud_confirm_amount_sgd)):
        return ReactionResult(status="below_threshold", ref=None, undoable=False)

    result = reconciler.match(target, _receipt_records_from_event(event))
    if _match_outcome(result) is not MatchOutcome.NONE:
        return ReactionResult(status="receipt_matched", ref=target.id, undoable=False)

    await fraud_notify_fn(
        FraudSignal(
            txn_id=target.id,
            amount=target.amount,
            currency=target.currency,
            merchant=target.merchant,
        )
    )
    return ReactionResult(status="fraud_signal", ref=target.id, undoable=False)


async def react_bill_paid_lifecycle(
    event: DomainEvent,
    *,
    complete_task_fn: CompleteTaskFn,
) -> ReactionResult:
    """Tier-A bill-paid lifecycle: close the linked pay-bill task if present."""
    if event.event_type is not EventType.BILL_PAID:
        return ReactionResult(status="skipped", ref=None, undoable=False)
    task_ref = _payload_str(event, "linked_task_ref")
    if task_ref is None:
        return ReactionResult(status="skipped", ref=None, undoable=False)
    task_id = _task_id_from_ref(task_ref)
    await complete_task_fn(task_id)
    return ReactionResult(status="task_completed", ref=task_id, undoable=True)


def bill_paid_event(*, bill_id: str, payee: str, linked_task_ref: str | None = None) -> DomainEvent:
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


async def _no_linked_task_ref(bill_id: str) -> str | None:
    del bill_id
    return None


def register_self_reactions(
    registry: ToolRegistry,
    *,
    capture_service: CaptureServiceLike,
    mark_bill_paid_fn: MarkBillPaidFn,
    get_linked_task_ref_fn: GetLinkedTaskRefFn = _no_linked_task_ref,
    complete_task_fn: CompleteTaskFn,
    reconciler: ReconcilerLike,
    fraud_notify_fn: FraudNotifyFn,
    emit: EmitFn,
) -> tuple[ReactionRule, ...]:
    """Register Self/Finance reaction tools and return rule bindings.

    Event map and idempotency keys:
    payment-recorded/txn_id -> A1 ``finance.mark_settlement``;
    bill-recorded/bill_id -> A6 ``tasks.create_from_bill``;
    payment-recorded/txn_id+bill_id -> A9 ``finance.link_payment_bill``;
    txn-recorded/txn_id -> B4c ``reaction:fraud_confirm``; bill-paid/bill_id
    -> ``reaction:bill_lifecycle``. All callables are always-local and
    notification-only where owner judgment is required.
    """
    settlement_callable = cast(
        Callable[[ReactionArgs], Awaitable[ReactionResult]],
        partial(
            _statement_to_settlement_tool,
            mark_bill_paid_fn=mark_bill_paid_fn,
            get_linked_task_ref_fn=get_linked_task_ref_fn,
            emit=emit,
        ),
    )
    bill_task_callable = cast(
        Callable[[ReactionArgs], Awaitable[ReactionResult]],
        partial(_bill_to_task_tool, capture_service=capture_service),
    )
    payment_callable = cast(
        Callable[[ReactionArgs], Awaitable[ReactionResult]],
        partial(
            _payment_reconcile_tool,
            reconciler=reconciler,
            mark_bill_paid_fn=mark_bill_paid_fn,
            get_linked_task_ref_fn=get_linked_task_ref_fn,
            complete_task_fn=complete_task_fn,
            emit=emit,
        ),
    )
    fraud_callable = cast(
        Callable[[ReactionArgs], Awaitable[ReactionResult]],
        partial(_fraud_confirm_tool, reconciler=reconciler, fraud_notify_fn=fraud_notify_fn),
    )
    lifecycle_callable = cast(
        Callable[[ReactionArgs], Awaitable[ReactionResult]],
        partial(_bill_paid_lifecycle_tool, complete_task_fn=complete_task_fn),
    )

    _register_tool(
        registry,
        _A1_MARK_SETTLEMENT_REF,
        "Self A1 settlement payment to bill-paid lifecycle marker.",
        settlement_callable,
    )
    _register_tool(
        registry,
        _A6_CREATE_FROM_BILL_REF,
        "Self A6 confirmed bill to dated pay-bill task.",
        bill_task_callable,
    )
    _register_tool(
        registry,
        _A9_LINK_PAYMENT_BILL_REF,
        "Self A9 payment to exact bill match and linked task completion.",
        payment_callable,
    )
    _register_tool(
        registry,
        _B4C_FRAUD_CONFIRM_REF,
        "Self B4c high-value no-receipt charge to inert fraud confirmation.",
        fraud_callable,
    )
    _register_tool(
        registry,
        _BILL_LIFECYCLE_REF,
        "Self bill-paid lifecycle linked-task completion.",
        lifecycle_callable,
    )

    return (
        _builtin("cc_settlement_marker"),
        _builtin("bill_to_task"),
        _builtin("payment_bill_link"),
        ReactionRule(
            name=_B4C_FRAUD_CONFIRM_REF,
            event_type=EventType.TXN_RECORDED,
            tier=ReactionTier.B,
            external_effect=False,
            reaction_ref=_B4C_FRAUD_CONFIRM_REF,
            dedup_key_fields=("txn_id",),
            stateful=True,
        ),
        ReactionRule(
            name=_BILL_LIFECYCLE_REF,
            event_type=EventType.BILL_PAID,
            tier=ReactionTier.A,
            external_effect=False,
            reaction_ref=_BILL_LIFECYCLE_REF,
            dedup_key_fields=("bill_id",),
        ),
    )


async def _statement_to_settlement_tool(
    args: ReactionArgs,
    *,
    mark_bill_paid_fn: MarkBillPaidFn,
    get_linked_task_ref_fn: GetLinkedTaskRefFn,
    emit: EmitFn,
) -> ReactionResult:
    return await react_statement_to_settlement(
        _event_from_args(args),
        mark_bill_paid_fn=mark_bill_paid_fn,
        get_linked_task_ref_fn=get_linked_task_ref_fn,
        emit=emit,
    )


async def _bill_to_task_tool(
    args: ReactionArgs,
    *,
    capture_service: CaptureServiceLike,
) -> ReactionResult:
    return await react_bill_to_task(_event_from_args(args), capture_service=capture_service)


async def _payment_reconcile_tool(
    args: ReactionArgs,
    *,
    reconciler: ReconcilerLike,
    mark_bill_paid_fn: MarkBillPaidFn,
    get_linked_task_ref_fn: GetLinkedTaskRefFn,
    complete_task_fn: CompleteTaskFn,
    emit: EmitFn,
) -> ReactionResult:
    return await react_payment_reconcile(
        _event_from_args(args),
        reconciler=reconciler,
        mark_bill_paid_fn=mark_bill_paid_fn,
        get_linked_task_ref_fn=get_linked_task_ref_fn,
        complete_task_fn=complete_task_fn,
        emit=emit,
    )


async def _fraud_confirm_tool(
    args: ReactionArgs,
    *,
    reconciler: ReconcilerLike,
    fraud_notify_fn: FraudNotifyFn,
) -> ReactionResult:
    return await react_fraud_confirm(
        _event_from_args(args),
        reconciler=reconciler,
        fraud_notify_fn=fraud_notify_fn,
    )


async def _bill_paid_lifecycle_tool(
    args: ReactionArgs,
    *,
    complete_task_fn: CompleteTaskFn,
) -> ReactionResult:
    return await react_bill_paid_lifecycle(
        _event_from_args(args),
        complete_task_fn=complete_task_fn,
    )


def _register_tool(
    registry: ToolRegistry,
    fq_ref: str,
    description: str,
    callable_ref: Callable[[ReactionArgs], Awaitable[ReactionResult]],
) -> None:
    module_name, tool_name = _split_ref(fq_ref)
    tool = ToolSpec(
        name=tool_name,
        description=description,
        args_schema=ReactionArgs,
        return_schema=ReactionResult,
        callable_ref=callable_ref,
        action_risk=ActionRisk.WRITE,
    )
    registry._tools[fq_ref] = tool
    registry._pending.append((fq_ref, tool))
    if module_name not in registry._manifests and ":" not in module_name:
        registry._manifests[module_name] = ModuleManifest(
            name=module_name,
            version="0.1.0",
            description=f"Reaction recipe tools for {module_name}.",
            tools=[],
            data_scope=DataScope.OWNER_PRIVATE,
            permissions=Permissions(owner=True, guest=False),
            proactive_hooks=[],
            ui=UiSurface(kind="none"),
        )


def _split_ref(fq_ref: str) -> tuple[str, str]:
    if ":" in fq_ref and "." not in fq_ref:
        module, tool = fq_ref.split(":", 1)
        return module, tool
    module, tool = fq_ref.split(".", 1)
    return module, tool


def _builtin(name: str) -> ReactionRule:
    for rule in TIER_A_BUILTINS:
        if rule.name == name:
            return rule
    raise KeyError(name)


def _event_from_args(args: ReactionArgs) -> DomainEvent:
    dumped = args.model_dump()
    payload = {
        key: value
        for key, value in dumped.items()
        if key
        not in {
            "event_type",
            "source_module",
            "occurred_at",
            "dedup_key",
            "entity_refs",
        }
        and isinstance(value, (str, int, float, bool))
    }
    refs = tuple(
        EntityRef(module=ref["module"], entity_id=ref["entity_id"])
        for ref in args.entity_refs
        if "module" in ref and "entity_id" in ref
    )
    return DomainEvent(
        event_type=EventType(args.event_type),
        source_module=args.source_module,
        entity_refs=refs,
        payload=payload,
        occurred_at=args.occurred_at,
        dedup_key=args.dedup_key,
    )


def _target_record(event: DomainEvent) -> ReconcileRecord | None:
    txn_id = _payload_str(event, "txn_id")
    amount = _payload_decimal(event, "amount")
    date = _payload_str(event, "date") or _payload_str(event, "posted_at") or event.occurred_at
    merchant = _payload_str(event, "merchant") or _payee(event)
    currency = _payload_str(event, "currency") or "SGD"
    if txn_id is None or amount is None:
        return None
    return ReconcileRecord(
        id=txn_id,
        amount=amount,
        currency=currency,
        date=date,
        merchant=merchant,
    )


def _candidate_records_from_event(event: DomainEvent) -> tuple[ReconcileRecord, ...]:
    bill_id = _payload_str(event, "bill_id")
    if bill_id is None:
        return ()
    amount = _payload_decimal(event, "bill_amount") or _payload_decimal(event, "amount")
    date = _payload_str(event, "bill_due_date") or _payload_str(event, "due_date")
    merchant = _payload_str(event, "bill_payee") or _payee(event)
    currency = _payload_str(event, "bill_currency") or _payload_str(event, "currency") or "SGD"
    if amount is None or date is None:
        return ()
    return (
        ReconcileRecord(
            id=bill_id,
            amount=amount,
            currency=currency,
            date=date,
            merchant=merchant,
        ),
    )


def _receipt_records_from_event(event: DomainEvent) -> tuple[ReconcileRecord, ...]:
    receipt_id = _payload_str(event, "receipt_id")
    if receipt_id is None:
        return ()
    amount = _payload_decimal(event, "receipt_amount") or _payload_decimal(event, "amount")
    date = _payload_str(event, "receipt_date") or _payload_str(event, "date")
    merchant = _payload_str(event, "receipt_merchant") or _payee(event)
    currency = _payload_str(event, "receipt_currency") or _payload_str(event, "currency") or "SGD"
    if amount is None or date is None:
        return ()
    return (
        ReconcileRecord(
            id=receipt_id,
            amount=amount,
            currency=currency,
            date=date,
            merchant=merchant,
        ),
    )


def _match_outcome(result: object) -> MatchOutcome:
    raw = getattr(result, "outcome", MatchOutcome.NONE)
    return raw if isinstance(raw, MatchOutcome) else MatchOutcome(str(raw))


def _match_id(result: object) -> str | None:
    raw = getattr(result, "matched_id", None)
    return raw if isinstance(raw, str) and raw else None


def _tool_changed(result: object) -> bool:
    changed = getattr(result, "changed", True)
    return changed if isinstance(changed, bool) else True


def _payload_str(event: DomainEvent, key: str) -> str | None:
    value = event.payload.get(key)
    if isinstance(value, str) and value:
        return value
    return None


def _payload_decimal(event: DomainEvent, key: str) -> Decimal | None:
    value = event.payload.get(key)
    if isinstance(value, str | int | float):
        return Decimal(str(value))
    return None


def _payee(event: DomainEvent) -> str:
    return (
        _payload_str(event, "payee")
        or _payload_str(event, "bill_payee")
        or _payload_str(event, "merchant")
        or "unknown"
    )


def _task_id_from_ref(ref: str) -> str:
    return ref.removeprefix("tasks:task:")
