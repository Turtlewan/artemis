"""OpenAI-compatible ModelPort and EmbeddingModel adapters.

Resolves per-role endpoints from the M0-a ``roles.toml`` config.
Constrained decoding is handled server-side via ``response_format``
(no Outlines dependency in the client).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx

from artemis.config import get_settings
from artemis.ports.model import ModelResponse
from artemis.ports.types import Message, Usage, Vector


class OpenAIModelPort:
    """ModelPort adapter for OpenAI-compatible endpoints.

    Resolves per-role base URL and model ID from the ``roles.toml`` config.
    Raises ``NotImplementedError`` for ``claude-cli`` adapter roles.
    """

    def __init__(self, settings: Any | None = None) -> None:
        self._settings = settings or get_settings()
        self._client = httpx.AsyncClient(base_url="http://127.0.0.1", timeout=60.0)

    def _role_config(self, role: str) -> tuple[str, str]:
        """Resolve (base_url, model_id) for a logical role."""
        if role not in self._settings.roles:
            raise ValueError(f"Unknown role: {role}")
        role_cfg = self._settings.roles[role]
        if role_cfg.adapter == "claude-cli":
            raise NotImplementedError(f"claude-cli adapter not implemented in M1: {role}")
        return role_cfg.endpoint, role_cfg.model_id

    async def complete(
        self,
        *,
        role: str,
        messages: Sequence[Message],
        response_schema: dict[str, object] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        base_url, model_id = self._role_config(role)
        body: dict[str, object] = {
            "model": model_id,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
        }
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if response_schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "response",
                    "schema": response_schema,
                    "strict": True,
                },
            }

        resp = await self._client.post(
            f"{base_url}/chat/completions",
            json=body,
        )
        resp.raise_for_status()
        data = resp.json()

        choice = data["choices"][0]
        usage_data = data.get("usage", {})
        return ModelResponse(
            text=choice["message"]["content"],
            finish_reason=choice.get("finish_reason", "stop"),
            usage=Usage(
                prompt_tokens=usage_data.get("prompt_tokens", 0),
                completion_tokens=usage_data.get("completion_tokens", 0),
                total_tokens=usage_data.get("total_tokens", 0),
            ),
            origin="local",
            model_id=model_id,
        )

    def complete_stream(
        self,
        *,
        role: str,
        messages: Sequence[Message],
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        """Stream response tokens from the model."""

        async def _stream() -> AsyncIterator[str]:
            base_url, model_id = self._role_config(role)
            body: dict[str, object] = {
                "model": model_id,
                "messages": [{"role": m.role, "content": m.content} for m in messages],
                "temperature": temperature,
                "stream": True,
            }

            async with httpx.AsyncClient(base_url="http://127.0.0.1", timeout=120.0) as client:
                async with client.stream(
                    "POST", f"{base_url}/chat/completions", json=body
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        payload = line[6:].strip()
                        if payload == "[DONE]":
                            break
                        try:
                            chunk = json.loads(payload)
                            delta = chunk["choices"][0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                yield content
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue

        return _stream()

    async def embed(self, role: str, texts: Sequence[str]) -> list[Vector]:
        base_url, _model_id = self._role_config(role)
        body: dict[str, object] = {
            "input": list(texts),
            "model": "text-embedding-ada-002",  # generic; overridden by the server
        }

        resp = await self._client.post(
            f"{base_url}/embeddings",
            json=body,
        )
        resp.raise_for_status()
        data = resp.json()

        # Sort by index to preserve order
        sorted_data = sorted(data["data"], key=lambda x: x["index"])
        return [item["embedding"] for item in sorted_data]


class OpenAIEmbeddingModel:
    """EmbeddingModel adapter for OpenAI-compatible endpoints.

    Resolves per-role base URL from the ``roles.toml`` config.
    ``embed_query`` applies the Qwen3-Embedding instruction prefix.
    ``dimension`` is read from ``Settings.embedding_dimension`` (stable value).
    """

    def __init__(self, settings: Any | None = None) -> None:
        self._settings = settings or get_settings()
        self._client = httpx.AsyncClient(base_url="http://127.0.0.1", timeout=30.0)

    @property
    def dimension(self) -> int:
        return self._settings.embedding_dimension

    async def embed_documents(self, texts: Sequence[str]) -> list[Vector]:
        """Embed texts — NO instruction prefix (stored/indexed text)."""
        return await self._embed(texts, use_prefix=False)

    async def embed_query(self, query: str) -> Vector:
        """Embed a query — applies the Qwen3-Embedding instruction prefix."""
        results = await self._embed([query], use_prefix=True)
        return results[0]

    async def _embed(self, texts: Sequence[str], use_prefix: bool) -> list[Vector]:
        role_cfg = self._settings.roles.get("embedder")
        if not role_cfg:
            raise ValueError("No 'embedder' role configured")

        if use_prefix:
            inputs = [
                f"Instruct: Given a search query, retrieve relevant passages\nQuery:{t}"
                for t in texts
            ]
        else:
            inputs = list(texts)

        body: dict[str, object] = {
            "input": inputs,
            "model": role_cfg.model_id,
        }

        resp = await self._client.post(
            f"{role_cfg.endpoint}/embeddings",
            json=body,
        )
        resp.raise_for_status()
        data = resp.json()

        sorted_data = sorted(data["data"], key=lambda x: x["index"])
        return [item["embedding"] for item in sorted_data]
