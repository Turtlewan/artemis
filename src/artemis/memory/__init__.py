"""Artemis memory subsystem — bitemporal episodic + semantic fact storage.

Built on SQLCipher + sqlite-vec (encrypted at rest) in the per-scope vault.
This reduced build uses plain sqlite3 + sqlite-vec on the fallback path
(encryption layer deferred to the Mini — Tasks 1/3/5 of the M4-a spec).

Package layout:
  schema.py      — DDL for both stores, ``create_schema``
  repository.py  — ``BitemporalRepository`` (add/update/tombstone/as_of/history)
"""

from artemis.memory.decide import AudnDecider, AudnDecision, AudnOp, FakeDecider
from artemis.memory.entities import (
    EntityRef,
    EntityRepository,
    EntityRow,
    EntityType,
    person_fact_key,
)
from artemis.memory.extraction import ExtractedFact, FactExtractor, FakeExtractor
from artemis.memory.repository import (
    BitemporalRepository,
    CurrentFactConflictError,
    DimensionMismatchError,
    EpisodeRow,
    FactRow,
)
from artemis.memory.schema import SENTINEL_TS, create_schema, now_iso
from artemis.memory.write_path import (
    MemoryWritePath,
    MemoryWriteQueue,
    WritePathResult,
)
from artemis.ports.model import ModelPort
from artemis.ports.retrieval import EmbeddingModel


def build_write_path(
    repo: BitemporalRepository,
    embedder: EmbeddingModel,
    model: ModelPort,
) -> MemoryWritePath:
    """Construct a fully wired ``MemoryWritePath`` — M4-c's one-call constructor.

    The spec's Task 4 typed the first argument as ``SqliteMemoryStore``, but that
    type does not exist in the reduced build (M4-a takes a raw repository); the
    repository + embedder are passed in directly instead, with the same wiring
    intent. ``AudnDecider`` receives the repository for cardinality lookup.
    """
    extractor = FactExtractor(model)
    decider = AudnDecider(model, repo)
    return MemoryWritePath(repo, embedder, extractor, decider)


__all__ = [
    "AudnDecider",
    "AudnDecision",
    "AudnOp",
    "BitemporalRepository",
    "CurrentFactConflictError",
    "DimensionMismatchError",
    "EntityRef",
    "EntityRepository",
    "EntityRow",
    "EntityType",
    "EpisodeRow",
    "ExtractedFact",
    "FactExtractor",
    "FactRow",
    "FakeDecider",
    "FakeExtractor",
    "MemoryWritePath",
    "MemoryWriteQueue",
    "SENTINEL_TS",
    "WritePathResult",
    "build_write_path",
    "create_schema",
    "now_iso",
    "person_fact_key",
]
