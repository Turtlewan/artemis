"""Late chunk span generation for ingestion."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from artemis.ingest.parsing import ParsedBlock, ParsedDocument
from artemis.ports.types import Document, Scope
from artemis.sensitivity import Sensitivity

DEFAULT_CHUNK_CHARS = 2048


@dataclass(frozen=True)
class ChunkRecord:
    """A vector-store chunk with provenance and reserved summary-tree fields."""

    chunk_id: str
    document_id: str
    text: str
    scope: Scope
    content_hash: str
    source_id: str
    page: int | None
    bbox: tuple[float, float, float, float] | None
    char_start: int
    char_end: int
    node_level: int = 0
    is_summary: bool = False
    parent_chunk_id: str | None = None
    sensitivity: Sensitivity = "sensitive"
    category: str | None = None
    source_date: datetime | None = None


def chunk_document(
    parsed: ParsedDocument,
    document: Document,
    *,
    contextual: bool = False,
    context_fn: Callable[[str, str], str] | None = None,
    target_chars: int = DEFAULT_CHUNK_CHARS,
    source_date: datetime | None = None,
) -> list[ChunkRecord]:
    """Group parsed blocks into stable chunks.

    The locator uses the first block's page/bbox and the combined char span.
    Summary-tree fields are reserved; v1 writes level-0 leaves only. True
    long-context late-chunk pooling belongs in the embedder adapter.
    """
    chunks: list[ChunkRecord] = []
    current: list[ParsedBlock] = []
    current_len = 0

    for block in parsed.blocks:
        block_len = len(block.text)
        if current and current_len + block_len > target_chars:
            chunks.append(
                _make_chunk(document, len(chunks), current, contextual, context_fn, source_date)
            )
            current = []
            current_len = 0
        current.append(block)
        current_len += block_len

    if current:
        chunks.append(
            _make_chunk(document, len(chunks), current, contextual, context_fn, source_date)
        )
    return chunks


def _make_chunk(
    document: Document,
    ordinal: int,
    blocks: list[ParsedBlock],
    contextual: bool,
    context_fn: Callable[[str, str], str] | None,
    source_date: datetime | None = None,
) -> ChunkRecord:
    first = blocks[0]
    text = "\n\n".join(block.text for block in blocks if block.text)
    if contextual and context_fn is not None:
        text = f"{context_fn(document.text, text)}\n\n{text}"
    return ChunkRecord(
        chunk_id=f"{document.document_id}:{ordinal}",
        document_id=document.document_id,
        text=text,
        scope=document.scope,
        content_hash=document.content_hash,
        source_id=document.source_id,
        page=first.page,
        bbox=first.bbox,
        char_start=min(block.char_start for block in blocks),
        char_end=max(block.char_end for block in blocks),
        sensitivity=document.sensitivity,
        category=document.category,
        source_date=source_date,
    )
