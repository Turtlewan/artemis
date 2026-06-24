"""Retrieval helpers and adaptive retriever implementation."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from artemis.retrieval.retriever import AdaptiveRetriever, GraphModeNotImplemented
    from artemis.retrieval.rrf import reciprocal_rank_fusion

__all__ = [
    "AdaptiveRetriever",
    "GraphModeNotImplemented",
    "reciprocal_rank_fusion",
]


def __getattr__(name: str) -> object:
    """Lazily re-export retrieval helpers without adapter import cycles."""
    if name == "reciprocal_rank_fusion":
        from artemis.retrieval.rrf import reciprocal_rank_fusion

        return reciprocal_rank_fusion
    if name in {"AdaptiveRetriever", "GraphModeNotImplemented"}:
        from artemis.retrieval.retriever import AdaptiveRetriever, GraphModeNotImplemented

        return {
            "AdaptiveRetriever": AdaptiveRetriever,
            "GraphModeNotImplemented": GraphModeNotImplemented,
        }[name]
    raise AttributeError(name)
