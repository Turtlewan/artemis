from __future__ import annotations

import inspect
import sqlite3
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from artemis.config import Settings
from artemis.identity.key_provider import ScopeLockedError, SecretKey
from artemis.identity.scope import OWNER_PRIVATE
from artemis.modules.finance import (
    FinanceStore,
    TransactionSource,
    TransactionType,
    finance_manifest,
)
from artemis.modules.finance.csv_import import CsvColumnMapping, import_csv
from artemis.modules.finance.repository import FinanceRepository
from artemis.modules.finance.schema import SG_SEED_CATEGORIES, create_schema
from artemis.modules.finance.tools import TxnAddArgs
from artemis.ports.types import Scope


class FakeKeyProvider:
    def __init__(self, *, owner_unlocked: bool) -> None:
        self.owner_unlocked = owner_unlocked

    def dek_for_scope(self, scope: Scope) -> SecretKey:
        if scope != OWNER_PRIVATE or not self.owner_unlocked:
            raise ScopeLockedError(f"Scope is locked: {scope}")
        return SecretKey(b"f" * 32)

    def is_owner_unlocked(self) -> bool:
        return self.owner_unlocked


@pytest.fixture
def conn() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    create_schema(connection)
    return connection


def test_schema_round_trip() -> None:
    connection = sqlite3.connect(":memory:")
    create_schema(connection)
    create_schema(connection)

    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    assert {
        "account",
        "transaction",
        "subscription",
        "bill",
        "category",
        "csv_profile",
        "meta",
    } <= tables

    seed_count = connection.execute("SELECT COUNT(*) FROM category WHERE is_seed = 1").fetchone()[0]
    assert seed_count == len(SG_SEED_CATEGORIES) == 14

    for table in ("transaction", "subscription", "bill"):
        columns = {
            row[1]: row[2] for row in connection.execute(f'PRAGMA table_info("{table}")').fetchall()
        }
        assert columns["amount"].upper() == "TEXT"

    account_columns = {
        row[1]: row[2] for row in connection.execute('PRAGMA table_info("account")').fetchall()
    }
    assert account_columns["current_balance"].upper() == "TEXT"

    indexes = {
        row[1]: bool(row[4])
        for row in connection.execute('PRAGMA index_list("transaction")').fetchall()
    }
    assert indexes["idx_txn_raw_ref"] is True
    indexed_columns = [
        row[2] for row in connection.execute('PRAGMA index_info("idx_txn_raw_ref")').fetchall()
    ]
    assert indexed_columns == ["raw_ref"]


def test_account_category_transaction_crud(conn: sqlite3.Connection) -> None:
    repo = FinanceRepository(conn)
    account_id = repo.create_account("DBS Multiplier", "bank", institution="DBS")
    account = repo.get_account(account_id)
    assert account is not None
    assert account["name"] == "DBS Multiplier"
    repo.update_account(account_id, name="DBS Main", current_balance=Decimal("100.10"))
    updated_account = repo.get_account(account_id)
    assert updated_account is not None
    assert updated_account["current_balance"] == Decimal("100.10")
    repo.archive_account(account_id)
    assert repo.list_accounts() == []
    assert len(repo.list_accounts(include_archived=True)) == 1

    category_id = repo.add_category("Coffee")
    repo.rename_category(category_id, "Cafe")
    category = repo.get_category_by_name("Cafe")
    assert category is not None
    assert category["id"] == category_id

    txn_id = repo.add_transaction(
        txn_date="2026-06-01",
        amount=Decimal("19.99"),
        merchant="Kopi",
        category_id=category_id,
        source=TransactionSource.MANUAL.value,
        instrument_account_id=account_id,
        notes="morning",
    )
    transaction = repo.get_transaction(txn_id)
    assert transaction is not None
    assert transaction["amount"] == Decimal("19.99")
    repo.update_transaction(txn_id, merchant="Kopi Bar", amount=Decimal("20.01"))
    updated_transaction = repo.get_transaction(txn_id)
    assert updated_transaction is not None
    assert updated_transaction["merchant"] == "Kopi Bar"
    repo.recategorize(txn_id, category_id)
    assert len(repo.list_transactions(category_id=category_id)) == 1
    repo.delete_transaction(txn_id)
    assert repo.get_transaction(txn_id) is None


def test_raw_ref_idempotency(conn: sqlite3.Connection) -> None:
    repo = FinanceRepository(conn)
    account_id = repo.create_account("Card", "card")
    first = repo.add_transaction(
        txn_date="2026-06-01",
        amount=Decimal("10.00"),
        source=TransactionSource.MANUAL.value,
        instrument_account_id=account_id,
        raw_ref="x:1",
    )
    second = repo.add_transaction(
        txn_date="2026-06-01",
        amount=Decimal("10.00"),
        source=TransactionSource.MANUAL.value,
        instrument_account_id=account_id,
        raw_ref="x:1",
    )
    assert second == first
    assert len(repo.list_transactions()) == 1


def test_spend_excludes_transfer_settlement_and_subtracts_refund(
    conn: sqlite3.Connection,
) -> None:
    repo = FinanceRepository(conn)
    account_id = repo.create_account("Card", "card")
    category_id = repo.add_category("Daily")
    rows = [
        ("20.00", TransactionType.PURCHASE.value),
        ("5.00", TransactionType.REFUND.value),
        ("1000.00", TransactionType.TRANSFER.value),
        ("1200.00", TransactionType.SETTLEMENT.value),
    ]
    for amount, txn_type in rows:
        repo.add_transaction(
            txn_date="2026-06-01",
            amount=Decimal(amount),
            category_id=category_id,
            txn_type=txn_type,
            source=TransactionSource.MANUAL.value,
            instrument_account_id=account_id,
        )

    assert repo.total_spend(start="2026-06-01", end="2026-07-01") == Decimal("15.00")
    summary = repo.spend_summary(start="2026-06-01", end="2026-07-01", group_by="category")
    assert summary == [{"key": "Daily", "total": Decimal("15.00")}]


def test_csv_import_and_saved_profile(conn: sqlite3.Connection) -> None:
    repo = FinanceRepository(conn)
    account_id = repo.create_account("CSV Card", "card")
    mapping = CsvColumnMapping(
        date_col="Date",
        amount_col="Amount",
        merchant_col="Merchant",
        amount_is_negative_spend=True,
    )
    rows: list[Mapping[str, str]] = [
        {"Date": "2026-06-01", "Amount": "-1.10", "Merchant": "Coffee"},
        {"Date": "2026-06-02", "Amount": "-2.20", "Merchant": "Lunch"},
        {"Date": "2026-06-03", "Amount": "3.30", "Merchant": "Refund"},
    ]

    result = import_csv(rows, mapping, account_id=account_id, repo=repo)
    assert result.imported == 3
    assert result.skipped_duplicates == 0
    assert result.errors == []

    again = import_csv(rows, mapping, account_id=account_id, repo=repo)
    assert again.imported == 0
    assert again.skipped_duplicates == 3

    bad = import_csv(
        [
            {"Date": "bad", "Amount": "-4.40", "Merchant": "Bad"},
            {"Date": "2026-06-04", "Amount": "-5.50", "Merchant": "Good"},
        ],
        mapping,
        account_id=account_id,
        repo=repo,
    )
    assert bad.imported == 1
    assert len(bad.errors) == 1

    repo.save_csv_profile("bank", mapping)
    assert repo.get_csv_profile("bank") == mapping


def test_finance_store_scope_lock_and_round_trip(tmp_path: Path) -> None:
    settings = Settings(data_root=tmp_path)
    locked = FinanceStore(settings, FakeKeyProvider(owner_unlocked=False))
    with pytest.raises(ScopeLockedError):
        locked.list_accounts()

    store = FinanceStore(settings, FakeKeyProvider(owner_unlocked=True))
    account_id = store.create_account("Cash", "cash")
    account = store.get_account(account_id)
    assert account is not None
    assert account["name"] == "Cash"
    store.close()


def test_finance_store_fails_closed_without_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from artemis.data.sqlcipher import SqlCipherError

    def _no_binding(*_args: object, **_kwargs: object) -> object:
        raise SqlCipherError("sqlcipher3 binding not installed")

    monkeypatch.setattr("artemis.modules.finance.store.sqlcipher_open", _no_binding)
    store = FinanceStore(Settings(data_root=tmp_path), FakeKeyProvider(owner_unlocked=True))
    with pytest.raises(SqlCipherError):
        store.list_accounts()


def test_finance_manifest_and_tools_shape(tmp_path: Path) -> None:
    manifest = finance_manifest(
        FinanceStore(Settings(data_root=tmp_path), FakeKeyProvider(owner_unlocked=True))
    )
    assert manifest.name == "finance"
    assert manifest.data_scope.value == OWNER_PRIVATE
    assert manifest.permissions.guest is False
    # FIN-c wires 4 proactive hooks (all tier=1 on the OWNER_PRIVATE module).
    assert len(manifest.proactive_hooks) == 4
    assert all(hook.tier == 1 for hook in manifest.proactive_hooks)
    assert manifest.ui.kind == "card"
    assert all(inspect.iscoroutinefunction(tool.callable_ref) for tool in manifest.tools)
    with pytest.raises(ValidationError):
        TxnAddArgs(txn_date="2026-06-01", amount="not-decimal")


def test_finance_package_has_no_cloud_imports() -> None:
    # Always-local: the ledger may use the LOCAL ModelPort (loopback
    # sensitive_reasoner, added in FIN-b extraction) but never a CLOUD/Codex
    # port. Assert the cloud-specific markers are absent, not ModelPort itself.
    finance_dir = Path(__file__).parents[1] / "src" / "artemis" / "modules" / "finance"
    combined = "\n".join(path.read_text() for path in finance_dir.glob("*.py"))
    assert "model_adapters" not in combined
    assert "Codex" not in combined
    assert "responder_cloud" not in combined
    assert "model_adapters" not in combined
    assert "cloud" not in combined
