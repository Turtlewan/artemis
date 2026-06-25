"""MemoryStore adapter backed by the bitemporal SQLite repository."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from artemis.memory.decay import rank_for_inject, recall_multiplier
from artemis.memory.repository import BitemporalRepository, FactRow
from artemis.memory.schema import now_iso
from artemis.ports.retrieval import EmbeddingModel
from artemis.ports.types import AsOf, Fact, PersonId
from artemis.sensitivity import Sensitivity


class SqliteMemoryStore:
    """Concrete semantic memory store over ``BitemporalRepository``."""

    def __init__(self, repo: BitemporalRepository, embedder: EmbeddingModel) -> None:
        self._repo = repo
        self._embedder = embedder

    async def add_fact(self, person_id: PersonId, fact: Fact) -> None:
        """Embed and add a fact for protocol completeness."""
        del person_id
        embedding = (
            await self._embedder.embed_documents([f"{fact.subject} {fact.relation} {fact.object}"])
        )[0]
        self._repo.add(
            fact.subject,
            fact.relation,
            fact.object,
            fact.confidence,
            embedding,
            valid_from=fact.valid_at.isoformat(),
        )

    async def recall(
        self,
        person_id: PersonId,
        query: str,
        k: int = 10,
        as_of: AsOf | None = None,
    ) -> list[Fact]:
        """Recall semantic candidates and re-rank them by decay multiplier."""
        del person_id, as_of
        qv = await self._embedder.embed_query(query)
        candidates = self._repo.semantic_candidates(qv, k)
        now = now_iso()
        ranked: list[tuple[FactRow, float]] = []
        for fact_id, distance in candidates:
            try:
                row = self._repo.get_fact(fact_id)
            except KeyError:
                continue
            cosine = 1.0 - distance
            multiplier = recall_multiplier(
                last_access=row.last_access,
                valid_from=row.valid_from,
                access_count=row.access_count,
                cosine=cosine,
                now=now,
            )
            ranked.append((row, cosine * multiplier))
        ranked.sort(key=lambda item: item[1], reverse=True)
        return [self._to_fact(row) for row, _score in ranked[:k]]

    async def update_fact(self, person_id: PersonId, fact_id: str, fact: Fact) -> None:
        """Embed and update the current version for a logical fact."""
        del person_id
        row = self._repo.get_fact(fact_id)
        embedding = (
            await self._embedder.embed_documents([f"{fact.subject} {fact.relation} {fact.object}"])
        )[0]
        self._repo.update(row.fact_key, fact.object, fact.confidence, embedding)

    def delete_fact(self, person_id: PersonId, fact_id: str) -> None:
        """Tombstone a fact without deleting history."""
        del person_id
        row = self._repo.get_fact(fact_id)
        self._repo.tombstone(row.fact_key)

    async def inject_context(
        self,
        person_id: PersonId,
        token_budget: int,
        as_of: AsOf | None = None,
    ) -> list[Fact]:
        """Return top current facts within budget and bump access for selected facts."""
        del person_id
        valid_t = as_of.valid_at.isoformat() if as_of else None
        tx_t = as_of.tx_at.isoformat() if as_of and as_of.tx_at else None
        rows = self._repo.as_of(valid_t=valid_t, tx_t=tx_t)
        ranked = rank_for_inject(rows, now=now_iso())
        selected: list[FactRow] = []
        token_total = 0
        for row, _score in ranked:
            rendered = f"{row.subject} {row.relation} {row.object}"
            # Rough token estimate: most English text averages about four chars per token.
            token_cost = len(rendered) // 4
            if token_total + token_cost > token_budget:
                break
            selected.append(row)
            token_total += token_cost
        for row in selected:
            self._repo.bump_access(row.fact_id)
        return [self._to_fact(row) for row in selected]

    def _to_fact(self, row: FactRow) -> Fact:
        sensitivity: Sensitivity = "general" if row.sensitivity == "general" else "sensitive"
        return Fact(
            fact_id=row.fact_id,
            person_id=PersonId(row.person_id),
            subject=row.subject,
            relation=row.relation,
            object=row.object,
            confidence=row.confidence,
            valid_at=datetime.fromisoformat(row.valid_from),
            sensitivity=sensitivity,
            category=row.category,
        )


def render_inject_block(facts: Sequence[Fact]) -> str:
    """Render injected owner facts as a compact system-prompt block."""
    if not facts:
        return ""
    return "Known facts about the owner:\n" + "\n".join(
        f"- {fact.subject} {fact.relation} {fact.object}" for fact in facts
    )
