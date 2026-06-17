"""Per-slot / per-scope path resolution functions.

All functions resolve paths from a ``Settings`` instance — they never create
directories (use ``scripts/setup_data_dir.sh`` for that).
"""

from __future__ import annotations

from pathlib import Path

from artemis.config import Settings

# Valid scope identifiers
VALID_SCOPES = frozenset({"owner-private", "general"})


def slot_root(s: Settings) -> Path:
    """Return the root directory for the active slot."""
    return s.data_root / s.slot


def scope_dir(s: Settings, scope: str) -> Path:
    """Return the parent directory for a storage scope.

    Args:
        s: Application settings.
        scope: One of ``owner-private``, ``general``, or ``guest-<person_id>``.

    Returns:
        ``<data_root>/<slot>/<scope>/``

    Raises:
        ValueError: If scope is not a recognised identifier.
    """
    if scope not in VALID_SCOPES and not scope.startswith("guest-"):
        raise ValueError(f"Unknown scope: {scope!r}")
    return slot_root(s) / scope


def vault_dir(s: Settings, scope: str) -> Path:
    """Return the encrypted-volume mount point under a scope.

    This is where LanceDB lives (on the APFS encrypted volume, mounted at
    runtime by the M2 security broker). Returns an empty dir path until mounted.
    """
    return scope_dir(s, scope) / "vault"


def backups_dir(s: Settings) -> Path:
    """Return the backups directory for the active slot."""
    return slot_root(s) / "backups"


def logs_dir(s: Settings) -> Path:
    """Return the logs directory for the active slot."""
    return slot_root(s) / "logs"


def env_file(s: Settings) -> Path:
    """Resolve the canonical per-slot ``.env`` file path.

    The path is relative to the project root (``config/.env.<slot>``).
    """
    return Path("config") / f".env.{s.slot}"
