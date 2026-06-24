"""Reciprocal Rank Fusion for deterministic rank-list merging."""

from __future__ import annotations

from collections.abc import Sequence


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[str]],
    *,
    k: int = 60,
) -> list[tuple[str, float]]:
    """Fuse ranked ids with canonical 1-based RRF ranks.

    Each id receives ``1 / (k + rank)`` per input ranking where ``rank`` starts
    at 1. Duplicate ids inside one ranking only count at their first position.
    Ties are resolved by id so output is deterministic.
    """
    if k < 1:
        raise ValueError("k must be >= 1")

    scores: dict[str, float] = {}
    for ranking in rankings:
        seen: set[str] = set()
        for index, item_id in enumerate(ranking, start=1):
            if item_id in seen:
                continue
            seen.add(item_id)
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + index)

    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))
