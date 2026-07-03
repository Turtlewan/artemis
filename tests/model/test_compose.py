from __future__ import annotations

from pathlib import Path

import anthropic
import httpx
import pytest

import artemis.model.cli_support as cli_support
from artemis.model.compose import build_model_router
from artemis.model.router import QuotaAwareRouter
from artemis.types import Message


class FakeOllamaResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {"message": {"content": '{"answer":"ok"}'}}


@pytest.mark.asyncio
async def test_build_model_router_order_and_fallover(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # ClaudeCodeProvider now resolves a clean-context config dir from ~/.claude/.credentials.json;
    # point home at a dummy so this test never touches the real subscription token.
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir(parents=True)
    (claude_dir / ".credentials.json").write_text('{"token":"dummy"}', encoding="utf-8")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    async def fake_run_cli(
        argv: list[str],
        *,
        stdin: bytes,
        env: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> tuple[int, bytes, bytes]:
        del argv, stdin, env, timeout
        return (1, b"", b"quota exceeded")

    async def fake_anthropic_create(self: object, **kwargs: object) -> object:
        del self, kwargs
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        response = httpx.Response(429, request=request)
        raise anthropic.RateLimitError("rate limited", response=response, body=None)

    async def fake_ollama_post(
        self: httpx.AsyncClient,
        url: str,
        *,
        json: dict[str, object],
        timeout: float,
    ) -> FakeOllamaResponse:
        del self, url, json, timeout
        return FakeOllamaResponse()

    monkeypatch.setattr(cli_support, "run_cli", fake_run_cli)
    monkeypatch.setattr(anthropic.resources.messages.AsyncMessages, "create", fake_anthropic_create)
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_ollama_post)

    router = build_model_router(anthropic_api_key="test-key")

    assert isinstance(router, QuotaAwareRouter)
    assert [name for name, _backend in router._backends] == [
        "codex",
        "claude_code",
        "anthropic_api",
        "ollama",
    ]

    result = await router.complete(
        messages=[Message(role="user", content="answer")],
        response_schema=_schema(),
    )

    assert result.model_id == "qwen3:4b"
    assert result.structured == {"answer": "ok"}


def _schema() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
    }
