"""Regression: injection-flagged Extract content must not reach consumers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest

from artemis.modules.calendar.cache import CachedEvent
from artemis.modules.calendar.memory import CalendarMemoryExtractor
from artemis.modules.gmail.cache import CachedMessage, GmailReadCache
from artemis.modules.gmail.client import MailCategory
from artemis.modules.gmail.ingest import GmailMemoryExtractor
from artemis.modules.gmail.urgency import GmailUrgencyPreFilter
from artemis.sensitivity import Sensitivity
from artemis.untrusted.quarantine import Extract, QuarantinedReader

OWNER_EMAIL = "owner@example.com"


def _flagged(domain: str = "evil.com") -> Extract:
    return Extract(
        source_url="u",
        source_domain=domain,
        summary="",
        claims=(),
        flagged_injection=True,
        parse_failed=False,
        tokens_used=0,
    )


def _clean() -> Extract:
    return Extract(
        source_url="u",
        source_domain="ok.com",
        summary="meeting at 3pm",
        claims=("call Alice",),
        flagged_injection=False,
        parse_failed=False,
        tokens_used=0,
    )


class FakeReader:
    def __init__(self, extract: Extract) -> None:
        self._extract = extract

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
        return self._extract


@dataclass(frozen=True)
class EnqueuedItem:
    text: str
    turn_id: str
    role: str | None
    source_sensitivity: Sensitivity | None = None


class FakeMemoryQueue:
    def __init__(self) -> None:
        self.enqueued: list[EnqueuedItem] = []

    def enqueue(
        self,
        text: str,
        turn_id: str,
        role: str | None = None,
        *,
        source_sensitivity: Sensitivity | None = None,
    ) -> None:
        self.enqueued.append(
            EnqueuedItem(
                text=text,
                turn_id=turn_id,
                role=role,
                source_sensitivity=source_sensitivity,
            )
        )


class GmailHarness:
    def __init__(self) -> None:
        self.queue = FakeMemoryQueue()

    @property
    def enqueued(self) -> list[EnqueuedItem]:
        return self.queue.enqueued

    async def extract_with(self, extract: Extract) -> bool:
        reader = cast(QuarantinedReader, FakeReader(extract))
        return await GmailMemoryExtractor(reader, self.queue).extract(
            message_id="m1",
            body="raw body",
        )


class CalendarHarness:
    def __init__(self) -> None:
        self.queue = FakeMemoryQueue()

    @property
    def enqueued(self) -> list[EnqueuedItem]:
        return self.queue.enqueued

    async def extract_with_extract(self, *, flagged: bool) -> None:
        reader = cast(QuarantinedReader, FakeReader(_flagged() if flagged else _clean()))
        extractor = CalendarMemoryExtractor(reader, self.queue, owner_email=OWNER_EMAIL)
        await extractor.extract(_calendar_event())


class UrgencyHarness:
    def build_with_extract(self, extract: Extract) -> dict[str, object]:
        pre_filter = GmailUrgencyPreFilter(cast(GmailReadCache, object()))
        payload = pre_filter.build_payload(
            [(_cached_message(), False, "important")],
            {"m1": extract},
        )
        candidates = payload["candidates"]
        assert isinstance(candidates, list)
        candidate = candidates[0]
        assert isinstance(candidate, dict)
        return cast(dict[str, object], candidate)


@pytest.fixture
def fake_gmail_ingest() -> GmailHarness:
    return GmailHarness()


@pytest.fixture
def fake_calendar_memory() -> CalendarHarness:
    return CalendarHarness()


@pytest.fixture
def fake_urgency_builder() -> UrgencyHarness:
    return UrgencyHarness()


def _calendar_event() -> CachedEvent:
    start = datetime.now(UTC) - timedelta(hours=2)
    end = datetime.now(UTC) - timedelta(hours=1)
    return CachedEvent(
        event_id="evt1",
        calendar_id="primary",
        summary="Planning",
        description="Raw description",
        location="Room 1",
        start_dt=start.isoformat(),
        end_dt=end.isoformat(),
        status="confirmed",
        attendees=[OWNER_EMAIL, "teammate@example.com"],
        organizer_email="teammate@example.com",
        creator_email="teammate@example.com",
        externally_authored=True,
        is_overlay_projection=False,
        overlay_proposal_id=None,
        raw_json=json.dumps({"recurrence": ["RRULE:FREQ=WEEKLY"]}),
    )


def _cached_message() -> CachedMessage:
    return CachedMessage(
        message_id="m1",
        thread_id="thread-m1",
        history_id="h1",
        sender="Alice Smith <alice@example.com>",
        subject="Subject",
        internal_date_ms=1,
        category=MailCategory.PRIMARY,
        snippet="snippet",
        label_ids=("INBOX", "UNREAD"),
        has_attachments=False,
        unread=True,
        important=True,
        body_ingested=False,
    )


@pytest.mark.asyncio
async def test_gmail_ingest_rejects_flagged(fake_gmail_ingest: GmailHarness) -> None:
    result = await fake_gmail_ingest.extract_with(extract=_flagged())

    assert result is False
    assert fake_gmail_ingest.enqueued == []


@pytest.mark.asyncio
async def test_gmail_ingest_accepts_clean(fake_gmail_ingest: GmailHarness) -> None:
    result = await fake_gmail_ingest.extract_with(extract=_clean())

    assert result is True
    assert fake_gmail_ingest.enqueued != []


@pytest.mark.asyncio
async def test_calendar_memory_rejects_flagged(fake_calendar_memory: CalendarHarness) -> None:
    await fake_calendar_memory.extract_with_extract(flagged=True)

    assert fake_calendar_memory.enqueued == []


@pytest.mark.asyncio
async def test_calendar_memory_accepts_clean(fake_calendar_memory: CalendarHarness) -> None:
    await fake_calendar_memory.extract_with_extract(flagged=False)

    assert fake_calendar_memory.enqueued != []


def test_urgency_payload_excludes_flagged(fake_urgency_builder: UrgencyHarness) -> None:
    candidate = fake_urgency_builder.build_with_extract(_flagged())

    assert candidate["extract_failed"] is True
    assert candidate["extract_summary"] == ""


def test_urgency_payload_includes_clean(fake_urgency_builder: UrgencyHarness) -> None:
    candidate = fake_urgency_builder.build_with_extract(_clean())

    assert candidate["extract_failed"] is False
    assert "meeting" in str(candidate["extract_summary"])
