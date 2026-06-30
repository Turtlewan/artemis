from __future__ import annotations

from collections.abc import Sequence
from types import ModuleType, SimpleNamespace
from typing import cast

import pytest

from artemis.memory import CogneeMemory, ConsolidationDecision, MemoryConfig, MemoryLedger
from artemis.memory.cognee_backend import _as_items, _extract_text, _normalize_fact
from artemis.memory.pipeline import assemble
from artemis.ports.memory import MemoryPort
from artemis.types import MemoryItem


class FakeCognee(ModuleType):
    def __init__(self, search_results: list[object] | None = None) -> None:
        super().__init__("fake_cognee")
        self.SearchType = SimpleNamespace(CHUNKS="chunks")
        self.add_calls: list[tuple[str, str]] = []
        self.cognify_calls = 0
        self.search_calls: list[tuple[object, str]] = []
        self._search_results = search_results or []

    async def add(self, content: str, *, dataset_name: str) -> None:
        self.add_calls.append((content, dataset_name))

    async def cognify(self) -> None:
        self.cognify_calls += 1

    async def search(self, *, query_type: object, query_text: str) -> list[object]:
        self.search_calls.append((query_type, query_text))
        return self._search_results


class FakeEmbedder:
    def __init__(self, embeddings: list[list[float]]) -> None:
        self.calls: list[list[str]] = []
        self._embeddings = embeddings

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return self._embeddings


class FakeConsolidator:
    def __init__(self, decision: ConsolidationDecision) -> None:
        self.calls: list[tuple[str, list[str]]] = []
        self._decision = decision

    async def classify(self, new: str, existing: Sequence[str]) -> ConsolidationDecision:
        self.calls.append((new, list(existing)))
        return self._decision


def _ledger_row(ledger: MemoryLedger, key: str) -> tuple[float, float, int, float, int]:
    rows = cast(
        list[tuple[float, float, int, float, int]],
        ledger._conn.execute(
            "SELECT first_seen, last_access, access_count, salience, archived "
            "FROM facts WHERE key=?",
            (key,),
        ).fetchall(),
    )
    assert len(rows) == 1
    return rows[0]


def test_assemble_applies_token_budget() -> None:
    items = [
        MemoryItem(content="a" * 40, layer="semantic"),
        MemoryItem(content="b" * 40, layer="semantic"),
        MemoryItem(content="c" * 40, layer="semantic"),
    ]

    limited = assemble(items, token_budget=22)
    assert [item.content for item in limited.items] == ["a" * 40, "b" * 40]
    assert limited.token_cost == 20
    assert limited.truncated is True

    full = assemble(items, token_budget=100)
    assert [item.content for item in full.items] == ["a" * 40, "b" * 40, "c" * 40]
    assert full.token_cost == 30
    assert full.truncated is False


def test_extract_text_pulls_text_field_from_cognee_node_dicts() -> None:
    # SearchType.CHUNKS returns node dicts whose chunk text is under "text" (Cognee 1.2.2).
    chunk = {
        "id": "abc",
        "created_at": 1,
        "text": "Caroline adopted a dog named Max.",
        "chunk_index": 0,
    }
    assert _extract_text(chunk) == "Caroline adopted a dog named Max."
    assert _extract_text("plain string") == "plain string"
    assert _extract_text({"content": "via content"}) == "via content"
    # no known text field → fall back to str(), never silently empty
    assert _extract_text({"id": "x"}) == "{'id': 'x'}"


def test_as_items_extracts_text_from_chunk_dicts() -> None:
    raw = [{"text": "fact one", "id": "1"}, {"text": "fact two", "id": "2"}]
    assert [item.content for item in _as_items(raw, None)] == ["fact one", "fact two"]


def test_as_items_coerces_raw_results_and_filters_layers() -> None:
    items = _as_items(["alpha", 7], None)
    assert [item.content for item in items] == ["alpha", "7"]
    assert [item.layer for item in items] == ["semantic", "semantic"]
    assert _as_items(["alpha"], ["rules"]) == []


@pytest.mark.asyncio
async def test_write_routes_by_layer_to_dataset() -> None:
    fake = FakeCognee()
    mem = CogneeMemory(cognee_module=fake)

    await mem.write(MemoryItem(content="x", layer="semantic"))
    assert fake.add_calls == [("x", "artemis")]

    configured = CogneeMemory(
        MemoryConfig(layer_datasets={"rules": "rules_ds"}),
        cognee_module=fake,
    )
    await configured.write(MemoryItem(content="rule", layer="rules"))
    assert fake.add_calls == [("x", "artemis"), ("rule", "rules_ds")]


@pytest.mark.asyncio
async def test_write_records_normalized_key_in_ledger() -> None:
    fake = FakeCognee()
    ledger = MemoryLedger()
    mem = CogneeMemory(
        MemoryConfig(default_salience=0.7),
        cognee_module=fake,
        ledger=ledger,
    )

    await mem.write(MemoryItem(content="  Ben works at Acme. ", layer="semantic"))

    _, _, access_count, salience, archived = _ledger_row(
        ledger, _normalize_fact("Ben works at Acme")
    )
    assert (access_count, salience, archived) == (0, 0.7, 0)


@pytest.mark.parametrize(
    ("decision", "expected_adds", "expected_superseded"),
    [
        (ConsolidationDecision(op="NOOP", target=None, reason="known"), [], set()),
        (
            ConsolidationDecision(op="ADD", target=None, reason="new"),
            [("new fact", "artemis")],
            set(),
        ),
        (
            ConsolidationDecision(op="UPDATE", target="old fact", reason="changed"),
            [("new fact", "artemis")],
            {"old fact"},
        ),
        (
            ConsolidationDecision(op="DELETE", target="old fact", reason="negated"),
            [],
            {"old fact"},
        ),
    ],
)
@pytest.mark.asyncio
async def test_write_applies_consolidation_ops(
    decision: ConsolidationDecision,
    expected_adds: list[tuple[str, str]],
    expected_superseded: set[str],
) -> None:
    fake = FakeCognee(["old fact"])
    consolidator = FakeConsolidator(decision)
    mem = CogneeMemory(
        MemoryConfig(consolidate_on_write=True, use_embedding_mmr=False),
        cognee_module=fake,
        consolidator=consolidator,
    )

    await mem.write(MemoryItem(content="new fact", layer="semantic"))

    assert fake.add_calls == expected_adds
    assert mem._superseded == expected_superseded
    assert consolidator.calls == [("new fact", ["old fact"])]


class _SearchRaisesCognee(FakeCognee):
    async def search(self, *, query_type: object, query_text: str) -> list[object]:
        raise RuntimeError("store not created yet")


@pytest.mark.asyncio
async def test_consolidating_write_survives_uninitialized_store() -> None:
    # First consolidating write happens before any add/cognify → Cognee search raises.
    # _similar must degrade to empty existing, and the write must still ADD.
    fake = _SearchRaisesCognee()
    consolidator = FakeConsolidator(ConsolidationDecision(op="ADD", target=None, reason="new"))
    mem = CogneeMemory(
        MemoryConfig(consolidate_on_write=True, use_embedding_mmr=False),
        cognee_module=fake,
        consolidator=consolidator,
    )

    await mem.write(MemoryItem(content="first fact", layer="semantic"))

    assert fake.add_calls == [("first fact", "artemis")]
    assert consolidator.calls == [("first fact", [])]  # classified against empty existing


@pytest.mark.asyncio
async def test_write_default_path_adds_without_consolidator_call() -> None:
    fake = FakeCognee(["old fact"])
    consolidator = FakeConsolidator(ConsolidationDecision(op="NOOP", reason="known"))
    mem = CogneeMemory(cognee_module=fake, consolidator=consolidator)

    await mem.write(MemoryItem(content="new fact", layer="semantic"))

    assert fake.add_calls == [("new fact", "artemis")]
    assert fake.search_calls == []
    assert consolidator.calls == []


@pytest.mark.asyncio
async def test_consolidate_awaits_cognify_once() -> None:
    fake = FakeCognee()
    mem = CogneeMemory(cognee_module=fake)

    await mem.consolidate()

    assert fake.cognify_calls == 1


@pytest.mark.asyncio
async def test_retrieve_searches_and_applies_budget() -> None:
    fake = FakeCognee(["alpha", "beta"])
    mem = CogneeMemory(cognee_module=fake)

    result = await mem.retrieve("q", token_budget=10000)

    assert fake.search_calls == [("chunks", "q")]
    assert [item.content for item in result.items] == ["alpha", "beta"]
    assert result.truncated is False

    tiny = await mem.retrieve("q", token_budget=1)
    assert [item.content for item in tiny.items] == ["alpha"]
    assert tiny.token_cost == 1
    assert tiny.truncated is True


@pytest.mark.asyncio
async def test_retrieve_filters_superseded_content() -> None:
    fake = FakeCognee(["old fact", "new fact"])
    mem = CogneeMemory(MemoryConfig(use_embedding_mmr=False), cognee_module=fake)
    mem._superseded = {"old fact"}

    result = await mem.retrieve("q", token_budget=10000)

    assert [item.content for item in result.items] == ["new fact"]


@pytest.mark.asyncio
async def test_retrieve_filters_archived_content_and_touches_returned_items() -> None:
    ledger = MemoryLedger()
    ledger.record("archived fact")
    ledger.record("live fact")
    ledger.archive(["archived fact"])
    fake = FakeCognee(["Archived Fact.", "Live Fact."])
    mem = CogneeMemory(MemoryConfig(use_embedding_mmr=False), cognee_module=fake, ledger=ledger)

    result = await mem.retrieve("q", token_budget=10000)

    assert [item.content for item in result.items] == ["Live Fact."]
    assert _ledger_row(ledger, "archived fact")[2] == 0
    assert _ledger_row(ledger, "live fact")[2] == 1


def test_normalize_fact_tolerates_case_and_trailing_punctuation() -> None:
    assert _normalize_fact("Ben works at Acme.") == _normalize_fact("ben works at acme")
    assert _normalize_fact("  Hi! ") == "hi"


@pytest.mark.asyncio
async def test_retrieve_supersession_matches_despite_punctuation_drift() -> None:
    # The LLM target ("Ben works at Acme") drops the period the stored chunk has
    # ("Ben works at Acme.") — normalized matching must still filter it (live-smoke finding).
    fake = FakeCognee(["Ben works at Acme.", "Ben now works at Globex."])
    mem = CogneeMemory(MemoryConfig(use_embedding_mmr=False), cognee_module=fake)
    mem._superseded = {_normalize_fact("Ben works at Acme")}

    result = await mem.retrieve("where does Ben work", token_budget=10000)

    assert [item.content for item in result.items] == ["Ben now works at Globex."]


@pytest.mark.asyncio
async def test_retrieve_wires_chunks_to_pipeline_and_collapses_duplicate() -> None:
    fake = FakeCognee(
        [
            "the cat sat on the mat",
            "the cat sat on the mat today",
            "stock prices fell sharply",
            "weather stayed clear",
            "project notes mention retrieval",
        ]
    )
    mem = CogneeMemory(
        MemoryConfig(retrieve_candidates=2),
        cognee_module=fake,
    )

    result = await mem.retrieve("q", token_budget=10000)

    assert fake.search_calls == [("chunks", "q")]
    assert [item.content for item in result.items] == [
        "the cat sat on the mat",
        "stock prices fell sharply",
    ]
    assert result.truncated is False


@pytest.mark.asyncio
async def test_retrieve_uses_embedding_mmr_when_embedder_is_injected() -> None:
    fake = FakeCognee(
        [
            "the cat sat on the mat",
            "the cat sat on the mat today",
            "stock prices fell sharply",
            "weather stayed clear",
        ]
    )
    embedder = FakeEmbedder(
        [
            [1.0, 0.0],
            [0.99, 0.01],
            [0.0, 1.0],
            [0.0, 0.8],
        ]
    )
    mem = CogneeMemory(
        MemoryConfig(retrieve_candidates=2),
        cognee_module=fake,
        embedder=embedder,
    )

    result = await mem.retrieve("q", token_budget=10000)

    assert embedder.calls == [
        [
            "the cat sat on the mat",
            "the cat sat on the mat today",
            "stock prices fell sharply",
            "weather stayed clear",
        ]
    ]
    assert [item.content for item in result.items] == [
        "the cat sat on the mat",
        "stock prices fell sharply",
    ]
    assert "the cat sat on the mat today" not in [item.content for item in result.items]


@pytest.mark.asyncio
async def test_forget_without_ledger_raises_clear_error() -> None:
    mem = CogneeMemory(cognee_module=FakeCognee())

    with pytest.raises(RuntimeError, match="forget\\(\\) requires a MemoryLedger"):
        await mem.forget()


@pytest.mark.asyncio
async def test_forget_archives_by_age_and_salience_with_ledger() -> None:
    ledger = MemoryLedger()
    ledger.record("old")
    ledger.record("low", salience=0.1)
    ledger.record("live", salience=1.0)
    ledger._conn.execute("UPDATE facts SET first_seen=? WHERE key=?", (-31.0 * 86400.0, "old"))
    ledger._conn.commit()
    mem = CogneeMemory(cognee_module=FakeCognee(), ledger=ledger)

    await mem.forget(max_age_days=30, min_salience=0.5)

    assert ledger.archived_keys() == {"old", "low"}


def test_cognee_memory_satisfies_memory_port() -> None:
    mem: MemoryPort = CogneeMemory(cognee_module=FakeCognee())

    assert isinstance(mem, MemoryPort)
