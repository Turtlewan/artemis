from __future__ import annotations

from dataclasses import dataclass

import pytest

from artemis.modules.gmail.ingest import GmailMemoryExtractor
from artemis.sensitivity import Sensitivity
from artemis.untrusted.quarantine import Extract

SUMMARY = "Owner renewed a private bank card."
CLAIM = "The card renewal was confirmed."
RAW_BODY = "Raw email text with an attacker instruction and unrelated wording."


class FakeSensitivityClassifier:
    def __init__(self, label: Sensitivity = "general", *, raises: bool = False) -> None:
        self._label = label
        self._raises = raises
        self.calls: list[str] = []

    async def classify(self, request_text: str) -> Sensitivity:
        self.calls.append(request_text)
        if self._raises:
            raise RuntimeError("classification unavailable")
        return self._label


class FakeQuarantinedReader:
    def __init__(self) -> None:
        self.raw_seen: list[str] = []

    async def read(
        self,
        *,
        raw_content: str,
        source_url: str,
        source_domain: str,
        query: str,
        max_tokens: int = 1024,
    ) -> Extract:
        del max_tokens
        self.raw_seen.append(raw_content)
        return Extract(
            source_url=source_url,
            source_domain=source_domain,
            summary=SUMMARY,
            claims=(CLAIM,),
            flagged_injection=False,
            parse_failed=False,
            tokens_used=7,
        )


@dataclass(frozen=True)
class EnqueuedItem:
    text: str
    turn_id: str
    role: str | None
    source_sensitivity: Sensitivity | None
    category: None = None


class SpyMemoryQueue:
    def __init__(self) -> None:
        self.items: list[EnqueuedItem] = []

    def enqueue(
        self,
        text: str,
        turn_id: str,
        role: str | None = None,
        *,
        source_sensitivity: Sensitivity | None = None,
    ) -> None:
        self.items.append(
            EnqueuedItem(
                text=text,
                turn_id=turn_id,
                role=role,
                source_sensitivity=source_sensitivity,
            )
        )


@pytest.mark.asyncio
async def test_gmail_memory_extractor_classifies_extract_once_and_fact_inherits() -> None:
    reader = FakeQuarantinedReader()
    queue = SpyMemoryQueue()
    classifier = FakeSensitivityClassifier("general")
    extractor = GmailMemoryExtractor(reader, queue, classifier)

    assert await extractor.extract(message_id="m1", body=RAW_BODY)

    assert reader.raw_seen == [RAW_BODY]
    assert classifier.calls == [SUMMARY]
    assert RAW_BODY not in classifier.calls
    assert len(queue.items) == 1
    item = queue.items[0]
    assert item.source_sensitivity == "general"
    assert item.category is None
    assert item.turn_id == "gmail:m1"
    assert item.role == "gmail"
    assert SUMMARY in item.text
    assert CLAIM in item.text
    assert RAW_BODY not in item.text


@pytest.mark.asyncio
@pytest.mark.parametrize("label", ["general", "sensitive"])
async def test_gmail_memory_extractor_passes_configured_label(label: Sensitivity) -> None:
    queue = SpyMemoryQueue()
    classifier = FakeSensitivityClassifier(label)
    extractor = GmailMemoryExtractor(FakeQuarantinedReader(), queue, classifier)

    assert await extractor.extract(message_id="m2", body=RAW_BODY)

    assert classifier.calls == [SUMMARY]
    assert queue.items[0].source_sensitivity == label
    assert queue.items[0].category is None


@pytest.mark.asyncio
async def test_gmail_memory_extractor_fails_closed_without_classifier() -> None:
    queue = SpyMemoryQueue()
    extractor = GmailMemoryExtractor(FakeQuarantinedReader(), queue)

    assert await extractor.extract(message_id="m3", body=RAW_BODY)

    assert queue.items[0].source_sensitivity == "sensitive"
    assert queue.items[0].category is None


@pytest.mark.asyncio
async def test_gmail_memory_extractor_fails_closed_when_classifier_raises() -> None:
    queue = SpyMemoryQueue()
    classifier = FakeSensitivityClassifier("general", raises=True)
    extractor = GmailMemoryExtractor(FakeQuarantinedReader(), queue, classifier)

    assert await extractor.extract(message_id="m4", body=RAW_BODY)

    assert classifier.calls == [SUMMARY]
    assert queue.items[0].source_sensitivity == "sensitive"
    assert queue.items[0].category is None
