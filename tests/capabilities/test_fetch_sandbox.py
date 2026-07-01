from __future__ import annotations

import os
import shutil
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from artemis.capabilities import fetch_sandbox as fs
from artemis.capabilities.fetch_sandbox import FetchResult, FetchSandbox

_WSL_SMOKE = shutil.which("wsl.exe") is not None and os.environ.get("ARTEMIS_WSL_SMOKE") == "1"


def test_fetch_result_construction() -> None:
    r = FetchResult(output="hi", exit_code=0, truncated=False)
    assert (r.output, r.exit_code, r.truncated) == ("hi", 0, False)


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


@pytest.mark.asyncio
async def test_truncated_flag_passed_through(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
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
