from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

import pytest

from artemis.ingest.connectors import Connector, RawItem, Source
from artemis.ingest.parsing import FakeParser
from artemis.ingest.pipeline import IngestPipeline
from artemis.ports.types import Document, RetrievedChunk, Scope, Vector
from artemis.runtime_config import RuntimeConfig, load_runtime_config
from artemis.sensitivity import Sensitivity
from artemis.sensitivity_review import (
    SensitivityReviewItem,
    SensitivityReviewQueue,
    graduate_to_policy,
)


class FakeConnector:
    def __init__(self, text: str) -> None:
        self._text = text

    def fetch(self, source: Source) -> Iterable[RawItem]:
        yield RawItem(
            raw_bytes=None,
            text=self._text,
            mime="text/plain",
            source_id=source.uri,
            origin_uri=source.uri,
            fetched_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
            page_images=(),
        )


class FakeEmbedder:
    @property
    def dimension(self) -> int:
        return 2

    async def embed_documents(self, texts: Sequence[str]) -> list[Vector]:
        return [[1.0, 0.0] for _text in texts]

    async def embed_query(self, query: str) -> Vector:
        return [1.0, 0.0]


class FakeStore:
    def __init__(self) -> None:
        self.rows: list[dict[str, object]] = []

    def has_document(self, document_id: str, content_hash: str) -> bool:
        del document_id, content_hash
        return False

    def delete_document(self, document_id: str) -> None:
        del document_id

    def add(
        self,
        scope: Scope,
        ids: Sequence[str],
        vectors: Sequence[Vector],
        metadata: Sequence[Mapping[str, object]],
    ) -> None:
        del scope, ids, vectors
        self.rows.extend(dict(row) for row in metadata)

    def search(self, scope: Scope, query: Vector, k: int) -> list[RetrievedChunk]:
        del scope, query, k
        return []


class FakeSensitivityClassifier:
    def __init__(self, label: Sensitivity) -> None:
        self._label = label
        self.calls = 0

    async def classify(self, request_text: str) -> Sensitivity:
        del request_text
        self.calls += 1
        return self._label


def test_source_force_sensitive_default_and_override() -> None:
    assert Source(kind="file", uri="x", scope="owner-private").force_sensitive is False
    assert Source(kind="file", uri="x", scope="owner-private", force_sensitive=True).force_sensitive


@pytest.mark.asyncio
async def test_force_sensitive_skips_classifier() -> None:
    classifier = FakeSensitivityClassifier("general")
    result = await _pipeline("clean text", classifier=classifier).ingest(
        Source(kind="file", uri="source", scope="owner-private", force_sensitive=True)
    )

    assert result.document.sensitivity == "sensitive"
    assert classifier.calls == 0


@pytest.mark.asyncio
async def test_content_detector_precedes_classifier() -> None:
    classifier = FakeSensitivityClassifier("general")
    result = await _pipeline("card 4111 1111 1111 1111", classifier=classifier).ingest(
        Source(kind="file", uri="source", scope="owner-private")
    )

    assert result.document.sensitivity == "sensitive"
    assert classifier.calls == 0


@pytest.mark.asyncio
async def test_clean_text_uses_classifier_general_label() -> None:
    classifier = FakeSensitivityClassifier("general")
    result = await _pipeline("clean text", classifier=classifier).ingest(
        Source(kind="file", uri="source", scope="owner-private")
    )

    assert result.document.sensitivity == "general"
    assert classifier.calls == 1


@pytest.mark.asyncio
async def test_classify_source_without_classifier_fails_closed() -> None:
    pipeline = _pipeline("clean text", classifier=None)
    label = await pipeline._classify_source(
        Document(
            document_id="doc",
            source_id="src",
            content_hash="hash",
            scope="owner-private",
            text="clean text",
        )
    )

    assert label == "sensitive"


def test_runtime_config_sensitivity_defaults_and_owner_overrides(tmp_path: Path) -> None:
    assert RuntimeConfig().sensitivity.hard_sensitive_domains == ("journal", "health", "email")
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(
        '{"sensitivity": {"classifier_fail_closed": true, "owner_overrides": {"r1": "general"}}}',
        encoding="utf-8",
    )

    config = load_runtime_config(policy_path)

    assert config.sensitivity.classifier_fail_closed is True
    assert config.sensitivity.owner_overrides == {"r1": "general"}


def test_sensitivity_review_queue_round_trips_and_graduates(tmp_path: Path) -> None:
    queue = SensitivityReviewQueue(tmp_path / "sensitivity-review-queue.json")
    item = SensitivityReviewItem(
        source_id="source",
        text_preview="preview",
        proposed_sensitivity="sensitive",
        review_id="review-1",
    )

    queue.enqueue(item)
    pending = queue.pending()

    assert pending == [item]
    policy_path = tmp_path / "policy.json"
    graduate_to_policy("review-1", "general", policy_path)
    config = load_runtime_config(policy_path)
    assert config.sensitivity.owner_overrides == {"review-1": "general"}


def test_sensitivity_review_item_truncates_preview() -> None:
    # Privacy invariant: text_preview is hard-capped at 200 chars in the dataclass,
    # never left to call-site discipline (cross-model review hardening 2026-06-25).
    item = SensitivityReviewItem(source_id="s", text_preview="x" * 500)
    assert len(item.text_preview) == 200


def _pipeline(
    text: str,
    *,
    classifier: FakeSensitivityClassifier | None,
) -> IngestPipeline:
    store = FakeStore()
    return IngestPipeline(
        connector_for=lambda _source: _connector(text),
        parser=FakeParser(block_chars=100),
        embedder=FakeEmbedder(),
        store_for=lambda _scope: store,
        is_unlocked=lambda: True,
        classifier=classifier,
    )


def _connector(text: str) -> Connector:
    return FakeConnector(text)
