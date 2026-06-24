"""Async Finance tool callables for local ledger awareness."""

from __future__ import annotations

import json
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Literal, cast

from pydantic import BaseModel, field_validator

from artemis.manifest import ActionRisk, ToolSpec
from artemis.modules.finance.store import FinanceStore

_store: FinanceStore | None = None


class EmptyArgs(BaseModel):
    """Tool args for no-argument tools."""


class OkResult(BaseModel):
    """Generic success result."""

    ok: bool = True


class SpendSummaryArgs(BaseModel):
    """Arguments for grouped spend."""

    start: str
    end: str
    group_by: Literal["category", "day", "merchant"] = "category"


class SpendSummaryResult(BaseModel):
    """Grouped spend result."""

    rows: list[dict[str, object]]


class SpendTotalArgs(BaseModel):
    """Arguments for total spend."""

    start: str
    end: str


class SpendTotalResult(BaseModel):
    """Total spend result with Decimal represented as text."""

    total: str


class TxnListArgs(BaseModel):
    """Arguments for transaction listing."""

    start: str | None = None
    end: str | None = None
    category_id: str | None = None
    txn_type: str | None = None


class TxnListResult(BaseModel):
    """Transaction list result."""

    transactions: list[dict[str, object]]


class TxnGetArgs(BaseModel):
    """Arguments for getting a transaction."""

    id: str


class TxnResult(BaseModel):
    """Single transaction result."""

    transaction: dict[str, object] | None


class TxnCreatedResult(BaseModel):
    """Created transaction id."""

    transaction_id: str


class TxnAddArgs(BaseModel):
    """Arguments for creating a transaction."""

    txn_date: str
    amount: str
    merchant: str | None = None
    category_id: str | None = None
    txn_type: str = "purchase"
    instrument_account_id: str | None = None

    @field_validator("amount")
    @classmethod
    def _validate_amount(cls, value: str) -> str:
        return _validated_decimal_text(value)


class TxnUpdateArgs(BaseModel):
    """Arguments for updating a transaction."""

    id: str
    merchant: str | None = None
    category_id: str | None = None
    txn_type: str | None = None
    amount: str | None = None
    notes: str | None = None

    @field_validator("amount")
    @classmethod
    def _validate_amount(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validated_decimal_text(value)


class TxnRecategorizeArgs(BaseModel):
    """Arguments for recategorising a transaction."""

    id: str
    category_id: str


class CategoryListResult(BaseModel):
    """Category list result."""

    categories: list[dict[str, object]]


class CategoryAddArgs(BaseModel):
    """Arguments for adding a category."""

    name: str


class CategoryCreatedResult(BaseModel):
    """Created category id."""

    category_id: str


class AccountListArgs(BaseModel):
    """Arguments for listing accounts."""

    include_archived: bool = False


class AccountListResult(BaseModel):
    """Account list result."""

    accounts: list[dict[str, object]]


class AccountAddArgs(BaseModel):
    """Arguments for adding an account."""

    name: str
    account_type: str
    currency: str = "SGD"


class AccountCreatedResult(BaseModel):
    """Created account id."""

    account_id: str


class CsvImportArgs(BaseModel):
    """Arguments for importing rows using a saved CSV profile."""

    account_id: str
    profile_name: str
    rows_json: str


class CsvImportResult(BaseModel):
    """CSV import result."""

    imported: int
    skipped_duplicates: int
    errors: list[str]


def init_finance_tools(store: FinanceStore) -> None:
    """Set the Finance store used by module-level tool callables."""
    global _store
    _store = store


def build_finance_tool_specs() -> list[ToolSpec]:
    """Build bare Finance tool specs."""
    return [
        _spec(
            "spend_summary",
            "Summarise local ledger spend.",
            SpendSummaryArgs,
            SpendSummaryResult,
            spend_summary,
        ),
        _spec(
            "spend_total",
            "Total local ledger spend.",
            SpendTotalArgs,
            SpendTotalResult,
            spend_total,
        ),
        _spec(
            "transaction_list",
            "List local ledger transactions.",
            TxnListArgs,
            TxnListResult,
            transaction_list,
        ),
        _spec(
            "transaction_get",
            "Get a local ledger transaction.",
            TxnGetArgs,
            TxnResult,
            transaction_get,
        ),
        _spec(
            "transaction_add",
            "Add a local ledger transaction.",
            TxnAddArgs,
            TxnCreatedResult,
            transaction_add,
            ActionRisk.WRITE,
        ),
        _spec(
            "transaction_update",
            "Update a local ledger transaction.",
            TxnUpdateArgs,
            OkResult,
            transaction_update,
            ActionRisk.WRITE,
        ),
        _spec(
            "transaction_recategorize",
            "Recategorise a local ledger transaction.",
            TxnRecategorizeArgs,
            OkResult,
            transaction_recategorize,
            ActionRisk.WRITE,
        ),
        _spec(
            "category_list",
            "List finance categories.",
            EmptyArgs,
            CategoryListResult,
            category_list,
        ),
        _spec(
            "category_add",
            "Add a finance category.",
            CategoryAddArgs,
            CategoryCreatedResult,
            category_add,
            ActionRisk.WRITE,
        ),
        _spec(
            "account_list",
            "List finance accounts.",
            AccountListArgs,
            AccountListResult,
            account_list,
        ),
        _spec(
            "account_add",
            "Add a finance account.",
            AccountAddArgs,
            AccountCreatedResult,
            account_add,
            ActionRisk.WRITE,
        ),
        _spec(
            "csv_import",
            "Import mapped CSV rows into the local ledger.",
            CsvImportArgs,
            CsvImportResult,
            csv_import,
            ActionRisk.WRITE,
        ),
    ]


def _get_store() -> FinanceStore:
    if _store is None:
        raise RuntimeError("finance store not initialised")
    return _store


async def spend_summary(args: SpendSummaryArgs) -> SpendSummaryResult:
    rows = _get_store().spend_summary(start=args.start, end=args.end, group_by=args.group_by)
    return SpendSummaryResult(rows=rows)


async def spend_total(args: SpendTotalArgs) -> SpendTotalResult:
    total = _get_store().total_spend(start=args.start, end=args.end)
    return SpendTotalResult(total=str(total))


async def transaction_list(args: TxnListArgs) -> TxnListResult:
    transactions = _get_store().list_transactions(
        start=args.start,
        end=args.end,
        category_id=args.category_id,
        txn_type=args.txn_type,
    )
    return TxnListResult(transactions=transactions)


async def transaction_get(args: TxnGetArgs) -> TxnResult:
    return TxnResult(transaction=_get_store().get_transaction(args.id))


async def transaction_add(args: TxnAddArgs) -> TxnCreatedResult:
    transaction_id = _get_store().add_transaction(
        txn_date=args.txn_date,
        amount=Decimal(args.amount),
        merchant=args.merchant,
        category_id=args.category_id,
        txn_type=args.txn_type,
        source="manual",
        instrument_account_id=args.instrument_account_id,
    )
    return TxnCreatedResult(transaction_id=transaction_id)


async def transaction_update(args: TxnUpdateArgs) -> OkResult:
    _get_store().update_transaction(
        args.id,
        merchant=args.merchant,
        category_id=args.category_id,
        txn_type=args.txn_type,
        notes=args.notes,
        amount=Decimal(args.amount) if args.amount is not None else None,
    )
    return OkResult()


async def transaction_recategorize(args: TxnRecategorizeArgs) -> OkResult:
    _get_store().recategorize(args.id, args.category_id)
    return OkResult()


async def category_list(args: EmptyArgs) -> CategoryListResult:
    del args
    return CategoryListResult(categories=_get_store().list_categories())


async def category_add(args: CategoryAddArgs) -> CategoryCreatedResult:
    category_id = _get_store().add_category(args.name)
    return CategoryCreatedResult(category_id=category_id)


async def account_list(args: AccountListArgs) -> AccountListResult:
    return AccountListResult(
        accounts=_get_store().list_accounts(include_archived=args.include_archived)
    )


async def account_add(args: AccountAddArgs) -> AccountCreatedResult:
    account_id = _get_store().create_account(
        args.name,
        args.account_type,
        currency=args.currency,
    )
    return AccountCreatedResult(account_id=account_id)


async def csv_import(args: CsvImportArgs) -> CsvImportResult:
    profile = _get_store().get_csv_profile(args.profile_name)
    if profile is None:
        raise ValueError(f"Unknown CSV profile: {args.profile_name}")
    decoded = json.loads(args.rows_json)
    if not isinstance(decoded, list):
        raise ValueError("rows_json must decode to a list")
    rows = [cast(Mapping[str, str], row) for row in decoded if isinstance(row, Mapping)]
    result = _get_store().import_csv(rows, profile, account_id=args.account_id)
    return CsvImportResult(
        imported=result.imported,
        skipped_duplicates=result.skipped_duplicates,
        errors=result.errors,
    )


def _validated_decimal_text(value: str) -> str:
    try:
        Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("amount must be a decimal string") from exc
    return value


def _spec(
    name: str,
    description: str,
    args_schema: type[BaseModel],
    return_schema: type[BaseModel],
    callable_ref: object,
    action_risk: ActionRisk = ActionRisk.READ,
) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=description,
        args_schema=args_schema,
        return_schema=return_schema,
        callable_ref=callable_ref,
        action_risk=action_risk,
    )
