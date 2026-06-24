from __future__ import annotations

import sqlite3
from collections.abc import Sequence

import pytest
import sqlite_vec  # type: ignore[import-untyped]

from artemis.memory import OwnerConfirmationRequired, OwnerMemory
from artemis.memory.decay import sweep_tombstone_candidates
from artemis.memory.repository import BitemporalRepository
from artemis.memory.schema import create_schema, now_iso
from artemis.ports.types import PersonId, Vector

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
def owner(repo: BitemporalRepository) -> OwnerMemory:
    return OwnerMemory(repo, FakeEmbedder())


class FakeEmbedder:
    @property
    def dimension(self) -> int:
        return DIMENSION

    async def embed_documents(self, texts: Sequence[str]) -> list[Vector]:
        return [_embed(text) for text in texts]

    async def embed_query(self, query: str) -> Vector:
        return _embed(query)


def test_tombstone_sweep_flags_sub_floor_only_and_does_not_delete(
    repo: BitemporalRepository,
) -> None:
    stale_id = _add_fact(
        repo,
        "owner",
        "likes",
        "old-tea",
        confidence=0.2,
        valid_from="2000-01-01T00:00:00Z",
    )
    healthy_id = _add_fact(
        repo,
        "owner",
        "lives_in",
        "Paris",
        valid_from=now_iso(),
    )
    rows = repo.as_of()
    row_count_before = _fact_count(repo)

    candidates = sweep_tombstone_candidates(rows, now=now_iso())

    stale = repo.get_fact(stale_id)
    healthy = repo.get_fact(healthy_id)
    assert candidates == [stale.fact_key]
    assert healthy.fact_key not in candidates
    assert _fact_count(repo) == row_count_before
    assert repo.as_of(fact_keys=[stale.fact_key]) == [stale]
    assert repo.as_of(fact_keys=[healthy.fact_key]) == [healthy]


@pytest.mark.asyncio
async def test_owner_edit_requires_confirmation_and_preserves_history(
    owner: OwnerMemory,
    repo: BitemporalRepository,
) -> None:
    _add_fact(
        repo,
        "owner",
        "lives_in",
        "Paris",
        source_turn_id="T1",
        extractor_model="fake-extractor",
    )
    fact_key = repo.compute_fact_key("owner", "lives_in", "Paris")

    with pytest.raises(OwnerConfirmationRequired):
        await owner.edit_fact(fact_key, "London", confirm=False)

    new_fact_id = await owner.edit_fact(fact_key, "London", confirm=True)

    current = owner.view_fact(fact_key)
    history = owner.history(fact_key)
    assert current.fact_id == new_fact_id
    assert current.object == "London"
    assert current.source_turn_id == "owner-edit"
    assert current.extractor_model == "owner"
    assert any(row.object == "Paris" for row in history)
    assert len(history) == 2


def test_owner_list_view_history_include_provenance(
    owner: OwnerMemory,
    repo: BitemporalRepository,
) -> None:
    _add_fact(
        repo,
        "owner",
        "name",
        "Alice",
        confidence=0.87,
        source_turn_id="T-name",
        extractor_model="fake-extractor",
    )
    fact_key = repo.compute_fact_key("owner", "name", "Alice")

    current = owner.list_current()
    viewed = owner.view_fact(fact_key)
    history = owner.history(fact_key)

    assert [row.fact_key for row in current] == [fact_key]
    assert viewed.object == "Alice"
    assert viewed.source_turn_id == "T-name"
    assert viewed.extracted_at is not None
    assert viewed.extractor_model == "fake-extractor"
    assert viewed.confidence == pytest.approx(0.87)
    assert history == [viewed]


def test_owner_delete_tombstones_but_purge_hard_deletes(
    owner: OwnerMemory,
    repo: BitemporalRepository,
) -> None:
    first_id = _add_fact(repo, "owner", "name", "Alice")
    fact_key = repo.compute_fact_key("owner", "name", "Alice")

    owner.delete_fact(fact_key)

    with pytest.raises(KeyError):
        owner.view_fact(fact_key)
    assert repo.as_of(valid_t=now_iso(), fact_keys=[fact_key]) == []
    assert owner.history(fact_key) != []

    with pytest.raises(OwnerConfirmationRequired):
        owner.purge_fact(fact_key, confirm=False)

    removed = owner.purge_fact(fact_key, confirm=True)

    assert removed == 2
    assert owner.history(fact_key) == []
    assert _vec_count(repo, first_id) == 0
    assert _fts_count(repo, first_id) == 0


def _add_fact(
    repo: BitemporalRepository,
    subject: str,
    relation: str,
    object_: str,
    *,
    confidence: float = 1.0,
    source_turn_id: str | None = None,
    extractor_model: str | None = None,
    valid_from: str | None = None,
) -> str:
    return repo.add(
        subject=subject,
        relation=relation,
        object_=object_,
        confidence=confidence,
        embedding=_embed(f"{subject} {relation} {object_}"),
        source_turn_id=source_turn_id,
        extractor_model=extractor_model,
        valid_from=valid_from,
    )


def _embed(text: str) -> list[float]:
    h = sum(ord(char) for char in text)
    vec = [float((h >> (i * 4)) & 0xFF) for i in range(DIMENSION)]
    norm = sum(value * value for value in vec) ** 0.5 or 1.0
    return [value / norm for value in vec]


def _fact_count(repo: BitemporalRepository) -> int:
    row = repo._conn.execute("SELECT COUNT(*) FROM facts").fetchone()
    return int(row[0])


def _vec_count(repo: BitemporalRepository, fact_id: str) -> int:
    row = repo._conn.execute(
        "SELECT COUNT(*) FROM facts_vec WHERE fact_id = ?", (fact_id,)
    ).fetchone()
    return int(row[0])


def _fts_count(repo: BitemporalRepository, fact_id: str) -> int:
    row = repo._conn.execute(
        "SELECT COUNT(*) FROM facts_fts WHERE fact_id = ?", (fact_id,)
    ).fetchone()
    return int(row[0])
