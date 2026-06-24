from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar, cast

import pytest

from artemis.config import Settings
from artemis.heartbeat import Heartbeat
from artemis.identity.key_provider import FakeKeyProvider
from artemis.identity.scope import OWNER_PRIVATE
from artemis.manifest import ModuleManifest
from artemis.modules.productivity import hooks as productivity_hooks
from artemis.modules.productivity.hooks import (
    build_productivity_hooks,
    make_morning_digest_check,
    make_week_ahead_check,
    make_weekend_review_check,
)
from artemis.modules.productivity.manifest import projects_manifest, tasks_manifest
from artemis.modules.productivity.store import ProductivityStore
from artemis.ports.types import Vector
from artemis.proactive.hook_types import HookResult
from artemis.registry import ToolRegistry


class FakeEmbedder:
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


class FrozenDateTime:
    frozen_now: ClassVar[datetime] = datetime(2026, 6, 28, 19, 0, tzinfo=UTC)

    @classmethod
    def now(cls, tz: timezone | None = None) -> datetime:
        if tz is None:
            return cls.frozen_now.replace(tzinfo=None)
        return cls.frozen_now.astimezone(tz)


@pytest.fixture
def store(tmp_path: Path) -> ProductivityStore:
    return ProductivityStore(
        Settings(data_root=tmp_path, slot="dev"),
        FakeKeyProvider({OWNER_PRIVATE: b"0" * 32}, owner_unlocked=True),
    )


def test_morning_digest_misses_without_tasks(store: ProductivityStore) -> None:
    result = make_morning_digest_check(store)()

    assert result.hit is False


def test_morning_digest_folds_overdue_into_one_safe_payload(store: ProductivityStore) -> None:
    today = datetime.now(UTC).date()
    today_ids = {
        store.create_task("Today one", due_at=today.isoformat()),
        store.create_task("Today two", due_at=today.isoformat()),
    }
    overdue_id = store.create_task("Overdue", due_at=(today - timedelta(days=1)).isoformat())

    result = make_morning_digest_check(store)()

    assert result.hit is True
    assert result.payload["today_count"] == 2
    assert result.payload["overdue_count"] == 1
    assert set(cast(list[str], result.payload["today_task_ids"])) == today_ids
    assert result.payload["overdue_task_ids"] == [overdue_id]
    _assert_safe_payload(result.payload)


def test_weekend_review_misses_without_projects_or_overdue(store: ProductivityStore) -> None:
    result = make_weekend_review_check(store)()

    assert result.hit is False


def test_weekend_review_payload_has_no_area_count(store: ProductivityStore) -> None:
    project_ids = {store.create_project("One"), store.create_project("Two")}

    result = make_weekend_review_check(store)()

    assert result.hit is True
    assert result.payload["project_count"] == 2
    assert set(cast(list[str], result.payload["project_ids"])) == project_ids
    assert result.dedup_value is not None
    assert _is_iso_week(result.dedup_value)
    _assert_safe_payload(result.payload)


def test_week_ahead_misses_on_non_sunday_even_with_content(
    store: ProductivityStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    _freeze_hooks_time(monkeypatch, datetime(2026, 6, 24, 19, 0, tzinfo=UTC))
    store.create_task("Soon", due_at=(datetime.now(UTC).date() + timedelta(days=1)).isoformat())

    result = make_week_ahead_check(store)()

    assert result.hit is False


def test_week_ahead_hits_on_sunday_with_safe_payload(
    store: ProductivityStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    _freeze_hooks_time(monkeypatch, datetime(2026, 6, 28, 19, 0, tzinfo=UTC))
    start = datetime.now(UTC).date()
    task_ids = {
        store.create_task("Soon one", due_at=(start + timedelta(days=1)).isoformat()),
        store.create_task("Soon two", due_at=(start + timedelta(days=2)).isoformat()),
        store.create_task("Soon three", due_at=(start + timedelta(days=3)).isoformat()),
    }

    result = make_week_ahead_check(store)()

    assert result.hit is True
    assert result.payload["upcoming_count"] == 3
    assert set(cast(list[str], result.payload["upcoming_task_ids"])) == task_ids
    assert result.dedup_value is not None
    assert _is_iso_week(result.dedup_value)
    _assert_safe_payload(result.payload)


def test_build_productivity_hooks_constructs_wake_and_cron_specs(
    store: ProductivityStore,
) -> None:
    hooks = build_productivity_hooks(store)
    by_name = {hook.name: hook for hook in hooks}

    assert set(by_name) == {
        "productivity_morning_digest",
        "productivity_weekend_review",
        "productivity_week_ahead",
    }
    assert all(hook.tier == 1 for hook in hooks)
    assert all(hook.needs_llm is True for hook in hooks)
    assert "productivity_overdue_nudge" not in by_name

    morning = by_name["productivity_morning_digest"]
    assert morning.wake is True
    assert morning.wake_fallback_time == "08:00"
    assert morning.cron is None
    assert morning.interval_seconds is None

    weekend = by_name["productivity_weekend_review"]
    assert weekend.wake is True
    assert weekend.wake_day_gate == 5

    week_ahead = by_name["productivity_week_ahead"]
    assert week_ahead.cron == "0 19 * * *"
    assert week_ahead.wake is False
    Heartbeat(_registry_with(tasks_manifest(store)), _key_provider())


def test_morning_digest_fires_on_wake_once_and_via_fallback(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    store.create_task("Today", due_at=datetime.now(UTC).date().isoformat())
    wall = [datetime(2026, 6, 24, 7, 0)]
    heartbeat = Heartbeat(
        _registry_with(tasks_manifest(store)),
        _key_provider(),
        wall_clock=lambda: wall[0],
    )

    assert heartbeat.tick().hits == ()
    wall[0] = datetime(2026, 6, 24, 7, 5)
    heartbeat.note_wake(wall[0])
    wake_result = heartbeat.tick()
    second_result = heartbeat.tick()

    assert [hit.hook_name for hit in wake_result.hits] == ["productivity_morning_digest"]
    assert second_result.hits == ()

    fallback_store = _store(tmp_path / "fallback")
    fallback_store.create_task("Fallback", due_at=datetime.now(UTC).date().isoformat())
    fallback_wall = [datetime(2026, 6, 25, 8, 1)]
    fallback = Heartbeat(
        _registry_with(tasks_manifest(fallback_store)),
        _key_provider(),
        wall_clock=lambda: fallback_wall[0],
    )

    fallback_result = fallback.tick()
    fallback_second = fallback.tick()

    assert [hit.hook_name for hit in fallback_result.hits] == ["productivity_morning_digest"]
    assert fallback_second.hits == ()


def test_weekend_review_wake_day_gate(store: ProductivityStore) -> None:
    store.create_project("Active")
    wall = [datetime(2026, 6, 24, 7, 5)]  # Wednesday
    heartbeat = Heartbeat(
        _registry_with(tasks_manifest(store)),
        _key_provider(),
        wall_clock=lambda: wall[0],
    )

    heartbeat.note_wake(wall[0])
    wednesday = heartbeat.tick()
    wall[0] = datetime(2026, 6, 27, 7, 5)  # Saturday
    heartbeat.note_wake(wall[0])
    saturday = heartbeat.tick()

    assert "productivity_weekend_review" not in {hit.hook_name for hit in wednesday.hits}
    assert "productivity_weekend_review" in {hit.hook_name for hit in saturday.hits}


def test_week_ahead_sunday_gate_at_cron_time(
    store: ProductivityStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    store.create_task("Soon", due_at=(datetime.now(UTC).date() + timedelta(days=1)).isoformat())
    wall = [datetime(2026, 6, 24, 19, 0)]  # Wednesday
    _freeze_hooks_time(monkeypatch, wall[0].replace(tzinfo=UTC))
    heartbeat = Heartbeat(
        _registry_with(tasks_manifest(store)),
        _key_provider(),
        wall_clock=lambda: wall[0],
    )

    assert heartbeat.tick().hits == ()

    sunday_store = _store(Path(str(store.settings.data_root)) / "sunday")
    sunday_store.create_task(
        "Soon",
        due_at=(datetime.now(UTC).date() + timedelta(days=1)).isoformat(),
    )
    wall[0] = datetime(2026, 6, 28, 19, 0)
    _freeze_hooks_time(monkeypatch, wall[0].replace(tzinfo=UTC))
    sunday = Heartbeat(
        _registry_with(tasks_manifest(sunday_store)),
        _key_provider(),
        wall_clock=lambda: wall[0],
    )

    result = sunday.tick()

    assert [hit.hook_name for hit in result.hits] == ["productivity_week_ahead"]


def test_tier1_wake_hook_queues_when_locked_without_calling_check(store: ProductivityStore) -> None:
    called = False
    manifest = tasks_manifest(store)
    wall = [datetime(2026, 6, 24, 7, 5)]

    def _mark_called() -> HookResult:
        nonlocal called
        called = True
        raise AssertionError("check_ref should not run while locked")

    for hook in manifest.proactive_hooks:
        if hook.name == "productivity_morning_digest":
            hook.check_ref = _mark_called

    heartbeat = Heartbeat(
        _registry_with(manifest),
        FakeKeyProvider(owner_unlocked=False),
        wall_clock=lambda: wall[0],
    )

    heartbeat.note_wake(wall[0])
    result = heartbeat.tick()

    assert called is False
    assert "tasks.productivity_morning_digest" in result.tier1_skipped


def test_scope_locked_degrades_to_miss(tmp_path: Path) -> None:
    locked = ProductivityStore(
        Settings(data_root=tmp_path, slot="dev"),
        FakeKeyProvider(owner_unlocked=False),
    )

    result = make_morning_digest_check(locked)()

    assert result.hit is False


def test_manifest_integration(store: ProductivityStore) -> None:
    tasks = tasks_manifest(store)
    projects = projects_manifest(store)

    assert len(tasks.proactive_hooks) == 3
    assert projects.proactive_hooks == []


def _store(tmp_path: Path) -> ProductivityStore:
    return ProductivityStore(
        Settings(data_root=tmp_path, slot="dev"),
        FakeKeyProvider({OWNER_PRIVATE: b"0" * 32}, owner_unlocked=True),
    )


def _key_provider(*, owner_unlocked: bool = True) -> FakeKeyProvider:
    return FakeKeyProvider({OWNER_PRIVATE: b"0" * 32}, owner_unlocked=owner_unlocked)


def _registry_with(manifest: ModuleManifest) -> ToolRegistry:
    registry = ToolRegistry(FakeEmbedder())
    registry.register(manifest)
    return registry


def _freeze_hooks_time(monkeypatch: pytest.MonkeyPatch, value: datetime) -> None:
    FrozenDateTime.frozen_now = value
    monkeypatch.setattr(
        productivity_hooks,
        "datetime",
        SimpleNamespace(datetime=FrozenDateTime, UTC=UTC),
    )


def _assert_safe_payload(payload: dict[str, object]) -> None:
    forbidden = {"title", "notes", "raw_context", "area_count"}
    assert forbidden.isdisjoint(payload)


def _is_iso_week(value: str) -> bool:
    year, week = value.split("-W")
    return len(year) == 4 and year.isdigit() and len(week) == 2 and week.isdigit()
