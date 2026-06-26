"""Reliability helpers for the agentic plan-act-verify loop.

Verification is external and deterministic: check ids resolve to read-back
predicates over the tool result or workspace state. This module deliberately
has no planner/model dependency.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from artemis.agentic.types import Task

VerifyPredicate = Callable[[BaseModel], bool]


@dataclass(frozen=True)
class BudgetDecision:
    """Pre-call resource budget decision."""

    ok: bool
    reason: str = ""


class BudgetTracker:
    """Check task resource ceilings before model or tool calls."""

    def check(self, task: Task, *, steps_done: int, tokens_used: int) -> BudgetDecision:
        """Return a failing decision when a pre-call budget is already exhausted."""
        if steps_done >= task.step_budget:
            return BudgetDecision(ok=False, reason="step budget exhausted")
        if tokens_used >= task.token_budget:
            return BudgetDecision(ok=False, reason="token budget exhausted")
        return BudgetDecision(ok=True)


class CircuitBreaker:
    """Trip after too many consecutive unverified attempts."""

    def __init__(self, *, max_unverified: int = 2) -> None:
        if max_unverified < 1:
            raise ValueError("max_unverified must be at least 1")
        self._max_unverified = max_unverified
        self._consecutive_unverified = 0

    @property
    def consecutive_unverified(self) -> int:
        """Current no-progress count."""
        return self._consecutive_unverified

    def record(self, *, verified: bool) -> bool:
        """Record one attempt and return whether the breaker is tripped."""
        if verified:
            self._consecutive_unverified = 0
            return False
        self._consecutive_unverified += 1
        return self.tripped

    @property
    def tripped(self) -> bool:
        """Return whether the breaker is currently tripped."""
        return self._consecutive_unverified >= self._max_unverified

    def reset(self) -> None:
        """Reset the no-progress counter after owner approval or verified progress."""
        self._consecutive_unverified = 0


class VerifyResolver:
    """Resolve deterministic verification check ids."""

    def __init__(
        self,
        *,
        workspace_root: Path,
        predicates: Mapping[str, VerifyPredicate] | None = None,
    ) -> None:
        self._workspace_root = workspace_root
        self._predicates = dict(predicates or {})

    def verify(self, check_id: str, result: BaseModel) -> bool:
        """Evaluate ``check_id`` without consulting a model."""
        return verify(
            check_id,
            result,
            workspace_root=self._workspace_root,
            predicates=self._predicates,
        )


def verify(
    check_id: str,
    result: BaseModel,
    *,
    workspace_root: Path | None = None,
    predicates: Mapping[str, VerifyPredicate] | None = None,
) -> bool:
    """Resolve a deterministic check id against ``result`` or the filesystem."""
    if check_id == "exit0":
        exit_code = _field(result, "exit_code")
        if isinstance(exit_code, int):
            return exit_code == 0
        ok = _field(result, "ok")
        return isinstance(ok, bool) and ok

    if check_id.startswith("equals:"):
        expected = check_id.removeprefix("equals:")
        return _output_text(result) == expected

    if check_id.startswith("exists:"):
        root = Path.cwd() if workspace_root is None else workspace_root
        raw_path = check_id.removeprefix("exists:")
        path = Path(raw_path)
        candidate = path if path.is_absolute() else root / path
        return candidate.exists()

    predicate = (predicates or {}).get(check_id)
    if predicate is not None:
        return predicate(result)

    return False


def _field(result: BaseModel, name: str) -> object:
    return result.model_dump().get(name)


def _output_text(result: BaseModel) -> str:
    dumped = result.model_dump()
    output = dumped.get("output")
    if output is None:
        output = dumped.get("text")
    if output is None:
        output = dumped.get("stdout")
    return "" if output is None else str(output)
