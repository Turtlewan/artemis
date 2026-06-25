"""Held tentative events created from sanitised calendar extracts."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from enum import StrEnum
from typing import cast
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from artemis.modules.calendar.write_tools import (
    CalendarWriteTools,
    CreateEventArgs,
    StagedResult,
    WriteResult,
)


class EventExtract(BaseModel):
    """Calendar-relevant fields parsed upstream from a quarantined DR-a Extract.

    Raw email text never reaches this layer. Only sanitised summary/description
    fields are persisted in the held-event lifecycle.
    """

    model_config = ConfigDict(frozen=True)

    summary: str
    start_datetime: str
    end_datetime: str
    location: str | None = None
    description: str | None = None
    attendee_emails: tuple[str, ...] = ()
    raw_ref: str


class CreateFromExtractArgs(BaseModel):
    """Tool args for creating a held tentative event from an extract."""

    model_config = ConfigDict(frozen=True)

    extract: EventExtract
    event_type: str


class HeldEventIdArgs(BaseModel):
    """Tool args carrying a held-event id."""

    model_config = ConfigDict(frozen=True)

    held_id: str


class ListHeldEventsArgs(BaseModel):
    """Tool args for listing held events by status."""

    model_config = ConfigDict(frozen=True)

    status: str = "held"


class HeldEventStatus(StrEnum):
    """Lifecycle state for an Artemis-owned held tentative event."""

    HELD = "held"
    APPROVED = "approved"
    DISCARDED = "discarded"


class HeldTentativeEvent(BaseModel):
    """One held tentative event that is not yet necessarily a Google event."""

    model_config = ConfigDict(frozen=True)

    id: str
    event_type: str
    summary: str
    start_datetime: str
    end_datetime: str
    location: str | None
    description: str | None
    attendee_emails: tuple[str, ...]
    status: HeldEventStatus
    raw_ref: str
    google_event_id: str | None
    pending_action_id: str | None


class HeldTentativeEventList(BaseModel):
    """Manifest return schema for held-event list tools."""

    model_config = ConfigDict(frozen=True)

    events: list[HeldTentativeEvent]


def create_held_event_schema(conn: sqlite3.Connection) -> None:
    """Create the Calendar owner-private held-event table and indexes."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS held_event (
            id TEXT PRIMARY KEY,
            event_type TEXT NOT NULL,
            summary TEXT NOT NULL,
            start_datetime TEXT NOT NULL,
            end_datetime TEXT NOT NULL,
            location TEXT,
            description TEXT,
            attendee_emails TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'held'
                CHECK(status IN ('held', 'approved', 'discarded')),
            raw_ref TEXT NOT NULL,
            google_event_id TEXT,
            pending_action_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_held_raw_ref ON held_event(raw_ref)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_held_status ON held_event(status)")
    conn.commit()


class HeldEventStore:
    """Synchronous held-event store over the Calendar module's owned connection."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        create_held_event_schema(self._conn)

    def create_held(self, extract: EventExtract, event_type: str) -> str:
        """Create a held row, returning the existing id on raw_ref conflict."""
        held_id = str(uuid4())
        now = _now_iso()
        self._conn.execute(
            """
            INSERT INTO held_event (
                id, event_type, summary, start_datetime, end_datetime, location, description,
                attendee_emails, status, raw_ref, google_event_id, pending_action_id,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?)
            ON CONFLICT(raw_ref) DO NOTHING
            """,
            (
                held_id,
                event_type,
                extract.summary,
                extract.start_datetime,
                extract.end_datetime,
                extract.location,
                extract.description,
                json.dumps(list(extract.attendee_emails)),
                HeldEventStatus.HELD.value,
                extract.raw_ref,
                now,
                now,
            ),
        )
        self._conn.commit()
        row = self._conn.execute(
            "SELECT id FROM held_event WHERE raw_ref = ?",
            (extract.raw_ref,),
        ).fetchone()
        if row is None:
            raise KeyError(extract.raw_ref)
        return str(row[0])

    def get_held(self, held_id: str) -> HeldTentativeEvent:
        """Return one held event by id."""
        row = self._conn.execute(
            """
            SELECT id, event_type, summary, start_datetime, end_datetime, location, description,
                   attendee_emails, status, raw_ref, google_event_id, pending_action_id
            FROM held_event
            WHERE id = ?
            """,
            (held_id,),
        ).fetchone()
        if row is None:
            raise KeyError(held_id)
        return _held_from_row(cast(tuple[object, ...], tuple(row)))

    def list_held(self, *, status: str = "held") -> list[HeldTentativeEvent]:
        """List held events filtered by lifecycle status."""
        rows = self._conn.execute(
            """
            SELECT id, event_type, summary, start_datetime, end_datetime, location, description,
                   attendee_emails, status, raw_ref, google_event_id, pending_action_id
            FROM held_event
            WHERE status = ?
            ORDER BY created_at ASC, id ASC
            """,
            (status,),
        ).fetchall()
        return [_held_from_row(cast(tuple[object, ...], tuple(row))) for row in rows]

    def set_approved(
        self,
        held_id: str,
        *,
        google_event_id: str | None,
        pending_action_id: str | None,
    ) -> None:
        """Mark a held row approved after CAL-b accepts or stages the write."""
        self._set_status(
            held_id,
            HeldEventStatus.APPROVED,
            google_event_id=google_event_id,
            pending_action_id=pending_action_id,
        )

    def set_discarded(self, held_id: str) -> None:
        """Discard a held tentative event without external side effects."""
        self._set_status(
            held_id,
            HeldEventStatus.DISCARDED,
            google_event_id=None,
            pending_action_id=None,
        )

    def _set_status(
        self,
        held_id: str,
        status: HeldEventStatus,
        *,
        google_event_id: str | None,
        pending_action_id: str | None,
    ) -> None:
        cursor = self._conn.execute(
            """
            UPDATE held_event
            SET status = ?, google_event_id = ?, pending_action_id = ?, updated_at = ?
            WHERE id = ?
            """,
            (status.value, google_event_id, pending_action_id, _now_iso(), held_id),
        )
        self._conn.commit()
        if cursor.rowcount == 0:
            raise KeyError(held_id)


async def create_from_extract(
    extract: EventExtract,
    *,
    event_type: str,
    store: HeldEventStore,
) -> HeldTentativeEvent:
    """Create an internal held tentative event from a sanitised extract."""
    # C5=B: create_from_extract NEVER writes to Google. The held tentative lives
    # in the owned held_event table until the owner approves. The external
    # Google write happens ONLY in approve_held_event, via the CAL-b gated
    # create_event -> GATE.
    held_id = store.create_held(extract, event_type)
    return store.get_held(held_id)


async def approve_held_event(
    held_id: str,
    *,
    store: HeldEventStore,
    write_tools: CalendarWriteTools,
) -> HeldTentativeEvent:
    """Approve a held event and route creation through CAL-b's write surface."""
    held = store.get_held(held_id)
    if held.status is not HeldEventStatus.HELD:
        return held

    args = CreateEventArgs(
        summary=held.summary,
        start_datetime=held.start_datetime,
        end_datetime=held.end_datetime,
        description=held.description,
        location=held.location,
        attendee_emails=list(held.attendee_emails),
    )
    # The external Google write goes through CAL-b's create_event -> its
    # classifier -> GATE for any attendee event. approve_held_event NEVER calls
    # the Google client directly; it always goes through write_tools.create_event
    # (Seam 4) so the attendee-gating wall holds.
    result = await write_tools.create_event(args)
    if isinstance(result, WriteResult):
        store.set_approved(
            held_id,
            google_event_id=result.event_id,
            pending_action_id=None,
        )
    elif isinstance(result, StagedResult):
        store.set_approved(
            held_id,
            google_event_id=None,
            pending_action_id=result.pending_action_id,
        )
    return store.get_held(held_id)


async def list_held_events(
    *,
    store: HeldEventStore,
    status: str = "held",
) -> list[HeldTentativeEvent]:
    """List held events for the requested status."""
    return store.list_held(status=status)


async def discard_held_event(
    held_id: str,
    *,
    store: HeldEventStore,
) -> HeldTentativeEvent:
    """Discard a held tentative event as the reversible undo path."""
    held = store.get_held(held_id)
    # Status guard (mirrors approve_held_event): only a still-HELD event may be
    # discarded. Discarding an already-APPROVED event would silently null the
    # google_event_id/pending_action_id audit trail with no compensating revoke.
    if held.status is not HeldEventStatus.HELD:
        return held
    store.set_discarded(held_id)
    return store.get_held(held_id)


async def create_from_extract_tool(
    args: CreateFromExtractArgs,
    *,
    store: HeldEventStore,
) -> HeldTentativeEvent:
    """Manifest adapter for ``calendar.create_from_extract``."""
    return await create_from_extract(args.extract, event_type=args.event_type, store=store)


async def approve_held_event_tool(
    args: HeldEventIdArgs,
    *,
    store: HeldEventStore,
    write_tools: CalendarWriteTools,
) -> HeldTentativeEvent:
    """Manifest adapter for ``calendar.approve_held_event``."""
    return await approve_held_event(args.held_id, store=store, write_tools=write_tools)


async def list_held_events_tool(
    args: ListHeldEventsArgs,
    *,
    store: HeldEventStore,
) -> HeldTentativeEventList:
    """Manifest adapter for ``calendar.list_held_events``."""
    return HeldTentativeEventList(events=await list_held_events(store=store, status=args.status))


async def discard_held_event_tool(
    args: HeldEventIdArgs,
    *,
    store: HeldEventStore,
) -> HeldTentativeEvent:
    """Manifest adapter for ``calendar.discard_held_event``."""
    return await discard_held_event(args.held_id, store=store)


def _held_from_row(row: tuple[object, ...]) -> HeldTentativeEvent:
    return HeldTentativeEvent(
        id=str(row[0]),
        event_type=str(row[1]),
        summary=str(row[2]),
        start_datetime=str(row[3]),
        end_datetime=str(row[4]),
        location=_optional_str(row[5]),
        description=_optional_str(row[6]),
        attendee_emails=tuple(str(item) for item in json.loads(str(row[7]))),
        status=HeldEventStatus(str(row[8])),
        raw_ref=str(row[9]),
        google_event_id=_optional_str(row[10]),
        pending_action_id=_optional_str(row[11]),
    )


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()
