"""Tests for intent-routed ask routes."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
import json
import os
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, Request
import pytest
from fastapi.testclient import TestClient

from artemis.api import ask_routes
from artemis.api.app import create_app
from artemis.api.auth import Principal, require_session
from artemis.capabilities.fetch_sandbox import FetchResult, FetchSandbox
from artemis.capabilities.invoke import InvokeState
from artemis.capabilities.select import CapabilitySelector, SelectionResult
from artemis.data.curate import CurateExtractor
from artemis.data.read import ReadService
from artemis.data.store import DataStore, Record
from artemis.intent import Intent, IntentRouter, Route
from artemis.model.claude_code_provider import ClaudeCodeProvider
from artemis.model.client import ModelClient
from artemis.reachout.web_tool import WebAnswer
from artemis.types import Message, ModelResponse, SkillDraft, SkillInputParam, Usage


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


class FakeCurateModel:
    def __init__(self, reply: dict[str, str]) -> None:
        self._reply = reply

    async def complete(
        self,
        *,
        messages: Sequence[Message],
        model: str | None = None,
        response_schema: dict | None = None,  # type: ignore[type-arg]
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        del messages, response_schema, temperature, max_tokens
        return ModelResponse(
            text=json.dumps(self._reply),
            model_id=model or "fake",
            structured=None,
            finish_reason="stop",
            usage=Usage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )


class FakePhraser:
    async def complete(
        self,
        *,
        messages: Sequence[Message],
        model: str | None = None,
        response_schema: dict | None = None,  # type: ignore[type-arg]
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        del messages, response_schema, temperature, max_tokens
        return ModelResponse(
            text=json.dumps({"answer": "calendar answer"}),
            model_id=model or "fake",
            structured=None,
            finish_reason="stop",
            usage=Usage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
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


class RaisingIntentRouter(IntentRouter):
    def __init__(self) -> None:
        pass

    async def classify(self, text: str) -> Intent:
        raise AssertionError(f"intent classifier must not be called for {text}")


class FixedSelector:
    def __init__(self, selection: SelectionResult) -> None:
        self._selection = selection
        self.calls: list[str] = []

    async def select(self, request: str) -> SelectionResult:
        self.calls.append(request)
        return self._selection


class FakeWebTool:
    def __init__(self) -> None:
        self.queries: list[str] = []
        self.closed = False

    async def answer(self, query: str) -> WebAnswer:
        self.queries.append(query)
        return WebAnswer(answer="web answer", sources=["https://example.com/source"])

    async def aclose(self) -> None:
        self.closed = True


class FakeFetchSandbox(FetchSandbox):
    def __init__(
        self,
        result: FetchResult | None = None,
        *,
        raises: Exception | None = None,
        delay_s: float = 0.0,
    ) -> None:
        self.result = result or FetchResult(output="raw output", exit_code=0, truncated=False)
        self.raises = raises
        self.delay_s = delay_s
        self.calls = 0

    async def run(
        self,
        capability_dir: Path,
        *,
        entrypoint: str,
        argv: list[str],
        egress_domains: list[str],
        timeout_s: float = 60.0,
        secrets: dict[str, str] | None = None,
        caps_profile: Literal["default", "render"] = "default",
        output_limit: int = 4000,
    ) -> FetchResult:
        del capability_dir, entrypoint, argv, egress_domains, timeout_s, secrets
        del caps_profile, output_limit
        self.calls += 1
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        if self.raises is not None:
            raise self.raises
        return self.result


class FakeOAuthBroker:
    def __init__(self, token: str = "ya29.route-token") -> None:
        self.token = token
        self.calls: list[tuple[str, str]] = []

    async def mint_access_token(self, account: str, scope: str) -> str:
        self.calls.append((account, scope))
        return self.token


class MutableSecretStore:
    def __init__(self, values: dict[str, str] | None = None) -> None:
        self.values = dict(values or {})

    def get(self, name: str) -> str | None:
        return self.values.get(name)

    def set(self, name: str, value: str) -> None:
        self.values[name] = value

    def delete(self, name: str) -> None:
        self.values.pop(name, None)

    def list_names(self) -> list[str]:
        return sorted(self.values)


def client_for(
    model: FakeModel, route: Route, *, secrets: MutableSecretStore | None = None
) -> TestClient:
    app = create_app(model=model, secrets=secrets or MutableSecretStore())
    app.dependency_overrides[require_session] = lambda: Principal(
        device_id="dev", person_id="owner"
    )
    app.dependency_overrides[ask_routes._intent] = lambda: FixedIntentRouter(route)
    app.dependency_overrides[ask_routes._selector] = lambda: FixedSelector(_no_match())
    return TestClient(app)


def client_for_curate(
    tmp_path: Path,
    reply: dict[str, str],
    *,
    model: FakeModel | None = None,
    route: Route = "plain_ask",
) -> tuple[TestClient, FastAPI]:
    app = create_app(data_dir=tmp_path, model=model or FakeModel("unused"))
    app.dependency_overrides[require_session] = lambda: Principal(
        device_id="dev", person_id="owner"
    )
    app.dependency_overrides[ask_routes._intent] = lambda: FixedIntentRouter(route)
    app.dependency_overrides[ask_routes._selector] = lambda: FixedSelector(_no_match())
    app.dependency_overrides[ask_routes._curate_extractor] = lambda: CurateExtractor(
        FakeCurateModel(reply)
    )
    return TestClient(app), app


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
        "invoke_id": None,
        "capability": None,
        "egress_domains": None,
        "secrets": None,
        "args": None,
        "missing": None,
        "verdict": None,
        "verdict_reason": None,
        "answered_from": None,
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


def test_web_q_resolves_tavily_key_keychain_first(monkeypatch: pytest.MonkeyPatch) -> None:
    tool = FakeWebTool()

    def build_fake_web_tool(*, tavily_api_key: str) -> FakeWebTool:
        assert tavily_api_key == "from-keychain"
        return tool

    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.setattr(ask_routes, "build_web_tool", build_fake_web_tool)
    client = client_for(
        FakeModel("local answer"),
        "web_q",
        secrets=MutableSecretStore({"TAVILY_API_KEY": "from-keychain"}),
    )

    response = client.post("/app/ask", json={"text": "current question"})

    assert response.status_code == 200
    assert response.json()["path"] == "web"
    assert tool.queries == ["current question"]


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


def test_create_app_wires_selector_sandbox_and_invokes(tmp_path: Path) -> None:
    app = create_app(data_dir=tmp_path, model=FakeModel())

    assert isinstance(app.state.capability_selector, CapabilitySelector)
    assert isinstance(app.state.fetch_sandbox, FetchSandbox)
    assert app.state.invokes == {}
    assert app.state.last_results == {}


def test_curate_save_writes_and_confirms(tmp_path: Path) -> None:
    client, app = client_for_curate(
        tmp_path,
        {"op": "save", "domain": "tasks", "content": "renew passport", "referent": ""},
    )

    response = client.post("/app/ask", json={"text": "add a task: renew passport"})

    assert response.status_code == 200
    body = response.json()
    assert body["text"] == "Saved to tasks."
    assert body["path"] == "curate"
    rows = app.state.data_store.query(domain="tasks")
    assert len(rows) == 1
    assert rows[0].sanitized_text == "renew passport"


def test_curate_none_falls_through_to_ask(tmp_path: Path) -> None:
    client, _app = client_for_curate(
        tmp_path,
        {"op": "none", "domain": "", "content": "", "referent": ""},
        model=FakeModel("plain answer"),
    )

    response = client.post("/app/ask", json={"text": "hi"})

    assert response.status_code == 200
    body = response.json()
    assert body["path"] in {"codex", "local"}
    assert body["text"] == "plain answer"


def test_curate_runs_before_read(tmp_path: Path) -> None:
    client, app = client_for_curate(
        tmp_path,
        {"op": "save", "domain": "tasks", "content": "buy milk", "referent": ""},
    )
    store: DataStore = app.state.data_store
    store.upsert(
        Record(
            domain="calendar",
            kind="event",
            key="e1",
            payload={},
            sanitized_text="Standup at 9am",
            source="calendar-sync",
            fetched_at=100.0,
        )
    )

    response = client.post("/app/ask", json={"text": "add my calendar note: buy milk"})

    assert response.status_code == 200
    assert response.json()["path"] == "curate"


def test_curate_unresolved_referent_no_write(tmp_path: Path) -> None:
    client, app = client_for_curate(
        tmp_path,
        {"op": "save", "domain": "tasks", "content": "", "referent": "the second one"},
    )

    response = client.post("/app/ask", json={"text": "save the second one to tasks"})

    assert response.status_code == 200
    assert response.json()["text"] == "I couldn't find what you're referring to -- nothing changed."
    assert response.json()["path"] == "curate"
    assert app.state.data_store.query(domain="tasks") == []


def test_read_then_referent_save_end_to_end(tmp_path: Path) -> None:
    client, app = client_for_curate(
        tmp_path,
        {"op": "none", "domain": "", "content": "", "referent": ""},
    )
    store: DataStore = app.state.data_store
    first = "Dentist at 3pm"
    second = "Gym session at 5pm"
    store.upsert(
        Record(
            domain="calendar",
            kind="event",
            key="e1",
            payload={"secret": "PAYLOAD_ONLY"},
            sanitized_text=first,
            source="calendar-sync",
            fetched_at=200.0,
        )
    )
    store.upsert(
        Record(
            domain="calendar",
            kind="event",
            key="e2",
            payload={"secret": "PAYLOAD_ONLY"},
            sanitized_text=second,
            source="calendar-sync",
            fetched_at=100.0,
        )
    )
    app.dependency_overrides[ask_routes._read_service] = lambda: ReadService(
        store, phraser=FakePhraser(), now=lambda: 200.0
    )

    read_response = client.post("/app/ask", json={"text": "what's on my calendar"})

    assert read_response.status_code == 200
    assert read_response.json()["path"] == "local_read"

    app.dependency_overrides[ask_routes._curate_extractor] = lambda: CurateExtractor(
        FakeCurateModel(
            {"op": "save", "domain": "tasks", "content": "", "referent": "the second one"}
        )
    )
    save_response = client.post("/app/ask", json={"text": "save the second one to tasks"})

    assert save_response.status_code == 200
    assert save_response.json()["text"] == "Saved to tasks."
    rows = store.query(domain="tasks")
    assert len(rows) == 1
    assert rows[0].sanitized_text == second


def test_ask_returns_invoke_confirm_on_full_match(tmp_path: Path) -> None:
    app = create_app(data_dir=tmp_path, model=FakeModel())
    _promote_echo(app, inputs=[SkillInputParam(name="topic", type="string", description="Topic")])
    selector = FixedSelector(
        SelectionResult(
            matched=True,
            capability="Echo",
            args={"topic": "x"},
            confidence=0.9,
            missing_required=[],
        )
    )
    app.dependency_overrides[require_session] = lambda: Principal(
        device_id="dev", person_id="owner"
    )
    app.dependency_overrides[ask_routes._selector] = lambda: selector
    app.dependency_overrides[ask_routes._intent] = lambda: RaisingIntentRouter()
    client = TestClient(app)

    response = client.post("/app/ask", json={"text": "echo x"})

    assert response.status_code == 200
    body = response.json()
    assert body["path"] == "invoke_confirm"
    assert body["invoke_id"]
    assert body["capability"] == "Echo"
    assert body["egress_domains"] == ["api.example.com"]
    assert body["secrets"] == ["TOKEN"]
    assert body["args"] == {"topic": "x"}
    assert app.state.invokes[body["invoke_id"]].capability == "Echo"


def test_ask_returns_invoke_clarify_for_missing_required_args(tmp_path: Path) -> None:
    app = create_app(data_dir=tmp_path, model=FakeModel())
    selector = FixedSelector(
        SelectionResult(
            matched=True,
            capability="Echo",
            args={},
            confidence=0.9,
            missing_required=["topic"],
        )
    )
    app.dependency_overrides[require_session] = lambda: Principal(
        device_id="dev", person_id="owner"
    )
    app.dependency_overrides[ask_routes._selector] = lambda: selector
    client = TestClient(app)

    response = client.post("/app/ask", json={"text": "echo"})

    assert response.status_code == 200
    body = response.json()
    assert body["path"] == "invoke_clarify"
    assert body["capability"] == "Echo"
    assert body["missing"] == ["topic"]
    assert body["invoke_id"] is None
    assert app.state.invokes == {}


def test_ask_falls_through_when_selector_has_no_match() -> None:
    client = client_for(FakeModel("the answer", "gpt-5.5"), "plain_ask")

    response = client.post("/app/ask", json={"text": "hi"})

    assert response.status_code == 200
    assert response.json()["path"] == "codex"
    assert response.json()["text"] == "the answer"


def test_ask_falls_through_when_matched_capability_is_stale(tmp_path: Path) -> None:
    app = create_app(data_dir=tmp_path, model=FakeModel("the answer", "gpt-5.5"))
    app.dependency_overrides[require_session] = lambda: Principal(
        device_id="dev", person_id="owner"
    )
    app.dependency_overrides[ask_routes._selector] = lambda: FixedSelector(
        SelectionResult(
            matched=True,
            capability="Missing",
            args={},
            confidence=0.9,
            missing_required=[],
        )
    )
    app.dependency_overrides[ask_routes._intent] = lambda: FixedIntentRouter("plain_ask")
    client = TestClient(app)

    response = client.post("/app/ask", json={"text": "missing"})

    assert response.status_code == 200
    assert response.json()["path"] == "codex"
    assert app.state.invokes == {}


def test_ask_stream_runs_selector_first_for_invoke_confirm(tmp_path: Path) -> None:
    app = create_app(data_dir=tmp_path, model=FakeModel())
    _promote_echo(app, inputs=[SkillInputParam(name="topic", type="string", description="Topic")])
    app.dependency_overrides[require_session] = lambda: Principal(
        device_id="dev", person_id="owner"
    )
    app.dependency_overrides[ask_routes._selector] = lambda: FixedSelector(
        SelectionResult(
            matched=True,
            capability="Echo",
            args={"topic": "x"},
            confidence=0.9,
            missing_required=[],
        )
    )
    app.dependency_overrides[ask_routes._intent] = lambda: RaisingIntentRouter()
    client = TestClient(app)

    response = client.post("/app/ask/stream", json={"text": "echo x"})

    assert response.status_code == 200
    assert "data: Ready to run 'Echo'. Confirm to proceed." in response.text
    assert response.text.rstrip().endswith("data: [DONE]")


def test_confirm_route_runs_end_to_end_and_spends_state(tmp_path: Path) -> None:
    app = create_app(data_dir=tmp_path, model=FakeModel(json.dumps({"answer": "confirmed"})))
    _promote_echo(app, secrets=[])
    app.dependency_overrides[require_session] = lambda: Principal(
        device_id="dev", person_id="owner"
    )
    app.dependency_overrides[ask_routes._selector] = lambda: FixedSelector(
        SelectionResult(
            matched=True,
            capability="Echo",
            args={},
            confidence=0.9,
            missing_required=[],
        )
    )
    app.dependency_overrides[ask_routes._fetch_sandbox] = lambda: FakeFetchSandbox(
        FetchResult(output="raw output", exit_code=0, truncated=False)
    )
    app.dependency_overrides[ask_routes._quarantine_reader] = lambda: FakeModel(
        json.dumps({"relevant": True, "extract": "validated", "confidence": "high"})
    )
    client = TestClient(app)
    invoke_id = client.post("/app/ask", json={"text": "echo"}).json()["invoke_id"]

    first = client.post(f"/app/ask/invoke/{invoke_id}/confirm")
    second = client.post(f"/app/ask/invoke/{invoke_id}/confirm")

    assert first.status_code == 200
    assert first.json()["status"] == "ok"
    assert first.json()["text"] == "confirmed"
    assert second.json()["status"] == "not_found"


def test_confirm_route_passes_oauth_broker_to_invoke(tmp_path: Path) -> None:
    app = create_app(data_dir=tmp_path, model=FakeModel(json.dumps({"answer": "confirmed"})))
    _promote_echo(app, secrets=[], oauth_scopes=["scope-a"])
    broker = FakeOAuthBroker()
    app.state.oauth_broker = broker
    app.dependency_overrides[require_session] = lambda: Principal(
        device_id="dev", person_id="owner"
    )
    app.dependency_overrides[ask_routes._selector] = lambda: FixedSelector(
        SelectionResult(
            matched=True,
            capability="Echo",
            args={},
            confidence=0.9,
            missing_required=[],
        )
    )
    app.dependency_overrides[ask_routes._fetch_sandbox] = lambda: FakeFetchSandbox(
        FetchResult(output="raw output", exit_code=0, truncated=False)
    )
    app.dependency_overrides[ask_routes._quarantine_reader] = lambda: FakeModel(
        json.dumps({"relevant": True, "extract": "validated", "confidence": "high"})
    )
    client = TestClient(app)
    invoke_id = client.post("/app/ask", json={"text": "echo"}).json()["invoke_id"]

    response = client.post(f"/app/ask/invoke/{invoke_id}/confirm")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert broker.calls == [("default", "scope-a")]


@pytest.mark.asyncio
async def test_concurrent_confirm_runs_capability_at_most_once(tmp_path: Path) -> None:
    app = create_app(data_dir=tmp_path, model=FakeModel(json.dumps({"answer": "confirmed"})))
    await _promote_echo_async(app, secrets=[])
    app.state.invokes["invoke-1"] = InvokeState(
        capability="Echo",
        args={},
        request_text="echo",
    )
    sandbox = FakeFetchSandbox(delay_s=0.01)
    request = Request({"type": "http", "app": app, "headers": []})

    first, second = await asyncio.gather(
        ask_routes.confirm_invoke_route(
            "invoke-1",
            request,
            _principal=Principal(device_id="dev", person_id="owner"),
            capability_store=app.state.capability_store,
            secrets_store=app.state.secrets,
            sandbox=sandbox,
            synth=FakeModel(json.dumps({"answer": "confirmed"})),
            reader=FakeModel(
                json.dumps({"relevant": True, "extract": "validated", "confidence": "high"})
            ),
        ),
        ask_routes.confirm_invoke_route(
            "invoke-1",
            request,
            _principal=Principal(device_id="dev", person_id="owner"),
            capability_store=app.state.capability_store,
            secrets_store=app.state.secrets,
            sandbox=sandbox,
            synth=FakeModel(json.dumps({"answer": "confirmed"})),
            reader=FakeModel(
                json.dumps({"relevant": True, "extract": "validated", "confidence": "high"})
            ),
        ),
    )

    assert sorted([first.status, second.status]) == ["not_found", "ok"]
    assert sandbox.calls == 1
    assert app.state.invokes == {}


def test_confirm_route_reinserts_state_only_on_missing_secrets(tmp_path: Path) -> None:
    secrets = MutableSecretStore()
    app = create_app(
        data_dir=tmp_path,
        model=FakeModel(json.dumps({"answer": "confirmed"})),
        secrets=secrets,
    )
    _promote_echo(app, secrets=["TOKEN"])
    app.dependency_overrides[require_session] = lambda: Principal(
        device_id="dev", person_id="owner"
    )
    app.dependency_overrides[ask_routes._selector] = lambda: FixedSelector(
        SelectionResult(
            matched=True,
            capability="Echo",
            args={},
            confidence=0.9,
            missing_required=[],
        )
    )
    app.dependency_overrides[ask_routes._fetch_sandbox] = lambda: FakeFetchSandbox()
    app.dependency_overrides[ask_routes._quarantine_reader] = lambda: FakeModel(
        json.dumps({"relevant": True, "extract": "validated", "confidence": "high"})
    )
    client = TestClient(app)
    invoke_id = client.post("/app/ask", json={"text": "echo"}).json()["invoke_id"]

    first = client.post(f"/app/ask/invoke/{invoke_id}/confirm")
    secrets.set("TOKEN", "resolved")
    second = client.post(f"/app/ask/invoke/{invoke_id}/confirm")

    assert first.json()["status"] == "missing_secrets"
    assert first.json()["missing_secrets"] == ["TOKEN"]
    assert second.json()["status"] == "ok"
    assert invoke_id not in app.state.invokes


def test_confirm_route_drops_state_on_error(tmp_path: Path) -> None:
    app = create_app(data_dir=tmp_path, model=FakeModel(json.dumps({"answer": "confirmed"})))
    _promote_echo(app, secrets=[])
    app.dependency_overrides[require_session] = lambda: Principal(
        device_id="dev", person_id="owner"
    )
    app.dependency_overrides[ask_routes._selector] = lambda: FixedSelector(
        SelectionResult(
            matched=True,
            capability="Echo",
            args={},
            confidence=0.9,
            missing_required=[],
        )
    )
    app.dependency_overrides[ask_routes._fetch_sandbox] = lambda: FakeFetchSandbox(
        raises=RuntimeError("boom")
    )
    client = TestClient(app)
    invoke_id = client.post("/app/ask", json={"text": "echo"}).json()["invoke_id"]

    first = client.post(f"/app/ask/invoke/{invoke_id}/confirm")
    second = client.post(f"/app/ask/invoke/{invoke_id}/confirm")

    assert first.json()["status"] == "error"
    assert invoke_id not in app.state.invokes
    assert second.json()["status"] == "not_found"


def test_new_proposal_evicts_expired_invoke(tmp_path: Path) -> None:
    from artemis.capabilities import invoke as invoke_mod

    app = create_app(data_dir=tmp_path, model=FakeModel())
    _promote_echo(app, inputs=[SkillInputParam(name="topic", type="string", description="Topic")])
    app.dependency_overrides[require_session] = lambda: Principal(
        device_id="dev", person_id="owner"
    )
    app.dependency_overrides[ask_routes._selector] = lambda: FixedSelector(
        SelectionResult(
            matched=True,
            capability="Echo",
            args={"topic": "x"},
            confidence=0.9,
            missing_required=[],
        )
    )
    app.dependency_overrides[ask_routes._intent] = lambda: RaisingIntentRouter()
    client = TestClient(app)

    # A stale proposal older than the TTL should be gone once the next proposal is created.
    stale = InvokeState(capability="Echo", args={}, request_text="old")
    stale.created_at -= invoke_mod._INVOKE_TTL_SECONDS + 1
    app.state.invokes["stale"] = stale

    fresh_id = client.post("/app/ask", json={"text": "echo x"}).json()["invoke_id"]

    assert "stale" not in app.state.invokes
    assert fresh_id in app.state.invokes


def test_confirm_route_returns_not_found_for_unknown_invoke_id(tmp_path: Path) -> None:
    app = create_app(data_dir=tmp_path, model=FakeModel())
    app.dependency_overrides[require_session] = lambda: Principal(
        device_id="dev", person_id="owner"
    )
    client = TestClient(app)

    response = client.post("/app/ask/invoke/does-not-exist/confirm")

    assert response.status_code == 200
    assert response.json()["status"] == "not_found"


def test_confirm_route_requires_session(tmp_path: Path) -> None:
    client = TestClient(create_app(data_dir=tmp_path, model=FakeModel()))

    response = client.post("/app/ask/invoke/x/confirm")

    assert response.status_code == 401


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
    app.dependency_overrides[ask_routes._selector] = lambda: FixedSelector(_no_match())
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

    sentinel = object()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(model=sentinel)))
    router = ask_routes._intent(request)  # type: ignore[arg-type]

    assert isinstance(router, IntentRouter)
    assert router._model is not sentinel
    assert isinstance(router._model, ModelClient)
    assert isinstance(router._model._provider, ClaudeCodeProvider)


def test_quarantine_reader_uses_dedicated_haiku_port_not_shared_router() -> None:
    from types import SimpleNamespace

    sentinel = object()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(model=sentinel)))
    reader = ask_routes._quarantine_reader(request)  # type: ignore[arg-type]

    assert reader is not sentinel
    assert isinstance(reader, ModelClient)
    assert isinstance(reader._provider, ClaudeCodeProvider)
    assert reader._model_default == "haiku"


def _no_match() -> SelectionResult:
    return SelectionResult(
        matched=False,
        capability=None,
        args={},
        confidence=0.0,
        missing_required=[],
    )


def _promote_echo(
    app: FastAPI,
    *,
    inputs: list[SkillInputParam] | None = None,
    secrets: list[str] | None = None,
    oauth_scopes: list[str] | None = None,
) -> None:
    asyncio.run(_promote_echo_async(app, inputs=inputs, secrets=secrets, oauth_scopes=oauth_scopes))


async def _promote_echo_async(
    app: FastAPI,
    *,
    inputs: list[SkillInputParam] | None = None,
    secrets: list[str] | None = None,
    oauth_scopes: list[str] | None = None,
) -> None:
    staged = await app.state.capability_store.stage(
        SkillDraft(
            name="Echo",
            description="Echoes text.",
            body="Use this skill to echo text.",
            tool_script="print('echo')\n",
            inputs=inputs or [],
            uses=[],
            secrets=["TOKEN"] if secrets is None else secrets,
            oauth_scopes=oauth_scopes or [],
            egress_domains=["api.example.com"],
            tests="def test_skill() -> None:\n    assert True\n",
        )
    )
    await app.state.capability_store.promote(staged.id)
