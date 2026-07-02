"""Typed records for the frozen web-tool evaluation corpus."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Behavior = Literal["answer", "abstain", "correct_premise", "clarify", "flag_conflict"]
QueryCategory = Literal[
    "single_fact",
    "multi_hop",
    "comparative",
    "aggregation",
    "temporal",
    "false_premise",
    "negative",
    "adversarial",
    "conflicting",
]


class ConflictClaim(BaseModel):
    """One attributed claim in a conflicting-answer query."""

    model_config = ConfigDict(frozen=True)

    claim: str
    source_url: str
    is_authoritative: bool


class PageFixtureRef(BaseModel):
    """Reference from a query record to a page fixture pinned by SHA-256."""

    model_config = ConfigDict(frozen=True)

    fixture_id: str
    sha256: str


class QueryRecord(BaseModel):
    """Golden query label and expected behavior for web-tool evaluation."""

    model_config = ConfigDict(frozen=True)

    id: str
    query: str
    category: QueryCategory
    noise: bool = False
    behavior: Behavior
    expected_answer: str | None = None
    accepted_variants: list[str] = Field(default_factory=list)
    expected_set: list[str] | None = None
    expected_count: int | None = None
    expected_citations: list[str] = Field(default_factory=list)
    must_not: list[str] = Field(default_factory=list)
    expected_correction: str | None = None
    conflicting_claims: list[ConflictClaim] = Field(default_factory=list)
    as_of_date: str | None = None
    capture_date: str | None = None
    pages: list[PageFixtureRef]
    notes: str | None = None


class PageFixture(BaseModel):
    """Stored clean-text page fixture used by one or more web-tool eval queries."""

    model_config = ConfigDict(frozen=True)

    id: str
    url: str
    text: str
    sha256: str
    source: Literal["captured", "authored"]
    capture_date: str | None = None
    published_date: str | None = None
    injection_subkind: Literal["A", "B", "C", "D", "E", "F", "G"] | None = None
    benign_twin_of: str | None = None
    payload_placement: Literal["top", "mid_body", "table_cell", "metadata", "comment"] | None = None
