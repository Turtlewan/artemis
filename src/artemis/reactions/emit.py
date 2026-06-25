"""Domain-event emit seam for Artemis reactions.

This module is the canonical event-type registry and producer-side bus. Payloads
are structurally limited to scalar ids/counts/timestamps; cross-module pointers
belong in ``EntityRef`` values instead of raw titles, names, notes, or bodies.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from artemis.memory import EntityRef


class EventType(StrEnum):
    """Canonical domain events published by module write points."""

    EMAIL_INGESTED = "email-ingested"
    TXN_RECORDED = "txn-recorded"
    BILL_RECORDED = "bill-recorded"
    SUBSCRIPTION_DETECTED = "subscription-detected"
    TASK_DONE = "task-done"
    TASK_CREATED = "task-created"
    FACT_ADDED = "fact-added"
    EVENT_INGESTED = "event-ingested"
    PAYMENT_RECORDED = "payment-recorded"
    TRIP_ASSEMBLED = "trip-assembled"
    BILL_PAID = "bill-paid"


class DomainEvent(BaseModel):
    """Reaction event containing only ids, scalar payload values, and entity refs."""

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    event_type: EventType
    source_module: str
    entity_refs: tuple[EntityRef, ...] = ()
    payload: dict[str, str | int | float | bool] = Field(default_factory=dict)
    occurred_at: str
    dedup_key: str

    @model_validator(mode="after")
    def _validate_payload_and_dedup_key(self) -> Self:
        for value in self.payload.values():
            if not isinstance(value, (str, int, float, bool)):
                raise ValueError(
                    "DomainEvent payload values must be scalars — no raw text/structures"
                )
        if not self.dedup_key:
            raise ValueError("DomainEvent dedup_key must be non-empty")
        return self


Subscriber = Callable[[DomainEvent], None]


class EventBus:
    """Synchronous publish bus for reaction events.

    Async dispatchers register a sync enqueue shim; ``emit`` itself does not run
    async work. The debug log carries event type, source module, entity-ref ids,
    payload keys, and the dedup key only - never payload values or raw text.
    """

    def __init__(self, *, logger: logging.Logger | None = None) -> None:
        self._subscribers: list[Subscriber] = []
        self._log = logger or logging.getLogger("artemis.reactions.emit")

    def subscribe(self, sink: Subscriber) -> None:
        """Register a sink for emitted domain events."""
        self._subscribers.append(sink)

    def emit(self, event: DomainEvent) -> None:
        """Publish a domain event to all subscribers, isolating subscriber failures."""
        self._log.debug(
            "emit %s from %s refs=%s keys=%s dedup=%s",
            event.event_type,
            event.source_module,
            [ref.entity_id for ref in event.entity_refs],
            sorted(event.payload.keys()),
            event.dedup_key,
        )
        for sink in self._subscribers:
            try:
                sink(event)
            except Exception:
                self._log.warning(
                    "reaction subscriber failed for %s",
                    event.event_type,
                    exc_info=True,
                )
