"""Best-effort memory write path: episode, extract, match, decide, apply."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass

from artemis.memory.decide import AudnDecider, AudnDecision, Candidate
from artemis.memory.entities import EntityRepository, EntityType
from artemis.memory.extraction import FactExtractor
from artemis.memory.repository import BitemporalRepository
from artemis.ports.retrieval import EmbeddingModel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WritePathResult:
    """Counters returned by one memory write pass."""

    episode_id: str
    facts_added: int = 0
    facts_updated: int = 0
    facts_deleted: int = 0
    noops: int = 0
    errors: int = 0


@dataclass(frozen=True)
class _QueuedTurn:
    text: str
    turn_id: str
    role: str | None


class MemoryWritePath:
    """Apply extracted memory facts through non-destructive repository primitives."""

    def __init__(
        self,
        repo: BitemporalRepository,
        embedder: EmbeddingModel,
        extractor: FactExtractor,
        decider: AudnDecider,
        *,
        entity_repo: EntityRepository | None = None,
        candidate_k: int = 5,
        extractor_model_id: str = "Qwen3.6-27B",
    ) -> None:
        self._repo = repo
        self.entity_repo = entity_repo or EntityRepository(repo.conn, repo.person_id)
        self._embedder = embedder
        self._extractor = extractor
        self._decider = decider
        self._candidate_k = candidate_k
        self._extractor_model_id = extractor_model_id

    async def process_turn(
        self, text: str, *, turn_id: str, role: str | None = None
    ) -> WritePathResult:
        """Append the episode first, then best-effort extract and apply facts."""
        episode_id = self._repo.append_episode(text, turn_id=turn_id, role=role)
        result = WritePathResult(episode_id=episode_id)

        try:
            facts = await self._extractor.extract(text)
        except Exception as exc:
            logger.warning(
                "Memory extraction failed for turn id %s (%s)", turn_id, type(exc).__name__
            )
            return _with_errors(result, 1)

        for fact in facts:
            try:
                embedding = (await self._embedder.embed_documents([_fact_text(fact)]))[0]
                candidates = self._candidates_for(embedding)
                decision = await self._decider.decide(fact, candidates)
                try:
                    # M4-d-2 auto-links fact SUBJECTS to PERSON entities only
                    # (ADR-013 Decision 1/6 person pointer). PLACE/GOAL entities
                    # are created on-demand by their owning spokes, not extracted here.
                    subject_entity_id = self.entity_repo.resolve_or_create_entity(
                        fact.subject, EntityType.PERSON
                    )
                except Exception as exc:
                    logger.warning(
                        "entity resolution failed (%s); storing fact without entity link",
                        type(exc).__name__,
                    )
                    subject_entity_id = None
                result = self._apply_decision(
                    result, fact, decision, embedding, turn_id, subject_entity_id
                )
            except Exception as exc:
                logger.warning(
                    "Memory write failed for turn id %s (%s)", turn_id, type(exc).__name__
                )
                result = _with_errors(result, 1)

        return result

    def _candidates_for(self, embedding: Sequence[float]) -> list[Candidate]:
        candidates: list[Candidate] = []
        for fact_id, _distance in self._repo.semantic_candidates(embedding, self._candidate_k):
            try:
                row = self._repo.get_fact(fact_id)
            except KeyError:
                continue
            candidates.append(
                Candidate(
                    fact_id=row.fact_id,
                    subject=row.subject,
                    relation=row.relation,
                    object=row.object,
                )
            )
        return candidates

    def _apply_decision(
        self,
        result: WritePathResult,
        fact: object,
        decision: AudnDecision,
        embedding: Sequence[float],
        turn_id: str,
        subject_entity_id: str | None,
    ) -> WritePathResult:
        from artemis.memory.extraction import ExtractedFact

        if not isinstance(fact, ExtractedFact):
            raise TypeError("fact must be an ExtractedFact")

        if decision.op == "ADD":
            self._repo.add(
                fact.subject,
                fact.relation,
                fact.object,
                decision.confidence,
                embedding,
                source_turn_id=turn_id,
                extractor_model=self._extractor_model_id,
                keywords=fact.keywords,
                contextual_description=fact.contextual_description,
                subject_entity_id=subject_entity_id,
            )
            return _replace(result, facts_added=result.facts_added + 1)

        if decision.op == "UPDATE":
            if decision.target_fact_id is None:
                raise ValueError("UPDATE decision missing target_fact_id")
            target = self._repo.get_fact(decision.target_fact_id)
            self._repo.update(
                target.fact_key,
                decision.object or fact.object,
                decision.confidence,
                embedding,
                source_turn_id=turn_id,
                extractor_model=self._extractor_model_id,
                keywords=fact.keywords,
                contextual_description=fact.contextual_description,
                subject_entity_id=subject_entity_id,
            )
            return _replace(result, facts_updated=result.facts_updated + 1)

        if decision.op == "DELETE":
            if decision.target_fact_id is None:
                raise ValueError("DELETE decision missing target_fact_id")
            target = self._repo.get_fact(decision.target_fact_id)
            self._repo.tombstone(target.fact_key)
            return _replace(result, facts_deleted=result.facts_deleted + 1)

        return _replace(result, noops=result.noops + 1)


class MemoryWriteQueue:
    """Single-flight in-process queue for best-effort memory writes."""

    def __init__(self, write_path: MemoryWritePath, *, maxsize: int = 100) -> None:
        self._write_path = write_path
        self._queue: asyncio.Queue[_QueuedTurn] = asyncio.Queue(maxsize=maxsize)

    def enqueue(self, text: str, turn_id: str, role: str | None = None) -> None:
        """Queue a turn without blocking; drop when full."""
        try:
            self._queue.put_nowait(_QueuedTurn(text=text, turn_id=turn_id, role=role))
        except asyncio.QueueFull:
            logger.warning("Memory write queue full; dropping turn id %s", turn_id)

    async def run_worker(self) -> None:
        """Drain queued writes forever, logging escapes so the worker survives."""
        while True:
            item = await self._queue.get()
            try:
                await self._write_path.process_turn(item.text, turn_id=item.turn_id, role=item.role)
            except Exception as exc:
                logger.warning(
                    "Memory write worker caught failure for turn id %s (%s)",
                    item.turn_id,
                    type(exc).__name__,
                )
            finally:
                self._queue.task_done()

    async def drain(self) -> None:
        """Process queued items when no worker is running, or wait for an active worker."""
        while True:
            try:
                item = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                await self._write_path.process_turn(item.text, turn_id=item.turn_id, role=item.role)
            except Exception as exc:
                logger.warning(
                    "Memory write drain caught failure for turn id %s (%s)",
                    item.turn_id,
                    type(exc).__name__,
                )
            finally:
                self._queue.task_done()


def _fact_text(fact: object) -> str:
    from artemis.memory.extraction import ExtractedFact

    if not isinstance(fact, ExtractedFact):
        raise TypeError("fact must be an ExtractedFact")
    return f"{fact.subject} {fact.relation} {fact.object}"


def _replace(
    result: WritePathResult,
    *,
    facts_added: int | None = None,
    facts_updated: int | None = None,
    facts_deleted: int | None = None,
    noops: int | None = None,
    errors: int | None = None,
) -> WritePathResult:
    return WritePathResult(
        episode_id=result.episode_id,
        facts_added=result.facts_added if facts_added is None else facts_added,
        facts_updated=result.facts_updated if facts_updated is None else facts_updated,
        facts_deleted=result.facts_deleted if facts_deleted is None else facts_deleted,
        noops=result.noops if noops is None else noops,
        errors=result.errors if errors is None else errors,
    )


def _with_errors(result: WritePathResult, count: int) -> WritePathResult:
    return _replace(result, errors=result.errors + count)
