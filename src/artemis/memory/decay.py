"""Decay-ranked memory scoring for recall and prompt injection."""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import datetime

from artemis.memory.repository import FactRow

HALF_LIFE_DAYS = 14.0
INJECT_THRESHOLD = 0.2
TOMBSTONE_FLOOR = 0.02
RECALL_BOOST_MAX = 1.5
RECALL_DAMP_MIN = 0.3
ALPHA = 1.0
BETA = 0.1
GAMMA = 1.0


def decay_score(
    *,
    valid_from: str,
    last_access: str | None,
    access_count: int,
    salience: float,
    confidence: float,
    now: str,
    half_life_days: float = HALF_LIFE_DAYS,
) -> float:
    """Score a fact for injection by recency, salience, access, and confidence."""
    base = last_access or valid_from
    delta_days = (datetime.fromisoformat(now) - datetime.fromisoformat(base)).total_seconds()
    recency = math.exp(-(delta_days / 86400.0) / half_life_days)
    access = 1.0 + math.log1p(access_count)
    return recency * salience * access * confidence


def rank_for_inject(
    rows: Sequence[FactRow],
    *,
    now: str,
    threshold: float = INJECT_THRESHOLD,
) -> list[tuple[FactRow, float]]:
    """Return above-threshold facts sorted by descending injection score."""
    ranked = [
        (
            row,
            decay_score(
                valid_from=row.valid_from,
                last_access=row.last_access,
                access_count=row.access_count,
                salience=row.salience,
                confidence=row.confidence,
                now=now,
            ),
        )
        for row in rows
    ]
    return sorted(
        [(row, score) for row, score in ranked if score >= threshold],
        key=lambda item: item[1],
        reverse=True,
    )


def sweep_tombstone_candidates(
    rows: Sequence[FactRow],
    *,
    now: str,
    floor: float = TOMBSTONE_FLOOR,
) -> list[str]:
    """Return below-floor logical fact keys for caller-managed tombstoning.

    This is a pure maintenance helper: it computes candidates only and never
    writes to the database. Callers may tombstone returned keys; they must not
    hard-delete facts as part of a decay sweep.
    """
    return [
        row.fact_key
        for row in rows
        if decay_score(
            valid_from=row.valid_from,
            last_access=row.last_access,
            access_count=row.access_count,
            salience=row.salience,
            confidence=row.confidence,
            now=now,
        )
        < floor
    ]


def recall_multiplier(
    *,
    last_access: str | None,
    valid_from: str,
    access_count: int,
    cosine: float,
    now: str,
    half_life_days: float = HALF_LIFE_DAYS,
    alpha: float = ALPHA,
    beta: float = BETA,
    gamma: float = GAMMA,
) -> float:
    """Composite forgetting multiplier for semantic recall re-ranking."""
    base = last_access or valid_from
    delta_days = (datetime.fromisoformat(now) - datetime.fromisoformat(base)).total_seconds()
    i_score = (
        alpha * math.exp(-(delta_days / 86400.0) / half_life_days)
        + beta * access_count
        + gamma * cosine
    )
    return max(RECALL_DAMP_MIN, min(RECALL_BOOST_MAX, i_score))
