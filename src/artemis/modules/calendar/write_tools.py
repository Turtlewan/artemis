"""Calendar write schemas and runtime-gated write tools."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Literal, Protocol, cast

from pydantic import BaseModel, ConfigDict, Field

from artemis.modules.calendar.cache import EventCacheStore
from artemis.modules.calendar.client import CalendarClient
from artemis.modules.calendar.gating import dispatch
from artemis.modules.calendar.preferences import CalPrefs
from artemis.staging.service import ActionStagingService

if TYPE_CHECKING:
    from artemis.modules.calendar.activity_log import ActivityLog

RecurrenceScope = Literal["THIS_EVENT", "THIS_AND_FOLLOWING", "ALL_EVENTS"]
SendUpdates = Literal["all", "externalOnly", "none"]
ReminderMethod = Literal["email", "popup"]


class Reminder(BaseModel):
    """Google reminder override."""

    model_config = ConfigDict(frozen=True)

    method: ReminderMethod
    minutes_before: int


class CreateEventArgs(BaseModel):
    """Arguments for creating a calendar event."""

    model_config = ConfigDict(frozen=True)

    summary: str
    start_datetime: str
    end_datetime: str
    description: str | None = None
    location: str | None = None
    attendee_emails: list[str] = Field(default_factory=list)
    calendar_id: str | None = None
    recurrence: list[str] = Field(default_factory=list)
    reminders: list[Reminder] = Field(default_factory=list)


class UpdateEventArgs(BaseModel):
    """Arguments for updating one event."""

    model_config = ConfigDict(frozen=True)

    event_id: str
    summary: str | None = None
    start_datetime: str | None = None
    end_datetime: str | None = None
    description: str | None = None
    location: str | None = None
    recurrence_scope: RecurrenceScope = "THIS_EVENT"


class MoveEventArgs(BaseModel):
    """Arguments for moving one event."""

    model_config = ConfigDict(frozen=True)

    event_id: str
    new_start_datetime: str
    new_end_datetime: str
    recurrence_scope: RecurrenceScope = "THIS_EVENT"


class CancelEventArgs(BaseModel):
    """Arguments for cancelling one event."""

    model_config = ConfigDict(frozen=True)

    event_id: str
    recurrence_scope: RecurrenceScope = "THIS_EVENT"


class RespondToInviteArgs(BaseModel):
    """Arguments for responding to an invite."""

    model_config = ConfigDict(frozen=True)

    event_id: str
    response: Literal["accepted", "declined", "tentative"]


class AddAttendeesArgs(BaseModel):
    """Arguments for adding event attendees."""

    model_config = ConfigDict(frozen=True)

    event_id: str
    attendee_emails: list[str]


class RemoveAttendeesArgs(BaseModel):
    """Arguments for removing event attendees."""

    model_config = ConfigDict(frozen=True)

    event_id: str
    attendee_emails: list[str]


class CreateRecurringEventArgs(BaseModel):
    """Arguments for creating a recurring event."""

    model_config = ConfigDict(frozen=True)

    summary: str
    start_datetime: str
    end_datetime: str
    rrule: str
    attendee_emails: list[str] = Field(default_factory=list)
    description: str | None = None
    calendar_id: str | None = None


class QuickAddArgs(BaseModel):
    """Arguments for Google quickAdd."""

    model_config = ConfigDict(frozen=True)

    text: str
    calendar_id: str | None = None


class BlockFocusTimeArgs(BaseModel):
    """Arguments for creating a self-only focus block."""

    model_config = ConfigDict(frozen=True)

    start_datetime: str
    end_datetime: str
    title: str = "Focus time"
    calendar_id: str | None = None


class SetRemindersArgs(BaseModel):
    """Arguments for replacing event reminders."""

    model_config = ConfigDict(frozen=True)

    event_id: str
    reminders: list[Reminder]


class WriteResult(BaseModel):
    """Result for an executed calendar write."""

    model_config = ConfigDict(frozen=True)

    event_id: str
    summary: str
    tool_name: str
    status: Literal["executed", "staged_for_review"]


class StagedResult(BaseModel):
    """Result for a calendar write staged for owner review."""

    model_config = ConfigDict(frozen=True)

    pending_action_id: str
    summary: str
    status: Literal["staged_for_review"] = "staged_for_review"


class CalendarWriteError(Exception):
    """Raised when a calendar write fails."""

    def __init__(
        self,
        message: str,
        *,
        event_id: str | None = None,
        http_status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.event_id = event_id
        self.http_status = http_status


class _Cache(Protocol):
    def invalidate(self, event_id: str, calendar_id: str) -> None:
        """Invalidate one cached event."""
        ...


class CalendarWriteTools:
    """Front-door gated calendar write tools plus classifier-free raw twins."""

    def __init__(
        self,
        client: CalendarClient,
        cache: EventCacheStore,
        prefs: CalPrefs,
        staging: ActionStagingService,
        activity_log: ActivityLog,
    ) -> None:
        self._client = client
        self._cache: _Cache = cache
        self._prefs = prefs
        self._staging = staging
        self._activity_log = activity_log

    async def create_event(self, args: CreateEventArgs) -> WriteResult | StagedResult:
        async def execute_fn() -> WriteResult:
            return await self.create_event_raw(args)

        async def stage_fn() -> StagedResult:
            return self._stage("create_event", args, _attendee_summary(args.attendee_emails))

        return await dispatch(
            "create_event",
            None,
            args.attendee_emails,
            self._owner_email(),
            execute_fn=execute_fn,
            stage_fn=stage_fn,
            log_fn=self._activity_log.record,
        )

    async def create_event_raw(self, args: CreateEventArgs) -> WriteResult:
        calendar_id = self._calendar_id(args.calendar_id)
        reminders = _reminders_body(args.reminders)
        event = self._call_write(
            "create_event",
            None,
            lambda: self._client.create_event(
                summary=args.summary,
                start=args.start_datetime,
                end=args.end_datetime,
                description=args.description,
                location=args.location,
                attendees=tuple(args.attendee_emails),
                calendar_id=calendar_id,
                recurrence=tuple(args.recurrence),
                reminders=reminders,
                send_updates="none",
            ),
        )
        event_id = _event_id(event)
        self._cache.invalidate(event_id, calendar_id)
        return WriteResult(
            event_id=event_id,
            summary=_event_summary(event, args.summary),
            tool_name="calendar.create_event",
            status="executed",
        )

    async def update_event(self, args: UpdateEventArgs) -> WriteResult | StagedResult:
        event = self._existing_event(args.event_id)
        attendees = _attendees(event)

        async def execute_fn() -> WriteResult:
            return await self.update_event_raw(args)

        async def stage_fn() -> StagedResult:
            return self._stage("update_event", args, _attendee_summary(attendees))

        return await dispatch(
            "update_event",
            args.event_id,
            attendees,
            self._owner_email(),
            execute_fn=execute_fn,
            stage_fn=stage_fn,
            log_fn=self._activity_log.record,
        )

    async def update_event_raw(self, args: UpdateEventArgs) -> WriteResult:
        changes: dict[str, object] = {}
        if args.summary is not None:
            changes["summary"] = args.summary
        if args.start_datetime is not None:
            changes["start"] = {"dateTime": args.start_datetime}
        if args.end_datetime is not None:
            changes["end"] = {"dateTime": args.end_datetime}
        if args.description is not None:
            changes["description"] = args.description
        if args.location is not None:
            changes["location"] = args.location
        event = self._call_write(
            "update_event",
            args.event_id,
            lambda: self._client.update_event(
                args.event_id,
                changes,
                recurrence_scope=args.recurrence_scope,
                send_updates="none",
            ),
        )
        calendar_id = self._calendar_id(None)
        self._cache.invalidate(args.event_id, calendar_id)
        return WriteResult(
            event_id=args.event_id,
            summary=_event_summary(event, args.summary or args.event_id),
            tool_name="calendar.update_event",
            status="executed",
        )

    async def move_event(self, args: MoveEventArgs) -> WriteResult | StagedResult:
        event = self._existing_event(args.event_id)
        attendees = _attendees(event)

        async def execute_fn() -> WriteResult:
            return await self.move_event_raw(args)

        async def stage_fn() -> StagedResult:
            return self._stage("move_event", args, _attendee_summary(attendees))

        return await dispatch(
            "move_event",
            args.event_id,
            attendees,
            self._owner_email(),
            execute_fn=execute_fn,
            stage_fn=stage_fn,
            log_fn=self._activity_log.record,
        )

    async def move_event_raw(self, args: MoveEventArgs) -> WriteResult:
        event = self._call_write(
            "move_event",
            args.event_id,
            lambda: self._client.move_event(
                args.event_id,
                new_start=args.new_start_datetime,
                new_end=args.new_end_datetime,
                recurrence_scope=args.recurrence_scope,
                send_updates="none",
            ),
        )
        calendar_id = self._calendar_id(None)
        self._cache.invalidate(args.event_id, calendar_id)
        return WriteResult(
            event_id=args.event_id,
            summary=_event_summary(event, args.event_id),
            tool_name="calendar.move_event",
            status="executed",
        )

    async def cancel_event(self, args: CancelEventArgs) -> WriteResult | StagedResult:
        event = self._existing_event(args.event_id)
        attendees = _attendees(event)

        async def execute_fn() -> WriteResult:
            return await self.cancel_event_raw(args)

        async def stage_fn() -> StagedResult:
            return self._stage("cancel_event", args, _attendee_summary(attendees))

        return await dispatch(
            "cancel_event",
            args.event_id,
            attendees,
            self._owner_email(),
            execute_fn=execute_fn,
            stage_fn=stage_fn,
            log_fn=self._activity_log.record,
        )

    async def cancel_event_raw(self, args: CancelEventArgs) -> WriteResult:
        summary = _event_summary(self._existing_event(args.event_id), args.event_id)
        self._call_write(
            "cancel_event",
            args.event_id,
            lambda: self._client.cancel_event(
                args.event_id,
                recurrence_scope=args.recurrence_scope,
                send_updates="none",
            ),
        )
        calendar_id = self._calendar_id(None)
        self._cache.invalidate(args.event_id, calendar_id)
        return WriteResult(
            event_id=args.event_id,
            summary=summary,
            tool_name="calendar.cancel_event",
            status="executed",
        )

    async def respond_to_invite(self, args: RespondToInviteArgs) -> WriteResult | StagedResult:
        async def execute_fn() -> WriteResult:
            return await self.respond_to_invite_raw(args)

        async def stage_fn() -> StagedResult:
            return self._stage("respond_to_invite", args, f"RSVP {args.response}")

        return await dispatch(
            "respond_to_invite",
            args.event_id,
            [],
            self._owner_email(),
            execute_fn=execute_fn,
            stage_fn=stage_fn,
            log_fn=self._activity_log.record,
        )

    async def respond_to_invite_raw(self, args: RespondToInviteArgs) -> WriteResult:
        event = self._call_write(
            "respond_to_invite",
            args.event_id,
            lambda: self._client.respond_to_invite(args.event_id, args.response),
        )
        calendar_id = self._calendar_id(None)
        self._cache.invalidate(args.event_id, calendar_id)
        return WriteResult(
            event_id=args.event_id,
            summary=_event_summary(event, args.event_id),
            tool_name="calendar.respond_to_invite",
            status="executed",
        )

    async def add_attendees(self, args: AddAttendeesArgs) -> WriteResult | StagedResult:
        event = self._existing_event(args.event_id)
        attendees = [*_attendees(event), *args.attendee_emails]

        async def execute_fn() -> WriteResult:
            return await self.add_attendees_raw(args)

        async def stage_fn() -> StagedResult:
            return self._stage("add_attendees", args, _attendee_summary(attendees))

        return await dispatch(
            "add_attendees",
            args.event_id,
            attendees,
            self._owner_email(),
            execute_fn=execute_fn,
            stage_fn=stage_fn,
            log_fn=self._activity_log.record,
        )

    async def add_attendees_raw(self, args: AddAttendeesArgs) -> WriteResult:
        event = self._call_write(
            "add_attendees",
            args.event_id,
            lambda: self._client.add_attendees(
                args.event_id,
                args.attendee_emails,
                send_updates="all",
            ),
        )
        calendar_id = self._calendar_id(None)
        self._cache.invalidate(args.event_id, calendar_id)
        return WriteResult(
            event_id=args.event_id,
            summary=_event_summary(event, args.event_id),
            tool_name="calendar.add_attendees",
            status="executed",
        )

    async def remove_attendees(self, args: RemoveAttendeesArgs) -> WriteResult | StagedResult:
        event = self._existing_event(args.event_id)
        attendees = [*_attendees(event), *args.attendee_emails]

        async def execute_fn() -> WriteResult:
            return await self.remove_attendees_raw(args)

        async def stage_fn() -> StagedResult:
            return self._stage("remove_attendees", args, _attendee_summary(attendees))

        return await dispatch(
            "remove_attendees",
            args.event_id,
            attendees,
            self._owner_email(),
            execute_fn=execute_fn,
            stage_fn=stage_fn,
            log_fn=self._activity_log.record,
        )

    async def remove_attendees_raw(self, args: RemoveAttendeesArgs) -> WriteResult:
        event = self._call_write(
            "remove_attendees",
            args.event_id,
            lambda: self._client.remove_attendees(
                args.event_id,
                args.attendee_emails,
                send_updates="all",
            ),
        )
        calendar_id = self._calendar_id(None)
        self._cache.invalidate(args.event_id, calendar_id)
        return WriteResult(
            event_id=args.event_id,
            summary=_event_summary(event, args.event_id),
            tool_name="calendar.remove_attendees",
            status="executed",
        )

    async def create_recurring_event(
        self, args: CreateRecurringEventArgs
    ) -> WriteResult | StagedResult:
        async def execute_fn() -> WriteResult:
            return await self.create_recurring_event_raw(args)

        async def stage_fn() -> StagedResult:
            return self._stage(
                "create_recurring_event",
                args,
                _attendee_summary(args.attendee_emails),
            )

        return await dispatch(
            "create_recurring_event",
            None,
            args.attendee_emails,
            self._owner_email(),
            execute_fn=execute_fn,
            stage_fn=stage_fn,
            log_fn=self._activity_log.record,
        )

    async def create_recurring_event_raw(self, args: CreateRecurringEventArgs) -> WriteResult:
        calendar_id = self._calendar_id(args.calendar_id)
        event = self._call_write(
            "create_recurring_event",
            None,
            lambda: self._client.create_event(
                summary=args.summary,
                start=args.start_datetime,
                end=args.end_datetime,
                description=args.description,
                attendees=tuple(args.attendee_emails),
                calendar_id=calendar_id,
                recurrence=(args.rrule,),
                send_updates="none",
            ),
        )
        event_id = _event_id(event)
        self._cache.invalidate(event_id, calendar_id)
        return WriteResult(
            event_id=event_id,
            summary=_event_summary(event, args.summary),
            tool_name="calendar.create_recurring_event",
            status="executed",
        )

    async def quick_add(self, args: QuickAddArgs) -> WriteResult:
        calendar_id = self._calendar_id(args.calendar_id)
        event = self._call_write(
            "quick_add",
            None,
            lambda: self._client.quick_add(args.text, calendar_id),
        )
        event_id = _event_id(event)
        self._cache.invalidate(event_id, calendar_id)
        result = WriteResult(
            event_id=event_id,
            summary=_event_summary(event, args.text),
            tool_name="calendar.quick_add",
            status="executed",
        )
        self._activity_log.record(result)
        return result

    async def block_focus_time(self, args: BlockFocusTimeArgs) -> WriteResult:
        result = await self.block_focus_time_raw(args)
        self._activity_log.record(result)
        return result

    async def block_focus_time_raw(self, args: BlockFocusTimeArgs) -> WriteResult:
        calendar_id = self._calendar_id(args.calendar_id)
        event = self._call_write(
            "block_focus_time",
            None,
            lambda: self._client.create_event(
                summary=args.title,
                start=args.start_datetime,
                end=args.end_datetime,
                calendar_id=calendar_id,
                send_updates="none",
            ),
        )
        event_id = _event_id(event)
        self._cache.invalidate(event_id, calendar_id)
        return WriteResult(
            event_id=event_id,
            summary=_event_summary(event, args.title),
            tool_name="calendar.block_focus_time",
            status="executed",
        )

    async def set_reminders(self, args: SetRemindersArgs) -> WriteResult:
        result = await self.set_reminders_raw(args)
        self._activity_log.record(result)
        return result

    async def set_reminders_raw(self, args: SetRemindersArgs) -> WriteResult:
        reminders = [_reminder_dict(reminder) for reminder in args.reminders]
        event = self._call_write(
            "set_reminders",
            args.event_id,
            lambda: self._client.set_reminders(args.event_id, reminders),
        )
        calendar_id = self._calendar_id(None)
        self._cache.invalidate(args.event_id, calendar_id)
        return WriteResult(
            event_id=args.event_id,
            summary=_event_summary(event, args.event_id),
            tool_name="calendar.set_reminders",
            status="executed",
        )

    def _stage(
        self,
        tool_name: str,
        args: BaseModel,
        effect: str,
    ) -> StagedResult:
        summary = f"{tool_name.replace('_', ' ')}: {effect}; pending owner approval"
        action = self._staging.stage(
            module="calendar",
            tool=f"calendar.{tool_name}",
            args=cast(dict[str, object], args.model_dump()),
            summary=summary,
        )
        return StagedResult(pending_action_id=action.id, summary=action.summary)

    def _existing_event(self, event_id: str) -> dict[str, object]:
        return self._client.get_event(self._calendar_id(None), event_id)

    def _owner_email(self) -> str:
        return self._prefs.owner_email or ""

    def _calendar_id(self, calendar_id: str | None) -> str:
        return calendar_id or self._prefs.default_write_calendar

    def _call_write(
        self,
        method: str,
        event_id: str | None,
        fn: _WriteCall,
    ) -> dict[str, object]:
        try:
            result = fn()
        except CalendarWriteError:
            raise
        except Exception as exc:
            raise CalendarWriteError(str(exc), event_id=event_id) from exc
        if result is None:
            return {}
        return result


type _WriteCall = Callable[[], dict[str, object] | None]


def _event_id(event: dict[str, object]) -> str:
    value = event.get("id")
    return value if isinstance(value, str) and value else "unknown"


def _event_summary(event: dict[str, object], fallback: str) -> str:
    value = event.get("summary")
    return value if isinstance(value, str) and value else fallback


def _attendees(event: dict[str, object]) -> list[str]:
    value = event.get("attendees")
    if not isinstance(value, list):
        return []
    emails: list[str] = []
    for item in value:
        if isinstance(item, dict):
            email = item.get("email")
            if isinstance(email, str):
                emails.append(email)
    return emails


def _attendee_summary(attendees: Sequence[str]) -> str:
    if not attendees:
        return "no attendees"
    return f"has attendees {', '.join(attendees)}"


def _reminder_dict(reminder: Reminder) -> dict[str, object]:
    return {"method": reminder.method, "minutes": reminder.minutes_before}


def _reminders_body(reminders: Sequence[Reminder]) -> dict[str, object] | None:
    if not reminders:
        return None
    return {"useDefault": False, "overrides": [_reminder_dict(reminder) for reminder in reminders]}
