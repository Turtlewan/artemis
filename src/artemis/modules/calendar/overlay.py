"""Calendar proposal overlay and tentative Google projection lifecycle."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from artemis import paths
from artemis.config import Settings
from artemis.data.sqlcipher import sqlcipher_open
from artemis.identity.key_provider import KeyProvider
from artemis.identity.scope import OWNER_PRIVATE
from artemis.integrations.google import ReauthRequiredError
from artemis.modules.calendar.client import CalendarClient
from artemis.modules.calendar.gating import GateDecision, classify
from artemis.modules.calendar.preferences import CalPrefs
from artemis.staging import ActionStagingService, PendingAction


class OverlayProjectionError(Exception):
    """Raised when a proposal cannot be projected to Google Calendar."""


class ProposalNotFoundError(Exception):
    """Raised when a proposal id is absent or not pending."""


@dataclass(frozen=True)
class ProposalRow:
    """One owner-private proposal/hold overlay row."""

    id: str
    kind: str
    status: str
    label: str
    proposed_start: str | None
    proposed_end: str | None
    source_event_id: str | None
    google_event_id: str | None
    created_at: str
    updated_at: str


class OverlayStore:
    """SQLCipher-backed owner-private store for calendar proposal rows."""

    def __init__(self, settings: Settings, key_provider: KeyProvider) -> None:
        self._settings = settings
        self._key_provider = key_provider

    def _db_path(self) -> Path:
        return paths.scope_dir(self._settings, OWNER_PRIVATE) / "calendar" / "overlay.db"

    def _connect(self) -> sqlite3.Connection:
        """Open the overlay DB, propagating ``ScopeLockedError`` when locked."""
        key = self._key_provider.dek_for_scope(OWNER_PRIVATE)
        db_path = self._db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        key_hex = key.as_hex()
        conn = sqlcipher_open(db_path, key_hex)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS proposals (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                status TEXT NOT NULL,
                label TEXT NOT NULL,
                proposed_start TEXT,
                proposed_end TEXT,
                source_event_id TEXT,
                google_event_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
        return conn

    def save(self, row: ProposalRow) -> None:
        """Insert or replace a proposal row."""
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO proposals (
                    id, kind, status, label, proposed_start, proposed_end, source_event_id,
                    google_event_id, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    kind=excluded.kind,
                    status=excluded.status,
                    label=excluded.label,
                    proposed_start=excluded.proposed_start,
                    proposed_end=excluded.proposed_end,
                    source_event_id=excluded.source_event_id,
                    google_event_id=excluded.google_event_id,
                    created_at=excluded.created_at,
                    updated_at=excluded.updated_at
                """,
                _to_db_row(row),
            )
            conn.commit()

    def get(self, proposal_id: str) -> ProposalRow | None:
        """Return one proposal row, or ``None`` when absent."""
        with closing(self._connect()) as conn:
            row = conn.execute(
                """
                SELECT id, kind, status, label, proposed_start, proposed_end, source_event_id,
                       google_event_id, created_at, updated_at
                FROM proposals
                WHERE id = ?
                """,
                (proposal_id,),
            ).fetchone()
        return None if row is None else _from_db_row(row)

    def list_pending(self) -> list[ProposalRow]:
        """Return pending proposals ordered by creation time."""
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT id, kind, status, label, proposed_start, proposed_end, source_event_id,
                       google_event_id, created_at, updated_at
                FROM proposals
                WHERE status = ?
                ORDER BY created_at ASC
                """,
                ("pending",),
            ).fetchall()
        return [_from_db_row(row) for row in rows]

    def mark_approved(self, proposal_id: str, *, updated_at: str) -> None:
        """Mark a proposal approved."""
        self._mark_status(proposal_id, "approved", updated_at=updated_at)

    def mark_rejected(self, proposal_id: str, *, updated_at: str) -> None:
        """Mark a proposal rejected."""
        self._mark_status(proposal_id, "rejected", updated_at=updated_at)

    def set_google_event_id(
        self, proposal_id: str, google_event_id: str, *, updated_at: str
    ) -> None:
        """Persist the Google tentative event id for a proposal."""
        with closing(self._connect()) as conn:
            cursor = conn.execute(
                """
                UPDATE proposals
                SET google_event_id = ?, updated_at = ?
                WHERE id = ?
                """,
                (google_event_id, updated_at, proposal_id),
            )
            conn.commit()
        if cursor.rowcount == 0:
            raise KeyError(proposal_id)

    def _mark_status(self, proposal_id: str, status: str, *, updated_at: str) -> None:
        with closing(self._connect()) as conn:
            cursor = conn.execute(
                "UPDATE proposals SET status = ?, updated_at = ? WHERE id = ?",
                (status, updated_at, proposal_id),
            )
            conn.commit()
        if cursor.rowcount == 0:
            raise KeyError(proposal_id)


class ProposeRescheduleArgs(BaseModel):
    """Arguments for proposing a reschedule."""

    model_config = ConfigDict(frozen=True)

    event_id: str
    suggested_start: str
    suggested_end: str
    reason: str


class ProposeEventArgs(BaseModel):
    """Arguments for proposing a new event from a draft body."""

    model_config = ConfigDict(frozen=True)

    draft: dict[str, object]


class HoldTentativeArgs(BaseModel):
    """Arguments for creating a tentative hold proposal."""

    model_config = ConfigDict(frozen=True)

    start: str
    end: str
    label: str


class ListProposalsArgs(BaseModel):
    """No-argument request for pending proposals."""

    model_config = ConfigDict(frozen=True)


class ApproveRejectArgs(BaseModel):
    """Arguments for approving or rejecting a proposal."""

    model_config = ConfigDict(frozen=True)

    proposal_id: str


class ProposalResult(BaseModel):
    """Pydantic result returned by overlay tool callables."""

    model_config = ConfigDict(frozen=True)

    proposal_id: str
    status: str
    google_event_id: str | None
    pending_action_id: str | None = None


class ProposalListResult(BaseModel):
    """Pydantic result for listing pending proposals."""

    model_config = ConfigDict(frozen=True)

    proposals: list[ProposalResult] = Field(default_factory=list)


class OverlayTools:
    """Async registry callables that inject overlay dependencies."""

    def __init__(
        self,
        client: CalendarClient,
        store: OverlayStore,
        staging: ActionStagingService,
        key_provider: KeyProvider,
        prefs: CalPrefs,
    ) -> None:
        self._client = client
        self._store = store
        self._staging = staging
        self._key_provider = key_provider
        self._prefs = prefs

    async def propose_reschedule(self, args: ProposeRescheduleArgs) -> ProposalResult:
        row = propose_reschedule(
            self._client,
            self._store,
            key_provider=self._key_provider,
            event_id=args.event_id,
            suggested_start=args.suggested_start,
            suggested_end=args.suggested_end,
            reason=args.reason,
        )
        return _proposal_result(row)

    async def propose_event(self, args: ProposeEventArgs) -> ProposalResult:
        row = propose_event(
            self._client,
            self._store,
            key_provider=self._key_provider,
            draft=args.draft,
        )
        return _proposal_result(row)

    async def hold_tentative(self, args: HoldTentativeArgs) -> ProposalResult:
        row = hold_tentative(
            self._client,
            self._store,
            key_provider=self._key_provider,
            start=args.start,
            end=args.end,
            label=args.label,
        )
        return _proposal_result(row)

    async def list_proposals(self, args: ListProposalsArgs) -> ProposalListResult:
        del args
        return ProposalListResult(
            proposals=[_proposal_result(row) for row in list_proposals(self._store)]
        )

    async def approve_proposal(self, args: ApproveRejectArgs) -> ProposalResult:
        result = approve_proposal(
            self._client,
            self._store,
            self._staging,
            key_provider=self._key_provider,
            proposal_id=args.proposal_id,
            owner_email=self._prefs.owner_email or "",
        )
        if isinstance(result, PendingAction):
            return ProposalResult(
                proposal_id=args.proposal_id,
                status="staged_for_review",
                google_event_id=None,
                pending_action_id=result.id,
            )
        return _proposal_result(result)

    async def reject_proposal(self, args: ApproveRejectArgs) -> ProposalResult:
        row = reject_proposal(
            self._client,
            self._store,
            key_provider=self._key_provider,
            proposal_id=args.proposal_id,
        )
        return _proposal_result(row)


def now_utc() -> str:
    """Return the current UTC timestamp as ISO-8601 text."""
    return datetime.now(tz=UTC).isoformat()


def propose_reschedule(
    client: CalendarClient,
    store: OverlayStore,
    *,
    key_provider: KeyProvider,
    event_id: str,
    suggested_start: str,
    suggested_end: str,
    reason: str,
) -> ProposalRow:
    """Create and project a reschedule proposal as a tentative Google event."""
    del reason
    _assert_unlocked(key_provider)
    proposal_id = str(uuid4())
    timestamp = now_utc()
    row = ProposalRow(
        id=proposal_id,
        kind="reschedule",
        status="pending",
        label=f"Reschedule: {event_id}",
        proposed_start=suggested_start,
        proposed_end=suggested_end,
        source_event_id=event_id,
        google_event_id=None,
        created_at=timestamp,
        updated_at=timestamp,
    )
    google_event_id = _project_to_google(client, proposal_id, row)
    projected = replace(row, google_event_id=google_event_id, updated_at=now_utc())
    store.save(projected)
    return projected


def propose_event(
    client: CalendarClient,
    store: OverlayStore,
    *,
    key_provider: KeyProvider,
    draft: dict[str, object],
) -> ProposalRow:
    """Create and project a proposed new event from a draft."""
    _assert_unlocked(key_provider)
    proposal_id = str(uuid4())
    timestamp = now_utc()
    start = _optional_str(draft.get("start")) or _optional_str(draft.get("start_datetime"))
    end = _optional_str(draft.get("end")) or _optional_str(draft.get("end_datetime"))
    row = ProposalRow(
        id=proposal_id,
        kind="event",
        status="pending",
        label=_optional_str(draft.get("summary")) or "Proposed event",
        proposed_start=start,
        proposed_end=end,
        source_event_id=None,
        google_event_id=None,
        created_at=timestamp,
        updated_at=timestamp,
    )
    google_event_id = _project_to_google(client, proposal_id, row)
    projected = replace(row, google_event_id=google_event_id, updated_at=now_utc())
    store.save(projected)
    return projected


def hold_tentative(
    client: CalendarClient,
    store: OverlayStore,
    *,
    key_provider: KeyProvider,
    start: str,
    end: str,
    label: str,
) -> ProposalRow:
    """Create a self-only tentative hold and project it to Google Calendar."""
    _assert_unlocked(key_provider)
    proposal_id = str(uuid4())
    timestamp = now_utc()
    row = ProposalRow(
        id=proposal_id,
        kind="hold",
        status="pending",
        label=label,
        proposed_start=start,
        proposed_end=end,
        source_event_id=None,
        google_event_id=None,
        created_at=timestamp,
        updated_at=timestamp,
    )
    google_event_id = _project_to_google(client, proposal_id, row)
    projected = replace(row, google_event_id=google_event_id, updated_at=now_utc())
    store.save(projected)
    return projected


def _project_to_google(client: CalendarClient, proposal_id: str, row: ProposalRow) -> str:
    """Project a proposal as a tentative Google event with the private marker.

    The current CalendarClient create seam has no extendedProperties parameter,
    so projection creates the event through the canonical write signature and
    immediately patches status plus ``extendedProperties.private.artemis_overlay``.
    """
    if row.proposed_start is None or row.proposed_end is None:
        raise OverlayProjectionError("proposal projection requires start and end")
    try:
        created = client.create_event(
            summary=row.label,
            start=row.proposed_start,
            end=row.proposed_end,
            calendar_id="primary",
            description=None,
            location=None,
            attendees=(),
            recurrence=(),
            reminders=None,
            send_updates="none",
        )
        google_event_id = _event_id(created)
        client.update_event(
            google_event_id,
            {
                "status": "tentative",
                "extendedProperties": {"private": {"artemis_overlay": proposal_id}},
            },
            recurrence_scope="THIS_EVENT",
            send_updates="none",
        )
        return google_event_id
    except ReauthRequiredError:
        raise
    except Exception as exc:
        raise OverlayProjectionError(str(exc)) from exc


def list_proposals(store: OverlayStore) -> list[ProposalRow]:
    """Return pending overlay proposals."""
    return store.list_pending()


def approve_proposal(
    client: CalendarClient,
    store: OverlayStore,
    staging: ActionStagingService,
    *,
    key_provider: KeyProvider,
    proposal_id: str,
    owner_email: str,
) -> ProposalRow | PendingAction:
    """Approve a proposal directly when self-only, or stage the underlying write action."""
    _assert_unlocked(key_provider)
    row = _pending_row(store, proposal_id)
    attendees = _proposal_attendees(client, row)
    decision = classify("approve_proposal", attendees, owner_email)
    if decision is GateDecision.GATED:
        return _stage_underlying_action(staging, row)

    if row.google_event_id is not None:
        client.update_event(
            row.google_event_id,
            {"status": "confirmed"},
            recurrence_scope="THIS_EVENT",
            send_updates="none",
        )
    elif row.kind == "reschedule" and row.source_event_id is not None:
        client.update_event(
            row.source_event_id,
            _reschedule_changes(row),
            recurrence_scope="THIS_EVENT",
            send_updates="none",
        )
    else:
        _create_direct_event(client, row)
    store.mark_approved(proposal_id, updated_at=now_utc())
    approved = store.get(proposal_id)
    if approved is None:
        raise ProposalNotFoundError(proposal_id)
    return approved


def reject_proposal(
    client: CalendarClient,
    store: OverlayStore,
    *,
    key_provider: KeyProvider,
    proposal_id: str,
) -> ProposalRow:
    """Reject a proposal and cancel any projected tentative Google event."""
    _assert_unlocked(key_provider)
    row = _pending_row(store, proposal_id)
    if row.google_event_id is not None:
        client.cancel_event(row.google_event_id, recurrence_scope="THIS_EVENT", send_updates="none")
    store.mark_rejected(proposal_id, updated_at=now_utc())
    rejected = store.get(proposal_id)
    if rejected is None:
        raise ProposalNotFoundError(proposal_id)
    return rejected


def _assert_unlocked(key_provider: KeyProvider) -> None:
    key_provider.dek_for_scope(OWNER_PRIVATE)


def _pending_row(store: OverlayStore, proposal_id: str) -> ProposalRow:
    row = store.get(proposal_id)
    if row is None or row.status != "pending":
        raise ProposalNotFoundError(proposal_id)
    return row


def _proposal_attendees(client: CalendarClient, row: ProposalRow) -> list[str]:
    if row.kind != "reschedule" or row.source_event_id is None:
        return []
    try:
        event = client.get_event("primary", row.source_event_id)
    except KeyError:
        return []
    return _attendees(event.get("attendees"))


def _stage_underlying_action(staging: ActionStagingService, row: ProposalRow) -> PendingAction:
    if row.kind == "reschedule" and row.source_event_id is not None:
        args: dict[str, object] = {
            "event_id": row.source_event_id,
            "start_datetime": row.proposed_start,
            "end_datetime": row.proposed_end,
            "recurrence_scope": "THIS_EVENT",
        }
        return staging.stage(
            "calendar",
            "calendar.update_event",
            args,
            f"Reschedule {row.source_event_id}; pending owner approval",
        )
    args = {
        "summary": row.label,
        "start_datetime": row.proposed_start,
        "end_datetime": row.proposed_end,
        "attendee_emails": [],
    }
    return staging.stage(
        "calendar",
        "calendar.create_event",
        args,
        f"Create {row.label}; pending owner approval",
    )


def _reschedule_changes(row: ProposalRow) -> dict[str, object]:
    changes: dict[str, object] = {}
    if row.proposed_start is not None:
        changes["start"] = {"dateTime": row.proposed_start}
    if row.proposed_end is not None:
        changes["end"] = {"dateTime": row.proposed_end}
    return changes


def _create_direct_event(client: CalendarClient, row: ProposalRow) -> str:
    if row.proposed_start is None or row.proposed_end is None:
        raise OverlayProjectionError("proposal approval requires start and end")
    event = client.create_event(
        summary=row.label,
        start=row.proposed_start,
        end=row.proposed_end,
        calendar_id="primary",
        send_updates="none",
    )
    return _event_id(event)


def _proposal_result(row: ProposalRow) -> ProposalResult:
    return ProposalResult(
        proposal_id=row.id,
        status=row.status,
        google_event_id=row.google_event_id,
    )


def _event_id(event: dict[str, object]) -> str:
    value = event.get("id")
    if isinstance(value, str) and value:
        return value
    raise OverlayProjectionError("Google event response did not include an id")


def _attendees(value: object) -> list[str]:
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


def _to_db_row(
    row: ProposalRow,
) -> tuple[str, str, str, str, str | None, str | None, str | None, str | None, str, str]:
    return (
        row.id,
        row.kind,
        row.status,
        row.label,
        row.proposed_start,
        row.proposed_end,
        row.source_event_id,
        row.google_event_id,
        row.created_at,
        row.updated_at,
    )


def _from_db_row(row: tuple[object, ...]) -> ProposalRow:
    return ProposalRow(
        id=cast(str, row[0]),
        kind=cast(str, row[1]),
        status=cast(str, row[2]),
        label=cast(str, row[3]),
        proposed_start=cast(str | None, row[4]),
        proposed_end=cast(str | None, row[5]),
        source_event_id=cast(str | None, row[6]),
        google_event_id=cast(str | None, row[7]),
        created_at=cast(str, row[8]),
        updated_at=cast(str, row[9]),
    )
