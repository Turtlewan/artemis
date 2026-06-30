# v2-07 · Cognee memory backend (write + retrieve behind MemoryPort)

status: ready
slice: 2 (memory) — part 1: the runnable write→consolidate→retrieve loop
coder: codex
coder_effort: high
autonomy: L5

## Identity

First Slice-2 build: a `CogneeMemory` implementing the existing `MemoryPort` (write / retrieve /
consolidate / forget) on the **Cognee** engine (confirmed 2026-06-30 — `docs/findings/cognee-vs-graphiti-spike-2026-06-30.md`).
Cognee is an **optional dependency group** (keeps the core spine thin); its internal LLM defaults to a
**small/local model** (Ollama `qwen3:4b`) and embeddings to local Ollama, configurable via `MemoryConfig`.
Consolidation/decay (RAPTOR, supersession, MMR rerank) are LATER specs — this one proves the loop.
Design home: `docs/v2/architecture.md` §5 + §10 fork 1.

## Prerequisites

Slice 1 committed (`44eeda0`). `MemoryPort` already exists at `src/artemis/ports/memory.py` (frozen — conform to it).

## Files to change

| File | Op | What |
|---|---|---|
| `pyproject.toml` | modify | add optional dep group `memory = ["cognee>=1.2"]` + a mypy `ignore_missing_imports` override for `cognee.*` |
| `src/artemis/memory/__init__.py` | create | package exports |
| `src/artemis/memory/config.py` | create | `MemoryConfig` (model/embeddings/data-root, local-small defaults) |
| `src/artemis/memory/cognee_backend.py` | create | `CogneeMemory` implementing `MemoryPort`; cognee injected/lazy |
| `tests/memory/__init__.py` | create | package marker (mirror `tests/model/`) |
| `tests/memory/test_cognee_backend.py` | create | hermetic tests with a FAKE cognee module (no real cognee/Ollama) |

> Scope lock: do NOT modify `ports/memory.py` (frozen), `types.py` (reuse `MemoryItem`,
> `RetrievedContext`), `model/`, `spine/`, or `capabilities/`. Cognee must NOT become a core dependency —
> it stays in the `memory` group; nothing in `src/artemis/` outside `memory/` may import it.

## Exact changes

### 1. `pyproject.toml`
- Add a dependency group (keep core `dependencies` unchanged):
  ```toml
  [dependency-groups]
  dev = [...]                       # unchanged
  memory = ["cognee>=1.2"]
  ```
- Add a mypy override so core type-checking passes WITHOUT cognee installed:
  ```toml
  [[tool.mypy.overrides]]
  module = ["cognee.*"]
  ignore_missing_imports = true
  ```

### 2. `src/artemis/memory/config.py` (create)
```python
from pydantic import BaseModel, Field

class MemoryConfig(BaseModel):
    # Cognee's INTERNAL extraction/answer LLM — small/local by default (memory work is cheap;
    # the flagship model is for agent reasoning, not memory grunt-work).
    llm_provider: str = "ollama"
    llm_model: str = "qwen3:4b"
    llm_endpoint: str = "http://localhost:11434/v1"
    llm_api_key: str = "ollama"
    embedding_provider: str = "ollama"
    embedding_model: str = "qwen3-embedding:0.6b"
    embedding_endpoint: str = "http://localhost:11434/api/embed"
    embedding_dim: int = 1024
    embedding_tokenizer: str = "Qwen/Qwen3-Embedding-0.6B"  # HF tokenizer Cognee's Ollama path needs
    data_root: str | None = None          # None → Cognee default; else its DB/storage dir
    default_dataset: str = "artemis"
    # layer → dataset name (Cognee partitions by dataset); unmapped layers fall back to default_dataset
    layer_datasets: dict[str, str] = Field(default_factory=dict)
```

### 3. `src/artemis/memory/cognee_backend.py` (create)
`CogneeMemory` implements the `MemoryPort` protocol. **cognee is injected for testability** and
otherwise lazily imported, so the core suite never needs the real package:
```python
from __future__ import annotations
import os
from types import ModuleType
from collections.abc import Sequence
from artemis.memory.config import MemoryConfig
from artemis.types import MemoryItem, RetrievedContext

class CogneeMemory:  # implements MemoryPort
    def __init__(self, config: MemoryConfig | None = None, *, cognee_module: ModuleType | None = None) -> None:
        self._config = config or MemoryConfig()
        self._cognee = cognee_module      # None → resolved + configured on first use
        self._configured = cognee_module is not None

    def _engine(self) -> ModuleType:
        if self._cognee is None:
            self._apply_env()             # set LLM_*/EMBEDDING_*/DATA_ROOT/HUGGINGFACE_TOKENIZER + disable server defaults
            import cognee                 # lazy
            self._cognee = cognee
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
        cog = self._engine()
        await cog.add(item.content, dataset_name=self._dataset(item.layer))

    async def consolidate(self) -> None:
        await self._engine().cognify()

    async def retrieve(self, query: str, *, token_budget: int,
                       layers: Sequence[str] | None = None) -> RetrievedContext:
        cog = self._engine()
        from cognee import SearchType   # lazy, inside method
        raw = await cog.search(query_type=SearchType.GRAPH_COMPLETION, query_text=query)
        return _assemble(_as_items(raw, layers), token_budget)

    async def forget(self, *, max_age_days: int | None = None,
                     min_salience: float | None = None) -> None:
        # decay/forgetting policy is v2-09; explicit, not silent
        raise NotImplementedError("forget() lands in v2-09 (decay/supersession policy)")
```
- `_as_items(raw, layers)`: Cognee's `GRAPH_COMPLETION` returns a list of answer strings (or objects);
  coerce each to a `MemoryItem(content=str(x), layer="semantic")`. (Pure function — unit-tested.)
- `_assemble(items, token_budget)`: pure function — estimate tokens per item (`max(1, len(content)//4)`),
  greedily keep items until the budget would be exceeded, set `token_cost` = sum kept,
  `truncated` = (any dropped). Returns `RetrievedContext`. (Pure — unit-tested with no engine.)
- Keep `_as_items` / `_assemble` as module-level pure functions so tests need no cognee.

### 4. `src/artemis/memory/__init__.py` (create)
Export `CogneeMemory`, `MemoryConfig`.

## Acceptance criteria

1. **Budget assembly (pure, no engine):** `_assemble` of 3 items (~tokens 10/10/10) with
   `token_budget=22` keeps 2 items, `token_cost==20`, `truncated is True`; with a huge budget keeps all,
   `truncated is False`. → `uv run pytest tests/memory/test_cognee_backend.py -q`
2. **write routes by layer:** with a FAKE cognee module injected, `await mem.write(MemoryItem(content="x",
   layer="semantic"))` calls `fake.add("x", dataset_name="artemis")` (default); a configured
   `layer_datasets={"rules":"rules_ds"}` routes a rules item to `"rules_ds"`.
3. **consolidate → cognify:** `await mem.consolidate()` awaits `fake.cognify()` exactly once.
4. **retrieve → search + budget:** with a fake whose `search` returns `["alpha","beta"]`,
   `retrieve("q", token_budget=10000)` returns a `RetrievedContext` whose items' contents are
   `["alpha","beta"]`; a tiny budget truncates and sets `truncated True`. (Fake provides a `SearchType`.)
5. **forget is explicit:** `await mem.forget()` raises `NotImplementedError` (deferred, not silent).
6. **`CogneeMemory` satisfies `MemoryPort`:** an `isinstance(mem, MemoryPort)` check passes (runtime_checkable),
   or a mypy-level assignment `m: MemoryPort = CogneeMemory(...)` type-checks.
7. **Core stays clean + green:** `uv run mypy` passes WITHOUT cognee installed (the override handles the
   lazy import); `uv run pytest -q` all pass (prior 48 + new); `uv run ruff check/format` clean. **No module
   under `src/artemis/` outside `memory/` imports cognee** (grep check).

## Commands to run
```bash
uv run ruff format --check src tests
uv run ruff check src tests
uv run mypy
uv run pytest -q
```

## Post-build (host, not Codex) — real integration smoke
After the hermetic suite is green, the host runs a live smoke (cognee installed via `uv sync --group memory`,
Ollama up): write 3 short facts → `consolidate()` → `retrieve()` returns grounded content within budget.
This is NOT a committed test (needs Ollama + heavy deps); it validates the wiring end-to-end on the box.
