"""Off-hardware tests for adaptive retrieval."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from pathlib import Path

import pytest

from artemis.adapters.lancedb_store import LanceDBVectorStore
from artemis.adapters.reranker import FakeReranker, QwenReranker
from artemis.config import Settings
from artemis.identity.key_provider import ScopeLockedError
from artemis.ports.model import ModelResponse
from artemis.ports.retrieval import Reranker, Retriever
from artemis.ports.types import Chunk, Message, RetrievedChunk, Scope, Vector
from artemis.retrieval.retriever import AdaptiveRetriever, GraphModeNotImplemented
from artemis.retrieval.rrf import reciprocal_rank_fusion


class FakeEmbedder:
    """Deterministic fixed-width embedder."""

    def __init__(self, dimension: int = 8) -> None:
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed_documents(self, texts: Sequence[str]) -> list[Vector]:
        return [self._vector(text) for text in texts]

    async def embed_query(self, query: str) -> Vector:
        return self._vector(query)

    def _vector(self, text: str) -> Vector:
        values = [0.0 for _ in range(self._dimension)]
        for index, byte in enumerate(text.encode("utf-8")):
            values[index % self._dimension] += float(byte)
        norm = sum(value * value for value in values) ** 0.5 or 1.0
        return [value / norm for value in values]


class DeterministicQwenReranker(QwenReranker):
    """QwenReranker with the transport seam replaced for tests."""

    async def _score(self, query: str, texts: Sequence[str]) -> list[float]:
        _ = query
        return [1.0 if "known relevant" in text else 0.1 for text in texts]


class FakeModelPort:
    """ModelPort double for constructing QwenReranker without network."""

    async def complete(
        self,
        *,
        role: str,
        messages: Sequence[Message],
        response_schema: dict[str, object] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        _ = role, messages, response_schema, temperature, max_tokens
        return ModelResponse(text='{"scores":[1.0]}')

    def complete_stream(
        self,
        *,
        role: str,
        messages: Sequence[Message],
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        _ = role, messages, temperature

        async def _stream() -> AsyncIterator[str]:
            if False:
                yield ""

        return _stream()

    async def embed(self, role: str, texts: Sequence[str]) -> list[Vector]:
        _ = role
        return [[0.0] for _text in texts]


def _settings(tmp_path: Path) -> Settings:
    return Settings(data_root=tmp_path, slot="dev")


def _store(
    tmp_path: Path,
    *,
    scope: Scope = "owner-private",
    unlocked: bool = True,
) -> LanceDBVectorStore:
    return LanceDBVectorStore(
        scope,
        _settings(tmp_path),
        embedder_model_id="fake-embedder",
        dimension=8,
        is_unlocked=lambda: unlocked,
    )


async def _seed_store(store: LanceDBVectorStore, embedder: FakeEmbedder) -> None:
    texts = [
        "known relevant passage about alpha launch details",
        "unrelated budget planning note",
        "alpha appendix without matching phrase",
    ]
    vectors = await embedder.embed_documents(texts)
    store.add(
        "owner-private",
        ["c-known", "c-budget", "c-alpha"],
        vectors,
        [
            {
                "text": texts[0],
                "document_id": "doc-known",
                "content_hash": "hash-known",
                "source_id": "file://known.md",
                "page": 1,
                "char_start": 0,
                "char_end": len(texts[0]),
            },
            {
                "text": texts[1],
                "document_id": "doc-budget",
                "content_hash": "hash-budget",
                "source_id": "file://budget.md",
                "page": 1,
                "char_start": 0,
                "char_end": len(texts[1]),
            },
            {
                "text": texts[2],
                "document_id": "doc-alpha",
                "content_hash": "hash-alpha",
                "source_id": "file://alpha.md",
                "page": 1,
                "char_start": 0,
                "char_end": len(texts[2]),
            },
        ],
    )


def test_rrf_favors_repeated_high_ranks() -> None:
    fused = reciprocal_rank_fusion([["shared", "single"], ["other", "shared"]], k=60)

    assert fused.index(next(item for item in fused if item[0] == "shared")) < fused.index(
        next(item for item in fused if item[0] == "single")
    )
    assert fused == reciprocal_rank_fusion([["shared", "single"], ["other", "shared"]], k=60)


@pytest.mark.asyncio
async def test_qwen_reranker_uses_score_seam() -> None:
    chunks = [
        RetrievedChunk(Chunk("c1", "d1", "noise", "owner-private"), score=0.0),
        RetrievedChunk(
            Chunk("c2", "d2", "known relevant evidence", "owner-private"),
            score=0.0,
        ),
    ]
    reranker = DeterministicQwenReranker(Settings(), model=FakeModelPort())
    _check: Reranker = reranker

    ranked = await reranker.rerank("known query", chunks, top_k=1)

    assert _check is reranker
    assert ranked[0].chunk.chunk_id == "c2"
    assert ranked[0].score == 1.0


@pytest.mark.asyncio
async def test_hybrid_search_returns_provenance(tmp_path: Path) -> None:
    embedder = FakeEmbedder()
    store = _store(tmp_path)
    await _seed_store(store, embedder)

    results = store.hybrid_search(
        "owner-private",
        await embedder.embed_query("known relevant alpha"),
        "known relevant alpha",
        2,
    )

    assert len(results) <= 2
    assert {result.chunk.document_id for result in results}
    assert {result.chunk.scope for result in results} == {"owner-private"}


@pytest.mark.asyncio
async def test_retriever_default_hybrid_reranks_known_chunk_first(tmp_path: Path) -> None:
    embedder = FakeEmbedder()
    store = _store(tmp_path)
    await _seed_store(store, embedder)
    retriever = AdaptiveRetriever(
        embedder,
        lambda _scope: store,
        FakeReranker(),
        candidate_k=5,
    )
    _check: Retriever = retriever

    results = await _check.retrieve("known relevant alpha", "owner-private", k=3)

    assert results[0].chunk.chunk_id == "c-known"
    assert results[0].chunk.document_id == "doc-known"
    assert results[0].chunk.scope == "owner-private"


@pytest.mark.asyncio
async def test_mode_routing_agentic_and_graph(tmp_path: Path) -> None:
    embedder = FakeEmbedder()
    store = _store(tmp_path)
    await _seed_store(store, embedder)
    delegated = [RetrievedChunk(Chunk("agentic", "doc", "delegated", "owner-private"), 9.0)]

    async def agentic_fn(query: str, scope: Scope, k: int) -> list[RetrievedChunk]:
        assert query == "known relevant alpha"
        assert scope == "owner-private"
        assert k == 1
        return delegated

    retriever = AdaptiveRetriever(
        embedder,
        lambda _scope: store,
        FakeReranker(),
        agentic_fn=agentic_fn,
    )

    with pytest.raises(GraphModeNotImplemented):
        await retriever.retrieve("known relevant alpha", "owner-private", mode="graph", k=1)

    assert (
        await retriever.retrieve("known relevant alpha", "owner-private", mode="agentic", k=1)
    ) == delegated


@pytest.mark.asyncio
async def test_agentic_without_delegate_degrades_to_hybrid(tmp_path: Path) -> None:
    embedder = FakeEmbedder()
    store = _store(tmp_path)
    await _seed_store(store, embedder)
    retriever = AdaptiveRetriever(embedder, lambda _scope: store, FakeReranker(), candidate_k=5)

    results = await retriever.retrieve("known relevant alpha", "owner-private", mode="agentic", k=1)

    assert results[0].chunk.chunk_id == "c-known"


@pytest.mark.asyncio
async def test_scope_locked_error_propagates(tmp_path: Path) -> None:
    embedder = FakeEmbedder()

    def locked_store_for(scope: Scope) -> LanceDBVectorStore:
        return _store(tmp_path, scope=scope, unlocked=False)

    retriever = AdaptiveRetriever(embedder, locked_store_for, FakeReranker())

    with pytest.raises(ScopeLockedError):
        await retriever.retrieve("known relevant alpha", "owner-private")


def test_agentic_fn_type_alias() -> None:
    async def agentic_fn(query: str, scope: Scope, k: int) -> list[RetrievedChunk]:
        _ = query, scope, k
        return []

    typed: Callable[[str, Scope, int], Awaitable[list[RetrievedChunk]]] = agentic_fn
    assert typed is agentic_fn
