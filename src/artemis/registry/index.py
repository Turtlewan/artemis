"""In-memory cosine vector store behind the ``VectorStore`` port.

For M1's tiny tool count (< 50) a brute-force dot-product over
L2-normalised vectors is sufficient. The ``VectorStore`` port lets
LanceDB ANN replace it at corpus scale with no caller change.
"""

from __future__ import annotations

import math

from artemis.ports.types import Chunk, RetrievedChunk, Vector

# Internal type for stored entries
_Entry = tuple[str, str, Vector, dict[str, object]]  # scope, id, vector, metadata


class InMemoryToolIndex:
    """Brute-force cosine vector store satisfying ``VectorStore``.

    L2-normalises vectors on insert. ``search`` filters by scope and
    returns top-k by cosine similarity. This class structurally
    satisfies ``artemis.ports.VectorStore``.

    .. code:: python

        index: VectorStore = InMemoryToolIndex()  # type-checks
    """

    def __init__(self) -> None:
        self._entries: list[_Entry] = []

    def add(
        self,
        scope: str,
        ids: list[str],  # type[ignore] — Sequence[str] vs list[str]
        vectors: list[Vector],
        metadata: list[dict[str, object]],
    ) -> None:
        """Store vectors under a scope. Each vector is L2-normalised."""
        if len(ids) != len(vectors) or len(vectors) != len(metadata):
            raise ValueError(
                f"Mismatched lengths: ids={len(ids)}, vectors={len(vectors)}, "
                f"metadata={len(metadata)}"
            )
        for entry_id, vec, meta in zip(ids, vectors, metadata):
            norm = self._l2_norm(vec)
            if norm > 0:
                normalised = tuple(x / norm for x in vec)
            else:
                normalised = tuple(vec)
            self._entries.append((scope, entry_id, normalised, dict(meta)))

    def search(self, scope: str, query: Vector, k: int) -> list[RetrievedChunk]:
        """Return top-k entries within the given scope."""
        query_norm = self._l2_norm(query)
        if query_norm == 0:
            return []
        q = [x / query_norm for x in query]

        scored: list[tuple[float, str, dict[str, object]]] = []
        for entry_scope, eid, evec, meta in self._entries:
            if entry_scope != scope:
                continue
            dot = sum(a * b for a, b in zip(q, evec))
            scored.append((dot, eid, meta))

        scored.sort(key=lambda t: t[0], reverse=True)
        top = scored[:k]

        results: list[RetrievedChunk] = []
        for score, eid, meta in top:
            chunk = Chunk(
                chunk_id=eid,
                document_id=str(meta.get("module", "")),
                text=str(meta.get("text", "")),
                scope=str(meta.get("scope", "")),
            )
            results.append(RetrievedChunk(chunk=chunk, score=score))
        return results

    @staticmethod
    def _l2_norm(v: Vector) -> float:
        return math.sqrt(sum(x * x for x in v))
