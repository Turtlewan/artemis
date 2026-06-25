"""Owner-private idempotency ledger for reaction dispatch.

The reaction ledger stores only deduplication keys, fire timestamps, counts, and
optional state hashes. It does not store domain rows or reaction-owned state;
the spoke module owns that state (ADR-021 I-8=C).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from artemis import paths
from artemis.config import Settings
from artemis.data.sqlcipher import sqlcipher_open
from artemis.identity.key_provider import KeyProvider
from artemis.identity.scope import OWNER_PRIVATE


class ReactionLedger:
    """SQLCipher-backed fire-once and stateful-refire ledger."""

    def __init__(self, settings: Settings, key_provider: KeyProvider) -> None:
        self._settings = settings
        self._key_provider = key_provider

    def _db_path(self) -> Path:
        return paths.scope_dir(self._settings, OWNER_PRIVATE) / "reactions" / "reaction_ledger.db"

    def _connect(self) -> sqlite3.Connection:
        key = self._key_provider.dek_for_scope(OWNER_PRIVATE)
        db_path = self._db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlcipher_open(db_path, key.as_hex())
        conn.execute(
            "CREATE TABLE IF NOT EXISTS reaction_ledger ("
            "rule_name TEXT NOT NULL, "
            "stable_key TEXT NOT NULL, "
            "first_fired_at TEXT NOT NULL, "
            "last_fired_at TEXT NOT NULL, "
            "fire_count INTEGER NOT NULL DEFAULT 1, "
            "state_hash TEXT, "
            "PRIMARY KEY (rule_name, stable_key))"
        )
        return conn

    def try_claim(self, rule_name: str, stable_key: str, *, now: str) -> bool:
        """Claim a fire-once reaction key with ``INSERT OR IGNORE``."""
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO reaction_ledger "
                "(rule_name, stable_key, first_fired_at, last_fired_at, fire_count) "
                "VALUES (?, ?, ?, ?, 1)",
                (rule_name, stable_key, now, now),
            )
            return cursor.rowcount == 1

    def record_refire(
        self,
        rule_name: str,
        stable_key: str,
        *,
        now: str,
        state_hash: str | None = None,
    ) -> None:
        """Record a stateful reaction occurrence as one row updated in place."""
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE reaction_ledger "
                "SET last_fired_at = ?, fire_count = fire_count + 1, state_hash = ? "
                "WHERE rule_name = ? AND stable_key = ?",
                (now, state_hash, rule_name, stable_key),
            )
            if cursor.rowcount == 0:
                conn.execute(
                    "INSERT INTO reaction_ledger "
                    "(rule_name, stable_key, first_fired_at, last_fired_at, fire_count, state_hash) "
                    "VALUES (?, ?, ?, ?, 1, ?)",
                    (rule_name, stable_key, now, now, state_hash),
                )

    def state_hash(self, rule_name: str, stable_key: str) -> str | None:
        """Return the current state digest for a stateful reaction key."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT state_hash FROM reaction_ledger WHERE rule_name = ? AND stable_key = ?",
                (rule_name, stable_key),
            ).fetchone()
        return None if row is None else row[0]
