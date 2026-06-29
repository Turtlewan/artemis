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
