"""Tier-1 proactive hooks for local finance awareness.

Hook payloads are deliberately narrow: counts, ids, scalar totals, and no raw
transaction text or per-transaction amounts beyond unusual transaction ids.
"""

from __future__ import annotations

import datetime
import logging
from collections.abc import Callable
from decimal import Decimal

from artemis.manifest import HookSpec
from artemis.modules.finance.reconcile import unusual_spend
from artemis.modules.finance.store import FinanceStore
from artemis.proactive.hit_handler import TemplateRegistry
from artemis.proactive.hook_types import HookResult
from artemis.runtime_config import get_runtime_config

logger = logging.getLogger(__name__)


def make_renewal_check(store: FinanceStore, *, days: int = 7) -> Callable[[], HookResult]:
    """Return subscriptions renewing soon, including price-increase count."""

    def check() -> HookResult:
        try:
            today = _today()
            until = today + datetime.timedelta(days=days)
            subscriptions = [
                row
                for row in store.list_subscriptions(active=True)
                if row.get("next_renewal") is not None
                and today <= datetime.date.fromisoformat(str(row["next_renewal"])) <= until
            ]
            if not subscriptions:
                return HookResult.miss()
            price_increases = [
                row
                for row in subscriptions
                if row.get("last_seen_price") is not None
                and Decimal(str(row["last_seen_price"])) > Decimal(str(row["amount"]))
            ]
            return HookResult.of(
                {
                    "renewing_count": len(subscriptions),
                    "price_increase_count": len(price_increases),
                    "subscription_ids": [str(row["id"]) for row in subscriptions],
                },
                dedup_value=today.isoformat(),
            )
        except Exception:
            logger.warning("finance renewal check failed", exc_info=True)
            return HookResult.miss()

    return check


def make_new_recurring_check(store: FinanceStore) -> Callable[[], HookResult]:
    """Return pending two-occurrence recurring suggestions."""

    def check() -> HookResult:
        try:
            suggestions = [
                row
                for row in store.list_fin_suggestions(status="pending")
                if row.get("kind") == "new_recurring"
            ]
            if not suggestions:
                return HookResult.miss()
            return HookResult.of(
                {
                    "new_recurring_count": len(suggestions),
                    "suggestion_ids": [str(row["id"]) for row in suggestions],
                },
                dedup_value=_today().isoformat(),
            )
        except Exception:
            logger.warning("finance new recurring check failed", exc_info=True)
            return HookResult.miss()

    return check


def make_bill_due_check(store: FinanceStore, *, days: int = 7) -> Callable[[], HookResult]:
    """Return open bills due soon. This hook never pays bills."""

    def check() -> HookResult:
        try:
            today = _today()
            until = today + datetime.timedelta(days=days)
            bills = [
                row
                for row in store.list_bills(status="open")
                if today <= datetime.date.fromisoformat(str(row["due_date"])) <= until
            ]
            if not bills:
                return HookResult.miss()
            return HookResult.of(
                {"due_count": len(bills), "bill_ids": [str(row["id"]) for row in bills]},
                dedup_value=today.isoformat(),
            )
        except Exception:
            logger.warning("finance bill due check failed", exc_info=True)
            return HookResult.miss()

    return check


def make_spending_summary_check(store: FinanceStore) -> Callable[[], HookResult]:
    """Return a periodic spend digest payload with unusual-spend ids."""
    cfg = get_runtime_config().finance

    def check() -> HookResult:
        try:
            today = _today()
            start = today - datetime.timedelta(days=7)
            total = store.total_spend(
                start=start.isoformat(), end=(today + datetime.timedelta(days=1)).isoformat()
            )
            summary = store.spend_summary(
                start=start.isoformat(),
                end=(today + datetime.timedelta(days=1)).isoformat(),
                group_by="category",
            )
            flags = unusual_spend(store, sigma=cfg.unusual_spend_sigma)
            if total == 0 and not flags:
                return HookResult.miss()
            top_category = ""
            if summary:
                top = max(summary, key=lambda row: Decimal(str(row["total"])))
                top_category = str(top["key"])
            return HookResult.of(
                {
                    "period_total": str(total),
                    "top_category": top_category,
                    "unusual_count": len(flags),
                    "unusual_txn_ids": [str(row["txn_id"]) for row in flags],
                },
                dedup_value=f"{today.isocalendar().year}-W{today.isocalendar().week:02d}",
            )
        except Exception:
            logger.warning("finance spending summary check failed", exc_info=True)
            return HookResult.miss()

    return check


def build_finance_hooks(store: FinanceStore) -> list[HookSpec]:
    """Build the four owner-private Tier-1 finance hooks."""
    return [
        HookSpec(
            name="finance_renewal",
            cron="0 8 * * *",
            tier=1,
            urgency="normal",
            needs_llm=False,
            dedup_key="finance_renewal",
            check_ref=make_renewal_check(store),
        ),
        HookSpec(
            name="finance_new_recurring",
            interval_seconds=6 * 60 * 60,
            tier=1,
            urgency="normal",
            needs_llm=False,
            dedup_key="finance_new_recurring",
            check_ref=make_new_recurring_check(store),
        ),
        HookSpec(
            name="finance_bill_due",
            cron="0 8 * * *",
            tier=1,
            urgency="normal",
            needs_llm=False,
            dedup_key="finance_bill_due",
            check_ref=make_bill_due_check(store),
        ),
        HookSpec(
            name="finance_spending_summary",
            interval_seconds=7 * 24 * 60 * 60,
            tier=1,
            urgency="low",
            needs_llm=True,
            dedup_key="finance_spending_summary",
            check_ref=make_spending_summary_check(store),
        ),
    ]


def register_finance_templates(registry: TemplateRegistry) -> None:
    """Register deterministic templates for the three LLM-free finance hooks."""
    registry.register(
        "finance.finance_renewal",
        lambda result: f"{result.payload.get('renewing_count', 0)} renewals soon",
    )
    registry.register(
        "finance.finance_new_recurring",
        lambda result: (
            f"{result.payload.get('new_recurring_count', 0)} recurring patterns need review"
        ),
    )
    registry.register(
        "finance.finance_bill_due",
        lambda result: f"{result.payload.get('due_count', 0)} bills due soon",
    )


def _today() -> datetime.date:
    return datetime.datetime.now(datetime.UTC).date()
