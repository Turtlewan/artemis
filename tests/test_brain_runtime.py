"""Tests for the brain runtime launcher and proactive lifespan wiring."""

from __future__ import annotations

import asyncio
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


class FakeHeartbeat:
    """Heartbeat double whose run loop is cancellable."""

    def __init__(self) -> None:
        self.started = False
        self.cancelled = False

    async def run_forever(self) -> None:
        self.started = True
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise


@pytest.fixture(autouse=True)
def runtime_patches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Patch heavyweight startup dependencies for lifespan tests."""
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr("artemis.main.sys.platform", "win32")
    monkeypatch.setattr("artemis.main.WindowsKeyProvider", FakeWindowsKeyProvider)
    monkeypatch.setattr("artemis.adapters.model_adapters.OpenAIEmbeddingModel", FakeEmbedder)
    monkeypatch.setattr("artemis.main.compose_brain", lambda *_args, **_kwargs: FakeBrain())
    yield
    if hasattr(app.state, "heartbeat_task"):
        delattr(app.state, "heartbeat_task")


def test_heartbeat_task_starts_and_cancels(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Enabled heartbeat is started on app startup and cancelled on shutdown."""
    settings = Settings(data_root=tmp_path, heartbeat_enabled=True)
    heartbeat = FakeHeartbeat()
    monkeypatch.setattr("artemis.main.get_settings", lambda: settings)
    monkeypatch.setattr(
        "artemis.main.compose_proactive",
        lambda *_args, **_kwargs: heartbeat,
    )

    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
        task = app.state.heartbeat_task
        assert isinstance(task, asyncio.Task)
        assert heartbeat.started is True
        assert task.done() is False

    assert task.cancelled() is True
    assert heartbeat.cancelled is True


def test_heartbeat_disabled_still_serves_healthz(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Disabling the heartbeat leaves startup and health checks available."""
    settings = Settings(data_root=tmp_path, heartbeat_enabled=False)
    monkeypatch.setattr("artemis.main.get_settings", lambda: settings)

    with TestClient(app) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert not hasattr(app.state, "heartbeat_task")


def test_heartbeat_compose_failure_still_serves_healthz(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A proactive compose failure degrades without blocking startup."""
    settings = Settings(data_root=tmp_path, heartbeat_enabled=True)
    monkeypatch.setattr("artemis.main.get_settings", lambda: settings)

    def raise_compose(*_args: object, **_kwargs: object) -> FakeHeartbeat:
        raise RuntimeError("notifier unavailable")

    monkeypatch.setattr("artemis.main.compose_proactive", raise_compose)

    with TestClient(app) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert not hasattr(app.state, "heartbeat_task")
