"""Generic column-mapped CSV import for the always-local Finance ledger."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha1
from typing import TYPE_CHECKING

from artemis.modules.finance.schema import TransactionType

if TYPE_CHECKING:
    from artemis.modules.finance.repository import FinanceRepository


@dataclass(frozen=True)
class CsvColumnMapping:
    """Saved mapping from arbitrary bank-export column names to ledger fields."""

    date_col: str
    amount_col: str
    merchant_col: str | None = None
    currency_col: str | None = None
    type_col: str | None = None
    date_format: str = "%Y-%m-%d"
    amount_is_negative_spend: bool = False


@dataclass(frozen=True)
class ImportResult:
    """CSV import counts and recoverable row errors."""

    imported: int
    skipped_duplicates: int
    errors: list[str]


def import_csv(
    rows: Iterable[Mapping[str, str]],
    mapping: CsvColumnMapping,
    *,
    account_id: str,
    repo: FinanceRepository,
) -> ImportResult:
    """Import mapped CSV rows, using ``raw_ref`` as the L0 idempotency key."""
    imported = 0
    skipped_duplicates = 0
    errors: list[str] = []

    for index, row in enumerate(rows, start=1):
        try:
            txn_date = (
                datetime.strptime(row[mapping.date_col], mapping.date_format).date().isoformat()
            )
            parsed_amount = _parse_amount(row[mapping.amount_col])
            txn_type, amount = _normalise_amount(
                parsed_amount,
                explicit_type=row.get(mapping.type_col) if mapping.type_col else None,
                amount_is_negative_spend=mapping.amount_is_negative_spend,
            )
            merchant = row.get(mapping.merchant_col, "") if mapping.merchant_col else ""
            currency = row.get(mapping.currency_col, "SGD") if mapping.currency_col else "SGD"
            raw_ref = _raw_ref(account_id, txn_date, amount, merchant)
            before = repo.get_transaction_by_raw_ref(raw_ref)
            repo.add_transaction(
                txn_date=txn_date,
                amount=amount,
                merchant=merchant or None,
                txn_type=txn_type,
                source="csv",
                instrument_account_id=account_id,
                currency=currency or "SGD",
                raw_ref=raw_ref,
            )
            if before is None:
                imported += 1
            else:
                skipped_duplicates += 1
        except (KeyError, ValueError, InvalidOperation) as exc:
            errors.append(f"row {index}: {exc}")

    return ImportResult(
        imported=imported,
        skipped_duplicates=skipped_duplicates,
        errors=errors,
    )


def _parse_amount(value: str) -> Decimal:
    cleaned = value.strip().replace(",", "")
    for symbol in ("S$", "$", "SGD"):
        cleaned = cleaned.replace(symbol, "")
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = f"-{cleaned[1:-1]}"
    return Decimal(cleaned.strip())


def _normalise_amount(
    amount: Decimal,
    *,
    explicit_type: str | None,
    amount_is_negative_spend: bool,
) -> tuple[str, Decimal]:
    if explicit_type:
        lowered = explicit_type.strip().lower()
        if lowered in {"refund", "credit", "cr"}:
            return TransactionType.REFUND.value, abs(amount)
        if lowered in {"transfer", "settlement"}:
            return lowered, abs(amount)
        return TransactionType.PURCHASE.value, abs(amount)
    if amount_is_negative_spend:
        if amount < 0:
            return TransactionType.PURCHASE.value, abs(amount)
        return TransactionType.REFUND.value, amount
    if amount < 0:
        return TransactionType.REFUND.value, abs(amount)
    return TransactionType.PURCHASE.value, amount


def _raw_ref(account_id: str, txn_date: str, amount: Decimal, merchant: str) -> str:
    digest = sha1(f"{txn_date}|{amount}|{merchant}".encode()).hexdigest()
    return f"csv:{account_id}:{digest}"
