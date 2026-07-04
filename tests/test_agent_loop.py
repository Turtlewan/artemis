from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import FrozenInstanceError
from typing import Any

import pytest

from artemis.agent.loop import AgentLoop, LoopResult, StepRecord
from artemis.agent.tools import (
    LoopTool,
    ToolRegistry,
    build_local_read_tool,
    build_memory_tool,
)
from artemis.data.store import DataStore, Record
from artemis.ports.memory import MemoryPort
from artemis.ports.model import ModelPort
from artemis.types import Message, MemoryItem, ModelResponse, RetrievedContext, Usage


class ScriptedDriver:
    """Return one pre-built action dict per call as ModelResponse.structured."""

    def __init__(self, actions: list[dict[str, Any]], *, raise_on: int | None = None) -> None:
        self._actions = actions
        self._raise_on = raise_on
        self.calls = 0

    async def complete(
        self,
        *,
        messages: Sequence[Message],
        model: str | None = None,
        response_schema: dict[Any, Any] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        _ = (messages, model, response_schema, temperature, max_tokens)
        self.calls += 1
        if self._raise_on is not None and self.calls >= self._raise_on:
            raise RuntimeError("driver boom")
        action = self._actions[min(self.calls - 1, len(self._actions) - 1)]
        return ModelResponse(
            text=json.dumps(action),
            model_id="fake",
            structured=action,
            finish_reason="stop",
            usage=Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
        )


class FakeMemory:
    def __init__(self, items: list[MemoryItem]) -> None:
        self._items = items

    async def write(self, item: MemoryItem) -> None:
        _ = item

    async def retrieve(
        self,
        query: str,
        *,
        token_budget: int,
        layers: Sequence[str] | None = None,
    ) -> RetrievedContext:
        _ = (query, token_budget, layers)
        return RetrievedContext(
            items=self._items, token_cost=len(self._items) * 10, truncated=False
        )

    async def consolidate(self) -> None:
        return None

    async def forget(
        self,
        *,
        max_age_days: int | None = None,
        min_salience: float | None = None,
    ) -> None:
        _ = (max_age_days, min_salience)


def _tool_call(tool: str, **args: Any) -> dict[str, Any]:
    return {"kind": "tool_call", "tool": tool, "args_json": json.dumps(args), "answer": None}


def _final(answer: str) -> dict[str, Any]:
    return {"kind": "final", "tool": None, "args_json": None, "answer": answer}


def _rec(
    store: DataStore, domain: str, sanitized: str, *, payload: dict[str, Any] | None = None
) -> None:
    store.upsert(
        Record(
            domain=domain,
            kind="item",
            key=sanitized[:12],
            payload=payload or {},
            sanitized_text=sanitized,
            source="sync",
            fetched_at=1.0,
        )
    )


def _loop(
    actions: list[dict[str, Any]],
    tools: Sequence[LoopTool],
    *,
    budget: int = 8,
    raise_on: int | None = None,
) -> AgentLoop:
    return AgentLoop(
        driver=ScriptedDriver(actions, raise_on=raise_on),
        tools=ToolRegistry(tools),
        budget=budget,
    )


@pytest.mark.asyncio
async def test_immediate_final() -> None:
    result = await _loop([_final("hi")], [build_local_read_tool(DataStore())]).run("q")
    assert result == LoopResult(
        answer="hi",
        steps=(),
        stop_reason="answered",
        driver_turns=1,
        driver_tokens_total=0,
    )


@pytest.mark.asyncio
async def test_single_tool_step_then_final() -> None:
    store = DataStore()
    _rec(store, "calendar", "lunch Fri 12pm")
    result = await _loop(
        [_tool_call("local_read", domain="calendar"), _final("You have lunch Fri.")],
        [build_local_read_tool(store)],
    ).run("what is on my calendar?")
    assert (
        result.stop_reason == "answered"
        and result.answer == "You have lunch Fri."
        and len(result.steps) == 1
        and result.steps[0].tool == "local_read"
        and result.steps[0].ok is True
        and result.steps[0].duration_ms >= 0
    )


@pytest.mark.asyncio
async def test_multi_step_chain_calendar_and_tasks_composed() -> None:
    store = DataStore()
    _rec(store, "calendar", "lunch Fri")
    _rec(store, "tasks", "file taxes")
    result = await _loop(
        [
            _tool_call("local_read", domain="calendar"),
            _tool_call("local_read", domain="tasks"),
            _final("Lunch Fri; taxes due."),
        ],
        [build_local_read_tool(store)],
    ).run("summarize my week")
    assert (
        len(result.steps) == 2
        and all(step.ok for step in result.steps)
        and result.stop_reason == "answered"
        and result.steps[0].args == {"domain": "calendar"}
        and result.steps[1].args == {"domain": "tasks"}
    )


@pytest.mark.asyncio
async def test_memory_retrieve_tool() -> None:
    mem = FakeMemory([MemoryItem(content="owner hates 8am meetings", layer="semantic")])
    result = await _loop(
        [_tool_call("memory_retrieve", query="meeting prefs"), _final("Noted.")],
        [build_memory_tool(mem)],
    ).run("what are my meeting preferences?")
    assert (
        result.steps[0].tool == "memory_retrieve"
        and result.steps[0].ok is True
        and "8am" in result.steps[0].outcome
    )


@pytest.mark.asyncio
async def test_budget_exhaustion_is_graceful() -> None:
    store = DataStore()
    result = await _loop(
        [_tool_call("local_read", domain="calendar")],
        [build_local_read_tool(store)],
        budget=3,
    ).run("keep reading")
    assert (
        result.stop_reason == "budget_exhausted"
        and len(result.steps) == 3
        and "tried" in result.answer.lower()
    )


@pytest.mark.asyncio
async def test_unknown_tool_is_fail_closed() -> None:
    result = await _loop(
        [_tool_call("does_not_exist", x=1), _final("ok")],
        [build_local_read_tool(DataStore())],
    ).run("q")
    assert (
        result.steps[0].ok is False
        and "unknown tool" in result.steps[0].outcome
        and result.stop_reason == "answered"
        and result.answer == "ok"
    )


@pytest.mark.asyncio
async def test_bad_args_json_is_fail_closed() -> None:
    result = await _loop(
        [
            {"kind": "tool_call", "tool": "local_read", "args_json": "{not json", "answer": None},
            _final("ok"),
        ],
        [build_local_read_tool(DataStore())],
    ).run("q")
    assert (
        result.steps[0].ok is False
        and ("JSON" in result.steps[0].outcome or "json" in result.steps[0].outcome)
        and result.stop_reason == "answered"
        and result.answer == "ok"
    )


@pytest.mark.asyncio
async def test_driver_error_is_graceful() -> None:
    store = DataStore()
    result = await _loop(
        [_tool_call("local_read", domain="calendar")],
        [build_local_read_tool(store)],
        raise_on=1,
    ).run("q")
    assert result.stop_reason == "driver_error" and result.steps == () and result.answer


@pytest.mark.asyncio
async def test_security_observation_renders_sanitized_text_only_never_payload() -> None:
    store = DataStore()
    _rec(store, "calendar", "benign lunch note", payload={"secret": "TOPSECRET_LEAK"})
    result = await _loop(
        [_tool_call("local_read", domain="calendar"), _final("done")],
        [build_local_read_tool(store)],
    ).run("q")
    assert (
        "benign lunch note" in result.steps[0].outcome
        and "TOPSECRET_LEAK" not in result.steps[0].outcome
    )


@pytest.mark.asyncio
async def test_conformance() -> None:
    assert isinstance(build_local_read_tool(DataStore()), LoopTool)
    assert isinstance(build_memory_tool(FakeMemory([])), LoopTool)
    driver_as_port: ModelPort = ScriptedDriver([_final("x")])
    memory_as_port: MemoryPort = FakeMemory([])
    assert isinstance(driver_as_port, ScriptedDriver) and isinstance(memory_as_port, FakeMemory)
    step = StepRecord(
        index=0,
        tool="local_read",
        args={},
        outcome="ok",
        ok=True,
        duration_ms=0,
        driver_ms=0,
        driver_tokens=0,
    )
    result = LoopResult(
        answer="x",
        steps=(step,),
        stop_reason="answered",
        driver_turns=1,
        driver_tokens_total=0,
    )
    with pytest.raises(FrozenInstanceError):
        setattr(step, "tool", "changed")
    with pytest.raises(FrozenInstanceError):
        setattr(result, "answer", "changed")


@pytest.mark.asyncio
async def test_empty_final_answer_reasks_never_returns_empty_answered() -> None:
    result = await _loop(
        [{"kind": "final", "tool": None, "args_json": None, "answer": None}, _final("real answer")],
        [build_local_read_tool(DataStore())],
    ).run("q")
    assert (
        result.stop_reason == "answered"
        and result.answer == "real answer"
        and result.steps == ()
        and result.driver_turns == 2
    )


@pytest.mark.asyncio
async def test_null_tool_is_fail_closed() -> None:
    result = await _loop(
        [{"kind": "tool_call", "tool": None, "args_json": None, "answer": None}, _final("ok")],
        [build_local_read_tool(DataStore())],
    ).run("q")
    assert (
        result.steps[0].ok is False
        and "unknown tool" in result.steps[0].outcome
        and result.stop_reason == "answered"
        and result.answer == "ok"
    )
