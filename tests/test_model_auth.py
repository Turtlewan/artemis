"""Bearer-auth header coverage for the OpenAI-compatible adapters."""

from __future__ import annotations

import httpx
import pytest

from artemis.adapters.model_adapters import OpenAIModelPort, _auth_headers
from artemis.config import Settings
from artemis.ports.types import Message


def test_auth_headers_present_when_key_set() -> None:
    assert _auth_headers(Settings(model_api_key="sk-test")) == {"Authorization": "Bearer sk-test"}


def test_auth_headers_absent_when_no_key() -> None:
    assert _auth_headers(Settings()) == {}


def test_model_port_client_carries_bearer() -> None:
    port = OpenAIModelPort(Settings(model_api_key="sk-test"))
    assert port._client.headers["authorization"] == "Bearer sk-test"


@pytest.mark.asyncio
async def test_complete_sends_bearer_on_wire() -> None:
    captured: dict[str, str | None] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    port = OpenAIModelPort(Settings(model_api_key="sk-test"))
    # Keep the adapter-built auth headers; swap only the transport.
    port._client = httpx.AsyncClient(
        base_url="http://127.0.0.1",
        transport=httpx.MockTransport(handler),
        headers=port._client.headers,
    )
    resp = await port.complete(role="responder", messages=[Message(role="user", content="hi")])
    assert resp.text == "ok"
    assert captured["auth"] == "Bearer sk-test"
