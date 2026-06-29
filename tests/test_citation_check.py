from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import cast

import pytest

from artemis.brain import Brain
from artemis.ports.model import ModelResponse
from artemis.ports.routing import RouteDecision
from artemis.ports.types import Chunk, Fact, Message, RetrievedChunk, Scope, Vector
from artemis.registry import ToolRegistry
from artemis.router import SemanticRouter
from artemis.sensitivity import Sensitivity, SensitivityEnforcer
from artemis.untrusted.citation_check import (
    CITE_INSTRUCTION,
    MATERIAL_GAP_NOTICE,
    audit_answer,
)
from artemis.untrusted.spotlight import SPOTLIGHT_INSTRUCTION


class FakeEmbedder:
    @property
    def dimension(self) -> int:
        return 4

    async def embed_documents(self, texts: Sequence[str]) -> list[Vector]:
        return [[1.0, 0.0, 0.0, 0.0] for _ in texts]

    async def embed_query(self, query: str) -> Vector:
        return [1.0, 0.0, 0.0, 0.0]


class FakeRouter:
    async def route(self, request_text: str, scope: Scope) -> RouteDecision:
        del request_text, scope
        return RouteDecision(path="local", candidate_tools=[], confidence=0.5)


class FakeSensitivityClassifier:
    async def classify(self, request_text: str) -> Sensitivity:
        del request_text
        return "general"


class FakeModelPort:
    def __init__(self, text: str) -> None:
        self.text = text
        self.complete_messages: list[list[Message]] = []

    async def complete(
        self,
        *,
        role: str,
        messages: Sequence[Message],
        response_schema: dict[str, object] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        del role, response_schema, temperature, max_tokens
        self.complete_messages.append(list(messages))
        return ModelResponse(text=self.text)

    def complete_stream(
        self,
        *,
        role: str,
        messages: Sequence[Message],
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        del role, messages, temperature

        async def _stream() -> AsyncIterator[str]:
            yield self.text

        return _stream()

    async def embed(self, role: str, texts: Sequence[str]) -> list[Vector]:
        del role
        return [[0.0] for _ in texts]


def test_empty_retrieval_audits_material_gap() -> None:
    report = audit_answer("anything", (), ())

    assert report.material_gap is True
    assert MATERIAL_GAP_NOTICE in report.notices()


def test_hallucinated_citation_is_flagged_and_gap_sentinel_is_ignored() -> None:
    chunk = _chunk("c1", "grounded evidence")

    report = audit_answer("Claim [c1]. Other [c2]. Gap [MATERIAL GAP].", (chunk,), ())

    assert report.material_gap is False
    assert report.invalid_citations == ("c2",)


def test_clean_cited_answer_has_no_notices() -> None:
    chunk = _chunk("c1", "grounded evidence")

    report = audit_answer("Claim [c1].", (chunk,), ())

    assert report.material_gap is False
    assert report.invalid_citations == ()
    assert report.notices() == []


def test_rag_messages_forces_material_gap_system_message() -> None:
    messages = _brain(FakeModelPort("unused"))._rag_messages("q", (), ())

    assert messages[0].role == "system"
    assert MATERIAL_GAP_NOTICE in messages[0].content
    assert CITE_INSTRUCTION in messages[0].content


def test_rag_messages_injects_cite_instruction_with_context() -> None:
    chunk = _chunk("c1", "grounded evidence")

    messages = _brain(FakeModelPort("unused"))._rag_messages("q", (chunk,), ())

    assert messages[0].role == "system"
    assert SPOTLIGHT_INSTRUCTION.split("{nonce}")[0] in messages[0].content
    assert CITE_INSTRUCTION in messages[0].content
    assert "[c1] grounded evidence" in messages[0].content


@pytest.mark.asyncio
async def test_respond_surfaces_invalid_citation_notice() -> None:
    chunk = _chunk("c1", "grounded evidence")
    brain = _brain_with_rag(FakeModelPort("See [ghost]."), (chunk,))

    response = await brain.respond("q", "owner-private")

    assert response.notices == ["[CITATION WARNING] cited context not provided: ghost"]
    assert response.text == ("See [ghost].\n\n[CITATION WARNING] cited context not provided: ghost")


@pytest.mark.asyncio
async def test_respond_leaves_clean_cited_answer_unchanged() -> None:
    chunk = _chunk("c1", "grounded evidence")
    brain = _brain_with_rag(FakeModelPort("See [c1]."), (chunk,))

    response = await brain.respond("q", "owner-private")

    assert response.notices == []
    assert response.text == "See [c1]."


def _brain(model: FakeModelPort) -> Brain:
    return Brain(
        cast(SemanticRouter, FakeRouter()),
        ToolRegistry(FakeEmbedder()),
        model,
    )


def _brain_with_rag(model: FakeModelPort, chunks: tuple[RetrievedChunk, ...]) -> Brain:
    async def retrieve_fn(query: str) -> list[RetrievedChunk]:
        del query
        return list(chunks)

    async def recall_fn() -> list[Fact]:
        return []

    return Brain(
        cast(SemanticRouter, FakeRouter()),
        ToolRegistry(FakeEmbedder()),
        model,
        enforcer=SensitivityEnforcer(FakeSensitivityClassifier()),
        retrieve_fn=retrieve_fn,
        recall_fn=recall_fn,
    )


def _chunk(chunk_id: str, text: str, *, score: float = 0.9) -> RetrievedChunk:
    return RetrievedChunk(
        Chunk(
            chunk_id=chunk_id,
            document_id=f"doc-{chunk_id}",
            text=text,
            scope="owner-private",
            sensitivity="general",
        ),
        score=score,
    )
