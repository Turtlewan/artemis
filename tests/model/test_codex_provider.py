from __future__ import annotations

import json
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
    reap_stale_codex,
)
from artemis.model.errors import ProviderUnavailableError, QuotaExhaustedError
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

    assert result == '{"answer":"ok"}'
    assert captured_schema is not None
    assert captured_schema["additionalProperties"] is False


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
