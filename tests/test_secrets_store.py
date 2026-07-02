from __future__ import annotations

import json
import os
import stat
from pathlib import Path

from pytest import MonkeyPatch

from artemis.secrets_store import KeyringSecretStore, SERVICE_NAME


class InMemoryBackend:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service_name: str, username: str) -> str | None:
        return self.values.get((service_name, username))

    def set_password(self, service_name: str, username: str, password: str) -> None:
        self.values[(service_name, username)] = password

    def delete_password(self, service_name: str, username: str) -> None:
        self.values.pop((service_name, username), None)


def test_set_get_round_trips_through_injected_backend(tmp_path: Path) -> None:
    backend = InMemoryBackend()
    store = KeyringSecretStore(tmp_path / "secrets.json", backend=backend)

    store.set("openai", "sk-test-secret")

    assert store.get("openai") == "sk-test-secret"
    assert backend.values == {(SERVICE_NAME, "openai"): "sk-test-secret"}


def test_missing_name_returns_none(tmp_path: Path) -> None:
    store = KeyringSecretStore(tmp_path / "secrets.json", backend=InMemoryBackend())

    assert store.get("missing") is None


def test_list_names_reflects_sets_and_deletes(tmp_path: Path) -> None:
    store = KeyringSecretStore(tmp_path / "secrets.json", backend=InMemoryBackend())

    store.set("beta", "second-secret")
    store.set("alpha", "first-secret")
    store.delete("beta")

    assert store.list_names() == ["alpha"]


def test_delete_removes_value_and_name(tmp_path: Path) -> None:
    backend = InMemoryBackend()
    store = KeyringSecretStore(tmp_path / "secrets.json", backend=backend)

    store.set("github", "ghp-test-secret")
    store.delete("github")

    assert store.get("github") is None
    assert store.list_names() == []
    assert backend.values == {}


def test_index_contains_names_but_not_values(tmp_path: Path) -> None:
    index_path = tmp_path / "secrets.json"
    store = KeyringSecretStore(index_path, backend=InMemoryBackend())

    store.set("anthropic", "not-for-json")

    index_text = index_path.read_text(encoding="utf-8")
    assert "anthropic" in index_text
    assert "not-for-json" not in index_text
    assert json.loads(index_text) == ["anthropic"]
    if os.name != "nt":
        assert stat.S_IMODE(index_path.stat().st_mode) == 0o600


def test_index_write_requests_private_permissions(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    requested_modes: list[int] = []

    def record_chmod(path: str | Path, mode: int) -> None:
        requested_modes.append(mode)

    monkeypatch.setattr("artemis.secrets_store.os.chmod", record_chmod)
    store = KeyringSecretStore(tmp_path / "secrets.json", backend=InMemoryBackend())

    store.set("owner", "private-secret")

    assert requested_modes == [0o600, 0o600]


def test_overwrite_updates_value_and_keeps_one_index_entry(tmp_path: Path) -> None:
    index_path = tmp_path / "secrets.json"
    store = KeyringSecretStore(index_path, backend=InMemoryBackend())

    store.set("calendar", "old-secret")
    store.set("calendar", "new-secret")

    assert store.get("calendar") == "new-secret"
    assert store.list_names() == ["calendar"]
    assert json.loads(index_path.read_text(encoding="utf-8")) == ["calendar"]


def test_corrupted_index_raises_before_backend_write(tmp_path: Path) -> None:
    """Regression (security review FLAG 1): a corrupted index must surface BEFORE the backend is
    mutated, so a value never persists in the keychain while staying invisible to list_names()."""
    index_path = tmp_path / "secrets.json"
    index_path.write_text("{ not json", encoding="utf-8")
    backend = InMemoryBackend()
    store = KeyringSecretStore(index_path, backend=backend)

    try:
        store.set("openai", "sk-should-not-persist")
        raised = False
    except ValueError:
        raised = True

    assert raised
    assert backend.values == {}  # backend was NOT written before the index error surfaced
