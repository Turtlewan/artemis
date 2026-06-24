from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta
from typing import cast

import pytest

from artemis.modules.calendar.cache import CachedEvent, EventCacheStore
from artemis.modules.calendar.preferences import CalPrefs
from artemis.modules.calendar.read_tools import (
    FindTimeArgs,
    FreeSlot,
    Window,
    filter_working_days,
    find_time_tool,
    rank_slots_by_focus_window,
)


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

    def upsert(self, event: CachedEvent) -> None:
        self.events[(event.event_id, event.calendar_id)] = event

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


def test_calprefs_new_defaults_and_round_trip_as_tuples() -> None:
    prefs = CalPrefs()
    assert prefs.working_days == (0, 1, 2, 3, 4)
    assert prefs.preferred_focus_window == ("09:00", "12:00")

    store = FakePreferencesStore(
        CalPrefs(working_days=(0, 1, 2, 3), preferred_focus_window=("08:00", "11:00"))
    )
    loaded = store.load()

    assert loaded.working_days == (0, 1, 2, 3)
    assert loaded.preferred_focus_window == ("08:00", "11:00")
    assert isinstance(loaded.working_days, tuple)
    assert isinstance(loaded.preferred_focus_window, tuple)


def test_update_accepts_new_fields_and_rejects_unknown() -> None:
    store = FakePreferencesStore(CalPrefs())

    updated = store.update(working_days=(0, 1, 2, 3, 4, 5))

    assert updated.working_days == (0, 1, 2, 3, 4, 5)
    with pytest.raises(ValueError):
        store.update(nonsense=1)


def test_working_days_filter() -> None:
    slots = [
        _slot("2026-06-26T09:00:00+00:00"),
        _slot("2026-06-27T09:00:00+00:00"),
        _slot("2026-06-29T09:00:00+00:00"),
    ]

    weekdays = filter_working_days(slots, (0, 1, 2, 3, 4), "UTC")
    all_days = filter_working_days(slots, (0, 1, 2, 3, 4, 5, 6), "UTC")

    assert [slot.start_dt for slot in weekdays] == [
        "2026-06-26T09:00:00+00:00",
        "2026-06-29T09:00:00+00:00",
    ]
    assert all_days == slots


def test_focus_window_ranking_within_first_and_fallback() -> None:
    mixed = [
        _slot("2026-06-22T08:00:00+00:00"),
        _slot("2026-06-22T10:00:00+00:00"),
        _slot("2026-06-22T14:00:00+00:00"),
    ]
    afternoon = [
        _slot("2026-06-22T13:00:00+00:00"),
        _slot("2026-06-22T15:00:00+00:00"),
    ]

    ranked = rank_slots_by_focus_window(mixed, ("09:00", "12:00"), "UTC")
    fallback = rank_slots_by_focus_window(afternoon, ("09:00", "12:00"), "UTC")

    assert [slot.start_dt[11:16] for slot in ranked] == ["10:00", "08:00", "14:00"]
    assert fallback == afternoon


def test_ranking_set_identity_and_filter_subset() -> None:
    slots = [
        _slot("2026-06-26T13:00:00+00:00"),
        _slot("2026-06-26T10:00:00+00:00"),
        _slot("2026-06-27T10:00:00+00:00"),
    ]

    ranked = rank_slots_by_focus_window(slots, ("09:00", "12:00"), "UTC")
    filtered = filter_working_days(slots, (0, 1, 2, 3, 4), "UTC")

    assert sorted(_identity(slot) for slot in ranked) == sorted(_identity(slot) for slot in slots)
    assert set(_identity(slot) for slot in filtered) < set(_identity(slot) for slot in slots)


@pytest.mark.asyncio
async def test_find_time_tool_filters_weekend_and_ranks_focus_window() -> None:
    store = FakeCacheStore()
    store.upsert(_cached("mon-busy", "primary", "2026-06-29T12:00:00+00:00", "Lunch"))
    prefs = CalPrefs(
        working_hours_start="09:00",
        working_hours_end="17:00",
        no_meeting_before="09:00",
        no_meeting_after="17:00",
        buffer_minutes=0,
        working_days=(0, 1, 2, 3, 4),
        preferred_focus_window=("09:00", "12:00"),
    )

    result = await find_time_tool(
        FindTimeArgs(
            duration_minutes=60,
            window=Window(start="2026-06-27T00:00:00+00:00", end="2026-06-30T00:00:00+00:00"),
            calendar_ids=["primary"],
        ),
        store=cast(EventCacheStore, store),
        prefs=prefs,
    )

    assert all("2026-06-27" not in slot.start_dt for slot in result.slots)
    assert result.slots[0].start_dt.startswith("2026-06-29T09:00:00")


def _slot(start: str) -> FreeSlot:
    end = datetime.fromisoformat(start) + timedelta(minutes=60)
    return FreeSlot(start_dt=start, end_dt=end.isoformat(), duration_minutes=60)


def _cached(event_id: str, calendar_id: str, start: str, summary: str) -> CachedEvent:
    return CachedEvent(
        event_id=event_id,
        calendar_id=calendar_id,
        summary=summary,
        description=None,
        location=None,
        start_dt=start,
        end_dt=(datetime.fromisoformat(start) + timedelta(minutes=60)).isoformat(),
        status="confirmed",
        attendees=[],
        organizer_email="owner@example.com",
        creator_email="owner@example.com",
        externally_authored=False,
        is_overlay_projection=False,
        overlay_proposal_id=None,
        raw_json="{}",
    )


def _identity(slot: FreeSlot) -> tuple[str, str, int]:
    return (slot.start_dt, slot.end_dt, slot.duration_minutes)
