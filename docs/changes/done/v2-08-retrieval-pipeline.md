# v2-08 · Retrieval-heavy pipeline (rerank → MMR dedup → budget) over Cognee

status: ready
slice: 2 (memory) — part 2: the retrieval pipeline ("where the quality lives")
coder: codex
coder_effort: high
autonomy: L5

## Identity

Replace v2-07's `GRAPH_COMPLETION` (pre-composed answer) retrieval with the architecture's
**context-assembly pipeline**: fetch a WIDE set of raw candidate chunks from Cognee, then run OUR
engine-agnostic pipeline — **pluggable rerank → MMR dedup → hard token-budget cap** — producing the
high-signal `RetrievedContext` to inject. Pure, testable functions; MMR uses a **pluggable similarity
(lexical default)**. Design home: `docs/v2/architecture.md` §5 (retrieval-heavy pipeline).
DEFERRED to v2-09 (state explicitly, don't build): embedding-cosine MMR similarity, cross-encoder
rerank, summarize-overflow, RAPTOR summary tree, consolidation/decay.

## Prerequisites

v2-07 committed (`71402fd`). `CogneeMemory` + `MemoryConfig` exist in `src/artemis/memory/`.

## Files to change

| File | Op | What |
|---|---|---|
| `src/artemis/memory/pipeline.py` | create | `Reranker` protocol + pure `lexical_similarity`, `mmr_select`, `assemble` |
| `src/artemis/memory/cognee_backend.py` | modify | retrieve: wide raw-chunk fetch → pipeline; config-driven search type + wideN |
| `src/artemis/memory/config.py` | modify | add `retrieve_candidates: int = 20`, `mmr_lambda: float = 0.7`, `search_type: str = "CHUNKS"` |
| `src/artemis/memory/__init__.py` | modify | export the pipeline pieces |
| `tests/memory/test_pipeline.py` | create | rerank order · MMR drops near-dups · budget cap (pure, no engine) |
| `tests/memory/test_cognee_backend.py` | modify | retrieve wires wide-fetch → pipeline (fake cognee returns N candidates) |

> Scope lock: do NOT touch `ports/`, `types.py`, `model/`, `spine/`, `capabilities/`. Keep cognee
> lazy/injected (no top-level import). All new pipeline logic is pure + hermetically tested.

## Exact changes

### 1. `src/artemis/memory/pipeline.py` (create)
```python
from __future__ import annotations
import re
from collections.abc import Sequence
from typing import Protocol
from artemis.types import MemoryItem, RetrievedContext


class Reranker(Protocol):
    def __call__(self, query: str, items: Sequence[MemoryItem]) -> list[MemoryItem]:
        """Return items reordered most-relevant-first. Default impl preserves input order."""
        ...


def identity_reranker(query: str, items: Sequence[MemoryItem]) -> list[MemoryItem]:
    return list(items)


_WORD = re.compile(r"\w+")

def _tokens(text: str) -> set[str]:
    return {w.lower() for w in _WORD.findall(text)}

def lexical_similarity(a: str, b: str) -> float:
    """Jaccard token overlap in [0,1]. v2-09 swaps in embedding cosine behind this signature."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def mmr_select(items: Sequence[MemoryItem], *, k: int, mmr_lambda: float = 0.7,
               similarity=lexical_similarity) -> list[MemoryItem]:
    """Maximal Marginal Relevance: greedily pick items balancing input-rank (relevance proxy)
    against novelty vs already-selected. Input order = relevance order (rank 0 best)."""
    pool = list(items)
    selected: list[MemoryItem] = []
    while pool and len(selected) < k:
        best_i, best_score = 0, float("-inf")
        for i, cand in enumerate(pool):
            rel = 1.0 - (items.index(cand) / max(1, len(items)))  # rank-derived relevance proxy
            div = max((similarity(cand.content, s.content) for s in selected), default=0.0)
            score = mmr_lambda * rel - (1 - mmr_lambda) * div
            if score > best_score:
                best_i, best_score = i, score
        selected.append(pool.pop(best_i))
    return selected


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def assemble(items: Sequence[MemoryItem], *, token_budget: int) -> RetrievedContext:
    kept: list[MemoryItem] = []
    cost = 0
    truncated = False
    for it in items:
        c = estimate_tokens(it.content)
        if cost + c > token_budget:
            truncated = True
            continue
        kept.append(it)
        cost += c
    return RetrievedContext(items=kept, token_cost=cost, truncated=truncated)


def run_pipeline(query: str, candidates: Sequence[MemoryItem], *, token_budget: int,
                 mmr_lambda: float = 0.7, k: int = 20,
                 reranker: Reranker = identity_reranker) -> RetrievedContext:
    ranked = reranker(query, candidates)
    deduped = mmr_select(ranked, k=k, mmr_lambda=mmr_lambda)
    return assemble(deduped, token_budget=token_budget)
```
- Keep every function pure (no engine/network). `mmr_select`'s `items.index` is fine for the small
  candidate sets here; if a worker prefers, derive relevance from enumerate order without `index`
  (equivalent) — micro-choice, log it.

### 2. `config.py` (modify)
Add fields: `retrieve_candidates: int = 20` (wide-fetch N), `mmr_lambda: float = 0.7`,
`search_type: str = "CHUNKS"` (raw chunks for the pipeline; was GRAPH_COMPLETION in v2-07).

### 3. `cognee_backend.py` (modify `retrieve` only)
- Resolve the Cognee search type from `config.search_type` via `getattr(SearchType, config.search_type)`
  (default `CHUNKS`) — wide raw retrieval, not a composed answer.
- `raw = await search(query_type=<resolved>, query_text=query)` → `_as_items(raw, layers)` (unchanged
  coercion) gives the candidate list → `run_pipeline(query, candidates, token_budget=token_budget,
  mmr_lambda=config.mmr_lambda, k=config.retrieve_candidates)`.
- Default `reranker=identity_reranker` (cross-encoder is v2-09). Keep the rest of CogneeMemory unchanged.

### 4. `__init__.py` (modify)
Also export: `run_pipeline`, `mmr_select`, `lexical_similarity`, `Reranker`.

## Acceptance criteria

1. **MMR drops near-duplicates:** `mmr_select` over `["the cat sat on the mat", "the cat sat on the
   mat today", "stock prices fell sharply"]` with `k=2` returns the first and the *third* (the near-dup
   second is dropped in favor of novelty). → `uv run pytest tests/memory/test_pipeline.py -q`
2. **rerank order honored:** a reranker that reverses input → `run_pipeline` selects from the reversed
   order (assert the top item differs from identity's top).
3. **budget cap:** `assemble` of 3 ~10-token items at `token_budget=22` keeps 2, `truncated True`;
   huge budget keeps all, `truncated False`.
4. **lexical_similarity** is 1.0 for identical strings, 0.0 for disjoint, in (0,1) for partial overlap.
5. **retrieve wiring:** with a fake cognee whose `CHUNKS` search returns 5 candidates (2 near-dup),
   `retrieve("q", token_budget=10000)` returns a `RetrievedContext` with the dup collapsed and items
   in pipeline order. Fake exposes `SearchType.CHUNKS`.
6. **Green:** `uv run mypy` (strict, cognee not installed) + `uv run pytest -q` (prior 55 + new) +
   `uv run ruff check/format` all pass.

## Commands to run
```bash
uv run ruff format --check src tests
uv run ruff check src tests
uv run mypy
uv run pytest -q
```

## Post-build (host) — live smoke
cognee venv + Ollama: write 3 facts → consolidate → retrieve (now CHUNKS+pipeline) returns deduped
raw context within budget (not a single composed sentence). Confirms the search-type switch works live.
