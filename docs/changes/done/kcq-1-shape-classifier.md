---
status: ready
coder_effort: low
cross_model_review: false
---
# kcq-1-shape-classifier

**Identity:** Deterministic query-shape classifier (`PINPOINT` / `WHOLE_DOC` / `AGGREGATE`) with a reserved constrained 1-of-N LLM-fallback seam — wave **KCQ spec 1 of 6** (foundation; **kcq-3** consumes `classify_query_shape` + the `QueryShape` enum to route retrieval). Design: `docs/findings/query-shape-retrieval-design-2026-06-29.md` (Decision **D1 — Hybrid shape detection**). **NB the public function is `classify_query_shape` (NOT `classify_shape`)** — `gateway.py` already imports an unrelated `classify_shape` from `artemis.speakable` (the speakable `"short"/"pointer"` rule); the distinct name avoids that collision.

## Files to change

1. `src/artemis/ports/types.py` — **modify** — add the `QueryShape` StrEnum (co-located with `Mode`, the existing retrieval-mode type).
2. `src/artemis/retrieval/shape.py` — **create** — deterministic classifier + LLM-fallback seam.
3. `tests/test_query_shape.py` — **create** — per-shape cases + fallback-seam behaviour.

`EXACT_IDENTIFIER` is **out of scope** (separate BACKLOG item per the design). No model dependency — the fallback is an injected `Callable`, fake in tests.

## Exact changes

### 1. `src/artemis/ports/types.py` (modify)

The file currently has no `enum` import. Add it to the existing top imports block:

```python
from enum import StrEnum
```

Then, immediately **below** the existing `Mode = str` alias (line ~21-22), add the enum:

```python
class QueryShape(StrEnum):
    """Retrieval query shape selected by the shape-aware router (KCQ wave).

    ``PINPOINT`` is the existing hybrid top-k path; ``WHOLE_DOC`` and
    ``AGGREGATE`` are the costlier-but-correct routes consumed by kcq-3.
    ``EXACT_IDENTIFIER`` is a separate BACKLOG item and is intentionally absent.
    """

    PINPOINT = "pinpoint"
    WHOLE_DOC = "whole_doc"
    AGGREGATE = "aggregate"
```

Do not touch any other type in the file.

### 2. `src/artemis/retrieval/shape.py` (create)

Mirror the module conventions in `src/artemis/retrieval/retriever.py` (module docstring, `from __future__ import annotations`, `Callable` from `collections.abc`, import `QueryShape` from `artemis.ports.types`).

```python
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
    against PINPOINT. When both fire, AGGREGATE wins (checked first) — a stable,
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
```

### 3. `tests/test_query_shape.py` (create)

Mirror test conventions in `tests/test_agentic.py` (`from __future__ import annotations`, `pytest`). No fixtures/IO needed — pure function.

```python
"""Tests for the deterministic query-shape classifier (kcq-1)."""

from __future__ import annotations

import pytest

from artemis.ports.types import QueryShape
from artemis.retrieval.shape import classify_query_shape


@pytest.mark.parametrize(
    "query",
    [
        "summarise this report for me",
        "give me an overview of the project",
        "what's the gist of the whole thread",
        "tl;dr the entire document",
    ],
)
def test_whole_doc_queries(query: str) -> None:
    assert classify_query_shape(query) is QueryShape.WHOLE_DOC


@pytest.mark.parametrize(
    "query",
    [
        "which week had the highest spend",
        "how many emails did I get",
        "what is the total of my expenses",
        "average spend per month",
        "count of meetings this quarter",
    ],
)
def test_aggregate_queries(query: str) -> None:
    assert classify_query_shape(query) is QueryShape.AGGREGATE


@pytest.mark.parametrize(
    "query",
    [
        "what did Sarah say about the budget",
        "when is my next dentist appointment",
        "find the address for the venue",
    ],
)
def test_pinpoint_queries(query: str) -> None:
    assert classify_query_shape(query) is QueryShape.PINPOINT


def test_aggregate_wins_tie_over_whole_doc() -> None:
    # Both strong triggers present; AGGREGATE is checked first (stable tie-break).
    assert classify_query_shape("summarise how many invoices") is QueryShape.AGGREGATE


def test_fallback_invoked_only_on_ambiguous_and_label_honored() -> None:
    calls: list[str] = []

    def fallback(q: str) -> QueryShape:
        calls.append(q)
        return QueryShape.WHOLE_DOC

    # "report" is a weak signal, no strong trigger -> ambiguous -> fallback used.
    result = classify_query_shape("what's in the report", fallback=fallback)
    assert result is QueryShape.WHOLE_DOC
    assert calls == ["what's in the report"]


def test_fallback_not_called_for_clear_pinpoint() -> None:
    def fallback(q: str) -> QueryShape:  # pragma: no cover - must not run
        raise AssertionError("fallback must not run on a clear pinpoint query")

    assert (
        classify_query_shape("what did Sarah say about the budget", fallback=fallback)
        is QueryShape.PINPOINT
    )


def test_fallback_not_called_when_strong_trigger_fires() -> None:
    def fallback(q: str) -> QueryShape:  # pragma: no cover - must not run
        raise AssertionError("fallback must not run when a strong trigger fired")

    assert classify_query_shape("summarise the report", fallback=fallback) is QueryShape.WHOLE_DOC


def test_no_fallback_ambiguous_defaults_to_pinpoint() -> None:
    # Ambiguous but no fallback supplied -> deterministic PINPOINT default.
    assert classify_query_shape("what's in the report") is QueryShape.PINPOINT
```

## Acceptance criteria

1. `QueryShape` enum added to `ports/types.py` with exactly `PINPOINT`/`WHOLE_DOC`/`AGGREGATE` → verify: `uv run python -c "from artemis.ports.types import QueryShape; print([m.value for m in QueryShape])"` prints `['pinpoint', 'whole_doc', 'aggregate']`.
2. Classifier + fallback seam behave per spec → verify: `uv run pytest tests/test_query_shape.py -q` passes (all cases green, including fallback-only-on-ambiguous and label-honored).
3. No type regressions → verify: `uv run mypy` is clean.
4. No broader regressions → verify: `uv run pytest -q` passes.

## Commands to run

```bash
uv run pytest tests/test_query_shape.py -q
uv run mypy
uv run pytest -q
```
