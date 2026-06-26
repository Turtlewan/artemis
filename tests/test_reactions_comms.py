from __future__ import annotations

import inspect
from collections.abc import Sequence
from typing import cast

from artemis.memory import EntityRef, TripExtract
from artemis.memory.write_path import MemoryWritePath
from artemis.modules.calendar.create_from_extract import (
    EventExtract,
    HeldEventStatus,
    HeldTentativeEvent,
)
from artemis.modules.gmail.structured import StructuredEmailExtract
from artemis.ports.types import Vector
from artemis.reactions.emit import DomainEvent, EventType
from artemis.reactions.recipes import comms, register_comms_reactions
from artemis.reactions.recipes.comms import (
    ReactionArgs,
    ReactionResult,
    react_commitment_to_task,
    react_email_to_held_event,
    react_gift_signal,
)
from artemis.reactions.rulestore import TIER_A_BUILTINS, ReactionRule, ReactionTier
from artemis.registry import ToolRegistry


class FakeEmbedder:
    @property
    def dimension(self) -> int:
        return 2

    async def embed_documents(self, texts: Sequence[str]) -> list[Vector]:
        return [[1.0, 0.0] for _ in texts]

    async def embed_query(self, query: str) -> Vector:
        del query
        return [1.0, 0.0]


class FakeCaptureService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, bool]] = []
        self.direct_task_creates = 0

    async def suggest_from_text(self, source: str, text: str, *, untrusted: bool) -> str:
        self.calls.append((source, text, untrusted))
        return "suggestion-1"


class FakeCalendarFromExtract:
    def __init__(self) -> None:
        self.calls: list[tuple[EventExtract, str]] = []
        self.google_write_calls = 0

    async def __call__(self, extract: EventExtract, event_type: str) -> HeldTentativeEvent:
        self.calls.append((extract, event_type))
        return HeldTentativeEvent(
            id=f"held-{event_type}",
            event_type=event_type,
            summary=extract.summary,
            start_datetime=extract.start_datetime,
            end_datetime=extract.end_datetime,
            location=extract.location,
            description=extract.description,
            attendee_emails=extract.attendee_emails,
            status=HeldEventStatus.HELD,
            raw_ref=extract.raw_ref,
            google_event_id=None,
            pending_action_id=None,
        )


class FakeTripAssembler:
    def __init__(self) -> None:
        self.calls: list[TripExtract] = []
        self.trip_ids: dict[tuple[str | None, str | None, str | None], str] = {}
        self.keyword_args_seen = False

    def assemble(self, extract: TripExtract) -> str:
        self.calls.append(extract)
        key = (extract.destination, extract.start_dt, extract.end_dt)
        return self.trip_ids.setdefault(key, f"trip-{len(self.trip_ids) + 1}")


class FakeMemory:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def add_module_fact(
        self,
        *,
        subject: str,
        relation: str,
        object_: str,
        category: str,
        source_ref: str,
        sensitivity: str,
    ) -> str:
        self.calls.append(
            {
                "subject": subject,
                "relation": relation,
                "object_": object_,
                "category": category,
                "source_ref": source_ref,
                "sensitivity": sensitivity,
            }
        )
        return "fact-1"


class FakeFetchExtract:
    def __init__(self, extracts: dict[str, StructuredEmailExtract]) -> None:
        self.extracts = extracts
        self.calls: list[str] = []

    async def __call__(self, source_ref: str) -> StructuredEmailExtract | None:
        self.calls.append(source_ref)
        return self.extracts.get(source_ref)


class FakeDispatcher:
    def __init__(self) -> None:
        self.ledger: set[str] = set()

    async def fire(
        self,
        rule: ReactionRule,
        event: DomainEvent,
        capture: FakeCaptureService,
        fetch_extract: FakeFetchExtract,
    ) -> None:
        key = _stable_key(rule, event)
        if key in self.ledger:
            return
        self.ledger.add(key)
        result = await react_commitment_to_task(
            event,
            capture_service=capture,
            fetch_extract=fetch_extract,
        )
        assert isinstance(result, ReactionResult)


async def test_a4_inert_suggestion_fetches_summary_and_dedups() -> None:
    capture = FakeCaptureService()
    fetch = FakeFetchExtract(
        {"gmail:m1": _structured(source_ref="gmail:m1", summary="Please send the report tomorrow.")}
    )
    rule = _email_to_task_rule()
    dispatcher = FakeDispatcher()
    event = _email_event(
        {
            "message_id": "m1",
            "source_ref": "gmail:m1",
            "has_commitment": True,
            "raw_body": "RAW SHOULD NOT BE USED",
        }
    )

    result = await react_commitment_to_task(
        event,
        capture_service=capture,
        fetch_extract=fetch,
    )
    await dispatcher.fire(rule, event, capture, fetch)
    await dispatcher.fire(rule, event, capture, fetch)

    assert result.status == "suggested"
    assert result.ref == "suggestion-1"
    assert capture.calls == [
        ("email", "Please send the report tomorrow.", True),
        ("email", "Please send the report tomorrow.", True),
    ]
    assert fetch.calls == ["gmail:m1", "gmail:m1"]
    assert all("RAW SHOULD NOT BE USED" not in call[1] for call in capture.calls)
    assert capture.direct_task_creates == 0


async def test_a4_guard_skips_when_commitment_flag_absent_without_fetching() -> None:
    capture = FakeCaptureService()
    fetch = FakeFetchExtract(
        {"gmail:m1": _structured(source_ref="gmail:m1", summary="Please send the report.")}
    )

    result = await react_commitment_to_task(
        _email_event({"message_id": "m1", "source_ref": "gmail:m1", "has_commitment": False}),
        capture_service=capture,
        fetch_extract=fetch,
    )

    assert result.status == "skipped"
    assert capture.calls == []
    assert fetch.calls == []


async def test_a7_meeting_fetches_extract_and_creates_held_event_without_google_write() -> None:
    calendar = FakeCalendarFromExtract()
    trip_assembler = FakeTripAssembler()
    fetch = FakeFetchExtract({"gmail:m-meeting": _meeting_extract()})

    result = await react_email_to_held_event(
        _email_event(
            {"message_id": "m-meeting", "source_ref": "gmail:m-meeting", "has_event": True}
        ),
        calendar_from_extract_fn=calendar,
        trip_assembler=trip_assembler,
        fetch_extract=fetch,
    )

    assert result.status == "held"
    assert result.ref == "held-meeting"
    assert fetch.calls == ["gmail:m-meeting"]
    assert calendar.google_write_calls == 0
    assert len(calendar.calls) == 1
    extract, event_type = calendar.calls[0]
    assert event_type == "meeting"
    assert extract.summary == "Planning meeting."
    assert extract.raw_ref == "gmail:m-meeting"
    assert trip_assembler.calls == []


async def test_a5_flight_fetches_extract_builds_trip_and_held_event() -> None:
    calendar = FakeCalendarFromExtract()
    trip_assembler = FakeTripAssembler()
    fetch = FakeFetchExtract(
        {
            "gmail:m-flight": _flight_extract(source_ref="gmail:m-flight"),
            "gmail:m-flight-2": _flight_extract(source_ref="gmail:m-flight-2"),
        }
    )

    result = await react_email_to_held_event(
        _email_event({"message_id": "m-flight", "source_ref": "gmail:m-flight", "has_event": True}),
        calendar_from_extract_fn=calendar,
        trip_assembler=trip_assembler,
        fetch_extract=fetch,
    )
    second = await react_email_to_held_event(
        _email_event(
            {"message_id": "m-flight-2", "source_ref": "gmail:m-flight-2", "has_event": True}
        ),
        calendar_from_extract_fn=calendar,
        trip_assembler=trip_assembler,
        fetch_extract=fetch,
    )

    assert result.status == "held"
    assert second.status == "held"
    assert fetch.calls == ["gmail:m-flight", "gmail:m-flight-2"]
    assert [call[1] for call in calendar.calls] == ["flight", "flight"]
    assert len(trip_assembler.calls) == 2
    first_trip_extract = trip_assembler.calls[0]
    assert first_trip_extract.kind.value == "flight"
    assert first_trip_extract.title == "Flight SQ1"
    assert first_trip_extract.origin == "Singapore"
    assert first_trip_extract.destination == "Tokyo"
    assert first_trip_extract.co_travellers == ("Ashley",)
    assert first_trip_extract.raw_ref == "gmail:m-flight"
    assert trip_assembler.trip_ids == {
        ("Tokyo", "2026-07-01T08:00:00Z", "2026-07-01T15:00:00Z"): "trip-1"
    }
    assert not hasattr(calendar, "airport_block_calls")


async def test_a5_a7_skip_non_flight_or_meeting_extract() -> None:
    calendar = FakeCalendarFromExtract()
    trip_assembler = FakeTripAssembler()
    fetch = FakeFetchExtract({"gmail:m1": _structured(source_ref="gmail:m1", event_kind="dentist")})

    result = await react_email_to_held_event(
        _email_event({"message_id": "m1", "source_ref": "gmail:m1", "has_event": True}),
        calendar_from_extract_fn=calendar,
        trip_assembler=trip_assembler,
        fetch_extract=fetch,
    )

    assert result.status == "skipped"
    assert fetch.calls == ["gmail:m1"]
    assert calendar.calls == []
    assert trip_assembler.calls == []


async def test_gift_signal_writes_general_module_fact() -> None:
    memory = FakeMemory()
    fetch = FakeFetchExtract(
        {
            "gmail:m-gift": _structured(
                source_ref="gmail:m-gift",
                has_gift_signal=True,
                gift_item="fountain pen",
                gift_recipient="Taylor",
            )
        }
    )

    result = await react_gift_signal(
        _email_event(
            {"message_id": "m-gift", "source_ref": "gmail:m-gift", "has_gift_signal": True}
        ),
        memory=cast(MemoryWritePath, memory),
        fetch_extract=fetch,
    )

    assert result.status == "noted"
    assert result.ref == "fact-1"
    assert result.undoable is True
    assert memory.calls == [
        {
            "subject": "Taylor",
            "relation": "interested_in",
            "object_": "fountain pen",
            "category": "gift_signal",
            "source_ref": "gmail:m-gift",
            "sensitivity": "general",
        }
    ]
    assert inspect.getsource(comms).count('sensitivity="general"') == 1


async def test_gift_signal_skips_missing_recipient() -> None:
    memory = FakeMemory()
    fetch = FakeFetchExtract(
        {
            "gmail:m-gift": _structured(
                source_ref="gmail:m-gift",
                has_gift_signal=True,
                gift_item="fountain pen",
                gift_recipient=None,
            )
        }
    )

    result = await react_gift_signal(
        _email_event(
            {"message_id": "m-gift", "source_ref": "gmail:m-gift", "has_gift_signal": True}
        ),
        memory=cast(MemoryWritePath, memory),
        fetch_extract=fetch,
    )

    assert result.status == "skipped"
    assert fetch.calls == ["gmail:m-gift"]
    assert memory.calls == []


async def test_malformed_source_ref_skips_without_fetching() -> None:
    capture = FakeCaptureService()
    calendar = FakeCalendarFromExtract()
    trip_assembler = FakeTripAssembler()
    memory = FakeMemory()
    fetch = FakeFetchExtract({})

    task_result = await react_commitment_to_task(
        _email_event({"message_id": "m1", "source_ref": "evil:1", "has_commitment": True}),
        capture_service=capture,
        fetch_extract=fetch,
    )
    held_result = await react_email_to_held_event(
        _email_event({"message_id": "m2", "source_ref": "", "has_event": True}),
        calendar_from_extract_fn=calendar,
        trip_assembler=trip_assembler,
        fetch_extract=fetch,
    )
    gift_result = await react_gift_signal(
        _email_event({"message_id": "m3", "source_ref": "evil:1", "has_gift_signal": True}),
        memory=cast(MemoryWritePath, memory),
        fetch_extract=fetch,
    )

    assert [task_result.status, held_result.status, gift_result.status] == [
        "skipped",
        "skipped",
        "skipped",
    ]
    assert fetch.calls == []
    assert capture.calls == []
    assert calendar.calls == []
    assert memory.calls == []


async def test_register_comms_reactions_rules_registry_and_tool_wrappers() -> None:
    registry = ToolRegistry(FakeEmbedder())
    capture = FakeCaptureService()
    calendar = FakeCalendarFromExtract()
    trip_assembler = FakeTripAssembler()
    memory = FakeMemory()
    fetch = FakeFetchExtract(
        {
            "gmail:m1": _structured(
                source_ref="gmail:m1",
                summary="Please send the report tomorrow.",
                has_commitment=True,
            ),
            "gmail:m2": _meeting_extract(source_ref="gmail:m2"),
            "gmail:m3": _structured(
                source_ref="gmail:m3",
                has_gift_signal=True,
                gift_item="fountain pen",
                gift_recipient="Taylor",
            ),
        }
    )

    rules = register_comms_reactions(
        registry,
        capture_service=capture,
        calendar_from_extract_fn=calendar,
        trip_assembler=trip_assembler,
        fetch_extract=fetch,
        memory=memory,
    )

    assert [rule.name for rule in rules] == [
        "reaction:email_to_task",
        "reaction:email_to_held_event",
        "reaction:gift_signal",
    ]
    for rule in rules:
        assert rule.event_type is EventType.EMAIL_INGESTED
        assert rule.tier is ReactionTier.B
        assert rule.external_effect is False
        assert isinstance(rule.reaction_ref, str)
        assert rule.dedup_key_fields == ("message_id",)
        assert rule not in TIER_A_BUILTINS
        assert registry.get_tool(rule.reaction_ref).callable_ref is not None

    assert rules[1].stateful is True
    assert rules[2].reaction_ref == "reaction:gift_signal"
    assert rules[2].stateful is False

    task_tool = registry.get_tool("reaction:email_to_task")
    task_result = await task_tool.callable_ref(
        ReactionArgs(
            event_type=EventType.EMAIL_INGESTED.value,
            source_module="gmail",
            occurred_at="2026-06-25T00:00:00+00:00",
            dedup_key="email:m1",
            message_id="m1",
            source_ref="gmail:m1",
            has_commitment=True,
        )
    )
    assert isinstance(task_result, ReactionResult)
    assert task_result.status == "suggested"

    held_tool = registry.get_tool("reaction:email_to_held_event")
    held_result = await held_tool.callable_ref(
        ReactionArgs(
            event_type=EventType.EMAIL_INGESTED.value,
            source_module="gmail",
            occurred_at="2026-06-25T00:00:00+00:00",
            dedup_key="email:m2",
            message_id="m2",
            source_ref="gmail:m2",
            has_event=True,
        )
    )
    assert isinstance(held_result, ReactionResult)
    assert held_result.status == "held"

    gift_tool = registry.get_tool("reaction:gift_signal")
    gift_result = await gift_tool.callable_ref(
        ReactionArgs(
            event_type=EventType.EMAIL_INGESTED.value,
            source_module="gmail",
            occurred_at="2026-06-25T00:00:00+00:00",
            dedup_key="email:m3",
            message_id="m3",
            source_ref="gmail:m3",
            has_gift_signal=True,
        )
    )
    assert isinstance(gift_result, ReactionResult)
    assert gift_result.status == "noted"
    assert memory.calls == [
        {
            "subject": "Taylor",
            "relation": "interested_in",
            "object_": "fountain pen",
            "category": "gift_signal",
            "source_ref": "gmail:m3",
            "sensitivity": "general",
        }
    ]


def test_import_reexport() -> None:
    from artemis.reactions.recipes import register_comms_reactions as imported

    assert imported is register_comms_reactions


def _email_event(payload: dict[str, str | int | float | bool]) -> DomainEvent:
    return DomainEvent(
        event_type=EventType.EMAIL_INGESTED,
        source_module="gmail",
        entity_refs=(EntityRef(module="gmail", entity_id=str(payload.get("message_id", "m1"))),),
        payload=payload,
        occurred_at="2026-06-25T00:00:00+00:00",
        dedup_key=f"email:{payload.get('message_id', 'm1')}",
    )


def _structured(
    *,
    source_ref: str,
    summary: str = "Structured summary.",
    has_commitment: bool = False,
    has_event: bool = False,
    has_gift_signal: bool = False,
    event_kind: str | None = None,
    title: str | None = None,
    start_datetime: str | None = None,
    end_datetime: str | None = None,
    location: str | None = None,
    description: str | None = None,
    attendee_emails: tuple[str, ...] = (),
    origin: str | None = None,
    destination: str | None = None,
    confirmation_ref: str | None = None,
    co_travellers: tuple[str, ...] = (),
    gift_item: str | None = None,
    gift_recipient: str | None = None,
) -> StructuredEmailExtract:
    return StructuredEmailExtract(
        source_ref=source_ref,
        summary=summary,
        has_commitment=has_commitment,
        has_event=has_event,
        has_gift_signal=has_gift_signal,
        event_kind=event_kind,
        title=title,
        start_datetime=start_datetime,
        end_datetime=end_datetime,
        location=location,
        description=description,
        attendee_emails=attendee_emails,
        origin=origin,
        destination=destination,
        confirmation_ref=confirmation_ref,
        co_travellers=co_travellers,
        gift_item=gift_item,
        gift_recipient=gift_recipient,
    )


def _meeting_extract(*, source_ref: str = "gmail:m-meeting") -> StructuredEmailExtract:
    return _structured(
        source_ref=source_ref,
        summary="Planning meeting.",
        has_event=True,
        event_kind="meeting",
        start_datetime="2026-07-01T08:00:00Z",
        end_datetime="2026-07-01T09:00:00Z",
        location="Office",
        attendee_emails=("owner@example.com", "friend@example.com"),
    )


def _flight_extract(*, source_ref: str) -> StructuredEmailExtract:
    return _structured(
        source_ref=source_ref,
        summary="Flight to Tokyo.",
        has_event=True,
        event_kind="flight",
        title="Flight SQ1",
        start_datetime="2026-07-01T08:00:00Z",
        end_datetime="2026-07-01T15:00:00Z",
        origin="Singapore",
        destination="Tokyo",
        confirmation_ref="ABC123",
        co_travellers=("Ashley",),
    )


def _email_to_task_rule() -> ReactionRule:
    return ReactionRule(
        name="reaction:email_to_task",
        event_type=EventType.EMAIL_INGESTED,
        tier=ReactionTier.B,
        external_effect=False,
        reaction_ref="reaction:email_to_task",
        dedup_key_fields=("message_id",),
    )


def _stable_key(rule: ReactionRule, event: DomainEvent) -> str:
    parts = [rule.name]
    for field in rule.dedup_key_fields:
        value = event.dedup_key if field == "dedup_key" else event.payload.get(field)
        parts.append(str(value or ""))
    parts.append(event.dedup_key)
    return ":".join(parts)
