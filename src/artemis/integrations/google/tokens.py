"""Owner-private storage for Google OAuth refresh tokens."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

from artemis import paths
from artemis.config import Settings
from artemis.data.sqlcipher import sqlcipher_open
from artemis.identity.key_provider import KeyProvider
from artemis.identity.scope import OWNER_PRIVATE


@dataclass(frozen=True)
class StoredToken:
    """Persisted Google refresh token metadata.

    ``obtained_at_ms`` is informational only for status display. Token validity
    is established by refresh-time ``invalid_grant`` handling, not by age; there
    is intentionally no TTL on the stored refresh token.
    """

    refresh_token: str
    scopes: tuple[str, ...]
    token_uri: str
    client_id: str
    obtained_at_ms: int

    def __repr__(self) -> str:
        return (
            "StoredToken(refresh_token=<redacted>, "
            f"scopes={self.scopes!r}, token_uri={self.token_uri!r}, "
            f"client_id={self.client_id!r}, obtained_at_ms={self.obtained_at_ms!r})"
        )

    def __str__(self) -> str:
        return repr(self)


class TokenStore(Protocol):
    """Port for storing the single owner's Google refresh token."""

    def save(self, token: StoredToken) -> None:
        """Persist ``token``."""
        ...

    def load(self) -> StoredToken | None:
        """Return the stored token, if one exists."""
        ...

    def clear(self) -> None:
        """Delete the stored token."""
        ...


class InMemoryTokenStore:
    """Test token store that never persists secrets to disk."""

    def __init__(self, token: StoredToken | None = None) -> None:
        self._token = token

    def save(self, token: StoredToken) -> None:
        self._token = token

    def load(self) -> StoredToken | None:
        return self._token

    def clear(self) -> None:
        self._token = None


class SqlCipherTokenStore:
    """Owner-private SQLCipher token store keyed by the broker owner DEK."""

    def __init__(self, settings: Settings, key_provider: KeyProvider) -> None:
        self.settings = settings
        self.key_provider = key_provider

    def _db_path(self) -> Path:
        """Return the dev path for the token DB.

        On-hardware vault-path reconciliation is deferred to the same one-line
        adapter used by the other owner-private stores once the Mini mount is
        present.
        """
        return paths.scope_dir(self.settings, OWNER_PRIVATE) / "connectors" / "google" / "tokens.db"

    def _connect(self) -> sqlite3.Connection:
        """Open the DB and ensure the single-row token schema exists.

        ``key_hex`` is local to this method and is never stored on ``self`` or
        module state. Python's GC bounds the immutable string lifetime.
        """
        key = self.key_provider.dek_for_scope(OWNER_PRIVATE)
        key_hex = key.as_hex()
        self._db_path().parent.mkdir(parents=True, exist_ok=True)
        conn = sqlcipher_open(self._db_path(), key_hex)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS google_token (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                refresh_token TEXT NOT NULL,
                scopes TEXT NOT NULL,
                token_uri TEXT NOT NULL,
                client_id TEXT NOT NULL,
                obtained_at_ms INTEGER NOT NULL
            )
            """
        )
        conn.commit()
        return conn

    def save(self, token: StoredToken) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO google_token (
                    id, refresh_token, scopes, token_uri, client_id, obtained_at_ms
                )
                VALUES (1, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    refresh_token = excluded.refresh_token,
                    scopes = excluded.scopes,
                    token_uri = excluded.token_uri,
                    client_id = excluded.client_id,
                    obtained_at_ms = excluded.obtained_at_ms
                """,
                (
                    token.refresh_token,
                    json.dumps(list(token.scopes)),
                    token.token_uri,
                    token.client_id,
                    token.obtained_at_ms,
                ),
            )
            conn.commit()

    def load(self) -> StoredToken | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                """
                SELECT refresh_token, scopes, token_uri, client_id, obtained_at_ms
                FROM google_token
                WHERE id = 1
                """
            ).fetchone()
        if row is None:
            return None
        scopes = _decode_scopes(cast(str, row[1]))
        return StoredToken(
            refresh_token=cast(str, row[0]),
            scopes=scopes,
            token_uri=cast(str, row[2]),
            client_id=cast(str, row[3]),
            obtained_at_ms=cast(int, row[4]),
        )

    def clear(self) -> None:
        with closing(self._connect()) as conn:
            conn.execute("DELETE FROM google_token WHERE id = 1")
            conn.commit()


def _decode_scopes(raw: str) -> tuple[str, ...]:
    decoded = json.loads(raw)
    if not isinstance(decoded, list) or not all(isinstance(item, str) for item in decoded):
        raise ValueError("stored Google scopes are malformed")
    return tuple(cast(Sequence[str], decoded))
