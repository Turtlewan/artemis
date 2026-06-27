"""Tests for the Gateway, HTTP API, and dev CLI (M1-c).

Uses a ``FakeBrain`` so all tests are deterministic — no network needed.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from artemis.brain import BrainResponse
from artemis.config import Settings
from artemis.gateway import OWNER_SCOPE, Gateway
from artemis.main import app

# ── FakeBrain ────────────────────────────────────────────────────────────────


class FakeBrain:
    """Deterministic Brain fake for surface tests."""

    FIXED_RESPONSE = BrainResponse(
        text="42 o'clock",
        path="deterministic",
        tool_used="time.get_current_time",
        escalated=False,
    )

    async def respond(self, request_text: str, scope: str) -> BrainResponse:
        assert scope == OWNER_SCOPE  # Gateway must attach owner scope
        return self.FIXED_RESPONSE

    async def respond_stream(self, request_text: str, scope: str) -> AsyncIterator[str]:
        assert scope == OWNER_SCOPE
        yield "42 o'clock"

    async def pre_route(self, request_text: str, scope: str) -> str | None:
        assert scope == OWNER_SCOPE
        return "time.get_current_time"


# ── Gateway tests ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_gateway_scope_attach() -> None:
    """Gateway attaches OWNER_SCOPE to requests."""
    fake = FakeBrain()
    gateway = Gateway(fake)  # type: ignore[arg-type]
    response = await gateway.handle_text("hi")
    assert response.text == "42 o'clock"
    assert response.tool_used == "time.get_current_time"


@pytest.mark.asyncio
async def test_gateway_pre_route() -> None:
    """Gateway.pre_route delegates through OWNER_SCOPE."""
    fake = FakeBrain()
    gateway = Gateway(fake)  # type: ignore[arg-type]
    result = await gateway.pre_route("hi")
    assert result == "time.get_current_time"


@pytest.mark.asyncio
async def test_gateway_stream() -> None:
    """Gateway.handle_text_stream yields the answer."""
    fake = FakeBrain()
    gateway = Gateway(fake)  # type: ignore[arg-type]
    chunks: list[str] = []
    async for chunk in gateway.handle_text_stream("hi"):
        chunks.append(chunk)
    assert "".join(chunks) == "42 o'clock"


# ── HTTP API tests ───────────────────────────────────────────────────────────


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """TestClient with a FakeBrain injected as the gateway.

    Lifespan runs first (creates real gateway), then we override
    so the tests use the deterministic FakeBrain.

    m2-win-b: on a win32 host the lifespan now Hello-unlocks a WindowsKeyProvider,
    so point it at a throwaway key store under the user profile and stub the
    gesture (the surface tests only exercise the gateway). On non-win32 hosts the
    broker branch runs and these patches are inert.
    """
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr("artemis.identity.windows_hello.hello_available", lambda: True)
    monkeypatch.setattr("artemis.identity.windows_hello.verify", lambda _message: True)
    monkeypatch.setattr("artemis.main.get_settings", lambda: Settings(data_root=tmp_path))
    with TestClient(app) as c:
        # Override after lifespan initialises the real gateway
        app.state.gateway = Gateway(FakeBrain())  # type: ignore[arg-type]
        yield c


def test_post_ask(client: TestClient) -> None:
    """POST /ask returns the expected JSON response."""
    response = client.post("/ask", json={"text": "what time is it"})
    assert response.status_code == 200
    data = response.json()
    assert data["text"] == "42 o'clock"
    assert data["path"] == "deterministic"
    assert data["tool_used"] == "time.get_current_time"
    assert data["escalated"] is False


def test_post_ask_stream(client: TestClient) -> None:
    """POST /ask/stream returns SSE with answer and terminal [DONE]."""
    response = client.post("/ask/stream", json={"text": "what time is it"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    body = response.text
    assert "data: 42 o'clock" in body
    assert "data: [DONE]" in body


def test_get_ask_stream(client: TestClient) -> None:
    """GET /ask/stream returns SSE with answer and terminal [DONE]."""
    response = client.get("/ask/stream", params={"text": "hi"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    body = response.text
    assert "data: 42 o'clock" in body
    assert "data: [DONE]" in body


def test_healthz_regression(client: TestClient) -> None:
    """M1-c did not break /healthz."""
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_readyz_regression(client: TestClient) -> None:
    """M1-c did not break /readyz."""
    response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
