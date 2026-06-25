"""Calendar memory extraction through the DR-a quarantine chokepoint."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Final, Protocol

from artemis.memory.write_path import MemoryWriteQueue
from artemis.modules.calendar.cache import CachedEvent
from artemis.modules.calendar.untrusted import quarantine_event_text
from artemis.obs import get_logger
from artemis.untrusted.quarantine import QuarantinedReader

CALENDAR_MEMORY_QUERY: Final[str] = (
    "recurring meetings, standing 1:1s, key contacts, preferred working patterns, and "
    "commitments associated with the owner's calendar"
)

logger = get_logger("calendar.memory")


class MemoryQueuePort(Protocol):
    """Small queue seam implemented by ``MemoryWriteQueue`` and tests."""

    def enqueue(self, text: str, turn_id: str, role: str | None = None) -> None:
        """Queue sanitized calendar memory text."""
        ...


class CalendarMemoryExtractor:
    """Extract standing facts from qualifying events without exposing raw event text."""

    def __init__(
        self,
        reader: QuarantinedReader,
        queue: MemoryWriteQueue | MemoryQueuePort,
        *,
        owner_email: str,
    ) -> None:
        self._reader = reader
        self._queue = queue
        self._owner_email = owner_email

    async def extract(self, event: CachedEvent) -> None:
        """Quarantine and enqueue recurring or externally attended event facts."""
        # Conservative quality filter only; the security boundary is quarantine_event_text.
        if not (_is_recurring(event) or _has_external_attendees(event, self._owner_email)):
            return

        extract = await quarantine_event_text(self._reader, event)
        if not extract.usable:
            logger.warning(
                "calendar memory extraction skipped unusable event %s "
                "(parse_failed=%s, flagged=%s)",
                event.event_id,
                extract.parse_failed,
                extract.flagged_injection,
            )
            return
        text = (extract.summary + "\n" + "\n".join(extract.claims)).strip()
        if not text:
            return
        self._queue.enqueue(text=text, turn_id=f"calendar:{event.event_id}")

    async def extract_batch(self, events: Sequence[CachedEvent]) -> None:
        """Extract events independently so one bad event does not abort the batch."""
        for event in events:
            try:
                await self.extract(event)
            except Exception as exc:
                logger.warning(
                    "calendar memory extraction failed for event %s (%s)",
                    event.event_id,
                    type(exc).__name__,
                )


def _is_recurring(event: CachedEvent) -> bool:
    try:
        raw = json.loads(event.raw_json)
    except json.JSONDecodeError:
        return False
    if not isinstance(raw, dict):
        return False
    return bool(raw.get("recurrence") or raw.get("recurringEventId"))


def _has_external_attendees(event: CachedEvent, owner_email: str) -> bool:
    owner = owner_email.casefold()
    return any(attendee.casefold() != owner for attendee in event.attendees)
