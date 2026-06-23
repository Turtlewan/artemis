"""Tests for the M6-a heartbeat scheduler and hook contract."""

from __future__ import annotations

import asyncio
import hashlib
import math
from collections.abc import Sequence
from datetime import datetime

import pytest

from artemis.heartbeat import HEARTBEAT_OK, Heartbeat
from artemis.identity.key_provider import FakeKeyProvider
from artemis.manifest import DataScope, HookSpec, ModuleManifest
from artemis.ports.types import Vector
from artemis.proactive.hook_types import Hit, HookResult, TickResult
from artemis.registry import ToolRegistry


class FakeEmbedder:
    """Deterministic no-network embedder for ``ToolRegistry`` construction."""

    DIMENSION = 8

    @property
    def dimension(self) -> int:
        return self.DIMENSION

    async def embed_documents(self, texts: Sequence[str]) -> list[Vector]:
        return [self._hash_vec(text) for text in texts]

    async def embed_query(self, query: str) -> Vector:
        return self._hash_vec(query)

    def _hash_vec(self, text: str) -> Vector:
        vec = [0.0] * self.DIMENSION
        for word in text.lower().split():
            bucket = hashlib.sha256(word.encode()).digest()[0] % self.DIMENSION
            vec[bucket] += 1.0
        norm = math.sqrt(sum(value * value for value in vec))
        return [value / norm for value in vec] if norm > 0 else vec


def _registry_with(manifest: ModuleManifest) -> ToolRegistry:
    registry = ToolRegistry(FakeEmbedder())
    registry.register(manifest)
    return registry


def _manifest(
    *,
    name: str = "demo",
    data_scope: DataScope = DataScope.OWNER_PRIVATE,
    hooks: list[HookSpec],
) -> ModuleManifest:
    return ModuleManifest(
        name=name,
        version="0.1.0",
        description="Demo module.",
        data_scope=data_scope,
        proactive_hooks=hooks,
    )


def _key_provider(*, owner_unlocked: bool = True) -> FakeKeyProvider:
    return FakeKeyProvider(owner_unlocked=owner_unlocked)


def test_silent_success_returns_heartbeat_ok_without_on_hits() -> None:
    on_hits: list[TickResult] = []

    async def _record(r: TickResult) -> None:
        on_hits.append(r)

    hook = HookSpec(name="miss", interval_seconds=60, check_ref=HookResult.miss)
    heartbeat = Heartbeat(
        _registry_with(_manifest(hooks=[hook])),
        _key_provider(),
        on_hits=_record,
        clock=lambda: 0.0,
    )

    result = heartbeat.tick()

    assert result.summary == HEARTBEAT_OK
    assert result.is_silent_success is True
    assert result.hits == ()
    assert on_hits == []


def test_interval_due_evaluation_uses_fake_clock() -> None:
    calls = 0
    now = [0.0]

    def check() -> HookResult:
        nonlocal calls
        calls += 1
        return HookResult.miss()

    hook = HookSpec(name="interval", interval_seconds=60, check_ref=check)
    heartbeat = Heartbeat(
        _registry_with(_manifest(hooks=[hook])),
        _key_provider(),
        clock=lambda: now[0],
    )

    heartbeat.tick()
    now[0] += 30.0
    heartbeat.tick()
    now[0] += 31.0
    heartbeat.tick()

    assert calls == 2


def test_hit_collection_preserves_payload() -> None:
    def check() -> HookResult:
        return HookResult.of({"budget_pct": 92}, dedup_value="2026-06-04")

    hook = HookSpec(
        name="budget",
        interval_seconds=60,
        urgency="high",
        needs_llm=True,
        dedup_key="budget",
        check_ref=check,
    )
    heartbeat = Heartbeat(
        _registry_with(_manifest(name="finance", hooks=[hook])),
        _key_provider(),
        clock=lambda: 0.0,
    )

    result = heartbeat.tick()

    assert result.summary != HEARTBEAT_OK
    assert len(result.hits) == 1
    hit = result.hits[0]
    assert hit.module == "finance"
    assert hit.hook_name == "budget"
    assert hit.urgency == "high"
    assert hit.needs_llm is True
    assert hit.result.payload["budget_pct"] == 92


async def test_run_forever_fires_on_hits_on_hit() -> None:
    received: list[TickResult] = []

    def check() -> HookResult:
        return HookResult.of({"budget_pct": 92}, dedup_value="2026-06-04")

    async def on_hits(result: TickResult) -> None:
        received.append(result)

    hook = HookSpec(
        name="budget",
        interval_seconds=60,
        urgency="high",
        needs_llm=True,
        dedup_key="budget",
        check_ref=check,
    )
    heartbeat = Heartbeat(
        _registry_with(_manifest(name="finance", hooks=[hook])),
        _key_provider(),
        on_hits=on_hits,
        clock=lambda: 0.0,
    )

    await heartbeat.run_forever(max_ticks=1, sleep_seconds=0.0)

    assert len(received) == 1
    result = received[0]
    assert len(result.hits) == 1
    hit = result.hits[0]
    assert hit.result.payload["budget_pct"] == 92
    assert hit.hook_name == "budget"
    assert hit.module == "finance"
    assert hit.urgency == "high"
    assert hit.needs_llm is True


def test_daily_cron_fires_once_per_day_and_after_slipped_tick() -> None:
    calls = 0
    wall = [datetime(2026, 6, 4, 8, 30)]

    def check() -> HookResult:
        nonlocal calls
        calls += 1
        return HookResult.miss()

    hook = HookSpec(name="briefing", cron="30 8 * * *", check_ref=check)
    heartbeat = Heartbeat(
        _registry_with(_manifest(hooks=[hook])),
        _key_provider(),
        wall_clock=lambda: wall[0],
    )

    heartbeat.tick()
    heartbeat.tick()
    wall[0] = datetime(2026, 6, 5, 8, 31)
    heartbeat.tick()
    wall[0] = datetime(2026, 6, 6, 8, 30)
    heartbeat.tick()

    assert calls == 3


def test_unsupported_cron_raises_at_construction() -> None:
    hook = HookSpec(name="bad", cron="*/5 * * * *", check_ref=HookResult.miss)
    registry = _registry_with(_manifest(hooks=[hook]))

    with pytest.raises(ValueError, match="unsupported cron expression"):
        Heartbeat(registry, _key_provider())


def test_tier0_hook_runs_while_owner_locked() -> None:
    calls = 0

    def check() -> HookResult:
        nonlocal calls
        calls += 1
        return HookResult.miss()

    hook = HookSpec(name="shared", interval_seconds=60, tier=0, check_ref=check)
    heartbeat = Heartbeat(
        _registry_with(_manifest(data_scope=DataScope.SHARED, hooks=[hook])),
        _key_provider(owner_unlocked=False),
    )

    heartbeat.tick()

    assert calls == 1


def test_tier1_hook_skips_and_queues_while_locked_then_runs_when_unlocked() -> None:
    calls = 0
    queued: list[Hit] = []

    def check() -> HookResult:
        nonlocal calls
        calls += 1
        return HookResult.of({"ready": True})

    hook = HookSpec(name="private", interval_seconds=60, tier=1, check_ref=check)
    registry = _registry_with(_manifest(name="ownerdata", hooks=[hook]))

    locked = Heartbeat(registry, _key_provider(owner_unlocked=False), tier1_sink=queued.append)
    locked_result = locked.tick()

    assert calls == 0
    assert locked_result.tier1_skipped == ("ownerdata.private",)
    assert len(queued) == 1
    assert queued[0].module == "ownerdata"
    assert queued[0].hook_name == "private"

    unlocked = Heartbeat(registry, _key_provider(owner_unlocked=True))
    unlocked_result = unlocked.tick()

    assert calls == 1
    assert len(unlocked_result.hits) == 1


def test_raising_hook_degrades_and_other_hooks_still_run() -> None:
    calls: list[str] = []

    def raises() -> HookResult:
        calls.append("raises")
        raise RuntimeError("boom")

    def succeeds() -> HookResult:
        calls.append("succeeds")
        return HookResult.of({"ok": True})

    registry = _registry_with(
        _manifest(
            hooks=[
                HookSpec(name="bad", interval_seconds=60, check_ref=raises),
                HookSpec(name="good", interval_seconds=60, check_ref=succeeds),
            ]
        )
    )
    heartbeat = Heartbeat(registry, _key_provider())

    result = heartbeat.tick()

    assert calls == ["raises", "succeeds"]
    assert len(result.hits) == 1
    assert result.hits[0].hook_name == "good"


def test_next_due_advances_on_exception_to_avoid_retry_storm() -> None:
    calls = 0
    now = [0.0]

    def raises() -> HookResult:
        nonlocal calls
        calls += 1
        raise RuntimeError("boom")

    hook = HookSpec(name="bad", interval_seconds=60, check_ref=raises)
    heartbeat = Heartbeat(
        _registry_with(_manifest(hooks=[hook])),
        _key_provider(),
        clock=lambda: now[0],
    )

    heartbeat.tick()
    now[0] += 30.0
    heartbeat.tick()
    now[0] += 31.0
    heartbeat.tick()

    assert calls == 2


async def test_on_hits_exception_does_not_kill_run_forever() -> None:
    def check() -> HookResult:
        return HookResult.of({"ok": True})

    async def on_hits(_result: TickResult) -> None:
        raise RuntimeError("handler failed")

    hook = HookSpec(name="hit", interval_seconds=60, check_ref=check)
    heartbeat = Heartbeat(
        _registry_with(_manifest(hooks=[hook])),
        _key_provider(),
        on_hits=on_hits,
    )

    await heartbeat.run_forever(max_ticks=1, sleep_seconds=0.0)


@pytest.mark.asyncio
async def test_run_forever_cancels_between_ticks() -> None:
    calls: list[str] = []

    def check() -> HookResult:
        calls.extend(["start", "end"])
        return HookResult.miss()

    hook = HookSpec(name="tick", interval_seconds=60, check_ref=check)
    heartbeat = Heartbeat(_registry_with(_manifest(hooks=[hook])), _key_provider())

    task = asyncio.create_task(heartbeat.run_forever(sleep_seconds=999.0))
    await asyncio.sleep(0)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert calls == ["start", "end"]


@pytest.mark.asyncio
async def test_pre_tick_steps_run_before_tick() -> None:
    calls: list[str] = []

    async def step() -> None:
        calls.append("step")

    def check() -> HookResult:
        calls.append("tick")
        return HookResult.miss()

    hook = HookSpec(name="tick", interval_seconds=60, check_ref=check)
    heartbeat = Heartbeat(
        _registry_with(_manifest(hooks=[hook])),
        _key_provider(),
        pre_tick_steps=[step],
    )

    await heartbeat.run_forever(max_ticks=1, sleep_seconds=0.0)

    assert calls == ["step", "tick"]


@pytest.mark.asyncio
async def test_raising_pre_tick_step_does_not_suppress_later_steps_or_tick() -> None:
    calls: list[str] = []

    async def raising_step() -> None:
        calls.append("raising")
        raise RuntimeError("pre-step failed")

    async def good_step() -> None:
        calls.append("good")

    def check() -> HookResult:
        calls.append("tick")
        return HookResult.miss()

    hook = HookSpec(name="tick", interval_seconds=60, check_ref=check)
    heartbeat = Heartbeat(
        _registry_with(_manifest(hooks=[hook])),
        _key_provider(),
        pre_tick_steps=[raising_step, good_step],
    )

    await heartbeat.run_forever(max_ticks=1, sleep_seconds=0.0)

    assert calls == ["raising", "good", "tick"]
