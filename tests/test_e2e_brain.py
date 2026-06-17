"""Milestone end-to-end brain acceptance test (M1-d).

Proves the full M1 pipeline with deterministic fakes:
  manifest → registry → router → dispatch → response

The real ``time_tool.manifest()`` and callable are exercised through
the real ``Brain`` with ``FakeEmbedder`` + ``FakeModelPort``.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Sequence
from datetime import datetime

import pytest

from artemis.brain import Brain
from artemis.ports.model import ModelResponse
from artemis.ports.types import Message, Usage, Vector
from artemis.registry import ToolRegistry
from artemis.router import SemanticRouter
from artemis.tools import time_tool

# ── Fakes (same pattern as test_router_brain.py) ─────────────────────────────


class FakeEmbedder:
    """Deterministic constant-unit-vector embedder."""

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
    """Fake ModelPort — returns schema-compliant JSON for the time tool."""

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
            # Return JSON valid for TimeArgs (the time tool's args_schema)
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

        return _gen()

    async def embed(self, role: str, texts: Sequence[str]) -> list[Vector]:
        return [[0.0] * 16 for _ in texts]


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def brain_with_time() -> Brain:
    """Build a real Brain pipeline with the real time tool registered."""
    embedder = FakeEmbedder()
    registry = ToolRegistry(embedder)
    registry.register(time_tool.manifest())
    router = SemanticRouter(registry, embedder)
    return Brain(router, registry, FakeModelPort())


# ── End-to-end tests ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_e2e_time_tool_path(brain_with_time: Brain) -> None:
    """A time query fires the real get_current_time and returns a rendered result."""
    response = await brain_with_time.respond("what time is it", "owner-private")
    assert response.tool_used == "time.get_current_time"
    assert response.escalated is False
    assert re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", response.text)
    match = re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", response.text)
    assert match is not None
    datetime.fromisoformat(match.group())  # does not raise


@pytest.mark.asyncio
async def test_e2e_escalation_stub() -> None:
    """A nonsense query with no tools → escalation stub."""
    embedder = FakeEmbedder()
    registry = ToolRegistry(embedder)
    # No tools registered — empty registry
    router = SemanticRouter(registry, embedder)
    brain = Brain(router, registry, FakeModelPort())
    response = await brain.respond("xyzzy nonsense token", "owner-private")
    assert response.text == "ESCALATION_NOT_AVAILABLE"
    assert response.escalated is True
