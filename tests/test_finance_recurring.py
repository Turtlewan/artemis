from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from artemis.config import Settings
from artemis.identity.key_provider import ScopeLockedError, SecretKey
from artemis.identity.scope import OWNER_PRIVATE
from artemis.modules.finance.events import (
    _noop_emit,
    bill_recorded_event,
    subscription_detected_event,
    txn_recorded_event,
)
from artemis.modules.finance.recurring import detect_recurring, infer_cadence
from artemis.modules.finance.store import FinanceStore
from artemis.ports.types import Scope
from artemis.reactions import DomainEvent, EventType


class FakeKeyProvider:
    def __init__(self, *, owner_unlocked: bool = True) -> None:
        self.owner_unlocked = owner_unlocked

    def dek_for_scope(self, scope: Scope) -> SecretKey:
        if scope != OWNER_PRIVATE or not self.owner_unlocked:
            raise ScopeLockedError(f"Scope is locked: {scope}")
        return SecretKey(b"f" * 32)

    def is_owner_unlocked(self) -> bool:
        return self.owner_unlocked


@pytest.fixture
def store(tmp_path: Path) -> FinanceStore:
    return FinanceStore(Settings(data_root=tmp_path), FakeKeyProvider())


def test_two_occurrences_create_inert_suggestion(store: FinanceStore) -> None:
    account_id = store.create_account("Card", "card")
    store.add_transaction(
        txn_date="2026-01-01",
        amount=Decimal("19.99"),
        merchant="Netflix",
        source="manual",
        instrument_account_id=account_id,
        raw_ref="netflix:jan",
    )
    store.add_transaction(
        txn_date="2026-01-31",
        amount=Decimal("19.99"),
        merchant="Netflix",
        source="manual",
        instrument_account_id=account_id,
        raw_ref="netflix:feb",
    )

    results = detect_recurring(store, min_occurrences=2)

    assert [row["kind"] for row in results] == ["new_recurring"]
    assert store.list_subscriptions() == []
    suggestions = store.list_fin_suggestions(status="pending")
    assert len(suggestions) == 1
    assert suggestions[0]["kind"] == "new_recurring"
    assert len(store.list_transactions()) == 2


def test_third_occurrence_hardens_subscription_and_emits(store: FinanceStore) -> None:
    account_id = store.create_account("Card", "card")
    for raw_ref, txn_date in (
        ("music:1", "2026-01-01"),
        ("music:2", "2026-01-31"),
        ("music:3", "2026-03-02"),
    ):
        store.add_transaction(
            txn_date=txn_date,
            amount=Decimal("12.00"),
            merchant="Music Box",
            source="manual",
            instrument_account_id=account_id,
            raw_ref=raw_ref,
        )
    seen: list[DomainEvent] = []

    results = detect_recurring(store, min_occurrences=2, emit=seen.append)

    assert [row["kind"] for row in results] == ["subscription"]
    subscriptions = store.list_subscriptions()
    assert len(subscriptions) == 1
    assert subscriptions[0]["cadence"] == "monthly"
    assert seen[0].event_type is EventType.SUBSCRIPTION_DETECTED
    assert seen[0].payload["subscription_id"] == subscriptions[0]["id"]


def test_bill_upsert_emits_bill_recorded(store: FinanceStore) -> None:
    account_id = store.create_account("Card", "card")
    for raw_ref, txn_date in (
        ("bill:1", "2026-01-05"),
        ("bill:2", "2026-02-04"),
        ("bill:3", "2026-03-06"),
    ):
        store.add_transaction(
            txn_date=txn_date,
            amount=Decimal("88.00"),
            merchant="Power Utility",
            source="email",
            instrument_account_id=account_id,
            raw_ref=raw_ref,
            confidence=0.95,
            notes="statement due:2026-03-20",
        )
    seen: list[DomainEvent] = []

    detect_recurring(store, min_occurrences=2, emit=seen.append)

    bills = store.list_bills(status="open")
    assert len(bills) == 1
    assert bills[0]["due_date"] == "2026-03-20"
    assert EventType.BILL_RECORDED in {event.event_type for event in seen}


def test_event_builders_are_scalar_frozen_and_noop_safe() -> None:
    txn = txn_recorded_event(
        txn_id="txn1",
        txn_type="purchase",
        amount="10.00",
        instrument_account_id=None,
    )
    bill = bill_recorded_event(bill_id="bill1", payee="SP", due_date="2026-06-30", amount=None)
    sub = subscription_detected_event(subscription_id="sub1", merchant="Music")

    assert txn.event_type is EventType.TXN_RECORDED
    assert txn.payload["instrument_account_id"] == ""
    assert bill.event_type is EventType.BILL_RECORDED
    assert bill.payload["amount"] == ""
    assert sub.event_type is EventType.SUBSCRIPTION_DETECTED
    assert sub.dedup_key == "subscription-detected:sub1"
    for event in (txn, bill, sub):
        assert all(isinstance(value, (str, int, float, bool)) for value in event.payload.values())
        with pytest.raises(Exception):
            event.dedup_key = "changed"  # type: ignore[misc]
        _noop_emit(event)


def test_cadence_inference() -> None:
    assert infer_cadence(["2026-01-01", "2026-01-08", "2026-01-15"]) == "weekly"
    assert infer_cadence(["2026-01-01", "2026-01-31", "2026-03-02"]) == "monthly"
    assert infer_cadence(["2025-01-01", "2026-01-01", "2027-01-01"]) == "yearly"
    assert infer_cadence(["2026-01-01", "2026-01-13"]) is None
