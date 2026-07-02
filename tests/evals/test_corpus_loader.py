from __future__ import annotations

from collections import Counter
from pathlib import Path
import sys
from typing import get_args

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "evals"))

from webtool.loader import load_corpus, verify_integrity
from webtool.schema import Behavior, PageFixture, QueryRecord

CORPUS_PATH = Path("evals/webtool/corpus")
EXPECTED_QUERY_COUNTS = {
    "single_fact": 10,
    "multi_hop": 7,
    "comparative": 4,
    "aggregation": 4,
    "temporal": 5,
    "false_premise": 4,
    "negative": 7,
    "adversarial": 5,
    "conflicting": 4,
}


def _real_corpus() -> tuple[list[QueryRecord], dict[str, PageFixture]]:
    return load_corpus(CORPUS_PATH)


def test_real_corpus_integrity_passes() -> None:
    _queries, pages = _real_corpus()

    verify_integrity(pages)


def test_verify_integrity_raises_for_corrupted_in_memory_copy() -> None:
    _queries, pages = _real_corpus()
    fixture = next(iter(pages.values()))
    corrupted_pages = dict(pages)
    corrupted_pages[fixture.id] = fixture.model_copy(update={"text": f"{fixture.text}\ncorrupt"})

    with pytest.raises(ValueError, match="sha256 mismatch"):
        verify_integrity(corrupted_pages)


def test_real_corpus_file_counts_are_in_band() -> None:
    page_file_count = len(list((CORPUS_PATH / "pages").glob("*.json")))
    query_file_count = len(list((CORPUS_PATH / "queries").glob("*.json")))

    assert 90 <= page_file_count <= 110
    assert 40 <= query_file_count <= 60


def test_query_category_counts_match_taxonomy() -> None:
    queries, _pages = _real_corpus()

    assert Counter(query.category for query in queries) == EXPECTED_QUERY_COUNTS


def test_behavior_coverage_includes_every_behavior() -> None:
    queries, _pages = _real_corpus()
    expected_behaviors = {str(value) for value in get_args(Behavior)}

    assert {query.behavior for query in queries} == expected_behaviors


def test_adversarial_page_share_and_subkind_coverage() -> None:
    _queries, pages = _real_corpus()
    adversarial_pages = [page for page in pages.values() if page.injection_subkind is not None]
    adversarial_share = len(adversarial_pages) / len(pages)
    subkinds = [
        page.injection_subkind
        for page in adversarial_pages
        if page.injection_subkind is not None
    ]
    subkind_counts: Counter[str] = Counter(subkinds)

    assert 0.20 <= adversarial_share <= 0.25
    for subkind in ("A", "B", "C", "D", "E", "F", "G"):
        assert subkind_counts[subkind] >= 2
    assert subkind_counts["B"] >= 3
    assert subkind_counts["E"] >= 3
    assert subkind_counts["G"] >= 2


def test_benign_twins_point_to_existing_adversarial_fixtures() -> None:
    _queries, pages = _real_corpus()
    benign_twins = [page for page in pages.values() if page.benign_twin_of is not None]

    assert 4 <= len(benign_twins) <= 6
    for twin in benign_twins:
        assert twin.benign_twin_of is not None
        original = pages[twin.benign_twin_of]
        assert original.injection_subkind is not None


def test_query_page_refs_resolve_and_match_fixture_hashes() -> None:
    queries, pages = _real_corpus()

    for query in queries:
        for page_ref in query.pages:
            fixture = pages[page_ref.fixture_id]
            assert page_ref.sha256 == fixture.sha256
