"""Precision-first finance reconciliation and unusual-spend flags.

L0 raw-ref idempotency lives in ``add_transaction``. FIN-c implements L1/L2
high-confidence merge, L3 inert duplicate suggestions, and a statistical
outlier flag. The L4 recipe-learning loop is referenced by suggestions; the
recipe system owns durable rule creation.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date
from decimal import Decimal
from statistics import mean, stdev

from artemis.modules.finance.schema import TransactionSource, TransactionType
from artemis.modules.finance.store import FinanceStore


def reconcile(store: FinanceStore, *, date_window_days: int, amount_exact: bool) -> dict[str, int]:
    """Run the L1-L3 reconciliation ladder over local transactions."""
    transactions = store.list_transactions(limit=10_000)
    auto_merged = 0
    suggested = 0
    reconciled = 0
    removed: set[str] = set()

    for left_index, left in enumerate(transactions):
        left_id = str(left["id"])
        if left_id in removed:
            continue
        for right in transactions[left_index + 1 :]:
            right_id = str(right["id"])
            if right_id in removed or left_id == right_id:
                continue
            if not _same_base_event(left, right, date_window_days):
                continue
            if str(left["source"]) == str(right["source"]):
                continue

            exact_amount = Decimal(str(left["amount"])) == Decimal(str(right["amount"]))
            amount_matches = exact_amount or (
                not amount_exact and _within_one_percent(left["amount"], right["amount"])
            )
            if amount_matches and _high_confidence(left) and _high_confidence(right):
                keep_id, drop_id = _merge_order(left, right)
                store.merge_transactions(keep_id, drop_id)
                removed.add(drop_id)
                auto_merged += 1
                if _is_csv_pair(left, right):
                    reconciled += 1
                break

            if _ambiguous_duplicate(left, right, exact_amount):
                store.create_fin_suggestion(
                    "possible_duplicate",
                    json.dumps(
                        {
                            "keep_id": left_id,
                            "drop_id": right_id,
                            "reason": "below auto-merge confidence bar",
                            "l4_reference": "owner decisions may later train a recipe",
                        },
                        sort_keys=True,
                    ),
                    raw_ref=f"possible-duplicate:{left_id}:{right_id}",
                )
                suggested += 1

    return {"auto_merged": auto_merged, "suggested_duplicates": suggested, "reconciled": reconciled}


def unusual_spend(store: FinanceStore, *, sigma: float) -> list[dict[str, object]]:
    """Flag purchase outliers above mean + sigma*stdev with at least four prior rows."""
    transactions = sorted(
        (
            row
            for row in store.list_transactions(
                txn_type=TransactionType.PURCHASE.value, limit=10_000
            )
            if row.get("merchant") is not None
        ),
        key=lambda row: (str(row["txn_date"]), str(row["id"])),
    )
    history: dict[tuple[str, str | None], list[Decimal]] = defaultdict(list)
    flagged: list[dict[str, object]] = []
    for row in transactions:
        merchant = _normalize_merchant(row.get("merchant"))
        category_id = str(row["category_id"]) if row.get("category_id") is not None else None
        key = (merchant, category_id)
        prior = history[key]
        amount = Decimal(str(row["amount"]))
        store.merchant_amount_history(merchant=str(row["merchant"]), category_id=category_id)
        if len(prior) >= 4:
            avg = mean(prior)
            spread = stdev(prior)
            threshold = avg + (Decimal(str(sigma)) * spread)
            if spread > 0 and amount > threshold:
                z_score = (amount - avg) / spread
                flagged.append({"txn_id": str(row["id"]), "z_score": float(z_score)})
        prior.append(amount)
    return flagged


def _same_base_event(
    left: dict[str, object],
    right: dict[str, object],
    date_window_days: int,
) -> bool:
    if str(left["currency"]) != str(right["currency"]):
        return False
    if _normalize_merchant(left.get("merchant")) != _normalize_merchant(right.get("merchant")):
        return False
    left_date = date.fromisoformat(str(left["txn_date"]))
    right_date = date.fromisoformat(str(right["txn_date"]))
    return abs((left_date - right_date).days) <= date_window_days


def _within_one_percent(left: object, right: object) -> bool:
    left_amount = Decimal(str(left))
    right_amount = Decimal(str(right))
    higher = max(abs(left_amount), abs(right_amount))
    if higher == 0:
        return True
    return abs(left_amount - right_amount) <= higher * Decimal("0.01")


def _high_confidence(row: dict[str, object]) -> bool:
    value = row.get("confidence")
    if value is None:
        return False
    if isinstance(value, (str, int, float)):
        return float(value) >= 0.9
    return False


def _merge_order(left: dict[str, object], right: dict[str, object]) -> tuple[str, str]:
    left_rank = _source_rank(str(left["source"]))
    right_rank = _source_rank(str(right["source"]))
    if right_rank > left_rank:
        return str(right["id"]), str(left["id"])
    return str(left["id"]), str(right["id"])


def _source_rank(source: str) -> int:
    if source == TransactionSource.CSV.value:
        return 3
    if source == "receipt":
        return 2
    return 1


def _is_csv_pair(left: dict[str, object], right: dict[str, object]) -> bool:
    sources = {str(left["source"]), str(right["source"])}
    return TransactionSource.CSV.value in sources and TransactionSource.EMAIL.value in sources


def _ambiguous_duplicate(
    left: dict[str, object], right: dict[str, object], exact_amount: bool
) -> bool:
    return not exact_amount or not (_high_confidence(left) and _high_confidence(right))


def _normalize_merchant(value: object) -> str:
    if value is None:
        return ""
    return " ".join(str(value).casefold().split())
