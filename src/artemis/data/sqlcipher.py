"""SQLCipher connection seam (M2-c) — dev stub.

On the Mac (with the SQLCipher binding installed and the broker delivering the
owner DEK), ``sqlcipher_open`` opens an encrypted database keyed with
``PRAGMA key = "x'<hex>'"``. Off-hardware (the dev box, per the M2 dev-stub in
docs/findings/cluster-spec-roadmap.md) there is no SQLCipher binding, so this is
a **plain-sqlite3 shim**: it opens (or creates) a normal database and accepts
``key_hex`` only for signature parity — the key is NOT applied. This keeps every
owner-private SQLCipher store (GATE-a staging, M8-a tokens, M8-d-a tasks, FIN-a
ledger) buildable and testable without the binding. Real keyed persistence is
gated on-hardware.

The full M2-c spec (broker IPC client, mlock, Secure-Enclave Tier-0 key) is
Mac-gated and unbuilt; this seam is the one dev-buildable piece its consumers
need now.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


def sqlcipher_open(path: Path, key_hex: str) -> sqlite3.Connection:
    """Open (creating if needed) the database at ``path``.

    DEV STUB: returns a plain ``sqlite3.Connection``. ``key_hex`` is accepted to
    match the on-hardware signature but is not applied (no SQLCipher binding off
    the Mini). On the Mini this is replaced by the real keyed open
    (``PRAGMA key``); the caller contract is identical — a ready-to-use
    connection to a per-scope owner-private database.
    """
    # key_hex intentionally unused off-hardware (no SQLCipher PRAGMA key); the
    # owner-private wall is provided by the broker-mounted volume on the Mini.
    return sqlite3.connect(path)
