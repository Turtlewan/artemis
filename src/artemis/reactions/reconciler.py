"""Shared precision-first reconciliation primitives for reaction loops.

ADR-021 Decision 4 keeps fuzzy matching in one place: finance dedup, bill/payment
links, task/calendar links, and later reaction recipes all map their domain rows
into the frozen ``ReconcileRecord`` shape below. The auto-merge gate is deliberately
narrow: only one exact amount/date-window/merchant match can return ``EXACT``.
Ties and partials return inert ``AMBIGUOUS`` suggestions for owner review.

The link-integrity sweep is likewise domain-neutral. Callers read spoke state
through their tools or repositories and pass logical ``LinkPair`` values here;
the sweep never opens another store or performs a cross-store join.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum


class MatchOutcome(StrEnum):
    """Deterministic reconciliation outcomes."""

    EXACT = "exact"
    AMBIGUOUS = "ambiguous"
    NONE = "none"


@dataclass(frozen=True)
class MatchResult:
    """A match decision for one target record."""

    outcome: MatchOutcome
    target_id: str
    matched_id: str | None
    score: float
    reason: str


@dataclass(frozen=True)
class ReconcileRecord:
    """Common reconciliation shape used by finance and reaction recipes."""

    id: str
    amount: Decimal
    currency: str
    date: str
    merchant: str


@dataclass(frozen=True)
class EntityRef:
    """Logical spoke entity reference used by link-integrity checks."""

    module: str
    id: str


@dataclass(frozen=True)
class LinkPair:
    """A cross-module link pair assembled from spoke read surfaces."""

    kind: str
    left_ref: EntityRef | str
    right_ref: EntityRef | str | None
    deterministic: bool


@dataclass(frozen=True)
class LinkIntegrityReport:
    """Summary of one link-integrity sweep."""

    repaired: tuple[str, ...]
    flagged: tuple[str, ...]
    checked: int


_PUNCT_RE = re.compile(r"[^\w\s]", re.ASCII)
_HASH_NUMBER_RE = re.compile(r"\s+#?\d+\b")
_STORE_NUMBER_RE = re.compile(r"\b(?:store|branch|outlet)\s+\d+\b")
_SUFFIX_RE = re.compile(
    r"\b(?:pte\s+ltd|private\s+limited|ltd|limited|llc|inc|corp|co)\b",
    re.IGNORECASE,
)
_SPACE_RE = re.compile(r"\s+")


def normalize_merchant(raw: str) -> str:
    """Return a stable comparison key for deterministic merchant matching."""
    folded = raw.casefold()
    without_suffixes = _SUFFIX_RE.sub(" ", folded)
    without_store_numbers = _STORE_NUMBER_RE.sub(" ", without_suffixes)
    without_punct = _PUNCT_RE.sub(" ", without_store_numbers)
    without_digits = _HASH_NUMBER_RE.sub(" ", without_punct)
    return _SPACE_RE.sub(" ", without_digits).strip()


class Reconciler:
    """Precision-first matcher over the shared reconciliation record shape."""

    def __init__(
        self,
        *,
        date_window_days: int,
        amount_exact: bool,
        amount_tol: Decimal = Decimal("0"),
    ) -> None:
        if date_window_days < 0:
            raise ValueError("date_window_days must be at least 0")
        if amount_tol < Decimal("0"):
            raise ValueError("amount_tol must be at least 0")
        self.date_window_days = date_window_days
        self.amount_exact = amount_exact
        self.amount_tol = amount_tol

    def match(
        self,
        target: ReconcileRecord,
        candidates: Sequence[ReconcileRecord],
    ) -> MatchResult:
        """Match one target to candidates using amount, date, currency, and merchant.

        ``EXACT`` means a caller may auto-merge. ``AMBIGUOUS`` is an inert
        possible-duplicate suggestion. ``NONE`` means no candidate met the date
        and currency window with enough overlap to review.
        """
        target_date = _parse_date(target.date)
        target_merchant = normalize_merchant(target.merchant)
        in_window = [
            candidate
            for candidate in candidates
            if candidate.currency == target.currency
            and abs((_parse_date(candidate.date) - target_date).days) <= self.date_window_days
        ]
        if not in_window:
            return MatchResult(
                outcome=MatchOutcome.NONE,
                target_id=target.id,
                matched_id=None,
                score=0.0,
                reason="no candidates within date window and currency",
            )

        exact_matches = [
            candidate
            for candidate in in_window
            if self._amount_matches(target.amount, candidate.amount)
            and normalize_merchant(candidate.merchant) == target_merchant
        ]
        if len(exact_matches) == 1:
            return MatchResult(
                outcome=MatchOutcome.EXACT,
                target_id=target.id,
                matched_id=exact_matches[0].id,
                score=1.0,
                reason="single exact amount, date-window, currency, and merchant match",
            )
        if len(exact_matches) > 1:
            return MatchResult(
                outcome=MatchOutcome.AMBIGUOUS,
                target_id=target.id,
                matched_id=None,
                score=0.95,
                reason="multiple exact matches; owner review required",
            )

        maybe_partials = [
            _partial_match(target, candidate, target_merchant, self.amount_exact, self.amount_tol)
            for candidate in in_window
        ]
        partials: list[_Partial] = [partial for partial in maybe_partials if partial is not None]
        if partials:
            best = max(partials, key=lambda partial: partial.score)
            return MatchResult(
                outcome=MatchOutcome.AMBIGUOUS,
                target_id=target.id,
                matched_id=best.id,
                score=best.score,
                reason=best.reason,
            )

        return MatchResult(
            outcome=MatchOutcome.NONE,
            target_id=target.id,
            matched_id=None,
            score=0.0,
            reason="no amount or merchant overlap within date window",
        )

    def _amount_matches(self, target_amount: Decimal, candidate_amount: Decimal) -> bool:
        if self.amount_exact:
            return target_amount == candidate_amount
        return abs(target_amount - candidate_amount) <= self.amount_tol


@dataclass(frozen=True)
class _Partial:
    id: str
    score: float
    reason: str


def _partial_match(
    target: ReconcileRecord,
    candidate: ReconcileRecord,
    target_merchant: str,
    amount_exact: bool,
    amount_tol: Decimal,
) -> _Partial | None:
    amount_delta = abs(target.amount - candidate.amount)
    merchant_equal = normalize_merchant(candidate.merchant) == target_merchant
    amount_equal = target.amount == candidate.amount
    amount_within_tol = not amount_exact and amount_delta <= amount_tol

    if merchant_equal:
        return _Partial(
            id=candidate.id,
            score=0.85 if amount_equal or amount_within_tol else 0.7,
            reason="merchant matches but amount is below exact auto-merge bar",
        )
    if amount_equal:
        return _Partial(
            id=candidate.id,
            score=0.6,
            reason="amount matches but merchant differs",
        )
    if amount_within_tol:
        return _Partial(
            id=candidate.id,
            score=0.55,
            reason="amount within tolerance but merchant differs",
        )
    return None


def sweep_link_integrity(
    *,
    link_pairs: Sequence[LinkPair],
    repair_fn: Callable[[LinkPair], None],
    flag_fn: Callable[[LinkPair], None],
) -> LinkIntegrityReport:
    """Repair deterministic half-links and flag fuzzy ones for owner review."""
    repaired: list[str] = []
    flagged: list[str] = []
    for pair in link_pairs:
        if pair.right_ref is not None:
            continue
        descriptor = _link_descriptor(pair)
        if pair.deterministic:
            repair_fn(pair)
            repaired.append(descriptor)
        else:
            flag_fn(pair)
            flagged.append(descriptor)
    return LinkIntegrityReport(
        repaired=tuple(repaired),
        flagged=tuple(flagged),
        checked=len(link_pairs),
    )


def _parse_date(raw: str) -> date:
    return date.fromisoformat(raw[:10])


def _link_descriptor(pair: LinkPair) -> str:
    return f"{pair.kind}:{_ref_descriptor(pair.left_ref)}->missing"


def _ref_descriptor(ref: EntityRef | str) -> str:
    if isinstance(ref, str):
        return ref
    return f"{ref.module}:{ref.id}"
