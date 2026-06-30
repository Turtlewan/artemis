"""Ollama local chat API-backed raw model provider."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

import httpx

from artemis.model.errors import ProviderUnavailableError, QuotaExhaustedError
from artemis.model.schema_norm import to_ollama_schema
from artemis.types import Message


class OllamaProvider:
    def __init__(
        self,
        *,
        base_url: str = "http://localhost:11434",
        model_default: str = "qwen3:4b",
        timeout: float = 120.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model_default = model_default
        self._timeout = timeout
        self._client = client

    async def generate(
        self,
        *,
        messages: Sequence[Message],
        model: str,
        schema: dict | None,  # type: ignore[type-arg]
    ) -> str:
        body: dict[str, object] = {
            "model": model or self._model_default,
            "stream": False,
            "messages": [
                {"role": message.role, "content": message.content} for message in messages
            ],
        }
        if schema is not None:
            body["format"] = to_ollama_schema(cast(dict[str, Any], schema))

        try:
            response = await self._post(body)
            response.raise_for_status()
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise ProviderUnavailableError("ollama", str(exc)) from exc
        except httpx.HTTPStatusError as exc:
            detail = str(exc)
            if exc.response.status_code == 429:
                raise QuotaExhaustedError("ollama", detail) from exc
            raise ProviderUnavailableError("ollama", detail) from exc
        return _extract_content(response.json())

    async def _post(self, body: dict[str, object]) -> httpx.Response:
        url = f"{self._base_url}/api/chat"
        if self._client is not None:
            return await self._client.post(url, json=body, timeout=self._timeout)
        async with httpx.AsyncClient() as client:
            return await client.post(url, json=body, timeout=self._timeout)


def _extract_content(payload: object) -> str:
    if not isinstance(payload, dict):
        raise ProviderUnavailableError("ollama", "response payload was not an object")
    message = payload.get("message")
    if not isinstance(message, dict):
        raise ProviderUnavailableError("ollama", "response missing message object")
    content = message.get("content")
    if not isinstance(content, str):
        raise ProviderUnavailableError("ollama", "response missing message content")
    return content
