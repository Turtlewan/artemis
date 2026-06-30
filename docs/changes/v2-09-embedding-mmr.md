# v2-09 · EmbeddingPort + Ollama embedder + embedding-cosine MMR

status: ready
slice: 2 (memory) — part 3 of 6: better dedup via real embeddings
coder: codex
coder_effort: high
autonomy: L5

## Identity

Replace MMR's lexical-Jaccard similarity with **embedding cosine** for stronger near-duplicate
detection. Introduces a reusable `EmbeddingPort` + an `OllamaEmbedder` (local, `httpx`), and wires
`CogneeMemory.retrieve` to embed the wide candidate set and run embedding-MMR (lexical stays as the
zero-dependency fallback when no embedder is configured). Design home: `docs/v2/architecture.md` §5.
First of the v2-09..12 anti-rot sequence (consolidation, forget/decay, summarize-overflow follow).

## Prerequisites

v2-08 committed (`4ffa9ba`). `memory/pipeline.py` has `mmr_select(items,*,k,mmr_lambda,similarity)`.
`httpx` is already a core dep (added in v2-06).

## Files to change

| File | Op | What |
|---|---|---|
| `src/artemis/ports/embedding.py` | create | `EmbeddingPort` protocol (`async embed(texts) -> list[list[float]]`) |
| `src/artemis/memory/embedder.py` | create | `OllamaEmbedder` (httpx → Ollama `/api/embed`), implements `EmbeddingPort` |
| `src/artemis/memory/pipeline.py` | modify | add pure `cosine_similarity` + `embedding_mmr_select(items, embeddings, *, k, mmr_lambda)` |
| `src/artemis/memory/cognee_backend.py` | modify | `retrieve`: if embedder set, embed candidates → embedding-MMR; else lexical MMR (unchanged path) |
| `src/artemis/memory/config.py` | modify | add `use_embedding_mmr: bool = True` |
| `src/artemis/memory/__init__.py` | modify | export `OllamaEmbedder`, `cosine_similarity`, `embedding_mmr_select` |
| `tests/memory/test_pipeline.py` | modify | cosine + embedding-MMR pure tests |
| `tests/memory/test_embedder.py` | create | OllamaEmbedder request/parse + error mapping (httpx mocked) |
| `tests/memory/test_cognee_backend.py` | modify | retrieve uses injected fake embedder → embedding-MMR path |

> Scope lock: do NOT touch `ports/memory.py`, `types.py`, `model/`, `spine/`, `capabilities/`. Keep
> cognee lazy/injected. EmbeddingPort goes in `ports/` (a real cross-cutting port, like ModelPort).

## Exact changes

### 1. `src/artemis/ports/embedding.py` (create)
```python
from __future__ import annotations
from collections.abc import Sequence
from typing import Protocol, runtime_checkable

@runtime_checkable
class EmbeddingPort(Protocol):
    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one embedding vector per input text, order-aligned."""
        ...
```

### 2. `src/artemis/memory/embedder.py` (create)
`OllamaEmbedder` implements `EmbeddingPort` via Ollama's native embed API:
```python
class OllamaEmbedder:
    def __init__(self, *, base_url="http://localhost:11434", model="qwen3-embedding:0.6b",
                 timeout=60.0, client: httpx.AsyncClient | None = None) -> None: ...
    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        # POST {base_url}/api/embed  {"model": model, "input": list(texts)}
        # parse resp.json()["embeddings"] -> list[list[float]]
        # httpx.ConnectError/ConnectTimeout -> reuse artemis.model.errors.ProviderUnavailableError("ollama_embed", ...)
        # (import the existing error type; do not invent a new taxonomy)
```
- Batch all texts in one request (`"input": [...]`). Support an injected `client` for tests.
- On connection failure raise `ProviderUnavailableError` (from `artemis.model.errors`) — consistent
  with the model layer's failover taxonomy.

### 3. `src/artemis/memory/pipeline.py` (modify — add, don't change existing)
```python
import math

def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)

def embedding_mmr_select(items: Sequence[MemoryItem], embeddings: Sequence[Sequence[float]],
                         *, k: int, mmr_lambda: float = 0.7) -> list[MemoryItem]:
    # same MMR loop as mmr_select but diversity = max cosine(emb[cand], emb[selected]);
    # relevance = 1 - input_rank/len. embeddings is order-aligned with items.
    ...
```
- Keep `mmr_select` (lexical) untouched as the fallback.

### 4. `cognee_backend.py` (modify `retrieve` + `__init__`)
- `__init__` gains `*, embedder: EmbeddingPort | None = None`.
- `retrieve`: after `_as_items` → candidates, if `self._embedder is not None and config.use_embedding_mmr`:
  `vecs = await self._embedder.embed([c.content for c in ranked]); deduped = embedding_mmr_select(ranked, vecs, k=..., mmr_lambda=...)`; else current lexical `run_pipeline`. Then `assemble(deduped, token_budget)`.
- Factor the rerank+assemble so both MMR paths share the budget step (keep `run_pipeline` for the lexical path).

### 5. `config.py` / `__init__.py` — add `use_embedding_mmr: bool = True`; export new symbols.

## Acceptance criteria

1. **cosine_similarity:** identical vectors → 1.0; orthogonal `[1,0]·[0,1]` → 0.0; mismatched length or
   zero vector → 0.0. → `uv run pytest tests/memory/test_pipeline.py -q`
2. **embedding_mmr_select drops near-dups by vector:** 3 items with embeddings where items 0 and 1 are
   near-identical vectors and item 2 is distant, `k=2` → returns items 0 and 2 (the vector-near-dup #1
   dropped). Order-aligned embeddings.
3. **OllamaEmbedder:** with a mocked httpx returning `{"embeddings":[[0.1,0.2],[0.3,0.4]]}`,
   `embed(["a","b"])` returns those two vectors; the POST body carried `model` + `input=["a","b"]`;
   `httpx.ConnectError` → `ProviderUnavailableError`. (No live call.)
4. **retrieve embedding path:** with an injected fake embedder + fake cognee CHUNKS of 4 candidates
   (2 vector-near-dup), `retrieve` collapses the dup via embedding-MMR (assert the dup is absent);
   with `embedder=None` it still works via lexical MMR (regression).
5. **EmbeddingPort satisfied:** `OllamaEmbedder` isinstance `EmbeddingPort` (runtime_checkable).
6. **Green:** `uv run mypy` (strict, cognee absent) + `uv run pytest -q` (prior 62 + new) +
   `uv run ruff check/format` all pass.

## Commands to run
```bash
uv run ruff format --check src tests
uv run ruff check src tests
uv run mypy
uv run pytest -q
```

## Post-build (host) — live smoke
cognee venv + Ollama: `CogneeMemory(config, embedder=OllamaEmbedder())` → write 3 facts (1 near-dup)
→ consolidate → retrieve returns the deduped set with clean text. Confirms real embeddings drive MMR.
