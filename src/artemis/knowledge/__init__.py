"""Knowledge subsystem (M3) — document storage + retrieval.

Slice 3a ships a TEST-ONLY LanceDB ``VectorStore`` round-trip; full M3-a
replaces this module with the ingestion-backed production store.
"""

from __future__ import annotations

from artemis.knowledge.vector_store import DimensionMismatchError, LanceDBVectorStore

__all__ = ["DimensionMismatchError", "LanceDBVectorStore"]
