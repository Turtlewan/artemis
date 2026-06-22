"""Tests for the Codex CLI model adapter."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

import pytest

from artemis.adapters.codex_adapter import CodexModelPort, _render_prompt
from artemis.config import Settings
from artemis.ports.model import ModelPort
from artemis.ports.types import Message


@dataclass
class _Capture:
    args: list[str]
    stdin: bytes
    schema_text: str | None


class _FakeProcess:
    def __init__(
        self,
        args: tuple[str, ...],
        capture: _Capture,
        *,
        returncode: int,
        output_text: str,
        stderr_text: str,
    ) -> None:
        self.returncode = returncode
        self._args = args
        self._capture = capture
        self._output_text = output_text
        self._stderr_text = stderr_text

    async def communicate(self, input: bytes | None = None) -> tuple[bytes, bytes]:
        self._capture.stdin = input or b""
        self._capture.args = list(self._args)
        if "--output-schema" in self._args:
            schema_index = self._args.index("--output-schema") + 1
            self._capture.schema_text = Path(self._args[schema_index]).read_text(encoding="utf-8")
        if self.returncode == 0:
            out_index = self._args.index("-o") + 1
            Path(self._args[out_index]).write_text(self._output_text, encoding="utf-8")
        return b"", self._stderr_text.encode()


def _install_fake_subprocess(
    monkeypatch: pytest.MonkeyPatch,
    *,
    returncode: int = 0,
    output_text: str = "codex answer\n",
    stderr_text: str = "fake stderr secret",
) -> _Capture:
    capture = _Capture(args=[], stdin=b"", schema_text=None)

    async def fake_create_subprocess_exec(
        *args: str,
        stdin: object = None,
        stdout: object = None,
        stderr: object = None,
    ) -> _FakeProcess:
        del stdin, stdout, stderr
        return _FakeProcess(
            args,
            capture,
            returncode=returncode,
            output_text=output_text,
            stderr_text=stderr_text,
        )

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    return capture


def test_render_prompt_flattens_role_tags() -> None:
    prompt = _render_prompt(
        [
            Message(role="system", content="Be precise."),
            Message(role="user", content="What changed?"),
        ]
    )

    assert prompt == "[system]\nBe precise.\n\n[user]\nWhat changed?"


@pytest.mark.asyncio
async def test_complete_returns_cloud_response(monkeypatch: pytest.MonkeyPatch) -> None:
    capture = _install_fake_subprocess(monkeypatch, output_text=" final answer \n")
    settings = Settings(codex_binary="codex-test", codex_model="gpt-5.4")
    port = CodexModelPort(settings)

    resp = await port.complete(role="reasoner", messages=[Message(role="user", content="hi")])

    assert resp.text == "final answer"
    assert resp.origin == "cloud"
    assert resp.model_id == "gpt-5.4"
    assert resp.usage.total_tokens == 0
    assert capture.args[:4] == ["codex-test", "exec", "-m", "gpt-5.4"]
    assert "--sandbox" in capture.args
    assert "read-only" in capture.args
    assert "--ephemeral" in capture.args
    assert capture.args[-1] == "-"
    assert capture.stdin == b"[user]\nhi"


@pytest.mark.asyncio
async def test_complete_writes_response_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    capture = _install_fake_subprocess(monkeypatch)
    settings = Settings(codex_binary="codex-test", codex_model="gpt-5.4")
    port = CodexModelPort(settings)
    schema: dict[str, object] = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    }

    await port.complete(
        role="reasoner",
        messages=[Message(role="user", content="json please")],
        response_schema=schema,
    )

    assert "--output-schema" in capture.args
    assert capture.schema_text is not None
    assert '"required": ["name"]' in capture.schema_text


@pytest.mark.asyncio
async def test_complete_error_is_scrubbed(monkeypatch: pytest.MonkeyPatch) -> None:
    prompt_secret = "owner secret prompt"
    stderr_secret = "stderr echoed owner secret"
    _install_fake_subprocess(monkeypatch, returncode=7, stderr_text=stderr_secret)
    settings = Settings(codex_binary="codex-test", codex_model="gpt-5.4")
    port = CodexModelPort(settings)

    with pytest.raises(RuntimeError) as exc_info:
        await port.complete(role="reasoner", messages=[Message(role="user", content=prompt_secret)])

    message = str(exc_info.value)
    assert "rc=7" in message
    assert prompt_secret not in message
    assert stderr_secret not in message


@pytest.mark.asyncio
async def test_embed_raises_not_implemented() -> None:
    port = CodexModelPort(Settings(codex_binary="codex-test", codex_model="gpt-5.4"))

    with pytest.raises(NotImplementedError, match="Codex has no embeddings"):
        await port.embed("embedder", ["hello"])


def test_protocol_conformance() -> None:
    port = CodexModelPort(Settings(codex_binary="codex-test", codex_model="gpt-5.4"))

    assert isinstance(port, ModelPort)


@pytest.mark.asyncio
async def test_complete_does_not_need_codex_on_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", "")
    _install_fake_subprocess(monkeypatch, output_text="path independent")
    settings = Settings(codex_binary="codex-missing", codex_model="gpt-5.4")
    port = CodexModelPort(settings)

    resp = await port.complete(role="reasoner", messages=[Message(role="user", content="hi")])

    assert resp.text == "path independent"
