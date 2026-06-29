from __future__ import annotations

from collections.abc import Mapping, Sequence

from artemis.ingest.summary_tree import build_summary_tree, make_summary_build_step
from artemis.ports.types import Scope, Vector


class FakeSummariser:
    def __init__(self) -> None:
        self.calls = 0

    async def summarise(self, texts: Sequence[str]) -> str:
        self.calls += 1
        return f"SUM[{len(texts)}]:" + " | ".join(t[:8] for t in texts)


class FakeEmbedder:
    async def embed_documents(self, texts: Sequence[str]) -> list[Vector]:
        return [[float(len(t)), 0.0, 1.0] for t in texts]

    async def embed_query(self, query: str) -> Vector:
        return [float(len(query)), 0.0, 1.0]

    @property
    def dimension(self) -> int:
        return 3


class InMemoryLeafStore:
    def __init__(self) -> None:
        self._rows: dict[str, dict[str, object]] = {}

    def rows(self) -> list[Mapping[str, object]]:
        return list(self._rows.values())

    def add(
        self,
        scope: Scope,
        ids: Sequence[str],
        vectors: Sequence[Vector],
        metadata: Sequence[Mapping[str, object]],
    ) -> None:
        for chunk_id, row in zip(ids, metadata, strict=True):
            self._rows.pop(chunk_id, None)
            self._rows[chunk_id] = {**row, "id": chunk_id, "scope": scope}

    def seed_leaves(self, count: int, *, document_id: str = "doc1") -> None:
        for ordinal in range(count):
            chunk_id = f"{document_id}:{ordinal}"
            self._rows[chunk_id] = {
                "id": chunk_id,
                "text": f"leaf text {ordinal}",
                "document_id": document_id,
                "content_hash": "hash1",
                "scope": "owner-private",
                "is_summary": False,
                "node_level": 0,
                "char_start": ordinal * 10,
                "char_end": ordinal * 10 + 9,
                "source_id": "source1",
                "sensitivity": "sensitive",
                "category": "note",
            }


async def test_builds_two_level_tree() -> None:
    store = InMemoryLeafStore()
    store.seed_leaves(6)
    summariser = FakeSummariser()

    written = await build_summary_tree(
        store=store,
        scope="owner-private",
        embedder=FakeEmbedder(),
        summariser=summariser,
        group_size=3,
    )

    assert written == 3
    summary_rows = [r for r in store.rows() if r.get("is_summary") is True]
    assert {r["id"] for r in summary_rows} == {
        "doc1:summary:1:0",
        "doc1:summary:1:1",
        "doc1:summary:2:0",
    }
    level1 = sorted(
        (r for r in summary_rows if r["node_level"] == 1),
        key=lambda r: str(r["id"]),
    )
    assert [r["parent_chunk_id"] for r in level1] == [
        "doc1:summary:2:0",
        "doc1:summary:2:0",
    ]
    root = next(r for r in summary_rows if r["id"] == "doc1:summary:2:0")
    assert root["node_level"] == 2
    assert root["parent_chunk_id"] is None
    assert summariser.calls == 3


async def test_single_group_single_root() -> None:
    store = InMemoryLeafStore()
    store.seed_leaves(2)

    written = await build_summary_tree(
        store=store,
        scope="owner-private",
        embedder=FakeEmbedder(),
        summariser=FakeSummariser(),
        group_size=5,
    )

    assert written == 1
    summary_rows = [r for r in store.rows() if r.get("is_summary") is True]
    assert len(summary_rows) == 1
    assert summary_rows[0]["id"] == "doc1:summary:1:0"
    assert summary_rows[0]["node_level"] == 1
    assert summary_rows[0]["parent_chunk_id"] is None


async def test_idempotent_rerun() -> None:
    store = InMemoryLeafStore()
    store.seed_leaves(6)
    summariser = FakeSummariser()

    first = await build_summary_tree(
        store=store,
        scope="owner-private",
        embedder=FakeEmbedder(),
        summariser=summariser,
        group_size=3,
    )
    first_ids = {r["id"] for r in store.rows() if r.get("is_summary") is True}

    second = await build_summary_tree(
        store=store,
        scope="owner-private",
        embedder=FakeEmbedder(),
        summariser=summariser,
        group_size=3,
    )
    second_ids = {r["id"] for r in store.rows() if r.get("is_summary") is True}

    assert first == 3
    assert second == 0
    assert second_ids == first_ids
    assert len(second_ids) == 3


async def test_step_skips_when_locked() -> None:
    store = InMemoryLeafStore()
    store.seed_leaves(2)
    before = len(store.rows())
    step = make_summary_build_step(
        store_for=lambda _scope: store,
        scopes=["owner-private"],
        embedder=FakeEmbedder(),
        summariser=FakeSummariser(),
        is_unlocked=lambda: False,
    )

    await step()

    assert len(store.rows()) == before
    assert not [r for r in store.rows() if r.get("is_summary") is True]
