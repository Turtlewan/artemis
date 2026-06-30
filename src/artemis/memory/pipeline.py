"""Pure retrieval pipeline helpers."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from typing import Protocol

from artemis.types import MemoryItem, RetrievedContext


class Reranker(Protocol):
    def __call__(self, query: str, items: Sequence[MemoryItem]) -> list[MemoryItem]:
        """Return items reordered most-relevant-first."""
        ...


def identity_reranker(query: str, items: Sequence[MemoryItem]) -> list[MemoryItem]:
    return list(items)


_WORD = re.compile(r"\w+")


def _tokens(text: str) -> set[str]:
    return {word.lower() for word in _WORD.findall(text)}


def lexical_similarity(a: str, b: str) -> float:
    """Jaccard token overlap in [0, 1]."""
    left = _tokens(a)
    right = _tokens(b)
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def mmr_select(
    items: Sequence[MemoryItem],
    *,
    k: int,
    mmr_lambda: float = 0.7,
    similarity: Callable[[str, str], float] = lexical_similarity,
) -> list[MemoryItem]:
    """Select items using input order as the relevance ranking."""
    pool = list(items)
    selected: list[MemoryItem] = []
    ranks = {id(item): rank for rank, item in enumerate(items)}
    item_count = max(1, len(items))

    while pool and len(selected) < k:
        best_i = 0
        best_score = float("-inf")
        for i, candidate in enumerate(pool):
            relevance = 1.0 - (ranks[id(candidate)] / item_count)
            diversity_penalty = max(
                (similarity(candidate.content, item.content) for item in selected),
                default=0.0,
            )
            score = mmr_lambda * relevance - (1 - mmr_lambda) * diversity_penalty
            if score > best_score:
                best_i = i
                best_score = score
        selected.append(pool.pop(best_i))

    return selected


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def assemble(items: Sequence[MemoryItem], *, token_budget: int) -> RetrievedContext:
    kept: list[MemoryItem] = []
    token_cost = 0
    truncated = False

    for item in items:
        item_cost = estimate_tokens(item.content)
        if token_cost + item_cost > token_budget:
            truncated = True
            continue
        kept.append(item)
        token_cost += item_cost

    return RetrievedContext(items=kept, token_cost=token_cost, truncated=truncated)


def run_pipeline(
    query: str,
    candidates: Sequence[MemoryItem],
    *,
    token_budget: int,
    mmr_lambda: float = 0.7,
    k: int = 20,
    reranker: Reranker = identity_reranker,
) -> RetrievedContext:
    ranked = reranker(query, candidates)
    deduped = mmr_select(ranked, k=k, mmr_lambda=mmr_lambda)
    return assemble(deduped, token_budget=token_budget)
