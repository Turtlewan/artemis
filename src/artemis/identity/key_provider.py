"""Key-provider port for per-scope data encryption keys."""

from __future__ import annotations

from typing import Protocol

from artemis.ports.types import Scope


class ScopeLockedError(Exception):
    """Raised when a scope's data encryption key is unavailable."""


class SecretKey:
    """Opaque wrapper around a 32-byte data encryption key."""

    def __init__(self, key_bytes: bytes) -> None:
        if len(key_bytes) != 32:
            raise ValueError("SecretKey requires exactly 32 bytes")
        self._buffer = bytearray(key_bytes)

    def __repr__(self) -> str:
        return "SecretKey(<redacted>)"

    def __str__(self) -> str:
        return "SecretKey(<redacted>)"

    def as_hex(self) -> str:
        """Return the raw hex SQLCipher expects for ``PRAGMA key``."""
        return bytes(self._buffer).hex()

    def wipe(self) -> None:
        """Best-effort zeroization of the in-memory key buffer."""
        for index in range(len(self._buffer)):
            self._buffer[index] = 0


class KeyProvider(Protocol):
    """Port implemented by the broker-backed key provider in M2-c."""

    def dek_for_scope(self, scope: Scope) -> SecretKey:
        """Return the unlocked data encryption key for ``scope``."""
        ...

    def is_owner_unlocked(self) -> bool:
        """Return true only while an owner broker session is unlocked."""
        ...


class FakeKeyProvider:
    """Test double for the M2-b key-provider port."""

    def __init__(self, keys: dict[Scope, bytes] | None = None, *, owner_unlocked: bool) -> None:
        self._keys = dict(keys or {})
        self._owner_unlocked = owner_unlocked

    def dek_for_scope(self, scope: Scope) -> SecretKey:
        """Return a redacted key wrapper for a known unlocked scope."""
        key = self._keys.get(scope)
        if key is None:
            raise ScopeLockedError(f"Scope is locked: {scope}")
        return SecretKey(key)

    def is_owner_unlocked(self) -> bool:
        """Return the configured fake owner-session state."""
        return self._owner_unlocked
