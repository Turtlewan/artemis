from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

from artemis.config import Settings
from artemis.heartbeat import Heartbeat
from artemis.identity.key_provider import FakeKeyProvider, ScopeLockedError
from artemis.identity.scope import OWNER_PRIVATE
from artemis.manifest import DataScope, HookSpec, ModuleManifest
from artemis.modules.calendar.cache import CachedEvent, CalendarSyncEngine, EventCacheStore
from artemis.modules.calendar.client import FakeCalendarClient
from artemis.modules.calendar.hooks import (
    _intentions_projection_stub,
    _quarantine_stub,
    build_calendar_hooks,
    make_change_detection_check,
    make_conflict_alert_check,
    make_daily_briefing_check,
    make_free_gap_check,
    make_prep_nudge_check,
    make_unanswered_invite_check,
    make_upcoming_reminder_check,
)
from artemis.modules.calendar.manifest import make_calendar_overlay_manifest
from artemis.modules.calendar.overlay import (
    OverlayStore,
    OverlayTools,
    ProposalRow,
    approve_proposal,
    hold_tentative,
    list_proposals,
    reject_proposal,
)
from artemis.modules.calendar.preferences import CalPrefs
from artemis.ports.types import Vector
from artemis.proactive.hook_types import HookResult
from artemis.registry import ToolRegistry
from artemis.staging import ActionStagingService
from artemis.staging.model import ActionStatus, PendingAction


class FakeEmbedder:
    @property
    def dimension(self) -> int:
        return 8

    async def embed_documents(self, texts: Sequence[str]) -> list[Vector]:
        return [self._hash_vec(text) for text in texts]

    async def embed_query(self, query: str) -> Vector:
        return self._hash_vec(query)

    def _hash_vec(self, text: str) -> Vector:
        vec = [0.0] * self.dimension
        for word in text.lower().split():
            vec[hashlib.sha256(word.encode()).digest()[0] % self.dimension] += 1.0
        norm = math.sqrt(sum(value * value for value in vec))
        return [value / norm for value in vec] if norm else vec


class FakeActionStagingService:
    def __init__(self) -> None:
        self.staged: list[PendingAction] = []

    def stage(
        self,
        module: str,
        tool: str,
        args: dict[str, object],
        summary: str,
        *,
        ttl: timedelta | None = None,
    ) -> PendingAction:
        del ttl
        now = datetime.now(tz=UTC)
        action = PendingAction(
            id=f"pending-{len(self.staged) + 1}",
            module=module,
            tool=tool,
            args=args,
            summary=summary,
            action_class="takes-action",
            status=ActionStatus.PENDING,
            created_at=now,
            expires_at=now + timedelta(hours=1),
        )
        self.staged.append(action)
        return action


class FakeCacheStore:
    def __init__(self, events: list[CachedEvent] | None = None) -> None:
        self.events: dict[tuple[str, str], CachedEvent] = {}
        self.sync_tokens: dict[str, str] = {}
        for event in events or []:
            self.upsert(event)

    def upsert(self, event: CachedEvent) -> None:
        self.events[(event.event_id, event.calendar_id)] = event

    def delete(self, event_id: str, calendar_id: str) -> None:
        self.events.pop((event_id, calendar_id), None)

    def invalidate(self, event_id: str, calendar_id: str) -> None:
        self.delete(event_id, calendar_id)

    def get_sync_token(self, calendar_id: str) -> str | None:
        return self.sync_tokens.get(calendar_id)

    def set_sync_token(self, calendar_id: str, token: str) -> None:
        self.sync_tokens[calendar_id] = token

    def query_events(
        self,
        *,
        calendar_ids: list[str] | None = None,
        time_min: str | None = None,
        time_max: str | None = None,
        status_filter: list[str] | None = None,
    ) -> list[CachedEvent]:
        events = list(self.events.values())
        if calendar_ids is not None:
            events = [event for event in events if event.calendar_id in calendar_ids]
        if time_min is not None:
            events = [event for event in events if event.end_dt > time_min]
        if time_max is not None:
            events = [event for event in events if event.start_dt < time_max]
        if status_filter is None:
            events = [event for event in events if event.status != "cancelled"]
        elif status_filter:
            events = [event for event in events if event.status in status_filter]
        return sorted(events, key=lambda event: event.start_dt)

    def clear_calendar(self, calendar_id: str) -> None:
        for key in list(self.events):
            if key[1] == calendar_id:
                self.events.pop(key)
        self.sync_tokens.pop(calendar_id, None)


class FakeSyncEngine:
    def __init__(self, added: int, updated: int, deleted: int) -> None:
        self.added = added
        self.updated = updated
        self.deleted = deleted

    def sync(self, calendar_id: str, owner_email: str) -> object:
        del calendar_id, owner_email

        class Result:
            events_added = self.added
            events_updated = self.updated
            events_deleted = self.deleted

        return Result()


def test_overlay_store_round_trips_and_locked_store_raises(tmp_path: Path) -> None:
    store = _store(tmp_path)
    row = ProposalRow(
        id="p1",
        kind="hold",
        status="pending",
        label="Focus",
        proposed_start=_iso(minutes=60),
        proposed_end=_iso(minutes=120),
        source_event_id=None,
        google_event_id=None,
        created_at=_iso(),
        updated_at=_iso(),
    )

    store.save(row)

    assert store.get("p1") == row
    with pytest.raises(ScopeLockedError):
        OverlayStore(_settings(tmp_path), FakeKeyProvider(owner_unlocked=False)).list_pending()


def test_hold_approve_reject_and_pending_list(tmp_path: Path) -> None:
    key_provider = _key_provider()
    store = _store(tmp_path, key_provider=key_provider)
    client = _client()
    staging = cast(ActionStagingService, FakeActionStagingService())
    row = hold_tentative(
        client,
        store,
        key_provider=key_provider,
        start=_iso(minutes=60),
        end=_iso(minutes=120),
        label="Focus",
    )

    event = client.events_by_calendar["primary"][0]
    assert event["status"] == "tentative"
    assert event["extendedProperties"] == {"private": {"artemis_overlay": row.id}}
    saved = store.get(row.id)
    assert saved is not None
    assert saved.google_event_id == row.google_event_id
    assert list_proposals(store) == [row]

    approved = approve_proposal(
        client,
        store,
        staging,
        key_provider=key_provider,
        proposal_id=row.id,
        owner_email="owner@example.com",
    )

    assert isinstance(approved, ProposalRow)
    assert approved.status == "approved"
    assert client.write_calls["update_event"][-1]["changes"] == {"status": "confirmed"}
    assert list_proposals(store) == []

    rejected_source = hold_tentative(
        client,
        store,
        key_provider=key_provider,
        start=_iso(minutes=180),
        end=_iso(minutes=240),
        label="Decline",
    )
    rejected = reject_proposal(
        client,
        store,
        key_provider=key_provider,
        proposal_id=rejected_source.id,
    )

    assert rejected.status == "rejected"
    assert client.write_calls["cancel_event"][-1] == {
        "event_id": rejected_source.google_event_id,
        "recurrence_scope": "THIS_EVENT",
        "send_updates": "none",
    }


def test_locked_key_provider_stops_before_google_call(tmp_path: Path) -> None:
    client = _client()
    with pytest.raises(ScopeLockedError):
        hold_tentative(
            client,
            _store(tmp_path),
            key_provider=FakeKeyProvider(owner_unlocked=False),
            start=_iso(minutes=60),
            end=_iso(minutes=120),
            label="Locked",
        )
    assert client.write_calls["create_event"] == []


def test_attendee_approval_stages_underlying_write_not_approve_loop(tmp_path: Path) -> None:
    key_provider = _key_provider()
    store = _store(tmp_path, key_provider=key_provider)
    client = _client(
        events=[
            {
                "id": "team",
                "summary": "Team",
                "start": {"dateTime": _iso(minutes=60)},
                "end": {"dateTime": _iso(minutes=120)},
                "status": "confirmed",
                "attendees": [{"email": "other@example.com"}],
            }
        ]
    )
    staging = FakeActionStagingService()
    row = ProposalRow(
        id="reschedule-1",
        kind="reschedule",
        status="pending",
        label="Reschedule: team",
        proposed_start=_iso(minutes=180),
        proposed_end=_iso(minutes=240),
        source_event_id="team",
        google_event_id="projection",
        created_at=_iso(),
        updated_at=_iso(),
    )
    store.save(row)

    result = approve_proposal(
        client,
        store,
        cast(ActionStagingService, staging),
        key_provider=key_provider,
        proposal_id=row.id,
        owner_email="owner@example.com",
    )

    assert isinstance(result, PendingAction)
    assert staging.staged[0].tool == "calendar.update_event"
    assert staging.staged[0].tool != "calendar.approve_proposal"
    staged_row = store.get(row.id)
    assert staged_row is not None
    assert staged_row.status == "pending"


def test_overlay_marker_sync_marks_own_projection(tmp_path: Path) -> None:
    key_provider = _key_provider()
    overlay = _store(tmp_path, key_provider=key_provider)
    client = _client()
    row = hold_tentative(
        client,
        overlay,
        key_provider=key_provider,
        start=_iso(minutes=60),
        end=_iso(minutes=120),
        label="Focus",
    )
    cache = FakeCacheStore()
    engine = CalendarSyncEngine(client, cast(EventCacheStore, cache), CalPrefs())

    engine.sync("primary", "owner@example.com")

    cached = cache.events[(cast(str, row.google_event_id), "primary")]
    assert cached.is_overlay_projection
    assert cached.overlay_proposal_id == row.id
    assert not cached.externally_authored


def test_hook_checks_fire_with_expected_payloads(tmp_path: Path) -> None:
    del tmp_path
    owner = "owner@example.com"
    conflict_a = _cached("conflict-a", _iso(minutes=90), end=_iso(minutes=150))
    conflict_b = _cached("conflict-b", _iso(minutes=120), end=_iso(minutes=180))
    invites = [
        _cached(
            f"invite-{idx}",
            _iso(hours=idx + 2),
            raw_json=json.dumps({"responseStatus": "needsAction"}),
        )
        for idx in range(3)
    ]
    prep = _cached(
        "prep", _iso(hours=12), attendees=[owner, "other@example.com"], summary="Raw prep"
    )
    external = _cached(
        "external",
        _iso(minutes=30),
        attendees=[],
        summary="External <script>",
        externally_authored=True,
    )
    upcoming_result = make_upcoming_reminder_check(
        cast(EventCacheStore, FakeCacheStore([_cached("upcoming", _iso(minutes=10))]))
    )()
    changes_result = make_change_detection_check(
        cast(CalendarSyncEngine, FakeSyncEngine(1, 1, 0)),
        ["primary"],
        owner,
    )()
    conflict_result = make_conflict_alert_check(
        cast(EventCacheStore, FakeCacheStore([conflict_a, conflict_b]))
    )()
    invite_result = make_unanswered_invite_check(
        cast(EventCacheStore, FakeCacheStore(invites)), owner_email=owner
    )()
    prep_result = make_prep_nudge_check(cast(EventCacheStore, FakeCacheStore([prep])))()
    briefing_result = make_daily_briefing_check(
        cast(EventCacheStore, FakeCacheStore([external, *invites]))
    )()

    assert upcoming_result.hit
    starts_in = cast(int, upcoming_result.payload["starts_in_minutes"])
    assert 0 <= starts_in <= 15
    assert changes_result.hit
    assert changes_result.payload["changed_count"] == 2
    assert conflict_result.hit
    assert conflict_result.payload["conflict_count"] == 1
    assert invite_result.hit
    assert invite_result.payload["invite_count"] == 3
    assert prep_result.hit
    assert set(prep_result.payload) == {"event_id", "starts_in_hours"}
    assert briefing_result.hit
    assert cast(int, briefing_result.payload["event_count"]) >= 3
    assert "External <script>" not in str(briefing_result.payload)


def test_free_gap_check_emits_hold_once(tmp_path: Path) -> None:
    key_provider = _key_provider()
    overlay = _store(tmp_path, key_provider=key_provider)
    client = _client()
    cache = FakeCacheStore()
    check = make_free_gap_check(
        cast(EventCacheStore, cache),
        overlay,
        client=client,
        key_provider=key_provider,
        min_gap_minutes=30,
    )

    first = check()
    second = check()

    assert first.hit
    assert second.hit is False
    assert overlay.list_pending()[0].kind == "hold"


def test_build_calendar_hooks_and_intentions_stub(tmp_path: Path) -> None:
    hooks = build_calendar_hooks(
        cast(CalendarSyncEngine, FakeSyncEngine(0, 0, 0)),
        cast(EventCacheStore, FakeCacheStore()),
        _store(tmp_path),
        owner_email="owner@example.com",
        calendar_ids=["primary"],
    )

    assert len(hooks) == 7
    assert all(hook.tier == 1 for hook in hooks)
    assert all(hook.name != "cal_intentions" for hook in hooks)
    _intentions_projection_stub()
    assert (
        _quarantine_stub("external title with <script>") == "[external content pending quarantine]"
    )


def test_tier1_queueing_skips_while_locked_and_runs_when_unlocked() -> None:
    calls = 0

    def check() -> HookResult:
        nonlocal calls
        calls += 1

        return HookResult.of({"ok": True})

    manifest = ModuleManifest(
        name="calendar",
        version="0.1.0",
        description="Calendar.",
        data_scope=DataScope.OWNER_PRIVATE,
        proactive_hooks=[HookSpec(name="cal_test", interval_seconds=60, tier=1, check_ref=check)],
    )
    registry = ToolRegistry(FakeEmbedder())
    registry.register(manifest)

    locked = Heartbeat(registry, FakeKeyProvider(owner_unlocked=False))
    locked_result = locked.tick()
    unlocked = Heartbeat(registry, FakeKeyProvider(owner_unlocked=True))
    unlocked_result = unlocked.tick()

    assert calls == 1
    assert locked_result.tier1_skipped == ("calendar.cal_test",)
    assert len(unlocked_result.hits) == 1


def test_overlay_manifest_factory_has_bare_tool_names(tmp_path: Path) -> None:
    key_provider = _key_provider()
    overlay_tools = OverlayTools(
        _client(),
        _store(tmp_path, key_provider=key_provider),
        cast(ActionStagingService, FakeActionStagingService()),
        key_provider,
        CalPrefs(owner_email="owner@example.com"),
    )

    specs = make_calendar_overlay_manifest(overlay_tools)

    assert len(specs) == 6
    assert all("." not in spec.name for spec in specs)


def _settings(tmp_path: Path) -> Settings:
    return Settings(data_root=tmp_path, slot="dev")


def _key_provider() -> FakeKeyProvider:
    return FakeKeyProvider({OWNER_PRIVATE: b"1" * 32}, owner_unlocked=True)


def _store(tmp_path: Path, *, key_provider: FakeKeyProvider | None = None) -> OverlayStore:
    return OverlayStore(_settings(tmp_path), key_provider or _key_provider())


def _client(events: list[dict[str, object]] | None = None) -> FakeCalendarClient:
    return FakeCalendarClient(
        calendar_list=[{"id": "primary", "summary": "Primary"}],
        events_by_calendar={"primary": list(events or [])},
        free_busy_response={},
    )


def _cached(
    event_id: str,
    start: str,
    *,
    end: str | None = None,
    attendees: list[str] | None = None,
    summary: str = "Event",
    raw_json: str = "{}",
    externally_authored: bool = False,
) -> CachedEvent:
    return CachedEvent(
        event_id=event_id,
        calendar_id="primary",
        summary=summary,
        description=None,
        location=None,
        start_dt=start,
        end_dt=end or _iso_from_dt(datetime.fromisoformat(start) + timedelta(minutes=60)),
        status="confirmed",
        attendees=attendees or [],
        organizer_email="owner@example.com",
        creator_email="owner@example.com",
        externally_authored=externally_authored,
        is_overlay_projection=False,
        overlay_proposal_id=None,
        raw_json=raw_json,
    )


def _iso(*, minutes: int = 0, hours: int = 0) -> str:
    return _iso_from_dt(datetime.now(tz=UTC) + timedelta(minutes=minutes, hours=hours))


def _iso_from_dt(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()
