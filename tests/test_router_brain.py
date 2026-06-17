"""Tests for the semantic Router and Brain reactive loop (M1-b).

All tests run against deterministic fakes — no network or model needed.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Sequence

import pytest
from pydantic import BaseModel

from artemis.brain import Brain
from artemis.manifest import ActionRisk, DataScope, ModuleManifest, Permissions, ToolSpec
from artemis.ports.model import ModelResponse
from artemis.ports.types import Message, Usage, Vector
from artemis.registry import ToolRegistry
from artemis.router import SemanticRouter

# ── Fakes ─────────────────────────────────────────────────────────────────


class FakeEmbedder:
    """Deterministic constant-unit-vector embedder.

    Every text gets the same unit vector ``[1.0, 0.0, …]``, so any
    query matches any registered tool with perfect cosine = 1.0.
    Negative tests (escalation) use an empty registry instead.
    """

    DIMENSION = 4

    @property
    def dimension(self) -> int:
        return self.DIMENSION

    async def embed_documents(self, texts: Sequence[str]) -> list[Vector]:
        return [self._unit() for _ in texts]

    async def embed_query(self, query: str) -> Vector:
        return self._unit()

    @staticmethod
    def _unit() -> Vector:
        return [1.0, 0.0, 0.0, 0.0]


class FakeModelPort:
    """Fake ModelPort for testing — returns schema-compliant JSON."""

    async def complete(
        self,
        *,
        role: str,
        messages: Sequence[Message],
        response_schema: dict[str, object] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        if response_schema:
            return ModelResponse(
                text='{"tz": null}',
                finish_reason="stop",
                usage=Usage(10, 5, 15),
                origin="local",
                model_id="fake",
            )
        return ModelResponse(
            text="I am a fake model.",
            finish_reason="stop",
            usage=Usage(10, 5, 15),
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
        async def _gen() -> AsyncIterator[str]:
            yield "fake "
            yield "streamed "
            yield "response"

        return _gen()

    async def embed(self, role: str, texts: Sequence[str]) -> list[Vector]:
        return [[0.0] * 16 for _ in texts]


# ── Tool stubs ────────────────────────────────────────────────────────────


class TimeArgs(BaseModel):
    tz: str | None = None


class TimeResult(BaseModel):
    iso: str
    tz: str


async def fake_time(args: TimeArgs) -> TimeResult:
    return TimeResult(iso="2026-06-17T12:00:00", tz=args.tz or "UTC")


class FailingArgs(BaseModel):
    x: str


class FailingResult(BaseModel):
    ok: bool


async def fake_failing(args: FailingArgs) -> FailingResult:
    msg = "intentional tool failure"
    raise RuntimeError(msg)


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def registry_with_time() -> ToolRegistry:
    embedder = FakeEmbedder()
    reg = ToolRegistry(embedder)
    manifest = ModuleManifest(
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
    reg.register(manifest)
    return reg


@pytest.fixture
def router(registry_with_time: ToolRegistry) -> SemanticRouter:
    return SemanticRouter(registry_with_time, FakeEmbedder())


@pytest.fixture
def brain(router: SemanticRouter, registry_with_time: ToolRegistry) -> Brain:
    return Brain(router, registry_with_time, FakeModelPort())


# ── Router tests ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_router_returns_time_tool(router: SemanticRouter) -> None:
    """A time query matches the time tool with local/deterministic path."""
    decision = await router.route("what time is it", "owner-private")
    assert decision.path in {"deterministic", "local"}
    assert "time.get_current_time" in decision.candidate_tools
    assert decision.confidence > 0.0


@pytest.mark.asyncio
async def test_router_no_match_escalates() -> None:
    """Router returns escalate when no tools are registered."""
    embedder = FakeEmbedder()
    reg = ToolRegistry(embedder)
    empty_router = SemanticRouter(reg, embedder)
    decision = await empty_router.route("anything", "owner-private")
    assert decision.path == "escalate"
    assert decision.confidence == 0.0


# ── Brain tests ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_brain_tool_path(brain: Brain) -> None:
    """A time query fires the time tool, returns rendered result."""
    response = await brain.respond("what time is it", "owner-private")
    assert response.tool_used == "time.get_current_time"
    assert response.escalated is False
    # The rendered result includes an ISO timestamp
    assert re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", response.text)


@pytest.mark.asyncio
async def test_brain_escalation_stub() -> None:
    """A request with no registered tools escalates."""
    embedder = FakeEmbedder()
    reg = ToolRegistry(embedder)
    # No tools registered — empty registry
    rtr = SemanticRouter(reg, embedder)
    b = Brain(rtr, reg, FakeModelPort())
    response = await b.respond("anything", "owner-private")
    assert response.text == "ESCALATION_NOT_AVAILABLE"
    assert response.escalated is True


@pytest.mark.asyncio
async def test_brain_degrade_on_tool_error() -> None:
    """A callable that raises degrades to TOOL_ERROR."""
    embedder = FakeEmbedder()
    reg = ToolRegistry(embedder)
    fail_manifest = ModuleManifest(
        name="fail",
        version="0.1.0",
        description="Fail tool — always fails on purpose.",
        data_scope=DataScope.OWNER_PRIVATE,
        tools=[
            ToolSpec(
                name="fail_tool",
                description="Fail tool — always fails on purpose.",
                args_schema=FailingArgs,
                return_schema=FailingResult,
                callable_ref=fake_failing,
                action_risk=ActionRisk.NO_DATA,
            )
        ],
    )
    reg.register(fail_manifest)
    rtr = SemanticRouter(reg, embedder)
    brain = Brain(rtr, reg, FakeModelPort())
    # "fail" appears in both the query and the tool description, so the
    # FakeEmbedder's bag-of-words hash will match, and the tool dispatches.
    response = await brain.respond("fail on purpose", "owner-private")
    assert response.text == "TOOL_ERROR"


@pytest.mark.asyncio
async def test_brain_stream(brain: Brain) -> None:
    """respond_stream yields at least one segment with the time."""
    segments: list[str] = []
    async for chunk in brain.respond_stream("what time is it", "owner-private"):
        segments.append(chunk)
    assert len(segments) >= 1
    combined = "".join(segments)
    assert re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", combined)


@pytest.mark.asyncio
async def test_brain_pre_route(brain: Brain) -> None:
    """pre_route returns the top candidate id for a matching query."""
    result = await brain.pre_route("what time is it", "owner-private")
    assert result == "time.get_current_time"


@pytest.mark.asyncio
async def test_brain_pre_route_no_match() -> None:
    """pre_route returns None when no tools registered."""
    embedder = FakeEmbedder()
    reg = ToolRegistry(embedder)
    rtr = SemanticRouter(reg, embedder)
    b = Brain(rtr, reg, FakeModelPort())
    result = await b.pre_route("anything", "owner-private")
    assert result is None
