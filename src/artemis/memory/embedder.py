"""Embedding adapters for memory retrieval."""

from __future__ import annotations

from collections.abc import Sequence

import httpx

from artemis.errors import ProviderUnavailableError


class OllamaEmbedder:
    """Ollama native embed API-backed embedding adapter."""

    def __init__(
        self,
        *,
        base_url: str = "http://localhost:11434",
        model: str = "qwen3-embedding:0.6b",
        timeout: float = 60.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout
        self._client = client

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        body: dict[str, object] = {"model": self._model, "input": list(texts)}
        try:
            response = await self._post(body)
            response.raise_for_status()
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise ProviderUnavailableError("ollama_embed", str(exc)) from exc
        except httpx.HTTPStatusError as exc:
            raise ProviderUnavailableError("ollama_embed", str(exc)) from exc
        return _extract_embeddings(response.json())

    async def _post(self, body: dict[str, object]) -> httpx.Response:
        url = f"{self._base_url}/api/embed"
        if self._client is not None:
            return await self._client.post(url, json=body, timeout=self._timeout)
        async with httpx.AsyncClient() as client:
            return await client.post(url, json=body, timeout=self._timeout)


def _extract_embeddings(payload: object) -> list[list[float]]:
    if not isinstance(payload, dict):
        raise ProviderUnavailableError("ollama_embed", "response payload was not an object")
    embeddings = payload.get("embeddings")
    if not isinstance(embeddings, list):
        raise ProviderUnavailableError("ollama_embed", "response missing embeddings list")

    parsed: list[list[float]] = []
    for embedding in embeddings:
        if not isinstance(embedding, list):
            raise ProviderUnavailableError("ollama_embed", "embedding was not a list")
        vector: list[float] = []
        for value in embedding:
            if not isinstance(value, int | float):
                raise ProviderUnavailableError("ollama_embed", "embedding value was not numeric")
            vector.append(float(value))
        parsed.append(vector)
    return parsed
