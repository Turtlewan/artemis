from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest
import sqlite_vec  # type: ignore[import-untyped]

from artemis.config import Settings
from artemis.identity.key_provider import FakeKeyProvider
from artemis.identity.scope import OWNER_PRIVATE
from artemis.memory.entities import EntityRepository
from artemis.memory.schema import create_schema
from artemis.memory.trips import (
    TripAssembler,
    TripExtract,
    TripLegKind,
    TripRepository,
    create_trip_schema,
)
from artemis.modules.calendar.cache import CachedEvent, CalendarSyncEngine, EventCacheStore
from artemis.modules.calendar.client import FakeCalendarClient
from artemis.modules.calendar.preferences import CalPrefs
from artemis.modules.finance.recurring import detect_recurring
from artemis.modules.finance.store import FinanceStore
from artemis.modules.gmail.classify import EmailClassifier
from artemis.modules.gmail.extract_store import EmailExtractStore
from artemis.modules.gmail.ingest import GmailMemoryExtractor
from artemis.modules.gmail.structured import StructuredEmailExtract
from artemis.ports.types import PersonId
from artemis.reactions import DomainEvent, EventBus, EventType
from artemis.untrusted.quarantine import Extract

KEY = b"7" * 32
OWNER = PersonId("owner")


class FakeReader:
    def __init__(self, extract: Extract) -> None:
        self.extract = extract

    async def read(
        self,
        *,
        raw_content: str,
        source_url: str,
        source_domain: str,
        query: str,
        max_tokens: int = 1024,
    ) -> Extract:
        _ = raw_content, source_url, source_domain, query, max_tokens
        return self.extract


class FakeQueue:
    def __init__(self) -> None:
        self.items: list[tuple[str, str]] = []

    def enqueue(
        self,
        text: str,
        turn_id: str,
        role: str | None = None,
        *,
        source_sensitivity: object | None = None,
    ) -> None:
        _ = role, source_sensitivity
        self.items.append((turn_id, text))


class FakeEmailClassifier:
    def __init__(self, result: StructuredEmailExtract | None) -> None:
        self.result = result
        self.calls = 0

    async def classify(self, extract: Extract) -> StructuredEmailExtract | None:
        _ = extract
        self.calls += 1
        return self.result


class FakeEmailExtractStore:
    def __init__(self) -> None:
        self.puts: list[StructuredEmailExtract] = []

    def put(self, extract: StructuredEmailExtract) -> None:
        self.puts.append(extract)


class FakeCacheStore:
    def __init__(self) -> None:
        self.events: dict[tuple[str, str], CachedEvent] = {}
        self.sync_tokens: dict[str, str] = {}

    def upsert(self, event: CachedEvent) -> None:
        self.events[(event.event_id, event.calendar_id)] = event

    def delete(self, event_id: str, calendar_id: str) -> None:
        self.events.pop((event_id, calendar_id), None)

    def get_sync_token(self, calendar_id: str) -> str | None:
        return self.sync_tokens.get(calendar_id)

    def set_sync_token(self, calendar_id: str, token: str) -> None:
        self.sync_tokens[calendar_id] = token

    def query_events(
        self,
        *,
        calendar_ids: list[str] | None = None,
        time_min: str | None = None,
        time_max: str | None = None,
        status_filter: list[str] | None = None,
    ) -> list[CachedEvent]:
        _ = time_min, time_max
        events = list(self.events.values())
        if calendar_ids is not None:
            events = [event for event in events if event.calendar_id in calendar_ids]
        if status_filter is not None:
            events = [event for event in events if event.status in status_filter]
        return events

    def clear_calendar(self, calendar_id: str) -> None:
        for key in list(self.events):
            if key[1] == calendar_id:
                self.events.pop(key)
        self.sync_tokens.pop(calendar_id, None)


@dataclass(frozen=True)
class MemoryRepos:
    conn: sqlite3.Connection
    trip_repo: TripRepository
    entity_repo: EntityRepository


@pytest.mark.asyncio
async def test_gmail_option_b_payload_store_then_emit_without_content() -> None:
    structured = StructuredEmailExtract(
        source_ref="gmail:msg-1",
        summary="private summary text",
        has_commitment=True,
        has_event=False,
        has_gift_signal=False,
    )
    store = FakeEmailExtractStore()
    events: list[DomainEvent] = []

    result = await GmailMemoryExtractor(
        FakeReader(_extract(summary="private summary text", claims=("safe claim",))),
        FakeQueue(),
        classifier=cast(EmailClassifier, FakeEmailClassifier(structured)),
        extract_store=cast(EmailExtractStore, store),
        emit=events.append,
    ).extract(message_id="msg-1", body="raw body secret")

    assert result is True
    assert store.puts == [structured]
    assert len(events) == 1
    event = events[0]
    assert event.event_type is EventType.EMAIL_INGESTED
    assert set(event.payload) == {
        "message_id",
        "source_ref",
        "has_commitment",
        "has_event",
        "has_gift_signal",
    }
    assert event.payload == {
        "message_id": "msg-1",
        "source_ref": "gmail:msg-1",
        "has_commitment": True,
        "has_event": False,
        "has_gift_signal": False,
    }
    assert all(isinstance(value, (str, int, float, bool)) for value in event.payload.values())
    assert "raw body secret" not in repr(event)
    assert "private summary text" not in repr(event)


@pytest.mark.asyncio
async def test_gmail_no_emit_for_non_usable_and_unclassifiable() -> None:
    non_usable_events: list[DomainEvent] = []
    non_usable = await GmailMemoryExtractor(
        FakeReader(_extract(flagged_injection=True)),
        FakeQueue(),
        classifier=cast(EmailClassifier, FakeEmailClassifier(_structured("msg-1"))),
        emit=non_usable_events.append,
    ).extract(message_id="msg-1", body="raw")

    none_events: list[DomainEvent] = []
    classify_none = await GmailMemoryExtractor(
        FakeReader(_extract()),
        FakeQueue(),
        classifier=cast(EmailClassifier, FakeEmailClassifier(None)),
        emit=none_events.append,
    ).extract(message_id="msg-2", body="raw")

    assert non_usable is False
    assert classify_none is True
    assert non_usable_events == []
    assert none_events == []


def test_calendar_full_sync_emits_scalar_events_for_non_cancelled_only() -> None:
    events: list[DomainEvent] = []
    store = FakeCacheStore()
    client = FakeCalendarClient(
        [],
        {
            "primary": [
                _raw_event("a", "2026-06-22T09:00:00+00:00"),
                _raw_event("b", "2026-06-22T11:00:00+00:00"),
                {"id": "cancelled", "status": "cancelled"},
            ]
        },
        {},
    )

    result = CalendarSyncEngine(
        client,
        cast(EventCacheStore, store),
        CalPrefs(),
        emit=events.append,
    ).sync("primary", "owner@example.com")

    assert result.events_added == 2
    assert [event.event_type for event in events] == [
        EventType.EVENT_INGESTED,
        EventType.EVENT_INGESTED,
    ]
    assert {event.payload["event_id"] for event in events} == {"a", "b"}
    assert "cancelled" not in {event.payload["event_id"] for event in events}
    for event in events:
        assert set(event.payload) == {
            "event_id",
            "calendar_id",
            "start_dt",
            "end_dt",
            "externally_authored",
        }
        assert all(isinstance(value, (str, int, float, bool)) for value in event.payload.values())
        assert "Meeting" not in repr(event)


@pytest.mark.asyncio
async def test_four_producer_reachability_with_shared_bus(tmp_path: Path) -> None:
    seen: list[DomainEvent] = []
    bus = EventBus()
    bus.subscribe(seen.append)

    finance = FinanceStore(
        _settings(tmp_path),
        FakeKeyProvider({OWNER_PRIVATE: KEY}, owner_unlocked=True),
    )
    account_id = finance.create_account("Card", "card")
    for raw_ref, txn_date in (
        ("bill:1", "2026-01-05"),
        ("bill:2", "2026-02-04"),
        ("bill:3", "2026-03-06"),
    ):
        finance.add_transaction(
            txn_date=txn_date,
            amount=Decimal("88.00"),
            merchant="Power Utility",
            source="email",
            instrument_account_id=account_id,
            raw_ref=raw_ref,
            confidence=0.95,
            notes="statement due:2026-03-20",
        )
    detect_recurring(finance, min_occurrences=2, emit=bus.emit)

    repos = _memory_repos()
    try:
        TripAssembler(repos.trip_repo, repos.entity_repo, emit=bus.emit).assemble(
            TripExtract(
                kind=TripLegKind.FLIGHT,
                title="SQ322 SIN-LHR",
                start_dt="2026-08-01T10:00:00Z",
                end_dt="2026-08-02T06:00:00Z",
                origin="Singapore",
                destination="London",
                confirmation_ref="PNR123",
                raw_ref="mail:1",
            )
        )
    finally:
        repos.conn.close()

    await GmailMemoryExtractor(
        FakeReader(_extract()),
        FakeQueue(),
        classifier=cast(EmailClassifier, FakeEmailClassifier(_structured("msg-1"))),
        extract_store=cast(EmailExtractStore, FakeEmailExtractStore()),
        emit=bus.emit,
    ).extract(message_id="msg-1", body="raw")

    CalendarSyncEngine(
        FakeCalendarClient(
            [], {"primary": [_raw_event("event-1", "2026-06-22T09:00:00+00:00")]}, {}
        ),
        cast(EventCacheStore, FakeCacheStore()),
        CalPrefs(),
        emit=bus.emit,
    ).sync("primary", "owner@example.com")

    event_types = {event.event_type for event in seen}
    assert EventType.BILL_RECORDED in event_types or EventType.TXN_RECORDED in event_types
    assert EventType.TRIP_ASSEMBLED in event_types
    assert EventType.EMAIL_INGESTED in event_types
    assert EventType.EVENT_INGESTED in event_types


@pytest.mark.asyncio
async def test_noop_defaults_preserve_baseline_return_values() -> None:
    queue = FakeQueue()
    extracted = await GmailMemoryExtractor(FakeReader(_extract()), queue).extract(
        message_id="msg-1",
        body="raw",
    )
    calendar_result = CalendarSyncEngine(
        FakeCalendarClient(
            [], {"primary": [_raw_event("event-1", "2026-06-22T09:00:00+00:00")]}, {}
        ),
        cast(EventCacheStore, FakeCacheStore()),
        CalPrefs(),
    ).sync("primary", "owner@example.com")

    assert extracted is True
    assert queue.items == [("gmail:msg-1", "safe summary\nsafe claim")]
    assert calendar_result.events_added == 1


def _extract(
    *,
    summary: str = "safe summary",
    claims: tuple[str, ...] = ("safe claim",),
    flagged_injection: bool = False,
) -> Extract:
    return Extract(
        source_url="gmail:msg-1",
        source_domain="gmail",
        summary=summary,
        claims=claims,
        flagged_injection=flagged_injection,
        parse_failed=False,
        tokens_used=10,
    )


def _structured(message_id: str) -> StructuredEmailExtract:
    return StructuredEmailExtract(
        source_ref=f"gmail:{message_id}",
        summary="safe summary",
        has_commitment=True,
    )


def _raw_event(event_id: str, start: str) -> dict[str, object]:
    return {
        "id": event_id,
        "summary": "Meeting",
        "start": {"dateTime": start},
        "end": {"dateTime": start.replace("09:00", "10:00").replace("11:00", "12:00")},
        "status": "confirmed",
        "organizer": {"email": "other@example.com"},
        "creator": {"email": "other@example.com"},
    }


def _memory_repos() -> MemoryRepos:
    conn = sqlite3.connect(":memory:")
    conn.enable_load_extension(True)
    conn.load_extension(sqlite_vec.loadable_path())
    conn.enable_load_extension(False)
    conn.row_factory = sqlite3.Row
    create_schema(conn, embedder_model_id="test-fake", dimension=4)
    create_trip_schema(conn)
    return MemoryRepos(conn, TripRepository(conn), EntityRepository(conn, OWNER))


def _settings(tmp_path: Path) -> Settings:
    return Settings(data_root=tmp_path)
