"""Google Calendar client port and off-hardware fake.

The concrete Google adapter lazy-imports ``googleapiclient`` so importing the
calendar module never requires the Calendar API package to be loaded. Retry
policy and reauth handling belong to callers; ``ReauthRequiredError`` is
propagated unchanged.
"""

from __future__ import annotations

from typing import Protocol, cast

from artemis.config import Settings
from artemis.integrations.google import GoogleCredentialsFactory


class InvalidSyncTokenError(Exception):
    """Raised when Google invalidates an incremental sync token."""


class CalendarClient(Protocol):
    """Port over Google Calendar v3 JSON-shaped read/write operations."""

    def list_calendars(self) -> list[dict[str, object]]:
        """Return raw Google calendar-list items."""
        ...

    def list_events(
        self,
        calendar_id: str,
        *,
        time_min: str | None = None,
        time_max: str | None = None,
        sync_token: str | None = None,
        page_token: str | None = None,
        max_results: int = 250,
        show_deleted: bool = False,
    ) -> dict[str, object]:
        """Return a raw Google events.list page."""
        ...

    def get_event(self, calendar_id: str, event_id: str) -> dict[str, object]:
        """Return one raw Google event resource."""
        ...

    def query_free_busy(
        self,
        time_min: str,
        time_max: str,
        items: list[dict[str, str]],
    ) -> dict[str, object]:
        """Return a raw Google freeBusy response."""
        ...

    def create_event(
        self,
        *,
        summary: str,
        start: str,
        end: str,
        description: str | None = None,
        location: str | None = None,
        attendees: tuple[str, ...] = (),
        calendar_id: str,
        recurrence: tuple[str, ...] = (),
        reminders: dict[str, object] | None = None,
        send_updates: str = "all",
    ) -> dict[str, object]:
        """Create an event. CAL-b owns write-tool policy."""
        ...

    def update_event(
        self,
        event_id: str,
        changes: dict[str, object],
        *,
        recurrence_scope: str,
        send_updates: str = "all",
    ) -> dict[str, object]:
        """Update an event. CAL-b owns write-tool policy."""
        ...

    def move_event(
        self,
        event_id: str,
        *,
        new_start: str,
        new_end: str,
        recurrence_scope: str,
        send_updates: str = "all",
    ) -> dict[str, object]:
        """Move an event. CAL-b owns write-tool policy."""
        ...

    def cancel_event(
        self,
        event_id: str,
        *,
        recurrence_scope: str,
        send_updates: str = "all",
    ) -> None:
        """Cancel an event. CAL-b owns write-tool policy."""
        ...

    def respond_to_invite(self, event_id: str, response: str) -> dict[str, object]:
        """Respond to an invite. CAL-b owns write-tool policy."""
        ...

    def add_attendees(
        self,
        event_id: str,
        attendee_emails: list[str],
        *,
        send_updates: str = "all",
    ) -> dict[str, object]:
        """Add event attendees. CAL-b owns write-tool policy."""
        ...

    def remove_attendees(
        self,
        event_id: str,
        attendee_emails: list[str],
        *,
        send_updates: str = "all",
    ) -> dict[str, object]:
        """Remove event attendees. CAL-b owns write-tool policy."""
        ...

    def quick_add(self, text: str, calendar_id: str) -> dict[str, object]:
        """Quick-add an event. CAL-b owns write-tool policy."""
        ...

    def set_reminders(
        self,
        event_id: str,
        reminders: list[dict[str, object]],
    ) -> dict[str, object]:
        """Set event reminders. CAL-b owns write-tool policy."""
        ...


class _Executable(Protocol):
    def execute(self) -> dict[str, object]:
        """Execute a googleapiclient request."""
        ...


class _CalendarListResource(Protocol):
    def list(self) -> _Executable:
        """Build a calendarList.list request."""
        ...


class _EventsResource(Protocol):
    def list(self, **kwargs: object) -> _Executable:
        """Build an events.list request."""
        ...

    def get(self, **kwargs: object) -> _Executable:
        """Build an events.get request."""
        ...


class _FreeBusyResource(Protocol):
    def query(self, *, body: dict[str, object]) -> _Executable:
        """Build a freebusy.query request."""
        ...


class _GoogleCalendarService(Protocol):
    def calendarList(self) -> _CalendarListResource:  # noqa: N802 — mirrors the Google API method name `service.calendarList()`
        """Return calendarList resource."""
        ...

    def events(self) -> _EventsResource:
        """Return events resource."""
        ...

    def freebusy(self) -> _FreeBusyResource:
        """Return freebusy resource."""
        ...


class GoogleCalendarClient:
    """Google Calendar v3 adapter over ``googleapiclient``."""

    def __init__(
        self, credentials_factory: GoogleCredentialsFactory, *, settings: Settings
    ) -> None:
        self._credentials_factory = credentials_factory
        self._settings = settings
        self._service: _GoogleCalendarService | None = None

    @property
    def service(self) -> _GoogleCalendarService:
        """Build and cache the googleapiclient Calendar service lazily."""
        if self._service is None:
            from googleapiclient.discovery import build  # type: ignore[import-untyped]

            credentials = self._credentials_factory.authorized_credentials()
            self._service = cast(
                _GoogleCalendarService,
                build("calendar", "v3", credentials=credentials),
            )
        return self._service

    def list_calendars(self) -> list[dict[str, object]]:
        result = self.service.calendarList().list().execute()
        return _dict_list(result.get("items", []))

    def list_events(
        self,
        calendar_id: str,
        *,
        time_min: str | None = None,
        time_max: str | None = None,
        sync_token: str | None = None,
        page_token: str | None = None,
        max_results: int = 250,
        show_deleted: bool = False,
    ) -> dict[str, object]:
        kwargs: dict[str, object] = {
            "calendarId": calendar_id,
            "maxResults": max_results,
            "showDeleted": show_deleted,
        }
        if sync_token is not None:
            kwargs["syncToken"] = sync_token
        else:
            if time_min is not None:
                kwargs["timeMin"] = time_min
            if time_max is not None:
                kwargs["timeMax"] = time_max
        if page_token is not None:
            kwargs["pageToken"] = page_token
        try:
            return self.service.events().list(**kwargs).execute()
        except Exception as exc:
            if _is_http_410(exc):
                raise InvalidSyncTokenError("Google Calendar sync token was invalidated") from exc
            raise

    def get_event(self, calendar_id: str, event_id: str) -> dict[str, object]:
        return self.service.events().get(calendarId=calendar_id, eventId=event_id).execute()

    def query_free_busy(
        self,
        time_min: str,
        time_max: str,
        items: list[dict[str, str]],
    ) -> dict[str, object]:
        body: dict[str, object] = {"timeMin": time_min, "timeMax": time_max, "items": items}
        return self.service.freebusy().query(body=body).execute()

    def create_event(
        self,
        *,
        summary: str,
        start: str,
        end: str,
        description: str | None = None,
        location: str | None = None,
        attendees: tuple[str, ...] = (),
        calendar_id: str,
        recurrence: tuple[str, ...] = (),
        reminders: dict[str, object] | None = None,
        send_updates: str = "all",
    ) -> dict[str, object]:
        raise NotImplementedError("CAL-b implements calendar writes")

    def update_event(
        self,
        event_id: str,
        changes: dict[str, object],
        *,
        recurrence_scope: str,
        send_updates: str = "all",
    ) -> dict[str, object]:
        raise NotImplementedError("CAL-b implements calendar writes")

    def move_event(
        self,
        event_id: str,
        *,
        new_start: str,
        new_end: str,
        recurrence_scope: str,
        send_updates: str = "all",
    ) -> dict[str, object]:
        raise NotImplementedError("CAL-b implements calendar writes")

    def cancel_event(
        self,
        event_id: str,
        *,
        recurrence_scope: str,
        send_updates: str = "all",
    ) -> None:
        raise NotImplementedError("CAL-b implements calendar writes")

    def respond_to_invite(self, event_id: str, response: str) -> dict[str, object]:
        raise NotImplementedError("CAL-b implements calendar writes")

    def add_attendees(
        self,
        event_id: str,
        attendee_emails: list[str],
        *,
        send_updates: str = "all",
    ) -> dict[str, object]:
        raise NotImplementedError("CAL-b implements calendar writes")

    def remove_attendees(
        self,
        event_id: str,
        attendee_emails: list[str],
        *,
        send_updates: str = "all",
    ) -> dict[str, object]:
        raise NotImplementedError("CAL-b implements calendar writes")

    def quick_add(self, text: str, calendar_id: str) -> dict[str, object]:
        raise NotImplementedError("CAL-b implements calendar writes")

    def set_reminders(
        self,
        event_id: str,
        reminders: list[dict[str, object]],
    ) -> dict[str, object]:
        raise NotImplementedError("CAL-b implements calendar writes")


class FakeCalendarClient:
    """Deterministic off-hardware calendar fake."""

    def __init__(
        self,
        calendar_list: list[dict[str, object]],
        events_by_calendar: dict[str, list[dict[str, object]]],
        free_busy_response: dict[str, object],
    ) -> None:
        self.calendar_list = calendar_list
        self.events_by_calendar = events_by_calendar
        self.free_busy_response = free_busy_response
        self.incremental_events_by_calendar: dict[str, list[dict[str, object]]] = {}
        self.raise_invalid_sync_token_once = False
        self.list_events_calls: list[dict[str, object]] = []

    def set_incremental_events(
        self,
        calendar_id: str,
        events: list[dict[str, object]],
        *,
        next_sync_token: str = "fake-token-2",
    ) -> None:
        """Configure the next incremental response for one calendar."""
        self.incremental_events_by_calendar[calendar_id] = events
        self._next_sync_token = next_sync_token

    def list_calendars(self) -> list[dict[str, object]]:
        return self.calendar_list

    def list_events(
        self,
        calendar_id: str,
        *,
        time_min: str | None = None,
        time_max: str | None = None,
        sync_token: str | None = None,
        page_token: str | None = None,
        max_results: int = 250,
        show_deleted: bool = False,
    ) -> dict[str, object]:
        self.list_events_calls.append(
            {
                "calendar_id": calendar_id,
                "time_min": time_min,
                "time_max": time_max,
                "sync_token": sync_token,
                "page_token": page_token,
                "max_results": max_results,
                "show_deleted": show_deleted,
            }
        )
        if sync_token is not None:
            if self.raise_invalid_sync_token_once:
                self.raise_invalid_sync_token_once = False
                raise InvalidSyncTokenError("fake invalid sync token")
            return {
                "items": self.incremental_events_by_calendar.get(calendar_id, []),
                "nextSyncToken": getattr(self, "_next_sync_token", "fake-token-2"),
            }
        return {
            "items": self.events_by_calendar.get(calendar_id, []),
            "nextSyncToken": "fake-token-1",
        }

    def get_event(self, calendar_id: str, event_id: str) -> dict[str, object]:
        for event in self.events_by_calendar.get(calendar_id, []):
            if event.get("id") == event_id:
                return event
        raise KeyError(event_id)

    def query_free_busy(
        self,
        time_min: str,
        time_max: str,
        items: list[dict[str, str]],
    ) -> dict[str, object]:
        return self.free_busy_response

    def create_event(
        self,
        *,
        summary: str,
        start: str,
        end: str,
        description: str | None = None,
        location: str | None = None,
        attendees: tuple[str, ...] = (),
        calendar_id: str,
        recurrence: tuple[str, ...] = (),
        reminders: dict[str, object] | None = None,
        send_updates: str = "all",
    ) -> dict[str, object]:
        raise NotImplementedError("CAL-b implements calendar writes")

    def update_event(
        self,
        event_id: str,
        changes: dict[str, object],
        *,
        recurrence_scope: str,
        send_updates: str = "all",
    ) -> dict[str, object]:
        raise NotImplementedError("CAL-b implements calendar writes")

    def move_event(
        self,
        event_id: str,
        *,
        new_start: str,
        new_end: str,
        recurrence_scope: str,
        send_updates: str = "all",
    ) -> dict[str, object]:
        raise NotImplementedError("CAL-b implements calendar writes")

    def cancel_event(
        self,
        event_id: str,
        *,
        recurrence_scope: str,
        send_updates: str = "all",
    ) -> None:
        raise NotImplementedError("CAL-b implements calendar writes")

    def respond_to_invite(self, event_id: str, response: str) -> dict[str, object]:
        raise NotImplementedError("CAL-b implements calendar writes")

    def add_attendees(
        self,
        event_id: str,
        attendee_emails: list[str],
        *,
        send_updates: str = "all",
    ) -> dict[str, object]:
        raise NotImplementedError("CAL-b implements calendar writes")

    def remove_attendees(
        self,
        event_id: str,
        attendee_emails: list[str],
        *,
        send_updates: str = "all",
    ) -> dict[str, object]:
        raise NotImplementedError("CAL-b implements calendar writes")

    def quick_add(self, text: str, calendar_id: str) -> dict[str, object]:
        raise NotImplementedError("CAL-b implements calendar writes")

    def set_reminders(
        self,
        event_id: str,
        reminders: list[dict[str, object]],
    ) -> dict[str, object]:
        raise NotImplementedError("CAL-b implements calendar writes")


def _dict_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _is_http_410(exc: Exception) -> bool:
    status_code = getattr(getattr(exc, "resp", None), "status", None)
    return status_code == 410
