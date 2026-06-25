from __future__ import annotations

from pathlib import Path

import pytest

from artemis.config import Settings
from artemis.identity.scope import OWNER_PRIVATE
from artemis.ingest.connectors import Source
from artemis.modules.finance.knowledge import FinanceFact, push_finance_knowledge


class FakeMemoryWriteQueue:
    def __init__(self) -> None:
        self.calls = 0

    def enqueue(self, *_args: object, **_kwargs: object) -> None:
        self.calls += 1


class FakeIngestPipeline:
    def __init__(self) -> None:
        self.records: list[tuple[Source, str]] = []

    async def ingest(self, source: Source) -> object:
        self.records.append((source, Path(source.uri).read_text(encoding="utf-8")))
        return object()


@pytest.mark.asyncio
async def test_push_finance_knowledge_does_not_write_general_memory(tmp_path: Path) -> None:
    memory_queue = FakeMemoryWriteQueue()
    ingest = FakeIngestPipeline()
    facts = [
        FinanceFact(
            text="Owner pays ~$16/monthly for StreamBox.",
            kind="subscription",
            key="subscription:StreamBox",
        ),
        FinanceFact(
            text="Owner's typical monthly Dining spend is around $40.",
            kind="spending_pattern",
            key="pattern:Dining",
        ),
    ]

    pushed = await push_finance_knowledge(
        facts,
        ingest=ingest,
        settings=Settings(data_root=tmp_path),
    )

    assert pushed == 2
    assert memory_queue.calls == 0
    assert [text for _source, text in ingest.records] == [fact.text for fact in facts]
    assert all(source.force_sensitive is False for source, _text in ingest.records)
    assert all(source.scope == OWNER_PRIVATE for source, _text in ingest.records)
