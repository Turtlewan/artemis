"""Owner-private event cache and Google Calendar incremental sync."""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import cast

from artemis import paths
from artemis.config import Settings
from artemis.data.sqlcipher import sqlcipher_open
from artemis.identity.key_provider import KeyProvider
from artemis.identity.scope import OWNER_PRIVATE
from artemis.memory.schema import now_iso
from artemis.modules.calendar.client import CalendarClient, InvalidSyncTokenError
from artemis.modules.calendar.preferences import CalPrefs
from artemis.reactions import DomainEvent, EventType

logger = logging.getLogger(__name__)


def _noop_emit(_e: DomainEvent) -> None:
    """Default event sink used when no reaction bus is composed."""


@dataclass(frozen=True)
class CachedEvent:
    """Cached Google event.

    Text fields and ``raw_json`` are untrusted source data when
    ``externally_authored`` is true. CAL-a only tags provenance; CAL-d owns LLM
    quarantine before rendering external text into prompts.
    """

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
    creator_email: str | None
    externally_authored: bool
    is_overlay_projection: bool
    overlay_proposal_id: str | None
    raw_json: str


@dataclass(frozen=True)
class SyncResult:
    """Summary of one calendar sync."""

    calendar_id: str
    events_added: int
    events_updated: int
    events_deleted: int
    full_sync: bool


class EventCacheStore:
    """SQLCipher-backed owner-private cache for read tools."""

    def __init__(self, settings: Settings, key_provider: KeyProvider) -> None:
        self._settings = settings
        self._key_provider = key_provider

    def _db_path(self) -> Path:
        """Return the dev path; Mini vault-path reconciliation is deferred."""
        return paths.scope_dir(self._settings, OWNER_PRIVATE) / "calendar" / "event_cache.db"

    def _connect(self) -> sqlite3.Connection:
        key = self._key_provider.dek_for_scope(OWNER_PRIVATE)
        db_path = self._db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        key_hex = key.as_hex()
        conn = sqlcipher_open(db_path, key_hex)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS events ("
            "event_id TEXT NOT NULL, calendar_id TEXT NOT NULL, summary TEXT NOT NULL, "
            "description TEXT, location TEXT, start_dt TEXT NOT NULL, end_dt TEXT NOT NULL, "
            "status TEXT NOT NULL, attendees TEXT NOT NULL, organizer_email TEXT, "
            "creator_email TEXT, externally_authored INTEGER NOT NULL, "
            "is_overlay_projection INTEGER NOT NULL, overlay_proposal_id TEXT, "
            "raw_json TEXT NOT NULL, PRIMARY KEY (event_id, calendar_id))"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS sync_tokens ("
            "calendar_id TEXT PRIMARY KEY, sync_token TEXT NOT NULL)"
        )
        return conn

    def upsert(self, event: CachedEvent) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event.event_id,
                    event.calendar_id,
                    event.summary,
                    event.description,
                    event.location,
                    event.start_dt,
                    event.end_dt,
                    event.status,
                    json.dumps(event.attendees),
                    event.organizer_email,
                    event.creator_email,
                    int(event.externally_authored),
                    int(event.is_overlay_projection),
                    event.overlay_proposal_id,
                    event.raw_json,
                ),
            )

    def delete(self, event_id: str, calendar_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM events WHERE event_id=? AND calendar_id=?", (event_id, calendar_id)
            )

    def invalidate(self, event_id: str, calendar_id: str) -> None:
        """Evict one stale cached row after a future CAL-b write."""
        self.delete(event_id, calendar_id)

    def get_sync_token(self, calendar_id: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT sync_token FROM sync_tokens WHERE calendar_id=?",
                (calendar_id,),
            ).fetchone()
        return None if row is None else str(row[0])

    def set_sync_token(self, calendar_id: str, token: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO sync_tokens (calendar_id, sync_token) VALUES (?, ?) "
                "ON CONFLICT(calendar_id) DO UPDATE SET sync_token=excluded.sync_token",
                (calendar_id, token),
            )

    def query_events(
        self,
        *,
        calendar_ids: list[str] | None = None,
        time_min: str | None = None,
        time_max: str | None = None,
        status_filter: list[str] | None = None,
    ) -> list[CachedEvent]:
        clauses: list[str] = []
        params: list[object] = []
        if calendar_ids:
            placeholders = ", ".join("?" for _ in calendar_ids)
            clauses.append(f"calendar_id IN ({placeholders})")
            params.extend(calendar_ids)
        if time_min is not None:
            clauses.append("end_dt > ?")
            params.append(time_min)
        if time_max is not None:
            clauses.append("start_dt < ?")
            params.append(time_max)
        if status_filter is None:
            clauses.append("status != ?")
            params.append("cancelled")
        elif status_filter:
            placeholders = ", ".join("?" for _ in status_filter)
            clauses.append(f"status IN ({placeholders})")
            params.extend(status_filter)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM events{where} ORDER BY start_dt ASC", params
            ).fetchall()
        return [_event_from_row(row) for row in rows]

    def clear_calendar(self, calendar_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM events WHERE calendar_id=?", (calendar_id,))
            conn.execute("DELETE FROM sync_tokens WHERE calendar_id=?", (calendar_id,))


class CalendarSyncEngine:
    """Incremental sync from Google Calendar into the owner-private cache."""

    def __init__(
        self,
        client: CalendarClient,
        store: EventCacheStore,
        prefs: CalPrefs,
        *,
        emit: Callable[[DomainEvent], None] = _noop_emit,
    ) -> None:
        self._client = client
        self._store = store
        self._prefs = prefs
        self._emit = emit

    def _emit_event_ingested(self, event: CachedEvent) -> None:
        """Emit scalar-only calendar ingest payload; external text stays in the cache."""
        try:
            self._emit(
                DomainEvent(
                    event_type=EventType.EVENT_INGESTED,
                    source_module="calendar",
                    payload={
                        "event_id": event.event_id,
                        "calendar_id": event.calendar_id,
                        "start_dt": event.start_dt,
                        "end_dt": event.end_dt,
                        "externally_authored": event.externally_authored,
                    },
                    occurred_at=now_iso(),
                    dedup_key=f"event-ingested:{event.event_id}:{event.calendar_id}",
                )
            )
        except Exception:
            logger.warning(
                "calendar event-ingested emit failed for %s/%s",
                event.calendar_id,
                event.event_id,
                exc_info=True,
            )

    def _tag_externally_authored(self, event_raw: dict[str, object], owner_email: str) -> bool:
        owner = owner_email.casefold()
        for field in ("organizer", "creator"):
            value = event_raw.get(field)
            if isinstance(value, dict):
                email = value.get("email")
                if isinstance(email, str) and email.casefold() != owner:
                    return True
        return False

    def _parse_overlay_marker(self, event_raw: dict[str, object]) -> tuple[bool, str | None]:
        """Return CAL-c overlay marker state.

        Overlay projections are trusted own-holds and take precedence over the
        external-author tag. Spoofing requires write access to the owner's
        calendar private extendedProperties, which is already owner-level access.
        """
        props = event_raw.get("extendedProperties")
        if not isinstance(props, dict):
            return (False, None)
        private = props.get("private")
        if not isinstance(private, dict):
            return (False, None)
        marker = private.get("artemis_overlay")
        if isinstance(marker, str) and marker:
            return (True, marker)
        return (False, None)

    def _to_cached_event(
        self,
        event_raw: dict[str, object],
        calendar_id: str,
        owner_email: str,
    ) -> CachedEvent:
        is_overlay, proposal_id = self._parse_overlay_marker(event_raw)
        organizer_email = _email_from_nested(event_raw, "organizer")
        creator_email = _email_from_nested(event_raw, "creator")
        return CachedEvent(
            event_id=str(event_raw.get("id", "")),
            calendar_id=calendar_id,
            summary=str(event_raw.get("summary", "")),
            description=_optional_str(event_raw.get("description")),
            location=_optional_str(event_raw.get("location")),
            start_dt=_event_time(event_raw.get("start")),
            end_dt=_event_time(event_raw.get("end")),
            status=str(event_raw.get("status", "confirmed")),
            attendees=_attendee_emails(event_raw.get("attendees")),
            organizer_email=organizer_email,
            creator_email=creator_email,
            externally_authored=False
            if is_overlay
            else self._tag_externally_authored(event_raw, owner_email),
            is_overlay_projection=is_overlay,
            overlay_proposal_id=proposal_id,
            raw_json=json.dumps(event_raw),
        )

    def sync(self, calendar_id: str, owner_email: str) -> SyncResult:
        sync_token = self._store.get_sync_token(calendar_id)
        if sync_token is None:
            return self._full_sync(calendar_id, owner_email)
        try:
            return self._incremental_sync(calendar_id, owner_email, sync_token)
        except InvalidSyncTokenError:
            self._store.clear_calendar(calendar_id)
            return self._full_sync(calendar_id, owner_email)

    def sync_all(self, calendar_ids: list[str], owner_email: str) -> list[SyncResult]:
        return [self.sync(calendar_id, owner_email) for calendar_id in calendar_ids]

    def _full_sync(self, calendar_id: str, owner_email: str) -> SyncResult:
        time_min, time_max = self._sync_window()
        self._store.clear_calendar(calendar_id)
        added = 0
        next_token = ""
        page_token: str | None = None
        while True:
            page = self._client.list_events(
                calendar_id,
                time_min=time_min,
                time_max=time_max,
                page_token=page_token,
                show_deleted=False,
            )
            for event_raw in _raw_items(page):
                if event_raw.get("status") == "cancelled":
                    continue
                cached = self._to_cached_event(event_raw, calendar_id, owner_email)
                self._store.upsert(cached)
                self._emit_event_ingested(cached)
                added += 1
            page_token = _optional_str(page.get("nextPageToken"))
            next_token = str(page.get("nextSyncToken", next_token))
            if page_token is None:
                break
        if next_token:
            self._store.set_sync_token(calendar_id, next_token)
        return SyncResult(calendar_id, added, 0, 0, True)

    def _incremental_sync(
        self,
        calendar_id: str,
        owner_email: str,
        sync_token: str,
    ) -> SyncResult:
        added = 0
        updated = 0
        deleted = 0
        next_token = ""
        page_token: str | None = None
        while True:
            page = self._client.list_events(
                calendar_id,
                sync_token=sync_token,
                page_token=page_token,
                show_deleted=True,
            )
            for event_raw in _raw_items(page):
                event_id = str(event_raw.get("id", ""))
                if event_raw.get("status") == "cancelled":
                    self._store.delete(event_id, calendar_id)
                    deleted += 1
                else:
                    existed = any(
                        event.event_id == event_id
                        for event in self._store.query_events(
                            calendar_ids=[calendar_id],
                            status_filter=["confirmed", "tentative", "cancelled"],
                        )
                    )
                    cached = self._to_cached_event(event_raw, calendar_id, owner_email)
                    self._store.upsert(cached)
                    self._emit_event_ingested(cached)
                    if existed:
                        updated += 1
                    else:
                        added += 1
            page_token = _optional_str(page.get("nextPageToken"))
            next_token = str(page.get("nextSyncToken", next_token))
            if page_token is None:
                break
        if next_token:
            self._store.set_sync_token(calendar_id, next_token)
        return SyncResult(calendar_id, added, updated, deleted, False)

    def _sync_window(self) -> tuple[str, str]:
        now = datetime.now().astimezone()
        past = now - timedelta(days=30 * self._prefs.sync_window_months_past)
        future = now + timedelta(days=30 * self._prefs.sync_window_months_future)
        return past.isoformat(), future.isoformat()


def _event_from_row(row: sqlite3.Row | tuple[object, ...]) -> CachedEvent:
    values = tuple(row)
    return CachedEvent(
        event_id=str(values[0]),
        calendar_id=str(values[1]),
        summary=str(values[2]),
        description=_optional_str(values[3]),
        location=_optional_str(values[4]),
        start_dt=str(values[5]),
        end_dt=str(values[6]),
        status=str(values[7]),
        attendees=[str(item) for item in json.loads(str(values[8]))],
        organizer_email=_optional_str(values[9]),
        creator_email=_optional_str(values[10]),
        externally_authored=bool(values[11]),
        is_overlay_projection=bool(values[12]),
        overlay_proposal_id=_optional_str(values[13]),
        raw_json=str(values[14]),
    )


def _raw_items(page: dict[str, object]) -> list[dict[str, object]]:
    items = page.get("items", [])
    if not isinstance(items, list):
        return []
    return [cast(dict[str, object], item) for item in items if isinstance(item, dict)]


def _event_time(value: object) -> str:
    if isinstance(value, dict):
        date_time = value.get("dateTime")
        if isinstance(date_time, str):
            return date_time
        date = value.get("date")
        if isinstance(date, str):
            return date
    return ""


def _email_from_nested(event_raw: dict[str, object], key: str) -> str | None:
    value = event_raw.get(key)
    if not isinstance(value, dict):
        return None
    return _optional_str(value.get("email"))


def _attendee_emails(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    emails: list[str] = []
    for item in value:
        if isinstance(item, dict):
            email = item.get("email")
            if isinstance(email, str):
                emails.append(email)
    return emails


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None
