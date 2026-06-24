"""Quarantine calendar event text before any privileged LLM consumer sees it."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from artemis.modules.calendar.cache import CachedEvent
from artemis.obs import get_logger
from artemis.untrusted.quarantine import QuarantinedReader

CALENDAR_QUARANTINE_QUERY: Final[str] = (
    "standing facts, commitments, key contacts, recurring meetings, and locations associated "
    "with this calendar event"
)

logger = get_logger("calendar.untrusted")


@dataclass(frozen=True)
class CalendarExtract:
    """Calendar-domain wrapper around a sanitized DR-a extract."""

    source_event_id: str
    summary: str
    claims: tuple[str, ...]
    flagged_injection: bool
    parse_failed: bool


async def quarantine_event_text(reader: QuarantinedReader, event: CachedEvent) -> CalendarExtract:
    """Return the only event text shape safe for privileged calendar consumers.

    Self-created events are trusted passthroughs. Externally authored title,
    description, and location fields go through DR-a quarantine; callers must
    treat ``parse_failed=True`` as unusable content.
    """
    if not event.externally_authored:
        return CalendarExtract(
            source_event_id=event.event_id,
            summary=f"{event.summary}\n{event.description or ''}",
            claims=(),
            flagged_injection=False,
            parse_failed=False,
        )

    raw_content = (
        f"Title: {event.summary}\n"
        f"Description: {event.description or ''}\n"
        f"Location: {event.location or ''}"
    )
    extract = await reader.read(
        raw_content=raw_content,
        source_url=f"calendar:{event.event_id}",
        source_domain="calendar.google.com",
        query=CALENDAR_QUARANTINE_QUERY,
        max_tokens=512,
    )
    if extract.parse_failed:
        logger.warning("quarantine failed for event %s", event.event_id)
        return CalendarExtract(
            source_event_id=event.event_id,
            summary="",
            claims=(),
            flagged_injection=False,
            parse_failed=True,
        )
    if extract.flagged_injection:
        logger.warning("injection attempt flagged in calendar event %s", event.event_id)
    return CalendarExtract(
        source_event_id=event.event_id,
        summary=extract.summary,
        claims=extract.claims,
        flagged_injection=extract.flagged_injection,
        parse_failed=False,
    )
