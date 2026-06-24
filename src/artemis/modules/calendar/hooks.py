"""Tier-1 proactive hook factories for the calendar module."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, time, timedelta
from typing import Protocol, cast

from artemis.identity.key_provider import KeyProvider
from artemis.integrations.google import ReauthRequiredError
from artemis.manifest import HookSpec
from artemis.modules.calendar.cache import CachedEvent, CalendarSyncEngine, EventCacheStore
from artemis.modules.calendar.client import CalendarClient
from artemis.modules.calendar.overlay import OverlayStore, hold_tentative
from artemis.proactive.hook_types import HookResult


class _CacheStore(Protocol):
    def query_events(
        self,
        *,
        calendar_ids: list[str] | None = None,
        time_min: str | None = None,
        time_max: str | None = None,
        status_filter: list[str] | None = None,
    ) -> list[CachedEvent]:
        """Return cached events in the requested window."""
        ...


def _quarantine_stub(title: str) -> str:
    """Placeholder quarantine boundary for externally authored calendar text."""
    del title
    # TODO(CAL-d): replace _quarantine_stub with quarantine_event_text once DR-a/CAL-d lands.
    return "[external content pending quarantine]"


def make_daily_briefing_check(cache_store: EventCacheStore) -> Callable[[], HookResult]:
    """Build the daily briefing check; payload carries only ids and start times."""

    def check() -> HookResult:
        today = datetime.now(tz=UTC).date()
        start = datetime.combine(today, time.min, tzinfo=UTC).isoformat()
        end = datetime.combine(today + timedelta(days=1), time.min, tzinfo=UTC).isoformat()
        events = _events(cast(_CacheStore, cache_store), time_min=start, time_max=end)
        if not events:
            return HookResult.miss()
        payload_events = [{"event_id": event.event_id, "start": event.start_dt} for event in events]
        return HookResult.of(
            {"event_count": len(events), "events": payload_events},
            dedup_value=today.isoformat(),
        )

    return check


def make_upcoming_reminder_check(
    cache_store: EventCacheStore, *, lookahead_minutes: int = 15
) -> Callable[[], HookResult]:
    """Build a check for the next event starting soon."""

    def check() -> HookResult:
        now = datetime.now(tz=UTC)
        end = now + timedelta(minutes=lookahead_minutes)
        upcoming = [
            event
            for event in _events(
                cast(_CacheStore, cache_store),
                time_min=now.isoformat(),
                time_max=end.isoformat(),
            )
            if now <= _dt(event.start_dt) <= end
        ]
        if not upcoming:
            return HookResult.miss()
        event = upcoming[0]
        starts_in = max(0, round((_dt(event.start_dt) - now).total_seconds() / 60))
        return HookResult.of(
            {"event_id": event.event_id, "starts_in_minutes": starts_in},
            dedup_value=event.event_id,
        )

    return check


def make_change_detection_check(
    sync_engine: CalendarSyncEngine, calendar_ids: list[str], owner_email: str
) -> Callable[[], HookResult]:
    """Build a polling change-detection check over CalendarSyncEngine.sync."""

    def check() -> HookResult:
        try:
            changed_count = 0
            for calendar_id in calendar_ids:
                result = sync_engine.sync(calendar_id, owner_email)
                changed_count += result.events_added + result.events_updated + result.events_deleted
        except ReauthRequiredError:
            return HookResult.miss()
        if changed_count == 0:
            return HookResult.miss()
        today = datetime.now(tz=UTC).date()
        return HookResult.of(
            {"changed_count": changed_count},
            dedup_value=f"{today.isoformat()}-{changed_count}",
        )

    return check


def make_conflict_alert_check(cache_store: EventCacheStore) -> Callable[[], HookResult]:
    """Build a check for overlapping cached events in the next 24 hours."""

    def check() -> HookResult:
        now = datetime.now(tz=UTC)
        events = _events(
            cast(_CacheStore, cache_store),
            time_min=now.isoformat(),
            time_max=(now + timedelta(hours=24)).isoformat(),
        )
        conflicts: list[str] = []
        for index, left in enumerate(events):
            left_start = _dt(left.start_dt)
            left_end = _dt(left.end_dt)
            for right in events[index + 1 :]:
                if left_start < _dt(right.end_dt) and _dt(right.start_dt) < left_end:
                    conflicts.extend([left.event_id, right.event_id])
        if not conflicts:
            return HookResult.miss()
        today = now.date()
        event_ids = sorted(set(conflicts))
        return HookResult.of(
            {"conflict_count": len(event_ids) // 2, "event_ids": event_ids},
            dedup_value=f"{today.isoformat()}-{len(event_ids) // 2}",
        )

    return check


def make_free_gap_check(
    cache_store: EventCacheStore,
    overlay_store: OverlayStore,
    *,
    client: CalendarClient | None = None,
    key_provider: KeyProvider | None = None,
    min_gap_minutes: int = 30,
) -> Callable[[], HookResult]:
    """Build a check that emits one focus-block hold for a free gap today."""

    def check() -> HookResult:
        today = datetime.now(tz=UTC).date()
        if any(
            row.kind == "hold"
            and row.proposed_start is not None
            and _dt(row.proposed_start).date() == today
            for row in overlay_store.list_pending()
        ):
            return HookResult.miss()
        day_start = datetime.combine(today, time(9, 0), tzinfo=UTC)
        day_end = datetime.combine(today, time(18, 0), tzinfo=UTC)
        events = _events(
            cast(_CacheStore, cache_store),
            time_min=day_start.isoformat(),
            time_max=day_end.isoformat(),
        )
        gaps = _free_gaps(events, day_start, day_end, min_gap_minutes)
        if not gaps:
            return HookResult.miss()
        gap_start, gap_end = gaps[0]
        if client is None or key_provider is None:
            return HookResult.miss()
        row = hold_tentative(
            client,
            overlay_store,
            key_provider=key_provider,
            start=gap_start.isoformat(),
            end=gap_end.isoformat(),
            label="Focus block",
        )
        return HookResult.of(
            {"gap_count": len(gaps), "proposal_id": row.id},
            dedup_value=f"{today.isoformat()}-gap",
        )

    return check


def make_unanswered_invite_check(
    cache_store: EventCacheStore, *, owner_email: str
) -> Callable[[], HookResult]:
    """Build a check for events awaiting the owner's RSVP."""
    del owner_email

    def check() -> HookResult:
        today = datetime.now(tz=UTC).date()
        events = [
            event
            for event in _events(cast(_CacheStore, cache_store))
            if '"responseStatus": "needsAction"' in event.raw_json
            or '"responseStatus":"needsAction"' in event.raw_json
        ]
        if not events:
            return HookResult.miss()
        return HookResult.of(
            {"invite_count": len(events), "event_ids": [event.event_id for event in events]},
            dedup_value=f"{today.isoformat()}-{len(events)}",
        )

    return check


def make_prep_nudge_check(
    cache_store: EventCacheStore, *, lookahead_hours: int = 18
) -> Callable[[], HookResult]:
    """Build a meeting-prep nudge check with id-only LLM payloads."""

    def check() -> HookResult:
        now = datetime.now(tz=UTC)
        end = now + timedelta(hours=lookahead_hours)
        meetings = [
            event
            for event in _events(
                cast(_CacheStore, cache_store),
                time_min=now.isoformat(),
                time_max=end.isoformat(),
            )
            if event.attendees and not event.is_overlay_projection
        ]
        if not meetings:
            return HookResult.miss()
        event = meetings[0]
        starts_in_hours = max(0, round((_dt(event.start_dt) - now).total_seconds() / 3600))
        return HookResult.of(
            {"event_id": event.event_id, "starts_in_hours": starts_in_hours},
            dedup_value=event.event_id,
        )

    return check


def _intentions_projection_stub() -> None:
    """Intentions projection deferred until Productivity module exists."""
    pass  # TODO: wire Productivity module when available.


def build_calendar_hooks(
    sync_engine: CalendarSyncEngine,
    cache_store: EventCacheStore,
    overlay_store: OverlayStore,
    *,
    owner_email: str,
    calendar_ids: list[str],
    client: CalendarClient | None = None,
    key_provider: KeyProvider | None = None,
) -> list[HookSpec]:
    """Assemble the seven Tier-1 calendar proactive hooks."""
    return [
        HookSpec(
            name="cal_daily_briefing",
            cron="30 7 * * *",
            urgency="normal",
            needs_llm=True,
            tier=1,
            dedup_key="cal_briefing",
            check_ref=make_daily_briefing_check(cache_store),
        ),
        HookSpec(
            name="cal_upcoming_reminder",
            interval_seconds=300,
            urgency="high",
            needs_llm=False,
            tier=1,
            dedup_key="cal_upcoming",
            check_ref=make_upcoming_reminder_check(cache_store),
        ),
        HookSpec(
            name="cal_change_detection",
            interval_seconds=300,
            urgency="normal",
            needs_llm=False,
            tier=1,
            dedup_key="cal_changes",
            check_ref=make_change_detection_check(sync_engine, calendar_ids, owner_email),
        ),
        HookSpec(
            name="cal_conflict_alert",
            interval_seconds=1800,
            urgency="high",
            needs_llm=False,
            tier=1,
            dedup_key="cal_conflicts",
            check_ref=make_conflict_alert_check(cache_store),
        ),
        HookSpec(
            name="cal_free_gap",
            interval_seconds=3600,
            urgency="low",
            needs_llm=False,
            tier=1,
            dedup_key="cal_free_gap",
            check_ref=make_free_gap_check(
                cache_store,
                overlay_store,
                client=client,
                key_provider=key_provider,
            ),
        ),
        HookSpec(
            name="cal_unanswered_invite",
            interval_seconds=3600,
            urgency="normal",
            needs_llm=False,
            tier=1,
            dedup_key="cal_invites",
            check_ref=make_unanswered_invite_check(cache_store, owner_email=owner_email),
        ),
        HookSpec(
            name="cal_prep_nudge",
            interval_seconds=3600,
            urgency="normal",
            needs_llm=True,
            tier=1,
            dedup_key="cal_prep",
            check_ref=make_prep_nudge_check(cache_store),
        ),
    ]


def _events(
    cache_store: _CacheStore,
    *,
    time_min: str | None = None,
    time_max: str | None = None,
) -> list[CachedEvent]:
    return cache_store.query_events(time_min=time_min, time_max=time_max)


def _free_gaps(
    events: list[CachedEvent],
    day_start: datetime,
    day_end: datetime,
    min_gap_minutes: int,
) -> list[tuple[datetime, datetime]]:
    gaps: list[tuple[datetime, datetime]] = []
    cursor = day_start
    for event in events:
        event_start = max(_dt(event.start_dt), day_start)
        event_end = min(_dt(event.end_dt), day_end)
        if event_start > cursor and (event_start - cursor) >= timedelta(minutes=min_gap_minutes):
            gaps.append((cursor, event_start))
        if event_end > cursor:
            cursor = event_end
    if day_end > cursor and (day_end - cursor) >= timedelta(minutes=min_gap_minutes):
        gaps.append((cursor, day_end))
    return gaps


def _dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
