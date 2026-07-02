"""Keyring-backed secret store.

Secret values live only in the OS keychain backend. The local JSON index stores
names only so callers can list configured credentials without enumerating the
keychain.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from collections.abc import Set as AbstractSet
from importlib import import_module
from pathlib import Path
from typing import Protocol, cast

from artemis.ports.secrets import SecretStorePort


SERVICE_NAME = "artemis"
_INDEX_MODE = 0o600


def resolve_secret(
    name: str,
    *,
    secrets: SecretStorePort | None,
    env: Mapping[str, str] = os.environ,
) -> str | None:
    """Resolve a secret keychain-first, then environment fallback.

    This is the migration path off env-var stopgaps (Telegram bot token, Tavily
    key): once the owner stores a secret in the keychain it wins, but an existing
    env var still works until then. Returns None when neither source has a value.
    Never logs the resolved value.
    """
    if secrets is not None:
        stored = secrets.get(name)
        if stored:
            return stored
    env_value = env.get(name)
    return env_value or None


class KeyringBackend(Protocol):
    """Minimal backend seam compatible with the keyring package."""

    def get_password(self, service_name: str, username: str) -> str | None:
        """Return a secret value or None without logging it."""
        ...

    def set_password(self, service_name: str, username: str, password: str) -> None:
        """Store a secret value without disclosing it."""
        ...

    def delete_password(self, service_name: str, username: str) -> None:
        """Delete a secret value."""
        ...


class _KeyringModule(Protocol):
    def get_password(self, service_name: str, username: str) -> str | None: ...

    def set_password(self, service_name: str, username: str, password: str) -> None: ...

    def delete_password(self, service_name: str, username: str) -> None: ...


class _DefaultKeyringBackend:
    def __init__(self) -> None:
        self._keyring = cast(_KeyringModule, import_module("keyring"))

    def get_password(self, service_name: str, username: str) -> str | None:
        return self._keyring.get_password(service_name, username)

    def set_password(self, service_name: str, username: str, password: str) -> None:
        self._keyring.set_password(service_name, username, password)

    def delete_password(self, service_name: str, username: str) -> None:
        self._keyring.delete_password(service_name, username)


class KeyringSecretStore:
    """SecretStorePort implementation backed by keyring and a names-only index."""

    def __init__(self, index_path: Path, *, backend: KeyringBackend | None = None) -> None:
        self._index_path = index_path
        self._backend = backend if backend is not None else _DefaultKeyringBackend()

    def get(self, name: str) -> str | None:
        return self._backend.get_password(SERVICE_NAME, name)

    def set(self, name: str, value: str) -> None:
        # Read the index FIRST so a corrupted index surfaces before we mutate the backend —
        # otherwise a value would persist in the keychain but stay invisible to list_names().
        names = set(self.list_names())
        self._backend.set_password(SERVICE_NAME, name, value)
        names.add(name)
        self._write_names(names)

    def delete(self, name: str) -> None:
        names = set(self.list_names())
        self._backend.delete_password(SERVICE_NAME, name)
        names.discard(name)
        self._write_names(names)

    def list_names(self) -> list[str]:
        if not self._index_path.exists():
            return []

        try:
            raw_names = json.loads(self._index_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            msg = f"Secret names index is not valid JSON: {self._index_path}"
            raise ValueError(msg) from exc

        if not isinstance(raw_names, list) or not all(isinstance(name, str) for name in raw_names):
            msg = f"Secret names index must contain a JSON list of strings: {self._index_path}"
            raise ValueError(msg)

        return sorted(set(raw_names))

    def _write_names(self, names: AbstractSet[str]) -> None:
        self._index_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        payload = json.dumps(sorted(names), indent=2) + "\n"

        temp_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self._index_path.parent,
                delete=False,
            ) as temp_file:
                temp_name = temp_file.name
                temp_file.write(payload)
                temp_file.flush()
                os.fsync(temp_file.fileno())

            os.chmod(temp_name, _INDEX_MODE)
            os.replace(temp_name, self._index_path)
            os.chmod(self._index_path, _INDEX_MODE)
        finally:
            if temp_name is not None and os.path.exists(temp_name):
                os.unlink(temp_name)
