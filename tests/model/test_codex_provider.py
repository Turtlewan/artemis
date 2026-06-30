from __future__ import annotations

import json
from pathlib import Path

import pytest

import artemis.model.cli_support as cli_support
from artemis.model.codex_provider import CodexProvider, CodexProviderError
from artemis.model.errors import QuotaExhaustedError
from artemis.types import Message


def test_codex_provider_resolves_binary_and_builds_expected_argv() -> None:
    provider = CodexProvider(binary="definitely-not-a-real-codex-binary")

    argv = provider._build_argv(
        model="gpt-test",
        output_path=Path("out.txt"),
        schema_path=Path("schema.json"),
    )

    assert argv == [
        "definitely-not-a-real-codex-binary",
        "exec",
        "-m",
        "gpt-test",
        "--sandbox",
        "read-only",
        "--ephemeral",
        "--skip-git-repo-check",
        "--color",
        "never",
        "-o",
        "out.txt",
        "--output-schema",
        "schema.json",
        "-",
    ]


def test_quota_signal_detection() -> None:
    assert cli_support.is_quota_signal("Claude usage limit reached")
    assert not cli_support.is_quota_signal("file not found")


@pytest.mark.asyncio
async def test_codex_provider_detects_quota(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run_cli(argv: list[str], *, stdin: bytes) -> tuple[int, bytes, bytes]:
        del argv, stdin
        return (1, b"", b"weekly quota exceeded")

    monkeypatch.setattr(cli_support, "run_cli", fake_run_cli)
    provider = CodexProvider(binary="codex-test")

    with pytest.raises(QuotaExhaustedError):
        await provider.generate(
            messages=[Message(role="user", content="hello")], model="", schema=None
        )


@pytest.mark.asyncio
async def test_codex_provider_keeps_non_quota_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run_cli(argv: list[str], *, stdin: bytes) -> tuple[int, bytes, bytes]:
        del argv, stdin
        return (2, b"", b"syntax failed")

    monkeypatch.setattr(cli_support, "run_cli", fake_run_cli)
    provider = CodexProvider(binary="codex-test")

    with pytest.raises(CodexProviderError):
        await provider.generate(
            messages=[Message(role="user", content="hello")], model="", schema=None
        )


@pytest.mark.asyncio
async def test_codex_provider_strictifies_schema_internally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_schema: dict | None = None  # type: ignore[type-arg]

    async def fake_run_cli(argv: list[str], *, stdin: bytes) -> tuple[int, bytes, bytes]:
        nonlocal captured_schema
        del stdin
        output_path = Path(argv[argv.index("-o") + 1])
        schema_path = Path(argv[argv.index("--output-schema") + 1])
        captured_schema = json.loads(schema_path.read_text(encoding="utf-8"))
        output_path.write_text('{"answer":"ok"}', encoding="utf-8")
        return (0, b"", b"")

    monkeypatch.setattr(cli_support, "run_cli", fake_run_cli)
    provider = CodexProvider(binary="codex-test")

    result = await provider.generate(
        messages=[Message(role="user", content="hello")],
        model="gpt-test",
        schema={
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
        },
    )

    assert result == '{"answer":"ok"}'
    assert captured_schema is not None
    assert captured_schema["additionalProperties"] is False
