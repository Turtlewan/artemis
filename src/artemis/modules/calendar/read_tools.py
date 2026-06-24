"""Calendar read tools and deterministic find-time engine.

Tool callables are ``async def`` for ADR-016 dispatch uniformity. Dependencies
are injected by ``CalendarTools`` in ``manifest.py``; the Pydantic args models
contain only user/tool inputs, not stores or clients.
"""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from artemis.modules.calendar.cache import CachedEvent, EventCacheStore
from artemis.modules.calendar.client import CalendarClient
from artemis.modules.calendar.preferences import CalPrefs


class Window(BaseModel):
    """ISO-8601 datetime or date window."""

    start: str
    end: str


class CalendarIdsFilter(BaseModel):
    """Optional calendar-id filter shared by read tools."""

    calendar_ids: list[str] | None = None


class ListCalendarsArgs(BaseModel):
    """No-argument calendar-list request."""


class CalendarInfo(BaseModel):
    """Calendar list entry."""

    calendar_id: str
    summary: str
    primary: bool
    access_role: str


class ListCalendarsResult(BaseModel):
    """Calendar list result."""

    calendars: list[CalendarInfo]


class ListEventsArgs(BaseModel):
    """List cached events in a window."""

    window: Window
    calendar_ids: list[str] | None = None
    query: str | None = None


class EventSummary(BaseModel):
    """Small event result for list surfaces."""

    event_id: str
    calendar_id: str
    summary: str
    start_dt: str
    end_dt: str
    status: str
    externally_authored: bool
    is_overlay_projection: bool


class ListEventsResult(BaseModel):
    """Cached event list."""

    events: list[EventSummary]


class GetEventArgs(BaseModel):
    """Lookup one cached event."""

    event_id: str
    calendar_id: str


class EventDetail(BaseModel):
    """Full cached event detail."""

    event_id: str
    calendar_id: str
    summary: str
    description: str | None
    location: str | None
    start_dt: str
    end_dt: str
    status: str
    attendees: list[str]
    organizer_email: str | None
    externally_authored: bool
    is_overlay_projection: bool
    overlay_proposal_id: str | None


class GetEventResult(BaseModel):
    """Optional event detail."""

    event: EventDetail | None


class AgendaArgs(BaseModel):
    """Agenda request for one day or explicit range."""

    day: str | None = None
    range: Window | None = None


class AgendaResult(BaseModel):
    """Agenda events sorted by start time; overlays are returned as holds."""

    events: list[EventSummary]


class NextEventArgs(BaseModel):
    """Next upcoming event request."""

    calendar_ids: list[str] | None = None


class NextEventResult(BaseModel):
    """Next upcoming non-overlay event."""

    event: EventSummary | None


class SearchArgs(BaseModel):
    """Search cached calendar text."""

    query: str
    range: Window | None = None
    calendar_ids: list[str] | None = None


class SearchResult(BaseModel):
    """Structured search results.

    External event description/location text is untrusted source data. CAL-a
    returns structured fields only; consumers must route externally-authored
    text through DR-a before LLM use.
    """

    events: list[EventSummary]


class FreeBusyArgs(BaseModel):
    """Local cache free/busy request."""

    window: Window
    calendar_ids: list[str] | None = None


class BusyBlock(BaseModel):
    """One busy interval."""

    calendar_id: str
    start_dt: str
    end_dt: str


class FreeBusyResult(BaseModel):
    """Busy blocks sorted by start time; overlays are excluded."""

    busy_blocks: list[BusyBlock]


class FindTimeArgs(BaseModel):
    """Find owner-local free time in the cache."""

    duration_minutes: int
    window: Window
    calendar_ids: list[str] | None = None
    buffer_minutes: int | None = None


class FreeSlot(BaseModel):
    """One available scheduling slot."""

    start_dt: str
    end_dt: str
    duration_minutes: int


class FindTimeResult(BaseModel):
    """Ranked free slots, capped at ten."""

    slots: list[FreeSlot]


class FindTimeWithAttendeesArgs(BaseModel):
    """Find mutual free time through Google FreeBusy."""

    duration_minutes: int
    window: Window
    attendee_emails: list[str]


class FindTimeWithAttendeesResult(BaseModel):
    """Mutual free slots for owner plus attendees."""

    slots: list[FreeSlot]


class ConflictsArgs(BaseModel):
    """Conflict scan request."""

    range: Window | None = None
    calendar_ids: list[str] | None = None


class ConflictGroup(BaseModel):
    """A group of overlapping events."""

    events: list[EventSummary]


class ConflictsResult(BaseModel):
    """Conflict groups."""

    conflicts: list[ConflictGroup]


async def list_calendars(args: ListCalendarsArgs, *, client: CalendarClient) -> ListCalendarsResult:
    """List live calendars via the read-only CalendarClient."""
    _ = args
    calendars = [
        CalendarInfo(
            calendar_id=str(item.get("id", "")),
            summary=str(item.get("summary", "")),
            primary=bool(item.get("primary", False)),
            access_role=str(item.get("accessRole", "")),
        )
        for item in client.list_calendars()
    ]
    return ListCalendarsResult(calendars=calendars)


async def list_events(args: ListEventsArgs, *, store: EventCacheStore) -> ListEventsResult:
    """List cached events and optionally filter summary text."""
    events = store.query_events(
        calendar_ids=args.calendar_ids,
        time_min=args.window.start,
        time_max=args.window.end,
    )
    if args.query:
        needle = args.query.casefold()
        events = [event for event in events if needle in event.summary.casefold()]
    return ListEventsResult(events=[_summary(event) for event in events])


async def get_event(args: GetEventArgs, *, store: EventCacheStore) -> GetEventResult:
    """Return full detail for one cached event."""
    events = store.query_events(
        calendar_ids=[args.calendar_id],
        status_filter=["confirmed", "tentative", "cancelled"],
    )
    for event in events:
        if event.event_id == args.event_id:
            return GetEventResult(event=_detail(event))
    return GetEventResult(event=None)


async def agenda(args: AgendaArgs, *, store: EventCacheStore, prefs: CalPrefs) -> AgendaResult:
    """Render an agenda window from cache, including overlay holds."""
    window = _resolve_agenda_window(args, prefs)
    events = store.query_events(time_min=window.start, time_max=window.end)
    return AgendaResult(events=[_summary(event) for event in events])


async def next_event(
    args: NextEventArgs,
    *,
    store: EventCacheStore,
    prefs: CalPrefs,
) -> NextEventResult:
    """Return the next upcoming real event, excluding overlays."""
    now = datetime.now(ZoneInfo(prefs.timezone))
    end = now + timedelta(days=30 * prefs.sync_window_months_future)
    events = store.query_events(
        calendar_ids=args.calendar_ids,
        time_min=now.isoformat(),
        time_max=end.isoformat(),
    )
    for event in events:
        if not event.is_overlay_projection and event.status != "cancelled":
            return NextEventResult(event=_summary(event))
    return NextEventResult(event=None)


async def search(args: SearchArgs, *, store: EventCacheStore) -> SearchResult:
    """Search summary, description, and location in cached events."""
    events = store.query_events(
        calendar_ids=args.calendar_ids,
        time_min=args.range.start if args.range else None,
        time_max=args.range.end if args.range else None,
    )
    needle = args.query.casefold()
    matched = [event for event in events if _search_text(event, needle)]
    return SearchResult(events=[_summary(event) for event in matched])


async def free_busy(args: FreeBusyArgs, *, store: EventCacheStore) -> FreeBusyResult:
    """Build owner busy blocks from the local cache, excluding overlays."""
    events = store.query_events(
        calendar_ids=args.calendar_ids,
        time_min=args.window.start,
        time_max=args.window.end,
    )
    blocks = [
        BusyBlock(calendar_id=event.calendar_id, start_dt=event.start_dt, end_dt=event.end_dt)
        for event in events
        if event.status != "cancelled" and not event.is_overlay_projection
    ]
    blocks.sort(key=lambda block: block.start_dt)
    return FreeBusyResult(busy_blocks=blocks)


async def find_time_tool(
    args: FindTimeArgs,
    *,
    store: EventCacheStore,
    prefs: CalPrefs,
) -> FindTimeResult:
    """Find owner-local free slots from cached busy blocks."""
    busy = await free_busy(
        FreeBusyArgs(window=args.window, calendar_ids=args.calendar_ids),
        store=store,
    )
    busy_blocks = [
        (
            _parse_iso_local(block.start_dt, prefs.timezone),
            _parse_iso_local(block.end_dt, prefs.timezone),
        )
        for block in busy.busy_blocks
    ]
    slots = FindTimeEngine(prefs).find_slots(
        busy_blocks,
        _parse_iso_local(args.window.start, prefs.timezone),
        _parse_iso_local(args.window.end, prefs.timezone),
        args.duration_minutes,
        buffer_minutes=args.buffer_minutes,
    )
    return FindTimeResult(slots=_post_process_slots(slots, prefs))


async def find_time_with_attendees_tool(
    args: FindTimeWithAttendeesArgs,
    *,
    store: EventCacheStore,
    prefs: CalPrefs,
    client: CalendarClient,
) -> FindTimeWithAttendeesResult:
    """Find mutually free slots. Owner working days and focus bias apply."""
    _ = store
    items = [{"id": email} for email in [prefs.owner_email, *args.attendee_emails] if email]
    raw = client.query_free_busy(args.window.start, args.window.end, items)
    busy_blocks = _freebusy_blocks(raw, prefs)
    slots = FindTimeEngine(prefs).find_slots(
        busy_blocks,
        _parse_iso_local(args.window.start, prefs.timezone),
        _parse_iso_local(args.window.end, prefs.timezone),
        args.duration_minutes,
    )
    return FindTimeWithAttendeesResult(slots=_post_process_slots(slots, prefs))


async def conflicts(
    args: ConflictsArgs,
    *,
    store: EventCacheStore,
    prefs: CalPrefs,
) -> ConflictsResult:
    """Detect overlapping real events in a small range."""
    window = args.range or _default_conflict_window(prefs)
    events = [
        event
        for event in store.query_events(
            calendar_ids=args.calendar_ids,
            time_min=window.start,
            time_max=window.end,
        )
        if not event.is_overlay_projection and event.status != "cancelled"
    ]
    groups: list[ConflictGroup] = []
    used: set[str] = set()
    for index, event in enumerate(events):
        if event.event_id in used:
            continue
        cluster = [event]
        start = _parse_iso_local(event.start_dt, prefs.timezone)
        end = _parse_iso_local(event.end_dt, prefs.timezone)
        for other in events[index + 1 :]:
            other_start = _parse_iso_local(other.start_dt, prefs.timezone)
            other_end = _parse_iso_local(other.end_dt, prefs.timezone)
            if start < other_end and other_start < end:
                cluster.append(other)
        if len(cluster) > 1:
            used.update(item.event_id for item in cluster)
            groups.append(ConflictGroup(events=[_summary(item) for item in cluster]))
    return ConflictsResult(conflicts=groups)


class FindTimeEngine:
    """Pure deterministic slot finder.

    The band-scan algorithm intentionally ignores ``working_days`` and
    ``preferred_focus_window``. X1/X2 are post-passes over its output.
    """

    def __init__(self, prefs: CalPrefs) -> None:
        self._prefs = prefs

    def find_slots(
        self,
        busy_blocks: list[tuple[datetime, datetime]],
        window_start: datetime,
        window_end: datetime,
        duration_minutes: int,
        *,
        buffer_minutes: int | None = None,
    ) -> list[FreeSlot]:
        """Return up to ten earliest free slots inside daily scheduling bands."""
        if duration_minutes <= 0 or window_start >= window_end:
            return []
        buffer = self._prefs.buffer_minutes if buffer_minutes is None else buffer_minutes
        expanded = _expanded_busy_blocks(busy_blocks, window_start, window_end, buffer)
        slots: list[FreeSlot] = []
        day = window_start.date()
        final_day = window_end.date()
        while day <= final_day and len(slots) < 10:
            band_start, band_end = self._daily_band(day, window_start, window_end)
            if band_start < band_end:
                slots.extend(_slots_for_band(band_start, band_end, expanded, duration_minutes))
                slots = slots[:10]
            day += timedelta(days=1)
        return slots

    def _daily_band(
        self,
        day: date,
        window_start: datetime,
        window_end: datetime,
    ) -> tuple[datetime, datetime]:
        tz = ZoneInfo(self._prefs.timezone)
        start_time = max(
            _parse_hhmm(self._prefs.working_hours_start),
            _parse_hhmm(self._prefs.no_meeting_before),
        )
        end_time = min(
            _parse_hhmm(self._prefs.working_hours_end),
            _parse_hhmm(self._prefs.no_meeting_after),
        )
        band_start = datetime.combine(day, start_time, tz)
        band_end = datetime.combine(day, end_time, tz)
        return max(band_start, window_start), min(band_end, window_end)


def _is_working_day(slot_start_iso: str, working_days: tuple[int, ...], tz: str) -> bool:
    """True when a slot starts on a configured working day (Mon=0)."""
    dt = _parse_iso_local(slot_start_iso, tz)
    return dt.weekday() in working_days


def filter_working_days(
    slots: list[FreeSlot],
    working_days: tuple[int, ...],
    tz: str,
) -> list[FreeSlot]:
    """Drop non-working-day slots without changing surviving slot boundaries."""
    return [slot for slot in slots if _is_working_day(slot.start_dt, working_days, tz)]


def rank_slots_by_focus_window(
    slots: list[FreeSlot],
    focus_window: tuple[str, str],
    tz: str,
) -> list[FreeSlot]:
    """Bias ranking toward the focus window only; never edits slot boundaries."""
    fstart, fend = focus_window

    def in_window(slot: FreeSlot) -> bool:
        tod = _time_of_day(slot.start_dt, tz)
        return fstart <= tod < fend

    within = [slot for slot in slots if in_window(slot)]
    outside = [slot for slot in slots if not in_window(slot)]
    return within + outside if within else slots


def _post_process_slots(slots: list[FreeSlot], prefs: CalPrefs) -> list[FreeSlot]:
    # X2 is RANKING ONLY: ranking never changes slot start/end/duration. X1
    # removes whole slots only; the frozen find_slots band-scan is untouched.
    working = filter_working_days(slots, prefs.working_days, prefs.timezone)
    ranked = rank_slots_by_focus_window(working, prefs.preferred_focus_window, prefs.timezone)
    return ranked[:10]


def _summary(event: CachedEvent) -> EventSummary:
    return EventSummary(
        event_id=event.event_id,
        calendar_id=event.calendar_id,
        summary=event.summary,
        start_dt=event.start_dt,
        end_dt=event.end_dt,
        status=event.status,
        externally_authored=event.externally_authored,
        is_overlay_projection=event.is_overlay_projection,
    )


def _detail(event: CachedEvent) -> EventDetail:
    return EventDetail(
        event_id=event.event_id,
        calendar_id=event.calendar_id,
        summary=event.summary,
        description=event.description,
        location=event.location,
        start_dt=event.start_dt,
        end_dt=event.end_dt,
        status=event.status,
        attendees=event.attendees,
        organizer_email=event.organizer_email,
        externally_authored=event.externally_authored,
        is_overlay_projection=event.is_overlay_projection,
        overlay_proposal_id=event.overlay_proposal_id,
    )


def _resolve_agenda_window(args: AgendaArgs, prefs: CalPrefs) -> Window:
    if args.range is not None:
        return args.range
    tz = ZoneInfo(prefs.timezone)
    day = date.fromisoformat(args.day) if args.day is not None else datetime.now(tz).date()
    start = datetime.combine(day, time.min, tz)
    end = datetime.combine(day, time.max.replace(microsecond=0), tz)
    return Window(start=start.isoformat(), end=end.isoformat())


def _default_conflict_window(prefs: CalPrefs) -> Window:
    now = datetime.now(ZoneInfo(prefs.timezone))
    return Window(start=now.isoformat(), end=(now + timedelta(days=7)).isoformat())


def _search_text(event: CachedEvent, needle: str) -> bool:
    fields = [event.summary, event.description or "", event.location or ""]
    try:
        raw = json.loads(event.raw_json)
    except json.JSONDecodeError:
        raw = {}
    if isinstance(raw, dict):
        fields.append(str(raw.get("description", "")))
        fields.append(str(raw.get("location", "")))
    return any(needle in field.casefold() for field in fields)


def _freebusy_blocks(raw: dict[str, object], prefs: CalPrefs) -> list[tuple[datetime, datetime]]:
    calendars = raw.get("calendars", {})
    blocks: list[tuple[datetime, datetime]] = []
    if not isinstance(calendars, dict):
        return blocks
    for calendar_value in calendars.values():
        if not isinstance(calendar_value, dict):
            continue
        busy = calendar_value.get("busy", [])
        if not isinstance(busy, list):
            continue
        for item in busy:
            if not isinstance(item, dict):
                continue
            start = item.get("start")
            end = item.get("end")
            if isinstance(start, str) and isinstance(end, str):
                blocks.append(
                    (_parse_iso_local(start, prefs.timezone), _parse_iso_local(end, prefs.timezone))
                )
    return blocks


def _expanded_busy_blocks(
    busy_blocks: list[tuple[datetime, datetime]],
    window_start: datetime,
    window_end: datetime,
    buffer_minutes: int,
) -> list[tuple[datetime, datetime]]:
    delta = timedelta(minutes=buffer_minutes)
    expanded = [
        (max(start - delta, window_start), min(end + delta, window_end))
        for start, end in busy_blocks
        if start < window_end and end > window_start
    ]
    expanded.sort(key=lambda pair: pair[0])
    return expanded


def _slots_for_band(
    band_start: datetime,
    band_end: datetime,
    busy_blocks: list[tuple[datetime, datetime]],
    duration_minutes: int,
) -> list[FreeSlot]:
    slots: list[FreeSlot] = []
    cursor = band_start
    duration = timedelta(minutes=duration_minutes)
    for busy_start, busy_end in busy_blocks:
        if busy_end <= band_start or busy_start >= band_end:
            continue
        clipped_start = max(busy_start, band_start)
        clipped_end = min(busy_end, band_end)
        if cursor + duration <= clipped_start:
            slots.append(_slot(cursor, clipped_start, duration_minutes))
        cursor = max(cursor, clipped_end)
    if cursor + duration <= band_end:
        slots.append(_slot(cursor, band_end, duration_minutes))
    return slots


def _slot(start: datetime, latest_end: datetime, duration_minutes: int) -> FreeSlot:
    end = start + timedelta(minutes=duration_minutes)
    if end > latest_end:
        end = latest_end
    return FreeSlot(
        start_dt=start.isoformat(), end_dt=end.isoformat(), duration_minutes=duration_minutes
    )


def _parse_iso_local(value: str, tz: str) -> datetime:
    zone = ZoneInfo(tz)
    if "T" not in value:
        return datetime.combine(date.fromisoformat(value), time.min, zone)
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=zone)
    return parsed.astimezone(zone)


def _time_of_day(value: str, tz: str) -> str:
    return _parse_iso_local(value, tz).strftime("%H:%M")


def _parse_hhmm(value: str) -> time:
    hour_text, minute_text = value.split(":")
    return time(hour=int(hour_text), minute=int(minute_text))
