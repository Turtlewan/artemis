from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from artemis.config import Settings
from artemis.identity.key_provider import ScopeLockedError, SecretKey
from artemis.identity.scope import OWNER_PRIVATE
from artemis.ingest.connectors import Source
from artemis.modules.finance.knowledge import (
    FinanceFact,
    derive_finance_facts,
    push_finance_knowledge,
)
from artemis.modules.finance.manifest import finance_manifest
from artemis.modules.finance.store import FinanceStore
from artemis.modules.finance.tools import EmptyArgs, finance_knowledge_push
from artemis.ports.types import Scope
from artemis.sensitivity import Sensitivity


class FakeKeyProvider:
    def dek_for_scope(self, scope: Scope) -> SecretKey:
        if scope != OWNER_PRIVATE:
            raise ScopeLockedError(f"Scope is locked: {scope}")
        return SecretKey(b"k" * 32)

    def is_owner_unlocked(self) -> bool:
        return True


class FakeMemoryWriteQueue:
    def __init__(self, *, fail_first: bool = False) -> None:
        self.fail_first = fail_first
        self.calls = 0
        self.records: list[tuple[str, str, Sensitivity | None]] = []

    def enqueue(
        self,
        text: str,
        turn_id: str,
        role: str | None = None,
        *,
        source_sensitivity: Sensitivity | None = None,
    ) -> None:
        del role
        self.calls += 1
        if self.fail_first and self.calls == 1:
            raise RuntimeError("forced enqueue failure")
        self.records.append((text, turn_id, source_sensitivity))


class FakeIngestPipeline:
    def __init__(self) -> None:
        self.records: list[tuple[Source, str]] = []

    async def ingest(self, source: Source) -> object:
        self.records.append((source, Path(source.uri).read_text(encoding="utf-8")))
        return object()


def test_derive_finance_facts_uses_summary_facts_only(tmp_path: Path) -> None:
    store = _seed_store(tmp_path)

    facts = derive_finance_facts(store)

    assert any(fact.kind == "subscription" and "StreamBox" in fact.text for fact in facts)
    assert any(
        fact.kind == "spending_pattern" and "Dining" in fact.text and "$40" in fact.text
        for fact in facts
    )
    combined = "\n".join(fact.text for fact in facts)
    assert "txn-raw-one-off" not in combined
    assert "receipt-123" not in combined
    assert "9.99" not in combined
    assert "40.22" not in combined


@pytest.mark.asyncio
async def test_push_finance_knowledge_tags_memory_sensitive_and_ingests(
    tmp_path: Path,
) -> None:
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
    settings = Settings(data_root=tmp_path)
    memory_queue = FakeMemoryWriteQueue()
    ingest = FakeIngestPipeline()

    pushed = await push_finance_knowledge(
        facts,
        ingest=ingest,
        memory_queue=memory_queue,
        settings=settings,
    )

    assert pushed == 2
    assert [record[0] for record in memory_queue.records] == [fact.text for fact in facts]
    assert all(record[2] == "sensitive" for record in memory_queue.records)
    assert all(record[2] != "general" for record in memory_queue.records)
    assert [record[1] for record in ingest.records] == [fact.text for fact in facts]
    assert all(source.kind == "file" for source, _text in ingest.records)
    assert all(source.scope == OWNER_PRIVATE for source, _text in ingest.records)
    staging_dir = tmp_path / "dev" / OWNER_PRIVATE / "ingest-staging"
    assert staging_dir.exists()
    assert list(staging_dir.glob("*.txt")) == []


@pytest.mark.asyncio
async def test_memory_excludes_raw_financial_records(tmp_path: Path) -> None:
    store = _seed_store(tmp_path)
    facts = derive_finance_facts(store)
    memory_queue = FakeMemoryWriteQueue()
    ingest = FakeIngestPipeline()

    pushed = await push_finance_knowledge(
        facts,
        ingest=ingest,
        memory_queue=memory_queue,
        settings=Settings(data_root=tmp_path),
    )

    assert pushed == len(facts)
    assert set(text for text, _turn_id, _sensitivity in memory_queue.records) == {
        fact.text for fact in facts
    }
    for text, _turn_id, _sensitivity in memory_queue.records:
        assert "raw_ref" not in text
        assert "txn-raw-one-off" not in text
        assert "receipt-123" not in text
        assert "Cafe Once" not in text


@pytest.mark.asyncio
async def test_push_degrades_per_fact_without_propagating(tmp_path: Path) -> None:
    facts = [
        FinanceFact(text="Owner pays ~$16/monthly for StreamBox.", kind="subscription", key="a"),
        FinanceFact(
            text="Owner regularly spends at TrainCard.", kind="recurring_merchant", key="b"
        ),
    ]
    memory_queue = FakeMemoryWriteQueue(fail_first=True)
    ingest = FakeIngestPipeline()

    pushed = await push_finance_knowledge(
        facts,
        ingest=ingest,
        memory_queue=memory_queue,
        settings=Settings(data_root=tmp_path),
    )

    assert pushed == 1
    assert memory_queue.records == [(facts[1].text, "finance:b", "sensitive")]
    assert [text for _source, text in ingest.records] == [facts[1].text]


def test_finance_knowledge_tool_and_manifest_wiring(tmp_path: Path) -> None:
    store = _seed_store(tmp_path)
    ingest = FakeIngestPipeline()
    memory_queue = FakeMemoryWriteQueue()

    manifest = finance_manifest(
        store,
        ingest_pipeline=ingest,  # type: ignore[arg-type]
        memory_queue=memory_queue,  # type: ignore[arg-type]
        settings=Settings(data_root=tmp_path),
    )

    spec = next(tool for tool in manifest.tools if tool.name == "finance_knowledge_push")
    assert spec.action_risk.value == "write"
    assert inspect.iscoroutinefunction(spec.callable_ref)


@pytest.mark.asyncio
async def test_finance_knowledge_push_requires_handles() -> None:
    from artemis.modules.finance import tools

    previous_ingest = tools._ingest
    previous_memory_queue = tools._memory_queue
    previous_settings = tools._settings
    tools._ingest = None
    tools._memory_queue = None
    tools._settings = None
    try:
        with pytest.raises(RuntimeError):
            await finance_knowledge_push(EmptyArgs())
    finally:
        tools._ingest = previous_ingest
        tools._memory_queue = previous_memory_queue
        tools._settings = previous_settings


def test_finance_package_imports_no_remote_reasoning_ports() -> None:
    finance_dir = Path(__file__).parents[1] / "src" / "artemis" / "modules" / "finance"
    combined = "\n".join(path.read_text(encoding="utf-8") for path in finance_dir.glob("*.py"))
    assert "model_adapters" not in combined
    assert "Codex" not in combined
    assert "responder_cloud" not in combined
    assert "cloud" not in combined


def _seed_store(tmp_path: Path) -> FinanceStore:
    store = FinanceStore(Settings(data_root=tmp_path), FakeKeyProvider())
    account_id = store.create_account("Card", "card")
    dining_id = store.add_category("Dining")
    one_off_id = store.add_category("OneOff")
    store.upsert_subscription(
        merchant="StreamBox",
        cadence="monthly",
        amount=Decimal("15.99"),
    )

    base_date = datetime.now(UTC).date() - timedelta(days=10)
    for offset, amount in enumerate((Decimal("30.11"), Decimal("40.22"), Decimal("50.33"))):
        store.add_transaction(
            txn_date=(base_date + timedelta(days=offset)).isoformat(),
            amount=amount,
            merchant="Dining Hall",
            category_id=dining_id,
            source="manual",
            instrument_account_id=account_id,
        )
    store.add_transaction(
        txn_date=(base_date + timedelta(days=5)).isoformat(),
        amount=Decimal("9.99"),
        merchant="Cafe Once",
        category_id=one_off_id,
        source="manual",
        instrument_account_id=account_id,
        raw_ref="txn-raw-one-off",
        notes="receipt-123",
    )
    return store
