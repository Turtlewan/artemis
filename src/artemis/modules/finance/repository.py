"""Repository for the always-local Finance ledger."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from decimal import Decimal
from typing import Literal
from uuid import uuid4

from artemis.data.sqlcipher import set_row_factory
from artemis.memory.schema import now_iso
from artemis.modules.finance.csv_import import CsvColumnMapping
from artemis.modules.finance.schema import BillStatus, SubscriptionCadence, TransactionType


class FinanceRepository:
    """Parameterised SQL access over the locked Finance schema."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        set_row_factory(self.conn)

    def create_account(
        self,
        name: str,
        account_type: str,
        *,
        currency: str = "SGD",
        institution: str | None = None,
    ) -> str:
        account_id = uuid4().hex
        now = now_iso()
        self.conn.execute(
            """
            INSERT INTO account (
                id, name, account_type, currency, institution, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (account_id, name, account_type, currency, institution, now, now),
        )
        self.conn.commit()
        return account_id

    def get_account(self, id: str) -> dict[str, object] | None:
        row = self.conn.execute("SELECT * FROM account WHERE id = ?", (id,)).fetchone()
        return _account_row(row) if row is not None else None

    def list_accounts(self, *, include_archived: bool = False) -> list[dict[str, object]]:
        if include_archived:
            rows = self.conn.execute("SELECT * FROM account ORDER BY name").fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM account WHERE archived = 0 ORDER BY name"
            ).fetchall()
        return [_account_row(row) for row in rows]

    def update_account(
        self,
        id: str,
        *,
        name: str | None = None,
        institution: str | None = None,
        current_balance: Decimal | None = None,
    ) -> None:
        updates: dict[str, object] = {"updated_at": now_iso()}
        if name is not None:
            updates["name"] = name
        if institution is not None:
            updates["institution"] = institution
        if current_balance is not None:
            updates["current_balance"] = str(current_balance)
        self._update("account", id, updates)

    def archive_account(self, id: str) -> None:
        self._update("account", id, {"archived": 1, "updated_at": now_iso()})

    def list_categories(self) -> list[dict[str, object]]:
        rows = self.conn.execute("SELECT * FROM category ORDER BY is_seed DESC, name").fetchall()
        return [_plain_row(row) for row in rows]

    def add_category(self, name: str) -> str:
        category_id = uuid4().hex
        self.conn.execute(
            """
            INSERT INTO category (id, name, is_seed, created_at)
            VALUES (?, ?, 0, ?)
            """,
            (category_id, name, now_iso()),
        )
        self.conn.commit()
        return category_id

    def rename_category(self, id: str, name: str) -> None:
        self.conn.execute("UPDATE category SET name = ? WHERE id = ?", (name, id))
        self.conn.commit()

    def get_category_by_name(self, name: str) -> dict[str, object] | None:
        row = self.conn.execute("SELECT * FROM category WHERE name = ?", (name,)).fetchone()
        return _plain_row(row) if row is not None else None

    def add_transaction(
        self,
        *,
        txn_date: str,
        amount: Decimal,
        merchant: str | None = None,
        category_id: str | None = None,
        txn_type: str = TransactionType.PURCHASE.value,
        source: str,
        instrument_account_id: str | None = None,
        currency: str = "SGD",
        amount_original: Decimal | None = None,
        currency_original: str | None = None,
        raw_ref: str | None = None,
        confidence: float | None = None,
        notes: str | None = None,
    ) -> str:
        transaction_id = uuid4().hex
        now = now_iso()
        cursor = self.conn.execute(
            """
            INSERT INTO "transaction" (
                id, txn_date, amount, currency, amount_original, currency_original, merchant,
                category_id, txn_type, source, instrument_account_id, raw_ref, confidence, notes,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(raw_ref) WHERE raw_ref IS NOT NULL DO NOTHING
            """,
            (
                transaction_id,
                txn_date,
                str(amount),
                currency,
                _decimal_text(amount_original),
                currency_original,
                merchant,
                category_id,
                txn_type,
                source,
                instrument_account_id,
                raw_ref,
                confidence,
                notes,
                now,
                now,
            ),
        )
        self.conn.commit()
        # Fast path: a fresh insert returns its own id. Only on an ON CONFLICT
        # no-op (rowcount == 0) do we resolve the pre-existing row (L0 dedup).
        if raw_ref is not None and cursor.rowcount == 0:
            existing = self.get_transaction_by_raw_ref(raw_ref)
            if existing is not None:
                return str(existing["id"])
        return transaction_id

    def get_transaction(self, id: str) -> dict[str, object] | None:
        row = self.conn.execute('SELECT * FROM "transaction" WHERE id = ?', (id,)).fetchone()
        return _transaction_row(row) if row is not None else None

    def get_transaction_by_raw_ref(self, raw_ref: str) -> dict[str, object] | None:
        row = self.conn.execute(
            'SELECT * FROM "transaction" WHERE raw_ref = ?', (raw_ref,)
        ).fetchone()
        return _transaction_row(row) if row is not None else None

    def list_transactions(
        self,
        *,
        start: str | None = None,
        end: str | None = None,
        category_id: str | None = None,
        txn_type: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, object]]:
        clauses: list[str] = []
        params: list[object] = []
        if start is not None:
            clauses.append("txn_date >= ?")
            params.append(start)
        if end is not None:
            clauses.append("txn_date < ?")
            params.append(end)
        if category_id is not None:
            clauses.append("category_id = ?")
            params.append(category_id)
        if txn_type is not None:
            clauses.append("txn_type = ?")
            params.append(txn_type)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.conn.execute(
            f'SELECT * FROM "transaction" {where} ORDER BY txn_date DESC, created_at DESC LIMIT ?',
            (*params, limit),
        ).fetchall()
        return [_transaction_row(row) for row in rows]

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
        updates: dict[str, object] = {"updated_at": now_iso()}
        if merchant is not None:
            updates["merchant"] = merchant
        if category_id is not None:
            updates["category_id"] = category_id
        if txn_type is not None:
            updates["txn_type"] = txn_type
        if notes is not None:
            updates["notes"] = notes
        if amount is not None:
            updates["amount"] = str(amount)
        self._update('"transaction"', id, updates)

    def recategorize(self, id: str, category_id: str) -> None:
        self._update('"transaction"', id, {"category_id": category_id, "updated_at": now_iso()})

    def delete_transaction(self, id: str) -> None:
        self.conn.execute('DELETE FROM "transaction" WHERE id = ?', (id,))
        self.conn.commit()

    def create_fin_suggestion(
        self,
        kind: str,
        payload_json: str,
        *,
        raw_ref: str | None = None,
    ) -> str:
        suggestion_id = uuid4().hex
        now = now_iso()
        self.conn.execute(
            """
            INSERT INTO fin_suggestion (
                id, kind, payload_json, raw_ref, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'pending', ?, ?)
            """,
            (suggestion_id, kind, payload_json, raw_ref, now, now),
        )
        self.conn.commit()
        return suggestion_id

    def list_fin_suggestions(self, *, status: str = "pending") -> list[dict[str, object]]:
        rows = self.conn.execute(
            """
            SELECT * FROM fin_suggestion
            WHERE status = ?
            ORDER BY created_at ASC
            """,
            (status,),
        ).fetchall()
        return [_plain_row(row) for row in rows]

    def accept_fin_suggestion(self, id: str, *, txn_type: str) -> str:
        row = self.conn.execute("SELECT * FROM fin_suggestion WHERE id = ?", (id,)).fetchone()
        if row is None:
            raise ValueError(f"Unknown finance suggestion: {id}")
        suggestion = _plain_row(row)
        status = str(suggestion["status"])
        if status != "pending":
            raise ValueError(f"suggestion {id} is already {status}")
        payload = _suggestion_payload(str(suggestion["payload_json"]))
        txn_id = self.add_transaction(
            txn_date=str(payload["txn_date"]),
            amount=Decimal(str(payload["amount"])),
            merchant=_optional_str(payload.get("merchant")),
            txn_type=txn_type,
            source="email",
            instrument_account_id=_optional_str(payload.get("instrument_account_id")),
            currency=str(payload.get("currency", "SGD")),
            raw_ref=_optional_str(payload.get("raw_ref"))
            or _optional_str(suggestion.get("raw_ref")),
            confidence=_optional_float(payload.get("confidence")),
        )
        self.conn.execute(
            """
            UPDATE fin_suggestion
            SET status = 'accepted', updated_at = ?
            WHERE id = ?
            """,
            (now_iso(), id),
        )
        self.conn.commit()
        return txn_id

    def reject_fin_suggestion(self, id: str) -> None:
        self.conn.execute(
            """
            UPDATE fin_suggestion
            SET status = 'rejected', updated_at = ?
            WHERE id = ?
            """,
            (now_iso(), id),
        )
        self.conn.commit()

    def mark_fin_suggestion_accepted(self, id: str) -> None:
        self.conn.execute(
            """
            UPDATE fin_suggestion
            SET status = 'accepted', updated_at = ?
            WHERE id = ?
            """,
            (now_iso(), id),
        )
        self.conn.commit()

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
        if cadence not in {item.value for item in SubscriptionCadence}:
            raise ValueError(f"unsupported subscription cadence: {cadence}")
        row = self.conn.execute(
            """
            SELECT id FROM subscription
            WHERE merchant = ? AND cadence = ?
            """,
            (merchant, cadence),
        ).fetchone()
        now = now_iso()
        if row is not None:
            subscription_id = str(row["id"])
            self.conn.execute(
                """
                UPDATE subscription
                SET amount = ?, next_renewal = ?, last_seen_price = ?,
                    last_seen_date = ?, active = 1, updated_at = ?
                WHERE id = ?
                """,
                (
                    str(amount),
                    next_renewal,
                    _decimal_text(last_seen_price),
                    last_seen_date,
                    now,
                    subscription_id,
                ),
            )
            self.conn.commit()
            return subscription_id

        subscription_id = uuid4().hex
        self.conn.execute(
            """
            INSERT INTO subscription (
                id, merchant, cadence, amount, next_renewal, last_seen_price,
                last_seen_date, active, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (
                subscription_id,
                merchant,
                cadence,
                str(amount),
                next_renewal,
                _decimal_text(last_seen_price),
                last_seen_date,
                now,
                now,
            ),
        )
        self.conn.commit()
        return subscription_id

    def list_subscriptions(self, *, active: bool = True) -> list[dict[str, object]]:
        if active:
            rows = self.conn.execute(
                "SELECT * FROM subscription WHERE active = 1 ORDER BY next_renewal"
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM subscription ORDER BY next_renewal").fetchall()
        return [_subscription_row(row) for row in rows]

    def upsert_bill(
        self,
        *,
        payee: str,
        due_date: str,
        amount: Decimal | None = None,
        raw_ref: str | None = None,
    ) -> str:
        row = self.conn.execute(
            "SELECT id FROM bill WHERE payee = ? AND due_date = ?",
            (payee, due_date),
        ).fetchone()
        now = now_iso()
        if row is not None:
            bill_id = str(row["id"])
            self.conn.execute(
                """
                UPDATE bill
                SET amount = COALESCE(?, amount), raw_ref = COALESCE(?, raw_ref), updated_at = ?
                WHERE id = ?
                """,
                (_decimal_text(amount), raw_ref, now, bill_id),
            )
            self.conn.commit()
            return bill_id

        bill_id = uuid4().hex
        self.conn.execute(
            """
            INSERT INTO bill (
                id, payee, due_date, amount, status, raw_ref, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                bill_id,
                payee,
                due_date,
                _decimal_text(amount),
                BillStatus.OPEN.value,
                raw_ref,
                now,
                now,
            ),
        )
        self.conn.commit()
        return bill_id

    def list_bills(self, *, status: str | None = None) -> list[dict[str, object]]:
        if status is None:
            rows = self.conn.execute("SELECT * FROM bill ORDER BY due_date").fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM bill WHERE status = ? ORDER BY due_date",
                (status,),
            ).fetchall()
        return [_bill_row(row) for row in rows]

    def get_bill(self, id: str) -> dict[str, object] | None:
        """Return a bill row by id, including lifecycle linkage fields."""
        row = self.conn.execute("SELECT * FROM bill WHERE id = ?", (id,)).fetchone()
        return _bill_row(row) if row is not None else None

    def mark_bill_paid(self, id: str) -> None:
        self.conn.execute(
            """
            UPDATE bill
            SET status = ?, paid_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (BillStatus.PAID.value, now_iso(), now_iso(), id),
        )
        self.conn.commit()

    def merge_transactions(self, keep_id: str, drop_id: str) -> None:
        if keep_id == drop_id:
            return
        self.conn.execute('DELETE FROM "transaction" WHERE id = ?', (drop_id,))
        self.conn.execute(
            'UPDATE "transaction" SET updated_at = ? WHERE id = ?',
            (now_iso(), keep_id),
        )
        self.conn.commit()

    def merchant_amount_history(
        self,
        *,
        merchant: str,
        category_id: str | None = None,
        lookback_days: int = 180,
    ) -> list[Decimal]:
        clauses = [
            "LOWER(TRIM(merchant)) = ?",
            "txn_type IN ('purchase','refund')",
            "txn_date >= date('now', ?)",
        ]
        params: list[object] = [
            _normalize_merchant(merchant),
            f"-{lookback_days} days",
        ]
        if category_id is not None:
            clauses.append("category_id = ?")
            params.append(category_id)
        rows = self.conn.execute(
            f"""
            SELECT amount FROM "transaction"
            WHERE {" AND ".join(clauses)}
            ORDER BY txn_date ASC, created_at ASC
            """,
            params,
        ).fetchall()
        return [Decimal(str(row["amount"])) for row in rows]

    def recurring_candidates(self, *, min_occurrences: int) -> list[dict[str, object]]:
        rows = self.conn.execute(
            """
            SELECT id, txn_date, amount, currency, merchant, category_id, notes
            FROM "transaction"
            WHERE txn_type = 'purchase' AND merchant IS NOT NULL
            ORDER BY merchant, amount, txn_date
            """
        ).fetchall()
        groups: dict[tuple[str, Decimal, str], list[dict[str, object]]] = {}
        for row in rows:
            amount = Decimal(str(row["amount"])).quantize(Decimal("0.01"))
            merchant = str(row["merchant"])
            key = (_normalize_merchant(merchant), amount, str(row["currency"]))
            groups.setdefault(key, []).append(_plain_row(row))

        candidates: list[dict[str, object]] = []
        for (normalized, amount, currency), group in groups.items():
            if len(group) < min_occurrences:
                continue
            dates = [str(row["txn_date"]) for row in group]
            candidates.append(
                {
                    "merchant": _merchant_label(group),
                    "normalized_merchant": normalized,
                    "amount": amount,
                    "currency": currency,
                    "occurrences": len(group),
                    "dates": dates,
                    "transaction_ids": [str(row["id"]) for row in group],
                    "category_id": group[-1].get("category_id"),
                    "due_dates": _due_dates(group),
                }
            )
        return candidates

    def spend_summary(
        self,
        *,
        start: str,
        end: str,
        group_by: Literal["category", "day", "merchant"],
    ) -> list[dict[str, object]]:
        select_expr = {
            "category": "COALESCE(category.name, 'Uncategorised')",
            "day": '"transaction".txn_date',
            "merchant": "COALESCE(\"transaction\".merchant, 'Unknown')",
        }[group_by]
        rows = self.conn.execute(
            f"""
            SELECT {select_expr} AS key,
                SUM(CASE WHEN txn_type='refund' THEN -amount ELSE amount END) AS total
            FROM "transaction"
            LEFT JOIN category ON category.id = "transaction".category_id
            WHERE txn_date >= ?
                AND txn_date < ?
                AND txn_type IN ('purchase','refund')
            GROUP BY key
            ORDER BY key
            """,
            (start, end),
        ).fetchall()
        return [{"key": str(row["key"]), "total": _decimal_from_sql(row["total"])} for row in rows]

    def total_spend(self, *, start: str, end: str) -> Decimal:
        row = self.conn.execute(
            """
            SELECT SUM(CASE WHEN txn_type='refund' THEN -amount ELSE amount END) AS total
            FROM "transaction"
            WHERE txn_date >= ?
                AND txn_date < ?
                AND txn_type IN ('purchase','refund')
            """,
            (start, end),
        ).fetchone()
        if row is None:
            return Decimal("0")
        return _decimal_from_sql(row["total"])

    def save_csv_profile(self, name: str, mapping: CsvColumnMapping) -> None:
        profile_id = uuid4().hex
        self.conn.execute(
            """
            INSERT INTO csv_profile (id, name, mapping_json, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET mapping_json = excluded.mapping_json
            """,
            (profile_id, name, json.dumps(asdict(mapping)), now_iso()),
        )
        self.conn.commit()

    def get_csv_profile(self, name: str) -> CsvColumnMapping | None:
        row = self.conn.execute(
            "SELECT mapping_json FROM csv_profile WHERE name = ?", (name,)
        ).fetchone()
        if row is None:
            return None
        raw = json.loads(str(row["mapping_json"]))
        if not isinstance(raw, dict):
            return None
        mapping: dict[str, object] = raw
        return CsvColumnMapping(
            date_col=str(mapping["date_col"]),
            amount_col=str(mapping["amount_col"]),
            merchant_col=_optional_str(mapping.get("merchant_col")),
            currency_col=_optional_str(mapping.get("currency_col")),
            type_col=_optional_str(mapping.get("type_col")),
            date_format=str(mapping.get("date_format", "%Y-%m-%d")),
            amount_is_negative_spend=bool(mapping.get("amount_is_negative_spend", False)),
        )

    def _update(self, table: str, id: str, updates: Mapping[str, object]) -> None:
        assignments = ", ".join(f"{column} = ?" for column in updates)
        self.conn.execute(
            f"UPDATE {table} SET {assignments} WHERE id = ?",
            (*updates.values(), id),
        )
        self.conn.commit()


def _decimal_text(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _plain_row(row: sqlite3.Row) -> dict[str, object]:
    return dict(row)


def _account_row(row: sqlite3.Row) -> dict[str, object]:
    result = dict(row)
    if result["current_balance"] is not None:
        result["current_balance"] = Decimal(str(result["current_balance"]))
    return result


def _transaction_row(row: sqlite3.Row) -> dict[str, object]:
    result = dict(row)
    result["amount"] = Decimal(str(result["amount"]))
    if result["amount_original"] is not None:
        result["amount_original"] = Decimal(str(result["amount_original"]))
    return result


def _subscription_row(row: sqlite3.Row) -> dict[str, object]:
    result = dict(row)
    result["amount"] = Decimal(str(result["amount"]))
    if result["last_seen_price"] is not None:
        result["last_seen_price"] = Decimal(str(result["last_seen_price"]))
    return result


def _bill_row(row: sqlite3.Row) -> dict[str, object]:
    result = dict(row)
    if result["amount"] is not None:
        result["amount"] = Decimal(str(result["amount"]))
    return result


def _decimal_from_sql(value: object) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def _optional_str(value: object) -> str | None:
    return str(value) if value is not None else None


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, str | int | float):
        return float(value)
    raise ValueError("suggestion confidence must be numeric")


def _suggestion_payload(payload_json: str) -> dict[str, object]:
    raw = json.loads(payload_json)
    if not isinstance(raw, dict):
        raise ValueError("suggestion payload must decode to an object")
    transaction = raw.get("transaction", raw)
    if not isinstance(transaction, dict):
        raise ValueError("suggestion payload transaction must be an object")
    required = ("txn_date", "amount", "raw_ref")
    if not all(key in transaction for key in required):
        raise ValueError("suggestion payload missing transaction fields")
    return dict(transaction)


def _normalize_merchant(value: str) -> str:
    return " ".join(value.casefold().split())


def _merchant_label(rows: Sequence[dict[str, object]]) -> str:
    value = rows[-1].get("merchant")
    return str(value) if value is not None else ""


_DUE_RE = re.compile(r"\bdue[:= ](?P<date>\d{4}-\d{2}-\d{2})\b", re.IGNORECASE)


def _due_dates(rows: Sequence[dict[str, object]]) -> list[str]:
    due_dates: list[str] = []
    for row in rows:
        notes = row.get("notes")
        if not isinstance(notes, str):
            continue
        match = _DUE_RE.search(notes)
        if match is not None:
            due_dates.append(match.group("date"))
    return due_dates
