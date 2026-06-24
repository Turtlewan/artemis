"""Calendar module exports and Google scope registration.

The composition root owns activation: construct ``CalendarTools``, call
``make_calendar_manifest(tools, write_tools)``, then register that manifest with
the tool registry. CAL-a intentionally has no global singleton credentials or
stores.

TODO(CAL-b): compose_brain wiring.
"""

from artemis.integrations.google.scopes import register_google_scopes
from artemis.modules.calendar.cache import CalendarSyncEngine, EventCacheStore
from artemis.modules.calendar.client import CalendarClient, FakeCalendarClient, GoogleCalendarClient
from artemis.modules.calendar.manifest import CalendarTools, make_calendar_manifest
from artemis.modules.calendar.preferences import CalPrefs, PreferencesStore

register_google_scopes(
    "calendar",
    {
        "https://www.googleapis.com/auth/calendar.readonly",
    },
)

__all__ = [
    "CalPrefs",
    "CalendarClient",
    "CalendarSyncEngine",
    "CalendarTools",
    "EventCacheStore",
    "FakeCalendarClient",
    "GoogleCalendarClient",
    "PreferencesStore",
    "make_calendar_manifest",
]
