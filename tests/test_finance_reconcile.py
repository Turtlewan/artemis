from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from artemis.config import Settings
from artemis.identity.key_provider import ScopeLockedError, SecretKey
from artemis.identity.scope import OWNER_PRIVATE
from artemis.modules.finance.reconcile import reconcile, unusual_spend
from artemis.modules.finance.store import FinanceStore
from artemis.ports.types import Scope


class FakeKeyProvider:
    def dek_for_scope(self, scope: Scope) -> SecretKey:
        if scope != OWNER_PRIVATE:
            raise ScopeLockedError(f"Scope is locked: {scope}")
        return SecretKey(b"f" * 32)

    def is_owner_unlocked(self) -> bool:
        return True


@pytest.fixture
def store(tmp_path: Path) -> FinanceStore:
    return FinanceStore(Settings(data_root=tmp_path), FakeKeyProvider())


def test_l1_high_confidence_cross_source_auto_merges(store: FinanceStore) -> None:
    account_id = store.create_account("Card", "card")
    store.add_transaction(
        txn_date="2026-06-01",
        amount=Decimal("25.00"),
        merchant="Coffee Co",
        source="email",
        instrument_account_id=account_id,
        raw_ref="email:coffee",
        confidence=0.95,
    )
    csv_id = store.add_transaction(
        txn_date="2026-06-01",
        amount=Decimal("25.00"),
        merchant="coffee co",
        source="csv",
        instrument_account_id=account_id,
        raw_ref="csv:coffee",
        confidence=0.99,
    )

    result = reconcile(store, date_window_days=1, amount_exact=True)

    assert result == {"auto_merged": 1, "suggested_duplicates": 0, "reconciled": 1}
    transactions = store.list_transactions()
    assert len(transactions) == 1
    assert transactions[0]["id"] == csv_id


def test_l2_email_pending_reconciles_against_csv_posted(store: FinanceStore) -> None:
    account_id = store.create_account("Card", "card")
    store.add_transaction(
        txn_date="2026-06-02",
        amount=Decimal("42.00"),
        merchant="Grocer",
        source="email",
        instrument_account_id=account_id,
        raw_ref="email:grocer",
        confidence=0.92,
    )
    store.add_transaction(
        txn_date="2026-06-03",
        amount=Decimal("42.00"),
        merchant="Grocer",
        source="csv",
        instrument_account_id=account_id,
        raw_ref="csv:grocer",
        confidence=0.99,
    )

    result = reconcile(store, date_window_days=1, amount_exact=True)

    assert result["auto_merged"] == 1
    assert result["reconciled"] == 1
    assert len(store.list_transactions()) == 1


def test_l3_below_bar_creates_inert_suggestion_without_merge(store: FinanceStore) -> None:
    account_id = store.create_account("Card", "card")
    store.add_transaction(
        txn_date="2026-06-04",
        amount=Decimal("10.00"),
        merchant="Bakery",
        source="email",
        instrument_account_id=account_id,
        raw_ref="email:bakery",
        confidence=0.70,
    )
    store.add_transaction(
        txn_date="2026-06-04",
        amount=Decimal("10.05"),
        merchant="Bakery",
        source="manual",
        instrument_account_id=account_id,
        raw_ref="manual:bakery",
        confidence=0.70,
    )

    result = reconcile(store, date_window_days=1, amount_exact=True)

    assert result == {"auto_merged": 0, "suggested_duplicates": 1, "reconciled": 0}
    assert len(store.list_transactions()) == 2
    suggestions = store.list_fin_suggestions(status="pending")
    assert suggestions[0]["kind"] == "possible_duplicate"


def test_unusual_spend_flags_outlier_not_pattern_or_first_seen(store: FinanceStore) -> None:
    account_id = store.create_account("Card", "card")
    for index, amount in enumerate(("10.00", "11.00", "9.00", "10.50"), start=1):
        store.add_transaction(
            txn_date=f"2026-06-0{index}",
            amount=Decimal(amount),
            merchant="Lunch Place",
            source="manual",
            instrument_account_id=account_id,
            raw_ref=f"lunch:{index}",
        )
    normal_id = store.add_transaction(
        txn_date="2026-06-05",
        amount=Decimal("10.75"),
        merchant="Lunch Place",
        source="manual",
        instrument_account_id=account_id,
        raw_ref="lunch:normal",
    )
    outlier_id = store.add_transaction(
        txn_date="2026-06-06",
        amount=Decimal("55.00"),
        merchant="Lunch Place",
        source="manual",
        instrument_account_id=account_id,
        raw_ref="lunch:outlier",
    )
    store.add_transaction(
        txn_date="2026-06-06",
        amount=Decimal("500.00"),
        merchant="First Seen",
        source="manual",
        instrument_account_id=account_id,
        raw_ref="first:seen",
    )

    flags = unusual_spend(store, sigma=2.0)

    assert [row["txn_id"] for row in flags] == [outlier_id]
    assert normal_id not in [row["txn_id"] for row in flags]
