"""Tests for the ask routes."""

from __future__ import annotations

from collections.abc import Sequence

from fastapi.testclient import TestClient

from artemis.api.app import create_app
from artemis.api.auth import Principal, require_session
from artemis.types import Message, ModelResponse, Usage


class FakeModel:
    def __init__(self, text: str = "hello there", model_id: str = "qwen3:4b") -> None:
        self._text = text
        self._model_id = model_id

    async def complete(
        self,
        *,
        messages: Sequence[Message],
        model: str | None = None,
        response_schema: dict | None = None,  # type: ignore[type-arg]
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        del messages, model, response_schema, temperature, max_tokens
        return ModelResponse(
            text=self._text,
            model_id=self._model_id,
            structured=None,
            finish_reason="stop",
            usage=Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
        )


def _client(model: FakeModel) -> TestClient:
    app = create_app(model=model)
    app.dependency_overrides[require_session] = lambda: Principal(
        device_id="dev", person_id="owner"
    )
    return TestClient(app)


def test_ask_returns_text_and_engine_tag() -> None:
    client = _client(FakeModel("the answer", "qwen3:4b"))
    resp = client.post("/app/ask", json={"text": "hi"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["text"] == "the answer"
    assert body["path"] == "local"
    assert body["escalated"] is False


def test_ask_codex_engine_tag() -> None:
    client = _client(FakeModel("x", "gpt-5.5"))
    assert client.post("/app/ask", json={"text": "hi"}).json()["path"] == "codex"


def test_ask_stream_emits_text_then_done() -> None:
    client = _client(FakeModel("line one\nline two"))
    resp = client.post("/app/ask/stream", json={"text": "hi"})
    assert resp.status_code == 200
    body = resp.text
    assert "data: line one" in body
    assert "data: line two" in body
    assert body.rstrip().endswith("data: [DONE]")


def test_ask_voice_deferred_message() -> None:
    client = _client(FakeModel())
    resp = client.post("/app/ask/voice", json={"text": "hi", "speak": True})
    assert resp.status_code == 200
    assert "aren't available yet" in resp.text
    assert "data: [DONE]" in resp.text


def test_ask_requires_session() -> None:
    client = TestClient(create_app(model=FakeModel()))
    assert client.post("/app/ask", json={"text": "hi"}).status_code == 401
