from __future__ import annotations

import json
import os
import time
from collections.abc import Mapping
from pathlib import Path

import psutil
import pytest

import artemis.model.cli_support as cli_support
import artemis.model.codex_provider as codex_provider_module
from artemis.model.codex_provider import (
    CODEX_SPAWN_MARKER,
    CodexProvider,
    CodexProviderError,
    Generation,
    reap_stale_codex,
)
from artemis.model.errors import ProviderUnavailableError, QuotaExhaustedError
from artemis.types import Message, Usage


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
        "--json",
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
    async def fake_run_cli(
        argv: list[str],
        *,
        stdin: bytes,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> tuple[int, bytes, bytes]:
        del argv, stdin, env, timeout
        return (1, b"", b"weekly quota exceeded")

    monkeypatch.setattr(cli_support, "run_cli", fake_run_cli)
    provider = CodexProvider(binary="codex-test")

    with pytest.raises(QuotaExhaustedError):
        await provider.generate(
            messages=[Message(role="user", content="hello")], model="", schema=None
        )


@pytest.mark.asyncio
async def test_codex_provider_keeps_non_quota_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run_cli(
        argv: list[str],
        *,
        stdin: bytes,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> tuple[int, bytes, bytes]:
        del argv, stdin, env, timeout
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

    async def fake_run_cli(
        argv: list[str],
        *,
        stdin: bytes,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> tuple[int, bytes, bytes]:
        nonlocal captured_schema
        del stdin, env, timeout
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

    assert result.text == '{"answer":"ok"}'
    assert result.usage.total_tokens == 0
    assert captured_schema is not None
    assert captured_schema["additionalProperties"] is False


@pytest.mark.asyncio
async def test_codex_provider_parses_usage_from_json_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = (
        b'{"id":"0","msg":{"type":"agent_message","text":"hi"}}\n'
        b'{"id":"1","msg":{"type":"token_count","info":{"total_token_usage":'
        b'{"input_tokens":1200,"cached_input_tokens":256,"output_tokens":340,'
        b'"total_tokens":1540}}}}\n'
    )

    async def fake_run_cli(argv, *, stdin, env=None, timeout=None):  # type: ignore[no-untyped-def]
        del stdin, env, timeout
        Path(argv[argv.index("-o") + 1]).write_text("hi", encoding="utf-8")
        return (0, stream, b"")

    monkeypatch.setattr(cli_support, "run_cli", fake_run_cli)
    result = await CodexProvider(binary="codex-test").generate(
        messages=[Message(role="user", content="hello")], model="", schema=None
    )
    assert result.text == "hi"
    assert (result.usage.prompt_tokens, result.usage.completion_tokens) == (1200, 340)
    assert result.usage.total_tokens == 1540


@pytest.mark.asyncio
async def test_codex_provider_usage_falls_back_to_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_run_cli(argv, *, stdin, env=None, timeout=None):  # type: ignore[no-untyped-def]
        del stdin, env, timeout
        Path(argv[argv.index("-o") + 1]).write_text("hi", encoding="utf-8")
        return (0, b'{"id":"0","msg":{"type":"agent_message","text":"hi"}}\n', b"")

    monkeypatch.setattr(cli_support, "run_cli", fake_run_cli)
    result = await CodexProvider(binary="codex-test").generate(
        messages=[Message(role="user", content="hello")], model="", schema=None
    )
    assert result.text == "hi"
    assert result.usage.total_tokens == 0


@pytest.mark.asyncio
async def test_codex_provider_negative_tokens_degrade_to_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = (
        b'{"id":"1","msg":{"type":"token_count","info":{"total_token_usage":'
        b'{"input_tokens":-5,"output_tokens":340}}}}\n'
    )

    async def fake_run_cli(argv, *, stdin, env=None, timeout=None):  # type: ignore[no-untyped-def]
        del stdin, env, timeout
        Path(argv[argv.index("-o") + 1]).write_text("hi", encoding="utf-8")
        return (0, stream, b"")

    monkeypatch.setattr(cli_support, "run_cli", fake_run_cli)
    result = await CodexProvider(binary="codex-test").generate(
        messages=[Message(role="user", content="hello")], model="", schema=None
    )
    assert result.text == "hi"
    assert result.usage == Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0)


@pytest.mark.skipif(
    os.environ.get("ARTEMIS_LIVE_SMOKE") != "1",
    reason=(
        "live smoke (set ARTEMIS_LIVE_SMOKE=1): runs one real codex call to verify the --json "
        "token-event field path -- usage.total_tokens must be > 0"
    ),
)
@pytest.mark.asyncio
async def test_codex_provider_usage_live_smoke() -> None:
    result = await CodexProvider().generate(
        messages=[Message(role="user", content="say OK")], model="gpt-5.5", schema=None
    )
    assert isinstance(result, Generation)
    assert result.usage.total_tokens > 0


@pytest.mark.asyncio
async def test_codex_provider_timeout_maps_to_failover_eligible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_run_cli(
        argv: list[str],
        *,
        stdin: bytes,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> tuple[int, bytes, bytes]:
        del argv, stdin, env, timeout
        raise TimeoutError

    monkeypatch.setattr(cli_support, "run_cli", fake_run_cli)
    provider = CodexProvider(binary="codex-test", timeout=7.0)

    with pytest.raises(ProviderUnavailableError, match="timed out after 7s"):
        await provider.generate(
            messages=[Message(role="user", content="hello")], model="", schema=None
        )


@pytest.mark.asyncio
async def test_codex_provider_passes_marker_env_and_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_run_cli(
        argv: list[str],
        *,
        stdin: bytes,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> tuple[int, bytes, bytes]:
        del stdin
        captured["env"] = env
        captured["timeout"] = timeout
        output_path = Path(argv[argv.index("-o") + 1])
        output_path.write_text("ok", encoding="utf-8")
        return (0, b"", b"")

    monkeypatch.setattr(cli_support, "run_cli", fake_run_cli)
    provider = CodexProvider(binary="codex-test", timeout=123.0)

    await provider.generate(messages=[Message(role="user", content="hello")], model="", schema=None)

    env = captured["env"]
    assert isinstance(env, dict)
    assert env[CODEX_SPAWN_MARKER] == "1"
    assert "PATH" in env or "Path" in env  # inherits the real environment
    assert captured["timeout"] == 123.0


@pytest.mark.asyncio
async def test_codex_provider_reaps_stale_processes_before_spawning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_reap(*, max_age_s: float = 900.0) -> list[int]:
        del max_age_s
        calls.append("reap")
        return []

    async def fake_run_cli(
        argv: list[str],
        *,
        stdin: bytes,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> tuple[int, bytes, bytes]:
        del stdin, env, timeout
        calls.append("run")
        output_path = Path(argv[argv.index("-o") + 1])
        output_path.write_text("ok", encoding="utf-8")
        return (0, b"", b"")

    monkeypatch.setattr(codex_provider_module, "reap_stale_codex", fake_reap)
    monkeypatch.setattr(cli_support, "run_cli", fake_run_cli)
    provider = CodexProvider(binary="codex-test")

    await provider.generate(messages=[Message(role="user", content="hello")], model="", schema=None)

    assert calls == ["reap", "run"]


class _FakeReapProc:
    def __init__(
        self,
        pid: int,
        name: str,
        age_s: float,
        env: dict[str, str] | None,
    ) -> None:
        self.pid = pid
        self.info: dict[str, object] = {"name": name, "create_time": time.time() - age_s}
        self._env = env
        self.killed = False

    def environ(self) -> dict[str, str]:
        if self._env is None:
            raise psutil.AccessDenied(self.pid)
        return self._env

    def kill(self) -> None:
        self.killed = True


def test_reap_stale_codex_kills_only_old_marked_codex(monkeypatch: pytest.MonkeyPatch) -> None:
    marked = {CODEX_SPAWN_MARKER: "1"}
    ours_old = _FakeReapProc(1, "codex.exe", age_s=3600, env=marked)
    ours_fresh = _FakeReapProc(2, "codex.exe", age_s=10, env=marked)
    foreign_old = _FakeReapProc(3, "codex.exe", age_s=3600, env={})
    unreadable_old = _FakeReapProc(4, "codex.exe", age_s=3600, env=None)
    other_tool = _FakeReapProc(5, "python.exe", age_s=3600, env=marked)
    procs = [ours_old, ours_fresh, foreign_old, unreadable_old, other_tool]

    def fake_process_iter(attrs: list[str]) -> list[_FakeReapProc]:
        del attrs
        return procs

    monkeypatch.setattr(psutil, "process_iter", fake_process_iter)

    assert reap_stale_codex() == [1]
    assert [p.killed for p in procs] == [True, False, False, False, False]


def test_reap_stale_codex_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken_process_iter(attrs: list[str]) -> list[_FakeReapProc]:
        del attrs
        raise psutil.Error("scan failed")

    monkeypatch.setattr(psutil, "process_iter", broken_process_iter)

    assert reap_stale_codex() == []
