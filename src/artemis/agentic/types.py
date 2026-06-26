"""Backbone seam for shared agentic runtime types and Protocols."""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict


class ExecutorState(StrEnum):
    """Executor lifecycle states shared by agentic runtime components."""

    PLANNING = "planning"
    ACTING = "acting"
    VERIFYING = "verifying"
    WAITING_OWNER = "waiting_owner"
    DONE = "done"
    FAILED = "failed"


class Crossing(StrEnum):
    """Authority boundary classification for an agentic action."""

    IN_SANDBOX = "in_sandbox"
    BOUNDARY = "boundary"


class PlanStep(BaseModel):
    """Single deterministic action in an agentic plan."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    id: str
    description: str
    tool_ref: str
    args: dict[str, str | int | float | bool] = {}
    verify: str


class Plan(BaseModel):
    """Ordered action plan for one task."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    task_id: str
    steps: tuple[PlanStep, ...]


class StepResult(BaseModel):
    """Recorded result for an executed plan step."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    step_id: str
    ok: bool
    output: str
    verified: bool


class Task(BaseModel):
    """Agentic task request with explicit resource budgets."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    id: str
    goal: str
    unattended: bool = False
    token_budget: int
    step_budget: int


class CheckpointRow(BaseModel):
    """Persisted executor checkpoint row."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    task_id: str
    state: ExecutorState
    plan: Plan
    step_index: int
    last_verified_output: str | None = None


class CheckpointStore(Protocol):
    """Structural port for executor checkpoint persistence."""

    def save(
        self,
        task_id: str,
        state: ExecutorState,
        plan: Plan,
        step_index: int,
        last_verified_output: str | None,
    ) -> None: ...

    def load(self, task_id: str) -> CheckpointRow | None: ...


class OwnerInbox(Protocol):
    """Structural port for owner questions at authority boundaries."""

    async def ask(
        self, question: str, *, options: tuple[str, ...] = (), timeout_s: int = 0
    ) -> str | None: ...
