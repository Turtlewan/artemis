"""Bitemporal repository — the core bitemporal fact store operations.

Every fact write goes through one of: ``add`` (create), ``update`` (close
interval + insert), ``tombstone`` (demote, never destroy). The ``as_of``
query enforces the four-timestamp bitemporal filter at read time.

The ``BitemporalRepository`` is a thin SQL wrapper over the schema defined
in :mod:`artemis.memory.schema`. It does **not** handle encryption, key
management, or the ``MemoryStore`` port adapter (those are Tasks 3/5).
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from artemis.memory.schema import (
    DEFAULT_CARDINALITY,
    SENTINEL_TS,
    now_iso,
)

if TYPE_CHECKING:
    import sqlite3

    from artemis.ports.types import PersonId, Vector


# ── Exception types (public) ────────────────────────────────────────────────


class DimensionMismatchError(Exception):
    """Raised when an embedding vector has the wrong dimension."""


class CurrentFactConflictError(Exception):
    """Raised when ``add`` is called for a SINGLE-cardinality key that already
    has a different current object — the caller should have used ``update``."""


# ── Return-type dataclasses ─────────────────────────────────────────────────


@dataclass(frozen=True)
class FactRow:
    """Mirrors a ``facts`` table row exactly (column order)."""

    fact_id: str
    fact_key: str
    person_id: str
    subject: str
    relation: str
    object: str
    confidence: float
    valid_from: str
    valid_to: str
    tx_from: str
    tx_to: str
    source_turn_id: str | None
    extracted_at: str | None
    extractor_model: str | None
    salience: float
    access_count: int
    last_access: str | None
    keywords: str | None
    contextual_description: str | None
    linked_ids: str | None
    subject_entity_id: str | None = None  # added by M4-d-2 migration; default None pre-migration


@dataclass(frozen=True)
class EpisodeRow:
    """Mirrors an ``episodes`` table row exactly (column order)."""

    episode_id: str
    person_id: str
    turn_id: str | None
    role: str | None
    text: str
    valid_from: str
    valid_to: str
    tx_from: str
    tx_to: str
    created_at: str


# ── Helpers ─────────────────────────────────────────────────────────────────


_FACT_COLUMNS: str = (
    "fact_id, fact_key, person_id, subject, relation, object, "
    "confidence, valid_from, valid_to, tx_from, tx_to, "
    "source_turn_id, extracted_at, extractor_model, "
    "salience, access_count, last_access, "
    "keywords, contextual_description, linked_ids, subject_entity_id"
)


def _row_to_fact(row: tuple[Any, ...]) -> FactRow:
    """Convert a ``facts`` table row tuple to a ``FactRow``."""
    return FactRow(
        fact_id=row[0],
        fact_key=row[1],
        person_id=row[2],
        subject=row[3],
        relation=row[4],
        object=row[5],
        confidence=row[6],
        valid_from=row[7],
        valid_to=row[8],
        tx_from=row[9],
        tx_to=row[10],
        source_turn_id=row[11],
        extracted_at=row[12],
        extractor_model=row[13],
        salience=row[14],
        access_count=row[15],
        last_access=row[16],
        keywords=row[17],
        contextual_description=row[18],
        linked_ids=row[19],
        subject_entity_id=row[20],
    )


# ── BitemporalRepository ────────────────────────────────────────────────────


class BitemporalRepository:
    """Bitemporal fact repository — all operations are in one transaction.

    Constructed with an open sqlite3 connection and a ``person_id``.
    The connection MUST have sqlite-vec loaded (``facts_vec`` queries).

    All timestamp args default to ``now_iso()``. All writes go through a
    single transaction per call.

    Args:
        conn: An open sqlite3 connection (with sqlite-vec loaded).
        person_id: The scoped person identifier for all operations.
    """

    def __init__(self, conn: sqlite3.Connection, person_id: PersonId) -> None:
        self._conn = conn
        self._person_id = person_id

    @property
    def conn(self) -> sqlite3.Connection:
        """Return the underlying owner-scoped SQLite connection."""
        return self._conn

    @property
    def person_id(self) -> PersonId:
        """Return the repository's owner person id."""
        return self._person_id

    # ── Cardinality helpers ─────────────────────────────────────────────────

    def cardinality_of(self, relation: str) -> str:
        """Return ``SINGLE`` or ``MULTI`` for a relation.

        Unknown relations are inserted with ``DEFAULT_CARDINALITY`` and
        returned — the registry is self-teaching.
        """
        row = self._conn.execute(
            "SELECT cardinality FROM relation_cardinality WHERE relation = ?",
            (relation,),
        ).fetchone()
        if row is not None:
            return str(row[0])
        # First sighting — insert default and return.
        self._conn.execute(
            "INSERT OR IGNORE INTO relation_cardinality (relation, cardinality, source) "
            "VALUES (?, ?, 'seed')",
            (relation, DEFAULT_CARDINALITY),
        )
        return DEFAULT_CARDINALITY

    def set_cardinality(self, relation: str, cardinality: str, *, source: str) -> None:
        """Upsert a relation's cardinality.

        Args:
            relation: The relation name.
            cardinality: ``SINGLE`` or ``MULTI``.
            source: Who set this (e.g. ``'owner'``, ``'teacher'``).
        """
        self._conn.execute(
            "INSERT INTO relation_cardinality (relation, cardinality, source) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(relation) DO UPDATE SET cardinality=excluded.cardinality, source=excluded.source",
            (relation, cardinality, source),
        )

    def compute_fact_key(self, subject: str, relation: str, object_: str) -> str:
        """Compute the cardinality-aware logical-fact key.

        SINGLE: ``sha256(person_id ␟ subject ␟ relation)`` — object excluded,
        so changing the object maps to the **same** key (UPDATE semantic).

        MULTI: ``sha256(person_id ␟ subject ␟ relation ␟ object)`` — different
        objects yield different keys so values coexist.

        The separator is ``\\x1f`` (unit separator). The encoding is UTF-8.
        The key is stable — golden-test-asserted.
        """
        cardinality = self.cardinality_of(relation)
        parts: list[str] = [self._person_id, subject, relation]
        if cardinality == "MULTI":
            parts.append(object_)
        raw = "\x1f".join(parts).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    # ── Write primitives ────────────────────────────────────────────────────

    def add(
        self,
        subject: str,
        relation: str,
        object_: str,
        confidence: float,
        embedding: Vector,
        *,
        valid_from: str | None = None,
        source_turn_id: str | None = None,
        extractor_model: str | None = None,
        keywords: tuple[str, ...] = (),
        contextual_description: str | None = None,
        linked_ids: tuple[str, ...] = (),
        subject_entity_id: str | None = None,
    ) -> str:
        """Insert a new fact version.

        For SINGLE-cardinality relations: if the current (tx-open) row has the
        **same** object, this is a NO-OP (idempotent re-ingest). If it has a
        **different** object, raises :class:`CurrentFactConflictError` — the caller
        should have used :meth:`update`.

        For MULTI-cardinality relations: every unique ``(subject, relation, object)``
        creates a separate logical fact (different ``fact_key``), so ``add``
        is always the correct operation.

        Returns:
            The new ``fact_id``.

        ``subject_entity_id`` is the optional M4-d-1 PERSON-entity link written
        at fact creation time. The idempotent NO-OP path does not compare or
        backfill it, so old or degraded rows may legitimately keep ``None``.
        """
        vf = valid_from or now_iso()
        now = now_iso()
        fact_key = self.compute_fact_key(subject, relation, object_)

        # ── Idempotency guard ──
        current = self._current_row(fact_key)
        if current is not None:
            if current.object == object_:
                # Same object, same key — idempotent NO-OP.
                return current.fact_id
            # Different object for SINGLE → caller should have used update().
            if self.cardinality_of(relation) == "SINGLE":
                raise CurrentFactConflictError(fact_key)

        # ── Insert new version row ──
        fact_id = uuid.uuid4().hex
        kw_str = " ".join(keywords) if keywords else None
        linked_str = " ".join(linked_ids) if linked_ids else None

        self._conn.execute(
            """INSERT INTO facts (
                fact_id, fact_key, person_id, subject, relation, object,
                confidence, valid_from, valid_to, tx_from, tx_to,
                source_turn_id, extracted_at, extractor_model,
                salience, access_count, last_access,
                keywords, contextual_description, linked_ids, subject_entity_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1.0, 0, NULL, ?, ?, ?, ?)""",
            (
                fact_id,
                fact_key,
                self._person_id,
                subject,
                relation,
                object_,
                confidence,
                vf,
                SENTINEL_TS,
                now,
                SENTINEL_TS,
                source_turn_id,
                now,
                extractor_model,
                kw_str,
                contextual_description,
                linked_str,
                subject_entity_id,
            ),
        )

        # ── Vector + FTS ──
        self._insert_embedding(fact_id, embedding)
        self._insert_fts(fact_id, subject, relation, object_)

        return fact_id

    def update(
        self,
        fact_key: str,
        new_object: str,
        new_confidence: float,
        embedding: Vector,
        *,
        valid_from: str | None = None,
        source_turn_id: str | None = None,
        extractor_model: str | None = None,
        keywords: tuple[str, ...] = (),
        contextual_description: str | None = None,
        linked_ids: tuple[str, ...] = (),
        subject_entity_id: str | None = None,
    ) -> str:
        """Close the current interval and insert a new version (the U path).

        In one transaction:
        1. Find the current (tx-open) row for ``fact_key``.
        2. Close its tx interval: ``tx_to = now``.
        3. Insert a new version row with the updated object.
        4. Add its vector + FTS rows.

        Returns:
            The new ``fact_id``.

        ``subject_entity_id`` is copied onto the new version row only. Closed
        historical rows retain the link value they had when written.
        """
        vf = valid_from or now_iso()
        now = now_iso()
        current = self._current_row(fact_key)

        # ── Close current interval ──
        if current is not None:
            self._conn.execute(
                "UPDATE facts SET tx_to = ? WHERE fact_id = ?",
                (now, current.fact_id),
            )

        # ── Insert new version ──
        fact_id = uuid.uuid4().hex
        kw_str = " ".join(keywords) if keywords else None
        linked_str = " ".join(linked_ids) if linked_ids else None
        relation = current.relation if current else ""
        subject = current.subject if current else ""

        self._conn.execute(
            """INSERT INTO facts (
                fact_id, fact_key, person_id, subject, relation, object,
                confidence, valid_from, valid_to, tx_from, tx_to,
                source_turn_id, extracted_at, extractor_model,
                salience, access_count, last_access,
                keywords, contextual_description, linked_ids, subject_entity_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1.0, 0, NULL, ?, ?, ?, ?)""",
            (
                fact_id,
                fact_key,
                self._person_id,
                subject,
                relation,
                new_object,
                new_confidence,
                vf,
                SENTINEL_TS,
                now,
                SENTINEL_TS,
                source_turn_id,
                now,
                extractor_model,
                kw_str,
                contextual_description,
                linked_str,
                subject_entity_id,
            ),
        )

        # ── Vector + FTS ──
        self._insert_embedding(fact_id, embedding)
        self._insert_fts(fact_id, subject, relation, new_object)

        return fact_id

    def tombstone(self, fact_key: str, *, valid_from: str | None = None) -> None:
        """Demote a logical fact — the D path (never hard-delete).

        Closes the current row's tx interval AND inserts a new tombstone
        version row with ``confidence=0.0`` and ``valid_to`` set to
        ``valid_from`` (or now), so ``as_of(now)`` returns nothing for
        this key. All prior history remains intact.
        """
        now = now_iso()
        vt = valid_from or now
        current = self._current_row(fact_key)

        if current is None:
            return  # Nothing to tombstone.

        # ── Close current interval ──
        self._conn.execute(
            "UPDATE facts SET tx_to = ? WHERE fact_id = ?",
            (now, current.fact_id),
        )

        # ── Insert tombstone version ──
        tombstone_id = uuid.uuid4().hex
        self._conn.execute(
            """INSERT INTO facts (
                fact_id, fact_key, person_id, subject, relation, object,
                confidence, valid_from, valid_to, tx_from, tx_to,
                source_turn_id, extracted_at, extractor_model,
                salience, access_count, last_access,
                keywords, contextual_description, linked_ids
            ) VALUES (?, ?, ?, ?, ?, ?, 0.0, ?, ?, ?, ?, NULL, NULL, NULL, 0.0, 0, NULL, NULL, NULL, NULL)""",
            (
                tombstone_id,
                fact_key,
                self._person_id,
                current.subject,
                current.relation,
                current.object,
                vt,  # valid_from = tombstone time
                vt,  # valid_to = vt → empty half-open [vt, vt) so as_of finds nothing
                now,
                SENTINEL_TS,
            ),
        )

        # No vector or FTS — tombstone rows are excluded from recall.

    # ── Read primitives ─────────────────────────────────────────────────────

    def as_of(
        self,
        valid_t: str | None = None,
        tx_t: str | None = None,
        *,
        fact_keys: Sequence[str] | None = None,
    ) -> list[FactRow]:
        """Return at most one current row per ``fact_key`` at the given times.

        The bitemporal predicate:
            ``valid_from <= valid_t < valid_to AND tx_from <= tx_t < tx_to``

        Defaults both to ``now_iso()``.
        """
        vt = valid_t or now_iso()
        tt = tx_t or now_iso()

        query = (
            f"SELECT {_FACT_COLUMNS} FROM facts "
            "WHERE valid_from <= ? AND valid_to > ? "
            "AND tx_from <= ? AND tx_to > ?"
        )
        params: list[str] = [vt, vt, tt, tt]

        if fact_keys:
            placeholders = ",".join("?" for _ in fact_keys)
            query += f" AND fact_key IN ({placeholders})"
            params.extend(fact_keys)

        rows = self._conn.execute(query, params).fetchall()
        return [_row_to_fact(r) for r in rows]

    def history(self, fact_key: str) -> list[FactRow]:
        """All version rows for a logical fact, ordered by ``tx_from``."""
        rows = self._conn.execute(
            f"SELECT {_FACT_COLUMNS} FROM facts WHERE fact_key = ? ORDER BY tx_from",
            (fact_key,),
        ).fetchall()
        return [_row_to_fact(r) for r in rows]

    def facts_for_entity(self, entity_id: str, *, as_of_tx: str | None = None) -> list[FactRow]:
        """Return current facts linked to a subject entity.

        The subject link is write-time only: rows first written without an entity
        link are not backfilled by later idempotent writes, and historical rows
        may have ``subject_entity_id`` set to ``None``.
        """
        now = as_of_tx or now_iso()
        rows = self._conn.execute(
            f"""SELECT {_FACT_COLUMNS}
               FROM facts
               WHERE subject_entity_id = ?
                 AND tx_from <= ? AND tx_to > ?
                 AND valid_from <= ? AND valid_to > ?
               ORDER BY relation, object""",
            (entity_id, now, now, now, now),
        ).fetchall()
        return [_row_to_fact(r) for r in rows]

    def semantic_candidates(
        self,
        query_embedding: Vector,
        k: int,
        *,
        as_of_tx: str | None = None,
    ) -> list[tuple[str, float]]:
        """sqlite-vec KNN search over current facts, returning ``(fact_id, distance)``.

        Results are restricted to tx-open rows (currently believed facts).
        The distance metric is cosine (set in the schema), so lower = more
        similar. Convert to similarity via ``1 - distance`` in the caller.

        Args:
            query_embedding: The query vector.
            k: Number of nearest neighbours.
            as_of_tx: Optional tx bound (defaults to now).
        """
        tt = as_of_tx or now_iso()

        # vec0 KNN + bitemporal join through tx-open filter.
        rows = self._conn.execute(
            """SELECT v.fact_id, v.distance
                FROM facts_vec v
                INNER JOIN facts f ON f.fact_id = v.fact_id
                WHERE f.tx_from <= ? AND f.tx_to > ?
                AND v.embedding MATCH ?
                AND k = ?
                ORDER BY v.distance""",
            (tt, tt, json_float_array(list(query_embedding)), k),
        ).fetchall()
        return [(r[0], r[1]) for r in rows]

    def get_fact(self, fact_id: str) -> FactRow:
        """Look up a single fact-version row by its version-row primary key.

        No bitemporal filtering — returns whichever version row has this
        exact ``fact_id``.

        Raises:
            KeyError: If no row with the given ``fact_id`` exists.
        """
        row = self._conn.execute(
            f"SELECT {_FACT_COLUMNS} FROM facts WHERE fact_id = ?",
            (fact_id,),
        ).fetchone()
        if row is None:
            raise KeyError(fact_id)
        return _row_to_fact(row)

    # ── Access tracking ─────────────────────────────────────────────────────

    def bump_access(self, fact_id: str) -> None:
        """Increment ``access_count`` and update ``last_access`` to now."""
        now = now_iso()
        self._conn.execute(
            "UPDATE facts SET access_count = access_count + 1, last_access = ? WHERE fact_id = ?",
            (now, fact_id),
        )

    # ── Hard-delete (owner-only, irreversible) ──────────────────────────────

    def purge(self, fact_key: str) -> int:
        """Permanently delete ALL version rows for a ``fact_key``.

        Also removes matching ``facts_vec`` and ``facts_fts`` rows.
        Returns the number of rows removed from ``facts``.
        Irreversible — owner-only.

        Args:
            fact_key: The logical-fact key to purge entirely.

        Returns:
            Number of version rows deleted.
        """
        # Collect fact_ids first.
        ids = [
            r[0]
            for r in self._conn.execute(
                "SELECT fact_id FROM facts WHERE fact_key = ?", (fact_key,)
            ).fetchall()
        ]
        if not ids:
            return 0

        # Delete from FTS.
        for fid in ids:
            self._conn.execute("DELETE FROM facts_fts WHERE fact_id = ?", (fid,))
        # Delete from vec (bulk with IN).
        placeholders = ",".join("?" for _ in ids)
        self._conn.execute(f"DELETE FROM facts_vec WHERE fact_id IN ({placeholders})", ids)
        # Delete from facts.
        self._conn.execute("DELETE FROM facts WHERE fact_key = ?", (fact_key,))
        return len(ids)

    # ── Episodic helpers ────────────────────────────────────────────────────

    def append_episode(
        self,
        text: str,
        *,
        turn_id: str | None = None,
        role: str | None = None,
        valid_from: str | None = None,
    ) -> str:
        """Append a raw observation to the episodic log.

        Returns:
            The new ``episode_id``.
        """
        episode_id = uuid.uuid4().hex
        now = now_iso()
        vf = valid_from or now
        self._conn.execute(
            """INSERT INTO episodes (
                episode_id, person_id, turn_id, role, text,
                valid_from, valid_to, tx_from, tx_to, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                episode_id,
                self._person_id,
                turn_id,
                role,
                text,
                vf,
                SENTINEL_TS,
                now,
                SENTINEL_TS,
                now,
            ),
        )
        return episode_id

    def read_episodes(
        self,
        *,
        as_of_tx: str | None = None,
        limit: int = 50,
    ) -> list[EpisodeRow]:
        """Read the most recent episodes (tx-open rows, newest first)."""
        tt = as_of_tx or now_iso()
        rows = self._conn.execute(
            """SELECT episode_id, person_id, turn_id, role, text,
                      valid_from, valid_to, tx_from, tx_to, created_at
               FROM episodes
               WHERE tx_from <= ? AND tx_to > ?
               ORDER BY rowid DESC
               LIMIT ?""",
            (tt, tt, limit),
        ).fetchall()
        return [
            EpisodeRow(
                episode_id=r[0],
                person_id=r[1],
                turn_id=r[2],
                role=r[3],
                text=r[4],
                valid_from=r[5],
                valid_to=r[6],
                tx_from=r[7],
                tx_to=r[8],
                created_at=r[9],
            )
            for r in rows
        ]

    # ── Internal helpers ────────────────────────────────────────────────────

    def _current_row(self, fact_key: str) -> FactRow | None:
        """Return the tx-open row for a ``fact_key``, or ``None``."""
        row = self._conn.execute(
            f"SELECT {_FACT_COLUMNS} FROM facts WHERE fact_key = ? AND tx_to = ?",
            (fact_key, SENTINEL_TS),
        ).fetchone()
        return _row_to_fact(row) if row is not None else None

    def _insert_embedding(self, fact_id: str, embedding: Vector) -> None:
        # Verify dimension from meta.
        dim_row = self._conn.execute("SELECT value FROM meta WHERE key = 'dimension'").fetchone()
        expected_dim = int(dim_row[0]) if dim_row else len(list(embedding))
        actual = list(embedding)
        if len(actual) != expected_dim:
            raise DimensionMismatchError(f"Expected dimension {expected_dim}, got {len(actual)}")
        self._conn.execute(
            "INSERT INTO facts_vec (fact_id, embedding) VALUES (?, ?)",
            (fact_id, json_float_array(actual)),
        )

    def _insert_fts(self, fact_id: str, subject: str, relation: str, object_: str) -> None:
        text = f"{subject} {relation} {object_}"
        self._conn.execute(
            "INSERT INTO facts_fts (fact_id, text) VALUES (?, ?)",
            (fact_id, text),
        )


def json_float_array(values: list[float]) -> str:
    """Format a float list as a JSON string for sqlite-vec MATCH queries.

    sqlite-vec expects the embedding parameter as a JSON-encoded float array
    string, e.g. ``'[0.1, 0.2, 0.3]'``.

    Args:
        values: The embedding vector as a list of floats.

    Returns:
        A JSON string representation of the float array.
    """
    return "[" + ",".join(str(v) for v in values) + "]"
