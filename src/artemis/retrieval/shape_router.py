"""Query-shape routing in front of retrieval.

Design: docs/findings/query-shape-retrieval-design-2026-06-29.md
PINPOINT -> existing hybrid retrieve (unchanged).
WHOLE_DOC -> retrieve-then-read: top document_id from a normal retrieve, then that
doc's summary node(s); fall back to pinpoint when no summary node exists yet.
AGGREGATE -> honest-decline sentinel chunk (+ a domain-tool routing hint).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Final

from artemis.identity.scope import GENERAL
from artemis.ports.types import Chunk, QueryShape, RetrievedChunk, Scope

ShapeClassifier = Callable[[str], QueryShape]
PinpointRetrieve = Callable[[str], Awaitable[list[RetrievedChunk]]]
SummaryLookup = Callable[[str], Awaitable[list[RetrievedChunk]]]

AGGREGATE_DECLINE_CHUNK_ID: Final = "__artemis_aggregate_decline__"

# Minimal keyword -> domain routing hint (a hint, not a tool-selection engine).
_DOMAIN_HINTS: Final[tuple[tuple[tuple[str, ...], str], ...]] = (
    (("spend", "spent", "budget", "expense", "cost", "income", "ledger"), "Finance"),
    (("meeting", "calendar", "schedule", "appointment", "event"), "Calendar"),
    (("task", "todo", "to-do", "deadline", "due"), "Tasks"),
)


def _domain_hint(query: str) -> str | None:
    low = query.lower()
    for keywords, domain in _DOMAIN_HINTS:
        if any(k in low for k in keywords):
            return domain
    return None


def build_decline_chunk(query: str, scope: Scope = GENERAL) -> RetrievedChunk:
    """Sentinel RetrievedChunk the brain renders as an honest aggregate decline."""
    notice = (
        "I can't reliably aggregate or total free-text documents -- "
        "sums, averages, and counts over notes are not trustworthy."
    )
    hint = _domain_hint(query)
    if hint is not None:
        notice += f" This looks like a {hint} question -- prefer the {hint} query tool."
    chunk = Chunk(
        chunk_id=AGGREGATE_DECLINE_CHUNK_ID,
        document_id="",
        text=notice,
        scope=scope,
    )
    return RetrievedChunk(chunk, score=1.0)


class ShapeRouter:
    """Classify a query's shape and dispatch to the matching retrieval strategy."""

    def __init__(
        self,
        classify: ShapeClassifier,
        pinpoint: PinpointRetrieve,
        summary_lookup: SummaryLookup,
    ) -> None:
        self._classify = classify
        self._pinpoint = pinpoint
        self._summary_lookup = summary_lookup

    async def route(self, query: str) -> list[RetrievedChunk]:
        shape = self._classify(query)
        if shape is QueryShape.WHOLE_DOC:
            return await self._whole_doc(query)
        if shape is QueryShape.AGGREGATE:
            return [build_decline_chunk(query)]
        # PINPOINT and any unrecognised shape: existing hybrid retrieve, unchanged.
        return await self._pinpoint(query)

    async def _whole_doc(self, query: str) -> list[RetrievedChunk]:
        results = await self._pinpoint(query)
        if not results:
            return results
        top_doc = results[0].chunk.document_id
        summary = await self._summary_lookup(top_doc)
        return summary if summary else results
