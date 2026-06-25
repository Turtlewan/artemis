"""Shared domain types for the Artemis ports package."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING, NewType

if TYPE_CHECKING:
    from artemis.sensitivity import Sensitivity

PersonId = NewType("PersonId", str)
"""Unique identifier for a person."""

Scope = str
"""Storage scope: ``owner-private``, ``general``, or ``guest-<person_id>``."""

Vector = Sequence[float]
"""Engine-agnostic embedding vector."""

Mode = str
"""Retrieval mode: ``hybrid``, ``agentic``, or ``graph``."""


class AsOf:
    """Bitemporal point-in-time query parameter.

    Attributes:
        valid_at: The valid-time bound (required).
        tx_at: The transaction-time bound (optional; defaults to now).
    """

    def __init__(self, valid_at: datetime, tx_at: datetime | None = None) -> None:
        self.valid_at = valid_at
        self.tx_at = tx_at

    def __repr__(self) -> str:
        return f"AsOf(valid_at={self.valid_at!r}, tx_at={self.tx_at!r})"


class Message:
    """A single chat message."""

    def __init__(self, role: str, content: str) -> None:
        self.role = role
        self.content = content

    def __repr__(self) -> str:
        return f"Message(role={self.role!r}, content={self.content!r})"


class Document:
    """A source document ingested into the knowledge store."""

    def __init__(
        self,
        document_id: str,
        source_id: str,
        content_hash: str,
        scope: Scope,
        text: str,
        sensitivity: Sensitivity = "sensitive",
        category: str | None = None,
    ) -> None:
        self.document_id = document_id
        self.source_id = source_id
        self.content_hash = content_hash
        self.scope = scope
        self.text = text
        self.sensitivity = sensitivity
        self.category = category


class Chunk:
    """A chunk of a document.

    ``sensitivity`` and ``category`` carry ADR-029 source tags written by
    SENS-prod-M3a for the downstream enforcer. Missing sensitivity fails closed
    to ``"sensitive"``.
    """

    def __init__(
        self,
        chunk_id: str,
        document_id: str,
        text: str,
        scope: Scope,
        sensitivity: Sensitivity = "sensitive",
        category: str | None = None,
    ) -> None:
        self.chunk_id = chunk_id
        self.document_id = document_id
        self.text = text
        self.scope = scope
        self.sensitivity = sensitivity
        self.category = category


class RetrievedChunk:
    """A chunk returned from a vector search with a relevance score."""

    def __init__(self, chunk: Chunk, score: float) -> None:
        self.chunk = chunk
        self.score = score


class Fact:
    """A bitemporal fact about a person.

    ``sensitivity`` and ``category`` carry ADR-029 tags written by
    SENS-prod-M4b for the downstream enforcer. Missing sensitivity fails
    closed to ``"sensitive"``.
    """

    def __init__(
        self,
        fact_id: str,
        person_id: PersonId,
        subject: str,
        relation: str,
        object: str,
        confidence: float,
        valid_at: datetime,
        invalid_at: datetime | None = None,
        sensitivity: Sensitivity = "sensitive",
        category: str | None = None,
    ) -> None:
        self.fact_id = fact_id
        self.person_id = person_id
        self.subject = subject
        self.relation = relation
        self.object = object
        self.confidence = confidence
        self.valid_at = valid_at
        self.invalid_at = invalid_at
        self.sensitivity = sensitivity
        self.category = category


class Usage:
    """Token usage for a model call."""

    def __init__(self, prompt_tokens: int, completion_tokens: int, total_tokens: int) -> None:
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = total_tokens
