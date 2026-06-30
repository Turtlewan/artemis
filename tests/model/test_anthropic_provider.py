from __future__ import annotations

import json
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import anthropic
import httpx
import pytest
from anthropic import AsyncAnthropic

from artemis.model.anthropic_provider import AnthropicAPIProvider
from artemis.model.errors import ProviderUnavailableError, QuotaExhaustedError
from artemis.types import Message


@pytest.mark.asyncio
async def test_anthropic_provider_returns_tool_input_json() -> None:
    tool_block = SimpleNamespace(type="tool_use", name="emit", input={"answer": "ok"})
    fake_client = SimpleNamespace(
        messages=SimpleNamespace(
            create=AsyncMock(return_value=SimpleNamespace(content=[tool_block]))
        )
    )
    provider = AnthropicAPIProvider(client=cast(AsyncAnthropic, fake_client))

    result = await provider.generate(
        messages=[
            Message(role="system", content="Be exact."),
            Message(role="user", content="answer"),
        ],
        model="claude-test",
        schema=_schema(),
    )

    assert json.loads(result) == {"answer": "ok"}
    fake_client.messages.create.assert_awaited_once()
    kwargs = fake_client.messages.create.await_args.kwargs
    assert kwargs["system"] == "Be exact."
    assert kwargs["messages"] == [{"role": "user", "content": "answer"}]
    assert kwargs["tools"][0]["name"] == "emit"
    assert kwargs["tool_choice"] == {"type": "tool", "name": "emit"}


@pytest.mark.asyncio
async def test_anthropic_rate_limit_maps_to_quota() -> None:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(429, request=request)
    fake_client = SimpleNamespace(
        messages=SimpleNamespace(
            create=AsyncMock(
                side_effect=anthropic.RateLimitError(
                    "rate limited",
                    response=response,
                    body=None,
                )
            )
        )
    )
    provider = AnthropicAPIProvider(client=cast(AsyncAnthropic, fake_client))

    with pytest.raises(QuotaExhaustedError):
        await provider.generate(
            messages=[Message(role="user", content="hi")], model="", schema=None
        )


@pytest.mark.asyncio
async def test_anthropic_missing_key_maps_to_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    provider = AnthropicAPIProvider()

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
