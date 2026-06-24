"""Calendar knowledge ingest using trusted structural meeting metadata only."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from artemis.config import Settings
from artemis.identity.scope import OWNER_PRIVATE
from artemis.ingest.connectors import RawItem, Source
from artemis.ingest.pipeline import IngestPipeline, IngestResult
from artemis.modules.calendar.cache import CachedEvent, EventCacheStore
from artemis.obs import get_logger
from artemis.ports.types import Scope

logger = get_logger("calendar.knowledge")


class CalendarKnowledgeConnector:
    """Fetch one calendar event as a trusted metadata-only raw item."""

    def __init__(self, cache: EventCacheStore) -> None:
        self._cache = cache

    def fetch(self, source: Source) -> Iterable[RawItem]:
        """Return a metadata-only meeting document for ``calendar_meeting`` sources."""
        if source.kind != "calendar_meeting":
            raise ValueError(f"CalendarKnowledgeConnector cannot fetch source kind {source.kind!r}")
        event = _event_by_id(self._cache, source.uri)
        summary_text = (
            f"Meeting: {event.start_dt} – {event.end_dt}\n"
            f"Calendar: {event.calendar_id}\n"
            f"Attendees: {', '.join(event.attendees)}\n"
            f"Status: {event.status}"
        )
        yield RawItem(
            raw_bytes=None,
            text=summary_text,
            mime="text/plain",
            source_id=f"calendar:{event.event_id}",
            origin_uri=f"calendar:{event.event_id}",
            fetched_at=datetime.now(UTC),
            page_images=(),
        )


class CalendarKnowledgePusher:
    """Push past meetings into knowledge via the async M3 ingest pipeline."""

    def __init__(
        self,
        pipeline: IngestPipeline,
        cache: EventCacheStore,
        settings: Settings,
        *,
        scope: Scope = OWNER_PRIVATE,
    ) -> None:
        self._pipeline = pipeline
        self._cache = cache
        self._settings = settings
        self._scope = scope

    async def push_past_meeting(self, event_id: str) -> IngestResult:
        """Ingest one completed meeting; future meetings are rejected."""
        _ = self._settings
        event = _event_by_id(self._cache, event_id)
        end_dt = _parse_event_dt(event.end_dt)
        now = datetime.now(end_dt.tzinfo or UTC)
        if end_dt >= now:
            raise ValueError("cannot push a future event to knowledge")
        return await self._pipeline.ingest(
            Source(kind="calendar_meeting", uri=event_id, scope=self._scope)
        )

    async def push_window(self, *, after_iso: str, before_iso: str) -> list[IngestResult]:
        """Push completed meetings in a window, logging and continuing per failure."""
        results: list[IngestResult] = []
        for event in self._cache.query_events(time_min=after_iso, time_max=before_iso):
            try:
                results.append(await self.push_past_meeting(event.event_id))
            except Exception as exc:
                logger.warning(
                    "calendar knowledge push failed for event %s (%s)",
                    event.event_id,
                    type(exc).__name__,
                )
        return results


def _event_by_id(cache: EventCacheStore, event_id: str) -> CachedEvent:
    events = cache.query_events(status_filter=["confirmed", "tentative", "cancelled"])
    for event in events:
        if event.event_id == event_id:
            return event
    raise KeyError(event_id)


def _parse_event_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed
