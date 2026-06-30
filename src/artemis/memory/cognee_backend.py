"""Cognee-backed memory implementation."""

from __future__ import annotations

import importlib
import os
from collections.abc import Awaitable, Sequence
from types import ModuleType
from typing import Protocol, cast

from artemis.memory.config import MemoryConfig
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
    ) -> None:
        self._config = config or MemoryConfig()
        self._cognee = cognee_module
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
        add = cast(_CogneeAdd, getattr(self._engine(), "add"))
        await add(item.content, dataset_name=self._dataset(item.layer))

    async def retrieve(
        self,
        query: str,
        *,
        token_budget: int,
        layers: Sequence[str] | None = None,
    ) -> RetrievedContext:
        cog = self._engine()
        search_type = getattr(cog, "SearchType")
        graph_completion = getattr(search_type, "GRAPH_COMPLETION")
        search = cast(_CogneeSearch, getattr(cog, "search"))
        raw = await search(query_type=graph_completion, query_text=query)
        return _assemble(_as_items(raw, layers), token_budget)

    async def consolidate(self) -> None:
        cognify = cast(_CogneeCognify, getattr(self._engine(), "cognify"))
        await cognify()

    async def forget(
        self,
        *,
        max_age_days: int | None = None,
        min_salience: float | None = None,
    ) -> None:
        raise NotImplementedError("forget() lands in v2-09 (decay/supersession policy)")


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
    return [MemoryItem(content=str(value), layer="semantic") for value in values]


def _assemble(items: Sequence[MemoryItem], token_budget: int) -> RetrievedContext:
    kept: list[MemoryItem] = []
    token_cost = 0
    truncated = False

    for item in items:
        item_cost = max(1, len(item.content) // 4)
        if token_cost + item_cost > token_budget:
            truncated = True
            continue
        kept.append(item)
        token_cost += item_cost

    return RetrievedContext(items=kept, token_cost=token_cost, truncated=truncated)
