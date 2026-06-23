"""Tests for Brain sensitivity-based free-form responder routing."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import cast

import pytest
from pydantic import BaseModel

from artemis.brain import Brain
from artemis.manifest import ActionRisk, DataScope, ModuleManifest, Permissions, ToolSpec
from artemis.ports.model import ModelResponse
from artemis.ports.routing import RouteDecision
from artemis.ports.types import Message, Scope, Usage, Vector
from artemis.registry import ToolRegistry
from artemis.router import SemanticRouter
from artemis.sensitivity import Sensitivity


class FakeRouter:
    """Router double returning a preconfigured decision."""

    def __init__(self, decision: RouteDecision) -> None:
        self.decision = decision

    async def route(self, request_text: str, scope: Scope) -> RouteDecision:
        return self.decision


class FakeEmbedder:
    @property
    def dimension(self) -> int:
        return 4

    async def embed_documents(self, texts: Sequence[str]) -> list[Vector]:
        return [[1.0, 0.0, 0.0, 0.0] for _ in texts]

    async def embed_query(self, query: str) -> Vector:
        return [1.0, 0.0, 0.0, 0.0]


class RecordingModelPort:
    """Fake ModelPort recording responder roles."""

    def __init__(self) -> None:
        self.complete_roles: list[str] = []
        self.stream_roles: list[str] = []
        self.response_schema_seen: dict[str, object] | None = None

    async def complete(
        self,
        *,
        role: str,
        messages: Sequence[Message],
        response_schema: dict[str, object] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        self.complete_roles.append(role)
        self.response_schema_seen = response_schema
        text = '{"tz": null}' if response_schema is not None else "free-form"
        return ModelResponse(
            text=text,
            finish_reason="stop",
            usage=Usage(1, 1, 2),
            origin="local",
            model_id="fake",
        )

    def complete_stream(
        self,
        *,
        role: str,
        messages: Sequence[Message],
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        self.stream_roles.append(role)

        async def _gen() -> AsyncIterator[str]:
            yield "chunk"

        return _gen()

    async def embed(self, role: str, texts: Sequence[str]) -> list[Vector]:
        return [[0.0] for _ in texts]


class SpyClassifier:
    """Async classifier spy."""

    def __init__(self, sensitivity: Sensitivity = "general", raises: bool = False) -> None:
        self.sensitivity = sensitivity
        self.raises = raises
        self.call_count = 0

    async def classify(self, request_text: str) -> Sensitivity:
        self.call_count += 1
        if self.raises:
            raise RuntimeError("classifier unavailable")
        return self.sensitivity


class TimeArgs(BaseModel):
    tz: str | None = None


class TimeResult(BaseModel):
    iso: str
    tz: str


async def fake_time(args: TimeArgs) -> TimeResult:
    return TimeResult(iso="2026-06-23T12:00:00", tz=args.tz or "UTC")


def _registry() -> ToolRegistry:
    return ToolRegistry(FakeEmbedder())


def _brain(
    model: RecordingModelPort,
    *,
    classifier: SpyClassifier | None,
    cloud_reasoning_enabled: bool = True,
    decision: RouteDecision | None = None,
    registry: ToolRegistry | None = None,
) -> Brain:
    route_decision = decision or RouteDecision(path="local", candidate_tools=[], confidence=0.5)
    return Brain(
        cast(SemanticRouter, FakeRouter(route_decision)),
        registry or _registry(),
        model,
        classifier=classifier,
        cloud_reasoning_enabled=cloud_reasoning_enabled,
    )


@pytest.mark.asyncio
async def test_sensitive_free_form_respond_uses_local_responder() -> None:
    model = RecordingModelPort()
    brain = _brain(model, classifier=SpyClassifier("sensitive"))

    await brain.respond("summarize my bank statement", "owner-private")

    assert model.complete_roles == ["responder"]


@pytest.mark.asyncio
async def test_general_free_form_respond_uses_cloud_responder() -> None:
    model = RecordingModelPort()
    brain = _brain(model, classifier=SpyClassifier("general"))

    await brain.respond("explain photosynthesis", "owner-private")

    assert model.complete_roles == ["responder_cloud"]


@pytest.mark.asyncio
async def test_cloud_kill_switch_forces_local_and_skips_classifier() -> None:
    model = RecordingModelPort()
    classifier = SpyClassifier("general")
    brain = _brain(model, classifier=classifier, cloud_reasoning_enabled=False)

    await brain.respond("explain photosynthesis", "owner-private")

    assert model.complete_roles == ["responder"]
    assert classifier.call_count == 0


@pytest.mark.asyncio
async def test_missing_classifier_forces_local() -> None:
    model = RecordingModelPort()
    brain = _brain(model, classifier=None)

    await brain.respond("explain photosynthesis", "owner-private")

    assert model.complete_roles == ["responder"]


@pytest.mark.asyncio
async def test_general_stream_uses_cloud_responder() -> None:
    model = RecordingModelPort()
    brain = _brain(model, classifier=SpyClassifier("general"))

    chunks = [chunk async for chunk in brain.respond_stream("explain gravity", "owner-private")]

    assert chunks == ["chunk"]
    assert model.stream_roles == ["responder_cloud"]


@pytest.mark.asyncio
async def test_classifier_raise_fail_closed_for_respond_and_stream() -> None:
    model = RecordingModelPort()
    brain = _brain(model, classifier=SpyClassifier(raises=True))

    await brain.respond("explain gravity", "owner-private")
    chunks = [chunk async for chunk in brain.respond_stream("explain gravity", "owner-private")]

    assert chunks == ["chunk"]
    assert model.complete_roles == ["responder"]
    assert model.stream_roles == ["responder"]


@pytest.mark.asyncio
async def test_tool_path_still_uses_local_responder_for_arg_decode() -> None:
    model = RecordingModelPort()
    registry = _registry()
    registry.register(
        ModuleManifest(
            name="time",
            version="0.1.0",
            description="Time utilities.",
            data_scope=DataScope.SHARED,
            permissions=Permissions(owner=True, guest=True),
            tools=[
                ToolSpec(
                    name="get_current_time",
                    description="Get the current date and time in a timezone.",
                    args_schema=TimeArgs,
                    return_schema=TimeResult,
                    callable_ref=fake_time,
                    action_risk=ActionRisk.NO_DATA,
                )
            ],
        )
    )
    brain = _brain(
        model,
        classifier=SpyClassifier("general"),
        decision=RouteDecision(
            path="deterministic",
            candidate_tools=["time.get_current_time"],
            confidence=1.0,
        ),
        registry=registry,
    )

    response = await brain.respond("what time is it", "owner-private")

    assert response.tool_used == "time.get_current_time"
    assert model.complete_roles == ["responder"]
    assert model.response_schema_seen is not None
