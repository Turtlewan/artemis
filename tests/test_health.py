"""Tests for the brain health stub endpoints (M0-b)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from artemis.config import Settings
from artemis.main import app


class FakeEmbedder:
    """No-network embedder test double."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings


class FakeBrain:
    """Minimal composed brain exposing the fields used by the lifespan."""

    def __init__(self) -> None:
        self._registry = object()
        self._model = object()


class FakeWindowsKeyProvider:
    """WindowsKeyProvider test double that avoids OS credential APIs."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def provision(self) -> None:
        pass

    def unlock(self) -> None:
        pass

    def is_owner_unlocked(self) -> bool:
        return True


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    settings = Settings(data_root=tmp_path, heartbeat_enabled=False)
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr("artemis.main.get_settings", lambda: settings)
    monkeypatch.setattr("artemis.main.sys.platform", "win32")
    monkeypatch.setattr("artemis.main.WindowsKeyProvider", FakeWindowsKeyProvider)
    monkeypatch.setattr("artemis.adapters.model_adapters.OpenAIEmbeddingModel", FakeEmbedder)
    monkeypatch.setattr("artemis.main.compose_brain", lambda *_args, **_kwargs: FakeBrain())
    with TestClient(app) as test_client:
        yield test_client


def test_healthz(client: TestClient) -> None:
    """GET /healthz returns 200 with status ok."""
    response = client.get("/healthz")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "slot" in data


def test_readyz(client: TestClient) -> None:
    """GET /readyz returns 200 with status ok."""
    response = client.get("/readyz")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "checks" in data
    assert data["checks"] == {}
