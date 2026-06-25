"""Finance summary-fact derivation and local knowledge/memory push."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Literal, Protocol
from uuid import uuid4

from artemis import paths
from artemis.config import Settings
from artemis.identity.scope import OWNER_PRIVATE
from artemis.ingest.connectors import Source
from artemis.ingest.pipeline import IngestPipeline
from artemis.memory.write_path import MemoryWriteQueue
from artemis.modules.finance.store import FinanceStore
from artemis.sensitivity import Sensitivity

logger = logging.getLogger(__name__)

FinanceFactKind = Literal["subscription", "recurring_merchant", "spending_pattern"]


class MemoryQueuePort(Protocol):
    """Small seam implemented by ``MemoryWriteQueue`` and tests."""

    def enqueue(
        self,
        text: str,
        turn_id: str,
        role: str | None = None,
        *,
        source_sensitivity: Sensitivity | None = None,
    ) -> None: ...


class IngestPipelinePort(Protocol):
    """Small seam implemented by ``IngestPipeline`` and tests."""

    async def ingest(self, source: Source) -> object: ...


@dataclass(frozen=True)
class FinanceFact:
    """Durable non-record finance fact safe for memory and knowledge indexing."""

    text: str
    kind: FinanceFactKind
    key: str


def derive_finance_facts(store: FinanceStore) -> list[FinanceFact]:
    """Derive durable summary facts from the local ledger.

    The output is summary-facts-only: active subscriptions, recurring merchants,
    and aggregate category patterns. It never includes raw transaction ids,
    one-off purchases, or exact single-record amounts.
    """
    facts: list[FinanceFact] = []
    subscription_merchants: set[str] = set()

    for subscription in store.list_subscriptions(active=True):
        merchant = _text_value(subscription.get("merchant"))
        if merchant is None:
            continue
        subscription_merchants.add(_normalise_key(merchant))
        amount = _decimal_value(subscription.get("amount"))
        cadence = _text_value(subscription.get("cadence")) or "period"
        if amount is None:
            continue
        facts.append(
            FinanceFact(
                text=f"Owner pays ~${_rounded_money(amount)}/{cadence} for {merchant}.",
                kind="subscription",
                key=f"subscription:{merchant}",
            )
        )

    for candidate in store.recurring_candidates(min_occurrences=3):
        merchant = _text_value(candidate.get("merchant"))
        if merchant is None or _normalise_key(merchant) in subscription_merchants:
            continue
        facts.append(
            FinanceFact(
                text=f"Owner regularly spends at {merchant}.",
                kind="recurring_merchant",
                key=f"merchant:{merchant}",
            )
        )

    end_date = datetime.now(UTC).date()
    start_date = end_date - timedelta(days=90)
    summaries = store.spend_summary(
        start=start_date.isoformat(),
        end=end_date.isoformat(),
        group_by="category",
    )
    category_counts = _category_counts(
        store, start=start_date.isoformat(), end=end_date.isoformat()
    )
    for row in sorted(summaries, key=_summary_total, reverse=True)[:5]:
        category = _text_value(row.get("key"))
        total = _decimal_value(row.get("total"))
        if (
            category is None
            or total is None
            or total <= Decimal("0")
            or category_counts.get(category, 0) < 2
        ):
            continue
        monthly = total / Decimal("3")
        facts.append(
            FinanceFact(
                text=(
                    f"Owner's typical monthly {category} spend is around "
                    f"${_rounded_money(monthly)}."
                ),
                kind="spending_pattern",
                key=f"pattern:{category}",
            )
        )

    return facts


async def push_finance_knowledge(
    facts: list[FinanceFact],
    *,
    ingest: IngestPipeline | IngestPipelinePort,
    memory_queue: MemoryWriteQueue | MemoryQueuePort,
    settings: Settings,
) -> int:
    """Best-effort push of sensitivity-tagged finance facts.

    Each finance fact is staged under the owner-private scope directory, pushed
    through the configured ingest pipeline, and removed afterward. Failures are
    degraded per fact without logging fact text, and no fact is ever pushed as
    general sensitivity.
    """
    staging_dir = paths.scope_dir(settings, OWNER_PRIVATE) / "ingest-staging"
    staging_dir.mkdir(parents=True, exist_ok=True)

    pushed = 0
    for fact in facts:
        staging_path = staging_dir / f"finance-{_safe_key(fact.key)}-{uuid4().hex}.txt"
        try:
            # PRIVACY: every finance fact is pushed with sensitivity="sensitive"
            # (ADR-029). The RAG-compose enforcer keeps these facts out of any
            # hosted prompt. A finance fact must NEVER be tagged "general".
            memory_queue.enqueue(
                fact.text,
                turn_id=f"finance:{fact.key}",
                source_sensitivity="sensitive",
            )
            staging_path.write_text(fact.text, encoding="utf-8")
            await ingest.ingest(Source(kind="file", uri=str(staging_path), scope=OWNER_PRIVATE))
        except Exception as exc:
            logger.warning(
                "finance knowledge push failed for kind=%s key=%s (%s)",
                fact.kind,
                fact.key,
                type(exc).__name__,
            )
            continue
        finally:
            _unlink_if_present(staging_path)
        pushed += 1
    return pushed


def _summary_total(row: dict[str, object]) -> Decimal:
    return _decimal_value(row.get("total")) or Decimal("0")


def _category_counts(store: FinanceStore, *, start: str, end: str) -> dict[str, int]:
    category_names = {
        str(category["id"]): str(category["name"])
        for category in store.list_categories()
        if category.get("id") is not None and category.get("name") is not None
    }
    counts: dict[str, int] = {}
    for transaction in store.list_transactions(start=start, end=end, limit=1000):
        txn_type = transaction.get("txn_type")
        if txn_type not in {"purchase", "refund"}:
            continue
        category_id = transaction.get("category_id")
        category = category_names.get(str(category_id), "Uncategorised")
        counts[category] = counts.get(category, 0) + 1
    return counts


def _text_value(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _decimal_value(value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _rounded_money(amount: Decimal) -> str:
    rounded = amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return f"{rounded:,}"


def _normalise_key(value: str) -> str:
    return " ".join(value.casefold().split())


def _safe_key(value: str) -> str:
    return "".join(char if char.isalnum() else "-" for char in value)[:80].strip("-") or "fact"


def _unlink_if_present(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError as exc:
        logger.warning("finance knowledge staging cleanup failed (%s)", type(exc).__name__)
