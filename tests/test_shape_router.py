"""Tests for query-shape retrieval routing."""

from __future__ import annotations

import pytest

from artemis.ports.types import Chunk, QueryShape, RetrievedChunk
from artemis.retrieval.shape_router import AGGREGATE_DECLINE_CHUNK_ID, ShapeRouter


def _rc(chunk_id: str, document_id: str = "docA", text: str = "t") -> RetrievedChunk:
    return RetrievedChunk(
        Chunk(chunk_id=chunk_id, document_id=document_id, text=text, scope="general"),
        1.0,
    )


def _router(
    shape: QueryShape,
    pinpoint_result: list[RetrievedChunk],
    summary_result: list[RetrievedChunk],
) -> ShapeRouter:
    async def pinpoint(_q: str) -> list[RetrievedChunk]:
        return list(pinpoint_result)

    async def summary(_doc: str) -> list[RetrievedChunk]:
        return list(summary_result)

    return ShapeRouter(classify=lambda _q: shape, pinpoint=pinpoint, summary_lookup=summary)


@pytest.mark.asyncio
async def test_pinpoint_passthrough() -> None:
    r = _router(QueryShape.PINPOINT, [_rc("c1")], [])
    out = await r.route("what did the memo say about X")
    assert [c.chunk.chunk_id for c in out] == ["c1"]


@pytest.mark.asyncio
async def test_whole_doc_reads_summary() -> None:
    r = _router(QueryShape.WHOLE_DOC, [_rc("pinpoint")], [_rc("summary", text="summary")])
    out = await r.route("summarize this")
    assert [c.chunk.chunk_id for c in out] == ["summary"]


@pytest.mark.asyncio
async def test_whole_doc_falls_back_when_no_summary() -> None:
    r = _router(QueryShape.WHOLE_DOC, [_rc("pinpoint")], [])
    out = await r.route("summarize this")
    assert [c.chunk.chunk_id for c in out] == ["pinpoint"]


@pytest.mark.asyncio
async def test_whole_doc_empty_pinpoint() -> None:
    r = _router(QueryShape.WHOLE_DOC, [], [_rc("summary")])
    out = await r.route("summarize this")
    assert out == []


@pytest.mark.asyncio
async def test_aggregate_returns_decline_with_domain_hint() -> None:
    r = _router(QueryShape.AGGREGATE, [_rc("pinpoint")], [_rc("summary")])
    out = await r.route("what was my total spend")
    assert len(out) == 1
    assert out[0].chunk.chunk_id == AGGREGATE_DECLINE_CHUNK_ID
    assert "can't reliably aggregate" in out[0].chunk.text
    assert "Finance" in out[0].chunk.text


@pytest.mark.asyncio
async def test_aggregate_decline_without_domain_hint() -> None:
    r = _router(QueryShape.AGGREGATE, [_rc("pinpoint")], [_rc("summary")])
    out = await r.route("how many notes mention blue")
    assert len(out) == 1
    assert out[0].chunk.chunk_id == AGGREGATE_DECLINE_CHUNK_ID
    assert "can't reliably aggregate" in out[0].chunk.text
    assert "prefer the" not in out[0].chunk.text
