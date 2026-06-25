"""Finance domain-event builders consumed by the reaction layer.

The finance package owns construction of its events but not dispatch. Callers
inject a synchronous ``Callable[[DomainEvent], None]``; the default no-op keeps
the recurring/reconciliation layer buildable without the reaction dispatcher.
"""

from __future__ import annotations

from collections.abc import Callable

from artemis.memory.schema import now_iso
from artemis.reactions import DomainEvent, EventType

FINANCE_EVENT_TYPES = (
    EventType.TXN_RECORDED,
    EventType.BILL_RECORDED,
    EventType.SUBSCRIPTION_DETECTED,
)

Emit = Callable[[DomainEvent], None]


def _noop_emit(_event: DomainEvent) -> None:
    """Default event sink used when no reaction bus is composed."""


def txn_recorded_event(
    *,
    txn_id: str,
    txn_type: str,
    amount: str,
    instrument_account_id: str | None,
) -> DomainEvent:
    """Build the FIN-b transaction-recorded event without dispatching it."""
    return DomainEvent(
        event_type=EventType.TXN_RECORDED,
        source_module="finance",
        payload={
            "txn_id": txn_id,
            "txn_type": txn_type,
            "amount": amount,
            "instrument_account_id": instrument_account_id or "",
        },
        occurred_at=now_iso(),
        dedup_key=f"txn-recorded:{txn_id}",
    )


def bill_recorded_event(
    *,
    bill_id: str,
    payee: str,
    due_date: str,
    amount: str | None,
) -> DomainEvent:
    """Build the bill-recorded event with scalar payload values only."""
    return DomainEvent(
        event_type=EventType.BILL_RECORDED,
        source_module="finance",
        payload={
            "bill_id": bill_id,
            "payee": payee,
            "due_date": due_date,
            "amount": amount or "",
        },
        occurred_at=now_iso(),
        dedup_key=f"bill-recorded:{bill_id}",
    )


def subscription_detected_event(*, subscription_id: str, merchant: str) -> DomainEvent:
    """Build the event fired when a recurring pattern hardens."""
    return DomainEvent(
        event_type=EventType.SUBSCRIPTION_DETECTED,
        source_module="finance",
        payload={"subscription_id": subscription_id, "merchant": merchant},
        occurred_at=now_iso(),
        dedup_key=f"subscription-detected:{subscription_id}",
    )
