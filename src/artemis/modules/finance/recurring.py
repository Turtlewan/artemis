"""Deterministic recurring-transaction detection for the local finance ledger.

Two regular occurrences create an inert ``new_recurring`` suggestion. A third
occurrence hardens the pattern into a subscription and emits the typed domain
event. Identical amounts across different months are therefore input evidence,
not duplicate transactions.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from datetime import date, timedelta
from decimal import Decimal
from statistics import median
from typing import Literal, cast

from artemis.modules.finance.events import (
    Emit,
    _noop_emit,
    bill_recorded_event,
    subscription_detected_event,
)
from artemis.modules.finance.store import FinanceStore

Cadence = Literal["monthly", "weekly", "quarterly", "yearly"]


def detect_recurring(
    store: FinanceStore,
    *,
    min_occurrences: int,
    emit: Emit = _noop_emit,
) -> list[dict[str, object]]:
    """Scan purchase series and suggest at two occurrences, harden at three."""
    results: list[dict[str, object]] = []
    candidates = store.recurring_candidates(min_occurrences=min_occurrences)
    for candidate in candidates:
        dates = [date.fromisoformat(str(value)) for value in _object_list(candidate["dates"])]
        cadence = infer_cadence([day.isoformat() for day in dates])
        if cadence is None:
            continue

        merchant = str(candidate["merchant"])
        amount = Decimal(str(candidate["amount"]))
        latest_date = max(dates)
        next_renewal = _next_renewal(latest_date, cadence).isoformat()
        occurrences = _object_int(candidate["occurrences"])

        bill_id = _maybe_record_bill(store, candidate, merchant, amount, emit)
        if bill_id is not None:
            results.append({"kind": "bill", "id": bill_id})

        if occurrences == min_occurrences:
            suggestion_id = store.create_fin_suggestion(
                "new_recurring",
                json.dumps(
                    {
                        "merchant": merchant,
                        "amount": str(amount),
                        "cadence": cadence,
                        "occurrences": occurrences,
                        "transaction_ids": _object_list(candidate["transaction_ids"]),
                        "next_renewal": next_renewal,
                    },
                    sort_keys=True,
                ),
                raw_ref=f"recurring:{str(candidate['normalized_merchant'])}:{amount}:{cadence}",
            )
            results.append({"kind": "new_recurring", "id": suggestion_id})
            continue

        subscription_id = store.upsert_subscription(
            merchant=merchant,
            cadence=cadence,
            amount=amount,
            next_renewal=next_renewal,
            last_seen_price=amount,
            last_seen_date=latest_date.isoformat(),
        )
        emit(subscription_detected_event(subscription_id=subscription_id, merchant=merchant))
        results.append({"kind": "subscription", "id": subscription_id})
    return results


def infer_cadence(date_series: list[str]) -> Cadence | None:
    """Infer cadence from median inter-arrival days with a 25 percent tolerance."""
    if len(date_series) < 2:
        return None
    days = sorted(date.fromisoformat(value) for value in date_series)
    intervals = [(right - left).days for left, right in zip(days, days[1:], strict=False)]
    if not intervals:
        return None
    med = float(median(intervals))
    bands: dict[Cadence, tuple[float, float]] = {
        "weekly": _band(7.0),
        "monthly": (28.0, 31.0),
        "quarterly": _band(90.0),
        "yearly": _band(365.0),
    }
    for cadence, (low, high) in bands.items():
        if low <= med <= high:
            return cadence
    return None


def _maybe_record_bill(
    store: FinanceStore,
    candidate: dict[str, object],
    merchant: str,
    amount: Decimal,
    emit: Emit,
) -> str | None:
    due_date = _first_due_date(candidate)
    if due_date is None:
        return None
    bill_id = store.upsert_bill(
        payee=merchant,
        due_date=due_date,
        amount=amount,
        raw_ref=f"bill:{merchant.lower()}:{due_date}",
    )
    emit(
        bill_recorded_event(
            bill_id=bill_id,
            payee=merchant,
            due_date=due_date,
            amount=str(amount),
        )
    )
    return bill_id


def _first_due_date(candidate: dict[str, object]) -> str | None:
    due_dates = candidate.get("due_dates")
    if not isinstance(due_dates, list):
        return None
    for value in due_dates:
        if isinstance(value, str):
            return value
    return None


def _next_renewal(last_seen: date, cadence: Cadence) -> date:
    if cadence == "weekly":
        return last_seen + timedelta(days=7)
    if cadence == "monthly":
        return last_seen + timedelta(days=30)
    if cadence == "quarterly":
        return last_seen + timedelta(days=90)
    return last_seen + timedelta(days=365)


def _band(days: float) -> tuple[float, float]:
    return (days * 0.75, days * 1.25)


def _object_list(value: object) -> list[object]:
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes)):
        raise ValueError("candidate value must be a list")
    return list(cast(Iterable[object], value))


def _object_int(value: object) -> int:
    if isinstance(value, (str, int)):
        return int(value)
    raise ValueError("candidate occurrence count must be integer-like")


_DUE_RE = re.compile(r"\bdue[:= ](?P<date>\d{4}-\d{2}-\d{2})\b", re.IGNORECASE)


def due_date_from_notes(notes: object) -> str | None:
    """Extract a normalized due date from deterministic FIN-b bill phrasing."""
    if not isinstance(notes, str):
        return None
    match = _DUE_RE.search(notes)
    return match.group("date") if match is not None else None
