"""LanceDB VectorStore adapter rooted in the per-scope vault directory."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Any, cast

import pyarrow as pa

from artemis import paths
from artemis.config import Settings
from artemis.data.scoped_store import assert_same_scope
from artemis.identity.key_provider import ScopeLockedError
from artemis.ports.types import Chunk, RetrievedChunk, Scope, Vector
from artemis.retrieval.rrf import reciprocal_rank_fusion
from artemis.sensitivity import Sensitivity

logger = logging.getLogger(__name__)

_SCOPE_RE = re.compile(r"[\w-]+")


class DimensionMismatchError(ValueError):
    """Raised when vector width or stored embedder metadata differs."""


class LanceDBVectorStore:
    """LanceDB store for document chunks inside ``paths.vault_dir``."""

    def __init__(
        self,
        scope: Scope,
        settings: Settings,
        embedder_model_id: str,
        dimension: int,
        *,
        is_unlocked: Callable[[], bool],
    ) -> None:
        if not is_unlocked():
            raise ScopeLockedError(f"Scope is locked: {scope}")
        _validate_scope(scope)
        self.scope = scope
        self._dimension = dimension
        self._embedder_model_id = embedder_model_id
        self._table_name = f"docs_{scope}"
        self._meta_table_name = f"{self._table_name}_metadata"
        self._fts_ok = True
        self._hybrid_native: bool | None = None

        import lancedb

        db_path = paths.vault_dir(settings, scope)
        db_path.mkdir(parents=True, exist_ok=True)
        self._db = lancedb.connect(str(db_path))
        self._table: Any | None = None
        self._ensure_metadata()
        if self._table_name in self._table_names():
            self._table = self._db.open_table(self._table_name)
            self._assert_table_dimension()

    def add(
        self,
        scope: Scope,
        ids: Sequence[str],
        vectors: Sequence[Vector],
        metadata: Sequence[Mapping[str, object]],
    ) -> None:
        """Upsert chunk rows for this scope."""
        assert_same_scope(self.scope, scope)
        if len(ids) != len(vectors) or len(vectors) != len(metadata):
            raise ValueError("ids, vectors, and metadata must have the same length")
        for vector in vectors:
            if len(vector) != self._dimension:
                raise DimensionMismatchError(
                    f"Vector length {len(vector)} != store dimension {self._dimension}"
                )

        rows = [
            {
                "id": entry_id,
                "vector": list(vector),
                "text": str(meta.get("text", "")),
                "scope": scope,
                "content_hash": str(meta.get("content_hash", "")),
                "source_id": str(meta.get("source_id", "")),
                "document_id": str(meta.get("document_id", "")),
                "page": _optional_int(meta.get("page")),
                "bbox": _optional_bbox(meta.get("bbox")),
                "char_start": _required_int(meta.get("char_start", 0)),
                "char_end": _required_int(meta.get("char_end", 0)),
                "node_level": _required_int(meta.get("node_level", 0)),
                "is_summary": bool(meta.get("is_summary", False)),
                "parent_chunk_id": _optional_str(meta.get("parent_chunk_id")),
                "sensitivity": _sensitivity(meta.get("sensitivity")),
                "category": _optional_str(meta.get("category")),
                "source_date": _iso_or_none(meta.get("source_date")),
            }
            for entry_id, vector, meta in zip(ids, vectors, metadata)
        ]
        if not rows:
            return

        if self._table is None:
            self._table = self._db.create_table(self._table_name, data=rows, schema=self._schema())
        else:
            for entry_id in ids:
                self._table.delete(f"id = '{_quote_sql(entry_id)}'")
            self._table.add(rows)
        self._build_fts_index()

    def search(self, scope: Scope, query: Vector, k: int) -> list[RetrievedChunk]:
        """Dense cosine KNN within this store's scope."""
        assert_same_scope(self.scope, scope)
        if len(query) != self._dimension:
            raise DimensionMismatchError(
                f"Query length {len(query)} != store dimension {self._dimension}"
            )
        if self._table is None:
            return []
        rows = (
            self._table.search(list(query))
            .metric("cosine")
            .where(f"scope = '{_quote_sql(scope)}'", prefilter=True)
            .limit(k)
            .to_list()
        )
        return [_row_to_retrieved(row, score=1.0 - float(row["_distance"])) for row in rows]

    def hybrid_search(
        self,
        scope: Scope,
        query_vector: Sequence[float],
        query_text: str,
        k: int,
    ) -> list[RetrievedChunk]:
        """Search dense+FTS with native LanceDB hybrid when available.

        ``self._hybrid_native`` records the path chosen on first call. Older or
        unstable LanceDB hybrid APIs fall back to explicit dense + text rankings
        fused by local RRF.
        """
        assert_same_scope(self.scope, scope)
        if k <= 0 or self._table is None:
            return []
        try:
            results = self._native_hybrid_search(scope, query_vector, query_text, k)
            if self._hybrid_native is None:
                self._hybrid_native = True
            return results
        except (AttributeError, NotImplementedError, TypeError, ValueError) as exc:
            if self._hybrid_native is None:
                self._hybrid_native = False
            logger.debug("LanceDB native hybrid unavailable; using explicit RRF: %s", exc)
            return self._fallback_hybrid_search(scope, query_vector, query_text, k)

    def has_document(self, document_id: str, content_hash: str) -> bool:
        """Return true when this document hash already exists."""
        if self._table is None:
            return False
        rows = (
            self._table.search()
            .where(
                "document_id = "
                f"'{_quote_sql(document_id)}' AND content_hash = '{_quote_sql(content_hash)}'",
                prefilter=True,
            )
            .limit(1)
            .to_list()
        )
        return bool(rows)

    def delete_document(self, document_id: str) -> None:
        """Delete all chunks for a document id."""
        if self._table is not None:
            self._table.delete(f"document_id = '{_quote_sql(document_id)}'")

    def row_count(self) -> int:
        """Return row count for tests and diagnostics."""
        if self._table is None:
            return 0
        return len(self._table.search().limit(1_000_000).to_list())

    def rows(self) -> list[Mapping[str, object]]:
        """Return table rows for focused tests."""
        if self._table is None:
            return []
        return list(self._table.search().limit(1_000_000).to_list())

    def _native_hybrid_search(
        self,
        scope: Scope,
        query_vector: Sequence[float],
        query_text: str,
        k: int,
    ) -> list[RetrievedChunk]:
        assert self._table is not None
        query = self._table.search(query_type="hybrid").vector(list(query_vector)).text(query_text)
        if hasattr(query, "rerank"):
            query = query.rerank("rrf")
        rows = query.where(f"scope = '{_quote_sql(scope)}'", prefilter=True).limit(k).to_list()
        return [_row_to_retrieved(row, score=_score_from_row(row, default=1.0)) for row in rows]

    def _fallback_hybrid_search(
        self,
        scope: Scope,
        query_vector: Sequence[float],
        query_text: str,
        k: int,
    ) -> list[RetrievedChunk]:
        candidate_k = max(k * 2, k)
        dense = self.search(scope, query_vector, candidate_k)
        text_rows = self._text_search_rows(scope, query_text, candidate_k)
        rankings = [
            [chunk.chunk.chunk_id for chunk in dense],
            [str(row["id"]) for row in text_rows],
        ]
        fused = reciprocal_rank_fusion(rankings)
        rows_by_id = {
            str(row["id"]): row for row in self._rows_by_ids([item_id for item_id, _score in fused])
        }
        return [
            _row_to_retrieved(rows_by_id[item_id], score=score)
            for item_id, score in fused[:k]
            if item_id in rows_by_id
        ]

    def _text_search_rows(
        self,
        scope: Scope,
        query_text: str,
        k: int,
    ) -> list[Mapping[str, object]]:
        assert self._table is not None
        if not query_text.strip():
            return []
        if self._fts_ok:
            try:
                return list(
                    self._table.search(query_text, query_type="fts")
                    .where(f"scope = '{_quote_sql(scope)}'", prefilter=True)
                    .limit(k)
                    .to_list()
                )
            except (AttributeError, NotImplementedError, TypeError, ValueError) as exc:
                self._fts_ok = False
                logger.debug("LanceDB FTS query unavailable; using lexical fallback: %s", exc)
        return self._lexical_text_search_rows(scope, query_text, k)

    def _lexical_text_search_rows(
        self,
        scope: Scope,
        query_text: str,
        k: int,
    ) -> list[Mapping[str, object]]:
        tokens = {token.lower() for token in re.findall(r"\w+", query_text)}
        if not tokens:
            return []
        rows = [
            row
            for row in self.rows()
            if str(row.get("scope", "")) == scope
            and tokens & {token.lower() for token in re.findall(r"\w+", str(row.get("text", "")))}
        ]
        return sorted(
            rows,
            key=lambda row: (
                -len(
                    tokens
                    & {token.lower() for token in re.findall(r"\w+", str(row.get("text", "")))}
                ),
                str(row["id"]),
            ),
        )[:k]

    def _rows_by_ids(self, ids: Sequence[str]) -> list[Mapping[str, object]]:
        if self._table is None or not ids:
            return []
        wanted = set(ids)
        return [row for row in self.rows() if str(row["id"]) in wanted]

    def _ensure_metadata(self) -> None:
        tables = self._table_names()
        row = {
            "key": "embedding",
            "embedder_model_id": self._embedder_model_id,
            "dimension": self._dimension,
        }
        if self._meta_table_name not in tables:
            self._db.create_table(self._meta_table_name, data=[row])
            return
        table = self._db.open_table(self._meta_table_name)
        rows = table.search().where("key = 'embedding'", prefilter=True).limit(1).to_list()
        if not rows:
            table.add([row])
            return
        stored = rows[0]
        stored_dim = int(stored["dimension"])
        stored_model = str(stored["embedder_model_id"])
        if stored_dim != self._dimension or stored_model != self._embedder_model_id:
            raise DimensionMismatchError(
                "Stored embedder metadata "
                f"({stored_model}, {stored_dim}) != "
                f"({self._embedder_model_id}, {self._dimension})"
            )

    def _assert_table_dimension(self) -> None:
        assert self._table is not None
        field = self._table.schema.field("vector")
        stored_dim = getattr(field.type, "list_size", None)
        if stored_dim is not None and stored_dim != self._dimension:
            raise DimensionMismatchError(
                f"Table dimension {stored_dim} != store dimension {self._dimension}"
            )

    def _build_fts_index(self) -> None:
        assert self._table is not None
        try:
            self._table.create_fts_index("text", use_tantivy=False, replace=True)
        except (TypeError, ValueError, NotImplementedError) as exc:
            self._fts_ok = False
            logger.warning("LanceDB native FTS unavailable; text index disabled: %s", exc)

    def _table_names(self) -> set[str]:
        response = self._db.list_tables()
        names = getattr(response, "tables", response)
        return {str(name) for name in names}

    def _schema(self) -> pa.Schema:
        return pa.schema(
            [
                pa.field("id", pa.string()),
                pa.field("vector", pa.list_(pa.float32(), self._dimension)),
                pa.field("text", pa.string()),
                pa.field("scope", pa.string()),
                pa.field("content_hash", pa.string()),
                pa.field("source_id", pa.string()),
                pa.field("document_id", pa.string()),
                pa.field("page", pa.int64()),
                pa.field("bbox", pa.list_(pa.float64(), 4)),
                pa.field("char_start", pa.int64()),
                pa.field("char_end", pa.int64()),
                pa.field("node_level", pa.int64()),
                pa.field("is_summary", pa.bool_()),
                pa.field("parent_chunk_id", pa.string()),
                pa.field("sensitivity", pa.string()),
                pa.field("category", pa.string()),
                pa.field("source_date", pa.string()),
            ]
        )


def _validate_scope(scope: str) -> None:
    if not _SCOPE_RE.fullmatch(scope):
        raise ValueError(f"Invalid scope (must match [\\w-]+): {scope!r}")


def _quote_sql(value: str) -> str:
    return value.replace("'", "''")


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return _required_int(value)


def _required_int(value: object) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str | bytes | bytearray):
        return int(value)
    if hasattr(value, "__int__"):
        return int(value)
    raise ValueError(f"Invalid integer value: {value!r}")


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _iso_or_none(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _parse_iso(value: object) -> datetime | None:
    if value is None or value == "":
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _sensitivity(value: object) -> str:
    if value == "general":
        return "general"
    return "sensitive"


def _optional_bbox(value: object) -> list[float] | None:
    if value is None:
        return None
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        items = [float(item) for item in value]
        if len(items) == 4:
            return items
    raise ValueError(f"Invalid bbox: {value!r}")


def _row_to_retrieved(row: Mapping[str, object], score: float) -> RetrievedChunk:
    raw_sens = row.get("sensitivity")
    sensitivity: Sensitivity = "general" if raw_sens == "general" else "sensitive"
    category = _optional_str(row.get("category"))
    source_date = _parse_iso(row.get("source_date"))
    return RetrievedChunk(
        chunk=Chunk(
            chunk_id=str(row["id"]),
            document_id=str(row.get("document_id", "")),
            text=str(row.get("text", "")),
            scope=str(row.get("scope", "")),
            sensitivity=sensitivity,
            category=category,
            source_date=source_date,
        ),
        score=score,
    )


def _score_from_row(row: Mapping[str, object], *, default: float) -> float:
    for key in ("_relevance_score", "_score", "score"):
        value = row.get(key)
        if value is not None:
            return float(cast(float | int | str, value))
    if "_distance" in row:
        return 1.0 - float(cast(float | int | str, row["_distance"]))
    return default
