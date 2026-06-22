"""Tests for the M4-d-1 memory entity data layer."""

from __future__ import annotations

import sqlite3
from dataclasses import FrozenInstanceError

import pytest
import sqlite_vec  # type: ignore[import-untyped]

from artemis.memory import EntityRef, EntityRepository, EntityType, person_fact_key
from artemis.memory.schema import SENTINEL_TS, create_schema, now_iso
from artemis.ports.types import PersonId

DIMENSION = 4
OWNER_PERSON_ID = PersonId("owner")


@pytest.fixture
def conn() -> sqlite3.Connection:
    """Fresh in-memory sqlite3 connection with sqlite-vec loaded."""
    c = sqlite3.connect(":memory:")
    c.enable_load_extension(True)
    c.load_extension(sqlite_vec.loadable_path())
    c.enable_load_extension(False)
    c.row_factory = sqlite3.Row
    create_schema(c, embedder_model_id="test-fake", dimension=DIMENSION)
    return c


@pytest.fixture
def repo(conn: sqlite3.Connection) -> EntityRepository:
    """Entity repository scoped to the owner person."""
    return EntityRepository(conn, OWNER_PERSON_ID)


def test_schema_adds_entity_tables_fact_link_and_indexes(conn: sqlite3.Connection) -> None:
    tables = {
        str(row["name"])
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    assert {"entities", "entity_aliases", "facts"}.issubset(tables)

    fact_columns = {str(row["name"]) for row in conn.execute("PRAGMA table_info(facts)")}
    assert "subject_entity_id" in fact_columns

    indexes = {
        str(row["name"])
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
    }
    assert {
        "idx_entities_type",
        "idx_entities_external_ref",
        "idx_entity_aliases_entity",
        "idx_facts_subject_entity",
    }.issubset(indexes)


def test_stale_facts_table_raises() -> None:
    c = sqlite3.connect(":memory:")
    c.execute(
        """CREATE TABLE facts (
            fact_id TEXT PRIMARY KEY,
            fact_key TEXT NOT NULL,
            person_id TEXT NOT NULL,
            subject TEXT NOT NULL,
            relation TEXT NOT NULL,
            object TEXT NOT NULL,
            confidence REAL NOT NULL,
            valid_from TEXT NOT NULL,
            valid_to TEXT NOT NULL,
            tx_from TEXT NOT NULL,
            tx_to TEXT NOT NULL
        )"""
    )

    with pytest.raises(RuntimeError, match="facts.subject_entity_id missing"):
        create_schema(c, embedder_model_id="test-fake", dimension=DIMENSION)


def test_resolve_or_create_name_only_idempotent(repo: EntityRepository) -> None:
    id1 = repo.resolve_or_create_entity("Alice", EntityType.PERSON)
    id2 = repo.resolve_or_create_entity("alice", EntityType.PERSON)

    assert id1 == id2
    assert id1.startswith("person:")
    assert len(repo.list_entities()) == 1


def test_email_keyed_person_stable_across_calls(repo: EntityRepository) -> None:
    e1 = repo.resolve_or_create_entity("Bob", EntityType.PERSON, external_ref="Bob@X.com")
    e2 = repo.resolve_or_create_entity("Robert", EntityType.PERSON, external_ref="bob@x.com")

    assert e1 == e2
    assert e1 == person_fact_key(external_ref="bob@x.com", name="Bob")


def test_alias_resolution(repo: EntityRepository) -> None:
    entity_id = repo.resolve_or_create_entity("Alice", EntityType.PERSON)
    repo.add_alias("my wife", entity_id, source="owner")

    assert repo.resolve_alias("My Wife") == entity_id
    assert repo.resolve_alias("nobody") is None
    assert set(repo.list_aliases(entity_id)) == {"alice", "my wife"}


def test_place_and_goal_creation(repo: EntityRepository) -> None:
    place_id = repo.resolve_or_create_entity("Home", EntityType.PLACE)
    goal_id = repo.resolve_or_create_entity("Run a marathon", EntityType.GOAL)

    assert place_id.startswith("place:")
    assert goal_id.startswith("goal:")
    assert repo.get_entity(place_id).entity_type == EntityType.PLACE
    assert len(repo.list_entities(EntityType.PLACE)) == 1


def test_merge_entities_repoints_aliases_and_facts(
    conn: sqlite3.Connection,
    repo: EntityRepository,
) -> None:
    merge_id = repo.resolve_or_create_entity("Jim", EntityType.PERSON)
    keep_id = repo.resolve_or_create_entity("James", EntityType.PERSON, external_ref="jim@x.com")
    repo.add_alias("jimmy", merge_id, source="owner")

    _insert_fact(conn, "fact-1", "fact-key-1", merge_id)
    _insert_fact(conn, "fact-2", "fact-key-2", merge_id)

    repo.merge_entities(keep=keep_id, merge=merge_id)

    assert repo.resolve_alias("jimmy") == keep_id
    assert _fact_count(conn, merge_id) == 0
    assert _fact_count(conn, keep_id) == 2
    with pytest.raises(KeyError):
        repo.get_entity(merge_id)
    assert repo.get_entity(keep_id).entity_id == keep_id


def test_merge_entities_guards(repo: EntityRepository) -> None:
    keep_id = repo.resolve_or_create_entity("James", EntityType.PERSON, external_ref="jim@x.com")

    with pytest.raises(ValueError, match="cannot merge an entity into itself"):
        repo.merge_entities(keep=keep_id, merge=keep_id)
    with pytest.raises(KeyError):
        repo.merge_entities(keep=keep_id, merge="person:does-not-exist")


def test_get_entity_key_error_on_miss(repo: EntityRepository) -> None:
    with pytest.raises(KeyError):
        repo.get_entity("person:does-not-exist")


def test_input_hygiene(repo: EntityRepository) -> None:
    with pytest.raises(ValueError, match="exceeds 255"):
        repo.resolve_or_create_entity("x" * 256, EntityType.PERSON)
    with pytest.raises(ValueError, match="NUL"):
        repo.resolve_or_create_entity("a\x00b", EntityType.PERSON)


def test_entity_ref_is_frozen(repo: EntityRepository) -> None:
    entity_id = repo.resolve_or_create_entity("Alice", EntityType.PERSON)
    ref = EntityRef(module="memory", entity_id=entity_id)

    assert ref.module == "memory"
    assert ref.entity_id == entity_id
    with pytest.raises(FrozenInstanceError):
        ref.module = "x"  # type: ignore[misc]


def _insert_fact(conn: sqlite3.Connection, fact_id: str, fact_key: str, entity_id: str) -> None:
    now = now_iso()
    conn.execute(
        """INSERT INTO facts (
            fact_id, fact_key, person_id, subject, relation, object, confidence,
            valid_from, valid_to, tx_from, tx_to, subject_entity_id
        ) VALUES (?, ?, ?, ?, ?, ?, 1.0, ?, ?, ?, ?, ?)""",
        (
            fact_id,
            fact_key,
            OWNER_PERSON_ID,
            "Jim",
            "likes",
            fact_id,
            now,
            SENTINEL_TS,
            now,
            SENTINEL_TS,
            entity_id,
        ),
    )


def _fact_count(conn: sqlite3.Connection, entity_id: str) -> int:
    row = conn.execute(
        "SELECT count(*) AS n FROM facts WHERE subject_entity_id = ?",
        (entity_id,),
    ).fetchone()
    return int(row["n"])
