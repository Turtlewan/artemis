"""LanceDB-backed ``VectorStore`` — reduced TEST-ONLY slice (plain dir, scope column).

Implements the M0-d ``VectorStore`` port: dense cosine KNN (``search``) +
an FTS/BM25 path (``search_text``), with a hard dimension-lock enforced on
write and on re-open. NOT forward-compatible with M3-a's on-disk schema —
full M3-a replaces this module (see the spec Assumptions). Never create this
store at a path M3-a will later open.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from artemis.ports.types import Chunk, RetrievedChunk, Scope, Vector

logger = logging.getLogger(__name__)

_SCOPE_RE = re.compile(r"[\w-]+")


class DimensionMismatchError(ValueError):
    """Raised when a vector's length (or a reopened table's width) != the store dimension."""


def _validate_scope(scope: str) -> None:
    """Reject a scope that is not a safe identifier (it is interpolated into SQL)."""
    if not _SCOPE_RE.fullmatch(scope):
        raise ValueError(f"Invalid scope (must match [\\w-]+): {scope!r}")


class LanceDBVectorStore:
    """LanceDB ``VectorStore`` (dense KNN + FTS) — structurally satisfies the port.

    .. code:: python

        store: VectorStore = LanceDBVectorStore(path, dimension=1024)  # type-checks
    """

    def __init__(self, db_path: Path, *, dimension: int, table_name: str = "chunks") -> None:
        import lancedb

        self._dimension = dimension
        self._table_name = table_name
        self._db = lancedb.connect(str(db_path))
        self._table: Any | None = None
        self._fts_ok = True
        if table_name in self._db.list_tables().tables:
            self._table = self._db.open_table(table_name)
            self._assert_table_dimension()

    def _assert_table_dimension(self) -> None:
        """Re-open guard: stored FixedSizeList width must match the store dimension."""
        assert self._table is not None
        field = self._table.schema.field("vector")
        stored_dim = getattr(field.type, "list_size", None)
        if stored_dim is not None and stored_dim != self._dimension:
            raise DimensionMismatchError(
                f"Table dimension {stored_dim} != store dimension {self._dimension}"
            )

    def _build_fts_index(self) -> None:
        """Build/refresh the native FTS index; degrade gracefully if unavailable."""
        assert self._table is not None
        try:
            self._table.create_fts_index("text", use_tantivy=False, replace=True)
        except (TypeError, ValueError, NotImplementedError) as exc:
            self._fts_ok = False
            logger.warning("LanceDB native FTS unavailable; search_text disabled: %s", exc)

    def add(
        self,
        scope: Scope,
        ids: Sequence[str],
        vectors: Sequence[Vector],
        metadata: Sequence[Mapping[str, object]],
    ) -> None:
        """Store vectors under a scope. Raises on a length, dimension, or scope error."""
        _validate_scope(scope)
        if len(ids) != len(vectors) or len(vectors) != len(metadata):
            raise ValueError(
                f"Mismatched lengths: ids={len(ids)}, vectors={len(vectors)}, "
                f"metadata={len(metadata)}"
            )
        for vec in vectors:
            if len(vec) != self._dimension:
                raise DimensionMismatchError(
                    f"Vector length {len(vec)} != store dimension {self._dimension}"
                )

        rows = [
            {
                "id": entry_id,
                "vector": list(vec),
                "scope": scope,
                "text": str(meta.get("text", "")),
                "document_id": str(meta.get("document_id", "")),
            }
            for entry_id, vec, meta in zip(ids, vectors, metadata)
        ]

        if self._table is None:
            self._table = self._db.create_table(self._table_name, data=rows)
        else:
            self._table.add(rows)
        # Native FTS is a static snapshot — rebuild after every write so newly
        # added rows are searchable (M3-a uses incremental optimize at scale).
        self._build_fts_index()

    def search(self, scope: Scope, query: Vector, k: int) -> list[RetrievedChunk]:
        """Dense cosine KNN within a scope (the ``VectorStore`` port method)."""
        _validate_scope(scope)
        if self._table is None:
            return []
        rows = (
            self._table.search(list(query))
            .metric("cosine")
            .where(f"scope = '{scope}'", prefilter=True)
            .limit(k)
            .to_list()
        )
        # score = cosine similarity ∈ [-1, 1] (LanceDB cosine _distance = 1 - sim).
        return [self._to_chunk(r, score=1.0 - float(r["_distance"])) for r in rows]

    def search_text(self, scope: Scope, query_text: str, k: int) -> list[RetrievedChunk]:
        """FTS/BM25 search within a scope (returns [] if native FTS is unavailable)."""
        _validate_scope(scope)
        if self._table is None or not self._fts_ok:
            return []
        rows = (
            self._table.search(query_text, query_type="fts")
            .where(f"scope = '{scope}'", prefilter=True)
            .limit(k)
            .to_list()
        )
        return [self._to_chunk(r, score=float(r.get("_score", 0.0))) for r in rows]

    @staticmethod
    def _to_chunk(row: Mapping[str, object], score: float) -> RetrievedChunk:
        return RetrievedChunk(
            chunk=Chunk(
                chunk_id=str(row["id"]),
                document_id=str(row.get("document_id", "")),
                text=str(row.get("text", "")),
                scope=str(row.get("scope", "")),
            ),
            score=score,
        )
