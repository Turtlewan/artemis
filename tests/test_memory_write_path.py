from __future__ import annotations

import json
import sqlite3
from collections.abc import AsyncIterator, Sequence

import pytest
import sqlite_vec  # type: ignore[import-untyped]

from artemis.memory.decide import AudnDecider, AudnDecision, Candidate, FakeDecider
from artemis.memory.extraction import EXTRACTION_SCHEMA, ExtractedFact, FactExtractor, FakeExtractor
from artemis.memory.repository import BitemporalRepository
from artemis.memory.schema import SENTINEL_TS, create_schema
from artemis.memory.write_path import MemoryWritePath, MemoryWriteQueue
from artemis.ports.model import ModelResponse
from artemis.ports.types import Message, PersonId, Vector

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


class FakeModelPort:
    def __init__(self, text: str) -> None:
        self._text = text
        self.response_schema: dict[str, object] | None = None
        self.role: str | None = None

    async def complete(
        self,
        *,
        role: str,
        messages: Sequence[Message],
        response_schema: dict[str, object] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        del messages, temperature, max_tokens
        self.role = role
        self.response_schema = response_schema
        return ModelResponse(text=self._text, model_id=role)

    async def complete_stream(
        self,
        *,
        role: str,
        messages: Sequence[Message],
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        if False:
            yield role + messages[0].content + str(temperature)

    async def embed(self, role: str, texts: Sequence[str]) -> list[Vector]:
        return [_embed(role + text) for text in texts]


class RaisingExtractor:
    async def extract(self, text: str, *, context: str | None = None) -> list[ExtractedFact]:
        del text, context
        raise RuntimeError("boom")


class ExplodingWritePath:
    def __init__(self) -> None:
        self.turn_ids: list[str] = []

    async def process_turn(self, text: str, *, turn_id: str, role: str | None = None) -> object:
        del text, role
        self.turn_ids.append(turn_id)
        if turn_id == "bad":
            raise RuntimeError("boom")
        return object()


@pytest.mark.asyncio
async def test_fact_extractor_uses_schema_and_parses_model_json() -> None:
    model = FakeModelPort(
        json.dumps(
            {
                "facts": [
                    {
                        "subject": "owner",
                        "relation": "lives_in",
                        "object": "Paris",
                        "confidence": 0.8,
                        "keywords": ["home"],
                        "contextual_description": "explicit",
                    }
                ]
            }
        )
    )
    extractor = FactExtractor(model)

    facts = await extractor.extract("I live in Paris")

    assert model.role == "sensitive_reasoner"
    assert model.response_schema == EXTRACTION_SCHEMA
    assert facts == [
        ExtractedFact(
            "owner",
            "lives_in",
            "Paris",
            0.8,
            keywords=("home",),
            contextual_description="explicit",
        )
    ]


@pytest.mark.asyncio
async def test_fake_decider_rubric() -> None:
    candidate = Candidate("f1", "owner", "lives_in", "London")
    decider = FakeDecider()

    update = await decider.decide(ExtractedFact("owner", "lives_in", "Paris", 0.9), [candidate])
    add = await decider.decide(ExtractedFact("owner", "likes", "tea", 0.9), [candidate])
    noop = await decider.decide(ExtractedFact("owner", "lives_in", "London", 0.9), [candidate])

    assert update == AudnDecision("UPDATE", "f1", "Paris", 0.9)
    assert add == AudnDecision("ADD", None, "tea", 0.9)
    assert noop == AudnDecision("NOOP", "f1", None, 0.9)


@pytest.mark.asyncio
async def test_audn_decider_downgrades_unknown_target(repo: BitemporalRepository) -> None:
    model = FakeModelPort(
        json.dumps(
            {
                "op": "UPDATE",
                "target_fact_id": "missing",
                "object": "Paris",
                "confidence": 0.7,
            }
        )
    )
    decider = AudnDecider(model, repo)

    decision = await decider.decide(ExtractedFact("owner", "lives_in", "Paris", 0.7), [])

    assert decision == AudnDecision("ADD", None, "Paris", 0.7)


@pytest.mark.asyncio
async def test_write_path_add_update_delete_noop_and_provenance(
    repo: BitemporalRepository,
) -> None:
    write_path = _write_path(repo)

    added = await write_path.process_turn("I live in London", turn_id="T1", role="user")
    assert added.facts_added == 1
    london_rows = repo.as_of()
    assert [(row.subject, row.relation, row.object) for row in london_rows] == [
        ("owner", "lives_in", "London")
    ]
    london = london_rows[0]
    assert london.source_turn_id == "T1"
    assert london.extractor_model == "fake-extractor"
    fact_key = london.fact_key

    updated = await write_path.process_turn("Actually I moved to Paris", turn_id="T2")
    assert updated.facts_updated == 1
    current = repo.as_of(fact_keys=[fact_key])
    assert [row.object for row in current] == ["Paris"]
    history = repo.history(fact_key)
    assert len(history) == 2
    assert history[0].object == "London"
    assert history[0].tx_to != SENTINEL_TS
    assert history[1].object == "Paris"
    assert history[1].source_turn_id == "T2"

    noop = await write_path.process_turn("I live in Paris", turn_id="T2-replay")
    assert noop.noops == 1
    assert len(repo.history(fact_key)) == 2

    deleted = await write_path.process_turn("I don't live in Paris anymore", turn_id="T3")
    assert deleted.facts_deleted == 1
    assert repo.as_of(fact_keys=[fact_key]) == []
    assert len(repo.history(fact_key)) == 3


@pytest.mark.asyncio
async def test_idempotent_reprocess_does_not_duplicate(repo: BitemporalRepository) -> None:
    write_path = _write_path(repo)

    first = await write_path.process_turn("I live in London", turn_id="T1")
    second = await write_path.process_turn("I live in London", turn_id="T1")

    assert first.facts_added == 1
    assert second.noops == 1
    key = repo.compute_fact_key("owner", "lives_in", "London")
    assert len(repo.history(key)) == 1


@pytest.mark.asyncio
async def test_episode_is_persisted_when_extraction_fails(repo: BitemporalRepository) -> None:
    write_path = MemoryWritePath(
        repo,
        FakeEmbedder(),
        RaisingExtractor(),  # type: ignore[arg-type]
        FakeDecider(),  # type: ignore[arg-type]
        extractor_model_id="fake-extractor",
    )

    result = await write_path.process_turn("I live in London", turn_id="T1")

    assert result.errors == 1
    episodes = repo.read_episodes()
    assert len(episodes) == 1
    assert episodes[0].text == "I live in London"


@pytest.mark.asyncio
async def test_queue_drain_processes_turns(repo: BitemporalRepository) -> None:
    queue = MemoryWriteQueue(_write_path(repo))

    queue.enqueue("I live in London", "T1")
    queue.enqueue("I like tea", "T2")
    await queue.drain()

    rows = {(row.relation, row.object) for row in repo.as_of()}
    assert rows == {("lives_in", "London"), ("likes", "tea")}


@pytest.mark.asyncio
async def test_queue_survives_process_turn_exception() -> None:
    write_path = ExplodingWritePath()
    queue = MemoryWriteQueue(write_path)  # type: ignore[arg-type]

    queue.enqueue("bad", "bad")
    queue.enqueue("good", "good")
    await queue.drain()

    assert write_path.turn_ids == ["bad", "good"]


def _write_path(repo: BitemporalRepository) -> MemoryWritePath:
    return MemoryWritePath(
        repo,
        FakeEmbedder(),
        FakeExtractor(),  # type: ignore[arg-type]
        FakeDecider(),  # type: ignore[arg-type]
        extractor_model_id="fake-extractor",
    )


def _embed(text: str) -> list[float]:
    h = sum(ord(char) for char in text)
    vec = [float((h >> (i * 4)) & 0xFF) for i in range(DIMENSION)]
    norm = sum(value * value for value in vec) ** 0.5 or 1.0
    return [value / norm for value in vec]
