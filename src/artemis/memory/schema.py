"""Schema DDL for the two-store bitemporal memory system.

Defines the SQL schema shared by both the encrypted (SQLCipher + sqlite-vec)
production path and the plain-sqlite + sqlite-vec fallback used for testing.
The bitemporal SQL is identical regardless of encryption layer — only the
``PRAGMA key`` call differs.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3

SENTINEL_TS: str = "9999-12-31T23:59:59Z"
"""Half-open interval upper bound — marks an open (current) interval."""

SEED_SINGLE_RELATIONS: frozenset[str] = frozenset(
    {
        "lives_in",
        "birthday",
        "name",
        "age",
        "employer",
        "home_address",
        "phone_number",
        "email",
    }
)
"""Relations where at most one value is expected per person.

For SINGLE-cardinality relations the ``fact_key`` excludes the *object*,
so the same *(person, subject, relation)* always maps to the same logical
fact across updates.
"""

DEFAULT_CARDINALITY: str = "MULTI"
"""Fallback cardinality for unrecognised relations — fail-safe (never overwrite)."""


def now_iso() -> str:
    """Current UTC timestamp as ISO-8601 with Z suffix, second precision.

    Returns:
        e.g. ``"2026-06-17T14:30:00Z"``
    """
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: UP017


def create_schema(
    conn: sqlite3.Connection,
    *,
    embedder_model_id: str,
    dimension: int,
) -> None:
    """Idempotently create all tables, indexes, and seed data.

    All statements use ``IF NOT EXISTS`` so repeated calls are safe.

    Args:
        conn: An open sqlite3 (or APSW) connection with sqlite-vec loaded.
        embedder_model_id: Model identifier stored in ``meta``.
        dimension: Embedding vector dimension — locked at schema creation
            (a different dimension on reopen raises ``DimensionMismatchError``).

    Raises:
        sqlite3.OperationalError: If sqlite-vec is not loaded (``facts_vec``
            creation will fail).
    """
    conn.executescript("PRAGMA journal_mode=WAL;")
    conn.executescript("PRAGMA foreign_keys=ON;")

    # ── meta table ──────────────────────────────────────────────────────────
    conn.execute(
        """CREATE TABLE IF NOT EXISTS meta (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )"""
    )
    # Seed meta on first creation (idempotent via INSERT OR IGNORE).
    conn.execute(
        "INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)",
        ("embedder_model_id", embedder_model_id),
    )
    conn.execute(
        "INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)",
        ("dimension", str(dimension)),
    )
    conn.execute(
        "INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)",
        ("schema_version", "1"),
    )

    # ── episodic store (append-mostly bitemporal event log) ──────────────────
    conn.execute(
        f"""CREATE TABLE IF NOT EXISTS episodes (
            episode_id TEXT PRIMARY KEY,
            person_id  TEXT NOT NULL,
            turn_id    TEXT,
            role       TEXT,
            text       TEXT NOT NULL,
            valid_from TEXT NOT NULL,
            valid_to   TEXT NOT NULL DEFAULT '{SENTINEL_TS}',
            tx_from    TEXT NOT NULL,
            tx_to      TEXT NOT NULL DEFAULT '{SENTINEL_TS}',
            created_at TEXT NOT NULL
        )"""
    )

    # ── semantic store (bitemporal fact-version table) ──────────────────────
    conn.execute(
        f"""CREATE TABLE IF NOT EXISTS facts (
            fact_id                TEXT PRIMARY KEY,
            fact_key               TEXT NOT NULL,
            person_id              TEXT NOT NULL,
            subject                TEXT NOT NULL,
            relation               TEXT NOT NULL,
            object                 TEXT NOT NULL,
            confidence             REAL NOT NULL,
            valid_from             TEXT NOT NULL,
            valid_to               TEXT NOT NULL DEFAULT '{SENTINEL_TS}',
            tx_from                TEXT NOT NULL,
            tx_to                  TEXT NOT NULL DEFAULT '{SENTINEL_TS}',
            source_turn_id         TEXT,
            extracted_at           TEXT,
            extractor_model        TEXT,
            salience               REAL NOT NULL DEFAULT 1.0,
            access_count           INTEGER NOT NULL DEFAULT 0,
            last_access            TEXT,
            keywords               TEXT,
            contextual_description TEXT,
            linked_ids             TEXT
        )"""
    )

    # Partial-unique index: at most one tx-open row per logical fact.
    conn.execute(
        f"""CREATE UNIQUE INDEX IF NOT EXISTS idx_facts_one_current
            ON facts (fact_key) WHERE tx_to = '{SENTINEL_TS}'"""
    )
    # Supporting indexes for range scans.
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_facts_valid ON facts (person_id, valid_from, valid_to)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_facts_tx ON facts (person_id, tx_from, tx_to)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_facts_key_tx ON facts (fact_key, tx_from)")

    # ── sqlite-vec vector index ─────────────────────────────────────────────
    conn.execute(
        f"""CREATE VIRTUAL TABLE IF NOT EXISTS facts_vec
            USING vec0(
                fact_id TEXT PRIMARY KEY,
                embedding FLOAT[{dimension}] distance_metric=cosine
            )"""
    )

    # ── FTS5 full-text index (PLAIN, not contentless) ───────────────────────
    conn.executescript(
        """CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts
            USING fts5(fact_id, text)"""
    )

    # ── relation-cardinality registry ───────────────────────────────────────
    conn.execute(
        """CREATE TABLE IF NOT EXISTS relation_cardinality (
            relation    TEXT PRIMARY KEY,
            cardinality TEXT NOT NULL CHECK (cardinality IN ('SINGLE', 'MULTI')),
            source      TEXT NOT NULL DEFAULT 'seed'
        )"""
    )
    # Seed SINGLE relations (idempotent).
    for rel in SEED_SINGLE_RELATIONS:
        conn.execute(
            "INSERT OR IGNORE INTO relation_cardinality (relation, cardinality, source) VALUES (?, 'SINGLE', 'seed')",
            (rel,),
        )
