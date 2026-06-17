"""Golden round-trip tests for the LanceDB VectorStore (deterministic vectors)."""

from __future__ import annotations

import math

import pytest

from artemis.knowledge import DimensionMismatchError, LanceDBVectorStore

_DIM = 8


def _unit(values: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in values)) or 1.0
    return [x / norm for x in values]


def _store(tmp_path, dim: int = _DIM) -> LanceDBVectorStore:
    return LanceDBVectorStore(tmp_path / "kb", dimension=dim)


def test_dense_round_trip(tmp_path) -> None:
    store = _store(tmp_path)
    texts = ["alpha doc", "beta doc", "gamma doc"]
    vecs = [
        _unit([1, 0, 0, 0, 0, 0, 0, 0]),
        _unit([0, 1, 0, 0, 0, 0, 0, 0]),
        _unit([0, 0, 1, 0, 0, 0, 0, 0]),
    ]
    store.add(
        "owner-private",
        ["c0", "c1", "c2"],
        vecs,
        [{"text": t, "document_id": "d1"} for t in texts],
    )
    results = store.search("owner-private", vecs[0], k=3)
    assert results[0].chunk.text == "alpha doc"  # identical vector ranks top
    assert results[0].score == pytest.approx(1.0, abs=1e-4)


def test_cosine_metric_contract(tmp_path) -> None:
    """Pin the distance->score contract: identical~1, orthogonal~0, opposite~-1."""
    store = _store(tmp_path)
    base = _unit([1, 0, 0, 0, 0, 0, 0, 0])
    opposite = [-x for x in base]
    orthogonal = _unit([0, 1, 0, 0, 0, 0, 0, 0])
    store.add(
        "owner-private",
        ["same", "opp", "orth"],
        [base, opposite, orthogonal],
        [{"text": "same"}, {"text": "opp"}, {"text": "orth"}],
    )
    by_id = {r.chunk.chunk_id: r.score for r in store.search("owner-private", base, k=3)}
    assert by_id["same"] == pytest.approx(1.0, abs=1e-3)
    assert by_id["orth"] == pytest.approx(0.0, abs=1e-3)
    assert by_id["opp"] == pytest.approx(-1.0, abs=1e-3)


def test_fts_round_trip(tmp_path) -> None:
    store = _store(tmp_path)
    store.add(
        "owner-private",
        ["c0", "c1"],
        [_unit([1, 0, 0, 0, 0, 0, 0, 0]), _unit([0, 1, 0, 0, 0, 0, 0, 0])],
        [{"text": "the quarterly revenue report"}, {"text": "a recipe for sourdough bread"}],
    )
    results = store.search_text("owner-private", "sourdough", k=5)
    if not store._fts_ok:  # native FTS unavailable on this host — acceptable
        pytest.skip("native FTS unavailable")
    assert [r.chunk.text for r in results] == ["a recipe for sourdough bread"]


def test_fts_incremental_add_is_searchable(tmp_path) -> None:
    """Rows added in a SECOND add() must be findable via FTS (index refreshed)."""
    store = _store(tmp_path)
    store.add(
        "owner-private",
        ["c0"],
        [_unit([1, 0, 0, 0, 0, 0, 0, 0])],
        [{"text": "first batch about turbines"}],
    )
    store.add(
        "owner-private",
        ["c1"],
        [_unit([0, 1, 0, 0, 0, 0, 0, 0])],
        [{"text": "second batch about dolphins"}],
    )
    if not store._fts_ok:
        pytest.skip("native FTS unavailable")
    results = store.search_text("owner-private", "dolphins", k=5)
    assert [r.chunk.chunk_id for r in results] == ["c1"]


def test_scope_isolation_dense_and_fts(tmp_path) -> None:
    store = _store(tmp_path)
    store.add(
        "owner-private",
        ["c0"],
        [_unit([1, 0, 0, 0, 0, 0, 0, 0])],
        [{"text": "private dolphins note"}],
    )
    store.add(
        "general",
        ["c1"],
        [_unit([1, 0, 0, 0, 0, 0, 0, 0])],
        [{"text": "general dolphins note"}],
    )
    dense = store.search("owner-private", _unit([1, 0, 0, 0, 0, 0, 0, 0]), k=10)
    assert {r.chunk.chunk_id for r in dense} == {"c0"}
    if store._fts_ok:
        fts = store.search_text("owner-private", "dolphins", k=10)
        assert {r.chunk.chunk_id for r in fts} == {"c0"}  # no cross-scope FTS leak


def test_dimension_lock_on_write(tmp_path) -> None:
    store = _store(tmp_path)
    with pytest.raises(DimensionMismatchError):
        store.add("owner-private", ["c0"], [[0.1, 0.2, 0.3]], [{"text": "wrong dim"}])


def test_dimension_lock_on_reopen(tmp_path) -> None:
    store = _store(tmp_path, dim=8)
    store.add(
        "owner-private", ["c0"], [_unit([1, 0, 0, 0, 0, 0, 0, 0])], [{"text": "x"}]
    )
    with pytest.raises(DimensionMismatchError):
        LanceDBVectorStore(tmp_path / "kb", dimension=4)  # same path, wrong dim


def test_invalid_scope_rejected(tmp_path) -> None:
    store = _store(tmp_path)
    with pytest.raises(ValueError):
        store.search("owner' OR '1'='1", _unit([1, 0, 0, 0, 0, 0, 0, 0]), k=5)


def test_empty_store_returns_nothing(tmp_path) -> None:
    store = _store(tmp_path)
    assert store.search("owner-private", _unit([1, 0, 0, 0, 0, 0, 0, 0]), k=5) == []
    assert store.search_text("owner-private", "anything", k=5) == []
