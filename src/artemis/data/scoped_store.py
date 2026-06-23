"""Scoped store handles and data-layer crypto-wall enforcement."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from artemis import paths
from artemis.config import Settings
from artemis.identity.key_provider import KeyProvider, SecretKey
from artemis.identity.scope import GENERAL, OWNER_PRIVATE
from artemis.ports.types import Scope

VectorIndexKind = Literal["sqlite-vec", "lancedb"]


class CrossScopeError(Exception):
    """Raised when a scoped handle is used for a different requested scope."""


@dataclass(frozen=True)
class VectorIndexHandle:
    """Locator for a per-scope vector index."""

    scope: Scope
    kind: VectorIndexKind
    path: Path


@dataclass(frozen=True)
class ScopedConnection:
    """SQLCipher connection handle bound to one scope, path, and key."""

    path: Path
    scope: Scope
    key: SecretKey

    def pragma_key_statement(self) -> str:
        """Return the SQLCipher key statement for the future engine open."""
        return f"PRAGMA key = \"x'{self.key.as_hex()}'\""


def assert_same_scope(handle_scope: Scope, requested_scope: Scope) -> None:
    """Reject attempts to use a scoped handle across the owner/guest wall."""
    if handle_scope != requested_scope:
        raise CrossScopeError(
            f"Scoped handle for {handle_scope!r} cannot satisfy {requested_scope!r}"
        )


class ScopedStore:
    """Lazy per-scope store facade.

    Construction opens nothing. The key is fetched only in ``open_connection``,
    which makes the key provider the wall: no key, no database handle.
    """

    def __init__(self, scope: Scope, settings: Settings, key_provider: KeyProvider) -> None:
        self.scope = scope
        self._settings = settings
        self._key_provider = key_provider

    def db_path(self) -> Path:
        """Return the per-scope SQLCipher database path outside ``vault/``."""
        return paths.scope_dir(self._settings, self.scope) / "memory" / "memory.db"

    def open_connection(self) -> ScopedConnection:
        """Return a typed SQLCipher handle after fetching this scope's DEK."""
        key = self._key_provider.dek_for_scope(self.scope)
        return ScopedConnection(path=self.db_path(), scope=self.scope, key=key)

    def vector_index_handle(self) -> VectorIndexHandle:
        """Return the per-scope vector-index locator.

        Owner document-corpus LanceDB locators point at ``vault/``; guest memory
        vector handles stay with the per-scope SQLCipher DB. Engine init is M3.
        """
        if self.scope in (OWNER_PRIVATE, GENERAL):
            return VectorIndexHandle(
                scope=self.scope,
                kind="lancedb",
                path=paths.vault_dir(self._settings, self.scope),
            )
        return VectorIndexHandle(scope=self.scope, kind="sqlite-vec", path=self.db_path())


def provision_scope(
    scope: Scope,
    settings: Settings,
    key_provider: KeyProvider,
    broker_provision: Callable[[Scope], None],
) -> None:
    """Provision a scope and verify its key is available through the port."""
    broker_provision(scope)
    scope_root = paths.scope_dir(settings, scope)
    (scope_root / "keys").mkdir(parents=True, exist_ok=True)
    (scope_root / "memory").mkdir(parents=True, exist_ok=True)
    key_provider.dek_for_scope(scope)
