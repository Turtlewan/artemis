from __future__ import annotations

import pytest
from pydantic import ValidationError

from artemis.agentic import (
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


class MemoryCheckpointStore:
    def __init__(self) -> None:
        self.row: CheckpointRow | None = None

    def save(
        self,
        task_id: str,
        state: ExecutorState,
        plan: Plan,
        step_index: int,
        last_verified_output: str | None,
    ) -> None:
        self.row = CheckpointRow(
            task_id=task_id,
            state=state,
            plan=plan,
            step_index=step_index,
            last_verified_output=last_verified_output,
        )

    def load(self, task_id: str) -> CheckpointRow | None:
        if self.row is None or self.row.task_id != task_id:
            return None
        return self.row


class StaticOwnerInbox:
    async def ask(
        self, question: str, *, options: tuple[str, ...] = (), timeout_s: int = 0
    ) -> str | None:
        _ = question, timeout_s
        return options[0] if options else None


def test_public_agentic_types_are_importable() -> None:
    assert ExecutorState.PLANNING.value == "planning"
    assert Crossing.BOUNDARY.value == "boundary"
    assert StepResult(step_id="s1", ok=True, output="done", verified=True).verified is True


def test_plan_constructs_with_tuple_steps() -> None:
    step = PlanStep(id="s1", description="do it", tool_ref="tool.echo", verify="echoed")
    plan = Plan(task_id="task-1", steps=(step,))

    assert plan.task_id == "task-1"
    assert plan.steps == (step,)


def test_plan_step_rejects_extra_fields_and_is_frozen() -> None:
    with pytest.raises(ValidationError):
        PlanStep.model_validate(
            {
                "id": "s1",
                "description": "do it",
                "tool_ref": "tool.echo",
                "verify": "echoed",
                "bogus": 1,
            }
        )

    step = PlanStep(id="s1", description="do it", tool_ref="tool.echo", verify="echoed")
    with pytest.raises(ValidationError):
        setattr(step, "description", "changed")


def test_task_requires_budgets() -> None:
    with pytest.raises(ValidationError):
        Task.model_validate({"id": "task-1", "goal": "finish"})

    task = Task(id="task-1", goal="finish", token_budget=100, step_budget=5)
    assert task.unattended is False


def test_protocols_accept_structural_implementations() -> None:
    step = PlanStep(id="s1", description="do it", tool_ref="tool.echo", verify="echoed")
    plan = Plan(task_id="task-1", steps=(step,))

    checkpoint_store: CheckpointStore = MemoryCheckpointStore()
    owner_inbox: OwnerInbox = StaticOwnerInbox()

    checkpoint_store.save("task-1", ExecutorState.PLANNING, plan, 0, None)

    assert checkpoint_store.load("task-1") == CheckpointRow(
        task_id="task-1",
        state=ExecutorState.PLANNING,
        plan=plan,
        step_index=0,
    )
    assert owner_inbox is not None
