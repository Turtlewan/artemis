"""Calendar module manifest construction."""

from __future__ import annotations

import dataclasses
from collections.abc import Awaitable, Callable
from functools import partial

from artemis.identity.key_provider import KeyProvider
from artemis.integrations.google.scopes import register_google_scopes
from artemis.manifest import ActionRisk, DataScope, ModuleManifest, Permissions, ToolSpec
from artemis.modules.calendar.cache import CalendarSyncEngine, EventCacheStore
from artemis.modules.calendar.client import CalendarClient
from artemis.modules.calendar.create_from_extract import (
    CreateFromExtractArgs,
    HeldEventIdArgs,
    HeldEventStore,
    HeldTentativeEvent,
    HeldTentativeEventList,
    ListHeldEventsArgs,
    approve_held_event_tool,
    create_from_extract_tool,
    discard_held_event_tool,
    list_held_events_tool,
)
from artemis.modules.calendar.hooks import build_calendar_hooks
from artemis.modules.calendar.overlay import (
    ApproveRejectArgs,
    HoldTentativeArgs,
    ListProposalsArgs,
    OverlayStore,
    OverlayTools,
    ProposalListResult,
    ProposalResult,
    ProposeEventArgs,
    ProposeRescheduleArgs,
)
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
from artemis.modules.calendar.schedule_task import ScheduleTaskArgs, ScheduleTaskResult
from artemis.modules.calendar.write_tools import (
    AddAttendeesArgs,
    BlockFocusTimeArgs,
    CalendarWriteTools,
    CancelEventArgs,
    CreateEventArgs,
    CreateRecurringEventArgs,
    MoveEventArgs,
    QuickAddArgs,
    RemoveAttendeesArgs,
    RespondToInviteArgs,
    SetRemindersArgs,
    UpdateEventArgs,
    WriteResult,
)
from artemis.runtime_config import get_runtime_config

register_google_scopes("calendar_write", {"https://www.googleapis.com/auth/calendar.events"})


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


def make_calendar_overlay_manifest(overlay_tools: OverlayTools) -> list[ToolSpec]:
    """Build overlay proposal ToolSpecs with bare names for registry composition."""
    return [
        ToolSpec(
            name="propose_reschedule",
            description="Propose a new time for an existing calendar event.",
            args_schema=ProposeRescheduleArgs,
            return_schema=ProposalResult,
            callable_ref=overlay_tools.propose_reschedule,
            action_risk=ActionRisk.WRITE,
        ),
        ToolSpec(
            name="propose_event",
            description="Create a pending proposed event and tentative Google projection.",
            args_schema=ProposeEventArgs,
            return_schema=ProposalResult,
            callable_ref=overlay_tools.propose_event,
            action_risk=ActionRisk.WRITE,
        ),
        ToolSpec(
            name="hold_tentative",
            description="Create a self-only tentative hold on the owner's calendar.",
            args_schema=HoldTentativeArgs,
            return_schema=ProposalResult,
            callable_ref=overlay_tools.hold_tentative,
            action_risk=ActionRisk.WRITE,
        ),
        ToolSpec(
            name="list_proposals",
            description="List pending calendar proposals and holds.",
            args_schema=ListProposalsArgs,
            return_schema=ProposalListResult,
            callable_ref=overlay_tools.list_proposals,
            action_risk=ActionRisk.READ,
        ),
        ToolSpec(
            name="approve_proposal",
            description="Approve a calendar proposal or stage the underlying attendee write.",
            args_schema=ApproveRejectArgs,
            return_schema=ProposalResult,
            callable_ref=overlay_tools.approve_proposal,
            action_risk=ActionRisk.HIGH_STAKES,
        ),
        ToolSpec(
            name="reject_proposal",
            description="Reject a calendar proposal and cancel its tentative projection.",
            args_schema=ApproveRejectArgs,
            return_schema=ProposalResult,
            callable_ref=overlay_tools.reject_proposal,
            action_risk=ActionRisk.WRITE,
        ),
    ]


def make_calendar_manifest(
    tools: CalendarTools,
    write_tools: CalendarWriteTools,
    held_event_store: HeldEventStore | None = None,
    overlay_tools: OverlayTools | None = None,
    *,
    schedule_task_fn: Callable[[ScheduleTaskArgs], Awaitable[ScheduleTaskResult]] | None = None,
    sync_engine: CalendarSyncEngine | None = None,
    overlay_store: OverlayStore | None = None,
    owner_email: str | None = None,
    calendar_ids: list[str] | None = None,
    key_provider: KeyProvider | None = None,
) -> ModuleManifest:
    """Build the Calendar module manifest with read and write scopes registered."""
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
            ToolSpec(
                name="block_focus_time",
                description="Create a self-only focus block on the owner's calendar.",
                args_schema=BlockFocusTimeArgs,
                return_schema=WriteResult,
                callable_ref=write_tools.block_focus_time,
                action_risk=ActionRisk.WRITE,
            ),
            ToolSpec(
                name="create_event",
                description="Create a calendar event, staging attendee events for review.",
                args_schema=CreateEventArgs,
                return_schema=WriteResult,
                callable_ref=write_tools.create_event,
                execute_callable_ref=write_tools.create_event_raw,
                action_risk=ActionRisk.HIGH_STAKES,
            ),
            ToolSpec(
                name="update_event",
                description="Update a calendar event, staging attendee events for review.",
                args_schema=UpdateEventArgs,
                return_schema=WriteResult,
                callable_ref=write_tools.update_event,
                execute_callable_ref=write_tools.update_event_raw,
                action_risk=ActionRisk.HIGH_STAKES,
            ),
            ToolSpec(
                name="move_event",
                description="Move a calendar event, staging attendee events for review.",
                args_schema=MoveEventArgs,
                return_schema=WriteResult,
                callable_ref=write_tools.move_event,
                execute_callable_ref=write_tools.move_event_raw,
                action_risk=ActionRisk.HIGH_STAKES,
            ),
            ToolSpec(
                name="cancel_event",
                description="Cancel a calendar event, staging attendee events for review.",
                args_schema=CancelEventArgs,
                return_schema=WriteResult,
                callable_ref=write_tools.cancel_event,
                execute_callable_ref=write_tools.cancel_event_raw,
                action_risk=ActionRisk.HIGH_STAKES,
            ),
            ToolSpec(
                name="respond_to_invite",
                description="Respond to a calendar invite after owner approval.",
                args_schema=RespondToInviteArgs,
                return_schema=WriteResult,
                callable_ref=write_tools.respond_to_invite,
                execute_callable_ref=write_tools.respond_to_invite_raw,
                action_risk=ActionRisk.HIGH_STAKES,
            ),
            ToolSpec(
                name="add_attendees",
                description="Add attendees to an event after owner approval when needed.",
                args_schema=AddAttendeesArgs,
                return_schema=WriteResult,
                callable_ref=write_tools.add_attendees,
                execute_callable_ref=write_tools.add_attendees_raw,
                action_risk=ActionRisk.HIGH_STAKES,
            ),
            ToolSpec(
                name="remove_attendees",
                description="Remove attendees from an event after owner approval when needed.",
                args_schema=RemoveAttendeesArgs,
                return_schema=WriteResult,
                callable_ref=write_tools.remove_attendees,
                execute_callable_ref=write_tools.remove_attendees_raw,
                action_risk=ActionRisk.HIGH_STAKES,
            ),
            ToolSpec(
                name="create_recurring_event",
                description="Create a recurring event, staging attendee events for review.",
                args_schema=CreateRecurringEventArgs,
                return_schema=WriteResult,
                callable_ref=write_tools.create_recurring_event,
                execute_callable_ref=write_tools.create_recurring_event_raw,
                action_risk=ActionRisk.HIGH_STAKES,
            ),
            ToolSpec(
                name="quick_add",
                description="Quick-add a self-only event on the owner's calendar.",
                args_schema=QuickAddArgs,
                return_schema=WriteResult,
                callable_ref=write_tools.quick_add,
                action_risk=ActionRisk.WRITE,
            ),
            ToolSpec(
                name="set_reminders",
                description="Set reminders on an event.",
                args_schema=SetRemindersArgs,
                return_schema=WriteResult,
                callable_ref=write_tools.set_reminders,
                action_risk=ActionRisk.WRITE,
            ),
            *(
                [
                    ToolSpec(
                        name="create_from_extract",
                        description=(
                            "Create an internal held tentative event from a sanitised extract."
                        ),
                        args_schema=CreateFromExtractArgs,
                        return_schema=HeldTentativeEvent,
                        callable_ref=partial(create_from_extract_tool, store=held_event_store),
                        action_risk=ActionRisk.WRITE,
                    ),
                    ToolSpec(
                        name="approve_held_event",
                        description=(
                            "Approve a held tentative event through the gated calendar write path."
                        ),
                        args_schema=HeldEventIdArgs,
                        return_schema=HeldTentativeEvent,
                        callable_ref=partial(
                            approve_held_event_tool,
                            store=held_event_store,
                            write_tools=write_tools,
                        ),
                        action_risk=ActionRisk.HIGH_STAKES,
                    ),
                    ToolSpec(
                        name="list_held_events",
                        description="List Calendar held tentative events by status.",
                        args_schema=ListHeldEventsArgs,
                        return_schema=HeldTentativeEventList,
                        callable_ref=partial(list_held_events_tool, store=held_event_store),
                        action_risk=ActionRisk.READ,
                    ),
                    ToolSpec(
                        name="discard_held_event",
                        description="Discard an internal held tentative event.",
                        args_schema=HeldEventIdArgs,
                        return_schema=HeldTentativeEvent,
                        callable_ref=partial(discard_held_event_tool, store=held_event_store),
                        action_risk=ActionRisk.WRITE,
                    ),
                ]
                if held_event_store is not None
                else []
            ),
            *(
                [
                    ToolSpec(
                        name="schedule_task",
                        description=(
                            "Find the earliest open focus-block slot for a task and create a "
                            "self-only focus-block calendar event. Returns the created event_id "
                            "and block times, or a message if no slot is available. Always auto "
                            "(self-only, no attendees)."
                        ),
                        args_schema=ScheduleTaskArgs,
                        return_schema=ScheduleTaskResult,
                        callable_ref=schedule_task_fn,
                        action_risk=ActionRisk.WRITE,
                    )
                ]
                if schedule_task_fn is not None
                else []
            ),
            *(make_calendar_overlay_manifest(overlay_tools) if overlay_tools is not None else []),
        ],
        proactive_hooks=build_calendar_hooks(
            sync_engine,
            tools._store,
            overlay_store,
            owner_email=owner_email,
            calendar_ids=calendar_ids,
            client=tools._client,
            key_provider=key_provider,
        )
        if sync_engine is not None
        and overlay_store is not None
        and owner_email is not None
        and calendar_ids is not None
        else [],
    )
