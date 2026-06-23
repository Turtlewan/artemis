"""Tests for the time tool and heartbeat skeleton (M1-d)."""

from __future__ import annotations

import asyncio
import re
from datetime import datetime

import pytest

from artemis.heartbeat import HEARTBEAT_OK, Heartbeat
from artemis.manifest import ActionRisk, DataScope
from artemis.proactive.hook_types import TickResult
from artemis.tools.time_tool import TimeArgs, get_current_time, manifest

# ── Time tool tests ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_time_tool_basic() -> None:
    """get_current_time returns a parseable ISO timestamp with no args."""
    result = await get_current_time(TimeArgs())
    assert re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", result.iso)
    # The parsed timestamp should not raise
    match = re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", result.iso)
    assert match is not None
    datetime.fromisoformat(match.group())


@pytest.mark.asyncio
async def test_time_tool_with_tz() -> None:
    """get_current_time respects an explicit timezone."""
    result = await get_current_time(TimeArgs(tz="Asia/Singapore"))
    assert result.tz == "Asia/Singapore"
    assert re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", result.iso)


@pytest.mark.asyncio
async def test_time_tool_invalid_tz() -> None:
    """An invalid timezone raises ValueError."""
    with pytest.raises(ValueError, match="Unknown timezone"):
        await get_current_time(TimeArgs(tz="Not/AZone"))


# ── Manifest contract tests ──────────────────────────────────────────────────


def test_manifest_name() -> None:
    """manifest().name is 'time'."""
    m = manifest()
    assert m.name == "time"


def test_manifest_tool_action_risk() -> None:
    """get_current_time has NO_DATA risk."""
    tool = manifest().tools[0]
    assert tool.action_risk is ActionRisk.NO_DATA


def test_manifest_tool_args_schema() -> None:
    """Tool's args_schema is TimeArgs."""
    tool = manifest().tools[0]
    assert tool.args_schema is TimeArgs


def test_manifest_tool_callable() -> None:
    """The callable_ref is callable (async functions are callable)."""
    tool = manifest().tools[0]
    assert callable(tool.callable_ref)


def test_manifest_tool_bare_name() -> None:
    """The tool name is the bare 'get_current_time', not 'time.get_current_time'."""
    tool = manifest().tools[0]
    assert tool.name == "get_current_time"


def test_manifest_data_scope() -> None:
    """DataScope.SHARED maps to scope 'general' at storage."""
    m = manifest()
    assert m.data_scope is DataScope.SHARED
    # Document the correspondence in the time_tool.py module docstring
    assert m.data_scope.value in ("shared",)


# ── Heartbeat tests ──────────────────────────────────────────────────────────


def test_heartbeat_tick_returns_ok() -> None:
    """Heartbeat().tick() returns HEARTBEAT_OK."""
    hb = Heartbeat()
    assert hb.tick() == HEARTBEAT_OK


@pytest.mark.asyncio
async def test_heartbeat_run_forever_max_ticks() -> None:
    """run_forever with max_ticks completes exactly that many ticks."""
    ticks: list[TickResult] = []

    class SpyHeartbeat(Heartbeat):
        def tick(self) -> TickResult:
            result = super().tick()
            ticks.append(result)
            return result

    await SpyHeartbeat(interval_seconds=0.0).run_forever(max_ticks=3)
    assert len(ticks) == 3
    assert all(t == HEARTBEAT_OK for t in ticks)


@pytest.mark.asyncio
async def test_heartbeat_cancellation() -> None:
    """run_forever raises CancelledError when cancelled mid-loop."""
    hb = Heartbeat(interval_seconds=999.0)  # very long sleep

    async def cancel_soon() -> None:
        await asyncio.sleep(0.01)
        task.cancel()

    task = asyncio.create_task(hb.run_forever())
    asyncio.create_task(cancel_soon())

    with pytest.raises(asyncio.CancelledError):
        await task
