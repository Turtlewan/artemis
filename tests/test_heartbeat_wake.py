"""Tests for the M6 wake trigger branch in the heartbeat scheduler."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from datetime import datetime

import pytest
from pydantic import ValidationError

from artemis.heartbeat import Heartbeat
from artemis.identity.key_provider import FakeKeyProvider
from artemis.manifest import DataScope, HookSpec, ModuleManifest
from artemis.ports.types import Vector
from artemis.proactive.hook_types import Hit, HookResult
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


def test_wake_path_fires_once_after_note_wake() -> None:
    calls = 0
    wall = [datetime(2026, 6, 24, 7, 0)]

    def check() -> HookResult:
        nonlocal calls
        calls += 1
        return HookResult.of({"wake": True})

    hook = HookSpec(name="morning", wake=True, check_ref=check)
    heartbeat = Heartbeat(
        _registry_with(_manifest(hooks=[hook])),
        _key_provider(),
        wall_clock=lambda: wall[0],
    )

    assert heartbeat.tick().hits == ()

    wake_time = datetime(2026, 6, 24, 7, 5)
    wall[0] = wake_time
    heartbeat.note_wake(wake_time)
    result = heartbeat.tick()
    second = heartbeat.tick()

    assert calls == 1
    assert len(result.hits) == 1
    assert result.hits[0].hook_name == "morning"
    assert second.hits == ()


def test_fallback_path_fires_once_when_no_wake_arrives() -> None:
    calls = 0
    wall = [datetime(2026, 6, 24, 7, 59)]

    def check() -> HookResult:
        nonlocal calls
        calls += 1
        return HookResult.of({"fallback": True})

    hook = HookSpec(name="fallback", wake=True, wake_fallback_time="08:00", check_ref=check)
    heartbeat = Heartbeat(
        _registry_with(_manifest(hooks=[hook])),
        _key_provider(),
        wall_clock=lambda: wall[0],
    )

    assert heartbeat.tick().hits == ()

    wall[0] = datetime(2026, 6, 24, 8, 1)
    result = heartbeat.tick()
    second = heartbeat.tick()

    assert calls == 1
    assert len(result.hits) == 1
    assert result.hits[0].hook_name == "fallback"
    assert second.hits == ()


def test_wake_and_fallback_never_both_fire_same_day() -> None:
    calls = 0
    wall = [datetime(2026, 6, 24, 7, 5)]

    def check() -> HookResult:
        nonlocal calls
        calls += 1
        return HookResult.of({"digest": True})

    hook = HookSpec(name="digest", wake=True, wake_fallback_time="08:00", check_ref=check)
    heartbeat = Heartbeat(
        _registry_with(_manifest(hooks=[hook])),
        _key_provider(),
        wall_clock=lambda: wall[0],
    )

    heartbeat.note_wake(wall[0])
    wake_result = heartbeat.tick()
    wall[0] = datetime(2026, 6, 24, 8, 1)
    fallback_result = heartbeat.tick()

    assert calls == 1
    assert len(wake_result.hits) == 1
    assert fallback_result.hits == ()


def test_wake_day_gate_skips_and_admits_matching_weekday() -> None:
    calls = 0
    wall = [datetime(2026, 6, 24, 7, 5)]  # Wednesday

    def check() -> HookResult:
        nonlocal calls
        calls += 1
        return HookResult.of({"review": True})

    hook = HookSpec(name="review", wake=True, wake_day_gate=5, check_ref=check)
    heartbeat = Heartbeat(
        _registry_with(_manifest(hooks=[hook])),
        _key_provider(),
        wall_clock=lambda: wall[0],
    )

    heartbeat.note_wake(wall[0])
    wednesday_result = heartbeat.tick()
    wall[0] = datetime(2026, 6, 27, 7, 5)  # Saturday
    heartbeat.note_wake(wall[0])
    saturday_result = heartbeat.tick()

    assert wednesday_result.hits == ()
    assert calls == 1
    assert len(saturday_result.hits) == 1
    assert saturday_result.hits[0].hook_name == "review"


def test_wake_latch_resets_across_days() -> None:
    calls = 0
    wall = [datetime(2026, 6, 24, 7, 5)]

    def check() -> HookResult:
        nonlocal calls
        calls += 1
        return HookResult.of({"wake": True})

    hook = HookSpec(name="daily", wake=True, check_ref=check)
    heartbeat = Heartbeat(
        _registry_with(_manifest(hooks=[hook])),
        _key_provider(),
        wall_clock=lambda: wall[0],
    )

    heartbeat.note_wake(wall[0])
    first = heartbeat.tick()
    wall[0] = datetime(2026, 6, 25, 7, 5)
    heartbeat.note_wake(wall[0])
    second = heartbeat.tick()

    assert calls == 2
    assert len(first.hits) == 1
    assert len(second.hits) == 1
    assert heartbeat._wake_date == wall[0].date()


def test_wake_tier1_hook_skips_while_locked_then_runs_when_unlocked() -> None:
    calls = 0
    queued: list[Hit] = []
    wall = [datetime(2026, 6, 24, 7, 5)]

    def check() -> HookResult:
        nonlocal calls
        calls += 1
        return HookResult.of({"private": True})

    hook = HookSpec(name="private", wake=True, tier=1, check_ref=check)
    registry = _registry_with(_manifest(name="ownerdata", hooks=[hook]))
    locked = Heartbeat(
        registry,
        _key_provider(owner_unlocked=False),
        wall_clock=lambda: wall[0],
        tier1_sink=queued.append,
    )

    locked.note_wake(wall[0])
    locked_result = locked.tick()

    assert calls == 0
    assert locked_result.hits == ()
    assert locked_result.tier1_skipped == ("ownerdata.private",)
    assert len(queued) == 1

    unlocked = Heartbeat(registry, _key_provider(owner_unlocked=True), wall_clock=lambda: wall[0])
    unlocked.note_wake(wall[0])
    unlocked_result = unlocked.tick()

    assert calls == 1
    assert len(unlocked_result.hits) == 1


def test_wake_validator_rejects_multiple_triggers_and_gate_without_wake() -> None:
    with pytest.raises(ValidationError, match="exactly one trigger"):
        HookSpec(name="bad", wake=True, interval_seconds=60, check_ref=HookResult.miss)

    with pytest.raises(ValidationError, match="require wake=True"):
        HookSpec(name="bad", interval_seconds=60, wake_day_gate=5, check_ref=HookResult.miss)

    with pytest.raises(ValidationError, match="range 0 through 6"):
        HookSpec(name="bad", wake=True, wake_day_gate=9, check_ref=HookResult.miss)

    hook = HookSpec(
        name="good",
        wake=True,
        wake_fallback_time="08:00",
        wake_day_gate=5,
        check_ref=HookResult.miss,
    )

    assert hook.wake is True
    assert hook.wake_fallback_time == "08:00"
    assert hook.wake_day_gate == 5
