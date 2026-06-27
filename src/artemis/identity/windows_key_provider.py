"""Windows DPAPI-backed key provider for per-scope Artemis data keys."""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from artemis.config import Settings
from artemis.identity import windows_hello
from artemis.identity.dpapi import dpapi_seal, dpapi_unseal
from artemis.identity.key_provider import ScopeLockedError, SecretKey
from artemis.identity.scope import OWNER_PRIVATE
from artemis.ports.types import Scope


class InsecureKeyStoreError(Exception):
    """Raised when the configured key store is outside the owner-private profile."""


class UnlockUnavailableError(Exception):
    """Raised when Windows Hello cannot be invoked (not enrolled / no hardware / no console).

    This is a hard fail-closed condition: there is **no** silent auto-unseal
    fallback, which would be a downgrade-attack path.
    """


class UnlockDeniedError(Exception):
    """Raised when the Windows Hello gesture was presented but not verified."""


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
        """Unseal scope keys, gated behind a Windows Hello gesture (m2-win-b).

        Always Hello-enforced — there is no bypass parameter. Raises
        ``UnlockUnavailableError`` when Hello cannot run (and unseals nothing — no
        silent auto-unseal fallback), and ``UnlockDeniedError`` when the gesture is
        not verified (and unseals nothing). Only a verified gesture reaches
        ``_unseal_all()``.
        """
        if not windows_hello.hello_available():
            raise UnlockUnavailableError("Windows Hello is not available")
        try:
            verified = windows_hello.verify("Unlock Artemis owner-private data")
        except windows_hello.NoConsoleWindowError as exc:
            # No console window to anchor the prompt is an unavailability, not a
            # denial (Assumption #2): surface it as UnlockUnavailableError so the
            # caller's fail-closed branch handles it. Never unseal.
            raise UnlockUnavailableError("no console window for the Hello prompt") from exc
        if not verified:
            raise UnlockDeniedError("Hello gesture was not verified")
        self._unseal_all()

    def _unseal_all(self) -> None:
        """Unseal configured scope keys into memory (internal — not Hello-gated).

        Production callers use ``unlock()``; this is the post-gesture unseal and is
        exercised directly only by tests.
        """
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

    @property
    def unlocked_scope_count(self) -> int:
        """Number of scope keys currently held in memory (0 when locked)."""
        return len(self._keys)

    def lock(self) -> None:
        """Wipe held keys and mark the provider locked."""
        for key in self._keys.values():
            key.wipe()
        self._keys.clear()
        self._unlocked = False
