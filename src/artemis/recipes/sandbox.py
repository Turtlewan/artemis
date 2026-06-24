"""Sandbox port for executing script-class recipes.

Script recipes are teacher-supplied automation. They must run only through a
concrete sandbox implementation supplied by the security layer; this module
defines the fail-closed port and a tiny fake for tests.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, runtime_checkable


class SandboxNotAvailableError(Exception):
    """Raised when a script recipe is applied without a ready sandbox."""


@runtime_checkable
class SandboxPort(Protocol):
    """Port for default-deny execution of script recipes."""

    def ready(self) -> bool:
        """Return whether the sandbox can execute a recipe now."""
        ...

    def run(
        self,
        script: str,
        inputs: Mapping[str, object],
        *,
        outputs_schema: dict[str, object],
    ) -> dict[str, object]:
        """Execute a script with structured inputs and schema-shaped outputs."""
        ...


class FakeSandbox:
    """Test sandbox returning a canned output."""

    def __init__(self, output: Mapping[str, object], *, ready: bool = True) -> None:
        self._output = dict(output)
        self._ready = ready
        self.runs: list[tuple[str, dict[str, object], dict[str, object]]] = []

    def ready(self) -> bool:
        """Return the configured readiness flag."""
        return self._ready

    def run(
        self,
        script: str,
        inputs: Mapping[str, object],
        *,
        outputs_schema: dict[str, object],
    ) -> dict[str, object]:
        """Record the run and return the canned output."""
        self.runs.append((script, dict(inputs), outputs_schema))
        return dict(self._output)
