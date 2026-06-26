"""Lazy owner-private store for the Finance ledger."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping
from decimal import Decimal
from pathlib import Path
from typing import Literal

from artemis import paths
from artemis.config import Settings
from artemis.identity.key_provider import KeyProvider
from artemis.identity.scope import OWNER_PRIVATE
from artemis.modules.finance.csv_import import (
    CsvColumnMapping,
    ImportResult,
)
from artemis.modules.finance.csv_import import (
    import_csv as _import_csv,
)
from artemis.modules.finance.repository import FinanceRepository
from artemis.modules.finance.schema import create_schema


class FinanceStore:
    """Owner-private SQLCipher-backed Finance store with lazy connection setup."""

    def __init__(self, settings: Settings, key_provider: KeyProvider) -> None:
        self.settings = settings
        self.key_provider = key_provider
        self._conn: sqlite3.Connection | None = None

    def _db_path(self) -> Path:
        return paths.scope_dir(self.settings, OWNER_PRIVATE) / "relational" / "finance.db"

    def _connect(self) -> sqlite3.Connection:
        """Open the Finance DB and ensure schema exists."""
        key = self.key_provider.dek_for_scope(OWNER_PRIVATE)
        key_hex = key.as_hex()
        db_path = self._db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            from artemis.data.sqlcipher import sqlcipher_open

            conn = sqlcipher_open(db_path, key_hex)
        except ImportError:
            conn = sqlite3.connect(db_path)  # FALLBACK: no encryption -- CI/dev only
        conn.execute("PRAGMA foreign_keys = ON")
        create_schema(conn)
        return conn

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = self._connect()
        return self._conn

    def close(self) -> None:
        """Close the lazy connection if opened."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _repo(self) -> FinanceRepository:
        return FinanceRepository(self._get_conn())

    def create_account(
        self,
        name: str,
        account_type: str,
        *,
        currency: str = "SGD",
        institution: str | None = None,
    ) -> str:
        return self._repo().create_account(
            name,
            account_type,
            currency=currency,
            institution=institution,
        )

    def get_account(self, id: str) -> dict[str, object] | None:
        return self._repo().get_account(id)

    def list_accounts(self, *, include_archived: bool = False) -> list[dict[str, object]]:
        return self._repo().list_accounts(include_archived=include_archived)

    def update_account(
        self,
        id: str,
        *,
        name: str | None = None,
        institution: str | None = None,
        current_balance: Decimal | None = None,
    ) -> None:
        self._repo().update_account(
            id,
            name=name,
            institution=institution,
            current_balance=current_balance,
        )

    def archive_account(self, id: str) -> None:
        self._repo().archive_account(id)

    def list_categories(self) -> list[dict[str, object]]:
        return self._repo().list_categories()

    def add_category(self, name: str) -> str:
        return self._repo().add_category(name)

    def rename_category(self, id: str, name: str) -> None:
        self._repo().rename_category(id, name)

    def get_category_by_name(self, name: str) -> dict[str, object] | None:
        return self._repo().get_category_by_name(name)

    def add_transaction(
        self,
        *,
        txn_date: str,
        amount: Decimal,
        merchant: str | None = None,
        category_id: str | None = None,
        txn_type: str = "purchase",
        source: str,
        instrument_account_id: str | None = None,
        currency: str = "SGD",
        amount_original: Decimal | None = None,
        currency_original: str | None = None,
        raw_ref: str | None = None,
        confidence: float | None = None,
        notes: str | None = None,
    ) -> str:
        return self._repo().add_transaction(
            txn_date=txn_date,
            amount=amount,
            merchant=merchant,
            category_id=category_id,
            txn_type=txn_type,
            source=source,
            instrument_account_id=instrument_account_id,
            currency=currency,
            amount_original=amount_original,
            currency_original=currency_original,
            raw_ref=raw_ref,
            confidence=confidence,
            notes=notes,
        )

    def get_transaction(self, id: str) -> dict[str, object] | None:
        return self._repo().get_transaction(id)

    def list_transactions(
        self,
        *,
        start: str | None = None,
        end: str | None = None,
        category_id: str | None = None,
        txn_type: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, object]]:
        return self._repo().list_transactions(
            start=start,
            end=end,
            category_id=category_id,
            txn_type=txn_type,
            limit=limit,
        )

    def update_transaction(
        self,
        id: str,
        *,
        merchant: str | None = None,
        category_id: str | None = None,
        txn_type: str | None = None,
        notes: str | None = None,
        amount: Decimal | None = None,
    ) -> None:
        self._repo().update_transaction(
            id,
            merchant=merchant,
            category_id=category_id,
            txn_type=txn_type,
            notes=notes,
            amount=amount,
        )

    def recategorize(self, id: str, category_id: str) -> None:
        self._repo().recategorize(id, category_id)

    def delete_transaction(self, id: str) -> None:
        self._repo().delete_transaction(id)

    def create_fin_suggestion(
        self,
        kind: str,
        payload_json: str,
        *,
        raw_ref: str | None = None,
    ) -> str:
        return self._repo().create_fin_suggestion(kind, payload_json, raw_ref=raw_ref)

    def list_fin_suggestions(self, *, status: str = "pending") -> list[dict[str, object]]:
        return self._repo().list_fin_suggestions(status=status)

    def accept_fin_suggestion(self, id: str, *, txn_type: str) -> str:
        return self._repo().accept_fin_suggestion(id, txn_type=txn_type)

    def reject_fin_suggestion(self, id: str) -> None:
        self._repo().reject_fin_suggestion(id)

    def mark_fin_suggestion_accepted(self, id: str) -> None:
        self._repo().mark_fin_suggestion_accepted(id)

    def upsert_subscription(
        self,
        *,
        merchant: str,
        cadence: str,
        amount: Decimal,
        next_renewal: str | None = None,
        last_seen_price: Decimal | None = None,
        last_seen_date: str | None = None,
    ) -> str:
        return self._repo().upsert_subscription(
            merchant=merchant,
            cadence=cadence,
            amount=amount,
            next_renewal=next_renewal,
            last_seen_price=last_seen_price,
            last_seen_date=last_seen_date,
        )

    def list_subscriptions(self, *, active: bool = True) -> list[dict[str, object]]:
        return self._repo().list_subscriptions(active=active)

    def upsert_bill(
        self,
        *,
        payee: str,
        due_date: str,
        amount: Decimal | None = None,
        raw_ref: str | None = None,
    ) -> str:
        return self._repo().upsert_bill(
            payee=payee,
            due_date=due_date,
            amount=amount,
            raw_ref=raw_ref,
        )

    def list_bills(self, *, status: str | None = None) -> list[dict[str, object]]:
        return self._repo().list_bills(status=status)

    def get_bill(self, id: str) -> dict[str, object] | None:
        """Return a bill row by id, including linked task metadata."""
        return self._repo().get_bill(id)

    def mark_bill_paid(self, id: str) -> None:
        self._repo().mark_bill_paid(id)

    def merge_transactions(self, keep_id: str, drop_id: str) -> None:
        self._repo().merge_transactions(keep_id, drop_id)

    def merchant_amount_history(
        self,
        *,
        merchant: str,
        category_id: str | None = None,
        lookback_days: int = 180,
    ) -> list[Decimal]:
        return self._repo().merchant_amount_history(
            merchant=merchant,
            category_id=category_id,
            lookback_days=lookback_days,
        )

    def recurring_candidates(self, *, min_occurrences: int) -> list[dict[str, object]]:
        return self._repo().recurring_candidates(min_occurrences=min_occurrences)

    def spend_summary(
        self,
        *,
        start: str,
        end: str,
        group_by: Literal["category", "day", "merchant"],
    ) -> list[dict[str, object]]:
        return self._repo().spend_summary(start=start, end=end, group_by=group_by)

    def total_spend(self, *, start: str, end: str) -> Decimal:
        return self._repo().total_spend(start=start, end=end)

    def save_csv_profile(self, name: str, mapping: CsvColumnMapping) -> None:
        self._repo().save_csv_profile(name, mapping)

    def get_csv_profile(self, name: str) -> CsvColumnMapping | None:
        return self._repo().get_csv_profile(name)

    def import_csv(
        self,
        rows: Iterable[Mapping[str, str]],
        mapping: CsvColumnMapping,
        *,
        account_id: str,
    ) -> ImportResult:
        return _import_csv(rows, mapping, account_id=account_id, repo=self._repo())
