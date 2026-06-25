from __future__ import annotations

import logging

import pytest
from pydantic import ValidationError

from artemis.memory import EntityRef
from artemis.reactions import DomainEvent, EventBus, EventType


def _event() -> DomainEvent:
    return DomainEvent(
        event_type=EventType.TXN_RECORDED,
        source_module="finance",
        entity_refs=(EntityRef(module="finance", entity_id="txn:1"),),
        payload={"txn_id": "txn:1", "amount": "19.99", "cleared": True},
        occurred_at="2026-06-23T00:00:00+00:00",
        dedup_key="txn:txn:1",
    )


def test_domain_event_constructs_with_scalar_payload_and_entity_refs() -> None:
    ref = EntityRef(module="memory", entity_id="person:abc")

    event = DomainEvent(
        event_type=EventType.FACT_ADDED,
        source_module="memory",
        entity_refs=(ref,),
        payload={"fact_id": "fact:1", "count": 1, "score": 0.5, "active": False},
        occurred_at="2026-06-23T00:00:00+00:00",
        dedup_key="fact:fact:1",
    )

    assert event.entity_refs == (ref,)
    assert event.payload["fact_id"] == "fact:1"


@pytest.mark.parametrize(
    "payload",
    [
        {"titles": ["a", "b"]},
        {"note": {"x": 1}},
    ],
)
def test_domain_event_rejects_non_scalar_payload_values(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        DomainEvent(
            event_type=EventType.EMAIL_INGESTED,
            source_module="gmail",
            payload=payload,
            occurred_at="2026-06-23T00:00:00+00:00",
            dedup_key="email:1",
        )


def test_domain_event_rejects_empty_dedup_key() -> None:
    with pytest.raises(ValidationError):
        DomainEvent(
            event_type=EventType.TASK_DONE,
            source_module="tasks",
            payload={"task_id": "task:1"},
            occurred_at="2026-06-23T00:00:00+00:00",
            dedup_key="",
        )


def test_event_bus_fans_out_to_all_subscribers_once() -> None:
    event = _event()
    first_seen: list[DomainEvent] = []
    second_seen: list[DomainEvent] = []
    bus = EventBus()

    bus.subscribe(first_seen.append)
    bus.subscribe(second_seen.append)
    bus.emit(event)

    assert first_seen == [event]
    assert second_seen == [event]


def test_event_bus_isolates_raising_subscriber() -> None:
    event = _event()
    seen: list[DomainEvent] = []
    bus = EventBus()

    def broken_subscriber(_: DomainEvent) -> None:
        raise RuntimeError("sink failed")

    bus.subscribe(broken_subscriber)
    bus.subscribe(seen.append)

    bus.emit(event)

    assert seen == [event]


def test_event_bus_log_contains_event_type_and_payload_keys_but_not_values(
    caplog: pytest.LogCaptureFixture,
) -> None:
    event = _event()
    logger = logging.getLogger("tests.reactions.emit")
    bus = EventBus(logger=logger)

    with caplog.at_level(logging.DEBUG, logger=logger.name):
        bus.emit(event)

    formatted_records = [record.getMessage() for record in caplog.records]
    assert any(EventType.TXN_RECORDED.value in message for message in formatted_records)
    assert any("amount" in message for message in formatted_records)
    assert all("19.99" not in message for message in formatted_records)
