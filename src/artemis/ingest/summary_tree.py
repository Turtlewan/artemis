"""RAPTOR-style background summary-tree build over reserved ChunkRecord fields.

Ingest writes level-0 leaves only (chunking.chunk_document). This module is the
D4 background pass: it finds documents that have leaves but no current summary
nodes and writes higher-level summary ChunkRecords (is_summary=True, node_level>0,
parent_chunk_id set). Embedded + stored through the same VectorStore.add path as
leaves. Designed to run as a pre_tick_step via compose_proactive(pre_tick_steps=...).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Protocol, runtime_checkable

from artemis.ingest.chunking import ChunkRecord
from artemis.ports.model import ModelPort
from artemis.ports.retrieval import EmbeddingModel
from artemis.ports.types import Message, Scope, Vector
from artemis.sensitivity import Sensitivity

DEFAULT_GROUP_SIZE = 8
_LOG = logging.getLogger(__name__)


@runtime_checkable
class Summariser(Protocol):
    """Faithful-summary seam over a set of passages (network I/O -> async)."""

    async def summarise(self, texts: Sequence[str]) -> str: ...


class ModelSummariser:
    """Concrete Summariser wrapping the swappable ModelPort (fake in tests)."""

    def __init__(self, model: ModelPort, *, role: str = "summary", max_tokens: int = 512) -> None:
        self._model = model
        self._role = role
        self._max_tokens = max_tokens

    async def summarise(self, texts: Sequence[str]) -> str:
        body = "\n\n---\n\n".join(texts)
        prompt = (
            "Summarise the following passages faithfully and concisely. "
            "Preserve concrete facts; do not invent.\n\n" + body
        )
        resp = await self._model.complete(
            role=self._role,
            messages=[Message("user", prompt)],
            temperature=0.2,
            max_tokens=self._max_tokens,
        )
        return resp.text.strip()


@runtime_checkable
class LeafSummaryStore(Protocol):
    def rows(self) -> list[Mapping[str, object]]:
        """All stored rows for this scope (LanceDBVectorStore.rows shape)."""
        ...

    def add(
        self,
        scope: Scope,
        ids: Sequence[str],
        vectors: Sequence[Vector],
        metadata: Sequence[Mapping[str, object]],
    ) -> None: ...


async def build_summary_tree(
    *,
    store: LeafSummaryStore,
    scope: Scope,
    embedder: EmbeddingModel,
    summariser: Summariser,
    group_size: int = DEFAULT_GROUP_SIZE,
) -> int:
    """Build summary nodes for every document in this scope with leaves but no
    current summary. Returns the count of summary nodes written.

    Idempotent: a document whose leaves already have matching (same content_hash)
    summary rows is skipped; summary chunk_ids are content-independent so a rebuild
    upserts in place. Staleness across content changes is handled upstream by
    re-ingest (delete_document wipes leaves AND summaries, then this pass rebuilds).
    """
    rows = list(store.rows())
    by_doc: dict[str, list[Mapping[str, object]]] = {}
    for row in rows:
        by_doc.setdefault(str(row.get("document_id", "")), []).append(row)

    new_records: list[ChunkRecord] = []
    for document_id, doc_rows in by_doc.items():
        if not document_id:
            continue
        leaves = [r for r in doc_rows if not bool(r.get("is_summary", False))]
        if not leaves:
            continue
        content_hash = str(leaves[0].get("content_hash", ""))
        already = any(
            bool(r.get("is_summary", False)) and str(r.get("content_hash", "")) == content_hash
            for r in doc_rows
        )
        if already:
            continue
        leaves.sort(key=_leaf_ordinal)
        new_records.extend(await _summary_records_for(document_id, leaves, summariser, group_size))

    if not new_records:
        return 0

    vectors = await embedder.embed_documents([rec.text for rec in new_records])
    store.add(
        scope,
        ids=[rec.chunk_id for rec in new_records],
        vectors=vectors,
        metadata=[_summary_metadata(rec) for rec in new_records],
    )
    return len(new_records)


def _leaf_ordinal(row: Mapping[str, object]) -> int:
    cid = str(row.get("id", ""))
    tail = cid.rsplit(":", 1)[-1]
    return int(tail) if tail.isdigit() else 0


async def _summary_records_for(
    document_id: str,
    leaves: list[Mapping[str, object]],
    summariser: Summariser,
    group_size: int,
) -> list[ChunkRecord]:
    groups = [leaves[i : i + group_size] for i in range(0, len(leaves), group_size)]
    summaries: list[tuple[str, list[Mapping[str, object]], int]] = []
    for ordinal, group in enumerate(groups):
        text = await summariser.summarise([str(r.get("text", "")) for r in group])
        summaries.append((text, group, ordinal))

    if len(summaries) == 1:
        text, group, ordinal = summaries[0]
        return [
            _make_summary_record(
                document_id,
                level=1,
                ordinal=ordinal,
                text=text,
                leaf_rows=group,
                parent_chunk_id=None,
            )
        ]

    root_text = await summariser.summarise([text for text, _group, _ordinal in summaries])
    root = _make_summary_record(
        document_id,
        level=2,
        ordinal=0,
        text=root_text,
        leaf_rows=leaves,
        parent_chunk_id=None,
    )
    level1 = [
        _make_summary_record(
            document_id,
            level=1,
            ordinal=ordinal,
            text=text,
            leaf_rows=group,
            parent_chunk_id=root.chunk_id,
        )
        for text, group, ordinal in summaries
    ]
    return [root, *level1]


def _make_summary_record(
    document_id: str,
    *,
    level: int,
    ordinal: int,
    text: str,
    leaf_rows: Sequence[Mapping[str, object]],
    parent_chunk_id: str | None,
) -> ChunkRecord:
    first = leaf_rows[0]
    return ChunkRecord(
        chunk_id=f"{document_id}:summary:{level}:{ordinal}",
        document_id=document_id,
        text=text,
        scope=str(first.get("scope", "")),
        content_hash=str(first.get("content_hash", "")),
        source_id=str(first.get("source_id", "")),
        page=None,
        bbox=None,
        char_start=min(int(str(r.get("char_start", 0) or 0)) for r in leaf_rows),
        char_end=max(int(str(r.get("char_end", 0) or 0)) for r in leaf_rows),
        node_level=level,
        is_summary=True,
        parent_chunk_id=parent_chunk_id,
        sensitivity=_sensitivity(first.get("sensitivity")),
        category=_opt_str(first.get("category")),
    )


def _summary_metadata(rec: ChunkRecord) -> Mapping[str, object]:
    return {
        "text": rec.text,
        "scope": rec.scope,
        "content_hash": rec.content_hash,
        "source_id": rec.source_id,
        "document_id": rec.document_id,
        "page": rec.page,
        "bbox": rec.bbox,
        "char_start": rec.char_start,
        "char_end": rec.char_end,
        "node_level": rec.node_level,
        "is_summary": rec.is_summary,
        "parent_chunk_id": rec.parent_chunk_id,
        "sensitivity": rec.sensitivity,
        "category": rec.category,
    }


def _sensitivity(value: object) -> Sensitivity:
    return "general" if value == "general" else "sensitive"


def _opt_str(value: object) -> str | None:
    return None if value is None else str(value)


def make_summary_build_step(
    *,
    store_for: Callable[[Scope], LeafSummaryStore],
    scopes: Sequence[Scope],
    embedder: EmbeddingModel,
    summariser: Summariser,
    is_unlocked: Callable[[], bool],
    group_size: int = DEFAULT_GROUP_SIZE,
    logger: logging.Logger | None = None,
) -> Callable[[], Awaitable[None]]:
    """Build a no-arg async step for compose_proactive(pre_tick_steps=[...])."""
    log = logger or _LOG

    async def _step() -> None:
        if not is_unlocked():
            return
        for scope in scopes:
            try:
                await build_summary_tree(
                    store=store_for(scope),
                    scope=scope,
                    embedder=embedder,
                    summariser=summariser,
                    group_size=group_size,
                )
            except Exception:
                log.exception("summary-tree build failed for scope=%s", scope)

    return _step
