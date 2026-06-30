from __future__ import annotations

from types import ModuleType, SimpleNamespace

import pytest

from artemis.memory import CogneeMemory, MemoryConfig
from artemis.memory.cognee_backend import _as_items, _assemble
from artemis.ports.memory import MemoryPort
from artemis.types import MemoryItem


class FakeCognee(ModuleType):
    def __init__(self, search_results: list[object] | None = None) -> None:
        super().__init__("fake_cognee")
        self.SearchType = SimpleNamespace(GRAPH_COMPLETION="graph_completion")
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


def test_assemble_applies_token_budget() -> None:
    items = [
        MemoryItem(content="a" * 40, layer="semantic"),
        MemoryItem(content="b" * 40, layer="semantic"),
        MemoryItem(content="c" * 40, layer="semantic"),
    ]

    limited = _assemble(items, token_budget=22)
    assert [item.content for item in limited.items] == ["a" * 40, "b" * 40]
    assert limited.token_cost == 20
    assert limited.truncated is True

    full = _assemble(items, token_budget=100)
    assert [item.content for item in full.items] == ["a" * 40, "b" * 40, "c" * 40]
    assert full.token_cost == 30
    assert full.truncated is False


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

    assert fake.search_calls == [("graph_completion", "q")]
    assert [item.content for item in result.items] == ["alpha", "beta"]
    assert result.truncated is False

    tiny = await mem.retrieve("q", token_budget=1)
    assert [item.content for item in tiny.items] == ["alpha"]
    assert tiny.token_cost == 1
    assert tiny.truncated is True


@pytest.mark.asyncio
async def test_forget_is_explicitly_deferred() -> None:
    mem = CogneeMemory(cognee_module=FakeCognee())

    with pytest.raises(NotImplementedError):
        await mem.forget()


def test_cognee_memory_satisfies_memory_port() -> None:
    mem: MemoryPort = CogneeMemory(cognee_module=FakeCognee())

    assert isinstance(mem, MemoryPort)
