# v2-12 · Summarize-overflow (compress truncated context, don't drop it)

status: ready
slice: 2 (memory) — part 6 of 6: "inject; summarize the overflow"
coder: codex
coder_effort: high
autonomy: L5

## Identity

Complete the retrieval pipeline's final stage: when the token budget would truncate retrieved items,
**summarize the overflow into one synthesis item** (within a reserved slice of the budget) instead of
silently dropping it. Pluggable `Summarizer` (default: none → current truncation behavior); an
`LLMSummarizer` uses our own `ModelPort` (small model). Last of the v2-09..12 anti-rot sequence —
finishes Slice 2's memory pipeline. Design home: `docs/v2/architecture.md` §5 ("HARD token-budget cap
→ inject; summarize the overflow").

## Prerequisites

v2-11 committed (`dabd2e6`). `pipeline.assemble` + `estimate_tokens` exist; `consolidation.py` shows
the `ModelPort`-via-ports import pattern to mirror.

## Files to change

| File | Op | What |
|---|---|---|
| `src/artemis/memory/pipeline.py` | modify | add pure `split_for_budget(items, *, token_budget) -> (kept, overflow, kept_cost)` |
| `src/artemis/memory/summarize.py` | create | `Summarizer` protocol + `LLMSummarizer` (via `ports.model`) |
| `src/artemis/memory/cognee_backend.py` | modify | `retrieve`: when summarizer set + overflow, append a synthesis item within reserve |
| `src/artemis/memory/config.py` | modify | add `summarize_overflow: bool = False`, `overflow_reserve_tokens: int = 256` |
| `src/artemis/memory/__init__.py` | modify | export `Summarizer`, `LLMSummarizer`, `split_for_budget` |
| `tests/memory/test_pipeline.py` | modify | `split_for_budget` pure tests |
| `tests/memory/test_summarize.py` | create | `LLMSummarizer` prompt/parse (mock ModelPort) |
| `tests/memory/test_cognee_backend.py` | modify | retrieve summarizes overflow into one item (mock summarizer); off → truncates as before |

> Scope lock: do NOT touch `ports/`, `types.py`, `model/` (import only `artemis.ports.model.ModelPort`),
> `spine/`, `capabilities/`. Keep cognee lazy/injected. Default `summarize_overflow=False` (opt-in —
> adds an LLM call only when truncation actually happens; the plain truncation path stays unchanged).

## Exact changes

### 1. `pipeline.py` (modify — add)
```python
def split_for_budget(items: Sequence[MemoryItem], *, token_budget: int
                     ) -> tuple[list[MemoryItem], list[MemoryItem], int]:
    """Greedy fill to budget. Returns (kept, overflow, kept_token_cost). Mirrors assemble()'s
    accounting but exposes the dropped items so callers can summarize them."""
    kept: list[MemoryItem] = []
    overflow: list[MemoryItem] = []
    cost = 0
    for item in items:
        c = estimate_tokens(item.content)
        if cost + c > token_budget:
            overflow.append(item)
            continue
        kept.append(item)
        cost += c
    return kept, overflow, cost
```

### 2. `src/artemis/memory/summarize.py` (create)
```python
from __future__ import annotations
from collections.abc import Sequence
from typing import Protocol
from artemis.ports.model import ModelPort
from artemis.types import MemoryItem, Message

class Summarizer(Protocol):
    async def summarize(self, items: Sequence[MemoryItem], *, query: str) -> str: ...

class LLMSummarizer:
    def __init__(self, model: ModelPort, *, model_id: str | None = None) -> None:
        self._model = model
        self._model_id = model_id

    async def summarize(self, items: Sequence[MemoryItem], *, query: str) -> str:
        bullets = "\n".join(f"- {i.content}" for i in items)
        sys = ("Compress the memory items into a few dense sentences, keeping only what is relevant "
               "to the user's query. No preamble.")
        resp = await self._model.complete(
            messages=[Message(role="system", content=sys),
                      Message(role="user", content=f"Query: {query}\n\nItems:\n{bullets}")],
            model=self._model_id)
        return resp.text.strip()
```

### 3. `cognee_backend.py` (modify `retrieve` + `__init__`)
- `__init__` gains `*, summarizer: Summarizer | None = None`.
- In `retrieve`, replace the final `assemble(deduped, token_budget=token_budget)` (BOTH the embedding
  path and the lexical `run_pipeline` path — refactor so both share one finalize step) with:
  ```python
  result = await self._finalize(query, deduped, token_budget)
  self._touch_retrieved(result); return result
  ```
  where `deduped` for the lexical path = `mmr_select(ranked, k=..., mmr_lambda=...)` (extract from
  run_pipeline so both paths produce a `deduped` list, then finalize identically).
- `_finalize`:
  ```python
  async def _finalize(self, query, deduped, token_budget) -> RetrievedContext:
      if self._summarizer is None or not self._config.summarize_overflow:
          return assemble(deduped, token_budget=token_budget)
      reserve = self._config.overflow_reserve_tokens
      kept, overflow, cost = split_for_budget(deduped, token_budget=max(0, token_budget - reserve))
      if not overflow:
          return assemble(deduped, token_budget=token_budget)   # nothing dropped → no summary
      summary_text = await self._summarizer.summarize(overflow, query=query)
      summary = MemoryItem(content=summary_text, layer="working", metadata={"overflow_summary": True})
      tail = assemble([summary], token_budget=reserve)          # fit summary within the reserve
      return RetrievedContext(items=[*kept, *tail.items], token_cost=cost + tail.token_cost,
                              truncated=True)
  ```

### 4. `config.py` / `__init__.py` — add the two fields + exports.

## Acceptance criteria

1. **split_for_budget (pure):** 3 ~10-token items, `token_budget=22` → kept 2, overflow 1, kept_cost 20;
   huge budget → all kept, empty overflow. → `uv run pytest tests/memory/test_pipeline.py -q`
2. **LLMSummarizer:** with a fake `ModelPort` whose `complete` returns `text="merged summary"`,
   `summarize([items], query="q")` returns `"merged summary"`; the user message lists the item contents.
3. **retrieve summarizes overflow:** with `summarize_overflow=True`, a mock summarizer returning
   `"SUMMARY"`, embedder off, and CHUNKS returning items that exceed a small `token_budget`, retrieve
   returns the kept items PLUS a final item `content="SUMMARY"` with `metadata["overflow_summary"]
   is True`, and `truncated is True`.
4. **no overflow → no summary call:** when everything fits, the summarizer is NOT awaited and output
   equals the plain `assemble` result.
5. **summarize_overflow=False (default):** retrieve truncates exactly as v2-11 (regression — existing
   truncation tests still pass, summarizer never called).
6. **Green:** `uv run mypy` (strict, cognee absent) + `uv run pytest -q` (prior 85 + new) +
   `uv run ruff check/format` all pass.

## Commands to run
```bash
uv run ruff format --check src tests
uv run ruff check src tests
uv run mypy
uv run pytest -q
```

## Post-build (host) — live smoke (optional)
cognee venv + Ollama ModelPort: write ~6 facts → consolidate → retrieve with a tiny token_budget +
`summarize_overflow=True` → result ends with one synthesis item compressing the overflow.
