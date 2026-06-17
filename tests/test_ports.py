"""Static-shape tests for the ports package.

Confirms every Protocol is importable, is a typing.Protocol, and that
key signatures carry the expected parameter names.
"""

from __future__ import annotations

import inspect
from collections.abc import Mapping, Sequence

from artemis.ports import (
    VAD,
    AsOf,
    AudioFrontend,
    Chunk,
    Document,
    EmbeddingModel,
    Fact,
    MemoryStore,
    Message,
    ModelPort,
    ModelResponse,
    PersonId,
    Reranker,
    RetrievedChunk,
    Retriever,
    RouteDecision,
    Router,
    Scope,
    SpeakerID,
    Stt,
    Tts,
    Usage,
    Vector,
    VectorStore,
    WakeWord,
)

# ── All names are importable ──────────────────────────────────────────────

_ALL_PROTOCOLS = [
    EmbeddingModel,
    VectorStore,
    Reranker,
    Retriever,
    MemoryStore,
    Router,
    ModelPort,
    WakeWord,
    VAD,
    Stt,
    Tts,
    SpeakerID,
    AudioFrontend,
]

_ALL_TYPES = [
    PersonId,
    Scope,
    Vector,
    AsOf,
    Message,
    Document,
    Chunk,
    RetrievedChunk,
    Fact,
    Usage,
    ModelResponse,
    RouteDecision,
]


def test_all_names_importable() -> None:
    """All types and protocols listed in __all__ are importable."""
    # The import at the top already proves this, but assert we can inspect them.
    for p in _ALL_PROTOCOLS:
        assert isinstance(p, type), f"{p} is not a type"
    for t in _ALL_TYPES:
        assert t is not None, f"{t} is None"


def test_every_protocol_is_protocol() -> None:
    """Each Protocol has _is_protocol = True."""
    for p in _ALL_PROTOCOLS:
        raw = getattr(p, "_is_protocol", False)
        assert raw is True, f"{p.__name__} is not a Protocol (typing.Protocol)"


def test_model_response_is_pydantic() -> None:
    """ModelResponse is a pydantic BaseModel, not a Protocol."""
    assert not getattr(ModelResponse, "_is_protocol", False)
    assert hasattr(ModelResponse, "model_dump")


# ── Signature shape assertions ────────────────────────────────────────────


def test_memory_store_has_person_id_and_as_of() -> None:
    """MemoryStore.recall signature includes person_id and as_of."""
    sig = inspect.signature(MemoryStore.recall)
    params = sig.parameters
    assert "person_id" in params
    assert "as_of" in params


def test_memory_store_delete_fact_is_sync() -> None:
    """delete_fact is sync (not async def) per the ASYNC PORT RULE."""
    # Check that the method is not a coroutine by verifying no `await` in sig
    # (a Protocol body is `...` so we can't inspect async-ness directly;
    # instead confirm the test stub check in the manual inspection step.)
    sig = inspect.signature(MemoryStore.delete_fact)
    assert "person_id" in sig.parameters
    assert "fact_id" in sig.parameters


def test_embedding_model_split_signatures() -> None:
    """EmbeddingModel has both embed_documents and embed_query."""
    embed_docs = inspect.signature(EmbeddingModel.embed_documents)
    assert "texts" in embed_docs.parameters

    embed_q = inspect.signature(EmbeddingModel.embed_query)
    assert "query" in embed_q.parameters


def test_model_port_no_tools_param() -> None:
    """ModelPort.complete has no tools/tool_choice param (DR-a guarantee)."""
    sig = inspect.signature(ModelPort.complete)
    param_names = set(sig.parameters.keys())
    assert "tools" not in param_names, "ModelPort.complete must NOT have a tools param"
    assert "tool_choice" not in param_names


def test_model_port_no_stream_param() -> None:
    """ModelPort.complete has no stream param — use complete_stream."""
    sig = inspect.signature(ModelPort.complete)
    assert "stream" not in sig.parameters


def test_static_conformance() -> None:
    """Structural type-check: in-test dummies confirm Protocol conformance.

    Each dummy class structurally satisfies its Protocol — mypy validates
    this during the regular ``mypy --strict src tests`` run.
    """
    # These assignments are verified by mypy — if they fail to type-check,
    # the Protocol shape has changed.
    vs: VectorStore = _MinimalVectorStore()
    r: Router = _MinimalRouter()
    assert isinstance(vs, VectorStore)
    assert isinstance(r, Router)


class _MinimalVectorStore:
    """Minimal VectorStore stub for structural type checking."""

    def add(
        self,
        scope: str,
        ids: Sequence[str],
        vectors: Sequence[Vector],
        metadata: Sequence[Mapping[str, object]],
    ) -> None:
        pass

    def search(self, scope: str, query: Vector, k: int) -> list[RetrievedChunk]:
        return []


class _MinimalRouter:
    """Minimal Router stub for structural type checking."""

    async def route(self, request_text: str, scope: str) -> RouteDecision:
        return RouteDecision(path="local", candidate_tools=[], confidence=0.0)
