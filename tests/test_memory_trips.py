from __future__ import annotations

import sqlite3
from collections.abc import Iterator

import pytest
import sqlite_vec  # type: ignore[import-untyped]

from artemis.memory.entities import EntityRepository, EntityType
from artemis.memory.schema import create_schema
from artemis.memory.trips import (
    TripAssembler,
    TripExtract,
    TripLegKind,
    TripRepository,
    TripStatus,
    create_trip_schema,
    trip_entity_ref,
)
from artemis.ports.types import PersonId
from artemis.reactions import DomainEvent, EventType

DIMENSION = 4
OWNER_PERSON_ID = PersonId("owner")


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    c = sqlite3.connect(":memory:")
    c.enable_load_extension(True)
    c.load_extension(sqlite_vec.loadable_path())
    c.enable_load_extension(False)
    c.row_factory = sqlite3.Row
    create_schema(c, embedder_model_id="test-fake", dimension=DIMENSION)
    create_trip_schema(c)
    try:
        yield c
    finally:
        c.close()


@pytest.fixture
def trip_repo(conn: sqlite3.Connection) -> TripRepository:
    return TripRepository(conn)


@pytest.fixture
def entity_repo(conn: sqlite3.Connection) -> EntityRepository:
    return EntityRepository(conn, OWNER_PERSON_ID)


def test_schema_creates_trip_tables_indexes_and_is_idempotent(
    conn: sqlite3.Connection,
) -> None:
    create_trip_schema(conn)

    tables = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'trip%'"
        ).fetchall()
    }
    assert tables == {"trip", "trip_leg"}

    indexes = {str(row[1]) for row in conn.execute("PRAGMA index_list('trip_leg')").fetchall()}
    assert "idx_trip_leg_raw_ref" in indexes
    raw_ref_index = conn.execute("PRAGMA index_info('idx_trip_leg_raw_ref')").fetchall()
    assert [str(row[2]) for row in raw_ref_index] == ["raw_ref"]
    unique_row = next(
        row
        for row in conn.execute("PRAGMA index_list('trip_leg')")
        if row[1] == "idx_trip_leg_raw_ref"
    )
    assert int(unique_row[2]) == 1


def test_repository_round_trip_idempotent_leg_and_window_match(
    trip_repo: TripRepository,
) -> None:
    trip_id = trip_repo.create_trip(
        "Trip to London",
        destination_place_id="place:london",
        start_dt="2026-08-01T10:00:00Z",
        end_dt="2026-08-02T06:00:00Z",
    )
    flight = _flight_extract(raw_ref="m1:0")
    hotel = _hotel_extract()

    first_leg_id = trip_repo.add_leg(
        trip_id,
        flight,
        origin_place_id="place:singapore",
        destination_place_id="place:london",
    )
    duplicate_leg_id = trip_repo.add_leg(
        trip_id,
        flight,
        origin_place_id="place:singapore",
        destination_place_id="place:london",
    )
    assert duplicate_leg_id == first_leg_id
    trip_repo.add_leg(trip_id, hotel, destination_place_id="place:london")

    trip = trip_repo.get_trip(trip_id)
    assert trip is not None
    assert trip.status is TripStatus.PLANNED
    assert trip.start_dt == "2026-08-01T10:00:00Z"
    assert trip.end_dt == "2026-08-05T11:00:00Z"
    assert len(trip.legs) == 2

    match = trip_repo.find_open_trip(
        destination_place_id="place:london",
        window_start="2026-08-02T15:00:00Z",
        window_end="2026-08-03T11:00:00Z",
    )
    assert match is not None
    assert match.id == trip_id
    disjoint = trip_repo.find_open_trip(
        destination_place_id="place:london",
        window_start="2027-02-01T10:00:00Z",
        window_end="2027-02-01T22:00:00Z",
    )
    assert disjoint is None


def test_assembler_revises_idempotently_links_cotraveller_and_entity_ref(
    trip_repo: TripRepository,
    entity_repo: EntityRepository,
) -> None:
    assembler = TripAssembler(trip_repo, entity_repo)
    flight = _flight_extract(raw_ref="m1:0")
    hotel = _hotel_extract(co_travellers=("Ashley",))

    trip_id = assembler.assemble(flight)
    trip = trip_repo.get_trip(trip_id)
    assert trip is not None
    assert len(trip.legs) == 1
    assert trip.destination_place_id is not None
    destination = entity_repo.get_entity(trip.destination_place_id)
    assert destination.entity_type is EntityType.PLACE
    assert destination.canonical_name == "London"

    revised_trip_id = assembler.assemble(hotel)
    assert revised_trip_id == trip_id
    revised = trip_repo.get_trip(trip_id)
    assert revised is not None
    assert len(revised.legs) == 2
    assert revised.start_dt == "2026-08-01T10:00:00Z"
    assert revised.end_dt == "2026-08-05T11:00:00Z"

    assert assembler.assemble(flight) == trip_id
    idempotent = trip_repo.get_trip(trip_id)
    assert idempotent is not None
    assert len(idempotent.legs) == 2

    person_id = entity_repo.resolve_or_create_entity("Ashley", EntityType.PERSON)
    assert idempotent.traveller_entity_ids == (person_id,)
    assembler.assemble(_hotel_extract(raw_ref="m2:1", co_travellers=("Ashley",)))
    deduped = trip_repo.get_trip(trip_id)
    assert deduped is not None
    assert deduped.traveller_entity_ids == (person_id,)

    before_replay = len(trip_repo.list_trips())
    trip_repo.set_status(trip_id, TripStatus.COMPLETED)
    assert assembler.assemble(flight) == trip_id
    assert len(trip_repo.list_trips()) == before_replay

    ref = trip_entity_ref(trip_id)
    assert ref.module == "memory"
    assert ref.entity_id == f"trip:{trip_id}"


def test_assembler_opens_new_trip_for_disjoint_window(
    trip_repo: TripRepository,
    entity_repo: EntityRepository,
) -> None:
    assembler = TripAssembler(trip_repo, entity_repo)
    first_id = assembler.assemble(_flight_extract(raw_ref="m1:0"))
    later_id = assembler.assemble(
        _flight_extract(
            start_dt="2027-02-01T10:00:00Z",
            end_dt="2027-02-01T22:00:00Z",
            raw_ref="m3:0",
        )
    )

    assert later_id != first_id


def test_assembler_opens_new_trip_for_missing_date_window(
    trip_repo: TripRepository,
    entity_repo: EntityRepository,
) -> None:
    assembler = TripAssembler(trip_repo, entity_repo)
    first_id = assembler.assemble(_flight_extract(raw_ref="m1:0"))
    undated_id = assembler.assemble(
        TripExtract(
            kind=TripLegKind.OTHER,
            title="London itinerary note",
            start_dt=None,
            end_dt=None,
            origin=None,
            destination="London",
            confirmation_ref=None,
            raw_ref="m4:0",
        )
    )

    assert undated_id != first_id


def test_assembler_emits_trip_assembled_per_call(
    trip_repo: TripRepository,
    entity_repo: EntityRepository,
) -> None:
    events: list[DomainEvent] = []
    assembler = TripAssembler(trip_repo, entity_repo, emit=events.append)

    trip_id = assembler.assemble(_flight_extract(raw_ref="m1:0"))
    assert len(events) == 1
    first = events[0]
    assert first.event_type is EventType.TRIP_ASSEMBLED
    assert first.source_module == "travel"
    assert first.entity_refs == (trip_entity_ref(trip_id),)
    assert first.payload["trip_id"] == trip_id
    assert first.payload["leg_count"] == 1
    assert all(isinstance(value, (str, int, float, bool)) for value in first.payload.values())
    assert first.dedup_key == f"trip-assembled:{trip_id}"

    revised_id = assembler.assemble(_hotel_extract())
    assert revised_id == trip_id
    assert len(events) == 2
    second = events[1]
    assert second.dedup_key == f"trip-assembled:{trip_id}"
    assert second.payload["leg_count"] == 2


def _flight_extract(
    *,
    start_dt: str = "2026-08-01T10:00:00Z",
    end_dt: str = "2026-08-02T06:00:00Z",
    raw_ref: str,
) -> TripExtract:
    return TripExtract(
        kind=TripLegKind.FLIGHT,
        title="SQ322 SIN-LHR",
        start_dt=start_dt,
        end_dt=end_dt,
        origin="Singapore",
        destination="London",
        confirmation_ref="PNR123",
        raw_ref=raw_ref,
    )


def _hotel_extract(
    *,
    raw_ref: str = "m2:0",
    co_travellers: tuple[str, ...] = (),
) -> TripExtract:
    return TripExtract(
        kind=TripLegKind.HOTEL,
        title="London hotel",
        start_dt="2026-08-02T15:00:00Z",
        end_dt="2026-08-05T11:00:00Z",
        origin=None,
        destination="London",
        confirmation_ref="HTL456",
        co_travellers=co_travellers,
        raw_ref=raw_ref,
    )
