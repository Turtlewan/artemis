from __future__ import annotations

import hashlib
import io
import json
import logging
import sys
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from pydantic import BaseModel

import artemis.obs.logging as obs_logging
from artemis.brain import Brain
from artemis.manifest import ActionRisk, DataScope, ModuleManifest, ToolSpec
from artemis.obs import (
    CompositeSink,
    ErrorCaptureSink,
    ErrorRecord,
    ErrorStore,
    ObservabilitySink,
    configure_logging,
    get_logger,
    redact,
)
from artemis.ports.model import ModelResponse
from artemis.ports.types import Message, Usage, Vector
from artemis.recipes import (
    RECIPE_SCHEMA,
    CloudEgressForbiddenError,
    DistillService,
    EscalationRequest,
    RecipeSigner,
    RecipeStore,
)
from artemis.registry import ToolRegistry
from artemis.router import SemanticRouter


class SpySink:
    def __init__(self) -> None:
        self.route_decisions: list[tuple[str, float, str, datetime]] = []
        self.escalations: list[tuple[str, bool, datetime]] = []
        self.errors: list[tuple[str, BaseException, datetime]] = []

    def on_route_decision(
        self,
        task_class_key: str,
        confidence: float,
        path: str,
        *,
        now: datetime,
    ) -> None:
        self.route_decisions.append((task_class_key, confidence, path, now))

    def on_escalation(
        self,
        task_class_key: str,
        *,
        is_cloud_safe: bool,
        now: datetime,
    ) -> None:
        self.escalations.append((task_class_key, is_cloud_safe, now))

    def on_error(self, component: str, exc: BaseException, *, now: datetime) -> None:
        self.errors.append((component, exc, now))

    def on_injection_flagged(self, source_domain: str, *, now: datetime) -> None:
        pass


class RaisingSink:
    def on_route_decision(
        self,
        task_class_key: str,
        confidence: float,
        path: str,
        *,
        now: datetime,
    ) -> None:
        raise RuntimeError("leaky secret child failure")

    def on_escalation(
        self,
        task_class_key: str,
        *,
        is_cloud_safe: bool,
        now: datetime,
    ) -> None:
        raise RuntimeError("leaky secret child failure")

    def on_error(self, component: str, exc: BaseException, *, now: datetime) -> None:
        raise RuntimeError("leaky secret child failure")


class FakeEmbedder:
    @property
    def dimension(self) -> int:
        return 8

    async def embed_documents(self, texts: Sequence[str]) -> list[Vector]:
        return [self._embed(text) for text in texts]

    async def embed_query(self, query: str) -> Vector:
        return self._embed(query)

    def _embed(self, text: str) -> Vector:
        tokens = {token.strip(".,").lower() for token in text.split()}
        values = [0.0] * self.dimension
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            values[digest[0] % self.dimension] += 1.0
        return values


class FakeKeyProvider:
    def signing_key(self) -> bytes:
        return b"test-obs-core-recipe-signing-key"


class FakeTeacher:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, bool]] = []

    async def complete(
        self,
        *,
        role: str,
        messages: Sequence[Message],
        response_schema: dict[str, object] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        del temperature, max_tokens
        prompt = messages[-1].content
        self.calls.append((role, prompt, response_schema is not None))
        if role == "teacher" and response_schema == RECIPE_SCHEMA:
            return ModelResponse(text=json.dumps(_recipe_payload()))
        if role == "teacher":
            return ModelResponse(text="teacher solved the instance")
        return ModelResponse(text=json.dumps({"summary": "schema-valid replay"}))

    def complete_stream(
        self,
        *,
        role: str,
        messages: Sequence[Message],
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        del role, messages, temperature

        async def _gen() -> AsyncIterator[str]:
            yield "chunk"

        return _gen()

    async def embed(self, role: str, texts: Sequence[str]) -> list[Vector]:
        del role
        return [[0.0] for _ in texts]


class FakeModelPort:
    async def complete(
        self,
        *,
        role: str,
        messages: Sequence[Message],
        response_schema: dict[str, object] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        del role, messages, temperature, max_tokens
        if response_schema is not None:
            return ModelResponse(text='{"tz": null}', usage=Usage(10, 5, 15))
        return ModelResponse(text="local response", usage=Usage(10, 5, 15))

    def complete_stream(
        self,
        *,
        role: str,
        messages: Sequence[Message],
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        del role, messages, temperature

        async def _gen() -> AsyncIterator[str]:
            yield "stream"

        return _gen()

    async def embed(self, role: str, texts: Sequence[str]) -> list[Vector]:
        del role
        return [[0.0] * 16 for _ in texts]


class TimeArgs(BaseModel):
    tz: str | None = None


class TimeResult(BaseModel):
    iso: str
    tz: str


async def fake_time(args: TimeArgs) -> TimeResult:
    return TimeResult(iso="2026-06-24T12:00:00", tz=args.tz or "UTC")


class FailingArgs(BaseModel):
    x: str | None = None


class FailingResult(BaseModel):
    ok: bool


async def fake_failing(args: FailingArgs) -> FailingResult:
    del args
    raise RuntimeError("intentional tool failure")


def _recipe_payload() -> dict[str, object]:
    return {
        "name": "summarize_request",
        "description": "summarize request for replay verification",
        "recipe_class": "instructions",
        "action_class": "read-only",
        "inputs_schema": {"type": "object"},
        "outputs_schema": {
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
            "additionalProperties": False,
        },
        "instructions": "Summarize the request into a short summary.",
        "script": None,
    }


def _store(tmp_path: Path) -> RecipeStore:
    return RecipeStore(FakeEmbedder(), tmp_path, signer=RecipeSigner(FakeKeyProvider()))


def _request(*, is_cloud_safe: bool = True) -> EscalationRequest:
    return EscalationRequest(
        request_text="Summarize my private agenda item",
        scope="owner-private",
        task_class_key="summary.task",
        is_cloud_safe=is_cloud_safe,
    )


def _registry_with_tool(*, failing: bool = False) -> ToolRegistry:
    embedder = FakeEmbedder()
    reg = ToolRegistry(embedder)
    if failing:
        tools = [
            ToolSpec(
                name="fail_tool",
                description="Fail on purpose.",
                args_schema=FailingArgs,
                return_schema=FailingResult,
                callable_ref=fake_failing,
                action_risk=ActionRisk.NO_DATA,
            )
        ]
        name = "fail"
        scope = DataScope.OWNER_PRIVATE
    else:
        tools = [
            ToolSpec(
                name="get_current_time",
                description="Get the current date and time.",
                args_schema=TimeArgs,
                return_schema=TimeResult,
                callable_ref=fake_time,
                action_risk=ActionRisk.NO_DATA,
            )
        ]
        name = "time"
        scope = DataScope.SHARED
    reg.register(
        ModuleManifest(
            name=name,
            version="0.1.0",
            description="Test module.",
            data_scope=scope,
            tools=tools,
        )
    )
    return reg


def _router(registry: ToolRegistry) -> SemanticRouter:
    return SemanticRouter(registry, FakeEmbedder())


def test_configure_logging_emits_json_and_redacts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = io.StringIO()
    monkeypatch.setattr(sys, "stdout", stream)
    monkeypatch.setattr(obs_logging, "_CONFIGURED", False)

    configure_logging()
    get_logger("t").info(
        "hi",
        extra={"token": "A" * 24, "content": "x", "nested": {"password": "p" * 8}, "n": 3},
    )

    payload = json.loads(stream.getvalue())
    assert payload["msg"] == "hi"
    assert payload["extra"]["token"] == "***REDACTED***"
    assert "content" not in payload["extra"]
    assert payload["extra"]["nested"]["password"] == "***REDACTED***"
    assert payload["extra"]["n"] == 3


def test_redact_boundaries_and_key_rules() -> None:
    assert redact("A" * 19) == "A" * 19
    assert redact("A" * 20) == "***REDACTED***"
    assert redact(b"\xab\xcd") == "***REDACTED***"
    assert redact({"handle": "h", "ok": 3}) == {"handle": "***REDACTED***", "ok": 3}
    assert redact({"content": "drop", "nested": [{"prompt": "drop"}, {"ok": "keep"}]}) == {
        "nested": [{}, {"ok": "keep"}]
    }


def test_composite_sink_fans_out_and_logs_only_failure_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = io.StringIO()
    monkeypatch.setattr(sys, "stdout", stream)
    monkeypatch.setattr(obs_logging, "_CONFIGURED", False)
    configure_logging(logging.INFO)
    spy = SpySink()
    composite = CompositeSink(
        [cast(ObservabilitySink, spy), cast(ObservabilitySink, RaisingSink())]
    )

    composite.on_error("brain", ValueError("raw secret message"), now=datetime.now(UTC))

    assert len(spy.errors) == 1
    payload = json.loads(stream.getvalue())
    assert payload["msg"] == "sink_child_failed"
    assert payload["extra"] == {"error_type": "RuntimeError", "sink": "RaisingSink"}
    assert "leaky secret child failure" not in stream.getvalue()
    assert "raw secret message" not in stream.getvalue()


def test_error_store_round_trip_and_error_capture_redacts(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    store = ErrorStore(tmp_path / "e.jsonl")
    store.append(
        ErrorRecord(component="brain", error_type="ValueError", message="redacted", at=now)
    )
    assert store.list() == [
        ErrorRecord(component="brain", error_type="ValueError", message="redacted", at=now)
    ]

    raw_secret = "A" * 32
    capture_store = ErrorStore(tmp_path / "captured.jsonl")
    ErrorCaptureSink(capture_store).on_error(
        "brain",
        ValueError("token: " + raw_secret),
        now=now,
    )

    records = capture_store.list()
    assert len(records) == 1
    assert records[0].error_type == "ValueError"
    assert "***REDACTED***" in records[0].message
    assert raw_secret not in records[0].message
    assert not hasattr(records[0], "traceback")


async def test_brain_route_and_error_taps_avoid_raw_request_text() -> None:
    request_text = "what time is it"
    spy = SpySink()
    registry = _registry_with_tool()
    brain = Brain(_router(registry), registry, FakeModelPort(), obs=spy)

    response = await brain.respond(request_text, "owner-private")

    assert response.tool_used == "time.get_current_time"
    assert len(spy.route_decisions) == 1
    task_key, confidence, path, _now = spy.route_decisions[0]
    assert task_key
    assert confidence > 0.0
    assert path in {"deterministic", "local"}
    assert request_text not in {str(value) for value in spy.route_decisions[0]}

    failing_spy = SpySink()
    failing_registry = _registry_with_tool(failing=True)
    failing_brain = Brain(
        _router(failing_registry), failing_registry, FakeModelPort(), obs=failing_spy
    )
    failed = await failing_brain.respond("fail on purpose", "owner-private")

    assert failed.text == "TOOL_ERROR"
    assert len(failing_spy.errors) == 1
    assert failing_spy.errors[0][0] == "brain"

    default_brain = Brain(_router(registry), registry, FakeModelPort())
    default_response = await default_brain.respond(request_text, "owner-private")
    assert default_response.text


async def test_distill_escalation_and_error_taps(tmp_path: Path) -> None:
    spy = SpySink()
    store = _store(tmp_path)
    req = _request()
    service = DistillService(model=FakeTeacher(), store=store, teacher_origin="local", obs=spy)

    recipe = await service.escalate_and_distill(req)

    assert recipe.task_class_key == req.task_class_key
    assert spy.escalations == [(req.task_class_key, req.is_cloud_safe, spy.escalations[0][2])]
    assert spy.errors == []

    error_spy = SpySink()
    cloud_service = DistillService(
        model=FakeTeacher(),
        store=_store(tmp_path / "cloud"),
        teacher_origin="cloud",
        obs=error_spy,
    )
    unsafe_req = _request(is_cloud_safe=False)

    with pytest.raises(CloudEgressForbiddenError):
        await cloud_service.escalate_and_distill(unsafe_req)

    assert len(error_spy.escalations) == 1
    assert error_spy.escalations[0][0] == unsafe_req.task_class_key
    assert len(error_spy.errors) == 1
    assert error_spy.errors[0][0] == "distill"
