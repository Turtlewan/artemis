from __future__ import annotations

from collections.abc import Sequence

from artemis.memory import EntityRef, TripExtract
from artemis.modules.calendar.create_from_extract import (
    EventExtract,
    HeldEventStatus,
    HeldTentativeEvent,
)
from artemis.ports.types import Vector
from artemis.reactions.emit import DomainEvent, EventType
from artemis.reactions.recipes import register_comms_reactions
from artemis.reactions.recipes.comms import (
    ReactionArgs,
    ReactionResult,
    react_commitment_to_task,
    react_email_to_held_event,
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


class FakeDispatcher:
    def __init__(self) -> None:
        self.ledger: set[str] = set()

    async def fire(
        self,
        rule: ReactionRule,
        event: DomainEvent,
        capture: FakeCaptureService,
    ) -> None:
        key = _stable_key(rule, event)
        if key in self.ledger:
            return
        self.ledger.add(key)
        result = await react_commitment_to_task(event, capture_service=capture)
        assert isinstance(result, ReactionResult)


async def test_a4_inert_suggestion_uses_extract_summary_and_dedups() -> None:
    capture = FakeCaptureService()
    rule = _email_to_task_rule()
    dispatcher = FakeDispatcher()
    event = _email_event(
        {
            "message_id": "m1",
            "extract_id": "x1",
            "commitment_detected": True,
            "extract_summary": "Please send the report tomorrow.",
            "raw_body": "RAW SHOULD NOT BE USED",
        }
    )

    result = await react_commitment_to_task(event, capture_service=capture)
    await dispatcher.fire(rule, event, capture)
    await dispatcher.fire(rule, event, capture)

    assert result.status == "suggested"
    assert result.ref == "suggestion-1"
    assert capture.calls == [
        ("email", "Please send the report tomorrow.", True),
        ("email", "Please send the report tomorrow.", True),
    ]
    assert all("RAW SHOULD NOT BE USED" not in call[1] for call in capture.calls)
    assert capture.direct_task_creates == 0


async def test_a4_guard_skips_when_commitment_flag_absent() -> None:
    capture = FakeCaptureService()

    result = await react_commitment_to_task(
        _email_event({"message_id": "m1", "extract_summary": "Send it"}),
        capture_service=capture,
    )

    assert result.status == "skipped"
    assert capture.calls == []


async def test_a7_meeting_creates_held_event_without_google_write() -> None:
    calendar = FakeCalendarFromExtract()
    trip_assembler = FakeTripAssembler()

    result = await react_email_to_held_event(
        _meeting_event(),
        calendar_from_extract_fn=calendar,
        trip_assembler=trip_assembler,
    )

    assert result.status == "held"
    assert result.ref == "held-meeting"
    assert calendar.google_write_calls == 0
    assert len(calendar.calls) == 1
    extract, event_type = calendar.calls[0]
    assert event_type == "meeting"
    assert extract.summary == "Planning meeting."
    assert extract.raw_ref == "m-meeting:0"
    assert trip_assembler.calls == []


async def test_a5_flight_builds_trip_extract_and_held_event_no_maps_or_airport_block() -> None:
    calendar = FakeCalendarFromExtract()
    trip_assembler = FakeTripAssembler()
    event = _flight_event(message_id="m-flight")

    result = await react_email_to_held_event(
        event,
        calendar_from_extract_fn=calendar,
        trip_assembler=trip_assembler,
    )
    second = await react_email_to_held_event(
        _flight_event(message_id="m-flight-2"),
        calendar_from_extract_fn=calendar,
        trip_assembler=trip_assembler,
    )

    assert result.status == "held"
    assert second.status == "held"
    assert [call[1] for call in calendar.calls] == ["flight", "flight"]
    assert len(trip_assembler.calls) == 2
    first_trip_extract = trip_assembler.calls[0]
    assert first_trip_extract.kind.value == "flight"
    assert first_trip_extract.title == "Flight SQ1"
    assert first_trip_extract.origin == "Singapore"
    assert first_trip_extract.destination == "Tokyo"
    assert first_trip_extract.co_travellers == ("Ashley",)
    assert first_trip_extract.raw_ref == "m-flight:0"
    assert trip_assembler.trip_ids == {
        ("Tokyo", "2026-07-01T08:00:00Z", "2026-07-01T15:00:00Z"): "trip-1"
    }
    assert not hasattr(calendar, "airport_block_calls")


async def test_register_comms_reactions_rules_registry_and_tool_wrappers() -> None:
    registry = ToolRegistry(FakeEmbedder())
    capture = FakeCaptureService()
    calendar = FakeCalendarFromExtract()
    trip_assembler = FakeTripAssembler()

    rules = register_comms_reactions(
        registry,
        capture_service=capture,
        calendar_from_extract_fn=calendar,
        trip_assembler=trip_assembler,
        memory=FakeMemory(),
    )

    assert [rule.name for rule in rules] == [
        "reaction:email_to_task",
        "reaction:email_to_held_event",
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

    task_tool = registry.get_tool("reaction:email_to_task")
    task_result = await task_tool.callable_ref(
        ReactionArgs(
            event_type=EventType.EMAIL_INGESTED.value,
            source_module="gmail",
            occurred_at="2026-06-25T00:00:00+00:00",
            dedup_key="email:m1",
            message_id="m1",
            commitment_detected=True,
            extract_summary="Please send the report tomorrow.",
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
            event_kind="meeting",
            extract_summary="Planning meeting.",
            start_datetime="2026-07-01T08:00:00Z",
            end_datetime="2026-07-01T09:00:00Z",
        )
    )
    assert isinstance(held_result, ReactionResult)
    assert held_result.status == "held"


def test_gift_signal_recipe_blocked_until_module_fact_push_exists() -> None:
    registry = ToolRegistry(FakeEmbedder())
    rules = register_comms_reactions(
        registry,
        capture_service=FakeCaptureService(),
        calendar_from_extract_fn=FakeCalendarFromExtract(),
        trip_assembler=FakeTripAssembler(),
        memory=FakeMemory(),
    )

    assert "reaction:gift_signal" not in {rule.reaction_ref for rule in rules}
    try:
        registry.get_tool("reaction:gift_signal")
    except KeyError:
        pass
    else:
        raise AssertionError("gift-signal must wait for module fact-push prerequisite")


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


def _meeting_event() -> DomainEvent:
    return _email_event(
        {
            "message_id": "m-meeting",
            "extract_id": "x-meeting",
            "event_kind": "meeting",
            "extract_summary": "Planning meeting.",
            "start_datetime": "2026-07-01T08:00:00Z",
            "end_datetime": "2026-07-01T09:00:00Z",
            "location": "Office",
            "attendee_emails": "owner@example.com, friend@example.com",
        }
    )


def _flight_event(*, message_id: str) -> DomainEvent:
    return _email_event(
        {
            "message_id": message_id,
            "extract_id": f"x-{message_id}",
            "event_kind": "flight",
            "extract_summary": "Flight to Tokyo.",
            "title": "Flight SQ1",
            "start_datetime": "2026-07-01T08:00:00Z",
            "end_datetime": "2026-07-01T15:00:00Z",
            "origin": "Singapore",
            "destination": "Tokyo",
            "confirmation_ref": "ABC123",
            "co_travellers": "Ashley",
        }
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
