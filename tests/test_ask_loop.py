from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from artemis.agent import EscalatingLoop
from artemis.agent.loop import LoopResult, StepRecord, StopReason, Verdict
from artemis.api import ask_routes
from artemis.api.app import create_app
from artemis.api.auth import Principal, require_session
from artemis.capabilities.select import SelectionResult
from artemis.data.store import DataStore
from artemis.intent import Intent, IntentRouter, Route
from artemis.types import Message, ModelResponse, Usage


class FakeModel:
    def __init__(self, text: str = "legacy answer", model_id: str = "qwen3:4b") -> None:
        self._text = text
        self._model_id = model_id

    async def complete(
        self,
        *,
        messages: Sequence[Message],
        model: str | None = None,
        response_schema: dict[str, Any] | None = None,
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


class FixedIntentRouter(IntentRouter):
    def __init__(self, route: Route) -> None:
        self._route = route

    async def classify(self, text: str) -> Intent:
        return Intent(route=self._route, confidence=1.0, reason=text)


class FixedSelector:
    async def select(self, request: str) -> SelectionResult:
        del request
        return SelectionResult(
            matched=False,
            capability=None,
            args={},
            confidence=0.0,
            missing_required=[],
        )


class FakeLoop:
    def __init__(self, result: LoopResult) -> None:
        self._result = result
        self.calls: list[str] = []

    async def run(self, request: str) -> LoopResult:
        self.calls.append(request)
        return self._result


class FakeRegistry:
    def for_role(self, role: str) -> FakeModel:
        del role
        return FakeModel()


class RaisingRegistry:
    def for_role(self, role: str) -> FakeModel:
        raise RuntimeError(f"failed to resolve {role}")


class NoneJudgeRegistry:
    def for_role(self, role: str) -> FakeModel | None:
        if role == "judge":
            return None
        return FakeModel()


def _ok_step() -> StepRecord:
    return StepRecord(
        index=0,
        tool="local_read",
        args={"domain": "calendar"},
        outcome="1 record",
        ok=True,
        duration_ms=1,
        driver_ms=1,
        driver_tokens=0,
    )


def _fail_step() -> StepRecord:
    return StepRecord(
        index=0,
        tool="nope",
        args={},
        outcome="unknown tool",
        ok=False,
        duration_ms=1,
        driver_ms=1,
        driver_tokens=0,
    )


def _lr(
    answer: str,
    *,
    steps: tuple[StepRecord, ...] = (),
    stop_reason: StopReason = "answered",
    verdict: Verdict = "unjudged",
    verdict_reason: str = "",
    escalated: bool = False,
) -> LoopResult:
    return LoopResult(
        answer=answer,
        steps=steps,
        stop_reason=stop_reason,
        driver_turns=1,
        driver_tokens_total=0,
        verdict=verdict,
        verdict_reason=verdict_reason,
        escalated=escalated,
    )


def _client(
    tmp_path: Path,
    model: FakeModel,
    *,
    route: Route = "plain_ask",
    loop: FakeLoop | None = None,
    enable: bool | None = None,
) -> TestClient:
    app = create_app(data_dir=tmp_path, model=model, enable_agent_loop=enable)
    app.dependency_overrides[require_session] = lambda: Principal(
        device_id="dev", person_id="owner"
    )
    app.dependency_overrides[ask_routes._intent] = lambda: FixedIntentRouter(route)
    app.dependency_overrides[ask_routes._selector] = lambda: FixedSelector()
    if loop is not None:
        app.dependency_overrides[ask_routes._agent_loop] = lambda: cast(EscalatingLoop, loop)
    return TestClient(app)


def _request(*, enabled: bool, roles: object | None) -> Request:
    return cast(
        Request,
        SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(
                    agent_loop_enabled=enabled,
                    model_roles=roles,
                    data_store=DataStore(":memory:"),
                )
            )
        ),
    )


def test_flag_off_uses_legacy_answer_with_loop_fields_null(tmp_path: Path) -> None:
    client = _client(tmp_path, FakeModel("legacy", "qwen3:4b"), enable=False)

    response = client.post("/app/ask", json={"text": "hi"})

    assert response.status_code == 200
    body = response.json()
    assert body["text"] == "legacy"
    assert body["path"] in {"local", "codex"}
    assert body["verdict"] is None
    assert body["verdict_reason"] is None
    assert body["answered_from"] is None
    assert body["escalated"] is False


def test_flag_on_injected_loop_maps_passed_answer_from_local_data(tmp_path: Path) -> None:
    loop = FakeLoop(
        _lr(
            "you have lunch",
            steps=(_ok_step(),),
            verdict="passed",
            verdict_reason="grounded",
        )
    )
    client = _client(tmp_path, FakeModel(), loop=loop, enable=True)

    response = client.post("/app/ask", json={"text": "hi"})

    assert response.status_code == 200
    body = response.json()
    assert body["text"] == "you have lunch"
    assert body["path"] == "loop"
    assert body["verdict"] == "passed"
    assert body["verdict_reason"] == "grounded"
    assert body["answered_from"] == "local_data"
    assert body["escalated"] is False
    assert loop.calls == ["hi"]


def test_zero_tool_steps_map_to_general_knowledge_and_empty_reason_null(
    tmp_path: Path,
) -> None:
    loop = FakeLoop(_lr("from memory", verdict="unjudged", verdict_reason=""))
    client = _client(tmp_path, FakeModel(), loop=loop, enable=True)

    response = client.post("/app/ask", json={"text": "hi"})

    assert response.status_code == 200
    body = response.json()
    assert body["answered_from"] == "general_knowledge"
    assert body["verdict"] == "unjudged"
    assert body["verdict_reason"] is None


def test_failed_only_steps_map_to_general_knowledge(tmp_path: Path) -> None:
    loop = FakeLoop(_lr("x", steps=(_fail_step(),)))
    client = _client(tmp_path, FakeModel(), loop=loop, enable=True)

    response = client.post("/app/ask", json={"text": "hi"})

    assert response.status_code == 200
    assert response.json()["answered_from"] == "general_knowledge"


@pytest.mark.parametrize("stop_reason", ["budget_exhausted", "stalling"])
def test_non_answered_stops_deliver_partial_unjudged(
    tmp_path: Path, stop_reason: StopReason
) -> None:
    loop = FakeLoop(
        _lr(
            "I couldn't fully answer - partial.",
            steps=(_ok_step(),),
            stop_reason=stop_reason,
        )
    )
    client = _client(tmp_path, FakeModel(), loop=loop, enable=True)

    response = client.post("/app/ask", json={"text": "hi"})

    assert response.status_code == 200
    body = response.json()
    assert body["text"] == "I couldn't fully answer - partial."
    assert body["verdict"] == "unjudged"
    assert body["verdict_reason"] is None
    assert body["answered_from"] == "local_data"
    assert body["path"] == "loop"


def test_escalated_flag_propagates(tmp_path: Path) -> None:
    loop = FakeLoop(_lr("done", steps=(_ok_step(),), escalated=True))
    client = _client(tmp_path, FakeModel(), loop=loop, enable=True)

    response = client.post("/app/ask", json={"text": "hi"})

    assert response.status_code == 200
    assert response.json()["escalated"] is True


def test_loop_runs_on_stream_route(tmp_path: Path) -> None:
    loop = FakeLoop(
        _lr(
            "you have lunch",
            steps=(_ok_step(),),
            verdict="passed",
            verdict_reason="grounded",
        )
    )
    client = _client(tmp_path, FakeModel(), loop=loop, enable=True)

    response = client.post("/app/ask/stream", json={"text": "hi"})

    assert response.status_code == 200
    assert "data: you have lunch" in response.text
    assert response.text.rstrip().endswith("data: [DONE]")
    assert loop.calls == ["hi"]


def test_non_plain_ask_does_not_run_loop(tmp_path: Path) -> None:
    loop = FakeLoop(_lr("SHOULD-NOT-APPEAR"))
    client = _client(tmp_path, FakeModel(), route="build", loop=loop, enable=True)

    response = client.post("/app/ask", json={"text": "build me a tool"})

    assert response.status_code == 200
    body = response.json()
    assert body["path"] == "build"
    assert body["verdict"] is None
    assert loop.calls == []


def test_no_registry_falls_back_to_none() -> None:
    assert ask_routes._agent_loop(_request(enabled=True, roles=None)) is None


def test_flag_off_dependency_returns_none() -> None:
    assert ask_routes._agent_loop(_request(enabled=False, roles=FakeRegistry())) is None


def test_flag_on_with_registry_builds_escalating_loop() -> None:
    assert isinstance(
        ask_routes._agent_loop(_request(enabled=True, roles=FakeRegistry())),
        EscalatingLoop,
    )


def test_create_app_reads_env_flag_fail_closed_and_kwarg_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ARTEMIS_AGENT_LOOP", "1")
    assert create_app(data_dir=tmp_path, model=FakeModel()).state.agent_loop_enabled is True

    monkeypatch.setenv("ARTEMIS_AGENT_LOOP", "0")
    assert create_app(data_dir=tmp_path, model=FakeModel()).state.agent_loop_enabled is False

    monkeypatch.setenv("ARTEMIS_AGENT_LOOP", "yes")
    assert create_app(data_dir=tmp_path, model=FakeModel()).state.agent_loop_enabled is False

    monkeypatch.delenv("ARTEMIS_AGENT_LOOP", raising=False)
    assert (
        create_app(
            data_dir=tmp_path, model=FakeModel(), enable_agent_loop=True
        ).state.agent_loop_enabled
        is True
    )


def test_role_resolution_raise_falls_back_to_none() -> None:
    assert ask_routes._agent_loop(_request(enabled=True, roles=RaisingRegistry())) is None


def test_role_resolving_none_falls_back_to_none() -> None:
    assert ask_routes._agent_loop(_request(enabled=True, roles=NoneJudgeRegistry())) is None


def test_integration_registry_absent_serves_legacy(tmp_path: Path) -> None:
    app = create_app(data_dir=tmp_path, model=FakeModel("legacy"), enable_agent_loop=True)
    app.state.model_roles = None
    app.dependency_overrides[require_session] = lambda: Principal(
        device_id="dev", person_id="owner"
    )
    app.dependency_overrides[ask_routes._intent] = lambda: FixedIntentRouter("plain_ask")
    app.dependency_overrides[ask_routes._selector] = lambda: FixedSelector()
    client = TestClient(app)

    response = client.post("/app/ask", json={"text": "hi"})

    assert response.status_code == 200
    body = response.json()
    assert body["path"] != "loop"
    assert body["text"] == "legacy"
    assert body["verdict"] is None
    assert body["verdict_reason"] is None
    assert body["answered_from"] is None
