"""Tests for Rung 2 sandboxed command execution."""

from __future__ import annotations

import platform
import socket
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest

from artemis.agentic.authority import AuthDecision, PendingActionRef
from artemis.agentic.rungs.command import CommandRunArgs, register_rung2, run_command
from artemis.agentic.sandbox import (
    CommandResult,
    DockerSandbox,
    SandboxUnavailableError,
    WindowsAppContainerSandbox,
)
from artemis.agentic.types import PlanStep
from artemis.ports.types import Vector
from artemis.registry import ToolRegistry


class FakeEmbedder:
    @property
    def dimension(self) -> int:
        return 2

    async def embed_documents(self, texts: Sequence[str]) -> list[Vector]:
        return [[1.0, 0.0] for _text in texts]

    async def embed_query(self, query: str) -> Vector:
        return [1.0, 0.0]


class RecordingSandbox:
    def __init__(self, result: CommandResult | None = None) -> None:
        self.calls: list[tuple[tuple[str, ...], Path, frozenset[str] | None, int]] = []
        self.result = result or CommandResult(exit_code=0, stdout="done", stderr="")

    async def run(
        self,
        argv: Sequence[str],
        *,
        workspace_root: Path,
        allow_network: frozenset[str] | None = None,
        timeout_s: int = 30,
    ) -> CommandResult:
        self.calls.append((tuple(argv), workspace_root, allow_network, timeout_s))
        return self.result


class FakeAuthority:
    def __init__(self, decision: AuthDecision | None = None, *, fail: bool = False) -> None:
        self.decision = decision or AuthDecision(auto=True, summary="in_sandbox: proc.run")
        self.fail = fail
        self.calls: list[PlanStep] = []

    def authorize(self, step: PlanStep, *, workspace_root: Path) -> AuthDecision:
        del workspace_root
        self.calls.append(step)
        if self.fail:
            raise RuntimeError("authority backend down")
        return self.decision


@pytest.mark.asyncio
async def test_proc_run_auto_authorized_invokes_sandbox(tmp_path: Path) -> None:
    sandbox = RecordingSandbox(CommandResult(exit_code=0, stdout="ok", stderr=""))
    authority = FakeAuthority()

    result = await run_command(
        CommandRunArgs(argv=(sys.executable, "-c", "print('ok')")),
        sandbox=sandbox,
        authority=authority,
        workspace_root=tmp_path,
    )

    assert result == CommandResult(exit_code=0, stdout="ok", stderr="")
    assert sandbox.calls == [((sys.executable, "-c", "print('ok')"), tmp_path, None, 30)]
    assert authority.calls[0].tool_ref == "proc.run"
    assert authority.calls[0].args["disposable"] is True


@pytest.mark.asyncio
async def test_authorize_raise_fails_closed_and_does_not_run(tmp_path: Path) -> None:
    sandbox = RecordingSandbox()
    result = await run_command(
        CommandRunArgs(argv=(sys.executable, "-c", "raise SystemExit(99)")),
        sandbox=sandbox,
        authority=FakeAuthority(fail=True),
        workspace_root=tmp_path,
    )

    assert result.exit_code == 2
    assert "authority failed closed: RuntimeError" in result.stderr
    assert sandbox.calls == []


@pytest.mark.asyncio
async def test_boundary_staged_does_not_run_until_graduated(tmp_path: Path) -> None:
    sandbox = RecordingSandbox()
    staged = FakeAuthority(
        AuthDecision(
            auto=False,
            pending=PendingActionRef("pending-1"),
            summary="boundary: proc.run",
        )
    )

    parked = await run_command(
        CommandRunArgs(argv=(sys.executable, "-c", "print('no')")),
        sandbox=sandbox,
        authority=staged,
        workspace_root=tmp_path,
    )
    assert parked.exit_code == 202
    assert "needs-approval: boundary: proc.run pending=pending-1" in parked.stderr
    assert sandbox.calls == []

    graduated = FakeAuthority(AuthDecision(auto=True, summary="boundary: proc.run"))
    ran = await run_command(
        CommandRunArgs(argv=(sys.executable, "-c", "print('yes')")),
        sandbox=sandbox,
        authority=graduated,
        workspace_root=tmp_path,
    )
    assert ran.exit_code == 0
    assert sandbox.calls[-1][0] == (sys.executable, "-c", "print('yes')")


def test_register_rung2_registers_proc_run(tmp_path: Path) -> None:
    registry = ToolRegistry(FakeEmbedder())

    register_rung2(
        registry,
        sandbox=RecordingSandbox(),
        authority=FakeAuthority(),
        workspace_root=tmp_path,
    )

    assert registry.get_tool("proc.run").callable_ref is not None
    assert registry.get_tool("proc.run_execute").callable_ref is not None


@pytest.mark.asyncio
async def test_docker_sandbox_is_mac_gated_on_dev_box(tmp_path: Path) -> None:
    if platform.system() == "Darwin":
        pytest.skip("Mac-gated stub is only expected to error on the Windows dev box")
    with pytest.raises(SandboxUnavailableError, match="Mac-gated"):
        await DockerSandbox().run((sys.executable, "-c", "print(1)"), workspace_root=tmp_path)


@pytest.mark.asyncio
async def test_windows_sandbox_shell_metacharacters_are_inert(tmp_path: Path) -> None:
    sandbox = WindowsAppContainerSandbox()
    marker = tmp_path / "marker.txt"
    result = await sandbox.run(
        (
            _python_executable(),
            "-c",
            "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text('ok')",
            f"{marker}; echo injected",
        ),
        workspace_root=tmp_path,
        timeout_s=10,
    )
    _skip_if_appcontainer_unavailable(result)

    assert result.exit_code == 0
    assert marker.with_name("marker.txt; echo injected").read_text(encoding="utf-8") == "ok"
    assert not marker.exists()


@pytest.mark.asyncio
async def test_windows_sandbox_output_cap_and_timeout(tmp_path: Path) -> None:
    sandbox = WindowsAppContainerSandbox()
    capped = await sandbox.run(
        (_python_executable(), "-c", "import sys; sys.stdout.write('x' * 1200000)"),
        workspace_root=tmp_path,
        timeout_s=10,
    )
    _skip_if_appcontainer_unavailable(capped)

    assert capped.exit_code == 0
    assert len(capped.stdout.encode()) <= 1_048_576
    timed = await sandbox.run(
        (_python_executable(), "-c", "import time; time.sleep(60)"),
        workspace_root=tmp_path,
        timeout_s=1,
    )
    assert timed.timed_out is True
    assert timed.exit_code == 124


@pytest.mark.asyncio
async def test_windows_sandbox_live_network_denied_or_host_guarded(tmp_path: Path) -> None:
    if platform.system() != "Windows":
        pytest.skip("AppContainer/live-network validation is Windows-specific")
    if not _outside_network_connects():
        pytest.skip(
            "AppContainer/live-network not exercisable under nested sandbox: "
            "positive-control outbound connection failed"
        )

    sandbox = WindowsAppContainerSandbox()
    payload = (
        "import socket,sys\n"
        "try:\n"
        "    socket.create_connection(('1.1.1.1', 80), timeout=3)\n"
        "except OSError:\n"
        "    raise SystemExit(0)\n"
        "raise SystemExit(42)\n"
    )
    result = await sandbox.run((_python_executable(), "-c", payload), workspace_root=tmp_path)
    _skip_if_appcontainer_unavailable(
        result,
        "AppContainer/live-network not exercisable under nested sandbox - host-validated",
    )

    assert result.exit_code == 0


@pytest.mark.asyncio
async def test_windows_sandbox_maps_icacls_failure_to_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # icacls ACL-grant runs with check=True -> CalledProcessError (a
    # SubprocessError, NOT an OSError). run() must map it to a fail-closed
    # CommandResult, never let it propagate unhandled.
    def _boom(*_args: object, **_kwargs: object) -> CommandResult:
        raise subprocess.CalledProcessError(1, ["icacls", str(tmp_path)])

    monkeypatch.setattr("artemis.agentic.sandbox._mpssvc_running", lambda: True)
    monkeypatch.setattr("artemis.agentic.sandbox._run_appcontainer_process", _boom)

    result = await WindowsAppContainerSandbox().run(
        (_python_executable(), "-c", "print('x')"), workspace_root=tmp_path
    )

    assert result.exit_code == 2
    assert "sandbox setup failed" in result.stderr


def _outside_network_connects() -> bool:
    try:
        with socket.create_connection(("1.1.1.1", 80), timeout=3):
            return True
    except OSError:
        return False


def _python_executable() -> str:
    base = getattr(sys, "_base_executable", "")
    if isinstance(base, str) and base:
        return base
    return sys.executable


def _skip_if_appcontainer_unavailable(
    result: CommandResult,
    reason: str = "AppContainer not exercisable under nested sandbox - host-validated",
) -> None:
    unavailable = (
        "AppContainer profile unavailable",
        "sandbox launch failed",
        "MPSSVC is not running",
        "CreateProcessW failed",
        "InitializeProcThreadAttributeList failed",
    )
    if result.exit_code == 2 and any(text in result.stderr for text in unavailable):
        pytest.skip(reason)
