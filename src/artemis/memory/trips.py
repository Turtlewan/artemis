"""Trip aggregation store and assembler for owner-private memory.

Trips are structured rows beside memory entities, not an ``EntityType``. The
``trip:`` entity ref is a cross-module pointer to this owner-private table,
while destinations and co-travellers resolve through the entity backbone.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from artemis.memory.entities import EntityRef, EntityRepository, EntityType
from artemis.memory.schema import now_iso
from artemis.reactions import DomainEvent, EventType

if TYPE_CHECKING:
    from sqlite3 import Row


class TripStatus(StrEnum):
    """Lifecycle status for an assembled trip."""

    PLANNED = "planned"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TripLegKind(StrEnum):
    """Supported itinerary leg kinds."""

    FLIGHT = "flight"
    HOTEL = "hotel"
    TRANSPORT = "transport"
    OTHER = "other"


class TripExtract(BaseModel):
    """Sanitised itinerary leg input built upstream from a quarantined Extract."""

    model_config = ConfigDict(frozen=True)

    kind: TripLegKind
    title: str
    start_dt: str | None
    end_dt: str | None
    origin: str | None
    destination: str | None
    confirmation_ref: str | None
    co_travellers: tuple[str, ...] = ()
    raw_ref: str


@dataclass(frozen=True)
class TripLeg:
    """A structured itinerary leg owned by a Trip row."""

    id: str
    trip_id: str
    kind: TripLegKind
    title: str
    start_dt: str | None
    end_dt: str | None
    origin_place_id: str | None
    destination_place_id: str | None
    confirmation_ref: str | None
    raw_ref: str


@dataclass(frozen=True)
class Trip:
    """An assembled trip with structured legs and linked co-traveller entities."""

    id: str
    name: str
    status: TripStatus
    destination_place_id: str | None
    start_dt: str | None
    end_dt: str | None
    traveller_entity_ids: tuple[str, ...]
    legs: tuple[TripLeg, ...]


def create_trip_schema(conn: sqlite3.Connection) -> None:
    """Idempotently create Trip and TripLeg tables in the memory database."""
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS trip (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'planned'
                CHECK(status IN ('planned','active','completed','cancelled')),
            destination_place_id TEXT,
            start_dt TEXT,
            end_dt TEXT,
            traveller_ids TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_trip_dest ON trip (destination_place_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_trip_span ON trip (start_dt, end_dt)")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS trip_leg (
            id TEXT PRIMARY KEY,
            trip_id TEXT NOT NULL REFERENCES trip(id) ON DELETE CASCADE,
            kind TEXT NOT NULL CHECK(kind IN ('flight','hotel','transport','other')),
            title TEXT NOT NULL,
            start_dt TEXT,
            end_dt TEXT,
            origin_place_id TEXT,
            destination_place_id TEXT,
            confirmation_ref TEXT,
            raw_ref TEXT NOT NULL,
            created_at TEXT NOT NULL
        )"""
    )
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_trip_leg_raw_ref ON trip_leg (raw_ref)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_trip_leg_trip ON trip_leg (trip_id)")


def trip_entity_ref(trip_id: str) -> EntityRef:
    """Return the logical cross-module pointer for a structured Trip row."""
    return EntityRef(module="memory", entity_id=f"trip:{trip_id}")


class TripRepository:
    """Repository for structured trips in the owner-private memory database."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create_trip(
        self,
        name: str,
        *,
        destination_place_id: str | None = None,
        start_dt: str | None = None,
        end_dt: str | None = None,
    ) -> str:
        trip_id = uuid.uuid4().hex
        now = now_iso()
        with self._conn:
            self._conn.execute(
                """INSERT INTO trip (
                    id, name, status, destination_place_id, start_dt, end_dt,
                    traveller_ids, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, '[]', ?, ?)""",
                (
                    trip_id,
                    name,
                    TripStatus.PLANNED.value,
                    destination_place_id,
                    start_dt,
                    end_dt,
                    now,
                    now,
                ),
            )
        return trip_id

    def get_trip(self, id: str) -> Trip | None:
        trip_row = self._conn.execute(
            """SELECT id, name, status, destination_place_id, start_dt, end_dt, traveller_ids
               FROM trip
               WHERE id = ?""",
            (id,),
        ).fetchone()
        if trip_row is None:
            return None
        leg_rows = self._conn.execute(
            """SELECT id, trip_id, kind, title, start_dt, end_dt, origin_place_id,
                      destination_place_id, confirmation_ref, raw_ref
               FROM trip_leg
               WHERE trip_id = ?
               ORDER BY COALESCE(start_dt, end_dt, created_at), id""",
            (id,),
        ).fetchall()
        return _row_to_trip(trip_row, tuple(_row_to_leg(row) for row in leg_rows))

    def list_trips(self, *, status: TripStatus | None = None) -> list[Trip]:
        if status is None:
            rows = self._conn.execute(
                """SELECT id, name, status, destination_place_id, start_dt, end_dt,
                          traveller_ids
                   FROM trip
                   ORDER BY COALESCE(start_dt, end_dt, created_at), id"""
            ).fetchall()
        else:
            rows = self._conn.execute(
                """SELECT id, name, status, destination_place_id, start_dt, end_dt,
                          traveller_ids
                   FROM trip
                   WHERE status = ?
                   ORDER BY COALESCE(start_dt, end_dt, created_at), id""",
                (status.value,),
            ).fetchall()
        trips: list[Trip] = []
        for row in rows:
            trip = self.get_trip(str(row[0]))
            if trip is not None:
                trips.append(trip)
        return trips

    def add_leg(
        self,
        trip_id: str,
        leg: TripExtract,
        *,
        origin_place_id: str | None = None,
        destination_place_id: str | None = None,
    ) -> str:
        leg_id = uuid.uuid4().hex
        now = now_iso()
        with self._conn:
            self._conn.execute(
                """INSERT INTO trip_leg (
                    id, trip_id, kind, title, start_dt, end_dt, origin_place_id,
                    destination_place_id, confirmation_ref, raw_ref, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(raw_ref) DO NOTHING""",
                (
                    leg_id,
                    trip_id,
                    leg.kind.value,
                    leg.title,
                    leg.start_dt,
                    leg.end_dt,
                    origin_place_id,
                    destination_place_id,
                    leg.confirmation_ref,
                    leg.raw_ref,
                    now,
                ),
            )
            row = self._conn.execute(
                "SELECT id, trip_id FROM trip_leg WHERE raw_ref = ?",
                (leg.raw_ref,),
            ).fetchone()
            if row is None:
                raise RuntimeError("trip leg insert did not produce a row")
            existing_leg_id = str(row[0])
            owning_trip_id = str(row[1])
            self._recompute_span(owning_trip_id)
        return existing_leg_id

    def find_trip_by_raw_ref(self, raw_ref: str) -> Trip | None:
        """Return the Trip that already owns a raw itinerary reference, if any."""
        row = self._conn.execute(
            "SELECT trip_id FROM trip_leg WHERE raw_ref = ?",
            (raw_ref,),
        ).fetchone()
        return self.get_trip(str(row[0])) if row is not None else None

    def find_open_trip(
        self,
        *,
        destination_place_id: str | None,
        window_start: str | None,
        window_end: str | None,
    ) -> Trip | None:
        if destination_place_id is None:
            rows = self._conn.execute(
                """SELECT id, start_dt, end_dt
                   FROM trip
                   WHERE destination_place_id IS NULL
                     AND status IN ('planned', 'active')
                   ORDER BY COALESCE(start_dt, end_dt, created_at), id"""
            ).fetchall()
        else:
            rows = self._conn.execute(
                """SELECT id, start_dt, end_dt
                   FROM trip
                   WHERE destination_place_id = ?
                     AND status IN ('planned', 'active')
                   ORDER BY COALESCE(start_dt, end_dt, created_at), id""",
                (destination_place_id,),
            ).fetchall()
        for row in rows:
            if _windows_overlap(
                start_a=str(row[1]) if row[1] is not None else None,
                end_a=str(row[2]) if row[2] is not None else None,
                start_b=window_start,
                end_b=window_end,
            ):
                return self.get_trip(str(row[0]))
        return None

    def set_travellers(self, trip_id: str, entity_ids: Sequence[str]) -> None:
        current = self.get_trip(trip_id)
        if current is None:
            raise KeyError(trip_id)
        merged = tuple(dict.fromkeys((*current.traveller_entity_ids, *entity_ids)))
        with self._conn:
            self._conn.execute(
                "UPDATE trip SET traveller_ids = ?, updated_at = ? WHERE id = ?",
                (json.dumps(list(merged)), now_iso(), trip_id),
            )

    def set_status(self, trip_id: str, status: TripStatus) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE trip SET status = ?, updated_at = ? WHERE id = ?",
                (status.value, now_iso(), trip_id),
            )

    def _recompute_span(self, trip_id: str) -> None:
        row = self._conn.execute(
            """SELECT MIN(COALESCE(start_dt, end_dt)), MAX(COALESCE(end_dt, start_dt))
               FROM trip_leg
               WHERE trip_id = ?""",
            (trip_id,),
        ).fetchone()
        start_dt = str(row[0]) if row is not None and row[0] is not None else None
        end_dt = str(row[1]) if row is not None and row[1] is not None else None
        self._conn.execute(
            "UPDATE trip SET start_dt = ?, end_dt = ?, updated_at = ? WHERE id = ?",
            (start_dt, end_dt, now_iso(), trip_id),
        )


class TripAssembler:
    """Assemble stateful itinerary extracts into one revisable Trip."""

    def __init__(
        self,
        repo: TripRepository,
        entity_repo: EntityRepository,
        *,
        emit: Callable[[DomainEvent], None] = lambda _e: None,
    ) -> None:
        self._repo = repo
        self._entity_repo = entity_repo
        self._emit = emit

    def assemble(self, extract: TripExtract) -> str:
        existing = self._repo.find_trip_by_raw_ref(extract.raw_ref)
        if existing is None:
            dest_id = (
                self._entity_repo.resolve_or_create_entity(extract.destination, EntityType.PLACE)
                if extract.destination
                else None
            )
            origin_id = (
                self._entity_repo.resolve_or_create_entity(extract.origin, EntityType.PLACE)
                if extract.origin
                else None
            )
            trip = self._repo.find_open_trip(
                destination_place_id=dest_id,
                window_start=extract.start_dt,
                window_end=extract.end_dt,
            )
            trip_id = (
                self._repo.create_trip(
                    name=_trip_name(extract),
                    destination_place_id=dest_id,
                    start_dt=extract.start_dt,
                    end_dt=extract.end_dt,
                )
                if trip is None
                else trip.id
            )
        else:
            trip_id = existing.id
            dest_id = existing.destination_place_id
            origin_id = None
        # Re-feeding the same TripExtract (same raw_ref) revises in place: the
        # leg UNIQUE(raw_ref) and stable-key Trip match guarantee no duplicate
        # Trip and no duplicate leg. The emit dedups on trip_id downstream.
        self._repo.add_leg(
            trip_id,
            extract,
            origin_place_id=origin_id,
            destination_place_id=dest_id,
        )
        traveller_ids = [
            self._entity_repo.resolve_or_create_entity(
                name,
                EntityType.PERSON,
                external_ref=name if _looks_like_email(name) else None,
            )
            for name in extract.co_travellers
        ]
        if traveller_ids:
            self._repo.set_travellers(trip_id, traveller_ids)
        assembled = self._repo.get_trip(trip_id)
        if assembled is None:
            raise KeyError(trip_id)
        self._emit(
            DomainEvent(
                event_type=EventType.TRIP_ASSEMBLED,
                source_module="travel",
                entity_refs=(trip_entity_ref(trip_id),),
                payload={
                    "trip_id": trip_id,
                    "destination_place_id": dest_id or "",
                    "start_dt": assembled.start_dt or "",
                    "end_dt": assembled.end_dt or "",
                    "leg_count": len(assembled.legs),
                },
                occurred_at=now_iso(),
                dedup_key=f"trip-assembled:{trip_id}",
            )
        )
        return trip_id


def _trip_name(extract: TripExtract) -> str:
    return f"Trip to {extract.destination or 'unknown'}"


def _looks_like_email(value: str) -> bool:
    return "@" in value and "." in value.rsplit("@", maxsplit=1)[-1]


def _row_to_leg(row: Row) -> TripLeg:
    return TripLeg(
        id=str(row[0]),
        trip_id=str(row[1]),
        kind=TripLegKind(str(row[2])),
        title=str(row[3]),
        start_dt=str(row[4]) if row[4] is not None else None,
        end_dt=str(row[5]) if row[5] is not None else None,
        origin_place_id=str(row[6]) if row[6] is not None else None,
        destination_place_id=str(row[7]) if row[7] is not None else None,
        confirmation_ref=str(row[8]) if row[8] is not None else None,
        raw_ref=str(row[9]),
    )


def _row_to_trip(row: Row, legs: tuple[TripLeg, ...]) -> Trip:
    traveller_ids = json.loads(str(row[6]))
    if not isinstance(traveller_ids, list) or not all(
        isinstance(item, str) for item in traveller_ids
    ):
        raise ValueError("trip.traveller_ids must be a JSON array of strings")
    return Trip(
        id=str(row[0]),
        name=str(row[1]),
        status=TripStatus(str(row[2])),
        destination_place_id=str(row[3]) if row[3] is not None else None,
        start_dt=str(row[4]) if row[4] is not None else None,
        end_dt=str(row[5]) if row[5] is not None else None,
        traveller_entity_ids=tuple(traveller_ids),
        legs=legs,
    )


def _windows_overlap(
    *,
    start_a: str | None,
    end_a: str | None,
    start_b: str | None,
    end_b: str | None,
) -> bool:
    left_start = start_a or end_a
    left_end = end_a or start_a
    right_start = start_b or end_b
    right_end = end_b or start_b
    if left_start is None or left_end is None or right_start is None or right_end is None:
        return False
    left_start_date = left_start[:10]
    left_end_date = left_end[:10]
    right_start_date = right_start[:10]
    right_end_date = right_end[:10]
    return left_start_date <= right_end_date and right_start_date <= left_end_date
