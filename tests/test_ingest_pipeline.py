"""Off-hardware ingestion pipeline tests."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import cast

import pytest

from artemis.adapters.lancedb_store import DimensionMismatchError, LanceDBVectorStore
from artemis.config import Settings
from artemis.data.scoped_store import CrossScopeError
from artemis.identity.key_provider import ScopeLockedError
from artemis.ingest.chunking import ChunkRecord, chunk_document
from artemis.ingest.connectors import FileConnector, Source, WebConnector
from artemis.ingest.parsing import FakeParser, ParsedBlock, ParsedDocument
from artemis.ingest.pipeline import IngestPipeline
from artemis.ports.types import Document, Scope, Vector
from artemis.sensitivity import Sensitivity


class FakeEmbedder:
    """Deterministic fixed-width embedder."""

    def __init__(self, dimension: int = 8) -> None:
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed_documents(self, texts: Sequence[str]) -> list[Vector]:
        return [self._vector(text) for text in texts]

    async def embed_query(self, query: str) -> Vector:
        return self._vector(query)

    def _vector(self, text: str) -> Vector:
        values = [0.0 for _ in range(self._dimension)]
        for index, byte in enumerate(text.encode("utf-8")):
            values[index % self._dimension] += float(byte)
        norm = sum(value * value for value in values) ** 0.5 or 1.0
        return [value / norm for value in values]


class FakeSensitivityClassifier:
    """Deterministic classifier for ingestion tests."""

    def __init__(self, label: Sensitivity = "sensitive", *, raises: bool = False) -> None:
        self._label = label
        self._raises = raises
        self.calls = 0

    async def classify(self, request_text: str) -> Sensitivity:
        _ = request_text
        self.calls += 1
        if self._raises:
            raise RuntimeError("classifier unavailable")
        return self._label


class FixtureWebConnector(WebConnector):
    def __init__(self, html: str) -> None:
        self._html = html

    def _fetch_url(self, url: str) -> str:
        _ = url
        return self._html


def _settings(tmp_path: Path) -> Settings:
    return Settings(data_root=tmp_path, slot="dev")


def _store(
    tmp_path: Path, scope: Scope = "owner-private", dimension: int = 8
) -> LanceDBVectorStore:
    return LanceDBVectorStore(
        scope,
        _settings(tmp_path),
        embedder_model_id="fake-embedder",
        dimension=dimension,
        is_unlocked=lambda: True,
    )


def _pipeline(
    tmp_path: Path,
    connector: FileConnector | WebConnector,
    store: LanceDBVectorStore,
    *,
    unlocked: bool = True,
    classifier: FakeSensitivityClassifier | None = None,
) -> IngestPipeline:
    embedder = FakeEmbedder(dimension=8)
    return IngestPipeline(
        connector_for=lambda _source: connector,
        parser=FakeParser(block_chars=32),
        embedder=embedder,
        store_for=lambda _scope: store,
        is_unlocked=lambda: unlocked,
        classifier=classifier,
    )


def _write_long_file(path: Path) -> None:
    path.parent.mkdir()
    path.write_text("alpha beta gamma delta " * 140, encoding="utf-8")


def _assert_rows_tagged(
    rows: Sequence[object],
    *,
    sensitivity: Sensitivity,
    category: object = None,
) -> None:
    for row in rows:
        row_mapping = cast(dict[str, object], row)
        assert row_mapping["sensitivity"] == sensitivity
        assert row_mapping["category"] is category


@pytest.mark.asyncio
async def test_file_ingest_writes_provenance_and_page_images(tmp_path: Path) -> None:
    path = tmp_path / "allowed" / "note.txt"
    path.parent.mkdir()
    path.write_text("alpha beta gamma delta epsilon zeta eta theta", encoding="utf-8")
    store = _store(tmp_path)
    pipeline = _pipeline(tmp_path, FileConnector([path.parent]), store)

    result = await pipeline.ingest(Source(kind="file", uri=str(path), scope="owner-private"))

    assert result.skipped is False
    assert result.chunks_written == store.row_count()
    assert result.parsed.page_images
    rows = store.rows()
    assert len(rows) == result.chunks_written
    for row in rows:
        assert row["content_hash"] == result.document.content_hash
        assert row["source_id"] == str(path.resolve())
        assert row["document_id"] == result.document_id
        assert row["page"] is not None
        assert int(cast(int | str, row["char_end"])) >= int(cast(int | str, row["char_start"]))
        assert row["node_level"] == 0
        assert row["is_summary"] is False
        assert row["parent_chunk_id"] is None
        assert row["sensitivity"] == "sensitive"
        assert row["category"] is None


@pytest.mark.asyncio
async def test_content_hash_idempotency_and_replace(tmp_path: Path) -> None:
    path = tmp_path / "allowed" / "note.txt"
    path.parent.mkdir()
    path.write_text("one two three four five six", encoding="utf-8")
    store = _store(tmp_path)
    pipeline = _pipeline(tmp_path, FileConnector([path.parent]), store)
    source = Source(kind="file", uri=str(path), scope="owner-private")

    first = await pipeline.ingest(source)
    first_count = store.row_count()
    second = await pipeline.ingest(source)
    assert second.skipped is True
    assert second.chunks_written == 0
    assert store.row_count() == first_count

    path.write_text("changed " * 40, encoding="utf-8")
    third = await pipeline.ingest(source)

    assert third.skipped is False
    assert third.document_id == first.document_id
    assert store.row_count() == third.chunks_written
    assert {str(row["content_hash"]) for row in store.rows()} == {third.document.content_hash}


def test_file_connector_rejects_path_traversal(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside.txt"
    allowed.mkdir()
    outside.write_text("secret", encoding="utf-8")
    connector = FileConnector([allowed])

    with pytest.raises(ValueError):
        list(connector.fetch(Source(kind="file", uri=str(outside), scope="owner-private")))


def test_dimension_lock_and_scope_wall(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.add(
        "owner-private",
        ["c1"],
        [[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]],
        [
            {
                "text": "alpha",
                "document_id": "doc",
                "content_hash": "hash",
                "source_id": "src",
                "char_start": 0,
                "char_end": 5,
            }
        ],
    )
    rows = store.rows()
    assert rows[0]["sensitivity"] == "sensitive"
    assert rows[0]["category"] is None

    with pytest.raises(DimensionMismatchError):
        _store(tmp_path, dimension=4)
    with pytest.raises(CrossScopeError):
        store.add("guest-x", ["c2"], [[1.0] * 8], [{"text": "x"}])


@pytest.mark.asyncio
async def test_locked_ingest_raises(tmp_path: Path) -> None:
    path = tmp_path / "allowed" / "note.txt"
    path.parent.mkdir()
    path.write_text("alpha", encoding="utf-8")
    store = _store(tmp_path)
    pipeline = _pipeline(tmp_path, FileConnector([path.parent]), store, unlocked=False)

    with pytest.raises(ScopeLockedError):
        await pipeline.ingest(Source(kind="file", uri=str(path), scope="owner-private"))


@pytest.mark.asyncio
async def test_web_ingest_fixture_has_url_source_and_no_page(tmp_path: Path) -> None:
    html = "<html><body><p>web alpha</p><p>web beta</p></body></html>"
    store = _store(tmp_path)
    connector = FixtureWebConnector(html)
    pipeline = _pipeline(tmp_path, connector, store)
    source = Source(kind="web", uri="https://example.test/page", scope="owner-private")

    result = await pipeline.ingest(source)

    assert result.skipped is False
    assert {row["source_id"] for row in store.rows()} == {"https://example.test/page"}
    assert {row["page"] for row in store.rows()} == {1}


def test_web_connector_rejects_non_http_scheme() -> None:
    connector = FixtureWebConnector("<p>x</p>")
    with pytest.raises(ValueError):
        list(connector.fetch(Source(kind="web", uri="file:///tmp/x.html", scope="owner-private")))


def test_vault_dir_rejects_non_owner_scope(tmp_path: Path) -> None:
    from artemis.paths import vault_dir

    with pytest.raises(ValueError):
        vault_dir(_settings(tmp_path), "guest-x")


def test_chunk_document_propagates_document_sensitivity() -> None:
    document = Document(
        document_id="doc",
        source_id="src",
        content_hash="hash",
        scope="owner-private",
        text="alpha beta",
        sensitivity="general",
    )
    parsed = ParsedDocument(
        text=document.text,
        blocks=(
            ParsedBlock(
                text=document.text,
                page=1,
                bbox=None,
                char_start=0,
                char_end=len(document.text),
            ),
        ),
        page_images=(),
    )

    chunks = chunk_document(parsed, document)

    assert {chunk.sensitivity for chunk in chunks} == {"general"}
    assert {chunk.category for chunk in chunks} == {None}
    assert (
        ChunkRecord(
            chunk_id="chunk",
            document_id="doc",
            text="text",
            scope="owner-private",
            content_hash="hash",
            source_id="src",
            page=None,
            bbox=None,
            char_start=0,
            char_end=4,
        ).sensitivity
        == "sensitive"
    )


@pytest.mark.asyncio
async def test_ingest_sensitivity_propagates_once_per_source(tmp_path: Path) -> None:
    path = tmp_path / "allowed" / "note.txt"
    _write_long_file(path)
    store = _store(tmp_path)
    classifier = FakeSensitivityClassifier("sensitive")
    pipeline = _pipeline(tmp_path, FileConnector([path.parent]), store, classifier=classifier)

    result = await pipeline.ingest(Source(kind="file", uri=str(path), scope="owner-private"))

    rows = store.rows()
    assert result.chunks_written > 1
    assert len(rows) == result.chunks_written
    assert result.document.sensitivity == "sensitive"
    assert result.document.category is None
    assert classifier.calls == 1
    _assert_rows_tagged(rows, sensitivity="sensitive")


@pytest.mark.asyncio
async def test_ingest_sensitivity_general_path(tmp_path: Path) -> None:
    path = tmp_path / "allowed" / "note.txt"
    _write_long_file(path)
    store = _store(tmp_path)
    classifier = FakeSensitivityClassifier("general")
    pipeline = _pipeline(tmp_path, FileConnector([path.parent]), store, classifier=classifier)

    result = await pipeline.ingest(Source(kind="file", uri=str(path), scope="owner-private"))

    assert result.document.sensitivity == "general"
    assert classifier.calls == 1
    _assert_rows_tagged(store.rows(), sensitivity="general")


@pytest.mark.asyncio
async def test_ingest_sensitivity_fail_closed_without_classifier(tmp_path: Path) -> None:
    path = tmp_path / "allowed" / "note.txt"
    _write_long_file(path)
    store = _store(tmp_path)
    pipeline = _pipeline(tmp_path, FileConnector([path.parent]), store, classifier=None)

    result = await pipeline.ingest(Source(kind="file", uri=str(path), scope="owner-private"))

    assert result.document.sensitivity == "sensitive"
    assert result.document.category is None
    _assert_rows_tagged(store.rows(), sensitivity="sensitive")


@pytest.mark.asyncio
async def test_ingest_sensitivity_fail_closed_when_classifier_raises(tmp_path: Path) -> None:
    path = tmp_path / "allowed" / "note.txt"
    _write_long_file(path)
    store = _store(tmp_path)
    classifier = FakeSensitivityClassifier("general", raises=True)
    pipeline = _pipeline(tmp_path, FileConnector([path.parent]), store, classifier=classifier)

    result = await pipeline.ingest(Source(kind="file", uri=str(path), scope="owner-private"))

    assert result.document.sensitivity == "sensitive"
    assert classifier.calls == 1
    _assert_rows_tagged(store.rows(), sensitivity="sensitive")


@pytest.mark.asyncio
async def test_idempotent_reingest_skips_sensitivity_classifier(tmp_path: Path) -> None:
    path = tmp_path / "allowed" / "note.txt"
    _write_long_file(path)
    store = _store(tmp_path)
    classifier = FakeSensitivityClassifier("general")
    pipeline = _pipeline(tmp_path, FileConnector([path.parent]), store, classifier=classifier)
    source = Source(kind="file", uri=str(path), scope="owner-private")

    first = await pipeline.ingest(source)
    second = await pipeline.ingest(source)

    assert first.skipped is False
    assert second.skipped is True
    assert second.chunks_written == 0
    assert classifier.calls == 1
