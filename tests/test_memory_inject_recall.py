from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta

import pytest
import sqlite_vec  # type: ignore[import-untyped]

from artemis.brain import Brain, BrainResponse
from artemis.identity.scope import OWNER_PRIVATE
from artemis.memory.decay import decay_score, rank_for_inject, recall_multiplier
from artemis.memory.repository import BitemporalRepository, FactRow
from artemis.memory.schema import create_schema, now_iso
from artemis.memory.store import SqliteMemoryStore, render_inject_block
from artemis.ports.memory import MemoryStore
from artemis.ports.model import ModelResponse
from artemis.ports.routing import RouteDecision
from artemis.ports.types import Fact, Message, PersonId, Scope, Vector
from artemis.registry import ToolRegistry

DIMENSION = 4
OWNER_PERSON_ID = PersonId("owner")


@pytest.fixture
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.enable_load_extension(True)
    c.load_extension(sqlite_vec.loadable_path())
    c.enable_load_extension(False)
    c.row_factory = sqlite3.Row
    create_schema(c, embedder_model_id="test-fake", dimension=DIMENSION)
    return c


@pytest.fixture
def repo(conn: sqlite3.Connection) -> BitemporalRepository:
    return BitemporalRepository(conn, OWNER_PERSON_ID)


class FakeEmbedder:
    @property
    def dimension(self) -> int:
        return DIMENSION

    async def embed_documents(self, texts: Sequence[str]) -> list[Vector]:
        return [_embed(text) for text in texts]

    async def embed_query(self, query: str) -> Vector:
        return _embed(query)


class RecordingModelPort:
    def __init__(self) -> None:
        self.messages: list[Sequence[Message]] = []
        self.roles: list[str] = []

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
        self.roles.append(role)
        self.messages.append(messages)
        return ModelResponse(text="ok", model_id=role)

    def complete_stream(
        self,
        *,
        role: str,
        messages: Sequence[Message],
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        del messages, temperature

        async def _gen() -> AsyncIterator[str]:
            yield role

        return _gen()

    async def embed(self, role: str, texts: Sequence[str]) -> list[Vector]:
        return [_embed(role + text) for text in texts]


class LocalRouter:
    async def route(self, request_text: str, scope: Scope) -> RouteDecision:
        del request_text, scope
        return RouteDecision(path="local", candidate_tools=[], confidence=0.5)


class SpyWriteQueue:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str | None]] = []

    def enqueue(self, text: str, turn_id: str, role: str | None = None) -> None:
        self.calls.append((text, turn_id, role))


class RaisingMemory:
    async def add_fact(self, person_id: PersonId, fact: Fact) -> None:
        del person_id, fact

    async def recall(
        self,
        person_id: PersonId,
        query: str,
        k: int = 10,
        as_of: object | None = None,
    ) -> list[Fact]:
        del person_id, query, k, as_of
        return []

    async def update_fact(self, person_id: PersonId, fact_id: str, fact: Fact) -> None:
        del person_id, fact_id, fact

    def delete_fact(self, person_id: PersonId, fact_id: str) -> None:
        del person_id, fact_id

    async def inject_context(
        self,
        person_id: PersonId,
        token_budget: int,
        as_of: object | None = None,
    ) -> list[Fact]:
        del person_id, token_budget, as_of
        raise RuntimeError("boom")


def test_decay_orders_recent_salient_and_drops_below_threshold() -> None:
    now = datetime(2026, 6, 24, tzinfo=UTC)
    recent = now - timedelta(hours=1)
    stale = now - timedelta(days=90)

    recent_score = decay_score(
        valid_from=recent.isoformat(),
        last_access=recent.isoformat(),
        access_count=2,
        salience=2.0,
        confidence=0.95,
        now=now.isoformat(),
    )
    stale_score = decay_score(
        valid_from=stale.isoformat(),
        last_access=None,
        access_count=0,
        salience=0.1,
        confidence=0.5,
        now=now.isoformat(),
    )

    assert recent_score > stale_score
    ranked = rank_for_inject(
        [
            _fact_row("recent", valid_from=recent.isoformat()),
            _fact_row("stale", valid_from=stale.isoformat()),
        ],
        now=now.isoformat(),
    )
    assert [row.fact_id for row, _score in ranked] == ["recent"]


def test_recall_multiplier_clamps() -> None:
    now = datetime(2026, 6, 24, tzinfo=UTC)
    assert recall_multiplier(
        last_access=now.isoformat(),
        valid_from=now.isoformat(),
        access_count=10,
        cosine=1.0,
        now=now.isoformat(),
    ) == pytest.approx(1.5)
    assert recall_multiplier(
        last_access=None,
        valid_from=(now - timedelta(days=365)).isoformat(),
        access_count=0,
        cosine=0.0,
        now=now.isoformat(),
    ) == pytest.approx(0.3)


@pytest.mark.asyncio
async def test_inject_respects_budget_and_bumps_selected(repo: BitemporalRepository) -> None:
    store = SqliteMemoryStore(repo, FakeEmbedder())
    recent_id = _add(repo, "owner", "lives_in", "Paris", valid_from=now_iso())
    old_id = _add(repo, "owner", "likes", "tea", valid_from="2000-01-01T00:00:00+00:00")
    repo.bump_access(recent_id)

    facts = await store.inject_context(OWNER_PERSON_ID, token_budget=6)

    assert [fact.fact_id for fact in facts] == [recent_id]
    assert repo.get_fact(recent_id).access_count == 2
    assert repo.get_fact(old_id).access_count == 0


def test_render_inject_block() -> None:
    fact = Fact(
        "f1",
        OWNER_PERSON_ID,
        "owner",
        "lives_in",
        "Paris",
        0.9,
        datetime(2026, 6, 24, tzinfo=UTC),
    )

    assert render_inject_block([]) == ""
    block = render_inject_block([fact])
    assert "Known facts about the owner:" in block
    assert "- owner lives_in Paris (as of 2026-06-24, still current)" in block


def test_rag_messages_includes_recency_instruction() -> None:
    model = RecordingModelPort()
    brain = _brain(model, owner_person_id=OWNER_PERSON_ID)
    fact = Fact(
        "f1",
        OWNER_PERSON_ID,
        "owner",
        "lives_in",
        "Paris",
        0.9,
        datetime(2026, 6, 24, tzinfo=UTC),
    )

    messages = brain._rag_messages("hi", (), (fact,))

    system = next(m.content for m in messages if m.role == "system")
    assert "recency" in system.lower()
    assert "as of 2026-06-24, still current" in system


@pytest.mark.asyncio
async def test_recall_returns_seeded_facts(repo: BitemporalRepository) -> None:
    store = SqliteMemoryStore(repo, FakeEmbedder())
    first_id = _add(repo, "owner", "lives_in", "Paris", valid_from=now_iso())
    second_id = _add(repo, "owner", "likes", "tea", valid_from=now_iso())

    facts = await store.recall(OWNER_PERSON_ID, "owner", k=2)

    assert {fact.fact_id for fact in facts} == {first_id, second_id}


@pytest.mark.asyncio
async def test_recall_and_inject_carry_sensitivity_and_category(
    repo: BitemporalRepository,
) -> None:
    store = SqliteMemoryStore(repo, FakeEmbedder())
    general_id = _add(
        repo,
        "owner",
        "likes",
        "coffee",
        valid_from=now_iso(),
        sensitivity="general",
        category="journal",
    )
    sensitive_id = _add(
        repo,
        "owner",
        "visits",
        "clinic",
        valid_from=now_iso(),
        sensitivity="sensitive",
    )
    untagged_id = _add(
        repo,
        "owner",
        "keeps",
        "notes",
        valid_from=now_iso(),
        sensitivity="",
    )

    recalled = {fact.fact_id: fact for fact in await store.recall(OWNER_PERSON_ID, "owner", k=3)}

    assert recalled[general_id].sensitivity == "general"
    assert recalled[general_id].category == "journal"
    assert recalled[sensitive_id].sensitivity == "sensitive"
    assert recalled[sensitive_id].category is None
    assert recalled[untagged_id].sensitivity == "sensitive"
    assert recalled[untagged_id].category is None

    injected = {
        fact.fact_id: fact for fact in await store.inject_context(OWNER_PERSON_ID, token_budget=100)
    }

    assert injected[general_id].sensitivity == "general"
    assert injected[general_id].category == "journal"
    assert injected[sensitive_id].sensitivity == "sensitive"
    assert injected[untagged_id].sensitivity == "sensitive"


@pytest.mark.asyncio
async def test_sqlite_memory_store_satisfies_protocol(repo: BitemporalRepository) -> None:
    store = SqliteMemoryStore(repo, FakeEmbedder())

    assert isinstance(store, MemoryStore)


@pytest.mark.asyncio
async def test_brain_injects_system_message_when_memory_enabled(
    repo: BitemporalRepository,
) -> None:
    _add(repo, "owner", "lives_in", "Paris", valid_from=now_iso())
    store = SqliteMemoryStore(repo, FakeEmbedder())
    model = RecordingModelPort()
    brain = _brain(model, memory=store, owner_person_id=OWNER_PERSON_ID)

    response = await brain.respond("hi", OWNER_PRIVATE)

    assert isinstance(response, BrainResponse)
    assert any(
        message.role == "system" and "owner lives_in Paris" in message.content
        for message in model.messages[0]
    )


@pytest.mark.asyncio
async def test_brain_without_memory_has_no_system_message() -> None:
    model = RecordingModelPort()
    brain = _brain(model)

    await brain.respond("hi", OWNER_PRIVATE)

    assert [message.role for message in model.messages[0]] == ["user"]


@pytest.mark.asyncio
async def test_brain_post_turn_enqueue_once() -> None:
    model = RecordingModelPort()
    queue = SpyWriteQueue()
    brain = _brain(model, write_queue=queue, owner_person_id=OWNER_PERSON_ID)

    await brain.respond("remember this", OWNER_PRIVATE)

    assert len(queue.calls) == 1
    text, turn_id, role = queue.calls[0]
    assert text == "remember this"
    assert turn_id
    assert role == "user"


@pytest.mark.asyncio
async def test_memory_failure_does_not_break_turn() -> None:
    model = RecordingModelPort()
    brain = _brain(model, memory=RaisingMemory(), owner_person_id=OWNER_PERSON_ID)

    response = await brain.respond("hi", OWNER_PRIVATE)

    assert response.text == "ok"
    assert [message.role for message in model.messages[0]] == ["user"]


def _brain(
    model: RecordingModelPort,
    *,
    memory: object | None = None,
    write_queue: object | None = None,
    owner_person_id: PersonId | None = None,
) -> Brain:
    registry = ToolRegistry(FakeEmbedder())
    return Brain(
        LocalRouter(),  # type: ignore[arg-type]
        registry,
        model,
        memory=memory,  # type: ignore[arg-type]
        write_queue=write_queue,  # type: ignore[arg-type]
        owner_person_id=owner_person_id,
    )


def _add(
    repo: BitemporalRepository,
    subject: str,
    relation: str,
    object_: str,
    *,
    valid_from: str,
    sensitivity: str = "sensitive",
    category: str | None = None,
) -> str:
    return repo.add(
        subject,
        relation,
        object_,
        0.95,
        _embed(f"{subject} {relation} {object_}"),
        valid_from=valid_from,
        sensitivity=sensitivity,  # type: ignore[arg-type]
        category=category,
    )


def _embed(text: str) -> list[float]:
    h = sum(ord(char) for char in text)
    vec = [float((h >> (i * 4)) & 0xFF) for i in range(DIMENSION)]
    norm = sum(value * value for value in vec) ** 0.5 or 1.0
    return [value / norm for value in vec]


def _fact_row(fact_id: str, *, valid_from: str) -> FactRow:
    return FactRow(
        fact_id=fact_id,
        fact_key=f"{fact_id}-key",
        person_id="owner",
        subject="owner",
        relation="likes",
        object=fact_id,
        confidence=0.9,
        valid_from=valid_from,
        valid_to="9999-12-31T23:59:59Z",
        tx_from=valid_from,
        tx_to="9999-12-31T23:59:59Z",
        source_turn_id=None,
        extracted_at=None,
        extractor_model=None,
        salience=1.0,
        access_count=0,
        last_access=None,
        keywords=None,
        contextual_description=None,
        linked_ids=None,
        sensitivity="sensitive",
        category=None,
    )
