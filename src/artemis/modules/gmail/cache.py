"""Owner-private SQLCipher read cache for Gmail metadata and sync cursor."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from artemis import paths
from artemis.config import Settings
from artemis.data.sqlcipher import set_row_factory, sqlcipher_open
from artemis.identity.key_provider import KeyProvider
from artemis.identity.scope import OWNER_PRIVATE

from .client import MailCategory


@dataclass(frozen=True)
class CachedMessage:
    """Cached metadata for one Gmail message. Bodies are never stored here."""

    message_id: str
    thread_id: str
    history_id: str
    sender: str
    subject: str
    internal_date_ms: int
    category: MailCategory
    snippet: str
    label_ids: tuple[str, ...]
    has_attachments: bool
    unread: bool
    important: bool
    body_ingested: bool


class GmailReadCache:
    """SQLCipher-backed owner-private cache for all mail metadata."""

    def __init__(self, settings: Settings, key_provider: KeyProvider) -> None:
        self._settings = settings
        self._key_provider = key_provider

    def upsert(self, msg: CachedMessage) -> None:
        """Insert or update one metadata row."""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO messages (
                    message_id, thread_id, history_id, sender, subject, internal_date_ms,
                    category, snippet, label_ids, has_attachments, unread, important,
                    body_ingested
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(message_id) DO UPDATE SET
                    thread_id=excluded.thread_id,
                    history_id=excluded.history_id,
                    sender=excluded.sender,
                    subject=excluded.subject,
                    internal_date_ms=excluded.internal_date_ms,
                    category=excluded.category,
                    snippet=excluded.snippet,
                    label_ids=excluded.label_ids,
                    has_attachments=excluded.has_attachments,
                    unread=excluded.unread,
                    important=excluded.important,
                    body_ingested=excluded.body_ingested
                """,
                _params(msg),
            )

    def get(self, message_id: str) -> CachedMessage | None:
        """Return cached metadata for a message id."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM messages WHERE message_id = ?", (message_id,)
            ).fetchone()
        return _row_to_cached(row) if row is not None else None

    def mark_body_ingested(self, message_id: str) -> None:
        """Mark a signal message body as already handed to the ingest pipeline."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE messages SET body_ingested = 1 WHERE message_id = ?", (message_id,)
            )

    def mark_removed(self, message_id: str) -> None:
        """Remove a message that left the mailbox."""
        with self._connect() as conn:
            conn.execute("DELETE FROM messages WHERE message_id = ?", (message_id,))

    def set_cursor(self, history_id: str) -> None:
        """Store the singleton History API cursor."""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sync_state (id, history_id) VALUES (1, ?)
                ON CONFLICT(id) DO UPDATE SET history_id = excluded.history_id
                """,
                (history_id,),
            )

    def get_cursor(self) -> str | None:
        """Return the singleton History API cursor if initialised."""
        with self._connect() as conn:
            row = conn.execute("SELECT history_id FROM sync_state WHERE id = 1").fetchone()
        if row is None:
            return None
        value = row["history_id"]
        return value if isinstance(value, str) else None

    def list_unread(self, category: MailCategory | None = None) -> list[CachedMessage]:
        """List unread cached message metadata, optionally by category."""
        with self._connect() as conn:
            if category is None:
                rows = conn.execute(
                    "SELECT * FROM messages WHERE unread = 1 ORDER BY internal_date_ms DESC"
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM messages
                    WHERE unread = 1 AND category = ?
                    ORDER BY internal_date_ms DESC
                    """,
                    (category.value,),
                ).fetchall()
        return [_row_to_cached(row) for row in rows]

    def search_metadata(self, query: str, limit: int) -> list[CachedMessage]:
        """Search local metadata using parameterised LIKE clauses."""
        pattern = f"%{query}%"
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM messages
                WHERE sender LIKE ? OR subject LIKE ? OR snippet LIKE ?
                ORDER BY internal_date_ms DESC
                LIMIT ?
                """,
                (pattern, pattern, pattern, limit),
            ).fetchall()
        return [_row_to_cached(row) for row in rows]

    def _db_path(self) -> Path:
        # On hardware this may be reconciled to the broker-mounted vault path.
        return paths.scope_dir(self._settings, OWNER_PRIVATE) / "connectors" / "gmail" / "cache.db"

    def _connect(self) -> sqlite3.Connection:
        key = self._key_provider.dek_for_scope(OWNER_PRIVATE)
        path = self._db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        key_hex = key.as_hex()
        conn = sqlcipher_open(path, key_hex)
        set_row_factory(conn)
        _create_schema(conn)
        return conn


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            message_id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL,
            history_id TEXT NOT NULL,
            sender TEXT NOT NULL,
            subject TEXT NOT NULL,
            internal_date_ms INTEGER NOT NULL,
            category TEXT NOT NULL,
            snippet TEXT NOT NULL,
            label_ids TEXT NOT NULL,
            has_attachments INTEGER NOT NULL,
            unread INTEGER NOT NULL,
            important INTEGER NOT NULL,
            body_ingested INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sync_state (
            id INTEGER PRIMARY KEY CHECK(id = 1),
            history_id TEXT NOT NULL
        )
        """
    )


def _params(msg: CachedMessage) -> tuple[object, ...]:
    return (
        msg.message_id,
        msg.thread_id,
        msg.history_id,
        msg.sender,
        msg.subject,
        msg.internal_date_ms,
        msg.category.value,
        msg.snippet,
        json.dumps(list(msg.label_ids)),
        int(msg.has_attachments),
        int(msg.unread),
        int(msg.important),
        int(msg.body_ingested),
    )


def _row_to_cached(row: sqlite3.Row) -> CachedMessage:
    return CachedMessage(
        message_id=str(row["message_id"]),
        thread_id=str(row["thread_id"]),
        history_id=str(row["history_id"]),
        sender=str(row["sender"]),
        subject=str(row["subject"]),
        internal_date_ms=int(row["internal_date_ms"]),
        category=MailCategory(str(row["category"])),
        snippet=str(row["snippet"]),
        label_ids=tuple(str(item) for item in json.loads(str(row["label_ids"]))),
        has_attachments=bool(row["has_attachments"]),
        unread=bool(row["unread"]),
        important=bool(row["important"]),
        body_ingested=bool(row["body_ingested"]),
    )
