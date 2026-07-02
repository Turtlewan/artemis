"""Tests for intent-routed ask routes."""

from __future__ import annotations

from collections.abc import Sequence
import json
import os
from typing import Any

import pytest
from fastapi.testclient import TestClient

from artemis.api import ask_routes
from artemis.api.app import create_app
from artemis.api.auth import Principal, require_session
from artemis.intent import Intent, IntentRouter, Route
from artemis.reachout.web_tool import WebAnswer
from artemis.types import Message, ModelResponse, Usage


class FakeModel:
    def __init__(self, text: str = "plain answer", model_id: str = "qwen3:4b") -> None:
        self._text = text
        self._model_id = model_id
        self.calls: list[ModelCall] = []

    async def complete(
        self,
        *,
        messages: Sequence[Message],
        model: str | None = None,
        response_schema: dict[str, Any] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        self.calls.append(
            ModelCall(
                messages=list(messages),
                model=model,
                response_schema=response_schema,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        )
        return ModelResponse(
            text=self._text,
            model_id=self._model_id,
            structured=None,
            finish_reason="stop",
            usage=Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
        )


class ModelCall:
    def __init__(
        self,
        *,
        messages: list[Message],
        model: str | None,
        response_schema: dict[str, Any] | None,
        temperature: float,
        max_tokens: int | None,
    ) -> None:
        self.messages = messages
        self.model = model
        self.response_schema = response_schema
        self.temperature = temperature
        self.max_tokens = max_tokens


class FixedIntentRouter(IntentRouter):
    def __init__(self, route: Route) -> None:
        self._route = route

    async def classify(self, text: str) -> Intent:
        return Intent(route=self._route, confidence=1.0, reason=f"forced for {text}")


class FakeWebTool:
    def __init__(self) -> None:
        self.queries: list[str] = []
        self.closed = False

    async def answer(self, query: str) -> WebAnswer:
        self.queries.append(query)
        return WebAnswer(answer="web answer", sources=["https://example.com/source"])

    async def aclose(self) -> None:
        self.closed = True


def client_for(model: FakeModel, route: Route) -> TestClient:
    app = create_app(model=model)
    app.dependency_overrides[require_session] = lambda: Principal(
        device_id="dev", person_id="owner"
    )
    app.dependency_overrides[ask_routes._intent] = lambda: FixedIntentRouter(route)
    return TestClient(app)


@pytest.mark.parametrize(
    ("text", "route"),
    [
        ("who won the 2022 world cup", "web_q"),
        ("make me a tool that summarizes my inbox", "build"),
    ],
)
async def test_intent_router_uses_haiku_structured_output(text: str, route: Route) -> None:
    model = FakeModel(json.dumps({"route": route, "confidence": 0.91, "reason": "matched"}))
    intent = await IntentRouter(model).classify(text)

    assert intent.route == route
    assert model.calls[0].model == "haiku"
    assert model.calls[0].response_schema is not None
    assert "route" in model.calls[0].response_schema["properties"]


def test_plain_ask_keeps_completion_path() -> None:
    client = client_for(FakeModel("the answer", "gpt-5.5"), "plain_ask")

    response = client.post("/app/ask", json={"text": "hi"})

    assert response.status_code == 200
    assert response.json() == {
        "text": "the answer",
        "path": "codex",
        "tool_used": None,
        "escalated": False,
    }


def test_web_q_executes_web_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool = FakeWebTool()

    def build_fake_web_tool(
        *,
        tavily_api_key: str,
    ) -> FakeWebTool:
        assert tavily_api_key == "test-key"
        return tool

    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    monkeypatch.setattr(ask_routes, "build_web_tool", build_fake_web_tool)
    client = client_for(FakeModel("local answer"), "web_q")

    response = client.post("/app/ask", json={"text": "current question"})

    assert response.status_code == 200
    assert response.json()["text"] == "web answer"
    assert response.json()["path"] == "web"
    assert response.json()["tool_used"] == "web"
    assert tool.queries == ["current question"]
    assert tool.closed is True


def test_web_q_without_key_degrades_to_local_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_build_web_tool(
        *,
        tavily_api_key: str,
    ) -> FakeWebTool:
        raise AssertionError(f"must not build without key: {tavily_api_key}")

    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.setattr(ask_routes, "build_web_tool", fail_build_web_tool)
    client = client_for(FakeModel("local answer", "gpt-5.5"), "web_q")

    response = client.post("/app/ask", json={"text": "current question"})

    assert response.status_code == 200
    body = response.json()
    assert body["path"] == "local"
    assert body["tool_used"] is None
    assert body["text"].startswith("(couldn't search; answering directly) ")
    assert body["text"].endswith("local answer")


def test_build_returns_signal_response() -> None:
    client = client_for(FakeModel(), "build")

    response = client.post("/app/ask", json={"text": "build me a calendar tool"})

    assert response.status_code == 200
    body = response.json()
    assert body["path"] == "build"
    assert body["tool_used"] is None
    assert "build mode" in body["text"]


def test_aggregate_returns_signal_response() -> None:
    client = client_for(FakeModel(), "aggregate")

    response = client.post("/app/ask", json={"text": "research this across many sources"})

    assert response.status_code == 200
    body = response.json()
    assert body["path"] == "aggregate"
    assert body["tool_used"] is None
    assert "Deep research" in body["text"]


def test_stream_uses_same_routing() -> None:
    client = client_for(FakeModel(), "aggregate")

    response = client.post("/app/ask/stream", json={"text": "research this"})

    assert response.status_code == 200
    assert "data: Deep research is not available yet." in response.text
    assert response.text.rstrip().endswith("data: [DONE]")


@pytest.mark.live
def test_live_real_web_q_smoke(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run the real web_q route smoke.

    PowerShell:
    $env:TAVILY_API_KEY="<real>"; uv run pytest tests/api/test_ask_routes.py -q -o addopts='' -m live -k real_web_q
    """
    if not os.environ.get("TAVILY_API_KEY"):
        pytest.skip("TAVILY_API_KEY is required for the live web_q smoke")

    app = create_app(model=FakeModel("unused"))
    app.dependency_overrides[require_session] = lambda: Principal(
        device_id="dev", person_id="owner"
    )
    app.dependency_overrides[ask_routes._intent] = lambda: FixedIntentRouter("web_q")
    client = TestClient(app)

    response = client.post("/app/ask", json={"text": "who won the 2022 world cup"})

    assert response.status_code == 200
    body = response.json()
    assert body["path"] == "web"
    assert body["tool_used"] == "web"
    assert body["text"]


def test_intent_uses_dedicated_haiku_port_not_shared_router() -> None:
    """Regression: _intent must build a dedicated claude_code Haiku port, NOT wrap the shared
    QuotaAwareRouter. Forcing model="haiku" onto the codex-primary router reaches Codex as an
    unknown model, fails non-failover-eligibly, and silently degrades every classify to plain_ask.
    """
    from types import SimpleNamespace

    from artemis.model.claude_code_provider import ClaudeCodeProvider
    from artemis.model.client import ModelClient

    sentinel = object()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(model=sentinel)))
    router = ask_routes._intent(request)  # type: ignore[arg-type]

    assert isinstance(router, IntentRouter)
    assert router._model is not sentinel
    assert isinstance(router._model, ModelClient)
    assert isinstance(router._model._provider, ClaudeCodeProvider)
