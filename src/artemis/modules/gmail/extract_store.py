"""Owner-private SQLCipher claim-check store for structured email extracts.

Rows are keyed by trusted ``source_ref`` and store the JSON-serialised
``StructuredEmailExtract`` plus a TTL pruning timestamp.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from artemis import paths
from artemis.config import Settings
from artemis.data.sqlcipher import set_row_factory, sqlcipher_open
from artemis.identity.key_provider import KeyProvider
from artemis.identity.scope import OWNER_PRIVATE
from artemis.memory.schema import now_iso

from .structured import StructuredEmailExtract


class EmailExtractStore:
    """Owner-private, source_ref-keyed store for laundered structured extracts."""

    def __init__(self, settings: Settings, key_provider: KeyProvider) -> None:
        self._settings = settings
        self._key_provider = key_provider

    def put(self, extract: StructuredEmailExtract) -> None:
        """Insert or replace one structured extract under its trusted source_ref."""
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO email_extract (source_ref, payload_json, stored_at) "
                "VALUES (?, ?, ?)",
                (extract.source_ref, extract.model_dump_json(), now_iso()),
            )

    def fetch(self, source_ref: str) -> StructuredEmailExtract | None:
        """Fetch a structured extract by source_ref, if present."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM email_extract WHERE source_ref = ?",
                (source_ref,),
            ).fetchone()
        if row is None:
            return None
        return StructuredEmailExtract.model_validate_json(str(row["payload_json"]))

    def prune_older_than(self, cutoff_iso: str) -> None:
        """Delete extracts stored before the lexicographic UTC ISO cutoff."""
        with self._connect() as conn:
            conn.execute("DELETE FROM email_extract WHERE stored_at < ?", (cutoff_iso,))

    def _db_path(self) -> Path:
        return (
            paths.scope_dir(self._settings, OWNER_PRIVATE) / "connectors" / "gmail" / "extracts.db"
        )

    def _connect(self) -> sqlite3.Connection:
        key = self._key_provider.dek_for_scope(OWNER_PRIVATE)
        db_path = self._db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlcipher_open(db_path, key.as_hex())
        set_row_factory(conn)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS email_extract ("
            "source_ref TEXT PRIMARY KEY, "
            "payload_json TEXT NOT NULL, "
            "stored_at TEXT NOT NULL)"
        )
        return conn
