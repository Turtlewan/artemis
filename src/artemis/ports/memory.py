"""Memory subsystem port."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from artemis.types import MemoryItem, RetrievedContext


@runtime_checkable
class MemoryPort(Protocol):
    async def write(self, item: MemoryItem) -> None:
        """Consolidating write (ADD/UPDATE/DELETE/NOOP) — never blind-append."""
        ...

    async def retrieve(
        self,
        query: str,
        *,
        token_budget: int,
        layers: Sequence[str] | None = None,
    ) -> RetrievedContext:
        """Retrieve wide, rerank + MMR-dedup, cap to token_budget, summarize overflow."""
        ...

    async def consolidate(self) -> None:
        """Background: episodic to semantic, build/refresh summaries, merge near-dupes."""
        ...

    async def forget(
        self,
        *,
        max_age_days: int | None = None,
        min_salience: float | None = None,
    ) -> None:
        """Demote/decay/archive — never hard-delete."""
        ...
