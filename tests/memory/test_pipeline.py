from __future__ import annotations

from collections.abc import Sequence

from artemis.memory.pipeline import assemble, lexical_similarity, mmr_select, run_pipeline
from artemis.types import MemoryItem


def _item(content: str) -> MemoryItem:
    return MemoryItem(content=content, layer="semantic")


def test_lexical_similarity_scores_identical_disjoint_and_partial() -> None:
    assert lexical_similarity("the cat sat", "the cat sat") == 1.0
    assert lexical_similarity("alpha beta", "gamma delta") == 0.0

    partial = lexical_similarity("alpha beta", "alpha gamma")
    assert 0.0 < partial < 1.0


def test_mmr_drops_near_duplicate_for_novel_item() -> None:
    items = [
        _item("the cat sat on the mat"),
        _item("the cat sat on the mat today"),
        _item("stock prices fell sharply"),
    ]

    selected = mmr_select(items, k=2)

    assert [item.content for item in selected] == [
        "the cat sat on the mat",
        "stock prices fell sharply",
    ]


def test_run_pipeline_honors_rerank_order() -> None:
    items = [_item("first item"), _item("second item"), _item("third item")]

    def reverse_reranker(query: str, items: Sequence[MemoryItem]) -> list[MemoryItem]:
        return list(reversed(items))

    identity = run_pipeline("q", items, token_budget=1000, k=1)
    reversed_result = run_pipeline(
        "q",
        items,
        token_budget=1000,
        k=1,
        reranker=reverse_reranker,
    )

    assert identity.items[0].content == "first item"
    assert reversed_result.items[0].content == "third item"


def test_assemble_applies_hard_token_budget() -> None:
    items = [
        _item("a" * 40),
        _item("b" * 40),
        _item("c" * 40),
    ]

    limited = assemble(items, token_budget=22)
    assert [item.content for item in limited.items] == ["a" * 40, "b" * 40]
    assert limited.token_cost == 20
    assert limited.truncated is True

    full = assemble(items, token_budget=100)
    assert [item.content for item in full.items] == ["a" * 40, "b" * 40, "c" * 40]
    assert full.token_cost == 30
    assert full.truncated is False
