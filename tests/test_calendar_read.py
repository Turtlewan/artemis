from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

from artemis.config import Settings
from artemis.identity.key_provider import FakeKeyProvider, ScopeLockedError
from artemis.modules.calendar.cache import CachedEvent, CalendarSyncEngine, EventCacheStore
from artemis.modules.calendar.client import CalendarClient, FakeCalendarClient
from artemis.modules.calendar.preferences import CalPrefs
from artemis.modules.calendar.read_tools import (
    AgendaArgs,
    FindTimeEngine,
    FindTimeWithAttendeesArgs,
    FreeBusyArgs,
    ListEventsArgs,
    SearchArgs,
    Window,
    agenda,
    find_time_with_attendees_tool,
    free_busy,
    list_events,
    search,
)

_c: CalendarClient = FakeCalendarClient([], {}, {})  # satisfies CalendarClient


class FakePreferencesStore:
    def __init__(self, prefs: CalPrefs) -> None:
        self.prefs = prefs

    def load(self) -> CalPrefs:
        return self.prefs

    def save(self, prefs: CalPrefs) -> None:
        self.prefs = prefs

    def update(self, **kwargs: object) -> CalPrefs:
        known = {field.name for field in dataclasses.fields(CalPrefs)}
        for key in kwargs:
            if key not in known:
                raise ValueError(f"unknown pref field: {key}")
        self.prefs = dataclasses.replace(self.prefs, **kwargs)  # type: ignore[arg-type]
        return self.prefs


class FakeCacheStore:
    def __init__(self) -> None:
        self.events: dict[tuple[str, str], CachedEvent] = {}
        self.sync_tokens: dict[str, str] = {}

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


def test_sync_idempotency_uses_incremental_token() -> None:
    store = FakeCacheStore()
    client = FakeCalendarClient([], {"primary": [_raw_event("a", "2026-06-22T09:00:00+00:00")]}, {})
    engine = CalendarSyncEngine(client, cast(EventCacheStore, store), CalPrefs())

    first = engine.sync("primary", "owner@example.com")
    second = engine.sync("primary", "owner@example.com")

    assert first.full_sync
    assert not second.full_sync
    assert second.events_added == 0
    assert second.events_updated == 0
    assert second.events_deleted == 0
    assert client.list_events_calls[-1]["sync_token"] == "fake-token-1"


def test_sync_add_update_delete_incremental() -> None:
    store = FakeCacheStore()
    client = FakeCalendarClient(
        [],
        {
            "primary": [
                _raw_event("a", "2026-06-22T09:00:00+00:00", summary="A"),
                _raw_event("b", "2026-06-22T11:00:00+00:00", summary="B"),
                _raw_event("c", "2026-06-22T13:00:00+00:00", summary="C"),
            ]
        },
        {},
    )
    engine = CalendarSyncEngine(client, cast(EventCacheStore, store), CalPrefs())
    engine.sync("primary", "owner@example.com")
    client.set_incremental_events(
        "primary",
        [
            _raw_event("a", "2026-06-22T09:00:00+00:00", summary="A updated"),
            _raw_event("d", "2026-06-22T15:00:00+00:00", summary="D"),
            {"id": "b", "status": "cancelled"},
        ],
    )

    result = engine.sync("primary", "owner@example.com")

    assert result.events_added == 1
    assert result.events_updated == 1
    assert result.events_deleted == 1
    assert len(store.events) == 3
    assert store.events[("a", "primary")].summary == "A updated"
    assert ("b", "primary") not in store.events


def test_invalid_sync_token_falls_back_to_full_sync() -> None:
    store = FakeCacheStore()
    client = FakeCalendarClient([], {"primary": [_raw_event("a", "2026-06-22T09:00:00+00:00")]}, {})
    engine = CalendarSyncEngine(client, cast(EventCacheStore, store), CalPrefs())
    engine.sync("primary", "owner@example.com")
    client.events_by_calendar["primary"] = [_raw_event("b", "2026-06-23T09:00:00+00:00")]
    client.raise_invalid_sync_token_once = True

    result = engine.sync("primary", "owner@example.com")

    assert result.full_sync
    assert list(store.events) == [("b", "primary")]


@pytest.mark.asyncio
async def test_overlay_marker_excluded_from_free_busy_but_in_agenda() -> None:
    store = FakeCacheStore()
    engine = CalendarSyncEngine(
        FakeCalendarClient(
            [],
            {"primary": [_raw_event("hold", "2026-06-22T09:00:00+00:00", overlay="prop-123")]},
            {},
        ),
        cast(EventCacheStore, store),
        CalPrefs(),
    )
    engine.sync("primary", "owner@example.com")
    event = store.events[("hold", "primary")]

    busy = await free_busy(
        FreeBusyArgs(
            window=Window(start="2026-06-22T00:00:00+00:00", end="2026-06-23T00:00:00+00:00")
        ),
        store=cast(EventCacheStore, store),
    )
    day = await agenda(
        AgendaArgs(day="2026-06-22"),
        store=cast(EventCacheStore, store),
        prefs=CalPrefs(),
    )

    assert event.is_overlay_projection
    assert not event.externally_authored
    assert event.overlay_proposal_id == "prop-123"
    assert busy.busy_blocks == []
    assert day.events[0].is_overlay_projection


def test_externally_authored_tagging() -> None:
    engine = CalendarSyncEngine(
        FakeCalendarClient([], {}, {}),
        cast(EventCacheStore, FakeCacheStore()),
        CalPrefs(),
    )

    mine = engine._to_cached_event(
        _raw_event("mine", "2026-06-22T09:00:00+00:00", organizer="owner@example.com"),
        "primary",
        "owner@example.com",
    )
    theirs = engine._to_cached_event(
        _raw_event("theirs", "2026-06-22T09:00:00+00:00", organizer="other@example.com"),
        "primary",
        "owner@example.com",
    )
    overlay = engine._to_cached_event(
        _raw_event(
            "overlay",
            "2026-06-22T09:00:00+00:00",
            organizer="other@example.com",
            overlay="prop",
        ),
        "primary",
        "owner@example.com",
    )

    assert not mine.externally_authored
    assert theirs.externally_authored
    assert not overlay.externally_authored


def test_initial_sync_uses_bounded_window() -> None:
    store = FakeCacheStore()
    client = FakeCalendarClient([], {"primary": []}, {})

    CalendarSyncEngine(
        client,
        cast(EventCacheStore, store),
        CalPrefs(sync_window_months_past=1, sync_window_months_future=2),
    ).sync(
        "primary",
        "owner@example.com",
    )

    call = client.list_events_calls[0]
    assert call["time_min"] is not None
    assert call["time_max"] is not None
    assert call["sync_token"] is None


def test_locked_event_cache_store_raises(tmp_path: Path) -> None:
    store = EventCacheStore(_settings(tmp_path), FakeKeyProvider(owner_unlocked=False))

    with pytest.raises(ScopeLockedError):
        store.query_events()


def test_find_time_honors_working_hours_buffers_and_no_meeting_windows() -> None:
    prefs = CalPrefs(
        working_hours_start="09:00",
        working_hours_end="17:00",
        buffer_minutes=15,
        no_meeting_before="10:00",
        no_meeting_after="17:00",
    )
    slots = FindTimeEngine(prefs).find_slots(
        [(_dt("2026-06-22T10:00:00+00:00"), _dt("2026-06-22T11:00:00+00:00"))],
        _dt("2026-06-22T00:00:00+00:00"),
        _dt("2026-06-22T23:00:00+00:00"),
        60,
    )

    assert slots
    assert all(slot.start_dt >= "2026-06-22T11:15:00+00:00" for slot in slots)
    assert (
        FindTimeEngine(prefs).find_slots(
            [], _dt("2026-06-22T00:00:00+00:00"), _dt("2026-06-22T23:00:00+00:00"), 600
        )
        == []
    )


def test_no_meeting_after_clips_day() -> None:
    prefs = CalPrefs(
        working_hours_start="09:00", working_hours_end="18:00", no_meeting_after="12:00"
    )

    slots = FindTimeEngine(prefs).find_slots(
        [],
        _dt("2026-06-22T00:00:00+00:00"),
        _dt("2026-06-22T23:00:00+00:00"),
        60,
    )

    assert slots[-1].end_dt <= "2026-06-22T12:00:00+00:00"


@pytest.mark.asyncio
async def test_find_time_with_attendees_intersects_all_busy_sets() -> None:
    client = FakeCalendarClient(
        [],
        {},
        {
            "calendars": {
                "owner@example.com": {
                    "busy": [
                        {"start": "2026-06-22T09:00:00+00:00", "end": "2026-06-22T10:00:00+00:00"}
                    ]
                },
                "a@example.com": {
                    "busy": [
                        {"start": "2026-06-22T11:00:00+00:00", "end": "2026-06-22T12:00:00+00:00"}
                    ]
                },
                "b@example.com": {
                    "busy": [
                        {"start": "2026-06-22T14:00:00+00:00", "end": "2026-06-22T15:00:00+00:00"}
                    ]
                },
            }
        },
    )

    result = await find_time_with_attendees_tool(
        FindTimeWithAttendeesArgs(
            duration_minutes=30,
            window=Window(start="2026-06-22T09:00:00+00:00", end="2026-06-22T17:00:00+00:00"),
            attendee_emails=["a@example.com", "b@example.com"],
        ),
        store=cast(EventCacheStore, FakeCacheStore()),
        prefs=CalPrefs(owner_email="owner@example.com", buffer_minutes=0),
        client=client,
    )

    assert result.slots
    assert all(not ("09:00" <= slot.start_dt[11:16] < "10:00") for slot in result.slots)
    assert all(not ("11:00" <= slot.start_dt[11:16] < "12:00") for slot in result.slots)
    assert all(not ("14:00" <= slot.start_dt[11:16] < "15:00") for slot in result.slots)


@pytest.mark.asyncio
async def test_multi_calendar_list_events_filter() -> None:
    store = FakeCacheStore()
    store.upsert(_cached("a", "cal1", "2026-06-22T09:00:00+00:00", "A"))
    store.upsert(_cached("b", "cal2", "2026-06-22T10:00:00+00:00", "B"))

    both = await list_events(
        ListEventsArgs(
            window=Window(start="2026-06-22T00:00:00+00:00", end="2026-06-23T00:00:00+00:00"),
            calendar_ids=["cal1", "cal2"],
        ),
        store=cast(EventCacheStore, store),
    )
    one = await list_events(
        ListEventsArgs(
            window=Window(start="2026-06-22T00:00:00+00:00", end="2026-06-23T00:00:00+00:00"),
            calendar_ids=["cal1"],
        ),
        store=cast(EventCacheStore, store),
    )

    assert {event.calendar_id for event in both.events} == {"cal1", "cal2"}
    assert [event.calendar_id for event in one.events] == ["cal1"]


@pytest.mark.asyncio
async def test_search_text_filter_case_insensitive() -> None:
    store = FakeCacheStore()
    store.upsert(_cached("a", "cal1", "2026-06-22T09:00:00+00:00", "Project Review"))
    store.upsert(_cached("b", "cal1", "2026-06-22T10:00:00+00:00", "Lunch"))

    result = await search(SearchArgs(query="project"), store=cast(EventCacheStore, store))

    assert [event.event_id for event in result.events] == ["a"]


def test_fake_preferences_store_update_contract() -> None:
    store = FakePreferencesStore(CalPrefs())
    updated = store.update(timezone="Asia/Singapore")

    assert updated.timezone == "Asia/Singapore"
    with pytest.raises(ValueError):
        store.update(nope=1)


def _raw_event(
    event_id: str,
    start: str,
    *,
    summary: str = "Meeting",
    organizer: str = "owner@example.com",
    overlay: str | None = None,
) -> dict[str, object]:
    raw: dict[str, object] = {
        "id": event_id,
        "summary": summary,
        "start": {"dateTime": start},
        "end": {"dateTime": start.replace(":00+00:00", ":00+00:00")},
        "status": "confirmed",
        "organizer": {"email": organizer},
        "creator": {"email": organizer},
        "attendees": [{"email": "owner@example.com"}],
    }
    start_dt = _dt(start)
    raw["end"] = {"dateTime": (start_dt + timedelta(minutes=60)).isoformat()}
    if overlay is not None:
        raw["extendedProperties"] = {"private": {"artemis_overlay": overlay}}
    return raw


def _cached(event_id: str, calendar_id: str, start: str, summary: str) -> CachedEvent:
    return CachedEvent(
        event_id=event_id,
        calendar_id=calendar_id,
        summary=summary,
        description=None,
        location=None,
        start_dt=start,
        end_dt=(_dt(start) + timedelta(minutes=60)).isoformat(),
        status="confirmed",
        attendees=[],
        organizer_email="owner@example.com",
        creator_email="owner@example.com",
        externally_authored=False,
        is_overlay_projection=False,
        overlay_proposal_id=None,
        raw_json="{}",
    )


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _settings(tmp_path: Path) -> Settings:
    return Settings(data_root=tmp_path, slot="dev")
