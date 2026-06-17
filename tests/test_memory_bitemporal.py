"""Golden tests for the bitemporal memory schema and repository (M4-a Slice 2a).

All tests run against a plain-sqlite + sqlite-vec in-memory database (no
encryption — the SQLCipher layer is gated behind Task 1/3/5 per the spec).
The bitemporal SQL is identical regardless of encryption layer.

Every test uses the real ``BitemporalRepository`` with a fresh in-memory DB.
"""

from __future__ import annotations

import sqlite3

import pytest
import sqlite_vec  # type: ignore[import-untyped]

from artemis.memory import BitemporalRepository, DimensionMismatchError
from artemis.memory.repository import CurrentFactConflictError, json_float_array
from artemis.memory.schema import SENTINEL_TS, create_schema, now_iso
from artemis.ports.types import PersonId

# ── Fixtures ────────────────────────────────────────────────────────────────

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
def repo(conn: sqlite3.Connection) -> BitemporalRepository:
    """Repository scoped to the owner person."""
    return BitemporalRepository(conn, OWNER_PERSON_ID)


def _add_fact(
    repo: BitemporalRepository,
    subject: str,
    relation: str,
    object_: str,
    *,
    source_turn_id: str | None = None,
    valid_from: str | None = None,
) -> str:
    """Helper: add a fact with a fixed unit vector."""
    return repo.add(
        subject=subject,
        relation=relation,
        object_=object_,
        confidence=1.0,
        embedding=_embed(object_),
        source_turn_id=source_turn_id,
        valid_from=valid_from,
    )


def _embed(text: str) -> list[float]:
    """Deterministic vector based on text hash — maps into DIMENSION space.

    Simple: normalise bytes modulo dimension so similar texts land near each
    other for basic recall testing.
    """
    h = sum(ord(c) for c in text)
    vec = [float((h >> (i * 4)) & 0xFF) for i in range(DIMENSION)]
    norm = sum(v * v for v in vec) ** 0.5 or 1.0
    return [v / norm for v in vec]


# ── Tests ───────────────────────────────────────────────────────────────────


class TestSchema:
    """Schema-level invariants: table creation, meta, indexes."""

    def test_create_schema_idempotent(self, conn: sqlite3.Connection) -> None:
        """Calling create_schema twice is safe (IF NOT EXISTS)."""
        create_schema(conn, embedder_model_id="test-fake", dimension=DIMENSION)
        # No error — good.
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        names = {r["name"] for r in tables}
        for expected in {
            "meta",
            "episodes",
            "facts",
            "facts_vec",
            "facts_fts",
            "relation_cardinality",
        }:
            assert expected in names, f"Missing table: {expected}"

    def test_meta_seeded(self, conn: sqlite3.Connection) -> None:
        """Meta table has embedder_model_id, dimension, schema_version."""
        rows = conn.execute("SELECT key, value FROM meta ORDER BY key").fetchall()
        meta = {r["key"]: r["value"] for r in rows}
        assert meta["embedder_model_id"] == "test-fake"
        assert meta["dimension"] == str(DIMENSION)
        assert meta["schema_version"] == "1"

    def test_partial_unique_index_created(self, conn: sqlite3.Connection) -> None:
        """The partial-unique index idx_facts_one_current exists."""
        idx = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_facts_one_current'"
        ).fetchone()
        assert idx is not None


class TestCardinality:
    """Cardinality registry and fact_key computation."""

    def test_seed_single_resolves(self, repo: BitemporalRepository) -> None:
        """Seed relations resolve as SINGLE."""
        assert repo.cardinality_of("lives_in") == "SINGLE"
        assert repo.cardinality_of("name") == "SINGLE"
        assert repo.cardinality_of("birthday") == "SINGLE"

    def test_unseen_defaults_multi(self, repo: BitemporalRepository) -> None:
        """Unseen relation defaults to MULTI and persists."""
        assert repo.cardinality_of("likes") == "MULTI"
        # Second call — should still be MULTI (persisted)
        assert repo.cardinality_of("likes") == "MULTI"

    def test_set_cardinality_override(self, repo: BitemporalRepository) -> None:
        """set_cardinality overrides the default."""
        repo.set_cardinality("likes", "SINGLE", source="owner")
        assert repo.cardinality_of("likes") == "SINGLE"

    def test_compute_fact_key_single_excludes_object(self, repo: BitemporalRepository) -> None:
        """SINGLE key excludes object — London and Paris hash to the same key."""
        repo.set_cardinality("lives_in", "SINGLE", source="owner")
        k1 = repo.compute_fact_key("owner", "lives_in", "London")
        k2 = repo.compute_fact_key("owner", "lives_in", "Paris")
        assert k1 == k2, "SINGLE keys must be identical regardless of object"

    def test_compute_fact_key_multi_includes_object(self, repo: BitemporalRepository) -> None:
        """MULTI key includes object — tea and coffee yield different keys."""
        k1 = repo.compute_fact_key("owner", "likes", "tea")
        k2 = repo.compute_fact_key("owner", "likes", "coffee")
        assert k1 != k2, "MULTI keys must differ for different objects"


class TestAddAndIdempotency:
    """Fact insertion and idempotent re-ingest."""

    def test_add_creates_version_row(self, repo: BitemporalRepository) -> None:
        """A basic add creates a fact with tx_to=SENTINEL."""
        fact_id = _add_fact(repo, "owner", "name", "Alice")
        row = repo.get_fact(fact_id)
        assert row.subject == "owner"
        assert row.relation == "name"
        assert row.object == "Alice"
        assert row.tx_to == SENTINEL_TS
        assert row.tx_from <= now_iso()  # sensible timestamp

    def test_idempotent_same_object_noop(self, repo: BitemporalRepository) -> None:
        """Adding the same SINGLE fact twice is a NO-OP (same fact_id)."""
        fid1 = _add_fact(repo, "owner", "name", "Alice")
        fid2 = _add_fact(repo, "owner", "name", "Alice")
        assert fid1 == fid2, "Idempotent re-ingest must return the same fact_id"
        # Only one version row.
        assert len(repo.history(repo.compute_fact_key("owner", "name", "Alice"))) == 1

    def test_add_single_current_conflict(self, repo: BitemporalRepository) -> None:
        """Adding a different object for a SINGLE key raises CurrentFactConflictError."""
        _add_fact(repo, "owner", "name", "Alice")
        with pytest.raises(CurrentFactConflictError):
            _add_fact(repo, "owner", "name", "Bob")

    def test_multi_coexistence(self, repo: BitemporalRepository) -> None:
        """MULTI facts with different objects coexist as separate rows."""
        fid_tea = _add_fact(repo, "owner", "likes", "tea")
        fid_coffee = _add_fact(repo, "owner", "likes", "coffee")
        assert fid_tea != fid_coffee
        # Both are current.
        assert repo.get_fact(fid_tea).tx_to == SENTINEL_TS
        assert repo.get_fact(fid_coffee).tx_to == SENTINEL_TS


class TestUpdateAndBitemporal:
    """UPDATE-closes-interval and as_of valid-time history."""

    def test_update_closes_prior_interval(self, repo: BitemporalRepository) -> None:
        """Update closes the old tx interval and opens a new one."""
        fid1 = _add_fact(repo, "owner", "lives_in", "London")
        key = repo.compute_fact_key("owner", "lives_in", "London")
        fid2 = repo.update(key, "Paris", 1.0, _embed("Paris"))
        assert fid1 != fid2

        # London row is closed (tx_to < SENTINEL).
        london = repo.get_fact(fid1)
        assert london.tx_to != SENTINEL_TS
        # Closed row's tx_to equals new row's tx_from (same transaction).
        paris = repo.get_fact(fid2)
        assert london.tx_to == paris.tx_from
        # Paris row is open.
        assert paris.tx_to == SENTINEL_TS

        # Exactly one tx-open row for the key.
        open_rows = repo._conn.execute(
            "SELECT COUNT(*) FROM facts WHERE fact_key = ? AND tx_to = ?",
            (key, SENTINEL_TS),
        ).fetchone()
        assert open_rows[0] == 1

    def test_partial_unique_index_guard(self, repo: BitemporalRepository) -> None:
        """Manually inserting a second tx-open row for the same key raises IntegrityError."""
        _add_fact(repo, "owner", "name", "Alice")
        key = repo.compute_fact_key("owner", "name", "Alice")
        with pytest.raises(sqlite3.IntegrityError):
            repo._conn.execute(
                """INSERT INTO facts (fact_id, fact_key, person_id, subject, relation, object,
                   confidence, valid_from, valid_to, tx_from, tx_to)
                   VALUES (?, ?, ?, ?, ?, ?, 1.0, ?, ?, ?, ?)""",
                (
                    "fake-id",
                    key,
                    OWNER_PERSON_ID,
                    "owner",
                    "name",
                    "Bob",
                    now_iso(),
                    SENTINEL_TS,
                    now_iso(),
                    SENTINEL_TS,
                ),
            )

    def test_as_of_history_bitemporal(self, repo: BitemporalRepository) -> None:
        """as_of filters by valid time; history proves bitemporal intervals."""
        _add_fact(repo, "owner", "lives_in", "London", valid_from="2026-01-01T00:00:00Z")
        key = repo.compute_fact_key("owner", "lives_in", "London")

        # Pre-update: valid_t in London's range returns London.
        as_of_pre = {r.subject: r.object for r in repo.as_of(valid_t="2026-06-01T00:00:00Z")}
        assert as_of_pre.get("owner") == "London"

        # Update: Paris valid from 2026-07-01.
        repo.update(key, "Paris", 1.0, _embed("Paris"), valid_from="2026-07-01T00:00:00Z")

        # valid_t in Paris's range returns Paris.
        as_of_paris = {r.subject: r.object for r in repo.as_of(valid_t="2026-09-01T00:00:00Z")}
        assert as_of_paris.get("owner") == "Paris"

        # History has exactly 2 rows: London (closed) + Paris (open).
        hist = repo.history(key)
        assert len(hist) == 2
        assert hist[0].object == "London"
        assert hist[0].tx_to != SENTINEL_TS  # closed
        assert hist[1].object == "Paris"
        assert hist[1].tx_to == SENTINEL_TS  # open

    def test_as_of_fact_keys_filter(self, repo: BitemporalRepository) -> None:
        """as_of with fact_keys filter returns only matching facts."""
        _add_fact(repo, "owner", "name", "Alice")
        _add_fact(repo, "owner", "likes", "tea")
        name_key = repo.compute_fact_key("owner", "name", "Alice")
        likes_key = repo.compute_fact_key("owner", "likes", "tea")

        filtered = repo.as_of(fact_keys=[name_key])
        assert len(filtered) == 1
        assert filtered[0].object == "Alice"

        both = repo.as_of(fact_keys=[name_key, likes_key])
        assert len(both) == 2


class TestTombstoneAndPurge:
    """Tombstone (never hard-delete) and purge (irreversible hard-delete)."""

    def test_tombstone_hides_from_as_of(self, repo: BitemporalRepository) -> None:
        """Tombstoned fact is invisible to as_of but history survives."""
        _add_fact(repo, "owner", "name", "Alice")
        key = repo.compute_fact_key("owner", "name", "Alice")
        repo.tombstone(key)

        # as_of returns nothing for the key.
        rows = repo.as_of(fact_keys=[key])
        assert len(rows) == 0

        # History still has the original row + tombstone.
        hist = repo.history(key)
        assert len(hist) == 2

    def test_tombstone_idempotent(self, repo: BitemporalRepository) -> None:
        """Tombstoning an already-tombstoned fact is a no-op."""
        _add_fact(repo, "owner", "name", "Alice")
        key = repo.compute_fact_key("owner", "name", "Alice")
        repo.tombstone(key)
        repo.tombstone(key)  # No error.

    def test_purge_removes_all(self, repo: BitemporalRepository) -> None:
        """Purge removes ALL version rows + vector + FTS rows."""
        fid = _add_fact(repo, "owner", "name", "Alice")
        key = repo.compute_fact_key("owner", "name", "Alice")

        removed = repo.purge(key)
        assert removed >= 1

        assert len(repo.as_of(fact_keys=[key])) == 0
        assert repo.history(key) == []

        vec_rows = repo._conn.execute(
            "SELECT COUNT(*) FROM facts_vec WHERE fact_id = ?", (fid,)
        ).fetchone()
        assert vec_rows[0] == 0, "Vector row not purged"

        fts_rows = repo._conn.execute(
            "SELECT COUNT(*) FROM facts_fts WHERE fact_id = ?", (fid,)
        ).fetchone()
        assert fts_rows[0] == 0, "FTS row not purged"

    def test_purge_empty_key(self, repo: BitemporalRepository) -> None:
        """Purging a non-existent key returns 0."""
        assert repo.purge("nonexistent-key") == 0


class TestProvenance:
    """Two-store provenance link (episodes → facts)."""

    def test_episode_and_fact_provenance(self, repo: BitemporalRepository) -> None:
        """Episodes and facts link via source_turn_id."""
        ep_id = repo.append_episode("Alice said she lives in London", turn_id="T1", role="user")
        assert ep_id is not None

        fact_id = _add_fact(repo, "owner", "lives_in", "London", source_turn_id="T1")
        fact = repo.get_fact(fact_id)
        assert fact.source_turn_id == "T1"

        episodes = repo.read_episodes(limit=10)
        texts = [e.text for e in episodes]
        assert any("London" in t for t in texts)


class TestAccessTracking:
    """bump_access increments and updates."""

    def test_bump_access_increments(self, repo: BitemporalRepository) -> None:
        """bump_access increments access_count by 1."""
        fid = _add_fact(repo, "owner", "name", "Alice")
        assert repo.get_fact(fid).access_count == 0
        repo.bump_access(fid)
        assert repo.get_fact(fid).access_count == 1
        repo.bump_access(fid)
        assert repo.get_fact(fid).access_count == 2

    def test_bump_access_updates_last_access(self, repo: BitemporalRepository) -> None:
        """bump_access sets last_access to a non-None timestamp."""
        fid = _add_fact(repo, "owner", "name", "Alice")
        assert repo.get_fact(fid).last_access is None
        repo.bump_access(fid)
        assert repo.get_fact(fid).last_access is not None


class TestVectorAndRecall:
    """sqlite-vec KNN search and dimension enforcement."""

    def test_semantic_candidates_returns_matches(self, repo: BitemporalRepository) -> None:
        """semantic_candidates returns the nearest fact by vector distance."""
        fid = _add_fact(repo, "owner", "name", "Alice")
        candidates = repo.semantic_candidates(_embed("Alice"), k=5)
        ids = [c[0] for c in candidates]
        assert fid in ids

    def test_semantic_candidates_excludes_tombstoned(self, repo: BitemporalRepository) -> None:
        """Tombstoned facts are excluded from KNN results."""
        _add_fact(repo, "owner", "name", "Alice")
        key = repo.compute_fact_key("owner", "name", "Alice")
        repo.tombstone(key)

        candidates = repo.semantic_candidates(_embed("Alice"), k=5)
        assert len(candidates) == 0, "Tombstoned facts must not appear in KNN"

    def test_dimension_lock_on_insert(self, repo: BitemporalRepository) -> None:
        """Inserting a wrong-dimension vector raises DimensionMismatchError."""
        with pytest.raises(DimensionMismatchError):
            repo.add(
                subject="owner",
                relation="name",
                object_="Bob",
                confidence=1.0,
                embedding=[0.1, 0.2],  # dimension 2, not 4
            )

    def test_json_float_array_format(self) -> None:
        """json_float_array produces valid JSON float array strings."""
        result = json_float_array([0.1, 0.2, -3.14])
        assert result == "[0.1,0.2,-3.14]"
        assert not result.startswith("[ ")
        assert ", " not in result


class TestEpisodicStore:
    """Episodic append/read operations."""

    def test_append_and_read_episodes(self, repo: BitemporalRepository) -> None:
        """Appended episodes are readable in newest-first order."""
        repo.append_episode("First observation", turn_id="T1")
        repo.append_episode("Second observation", turn_id="T2")

        episodes = repo.read_episodes(limit=10)
        assert len(episodes) == 2
        assert episodes[0].turn_id == "T2"
        assert episodes[1].turn_id == "T1"

    def test_read_episodes_limit(self, repo: BitemporalRepository) -> None:
        """read_episodes respects the limit parameter."""
        for i in range(5):
            repo.append_episode(f"Observation {i}", turn_id=f"T{i}")

        assert len(repo.read_episodes(limit=3)) == 3
        assert len(repo.read_episodes(limit=100)) == 5


class TestEdgeCases:
    """Edge cases and error handling."""

    def test_get_fact_nonexistent_raises(self, repo: BitemporalRepository) -> None:
        """get_fact on a non-existent fact_id raises KeyError."""
        with pytest.raises(KeyError):
            repo.get_fact("no-such-fact")

    def test_update_nonexistent_key(self, repo: BitemporalRepository) -> None:
        """update on a key with no current row still inserts a new version."""
        fid = repo.update("nonexistent-key", "Value", 1.0, _embed("Value"))
        fact = repo.get_fact(fid)
        assert fact.object == "Value"
        assert fact.tx_to == SENTINEL_TS

    def test_append_episode_returns_unique_ids(self, repo: BitemporalRepository) -> None:
        """Each append_episode call returns a unique episode_id."""
        ids = {repo.append_episode("test") for _ in range(100)}
        assert len(ids) == 100

    def test_sentinel_ts_is_constant(self) -> None:
        """SENTINEL_TS is the expected max timestamp."""
        assert SENTINEL_TS == "9999-12-31T23:59:59Z"
