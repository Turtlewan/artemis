"""Artemis memory subsystem — bitemporal episodic + semantic fact storage.

Built on SQLCipher + sqlite-vec (encrypted at rest) in the per-scope vault.
This reduced build uses plain sqlite3 + sqlite-vec on the fallback path
(encryption layer deferred to the Mini — Tasks 1/3/5 of the M4-a spec).

Package layout:
  schema.py      — DDL for both stores, ``create_schema``
  repository.py  — ``BitemporalRepository`` (add/update/tombstone/as_of/history)
"""

from artemis.memory.decay import (
    decay_score,
    rank_for_inject,
    recall_multiplier,
    sweep_tombstone_candidates,
)
from artemis.memory.decide import AudnDecider, AudnDecision, AudnOp, FakeDecider
from artemis.memory.entities import (
    EntityRef,
    EntityRepository,
    EntityRow,
    EntityType,
    person_fact_key,
)
from artemis.memory.extraction import ExtractedFact, FactExtractor, FakeExtractor
from artemis.memory.owner import OwnerConfirmationRequired, OwnerMemory
from artemis.memory.repository import (
    BitemporalRepository,
    CurrentFactConflictError,
    DimensionMismatchError,
    EpisodeRow,
    FactRow,
)
from artemis.memory.schema import SENTINEL_TS, create_schema, now_iso
from artemis.memory.store import SqliteMemoryStore, render_inject_block
from artemis.memory.tools import (
    EntityNotFound,
    FactView,
    ResolveEntityArgs,
    ResolveEntityResult,
    memory_manifest,
    resolve_entity,
)
from artemis.memory.trips import (
    Trip,
    TripAssembler,
    TripExtract,
    TripLeg,
    TripLegKind,
    TripRepository,
    TripStatus,
    create_trip_schema,
    trip_entity_ref,
)
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
    entity_repo = EntityRepository(repo.conn, repo.person_id)
    return MemoryWritePath(repo, embedder, extractor, decider, entity_repo=entity_repo)


__all__ = [
    "AudnDecider",
    "AudnDecision",
    "AudnOp",
    "BitemporalRepository",
    "CurrentFactConflictError",
    "DimensionMismatchError",
    "EntityRef",
    "EntityNotFound",
    "EntityRepository",
    "EntityRow",
    "EntityType",
    "EpisodeRow",
    "ExtractedFact",
    "FactExtractor",
    "FactRow",
    "FactView",
    "FakeDecider",
    "FakeExtractor",
    "MemoryWritePath",
    "MemoryWriteQueue",
    "OwnerConfirmationRequired",
    "OwnerMemory",
    "ResolveEntityArgs",
    "ResolveEntityResult",
    "SENTINEL_TS",
    "SqliteMemoryStore",
    "Trip",
    "TripAssembler",
    "TripExtract",
    "TripLeg",
    "TripLegKind",
    "TripRepository",
    "TripStatus",
    "WritePathResult",
    "build_write_path",
    "create_schema",
    "create_trip_schema",
    "decay_score",
    "memory_manifest",
    "now_iso",
    "person_fact_key",
    "rank_for_inject",
    "recall_multiplier",
    "render_inject_block",
    "resolve_entity",
    "sweep_tombstone_candidates",
    "trip_entity_ref",
]
