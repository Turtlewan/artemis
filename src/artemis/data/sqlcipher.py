"""SQLCipher connection seam for real encryption at rest.

On Windows, ``sqlcipher_open`` opens an encrypted SQLCipher database keyed by a
DPAPI-custodied key per ADR-033. The ``PRAGMA key`` string is never logged; do
not ``repr()`` the connection before the key is applied because bindings may
include diagnostic state in representations.

This protects against offline disk theft and cross-user access. It does not
protect against a same-user-credential attacker; that boundary is deferred to
m2-win-b (Hello) and the Mac Secure Enclave broker.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import cast


class SqlCipherError(Exception):
    """Raised when the SQLCipher binding or keyed open fails."""


def sqlcipher_open(path: Path, key_hex: str) -> sqlite3.Connection:
    """Open a SQLCipher database at ``path`` using a 256-bit hex key.

    The ``PRAGMA key`` string is never logged, and callers must not ``repr()``
    the connection before this function returns with the key applied. The
    resulting encrypted-at-rest database protects against offline disk theft and
    cross-user access, but not a same-user-credential attacker; that boundary is
    deferred to m2-win-b (Hello) and the Mac Secure Enclave broker.
    """
    if len(key_hex) != 64 or any(char not in "0123456789abcdefABCDEF" for char in key_hex):
        raise ValueError("key_hex must be 64 hex characters")

    try:
        import sqlcipher3  # from sqlcipher3-wheels wheel; not the sqlcipher3 source build
    except ImportError as exc:
        raise SqlCipherError("sqlcipher3 binding not installed") from exc

    conn = cast(sqlite3.Connection, sqlcipher3.connect(str(path)))
    try:
        conn.execute(f"PRAGMA key = \"x'{key_hex}'\"")
        if conn.execute("PRAGMA cipher_version").fetchone() is None:
            raise SqlCipherError("binding is not SQLCipher")
        # Force a read of the keyed database. SQLCipher defers key verification to
        # first read, so a wrong key or corrupted file fails HERE and is surfaced
        # through the sanitized error below — never later in caller code, and never
        # echoing the key.
        conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
    except SqlCipherError:
        conn.close()
        raise
    except Exception:
        conn.close()
        raise SqlCipherError(
            "key application failed"
        ) from None  # `from None` drops the PRAGMA-text context

    return conn


def set_row_factory(conn: sqlite3.Connection) -> None:
    """Set a ``Row`` factory matching the connection's binding.

    A real SQLCipher connection's cursor is rejected by ``sqlite3.Row`` (and vice
    versa), so the factory must match the connection's actual binding. Owner-private
    stores opened through ``sqlcipher_open`` get ``sqlcipher3.Row``; plain
    ``sqlite3`` connections (e.g. a no-key dev fallback) keep ``sqlite3.Row``.
    Both expose the same mapping/index row API.
    """
    if type(conn).__module__.startswith("sqlcipher3"):
        import sqlcipher3  # from sqlcipher3-wheels wheel; not the sqlcipher3 source build

        # sqlcipher3.Row mirrors sqlite3.Row's (cursor, row) constructor at runtime.
        conn.row_factory = cast("type[sqlite3.Row]", sqlcipher3.Row)
    else:
        conn.row_factory = sqlite3.Row
