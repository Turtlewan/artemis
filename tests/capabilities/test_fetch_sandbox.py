from __future__ import annotations

import os
import shutil
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from artemis.capabilities import fetch_sandbox as fs
from artemis.capabilities.fetch_sandbox import FetchResult, FetchSandbox
from artemis.capabilities.sandbox_wsl2 import RENDER_CAPS, SandboxCaps

_WSL_SMOKE = shutil.which("wsl.exe") is not None and os.environ.get("ARTEMIS_WSL_SMOKE") == "1"


class _FakeSecretStore:
    def __init__(self, names: list[str], values: dict[str, str | None] | None = None) -> None:
        self._names = names
        self._values = values or {}
        self.list_names_calls = 0
        self.get_calls: list[str] = []

    def get(self, name: str) -> str | None:
        self.get_calls.append(name)
        return self._values.get(name)

    def set(self, name: str, value: str) -> None:
        self._values[name] = value
        if name not in self._names:
            self._names.append(name)

    def delete(self, name: str) -> None:
        self._values.pop(name, None)
        if name in self._names:
            self._names.remove(name)

    def list_names(self) -> list[str]:
        self.list_names_calls += 1
        return list(self._names)


def test_fetch_result_construction() -> None:
    r = FetchResult(output="hi", exit_code=0, truncated=False)
    assert (r.output, r.exit_code, r.truncated) == ("hi", 0, False)


def test_missing_required_secrets_is_presence_only() -> None:
    store = _FakeSecretStore(["A"])

    assert fs.missing_required_secrets(["A", "B"], store) == ["B"]
    assert store.list_names_calls == 1
    assert store.get_calls == []


def test_missing_required_secrets_returns_empty_when_all_present() -> None:
    store = _FakeSecretStore(["A", "B"])

    assert fs.missing_required_secrets(["A", "B"], store) == []
    assert store.list_names_calls == 1
    assert store.get_calls == []


def test_resolve_secret_values_returns_present_values() -> None:
    store = _FakeSecretStore(["A"], {"A": "va"})

    assert fs.resolve_secret_values(["A"], store) == {"A": "va"}
    assert store.get_calls == ["A"]


@pytest.mark.parametrize(("name", "value"), [("B", None), ("C", "")])
def test_resolve_secret_values_fails_closed_on_missing_or_empty(
    name: str, value: str | None
) -> None:
    store = _FakeSecretStore([name], {name: value})

    with pytest.raises(ValueError, match=f"secret not available for injection: {name}"):
        fs.resolve_secret_values([name], store)


@pytest.mark.asyncio
async def test_run_assembles_command_and_passes_egress(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    mock = AsyncMock(return_value=(0, "raw bytes out", False))
    monkeypatch.setattr(fs, "run_isolated", mock)

    result = await FetchSandbox().run(
        tmp_path,
        entrypoint="fetch.py",
        argv=["--q", "x"],
        egress_domains=["api.example.com"],
        timeout_s=42.0,
    )

    assert isinstance(result, FetchResult)
    assert (result.output, result.exit_code, result.truncated) == ("raw bytes out", 0, False)
    await_args = mock.await_args
    assert await_args is not None
    kwargs = await_args.kwargs
    assert kwargs["command"] == ["python3", "fetch.py", "--q", "x"]
    assert kwargs["egress_domains"] == ["api.example.com"]
    assert kwargs["timeout_s"] == 42.0
    assert kwargs["secrets"] is None
    assert kwargs["output_limit"] == 4000


@pytest.mark.asyncio
async def test_run_forwards_output_limit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    mock = AsyncMock(return_value=(0, "raw bytes out", False))
    monkeypatch.setattr(fs, "run_isolated", mock)

    await FetchSandbox().run(
        tmp_path,
        entrypoint="fetch.py",
        argv=[],
        egress_domains=[],
        output_limit=200_000,
    )

    await_args = mock.await_args
    assert await_args is not None
    assert await_args.kwargs["output_limit"] == 200_000


@pytest.mark.asyncio
async def test_run_uses_default_caps_profile_when_omitted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    mock = AsyncMock(return_value=(0, "raw bytes out", False))
    monkeypatch.setattr(fs, "run_isolated", mock)

    await FetchSandbox().run(tmp_path, entrypoint="fetch.py", argv=[], egress_domains=[])

    await_args = mock.await_args
    assert await_args is not None
    assert await_args.kwargs["caps"] == SandboxCaps()


@pytest.mark.asyncio
async def test_run_forwards_render_caps_profile(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    mock = AsyncMock(return_value=(0, "raw bytes out", False))
    monkeypatch.setattr(fs, "run_isolated", mock)

    await FetchSandbox().run(
        tmp_path, entrypoint="fetch.py", argv=[], egress_domains=[], caps_profile="render"
    )

    await_args = mock.await_args
    assert await_args is not None
    assert await_args.kwargs["caps"] == RENDER_CAPS


@pytest.mark.asyncio
async def test_run_forwards_secrets(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    mock = AsyncMock(return_value=(0, "raw bytes out", False))
    monkeypatch.setattr(fs, "run_isolated", mock)

    await FetchSandbox().run(
        tmp_path,
        entrypoint="fetch.py",
        argv=[],
        egress_domains=[],
        secrets={"A": "b"},
    )

    await_args = mock.await_args
    assert await_args is not None
    assert await_args.kwargs["secrets"] == {"A": "b"}


@pytest.mark.asyncio
async def test_truncated_flag_passed_through(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(fs, "run_isolated", AsyncMock(return_value=(0, "short", True)))

    result = await FetchSandbox().run(tmp_path, entrypoint="f.py", argv=[], egress_domains=[])

    assert result.truncated is True


@pytest.mark.asyncio
async def test_nonzero_exit_propagates(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(fs, "run_isolated", AsyncMock(return_value=(1, "boom", False)))

    result = await FetchSandbox().run(tmp_path, entrypoint="f.py", argv=[], egress_domains=[])

    assert result.exit_code == 1


@pytest.mark.parametrize("bad", ["/etc/passwd", "../evil.py", "a/../../evil.py"])
@pytest.mark.asyncio
async def test_entrypoint_traversal_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, bad: str
) -> None:
    mock = AsyncMock(return_value=(0, "", False))
    monkeypatch.setattr(fs, "run_isolated", mock)

    with pytest.raises(ValueError):
        await FetchSandbox().run(tmp_path, entrypoint=bad, argv=[], egress_domains=[])

    mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_timeout_clamped_to_ceiling(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    mock = AsyncMock(return_value=(0, "ok", False))
    monkeypatch.setattr(fs, "run_isolated", mock)

    await FetchSandbox().run(
        tmp_path, entrypoint="f.py", argv=[], egress_domains=[], timeout_s=99999.0
    )

    await_args = mock.await_args
    assert await_args is not None
    assert await_args.kwargs["timeout_s"] == fs._MAX_TIMEOUT_S


@pytest.mark.skipif(
    not _WSL_SMOKE,
    reason="WSL2 not provisioned (set ARTEMIS_WSL_SMOKE=1 on a provisioned host)",
)
@pytest.mark.asyncio
async def test_live_wsl_allowlisted_fetch_returns_bytes(tmp_path: Path) -> None:
    (tmp_path / "fetch.py").write_text(
        "import urllib.request\n"
        "print(urllib.request.urlopen('https://example.com', timeout=20)"
        ".read()[:64].decode('latin-1'))\n",
        encoding="utf-8",
    )
    allowed = await FetchSandbox().run(
        tmp_path,
        entrypoint="fetch.py",
        argv=[],
        egress_domains=["example.com"],
        timeout_s=60.0,
    )
    assert allowed.exit_code == 0
    assert allowed.output.strip() != ""

    blocked = await FetchSandbox().run(
        tmp_path,
        entrypoint="fetch.py",
        argv=[],
        egress_domains=["other.invalid"],
        timeout_s=60.0,
    )
    assert blocked.exit_code != 0
