"""Tests for ADR-029 sensitivity enforcement at RAG compose."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from typing import cast

import pytest

from artemis.brain import Brain
from artemis.ports.model import ModelResponse
from artemis.ports.routing import RouteDecision
from artemis.ports.types import Chunk, Fact, Message, PersonId, RetrievedChunk, Scope, Usage, Vector
from artemis.registry import ToolRegistry
from artemis.router import SemanticRouter
from artemis.sensitivity import (
    GateDecision,
    ReleaseAuditEntry,
    Sensitivity,
    SensitivityEnforcer,
    compose_with_gate,
)


class FakeSensitivityClassifier:
    """Classifier fake returning a configured label or raising."""

    def __init__(self, label: Sensitivity = "general", raises: bool = False) -> None:
        self.label = label
        self.raises = raises
        self.call_count = 0

    async def classify(self, request_text: str) -> Sensitivity:
        self.call_count += 1
        if self.raises:
            raise RuntimeError("classifier unavailable")
        return self.label


class FakeAuditLog:
    """Records release audit entries."""

    def __init__(self) -> None:
        self.entries: list[ReleaseAuditEntry] = []

    def __call__(self, entry: ReleaseAuditEntry) -> None:
        self.entries.append(entry)


class FakeRouter:
    def __init__(self) -> None:
        self.decision = RouteDecision(path="local", candidate_tools=[], confidence=0.5)

    async def route(self, request_text: str, scope: Scope) -> RouteDecision:
        return self.decision


class FakeEmbedder:
    @property
    def dimension(self) -> int:
        return 4

    async def embed_documents(self, texts: Sequence[str]) -> list[Vector]:
        return [[1.0, 0.0, 0.0, 0.0] for _ in texts]

    async def embed_query(self, query: str) -> Vector:
        return [1.0, 0.0, 0.0, 0.0]


class RecordingModelPort:
    def __init__(self) -> None:
        self.complete_roles: list[str] = []
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
        del response_schema, temperature, max_tokens
        self.complete_roles.append(role)
        self.complete_messages.append(list(messages))
        return ModelResponse(
            text="answer",
            finish_reason="stop",
            usage=Usage(1, 1, 2),
            origin="local",
            model_id="fake",
        )

    def complete_stream(
        self,
        *,
        role: str,
        messages: Sequence[Message],
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        del role, messages, temperature

        async def _gen() -> AsyncIterator[str]:
            yield "chunk"

        return _gen()

    async def embed(self, role: str, texts: Sequence[str]) -> list[Vector]:
        del role
        return [[0.0] for _ in texts]


def _chunk(
    chunk_id: str,
    text: str,
    sensitivity: Sensitivity,
    category: str | None,
) -> RetrievedChunk:
    return RetrievedChunk(
        Chunk(
            chunk_id=chunk_id,
            document_id=f"doc-{chunk_id}",
            text=text,
            scope="owner-private",
            sensitivity=sensitivity,
            category=category,
        ),
        score=0.9,
    )


def _fact(
    fact_id: str,
    object_value: str,
    sensitivity: Sensitivity,
    category: str | None,
) -> Fact:
    return Fact(
        fact_id=fact_id,
        person_id=PersonId("owner"),
        subject="owner",
        relation="has",
        object=object_value,
        confidence=0.9,
        valid_at=datetime(2026, 6, 25, tzinfo=UTC),
        sensitivity=sensitivity,
        category=category,
    )


async def _retrieve(chunks: list[RetrievedChunk], query: str) -> list[RetrievedChunk]:
    del query
    return chunks


async def _recall(facts: list[Fact]) -> list[Fact]:
    return facts


@pytest.mark.asyncio
async def test_general_mixed_context_filters_sensitive_items() -> None:
    general_chunk = _chunk("A", "public botany note", "general", "research")
    sensitive_chunk = _chunk("B", "private medical text", "sensitive", "medical email")
    general_fact = _fact("F1", "likes tea", "general", "preference")
    sensitive_fact = _fact("F2", "has diagnosis", "sensitive", "health fact")

    decision = await SensitivityEnforcer(FakeSensitivityClassifier("general")).enforce(
        request_text="explain plants",
        chunks=[general_chunk, sensitive_chunk],
        facts=[general_fact, sensitive_fact],
    )

    assert decision.role == "responder_cloud"
    assert decision.context.request_sensitive is False
    assert decision.context.cloud_safe_chunks == (general_chunk,)
    assert decision.context.cloud_safe_facts == (general_fact,)
    assert [(item.kind, item.ref_id, item.category) for item in decision.context.held_back] == [
        ("chunk", "B", "medical email"),
        ("fact", "F2", "health fact"),
    ]


@pytest.mark.asyncio
async def test_sensitive_request_keeps_whole_turn_local() -> None:
    chunks = [_chunk("A", "public note", "general", "research")]
    facts = [_fact("F1", "private thing", "sensitive", "journal")]

    decision = await SensitivityEnforcer(FakeSensitivityClassifier("sensitive")).enforce(
        request_text="summarize my journal",
        chunks=chunks,
        facts=facts,
    )

    assert decision.role == "responder"
    assert decision.context.request_sensitive is True
    assert decision.context.held_back == ()
    assert decision.context.cloud_safe_chunks == tuple(chunks)
    assert decision.context.cloud_safe_facts == tuple(facts)


@pytest.mark.asyncio
async def test_kill_switch_skips_classifier_and_forces_local() -> None:
    classifier = FakeSensitivityClassifier("general")

    decision = await SensitivityEnforcer(
        classifier,
        cloud_reasoning_enabled=False,
    ).enforce(request_text="explain gravity", chunks=[], facts=[])

    assert decision.role == "responder"
    assert classifier.call_count == 0


@pytest.mark.asyncio
async def test_no_classifier_forces_local() -> None:
    decision = await SensitivityEnforcer(None).enforce(
        request_text="explain gravity",
        chunks=[],
        facts=[],
    )

    assert decision.role == "responder"
    assert decision.context.request_sensitive is True


@pytest.mark.asyncio
async def test_classifier_raises_fail_closed() -> None:
    decision = await SensitivityEnforcer(FakeSensitivityClassifier(raises=True)).enforce(
        request_text="explain gravity",
        chunks=[],
        facts=[],
    )

    assert decision.role == "responder"
    assert decision.context.request_sensitive is True


@pytest.mark.asyncio
async def test_untagged_fail_closed_default_is_held_back() -> None:
    untagged_default = RetrievedChunk(
        Chunk(
            chunk_id="B",
            document_id="doc-B",
            text="defaults sensitive",
            scope="owner-private",
        ),
        score=0.8,
    )

    decision = await SensitivityEnforcer(FakeSensitivityClassifier("general")).enforce(
        request_text="general question",
        chunks=[untagged_default],
        facts=[],
    )

    assert decision.context.cloud_safe_chunks == ()
    assert [item.ref_id for item in decision.context.held_back] == ["B"]


@pytest.mark.asyncio
async def test_one_time_release_includes_sensitive_item() -> None:
    sensitive_chunk = _chunk("B", "private medical text", "sensitive", "medical email")

    decision = await SensitivityEnforcer(FakeSensitivityClassifier("general")).enforce(
        request_text="general question",
        chunks=[sensitive_chunk],
        facts=[],
        released_ref_ids=frozenset({"B"}),
    )

    assert decision.context.cloud_safe_chunks == (sensitive_chunk,)
    assert decision.context.held_back == ()


@pytest.mark.asyncio
async def test_release_is_audited_once_and_general_release_is_not_audited() -> None:
    sensitive_chunk = _chunk("B", "private medical text", "sensitive", "medical email")
    general_chunk = _chunk("A", "public note", "general", "research")
    audit_log = FakeAuditLog()

    await compose_with_gate(
        request_text="general question",
        query_id="q1",
        retrieve_fn=lambda query: _retrieve([sensitive_chunk, general_chunk], query),
        recall_fn=lambda: _recall([]),
        enforcer=SensitivityEnforcer(FakeSensitivityClassifier("general")),
        released_ref_ids=frozenset({"B", "A"}),
        audit_log=audit_log,
    )

    assert len(audit_log.entries) == 1
    entry = audit_log.entries[0]
    assert entry.query_id == "q1"
    assert entry.ref_id == "B"
    assert entry.kind == "chunk"
    assert entry.category == "medical email"
    datetime.fromisoformat(entry.released_at)


@pytest.mark.asyncio
async def test_held_back_label_carries_no_raw_content() -> None:
    sensitive_chunk = _chunk("B", "raw private diagnosis text", "sensitive", None)

    decision = await SensitivityEnforcer(FakeSensitivityClassifier("general")).enforce(
        request_text="general question",
        chunks=[sensitive_chunk],
        facts=[],
    )

    held = decision.context.held_back[0]
    assert held.label == "private item"
    assert held.label != sensitive_chunk.chunk.text


@pytest.mark.asyncio
async def test_compose_degrades_when_retrieve_and_recall_raise() -> None:
    async def bad_retrieve(query: str) -> list[RetrievedChunk]:
        del query
        raise RuntimeError("retrieve failed")

    async def bad_recall() -> list[Fact]:
        raise RuntimeError("recall failed")

    decision = await compose_with_gate(
        request_text="general question",
        query_id="q1",
        retrieve_fn=bad_retrieve,
        recall_fn=bad_recall,
        enforcer=SensitivityEnforcer(FakeSensitivityClassifier("general")),
    )

    assert decision == GateDecision(
        role="responder_cloud",
        context=decision.context,
    )
    assert decision.context.cloud_safe_chunks == ()
    assert decision.context.cloud_safe_facts == ()


@pytest.mark.asyncio
async def test_fail_closed_assertion_holds_for_sensitive_non_released_items() -> None:
    sensitive_chunk = _chunk("B", "private medical text", "sensitive", "medical email")
    sensitive_fact = _fact("F2", "has diagnosis", "sensitive", "health fact")

    decision = await SensitivityEnforcer(FakeSensitivityClassifier("general")).enforce(
        request_text="general question",
        chunks=[sensitive_chunk],
        facts=[sensitive_fact],
    )

    assert all(
        item.chunk.sensitivity == "general" or item.chunk.chunk_id == "released"
        for item in decision.context.cloud_safe_chunks
    )
    assert all(
        item.sensitivity == "general" or item.fact_id == "released"
        for item in decision.context.cloud_safe_facts
    )


@pytest.mark.asyncio
async def test_brain_surfaces_held_back_and_filters_cloud_prompt() -> None:
    model = RecordingModelPort()
    sensitive_chunk = _chunk("B", "private medical text", "sensitive", "medical email")
    general_chunk = _chunk("A", "public botany note", "general", "research")
    brain = Brain(
        cast(SemanticRouter, FakeRouter()),
        ToolRegistry(FakeEmbedder()),
        model,
        enforcer=SensitivityEnforcer(FakeSensitivityClassifier("general")),
        retrieve_fn=lambda query: _retrieve([general_chunk, sensitive_chunk], query),
        recall_fn=lambda: _recall([]),
    )

    response = await brain.respond("explain plants", "owner-private")

    assert model.complete_roles == ["responder_cloud"]
    assert [item.ref_id for item in response.held_back] == ["B"]
    rendered = "\n".join(message.content for message in model.complete_messages[0])
    assert "public botany note" in rendered
    assert "private medical text" not in rendered


@pytest.mark.asyncio
async def test_brain_one_time_release_includes_item_and_audits_once() -> None:
    model = RecordingModelPort()
    sensitive_chunk = _chunk("B", "private medical text", "sensitive", "medical email")
    audit_log = FakeAuditLog()
    brain = Brain(
        cast(SemanticRouter, FakeRouter()),
        ToolRegistry(FakeEmbedder()),
        model,
        enforcer=SensitivityEnforcer(FakeSensitivityClassifier("general")),
        retrieve_fn=lambda query: _retrieve([sensitive_chunk], query),
        recall_fn=lambda: _recall([]),
        audit_log=audit_log,
    )

    response = await brain.respond(
        "explain plants",
        "owner-private",
        released_ref_ids=frozenset({"B"}),
    )

    assert model.complete_roles == ["responder_cloud"]
    assert response.held_back == []
    rendered = "\n".join(message.content for message in model.complete_messages[0])
    assert "private medical text" in rendered
    assert [entry.ref_id for entry in audit_log.entries] == ["B"]
