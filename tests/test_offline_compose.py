"""compose_brain override-seam coverage — runs the brain fully offline."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any

from artemis.config import Settings
from artemis.gateway import Gateway, compose_brain
from artemis.ports.model import ModelResponse
from artemis.ports.types import Usage, Vector


class _FakeEmbedder:
    def __init__(self, dim: int = 8) -> None:
        self._dim = dim

    @property
    def dimension(self) -> int:
        return self._dim

    async def embed_documents(self, texts: Sequence[str]) -> list[Vector]:
        return [[0.1] * self._dim for _ in texts]

    async def embed_query(self, query: str) -> Vector:
        return [0.1] * self._dim


class _FakeModel:
    async def complete(self, **kwargs: Any) -> ModelResponse:
        return ModelResponse(
            text="{}",
            finish_reason="stop",
            usage=Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
            origin="local",
            model_id="fake",
        )

    def complete_stream(self, **kwargs: Any) -> AsyncIterator[str]:
        async def _gen() -> AsyncIterator[str]:
            yield "fake-stream"

        return _gen()

    async def embed(self, role: str, texts: Sequence[str]) -> list[Vector]:
        return [[0.1] * 8 for _ in texts]


def test_compose_brain_accepts_overrides() -> None:
    brain = compose_brain(Settings(), embedder=_FakeEmbedder(), model=_FakeModel())
    assert brain is not None


async def test_offline_brain_handles_request_without_network() -> None:
    gateway = Gateway(
        compose_brain(Settings(), embedder=_FakeEmbedder(), model=_FakeModel())
    )
    resp = await gateway.handle_text("what time is it?")
    # Returns *something* (tool result / responder / escalation stub) without raising.
    assert resp.text
