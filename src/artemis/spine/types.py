"""Types for the Artemis plan-act-verify spine."""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel


RunState = Literal["planning", "acting", "verifying", "done", "failed"]


class Task(BaseModel):
    id: str
    goal: str
    context: str = ""
    max_retries: int = 1


class Plan(BaseModel):
    steps: list[str]


class RunResult(BaseModel):
    task_id: str
    state: RunState
    output: str
    plan: Plan | None
    attempts: int


Acceptance = Callable[[str], bool]

PLAN_SCHEMA: dict = {  # type: ignore[type-arg]
    "type": "object",
    "properties": {"steps": {"type": "array", "items": {"type": "string"}}},
}
