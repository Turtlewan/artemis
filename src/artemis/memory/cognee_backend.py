"""Cognee-backed memory implementation."""

from __future__ import annotations

import importlib
import os
from collections.abc import Awaitable, Sequence
from types import ModuleType
from typing import Protocol, cast

from artemis.memory.consolidation import Consolidator
from artemis.memory.config import MemoryConfig
from artemis.memory.pipeline import (
    assemble,
    embedding_mmr_select,
    identity_reranker,
    run_pipeline,
)
from artemis.memory.ledger import MemoryLedger
from artemis.ports.embedding import EmbeddingPort
from artemis.types import MemoryItem, RetrievedContext


class _CogneeAdd(Protocol):
    def __call__(self, content: str, *, dataset_name: str) -> Awaitable[object]: ...


class _CogneeCognify(Protocol):
    def __call__(self) -> Awaitable[object]: ...


class _CogneeSearch(Protocol):
    def __call__(self, *, query_type: object, query_text: str) -> Awaitable[object]: ...


class CogneeMemory:
    """MemoryPort implementation backed by Cognee."""

    def __init__(
        self,
        config: MemoryConfig | None = None,
        *,
        cognee_module: ModuleType | None = None,
        embedder: EmbeddingPort | None = None,
        consolidator: Consolidator | None = None,
        ledger: MemoryLedger | None = None,
    ) -> None:
        self._config = config or MemoryConfig()
        self._cognee = cognee_module
        self._embedder = embedder
        self._consolidator = consolidator
        self._ledger = ledger
        self._superseded: set[str] = set()
        self._configured = cognee_module is not None

    def _engine(self) -> ModuleType:
        if self._cognee is None:
            self._apply_env()
            self._cognee = importlib.import_module("cognee")
            self._configured = True
        return self._cognee

    def _apply_env(self) -> None:
        c = self._config
        os.environ.setdefault("LLM_PROVIDER", c.llm_provider)
        os.environ.setdefault("LLM_MODEL", c.llm_model)
        os.environ.setdefault("LLM_ENDPOINT", c.llm_endpoint)
        os.environ.setdefault("LLM_API_KEY", c.llm_api_key)
        os.environ.setdefault("EMBEDDING_PROVIDER", c.embedding_provider)
        os.environ.setdefault("EMBEDDING_MODEL", c.embedding_model)
        os.environ.setdefault("EMBEDDING_ENDPOINT", c.embedding_endpoint)
        os.environ.setdefault("EMBEDDING_DIMENSIONS", str(c.embedding_dim))
        os.environ.setdefault("HUGGINGFACE_TOKENIZER", c.embedding_tokenizer)
        os.environ.setdefault("ENABLE_BACKEND_ACCESS_CONTROL", "false")
        os.environ.setdefault("CACHING", "false")
        if c.data_root:
            os.environ.setdefault("DATA_ROOT_DIRECTORY", c.data_root)

    def _dataset(self, layer: str) -> str:
        return self._config.layer_datasets.get(layer, self._config.default_dataset)

    async def write(self, item: MemoryItem) -> None:
        if self._consolidator is not None and self._config.consolidate_on_write:
            existing = [
                existing_item.content
                for existing_item in (await self._similar(item.content, item.layer)).items
            ]
            decision = await self._consolidator.classify(item.content, existing)
            if decision.op == "NOOP":
                return
            if decision.op in ("UPDATE", "DELETE") and decision.target:
                self._superseded.add(_normalize_fact(decision.target))
            if decision.op != "DELETE":
                await self._add(item)
            return
        await self._add(item)

    async def _add(self, item: MemoryItem) -> None:
        add = cast(_CogneeAdd, getattr(self._engine(), "add"))
        await add(item.content, dataset_name=self._dataset(item.layer))
        if self._ledger is not None:
            self._ledger.record(
                _normalize_fact(item.content),
                salience=self._config.default_salience,
            )

    async def _similar(self, content: str, layer: str) -> RetrievedContext:
        # Best-effort: the store may be empty/uninitialized (no add+cognify yet) or transiently
        # unreachable. A failed similar-lookup degrades consolidation to ADD (correct for an empty
        # store), never blocks the write.
        try:
            context = await self.retrieve(content, token_budget=10_000, layers=[layer])
        except Exception:  # noqa: BLE001 - consolidation pre-lookup is best-effort
            return RetrievedContext(items=[], token_cost=0, truncated=False)
        return RetrievedContext(
            items=context.items[: self._config.consolidation_similar_k],
            token_cost=context.token_cost,
            truncated=context.truncated,
        )

    async def retrieve(
        self,
        query: str,
        *,
        token_budget: int,
        layers: Sequence[str] | None = None,
    ) -> RetrievedContext:
        cog = self._engine()
        search_type = getattr(cog, "SearchType")
        query_type = getattr(search_type, self._config.search_type, None)
        if query_type is None:
            query_type = getattr(search_type, "CHUNKS")
        search = cast(_CogneeSearch, getattr(cog, "search"))
        raw = await search(query_type=query_type, query_text=query)
        candidates = _as_items(raw, layers)
        archived = self._ledger.archived_keys() if self._ledger is not None else set()
        candidates = [
            candidate
            for candidate in candidates
            if _normalize_fact(candidate.content) not in self._superseded
            and _normalize_fact(candidate.content) not in archived
        ]
        ranked = identity_reranker(query, candidates)
        if self._embedder is not None and self._config.use_embedding_mmr:
            vecs = await self._embedder.embed([candidate.content for candidate in ranked])
            deduped = embedding_mmr_select(
                ranked,
                vecs,
                k=self._config.retrieve_candidates,
                mmr_lambda=self._config.mmr_lambda,
            )
            result = assemble(deduped, token_budget=token_budget)
            self._touch_retrieved(result)
            return result
        result = run_pipeline(
            query,
            candidates,
            token_budget=token_budget,
            mmr_lambda=self._config.mmr_lambda,
            k=self._config.retrieve_candidates,
            reranker=identity_reranker,
        )
        self._touch_retrieved(result)
        return result

    def _touch_retrieved(self, context: RetrievedContext) -> None:
        if self._ledger is not None:
            self._ledger.touch([_normalize_fact(item.content) for item in context.items])

    async def consolidate(self) -> None:
        cognify = cast(_CogneeCognify, getattr(self._engine(), "cognify"))
        await cognify()

    async def forget(
        self,
        *,
        max_age_days: int | None = None,
        min_salience: float | None = None,
    ) -> None:
        if self._ledger is None:
            raise RuntimeError("forget() requires a MemoryLedger; none configured")
        self._ledger.decay(max_age_days=max_age_days, min_salience=min_salience)


def _normalize_fact(text: str) -> str:
    """Normalize a fact for supersession matching — tolerates LLM verbatim drift
    (case, surrounding whitespace, trailing punctuation). Paraphrase-level matching is a
    future upgrade (embedding similarity); this handles the common punctuation/case drift."""
    return text.strip().casefold().rstrip(".!?;:, ")


_TEXT_KEYS = ("text", "content", "name", "description")


def _extract_text(value: object) -> str:
    """Pull clean text from a Cognee result element.

    SearchType.CHUNKS/SUMMARIES return node dicts whose chunk text lives under "text"
    (verified against Cognee 1.2.2); GRAPH_COMPLETION returns plain strings. Fall back to
    str() only when no known text field is present, so context is never a serialized node dict.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in _TEXT_KEYS:
            field = value.get(key)
            if isinstance(field, str) and field:
                return field
        return str(value)
    for attr in _TEXT_KEYS:
        field = getattr(value, attr, None)
        if isinstance(field, str) and field:
            return field
    return str(value)


def _as_items(raw: object, layers: Sequence[str] | None) -> list[MemoryItem]:
    if layers is not None and "semantic" not in layers:
        return []
    if raw is None:
        return []
    if isinstance(raw, str):
        values: list[object] = [raw]
    elif isinstance(raw, Sequence):
        values = list(raw)
    else:
        values = [raw]
    return [MemoryItem(content=_extract_text(value), layer="semantic") for value in values]
