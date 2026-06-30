from __future__ import annotations

import json
from typing import cast

import httpx
import pytest

from artemis.memory.embedder import OllamaEmbedder
from artemis.model.errors import ProviderUnavailableError
from artemis.ports.embedding import EmbeddingPort


@pytest.mark.asyncio
async def test_ollama_embedder_posts_batch_and_parses_embeddings() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = cast(dict[str, object], json.loads(request.content))
        return httpx.Response(200, json={"embeddings": [[0.1, 0.2], [0.3, 0.4]]})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        embedder = OllamaEmbedder(
            base_url="http://localhost:11434",
            model="qwen-test",
            client=client,
        )

        result = await embedder.embed(["a", "b"])

    assert result == [[0.1, 0.2], [0.3, 0.4]]
    assert captured["url"] == "http://localhost:11434/api/embed"
    assert captured["body"] == {"model": "qwen-test", "input": ["a", "b"]}


@pytest.mark.asyncio
async def test_ollama_embedder_connect_error_maps_to_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        embedder = OllamaEmbedder(client=client)

        with pytest.raises(ProviderUnavailableError) as exc_info:
            await embedder.embed(["a"])

    assert exc_info.value.provider == "ollama_embed"


def test_ollama_embedder_satisfies_embedding_port() -> None:
    embedder: EmbeddingPort = OllamaEmbedder()

    assert isinstance(embedder, EmbeddingPort)
