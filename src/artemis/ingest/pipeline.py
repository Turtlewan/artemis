"""Async ingestion pipeline from connector to vector store."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from artemis.identity.key_provider import ScopeLockedError
from artemis.ingest.chunking import ChunkRecord, chunk_document
from artemis.ingest.connectors import Connector, RawItem, Source, to_document
from artemis.ingest.parsing import DocumentParser, ParsedDocument
from artemis.ports.retrieval import EmbeddingModel, VectorStore
from artemis.ports.types import Document, Scope


class IngestError(Exception):
    """Raised when one source fails to ingest."""


@dataclass(frozen=True)
class Projection:
    """Reserved structured-projection row for future aggregate query paths."""

    document_id: str
    scope: Scope
    key: str
    value: str


@dataclass(frozen=True)
class IngestResult:
    """Result of ingesting one source."""

    document_id: str
    chunks_written: int
    skipped: bool
    parsed: ParsedDocument
    document: Document
    item: RawItem


class IngestPipeline:
    """Connector -> parser -> chunker -> embedder -> vector store."""

    def __init__(
        self,
        connector_for: Callable[[Source], Connector],
        parser: DocumentParser,
        embedder: EmbeddingModel,
        store_for: Callable[[Scope], VectorStore],
        is_unlocked: Callable[[], bool],
        projection_fn: Callable[[ParsedDocument, Document], Sequence[Projection]] | None = None,
    ) -> None:
        self._connector_for = connector_for
        self._parser = parser
        self._embedder = embedder
        self._store_for = store_for
        self._is_unlocked = is_unlocked
        self._projection_fn = projection_fn

    async def ingest(self, source: Source) -> IngestResult:
        """Ingest one source, idempotent by document content hash."""
        if not self._is_unlocked():
            raise ScopeLockedError(f"Scope is locked: {source.scope}")

        try:
            connector = self._connector_for(source)
            item = next(iter(connector.fetch(source)))
            parsed = self._parser.parse(item)
            document = to_document(item, source.scope, parsed.text)
        except Exception as exc:
            raise IngestError(f"Failed to fetch or parse source {source.uri!r}") from exc

        store = self._store_for(source.scope)
        if _has_document(store, document.document_id, document.content_hash):
            return IngestResult(
                document_id=document.document_id,
                chunks_written=0,
                skipped=True,
                parsed=parsed,
                document=document,
                item=item,
            )

        _delete_document(store, document.document_id)
        if self._projection_fn is not None:
            # Structured-projection hook reserved; v1 does not persist projections.
            _ = self._projection_fn(parsed, document)

        chunks = chunk_document(parsed, document)
        vectors = await self._embedder.embed_documents([chunk.text for chunk in chunks])
        if len(vectors) != len(chunks):
            raise IngestError(f"Embedder returned {len(vectors)} vectors for {len(chunks)} chunks")

        store.add(
            source.scope,
            ids=[chunk.chunk_id for chunk in chunks],
            vectors=vectors,
            metadata=[_metadata_for(chunk) for chunk in chunks],
        )
        return IngestResult(
            document_id=document.document_id,
            chunks_written=len(chunks),
            skipped=False,
            parsed=parsed,
            document=document,
            item=item,
        )


def _metadata_for(chunk: ChunkRecord) -> Mapping[str, object]:
    return {
        "text": chunk.text,
        "scope": chunk.scope,
        "content_hash": chunk.content_hash,
        "source_id": chunk.source_id,
        "document_id": chunk.document_id,
        "page": chunk.page,
        "bbox": chunk.bbox,
        "char_start": chunk.char_start,
        "char_end": chunk.char_end,
        "node_level": chunk.node_level,
        "is_summary": chunk.is_summary,
        "parent_chunk_id": chunk.parent_chunk_id,
    }


def _has_document(store: VectorStore, document_id: str, content_hash: str) -> bool:
    method = getattr(store, "has_document", None)
    if not callable(method):
        raise IngestError("VectorStore must provide has_document for ingestion")
    result = method(document_id, content_hash)
    if not isinstance(result, bool):
        raise IngestError("VectorStore.has_document must return bool")
    return result


def _delete_document(store: VectorStore, document_id: str) -> None:
    method = getattr(store, "delete_document", None)
    if not callable(method):
        raise IngestError("VectorStore must provide delete_document for ingestion")
    result = method(document_id)
    if result is not None:
        raise IngestError("VectorStore.delete_document must return None")
