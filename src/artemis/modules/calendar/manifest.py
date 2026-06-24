"""Calendar module manifest construction."""

from __future__ import annotations

import dataclasses

from artemis.manifest import ActionRisk, DataScope, ModuleManifest, Permissions, ToolSpec
from artemis.modules.calendar.cache import EventCacheStore
from artemis.modules.calendar.client import CalendarClient
from artemis.modules.calendar.preferences import CalPrefs, PreferencesStore
from artemis.modules.calendar.read_tools import (
    AgendaArgs,
    AgendaResult,
    ConflictsArgs,
    ConflictsResult,
    FindTimeArgs,
    FindTimeResult,
    FindTimeWithAttendeesArgs,
    FindTimeWithAttendeesResult,
    FreeBusyArgs,
    FreeBusyResult,
    GetEventArgs,
    GetEventResult,
    ListCalendarsArgs,
    ListCalendarsResult,
    ListEventsArgs,
    ListEventsResult,
    NextEventArgs,
    NextEventResult,
    SearchArgs,
    SearchResult,
    agenda,
    conflicts,
    find_time_tool,
    find_time_with_attendees_tool,
    free_busy,
    get_event,
    list_calendars,
    list_events,
    next_event,
    search,
)
from artemis.runtime_config import get_runtime_config


class CalendarTools:
    """Bound read tools with injected cache, prefs store, and client."""

    def __init__(
        self,
        store: EventCacheStore,
        prefs_store: PreferencesStore,
        client: CalendarClient,
    ) -> None:
        self._store = store
        self._prefs_store = prefs_store
        self._client = client

    def _prefs(self) -> CalPrefs:
        prefs = self._prefs_store.load()
        cfg = get_runtime_config().calendar
        return dataclasses.replace(
            prefs,
            working_days=cfg.working_days,
            preferred_focus_window=cfg.preferred_focus_window,
        )

    async def list_calendars(self, args: ListCalendarsArgs) -> ListCalendarsResult:
        return await list_calendars(args, client=self._client)

    async def list_events(self, args: ListEventsArgs) -> ListEventsResult:
        return await list_events(args, store=self._store)

    async def get_event(self, args: GetEventArgs) -> GetEventResult:
        return await get_event(args, store=self._store)

    async def agenda(self, args: AgendaArgs) -> AgendaResult:
        return await agenda(args, store=self._store, prefs=self._prefs())

    async def next_event(self, args: NextEventArgs) -> NextEventResult:
        return await next_event(args, store=self._store, prefs=self._prefs())

    async def search(self, args: SearchArgs) -> SearchResult:
        return await search(args, store=self._store)

    async def free_busy(self, args: FreeBusyArgs) -> FreeBusyResult:
        return await free_busy(args, store=self._store)

    async def find_time(self, args: FindTimeArgs) -> FindTimeResult:
        return await find_time_tool(args, store=self._store, prefs=self._prefs())

    async def find_time_with_attendees(
        self,
        args: FindTimeWithAttendeesArgs,
    ) -> FindTimeWithAttendeesResult:
        return await find_time_with_attendees_tool(
            args,
            store=self._store,
            prefs=self._prefs(),
            client=self._client,
        )

    async def conflicts(self, args: ConflictsArgs) -> ConflictsResult:
        return await conflicts(args, store=self._store, prefs=self._prefs())


def make_calendar_manifest(tools: CalendarTools) -> ModuleManifest:
    """Build the read-only Calendar module manifest."""
    return ModuleManifest(
        name="calendar",
        version="0.1.0",
        description="Google Calendar read/awareness, scheduling, and find_time engine.",
        data_scope=DataScope.OWNER_PRIVATE,
        permissions=Permissions(owner=True, guest=False),
        tools=[
            ToolSpec(
                name="list_calendars",
                description="List all of the owner's Google calendars.",
                args_schema=ListCalendarsArgs,
                return_schema=ListCalendarsResult,
                callable_ref=tools.list_calendars,
                action_risk=ActionRisk.READ,
            ),
            ToolSpec(
                name="list_events",
                description="List calendar events within a time window.",
                args_schema=ListEventsArgs,
                return_schema=ListEventsResult,
                callable_ref=tools.list_events,
                action_risk=ActionRisk.READ,
            ),
            ToolSpec(
                name="get_event",
                description="Get full details of a single calendar event.",
                args_schema=GetEventArgs,
                return_schema=GetEventResult,
                callable_ref=tools.get_event,
                action_risk=ActionRisk.READ,
            ),
            ToolSpec(
                name="agenda",
                description="Render the owner's schedule for a day or date range.",
                args_schema=AgendaArgs,
                return_schema=AgendaResult,
                callable_ref=tools.agenda,
                action_risk=ActionRisk.READ,
            ),
            ToolSpec(
                name="next_event",
                description="Get the next upcoming calendar event.",
                args_schema=NextEventArgs,
                return_schema=NextEventResult,
                callable_ref=tools.next_event,
                action_risk=ActionRisk.READ,
            ),
            ToolSpec(
                name="search",
                description="Search calendar events by text query.",
                args_schema=SearchArgs,
                return_schema=SearchResult,
                callable_ref=tools.search,
                action_risk=ActionRisk.READ,
            ),
            ToolSpec(
                name="free_busy",
                description="Get the owner's busy blocks across calendars in a window.",
                args_schema=FreeBusyArgs,
                return_schema=FreeBusyResult,
                callable_ref=tools.free_busy,
                action_risk=ActionRisk.READ,
            ),
            ToolSpec(
                name="find_time",
                description="Find free time slots respecting working hours and buffers.",
                args_schema=FindTimeArgs,
                return_schema=FindTimeResult,
                callable_ref=tools.find_time,
                action_risk=ActionRisk.READ,
            ),
            ToolSpec(
                name="find_time_with_attendees",
                description="Find mutually free slots across the owner and attendees via FreeBusy.",
                args_schema=FindTimeWithAttendeesArgs,
                return_schema=FindTimeWithAttendeesResult,
                callable_ref=tools.find_time_with_attendees,
                action_risk=ActionRisk.READ,
            ),
            ToolSpec(
                name="conflicts",
                description="Detect double-bookings and overlapping events.",
                args_schema=ConflictsArgs,
                return_schema=ConflictsResult,
                callable_ref=tools.conflicts,
                action_risk=ActionRisk.READ,
            ),
        ],
        proactive_hooks=[],
    )
