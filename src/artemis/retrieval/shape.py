"""Deterministic query-shape classifier with a reserved LLM-fallback seam."""

from __future__ import annotations

import re
from collections.abc import Callable

from artemis.ports.types import QueryShape

ShapeFallback = Callable[[str], QueryShape]
"""Constrained 1-of-N seam: returns a single QueryShape label (NOT JSON).

Invoked ONLY when the deterministic rules are ambiguous (a weak signal is
present but no strong trigger fired). Per design D1 the model is asked for one
label out of N, sidestepping qwen3:4b structured-output fragility.
"""

# Strong WHOLE_DOC triggers: faithful-summary / read-the-whole-thing intent.
_WHOLE_DOC_PATTERNS: tuple[str, ...] = (
    "summarise",
    "summarize",
    "summary of",
    "overview",
    "the whole",
    "entire",
    "tl;dr",
    "gist of",
)

# Strong AGGREGATE triggers: compute-over-all-records intent.
_AGGREGATE_SUBSTRINGS: tuple[str, ...] = (
    "how many",
    "total of",
    "sum of",
    "average",
    "count of",
)
_AGGREGATE_REGEXES: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bwhich\b.*\b(most|highest|lowest|largest)\b"),
    re.compile(r"\bper\s+(week|month|day)\b"),
)

# Weak signals: possibly whole-doc/aggregate but inconclusive -> ambiguous.
_WEAK_SIGNALS: tuple[str, ...] = (
    "report",
    "document",
    "the file",
    "everything",
    "breakdown",
)


def _is_aggregate(text: str) -> bool:
    if any(sub in text for sub in _AGGREGATE_SUBSTRINGS):
        return True
    return any(rx.search(text) for rx in _AGGREGATE_REGEXES)


def _is_whole_doc(text: str) -> bool:
    return any(pat in text for pat in _WHOLE_DOC_PATTERNS)


def _is_ambiguous(text: str) -> bool:
    return any(sig in text for sig in _WEAK_SIGNALS)


def classify_query_shape(query: str, *, fallback: ShapeFallback | None = None) -> QueryShape:
    """Classify ``query`` into a :class:`QueryShape`.

    Deterministic first. Aggregate and whole-doc strong triggers are checked
    before the PINPOINT default, so any costlier-but-correct match wins the tie
    against PINPOINT. When both fire, AGGREGATE wins (checked first) -- a stable,
    deterministic tie-break. The ``fallback`` seam is consulted ONLY when no
    strong trigger fired but a weak signal makes the query ambiguous; its
    returned label is honored as-is.
    """
    text = query.lower().strip()

    if _is_aggregate(text):
        return QueryShape.AGGREGATE
    if _is_whole_doc(text):
        return QueryShape.WHOLE_DOC

    if fallback is not None and _is_ambiguous(text):
        return fallback(query)

    return QueryShape.PINPOINT
