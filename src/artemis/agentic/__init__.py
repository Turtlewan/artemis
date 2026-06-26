"""Shared agentic runtime types and Protocols."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from artemis.agentic.types import (
        CheckpointRow,
        CheckpointStore,
        Crossing,
        ExecutorState,
        OwnerInbox,
        Plan,
        PlanStep,
        StepResult,
        Task,
    )

__all__ = [
    "CheckpointRow",
    "CheckpointStore",
    "Crossing",
    "ExecutorState",
    "OwnerInbox",
    "Plan",
    "PlanStep",
    "StepResult",
    "Task",
]


def __getattr__(name: str) -> object:
    if name in __all__:
        from artemis.agentic import types

        return getattr(types, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
