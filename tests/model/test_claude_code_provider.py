from __future__ import annotations

import pytest

import artemis.model.cli_support as cli_support
from artemis.model.claude_code_provider import ClaudeCodeProvider, _extract_result
from artemis.model.errors import QuotaExhaustedError
from artemis.types import Message


def test_extract_result_reads_json_envelope() -> None:
    assert _extract_result('{"result":"hi"}') == "hi"


def test_extract_result_falls_back_to_stripped_stdout() -> None:
    assert _extract_result("  not json\n") == "not json"


@pytest.mark.asyncio
async def test_claude_provider_argv_and_json_output(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def fake_run_cli(argv: list[str], *, stdin: bytes) -> tuple[int, bytes, bytes]:
        captured["argv"] = argv
        captured["stdin"] = stdin
        return (0, b'{"result":"hi"}', b"")

    monkeypatch.setattr(cli_support, "run_cli", fake_run_cli)
    provider = ClaudeCodeProvider(binary="claude-test", model_default="sonnet")

    result = await provider.generate(
        messages=[Message(role="user", content="hello")],
        model="opus",
        schema={"type": "object"},
    )

    argv = captured["argv"]
    assert isinstance(argv, list)
    assert result == "hi"
    assert "-p" in argv
    assert "--output-format" in argv
    assert "json" in argv
    assert captured["stdin"] == b""


@pytest.mark.asyncio
async def test_claude_provider_detects_quota(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run_cli(argv: list[str], *, stdin: bytes) -> tuple[int, bytes, bytes]:
        del argv, stdin
        return (1, b"", b"Claude usage limit reached")

    monkeypatch.setattr(cli_support, "run_cli", fake_run_cli)
    provider = ClaudeCodeProvider(binary="claude-test")

    with pytest.raises(QuotaExhaustedError):
        await provider.generate(
            messages=[Message(role="user", content="hello")], model="", schema=None
        )
