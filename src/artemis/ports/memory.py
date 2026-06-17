"""MemoryStore port — bitemporal person-scoped memory.

ASYNC PORT RULE (ADR-015): methods that embed (add_fact, recall,
update_fact, inject_context) are async; delete_fact (tombstone only,
no embed) stays sync.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from artemis.ports.types import AsOf, Fact, PersonId


@runtime_checkable
class MemoryStore(Protocol):
    """Bitemporal fact store scoped to a person."""

    async def add_fact(self, person_id: PersonId, fact: Fact) -> None:
        """Store a fact (embeds it — async)."""
        ...

    async def recall(
        self,
        person_id: PersonId,
        query: str,
        k: int = 10,
        as_of: AsOf | None = None,
    ) -> list[Fact]:
        """Recall facts by semantic similarity to query (async — embeds query)."""
        ...

    async def update_fact(self, person_id: PersonId, fact_id: str, fact: Fact) -> None:
        """Replace a fact — closes the prior interval and inserts new (async — embeds)."""
        ...

    def delete_fact(self, person_id: PersonId, fact_id: str) -> None:
        """Tombstone a fact (sync — no embed, local DB write)."""
        ...

    async def inject_context(
        self,
        person_id: PersonId,
        token_budget: int,
        as_of: AsOf | None = None,
    ) -> list[Fact]:
        """Auto-inject the current top facts for context (async — may embed/rank)."""
        ...
