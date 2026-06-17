"""Retrieval ports: Retriever, VectorStore, Reranker, EmbeddingModel.

ASYNC PORT RULE (ADR-015): network-I/O methods are ``async def``;
local-disk / cached / sync operations stay sync.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol, runtime_checkable

from artemis.ports.types import RetrievedChunk, Scope, Vector


@runtime_checkable
class EmbeddingModel(Protocol):
    """Text embedding model.

    - ``embed_documents``: stores the returned vectors (no instruction prefix).
    - ``embed_query``: returns a single query vector (the adapter applies
      the model's query instruction prefix).
    - ``dimension``: read-only cached dimension (sync).
    """

    async def embed_documents(self, texts: Sequence[str]) -> list[Vector]:
        """Embed texts for storage — NO instruction prefix (sync-cached)."""
        ...

    async def embed_query(self, query: str) -> Vector:
        """Embed a single search query — adapter applies the query prefix."""
        ...

    @property
    def dimension(self) -> int:
        """Embedding dimension, locked in the store schema."""
        ...


@runtime_checkable
class VectorStore(Protocol):
    """Local-disk vector store (sync — LanceDB / in-memory)."""

    def add(
        self,
        scope: Scope,
        ids: Sequence[str],
        vectors: Sequence[Vector],
        metadata: Sequence[Mapping[str, object]],
    ) -> None:
        """Store vectors under the given scope and ids."""
        ...

    def search(self, scope: Scope, query: Vector, k: int) -> list[RetrievedChunk]:
        """Search for the top-k nearest neighbours within a scope."""
        ...


@runtime_checkable
class Reranker(Protocol):
    """Cross-encoder reranker (network I/O → async)."""

    async def rerank(
        self,
        query: str,
        chunks: Sequence[RetrievedChunk],
        top_k: int,
    ) -> list[RetrievedChunk]:
        """Rerank chunks by relevance to the query."""
        ...


@runtime_checkable
class Retriever(Protocol):
    """High-level document retriever (network I/O → async)."""

    async def retrieve(
        self,
        query: str,
        scope: Scope,
        mode: str = "hybrid",
        k: int = 10,
    ) -> list[RetrievedChunk]:
        """Retrieve the top-k chunks for a query within a scope."""
        ...
