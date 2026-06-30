from __future__ import annotations

import httpx
import pytest

from artemis.model.errors import ProviderUnavailableError
from artemis.model.ollama_provider import OllamaProvider
from artemis.types import Message


class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self._payload


@pytest.mark.asyncio
async def test_ollama_provider_returns_message_content_with_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_post(
        self: httpx.AsyncClient,
        url: str,
        *,
        json: dict[str, object],
        timeout: float,
    ) -> FakeResponse:
        del self, timeout
        captured["url"] = url
        captured["json"] = json
        return FakeResponse({"message": {"content": '{"answer":"ok"}'}})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    provider = OllamaProvider(base_url="http://localhost:11434")

    result = await provider.generate(
        messages=[Message(role="user", content="answer")],
        model="qwen-test",
        schema=_schema(),
    )

    assert result == '{"answer":"ok"}'
    assert captured["url"] == "http://localhost:11434/api/chat"
    body = captured["json"]
    assert isinstance(body, dict)
    assert body["model"] == "qwen-test"
    assert "format" in body


@pytest.mark.asyncio
async def test_ollama_connect_error_maps_to_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_post(
        self: httpx.AsyncClient,
        url: str,
        *,
        json: dict[str, object],
        timeout: float,
    ) -> FakeResponse:
        del self, url, json, timeout
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    provider = OllamaProvider()

    with pytest.raises(ProviderUnavailableError):
        await provider.generate(
            messages=[Message(role="user", content="hi")], model="", schema=None
        )


def _schema() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
    }
