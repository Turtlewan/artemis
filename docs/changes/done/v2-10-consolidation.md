# v2-10 · Consolidation / latest-wins (ADD/UPDATE/DELETE/NOOP on write)

status: ready
slice: 2 (memory) — part 4 of 6: consolidating write (never blind-append)
coder: codex
coder_effort: high
autonomy: L5

## Identity

Make `write()` **consolidating** (Mem0-style): before storing, compare the new fact against similar
existing memories and classify the operation — ADD (new), UPDATE (supersedes an existing fact),
DELETE (negates one), or NOOP (redundant). The decision is made by a small LLM through our own
`ModelPort` (dogfoods the subscription-first router). UPDATE/DELETE record a **supersession** that
`retrieve` filters out (latest-wins). Design home: `docs/v2/architecture.md` §5 ("permissive write but
CONSOLIDATE; update/supersede not append; temporal validity latest-wins").
DEFERRED (explicit): persisting the supersession set across restarts, hard-deleting superseded nodes
from Cognee, multi-fact merges. forget()/decay = v2-11; summarize-overflow = v2-12.

## Prerequisites

v2-09 committed (`1228190`). `ModelPort` at `src/artemis/ports/model.py` (reuse; do NOT import the heavy
`artemis.model` package — import the port only). `CogneeMemory` already supports an injected embedder.

## Files to change

| File | Op | What |
|---|---|---|
| `src/artemis/memory/consolidation.py` | create | `ConsolidationDecision` + schema + `Consolidator` protocol + `LLMConsolidator` |
| `src/artemis/memory/cognee_backend.py` | modify | `write` consolidates when a consolidator is set; `_superseded` set; `retrieve` filters it |
| `src/artemis/memory/config.py` | modify | add `consolidate_on_write: bool = False`, `consolidation_similar_k: int = 5` |
| `src/artemis/memory/__init__.py` | modify | export `LLMConsolidator`, `ConsolidationDecision`, `Consolidator` |
| `tests/memory/test_consolidation.py` | create | decision parse + each-op application (mock ModelPort + mock cognee) |
| `tests/memory/test_cognee_backend.py` | modify | write applies ADD/NOOP/UPDATE/DELETE; retrieve filters superseded |

> Scope lock: do NOT touch `ports/`, `types.py`, `model/` (import only `artemis.ports.model.ModelPort`),
> `spine/`, `capabilities/`. Keep cognee lazy/injected. Default `consolidate_on_write=False` (opt-in —
> consolidation adds an LLM call per write; the plain write path must stay unchanged when off).

## Exact changes

### 1. `src/artemis/memory/consolidation.py` (create)
```python
from __future__ import annotations
from collections.abc import Sequence
from typing import Literal, Protocol
from pydantic import BaseModel
from artemis.ports.model import ModelPort       # port only — no provider import
from artemis.types import MemoryItem, Message

ConsolidationOp = Literal["ADD", "UPDATE", "DELETE", "NOOP"]

class ConsolidationDecision(BaseModel):
    op: ConsolidationOp
    target: str | None = None     # content of the existing fact an UPDATE/DELETE supersedes
    reason: str = ""

CONSOLIDATION_SCHEMA: dict = {   # canonical schema for ModelPort.complete
    "type": "object",
    "properties": {
        "op": {"type": "string", "enum": ["ADD", "UPDATE", "DELETE", "NOOP"]},
        "target": {"type": ["string", "null"]},
        "reason": {"type": "string"},
    },
    "required": ["op", "target", "reason"],
}

class Consolidator(Protocol):
    async def classify(self, new: str, existing: Sequence[str]) -> ConsolidationDecision: ...

class LLMConsolidator:
    def __init__(self, model: ModelPort, *, model_id: str | None = None) -> None:
        self._model = model
        self._model_id = model_id

    async def classify(self, new: str, existing: Sequence[str]) -> ConsolidationDecision:
        if not existing:
            return ConsolidationDecision(op="ADD", reason="no existing memory")
        listing = "\n".join(f"- {e}" for e in existing)
        sys = ("You maintain a memory store. Decide how a NEW fact relates to EXISTING facts. "
               "ADD = genuinely new; UPDATE = supersedes/refines one existing fact (set target to that "
               "fact verbatim); DELETE = negates one existing fact (set target); NOOP = already known. "
               "Return only the JSON.")
        resp = await self._model.complete(
            messages=[Message(role="system", content=sys),
                      Message(role="user", content=f"NEW:\n{new}\n\nEXISTING:\n{listing}")],
            response_schema=CONSOLIDATION_SCHEMA, model=self._model_id)
        data = resp.structured or {"op": "ADD", "target": None, "reason": "fallback"}
        return ConsolidationDecision.model_validate(data)
```

### 2. `cognee_backend.py` (modify)
- `__init__` gains `*, consolidator: Consolidator | None = None`; init `self._superseded: set[str] = set()`.
- `write`:
  ```python
  if self._consolidator is not None and self._config.consolidate_on_write:
      existing = [i.content for i in (await self._similar(item.content)).items]
      decision = await self._consolidator.classify(item.content, existing)
      if decision.op == "NOOP":
          return
      if decision.op in ("UPDATE", "DELETE") and decision.target:
          self._superseded.add(decision.target)
      if decision.op != "DELETE":
          await self._add(item)        # the existing add path
  else:
      await self._add(item)            # unchanged plain write
  ```
  Factor the existing `cognee.add(...)` into `_add(item)`. Add `_similar(content)` = retrieve over the
  current store with `token_budget` large enough and `k=consolidation_similar_k` (reuse retrieve logic;
  may simply call `self.retrieve(content, token_budget=10_000, layers=[item.layer])` — superseded
  filtering inside retrieve is fine here).
- `retrieve`: after building `candidates` (post `_as_items`), drop any whose `content in self._superseded`
  BEFORE rerank/MMR. (One-line filter.)

### 3. `config.py` / `__init__.py` — add the two config fields + exports.

## Acceptance criteria

1. **Decision parse:** with a fake `ModelPort` whose `complete` returns `structured={"op":"UPDATE",
   "target":"Ben works at Acme","reason":"job changed"}`, `LLMConsolidator.classify("Ben works at
   Globex", ["Ben works at Acme"])` returns that decision; **empty existing → ADD without calling the
   model**. → `uv run pytest tests/memory/test_consolidation.py -q`
2. **write applies ops (mock cognee + mock consolidator, consolidate_on_write=True):**
   - NOOP → `cognee.add` NOT called.
   - ADD → `add` called once with the new content.
   - UPDATE → `add` called with new content AND `target` recorded in `_superseded`.
   - DELETE → `add` NOT called AND `target` recorded in `_superseded`.
3. **retrieve filters superseded:** with `_superseded={"old fact"}` and fake CHUNKS returning
   `["old fact","new fact"]`, retrieve returns only `"new fact"`.
4. **consolidate_on_write=False (default):** write calls `add` directly, never invokes the consolidator
   (regression — plain path unchanged).
5. **Green:** `uv run mypy` (strict, cognee absent) + `uv run pytest -q` (prior 68 + new) +
   `uv run ruff check/format` all pass.

## Commands to run
```bash
uv run ruff format --check src tests
uv run ruff check src tests
uv run mypy
uv run pytest -q
```

## Post-build (host) — live smoke
cognee venv + Ollama + a real ModelPort (use the Codex proxy or an Ollama-backed model): write "Ben
works at Acme" → consolidate → write "Ben now works at Globex" with `consolidate_on_write=True` →
retrieve "where does Ben work" returns Globex, not Acme (latest-wins).
