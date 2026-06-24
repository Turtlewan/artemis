"""Adaptive retriever: hybrid search, rerank, and mode dispatch."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from artemis.adapters.lancedb_store import LanceDBVectorStore
from artemis.ports.retrieval import EmbeddingModel, Reranker
from artemis.ports.types import Mode, RetrievedChunk, Scope

AgenticRetrieveFn = Callable[[str, Scope, int], Awaitable[list[RetrievedChunk]]]


class GraphModeNotImplemented(NotImplementedError):  # noqa: N818 - spec names this seam.
    """Raised for the deferred ADR-007 graph retrieval seam."""


class AdaptiveRetriever:
    """Retriever port implementation with hybrid default and mode seam."""

    def __init__(
        self,
        embedder: EmbeddingModel,
        store_for: Callable[[Scope], LanceDBVectorStore],
        reranker: Reranker,
        *,
        agentic_fn: AgenticRetrieveFn | None = None,
        candidate_k: int = 30,
    ) -> None:
        if candidate_k < 1:
            raise ValueError("candidate_k must be >= 1")
        self._embedder = embedder
        self._store_for = store_for
        self._reranker = reranker
        self._agentic_fn = agentic_fn
        self._candidate_k = candidate_k

    async def retrieve(
        self,
        query: str,
        scope: Scope,
        mode: Mode = "hybrid",
        k: int = 10,
    ) -> list[RetrievedChunk]:
        """Retrieve chunks for ``query`` using hybrid, agentic, or graph mode."""
        if mode == "graph":
            raise GraphModeNotImplemented(
                "graph mode is deferred per ADR-007; use hybrid or agentic"
            )
        if mode == "agentic" and self._agentic_fn is not None:
            return await self._agentic_fn(query, scope, k)

        if k <= 0:
            return []
        query_vector = await self._embedder.embed_query(query)
        store = self._store_for(scope)
        candidates = store.hybrid_search(scope, query_vector, query, self._candidate_k)
        return await self._reranker.rerank(query, candidates, top_k=k)
