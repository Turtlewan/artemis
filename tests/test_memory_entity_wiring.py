from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from typing import Literal, cast

import pytest
import sqlite_vec  # type: ignore[import-untyped]
from pydantic import ValidationError

from artemis.manifest import ActionRisk
from artemis.memory.decide import FakeDecider
from artemis.memory.entities import EntityRepository, EntityType
from artemis.memory.extraction import FakeExtractor
from artemis.memory.repository import BitemporalRepository, FactRow
from artemis.memory.schema import create_schema
from artemis.memory.tools import (
    EntityNotFound,
    FactView,
    ResolveEntityArgs,
    ResolveEntityResult,
    memory_manifest,
    resolve_entity,
)
from artemis.memory.write_path import MemoryWritePath
from artemis.ports.types import PersonId, Vector
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


@pytest.fixture
def entity_repo(conn: sqlite3.Connection) -> EntityRepository:
    return EntityRepository(conn, OWNER_PERSON_ID)


class FakeEmbedder:
    @property
    def dimension(self) -> int:
        return DIMENSION

    async def embed_documents(self, texts: Sequence[str]) -> list[Vector]:
        return [_embed(text) for text in texts]

    async def embed_query(self, query: str) -> Vector:
        return _embed(query)


class RaisingEntityRepo:
    def resolve_or_create_entity(
        self,
        name: str,
        entity_type: EntityType,
        *,
        external_ref: str | None = None,
    ) -> str:
        del name, entity_type, external_ref
        raise RuntimeError("entity backend unavailable")


@pytest.mark.asyncio
async def test_write_path_links_subject_to_owner_person_and_update_keeps_entity(
    repo: BitemporalRepository,
    entity_repo: EntityRepository,
) -> None:
    write_path = _write_path(repo, entity_repo)

    added = await write_path.process_turn("I live in Paris", turn_id="T1")
    assert added.facts_added == 1
    first = _single_current(repo, "lives_in")
    assert first.subject_entity_id is not None
    entity = entity_repo.get_entity(first.subject_entity_id)
    assert entity.entity_type is EntityType.PERSON
    assert entity.canonical_name == "owner"

    updated = await write_path.process_turn("Actually I moved to London", turn_id="T2")
    assert updated.facts_updated == 1
    current = _single_current(repo, "lives_in")
    assert current.object == "London"
    assert current.subject_entity_id == first.subject_entity_id


@pytest.mark.asyncio
async def test_facts_for_entity_lifecycle_and_resolve_entity(
    repo: BitemporalRepository,
    entity_repo: EntityRepository,
) -> None:
    write_path = _write_path(repo, entity_repo)
    await write_path.process_turn("I live in Paris", turn_id="T1")
    await write_path.process_turn("Actually I moved to London", turn_id="T2")
    current = _single_current(repo, "lives_in")
    assert current.subject_entity_id is not None
    owner_entity_id = current.subject_entity_id

    linked = repo.facts_for_entity(owner_entity_id)
    assert [(row.relation, row.object, row.subject_entity_id) for row in linked] == [
        ("lives_in", "London", owner_entity_id)
    ]
    assert repo.facts_for_entity("person:does-not-exist") == []
    plan_rows = repo.conn.execute(
        """EXPLAIN QUERY PLAN
           SELECT fact_id
           FROM facts
           WHERE subject_entity_id = ?
             AND tx_from <= ? AND tx_to > ?
             AND valid_from <= ? AND valid_to > ?
           ORDER BY relation, object""",
        (owner_entity_id, current.tx_from, current.tx_from, current.tx_from, current.tx_from),
    ).fetchall()
    plan = " ".join(str(row[3]) for row in plan_rows)
    assert "USING INDEX" in plan
    assert "subject_entity_id" in plan

    resolved = await resolve_entity(
        ResolveEntityArgs(entity_id=owner_entity_id),
        entity_repo=entity_repo,
        repo=repo,
    )
    assert resolved.entity_type == "person"
    assert resolved.canonical_name == "owner"
    assert FactView(relation="lives_in", object="London", confidence=0.95) in resolved.facts

    repo.tombstone(current.fact_key)
    assert repo.facts_for_entity(owner_entity_id) == []


@pytest.mark.asyncio
async def test_resolve_entity_guards_and_unknown_id(
    repo: BitemporalRepository,
    entity_repo: EntityRepository,
) -> None:
    with pytest.raises(ValidationError):
        ResolveEntityArgs(module="finance", entity_id="x")

    invalid_module = cast(Literal["memory"], "finance")
    bypassed = ResolveEntityArgs.model_construct(module=invalid_module, entity_id="x")
    with pytest.raises(ValueError):
        await resolve_entity(bypassed, entity_repo=entity_repo, repo=repo)

    with pytest.raises(EntityNotFound) as exc:
        await resolve_entity(
            ResolveEntityArgs(entity_id="person:does-not-exist"),
            entity_repo=entity_repo,
            repo=repo,
        )
    assert str(exc.value) == "entity not found"


@pytest.mark.asyncio
async def test_registry_registration_callable_returns_resolved_entity(
    repo: BitemporalRepository,
    entity_repo: EntityRepository,
) -> None:
    write_path = _write_path(repo, entity_repo)
    await write_path.process_turn("I live in London", turn_id="T1")
    current = _single_current(repo, "lives_in")
    assert current.subject_entity_id is not None

    registry = ToolRegistry(FakeEmbedder())
    registry.register(memory_manifest(repo))
    spec = registry.get_tool("memory.resolve_entity")

    assert spec.action_risk is ActionRisk.READ
    assert spec.args_schema is ResolveEntityArgs
    assert callable(spec.callable_ref)
    result = await spec.callable_ref(ResolveEntityArgs(entity_id=current.subject_entity_id))
    assert isinstance(result, ResolveEntityResult)
    assert result.entity_id == current.subject_entity_id
    assert result.facts == [FactView(relation="lives_in", object="London", confidence=0.95)]


@pytest.mark.asyncio
async def test_entity_resolution_failure_stores_fact_without_link(
    repo: BitemporalRepository,
) -> None:
    write_path = MemoryWritePath(
        repo,
        FakeEmbedder(),
        FakeExtractor(),  # type: ignore[arg-type]
        FakeDecider(),  # type: ignore[arg-type]
        entity_repo=cast(EntityRepository, RaisingEntityRepo()),
        extractor_model_id="fake-extractor",
    )

    result = await write_path.process_turn("I live in Paris", turn_id="T9")

    assert result.facts_added == 1
    row = _single_current(repo, "lives_in")
    assert row.object == "Paris"
    assert row.subject_entity_id is None
    episodes = repo.read_episodes()
    assert len(episodes) == 1
    assert episodes[0].turn_id == "T9"


def _write_path(repo: BitemporalRepository, entity_repo: EntityRepository) -> MemoryWritePath:
    return MemoryWritePath(
        repo,
        FakeEmbedder(),
        FakeExtractor(),  # type: ignore[arg-type]
        FakeDecider(),  # type: ignore[arg-type]
        entity_repo=entity_repo,
        extractor_model_id="fake-extractor",
    )


def _single_current(repo: BitemporalRepository, relation: str) -> FactRow:
    matches = [row for row in repo.as_of() if row.relation == relation]
    assert len(matches) == 1
    return matches[0]


def _embed(text: str) -> list[float]:
    h = sum(ord(char) for char in text)
    vec = [float((h >> (i * 4)) & 0xFF) for i in range(DIMENSION)]
    norm = sum(value * value for value in vec) ** 0.5 or 1.0
    return [value / norm for value in vec]
