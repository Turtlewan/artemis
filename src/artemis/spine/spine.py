"""Minimal plan-act-verify orchestration spine.

Task goal and context are untrusted input that may later come from email or the web. Artemis
instructions stay in system messages; goal and context are only placed in user messages.
"""

from __future__ import annotations

from artemis.ports.model import ModelPort
from artemis.spine.checkpoint import Checkpoint, InMemoryCheckpoint
from artemis.spine.types import PLAN_SCHEMA, Acceptance, Plan, RunResult, RunState, Task
from artemis.types import Message


class Spine:
    def __init__(
        self,
        model: ModelPort,
        *,
        checkpoint: Checkpoint | None = None,
        model_id: str | None = None,
    ) -> None:
        self._model = model
        self._checkpoint = checkpoint or InMemoryCheckpoint()
        self._model_id = model_id

    async def run(self, task: Task, *, acceptance: Acceptance | None = None) -> RunResult:
        self._checkpoint.save(task.id, "planning", {"task": task.model_dump()})
        plan_response = await self._model.complete(
            messages=[
                Message(
                    role="system",
                    content="You are Artemis. Produce a concise execution plan for the task.",
                ),
                Message(role="user", content=f"Goal:\n{task.goal}"),
            ],
            response_schema=PLAN_SCHEMA,
            model=self._model_id,
        )
        plan = Plan.model_validate(plan_response.structured)

        attempts = 0
        out = ""
        final_state: RunState = "failed"
        failure_note: str | None = None
        max_attempts = task.max_retries + 1

        while attempts < max_attempts:
            attempts += 1
            self._checkpoint.save(
                task.id,
                "acting",
                {"task": task.model_dump(), "plan": plan.model_dump(), "attempt": attempts},
            )
            # TODO(slice-1): delegate-whole-task to a subscription sub-agent
            out = (
                await self._model.complete(
                    messages=self._act_messages(task, plan, failure_note),
                    model=self._model_id,
                )
            ).text

            if acceptance is None:
                final_state = "done"
                break

            self._checkpoint.save(
                task.id,
                "verifying",
                {
                    "task": task.model_dump(),
                    "plan": plan.model_dump(),
                    "attempt": attempts,
                    "output": out,
                },
            )
            if acceptance(out):
                final_state = "done"
                break
            failure_note = "The grounded acceptance check failed for the previous output."

        self._checkpoint.save(
            task.id,
            final_state,
            {
                "task": task.model_dump(),
                "plan": plan.model_dump(),
                "attempts": attempts,
                "output": out,
            },
        )
        return RunResult(
            task_id=task.id,
            state=final_state,
            output=out,
            plan=plan,
            attempts=attempts,
        )

    def _act_messages(self, task: Task, plan: Plan, failure_note: str | None) -> list[Message]:
        content_parts = [
            f"Goal:\n{task.goal}",
            f"Context:\n{task.context}",
            "Plan steps:\n" + "\n".join(f"- {step}" for step in plan.steps),
        ]
        if failure_note is not None:
            content_parts.append(f"Retry note:\n{failure_note}")
        return [
            Message(
                role="system", content="You are Artemis. Execute the plan and return the result."
            ),
            Message(role="user", content="\n\n".join(content_parts)),
        ]
