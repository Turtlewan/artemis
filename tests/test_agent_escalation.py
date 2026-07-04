from __future__ import annotations

import dataclasses
import json
from collections.abc import Sequence
from typing import Any

import pytest

from artemis.agent.escalation import EscalatingLoop, _state_summary
from artemis.agent.loop import AgentLoop, LoopResult
from artemis.agent.tools import ToolRegistry, build_local_read_tool
from artemis.data.store import DataStore, Record
from artemis.ports.model import ModelPort
from artemis.types import Message, ModelResponse, Usage


def _resp(action: dict[str, Any]) -> ModelResponse:
    return ModelResponse(
        text=json.dumps(action),
        model_id="fake",
        structured=action,
        finish_reason="stop",
        usage=Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
    )


class ScriptedDriver:
    """Return one pre-built action dict per call as ModelResponse.structured."""

    def __init__(self, actions: list[dict[str, Any]], *, raise_on: int | None = None) -> None:
        self._actions = actions
        self._raise_on = raise_on
        self.calls = 0
        self.last_messages: list[Message] = []
        self.all_messages: list[list[Message]] = []

    async def complete(
        self,
        *,
        messages: Sequence[Message],
        model: str | None = None,
        response_schema: dict[Any, Any] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        _ = (model, response_schema, temperature, max_tokens)
        self.calls += 1
        self.last_messages = list(messages)
        self.all_messages.append(self.last_messages)
        if self._raise_on is not None and self.calls >= self._raise_on:
            raise RuntimeError("driver boom")
        return _resp(self._actions[min(self.calls - 1, len(self._actions) - 1)])


class ScriptedJudge:
    """Return one pre-built verdict dict per call as ModelResponse.structured."""

    def __init__(self, verdicts: list[dict[str, Any]], *, raise_on: int | None = None) -> None:
        self._verdicts = verdicts
        self._raise_on = raise_on
        self.calls = 0
        self.seen: list[str] = []

    async def complete(
        self,
        *,
        messages: Sequence[Message],
        model: str | None = None,
        response_schema: dict[Any, Any] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        _ = (model, response_schema, temperature, max_tokens)
        self.calls += 1
        self.seen.append("\n".join(m.content for m in messages))
        if self._raise_on is not None and self.calls >= self._raise_on:
            raise RuntimeError("judge boom")
        return _resp(self._verdicts[min(self.calls - 1, len(self._verdicts) - 1)])


def _tool_call(tool: str, **args: Any) -> dict[str, Any]:
    return {"kind": "tool_call", "tool": tool, "args_json": json.dumps(args), "answer": None}


def _final(answer: str) -> dict[str, Any]:
    return {"kind": "final", "tool": None, "args_json": None, "answer": answer}


def _verdict(*, grounded: bool, addresses: bool, reason: str = "r") -> dict[str, Any]:
    return {"grounded": grounded, "addresses_request": addresses, "reason": reason}


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
    driver: ModelPort, store: DataStore, *, judge: ModelPort | None = None, **kw: Any
) -> AgentLoop:
    return AgentLoop(
        driver=driver,
        tools=ToolRegistry([build_local_read_tool(store)]),
        judge=judge,
        **kw,
    )


def _stalling_actions() -> list[dict[str, Any]]:
    return [
        _tool_call("local_read", domain="cal", limit=100),
        _tool_call("local_read", domain="cal", limit=200),
        _tool_call("local_read", domain="cal", limit=300),
        _final("x"),
    ]


def _primary_for_trigger(trigger: str, store: DataStore) -> tuple[AgentLoop, ScriptedDriver]:
    if trigger == "spinning":
        _rec(store, "cal", "x")
        driver = ScriptedDriver([_tool_call("local_read", domain="cal")])
        return _loop(driver, store, budget=8, spin_threshold=3), driver
    if trigger == "thrashing":
        driver = ScriptedDriver([_tool_call("nope_a"), _tool_call("nope_b"), _tool_call("nope_c")])
        return _loop(driver, store, fail_streak_threshold=3), driver
    if trigger == "budget_exhausted":
        driver = ScriptedDriver(
            [
                _tool_call("local_read", domain="a"),
                _tool_call("local_read", domain="b"),
                _tool_call("local_read", domain="c"),
            ]
        )
        return _loop(driver, store, budget=3, spin_threshold=3), driver
    if trigger == "stalling":
        _rec(store, "cal", "lunch")
        driver = ScriptedDriver(_stalling_actions())
        return _loop(driver, store, budget=8, spin_threshold=3, stall_threshold=3), driver
    raise AssertionError(f"unknown trigger: {trigger}")


@pytest.mark.asyncio
async def test_stalling_detection_stops_differing_args_identical_observations() -> None:
    store = DataStore(":memory:")
    _rec(store, "cal", "lunch")
    driver = ScriptedDriver(_stalling_actions())

    result = await _loop(driver, store, budget=8, spin_threshold=3, stall_threshold=3).run("q")

    assert result.stop_reason == "stalling"
    assert len(result.steps) == 3


@pytest.mark.asyncio
async def test_stalling_below_threshold_does_not_trip() -> None:
    store = DataStore(":memory:")
    _rec(store, "cal", "lunch")
    driver = ScriptedDriver(
        [
            _tool_call("local_read", domain="cal", limit=100),
            _tool_call("local_read", domain="cal", limit=200),
            _final("ok"),
        ]
    )

    result = await _loop(driver, store, stall_threshold=3).run("q")

    assert result.stop_reason == "answered"
    assert result.answer == "ok"
    assert len(result.steps) == 2


@pytest.mark.asyncio
async def test_no_escalation_port_returns_primary_passthrough() -> None:
    store = DataStore(":memory:")
    _rec(store, "cal", "lunch")
    primary = _loop(
        ScriptedDriver([_tool_call("local_read", domain="cal")]),
        store,
        spin_threshold=3,
    )

    result = await EscalatingLoop(primary=primary).run("q")

    assert result.stop_reason == "spinning"
    assert result.escalated is False
    assert result.escalation_of is None


@pytest.mark.asyncio
@pytest.mark.parametrize("trigger", ["spinning", "thrashing", "budget_exhausted", "stalling"])
async def test_each_non_convergent_trigger_fires_escalation(trigger: str) -> None:
    store = DataStore(":memory:")
    primary, _primary_driver = _primary_for_trigger(trigger, store)
    esc_driver = ScriptedDriver([_final("escalated answer")])
    escalation = _loop(esc_driver, store)

    result = await EscalatingLoop(primary=primary, escalation=escalation).run("q")

    assert result.escalated is True
    assert result.escalation_of == trigger
    assert result.answer == "escalated answer"
    assert result.stop_reason == "answered"
    assert esc_driver.calls >= 1


@pytest.mark.asyncio
async def test_answered_does_not_trigger_escalation() -> None:
    store = DataStore(":memory:")
    esc_driver = ScriptedDriver([], raise_on=1)

    result = await EscalatingLoop(
        primary=_loop(ScriptedDriver([_final("done")]), store),
        escalation=_loop(esc_driver, store),
    ).run("q")

    assert result.escalated is False
    assert result.answer == "done"
    assert esc_driver.calls == 0


@pytest.mark.asyncio
async def test_flagged_answer_does_not_trigger_escalation() -> None:
    store = DataStore(":memory:")
    esc_driver = ScriptedDriver([], raise_on=1)
    judge = ScriptedJudge([_verdict(grounded=False, addresses=True, reason="nope")])

    result = await EscalatingLoop(
        primary=_loop(ScriptedDriver([_final("bad")]), store, judge=judge, budget=1),
        escalation=_loop(esc_driver, store),
    ).run("q")

    assert result.escalated is False
    assert result.verdict == "flagged"
    assert result.stop_reason == "answered"
    assert esc_driver.calls == 0


@pytest.mark.asyncio
async def test_driver_error_does_not_trigger_escalation() -> None:
    store = DataStore(":memory:")
    primary_driver = ScriptedDriver([_tool_call("local_read", domain="cal")], raise_on=1)
    esc_driver = ScriptedDriver([], raise_on=1)

    result = await EscalatingLoop(
        primary=_loop(primary_driver, store),
        escalation=_loop(esc_driver, store),
    ).run("q")

    assert result.escalated is False
    assert result.stop_reason == "driver_error"
    assert esc_driver.calls == 0


@pytest.mark.asyncio
async def test_state_summary_content_and_observation_exclusion() -> None:
    store = DataStore(":memory:")
    _rec(store, "cal", "SECRET_OBS_TEXT")
    primary_driver = ScriptedDriver([_tool_call("local_read", domain="cal")])
    esc_driver = ScriptedDriver([_final("ok")])

    await EscalatingLoop(
        primary=_loop(primary_driver, store, spin_threshold=3),
        escalation=_loop(esc_driver, store),
    ).run("what is on my calendar")

    handoff = esc_driver.last_messages[1].content
    assert "ORIGINAL REQUEST" in handoff
    assert "what is on my calendar" in handoff
    assert "tool=local_read" in handoff
    assert "ok=True" in handoff
    assert "spinning" in handoff
    assert "<<" in handoff
    assert "untrusted data" in handoff
    assert "SECRET_OBS_TEXT" not in handoff

    primary_result = await _loop(
        ScriptedDriver([_tool_call("local_read", domain="cal")]),
        store,
        spin_threshold=3,
    ).run("what is on my calendar")
    direct = _state_summary("what is on my calendar", primary_result)
    assert "ORIGINAL REQUEST" in direct
    assert "tool=local_read" in direct
    assert "ok=True" in direct
    assert "spinning" in direct
    assert "<<" in direct
    assert "untrusted data" in direct
    assert "SECRET_OBS_TEXT" not in direct


@pytest.mark.asyncio
async def test_escalated_failure_returns_partial_and_no_third_pass() -> None:
    store = DataStore(":memory:")
    _rec(store, "cal", "lunch")
    primary_driver = ScriptedDriver([_tool_call("local_read", domain="cal")])
    esc_driver = ScriptedDriver([_tool_call("local_read", domain="cal")])

    result = await EscalatingLoop(
        primary=_loop(primary_driver, store, spin_threshold=3),
        escalation=_loop(esc_driver, store, spin_threshold=3),
    ).run("q")

    assert result.escalated is True
    assert result.escalation_of == "spinning"
    assert result.stop_reason == "spinning"
    assert esc_driver.calls == 3


@pytest.mark.asyncio
async def test_judge_runs_in_escalated_pass() -> None:
    store = DataStore(":memory:")
    primary = _loop(
        ScriptedDriver(
            [
                _tool_call("local_read", domain="a"),
                _tool_call("local_read", domain="b"),
                _tool_call("local_read", domain="c"),
            ]
        ),
        store,
        budget=3,
    )
    judge = ScriptedJudge([_verdict(grounded=True, addresses=True, reason="ok")])

    result = await EscalatingLoop(
        primary=primary,
        escalation=_loop(ScriptedDriver([_final("verified")]), store, judge=judge),
    ).run("q")

    assert result.escalated is True
    assert result.verdict == "passed"
    assert judge.calls == 1


@pytest.mark.asyncio
async def test_telemetry_is_per_pass_with_primary_carry() -> None:
    store = DataStore(":memory:")
    primary = _loop(
        ScriptedDriver(
            [
                _tool_call("local_read", domain="a"),
                _tool_call("local_read", domain="b"),
                _tool_call("local_read", domain="c"),
            ]
        ),
        store,
        budget=3,
    )

    result = await EscalatingLoop(
        primary=primary,
        escalation=_loop(ScriptedDriver([_final("x")]), store),
    ).run("q")

    assert result.driver_turns == 1
    assert result.primary_driver_turns == 3
    assert result.primary_driver_tokens_total == 0
    assert result.escalated is True
    assert result.escalation_of == "budget_exhausted"


def test_loop_result_escalation_fields_default_and_frozen() -> None:
    result = dataclasses.replace(
        LoopResult(
            answer="x",
            steps=(),
            stop_reason="answered",
            driver_turns=1,
            driver_tokens_total=0,
        ),
        escalated=True,
        escalation_of="spinning",
    )
    plain = LoopResult(
        answer="a",
        steps=(),
        stop_reason="answered",
        driver_turns=0,
        driver_tokens_total=0,
    )

    assert result.escalated is True
    assert result.escalation_of == "spinning"
    assert plain.escalated is False
    assert plain.escalation_of is None
    assert plain.primary_driver_turns == 0
    assert plain.primary_driver_tokens_total == 0
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(result, "escalated", True)
