"""Sandbox verification for staged capabilities."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import BaseModel


class VerifyResult(BaseModel):
    passed: bool
    output: str


@runtime_checkable
class SandboxRunner(Protocol):
    async def run_tests(self, skill_dir: Path) -> VerifyResult: ...


class SubprocessSandbox:
    """Subprocess interim verifier.

    The WSL2 runner (no-network, egress allowlist, resource limits) swaps in behind
    SandboxRunner. This runs untrusted self-authored code, so the hardening is required before
    external-authored capabilities.
    """

    def __init__(self, *, timeout_s: float = 30.0) -> None:
        self._timeout_s = timeout_s

    async def run_tests(self, skill_dir: Path) -> VerifyResult:
        tests_dir = skill_dir / "tests"
        if not tests_dir.is_dir() or not any(tests_dir.iterdir()):
            return VerifyResult(passed=False, output="no tests - cannot verify")

        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "pytest",
            "tests",
            "-q",
            cwd=skill_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self._timeout_s)
        except TimeoutError:
            proc.kill()
            stdout, stderr = await proc.communicate()
            output = self._truncate((stdout + stderr).decode(errors="replace"))
            return VerifyResult(passed=False, output=output)

        output = self._truncate((stdout + stderr).decode(errors="replace"))
        return VerifyResult(passed=proc.returncode == 0, output=output)

    def _truncate(self, output: str) -> str:
        return output[:4000]
