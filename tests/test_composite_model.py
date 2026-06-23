"""Composite model routing and fallback coverage."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from pathlib import Path

import pytest

from artemis.adapters.composite_model import CompositeModelPort
from artemis.config import Settings
from artemis.ports.model import ModelPort, ModelResponse
from artemis.ports.types import Message, Usage, Vector


class _FakeModel:
    def __init__(self, *, name: str, raises: bool = False) -> None:
        self.name = name
        self.raises = raises
        self.complete_roles: list[str] = []
        self.stream_roles: list[str] = []
        self.embed_roles: list[str] = []

    async def complete(
        self,
        *,
        role: str,
        messages: Sequence[Message],
        response_schema: dict[str, object] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        del messages, response_schema, temperature, max_tokens
        self.complete_roles.append(role)
        if self.raises:
            raise RuntimeError("fake failure")
        return ModelResponse(
            text=f"{self.name}:{role}",
            finish_reason="stop",
            usage=Usage(0, 0, 0),
            origin=self.name,
            model_id=f"{self.name}-model",
        )

    def complete_stream(
        self,
        *,
        role: str,
        messages: Sequence[Message],
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        del messages, temperature

        async def _stream() -> AsyncIterator[str]:
            self.stream_roles.append(role)
            yield f"{self.name}:{role}:stream"

        return _stream()

    async def embed(self, role: str, texts: Sequence[str]) -> list[Vector]:
        self.embed_roles.append(role)
        return [[float(index)] for index, _text in enumerate(texts)]


def _settings(tmp_path: Path) -> Settings:
    roles = tmp_path / "roles.toml"
    roles.write_text(
        """
[responder_cloud]
endpoint = "codex"
model_id = "gpt-5.4"
adapter = "codex"

[responder]
endpoint = "http://127.0.0.1:8040/v1"
model_id = "Qwen3-4B-Instruct-2507"
adapter = "openai"

[sensitive_reasoner]
endpoint = "http://127.0.0.1:8040/v1"
model_id = "Qwen3.6-27B"
adapter = "openai"

[embedder]
endpoint = "http://127.0.0.1:8040/v1"
model_id = "Qwen3-Embedding-0.6B"
adapter = "openai"
""",
        encoding="utf-8",
    )
    return Settings(roles_file=roles)


@pytest.mark.asyncio
async def test_complete_routes_codex_role_to_codex(tmp_path: Path) -> None:
    local = _FakeModel(name="local")
    codex = _FakeModel(name="cloud")
    port = CompositeModelPort(_settings(tmp_path), local=local, codex=codex)

    resp = await port.complete(
        role="responder_cloud", messages=[Message(role="user", content="hi")]
    )

    assert resp.text == "cloud:responder_cloud"
    assert codex.complete_roles == ["responder_cloud"]
    assert local.complete_roles == []


@pytest.mark.asyncio
async def test_complete_routes_local_role_to_local(tmp_path: Path) -> None:
    local = _FakeModel(name="local")
    codex = _FakeModel(name="cloud")
    port = CompositeModelPort(_settings(tmp_path), local=local, codex=codex)

    resp = await port.complete(role="responder", messages=[Message(role="user", content="hi")])

    assert resp.text == "local:responder"
    assert local.complete_roles == ["responder"]
    assert codex.complete_roles == []


@pytest.mark.asyncio
async def test_complete_falls_back_to_sensitive_reasoner_on_codex_failure(
    tmp_path: Path,
) -> None:
    local = _FakeModel(name="local")
    codex = _FakeModel(name="cloud", raises=True)
    port = CompositeModelPort(_settings(tmp_path), local=local, codex=codex)

    resp = await port.complete(
        role="responder_cloud", messages=[Message(role="user", content="hi")]
    )

    assert resp.text == "local:sensitive_reasoner"
    assert codex.complete_roles == ["responder_cloud"]
    assert local.complete_roles == ["sensitive_reasoner"]


@pytest.mark.asyncio
async def test_complete_stream_for_codex_role_uses_local_fallback_on_codex_failure(
    tmp_path: Path,
) -> None:
    local = _FakeModel(name="local")
    codex = _FakeModel(name="cloud", raises=True)
    port = CompositeModelPort(_settings(tmp_path), local=local, codex=codex)

    chunks = [
        chunk
        async for chunk in port.complete_stream(
            role="responder_cloud", messages=[Message(role="user", content="hi")]
        )
    ]

    assert chunks == ["local:sensitive_reasoner"]
    assert codex.complete_roles == ["responder_cloud"]
    assert local.complete_roles == ["sensitive_reasoner"]
    assert local.stream_roles == []


@pytest.mark.asyncio
async def test_embed_always_delegates_to_local(tmp_path: Path) -> None:
    local = _FakeModel(name="local")
    codex = _FakeModel(name="cloud")
    port = CompositeModelPort(_settings(tmp_path), local=local, codex=codex)

    vectors = await port.embed("embedder", ["a", "b"])

    assert vectors == [[0.0], [1.0]]
    assert local.embed_roles == ["embedder"]
    assert codex.embed_roles == []


def test_composite_model_port_conforms_to_protocol(tmp_path: Path) -> None:
    fake = _FakeModel(name="fake")
    assert isinstance(CompositeModelPort(_settings(tmp_path), local=fake, codex=fake), ModelPort)
