from __future__ import annotations

from collections.abc import Sequence

import pytest

from artemis.ports.model import ModelPort
from artemis.spine.checkpoint import Checkpoint
from artemis.spine.spine import Spine
from artemis.spine.types import RunState, Task
from artemis.types import Message, ModelResponse, Usage


class FakeModel:
    def __init__(self, outputs: list[str] | None = None) -> None:
        self.outputs = outputs or ["acted"]
        self.calls: list[Sequence[Message]] = []
        self.schemas: list[dict | None] = []  # type: ignore[type-arg]

    async def complete(
        self,
        *,
        messages: Sequence[Message],
        model: str | None = None,
        response_schema: dict | None = None,  # type: ignore[type-arg]
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        del model, temperature, max_tokens
        self.calls.append(messages)
        self.schemas.append(response_schema)
        if response_schema is not None:
            return ModelResponse(
                text='{"steps":["draft","check"]}',
                model_id="fake",
                structured={"steps": ["draft", "check"]},
                finish_reason="stop",
                usage=Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
            )
        index = len([schema for schema in self.schemas if schema is None]) - 1
        return ModelResponse(
            text=self.outputs[index],
            model_id="fake",
            structured=None,
            finish_reason="stop",
            usage=Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
        )


class RecordingCheckpoint:
    def __init__(self) -> None:
        self.states: list[RunState] = []
        self.snapshots: dict[str, dict] = {}  # type: ignore[type-arg]

    def save(self, task_id: str, state: RunState, data: dict) -> None:  # type: ignore[type-arg]
        self.states.append(state)
        self.snapshots[task_id] = {"state": state, "data": data}

    def load(self, task_id: str) -> dict | None:  # type: ignore[type-arg]
        return self.snapshots.get(task_id)


@pytest.mark.asyncio
async def test_run_without_acceptance_is_done_and_checkpoints_transitions() -> None:
    model = FakeModel()
    checkpoint = RecordingCheckpoint()
    result = await Spine(model, checkpoint=checkpoint).run(
        Task(id="task-1", goal="write it", context="source text")
    )

    assert isinstance(model, ModelPort)
    assert isinstance(checkpoint, Checkpoint)
    assert result.state == "done"
    assert result.output == "acted"
    assert checkpoint.states == ["planning", "acting", "done"]
    assert model.calls[0][0].role == "system"
    assert "write it" not in model.calls[0][0].content


@pytest.mark.asyncio
async def test_acceptance_passes_in_one_attempt() -> None:
    result = await Spine(FakeModel(["accepted"])).run(
        Task(id="task-1", goal="write it"),
        acceptance=lambda output: output == "accepted",
    )

    assert result.state == "done"
    assert result.attempts == 1


@pytest.mark.asyncio
async def test_acceptance_fails_once_then_passes_on_retry() -> None:
    result = await Spine(FakeModel(["bad", "good"])).run(
        Task(id="task-1", goal="write it", max_retries=1),
        acceptance=lambda output: output == "good",
    )

    assert result.state == "done"
    assert result.output == "good"
    assert result.attempts == 2


@pytest.mark.asyncio
async def test_acceptance_always_fails_after_max_retries() -> None:
    result = await Spine(FakeModel(["bad", "still bad"])).run(
        Task(id="task-1", goal="write it", max_retries=1),
        acceptance=lambda output: output == "good",
    )

    assert result.state == "failed"
    assert result.attempts == 2
