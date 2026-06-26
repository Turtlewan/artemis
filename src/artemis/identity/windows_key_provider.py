"""Windows DPAPI-backed key provider for per-scope Artemis data keys."""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from artemis.config import Settings
from artemis.identity.dpapi import dpapi_seal, dpapi_unseal
from artemis.identity.key_provider import ScopeLockedError, SecretKey
from artemis.identity.scope import OWNER_PRIVATE
from artemis.ports.types import Scope


class InsecureKeyStoreError(Exception):
    """Raised when the configured key store is outside the owner-private profile."""


def _scope_entropy(scope: Scope) -> bytes:
    return f"artemis-v1-{scope}".encode()


def _resolve_env_path(name: str) -> Path | None:
    value = os.environ.get(name)
    if value is None:
        return None
    return Path(value).resolve()


class WindowsKeyProvider:
    """DPAPI-backed key provider for Windows.

    Per ADR-033, this protects against offline disk theft and cross-user access.
    It does not protect against a same-user-credential attacker such as malware
    or session hijack; that boundary is deferred to m2-win-b (Hello) and the Mac
    Secure Enclave broker.
    """

    def __init__(self, settings: Settings, *, scopes: tuple[Scope, ...] = (OWNER_PRIVATE,)) -> None:
        data_root = Path(settings.data_root).resolve()
        owner_roots = tuple(
            root
            for root in (_resolve_env_path("APPDATA"), _resolve_env_path("LOCALAPPDATA"))
            if root is not None
        )
        # DPAPI is user-scoped, so the sealed DEKs must also live under the user's
        # profile ACLs rather than a shared directory.
        if not any(data_root == root or data_root.is_relative_to(root) for root in owner_roots):
            raise InsecureKeyStoreError("Key store must live under APPDATA or LOCALAPPDATA")

        self._settings = settings
        self._scopes = scopes
        self._keys_dir = data_root / "keys"
        self._keys: dict[Scope, SecretKey] = {}
        self._unlocked = False

    def provision(self) -> None:
        """Create sealed DEKs for missing scopes."""
        self._keys_dir.mkdir(parents=True, exist_ok=True)
        for scope in self._scopes:
            path = self._keys_dir / f"{scope}.dek"
            if path.exists():
                continue
            dek = bytearray(secrets.token_bytes(32))
            try:
                sealed = dpapi_seal(bytes(dek), entropy=_scope_entropy(scope))
            finally:
                dek[:] = bytes(len(dek))
            tmp_path = self._keys_dir / f"{scope}.dek.tmp"
            with open(tmp_path, "wb") as handle:
                handle.write(sealed)
                handle.flush()
                # fsync the sealed DEK before the atomic rename so a crash/power-loss
                # cannot leave a present-but-unflushed .dek that fails to unseal.
                os.fsync(handle.fileno())
            os.replace(tmp_path, path)

    def unlock(self) -> None:
        """Unseal configured scope keys into memory."""
        for scope in self._scopes:
            path = self._keys_dir / f"{scope}.dek"
            if not path.exists():
                raise ScopeLockedError(f"Scope is locked: {scope}")
            sealed = path.read_bytes()
            buf = dpapi_unseal(sealed, entropy=_scope_entropy(scope))
            try:
                key = SecretKey(bytes(buf))
            finally:
                buf[:] = bytes(len(buf))
            self._keys[scope] = key
        self._unlocked = True

    def dek_for_scope(self, scope: Scope) -> SecretKey:
        """Return the unlocked data encryption key for ``scope``."""
        try:
            return self._keys[scope]
        except KeyError as exc:
            raise ScopeLockedError(f"Scope is locked: {scope}") from exc

    def is_owner_unlocked(self) -> bool:
        """Return true only while scope keys are held in memory."""
        return self._unlocked

    def lock(self) -> None:
        """Wipe held keys and mark the provider locked."""
        for key in self._keys.values():
            key.wipe()
        self._keys.clear()
        self._unlocked = False
