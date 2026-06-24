"""Owner-controlled memory review and correction surface."""

from __future__ import annotations

from artemis.memory.repository import BitemporalRepository, FactRow
from artemis.memory.schema import now_iso
from artemis.ports.retrieval import EmbeddingModel


class OwnerConfirmationRequired(Exception):  # noqa: N818 - spec names this public exception.
    """Raised when an irreversible or owner-authored action lacks confirmation."""


class OwnerMemory:
    """Owner API for viewing, editing, tombstoning, and explicitly purging facts."""

    def __init__(self, repo: BitemporalRepository, embedder: EmbeddingModel) -> None:
        self._repo = repo
        self._embedder = embedder

    def list_current(self, *, limit: int = 100) -> list[FactRow]:
        """Return current facts with provenance for owner review."""
        return self._repo.as_of(now_iso())[:limit]

    def view_fact(self, fact_key: str) -> FactRow:
        """Return the current fact version and provenance for a logical fact."""
        rows = self._repo.as_of(now_iso(), fact_keys=[fact_key])
        if not rows:
            raise KeyError(fact_key)
        return rows[0]

    def history(self, fact_key: str) -> list[FactRow]:
        """Return the full bitemporal audit trail for a logical fact."""
        return self._repo.history(fact_key)

    async def edit_fact(
        self,
        fact_key: str,
        new_object: str,
        *,
        confirm: bool,
        new_confidence: float = 1.0,
        salience: float = 2.0,
    ) -> str:
        """Confirm, embed stored triple text, and write an auditable update."""
        del salience
        if confirm is not True:
            raise OwnerConfirmationRequired("Owner edit requires explicit confirmation.")

        current = self.view_fact(fact_key)
        stored_text = f"{current.subject} {current.relation} {new_object}"
        embedding = (await self._embedder.embed_documents([stored_text]))[0]
        return self._repo.update(
            fact_key,
            new_object,
            new_confidence,
            embedding,
            source_turn_id="owner-edit",
            extractor_model="owner",
        )

    def delete_fact(self, fact_key: str) -> None:
        """Soft-delete a logical fact by tombstoning it; history is preserved."""
        self._repo.tombstone(fact_key)

    def purge_fact(self, fact_key: str, *, confirm: bool) -> int:
        """Confirm and permanently purge all rows for a logical fact.

        This is the owner-only hard-delete path; decay and normal delete flows
        must use tombstones instead.
        """
        if confirm is not True:
            raise OwnerConfirmationRequired("Owner purge requires explicit confirmation.")
        return self._repo.purge(fact_key)
