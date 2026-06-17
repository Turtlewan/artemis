"""Artemis memory subsystem — bitemporal episodic + semantic fact storage.

Built on SQLCipher + sqlite-vec (encrypted at rest) in the per-scope vault.
This reduced build uses plain sqlite3 + sqlite-vec on the fallback path
(encryption layer deferred to the Mini — Tasks 1/3/5 of the M4-a spec).

Package layout:
  schema.py      — DDL for both stores, ``create_schema``
  repository.py  — ``BitemporalRepository`` (add/update/tombstone/as_of/history)
"""

from artemis.memory.repository import (
    BitemporalRepository,
    CurrentFactConflictError,
    DimensionMismatchError,
    EpisodeRow,
    FactRow,
)
from artemis.memory.schema import SENTINEL_TS, create_schema, now_iso

__all__ = [
    "BitemporalRepository",
    "CurrentFactConflictError",
    "DimensionMismatchError",
    "EpisodeRow",
    "FactRow",
    "SENTINEL_TS",
    "create_schema",
    "now_iso",
]
