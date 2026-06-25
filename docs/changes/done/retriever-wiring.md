---
spec: retriever-wiring
status: ready
token_profile: balanced
autonomy_level: L2
depends_on: SENS-enforce-ragcompose, SENS-carry-M3b, M3-b, M3-c
---
<!-- Closes two carried composition gaps: ADR-029 `retrieve_fn=None` (gateway.py:236) and M3-c `agentic=` unwired.
     → why: docs/findings/retriever-wiring-decision.md (2026-06-25) -->

# Spec: retriever-wiring — wire AdaptiveRetriever + AgenticRetriever into compose_brain; spotlight retrieved chunks before the responder

**Identity:** Assembles the already-built retrieval stack inside `compose_brain`: `store_for(scope)` factory → `AdaptiveRetriever` → `retrieve_fn` + `Brain.agentic`. Adds spotlighting of retrieved external-origin chunks before they reach a responder. Dev-buildable with `FakeReranker`; real `QwenReranker` + LanceDB-at-scale = Mac-gated tail.

## Assumptions

- **SENS-enforce-ragcompose** complete: `compose_with_gate` accepts `retrieve_fn: Callable[[str], Awaitable[list[RetrievedChunk]]] | None`; `Brain.__init__` already accepts `retrieve_fn`, `agentic`, `enforcer`. → impact: Stop (no re-adds).
- **SENS-carry-M3b** complete: retrieved `RetrievedChunk.chunk.sensitivity` is populated (fail-closed `"sensitive"`). Spotlighting applies to ALL retrieved chunks regardless of tag (external origin, not owner-curated). → impact: Low.
- **M3-b** complete: `AdaptiveRetriever` lives at `artemis.retrieval.retriever` with ctor `(embedder, store_for, reranker, *, agentic_fn=, candidate_k=)` and `async def retrieve(query, scope, mode, k)`. Its `store_for` param is `Callable[[Scope], LanceDBVectorStore]` — the import is from `artemis.adapters.lancedb_store`, NOT `artemis.knowledge.vector_store` (the M0-d slice). → impact: Stop (wrong import = wrong store).
- **M3-c** complete: `AgenticRetriever` at `artemis.retrieval.agentic` with ctor `(retriever, model, *, max_hops, per_hop_k, max_total_chunks)` and `as_agentic_fn() -> AgenticRetrieveFn`. Internally spotlights chunks during its loop. → impact: Low.
- `LanceDBVectorStore` (production adapter) ctor: `(scope, settings, embedder_model_id, dimension, *, is_unlocked: Callable[[], bool])`. The `is_unlocked` callable must be bound at construction time; it raises `ScopeLockedError` if the scope is locked at that moment. → impact: **Stop** (see Ambiguity A1 below — store_for must only be called when the key_provider is available and the scope is unlocked).
- `key_provider` is only available inside the `if key_provider is not None:` block in `compose_brain`. The retriever wiring that depends on LanceDB must live inside that block. → impact: Stop (shapes the insertion point).
- Spotlighting of retrieved chunks: `untrusted.spotlight.spotlight(text) -> (nonce, wrapped)` wraps a single string. The `SPOTLIGHT_INSTRUCTION` constant carries the per-nonce system instruction. `agentic.py` has its own internal `_spotlight` — no duplication needed there. The gap is the non-agentic path: `Brain._rag_messages` concatenates `retrieved.chunk.text` raw. That method must spotlight each chunk before concatenation. → impact: Stop (this is the insertion point for spotlight on the standard RAG path).
- `recall_fn` / owner memory facts are trusted (owner-curated); no spotlight applied. → impact: Low.
- `FakeReranker` (at `artemis.adapters.reranker`) requires no network. It is the dev default; `QwenReranker` is Mac-gated. Toggle via a settings flag or a passed-in `reranker` param — the simplest mechanism is an injected `reranker` param on `compose_brain` (mirrors the existing `embedder` and `model` params). → impact: Low (see Ambiguity A2).
- Scope policy: retrieve across `OWNER_PRIVATE` + `GENERAL`. The enforcer partitions; retrieval is privacy-unaware. Both stores are constructed in `store_for`. → impact: Low.

## Ambiguities / Gaps for Human Review

**A1 — LanceDB store construction requires `is_unlocked` at call time, not a deferred factory.**
`LanceDBVectorStore.__init__` calls `is_unlocked()` immediately and raises `ScopeLockedError` if false. So `store_for(scope)` cannot be a lazy factory that defers to later — it must either (a) be called only once inside the `key_provider is not None` block (constructing both stores eagerly) and return them from a dict closure, or (b) pass `key_provider.is_owner_unlocked` as the `is_unlocked` callable and accept that a cold call outside the unlocked window raises. The decision record says "the same store ingestion writes to" — ingestion already gate-checks the key_provider. Recommend option (a): build two stores eagerly inside the block, then `store_for = {OWNER_PRIVATE: store_private, GENERAL: store_general}.get` or a closure. **Review needed: confirm this is safe — if `GENERAL` scope is always unlocked (no vault), construct it unconditionally outside the block.**

**A2 — FakeReranker toggle mechanism.**
`compose_brain` currently injects `embedder` and `model` via params. Adding `reranker: Reranker | None = None` (default `None` → pick based on settings/hardware) mirrors that pattern. Alternatively, key off `settings.slot == "dev"` to choose `FakeReranker`. The spec uses the injected param approach (simplest, testable). Confirm preference before build.

**A3 — `retrieve_fn` scope: single scope or multi-scope merge.**
`AdaptiveRetriever.retrieve(query, scope, mode, k)` retrieves for ONE scope per call. The decision record says "retrieve across owner-private + general". The `retrieve_fn = lambda q: retriever.retrieve(q, ...)` in the spec merges two calls and deduplicates by `chunk_id`. Confirm this is the right merge strategy, or whether the enforcer should receive them separately.

**A4 — `Brain._rag_messages` spotlight insertion.**
`_rag_messages` currently builds `f"- [{retrieved.chunk.chunk_id}] {retrieved.chunk.text}"` inline. To add `SPOTLIGHT_INSTRUCTION`, the method signature or the messages list must carry the nonce-keyed system block. Since multiple chunks each get their own nonce, the system block would accumulate per-chunk instructions — or a single nonce could wrap all chunks as one block. The `agentic.py` pattern uses per-chunk markers with a single preamble in the system message. Recommend: one nonce for the entire "Retrieved context" block, wrapping `"\n".join(all chunk texts)`, plus one `SPOTLIGHT_INSTRUCTION` formatted with that nonce prepended to the system message. **Review needed: confirm this is cleaner than per-chunk nonces.**

## Files to Change

| File | Operation |
|------|-----------|
| `src/artemis/gateway.py` | modify — wire retriever inside `compose_brain` |
| `src/artemis/brain.py` | modify — spotlight retrieved chunks in `_rag_messages` |
| `tests/test_retriever_wiring.py` | create — wiring smoke + spotlight tests |

## Exact Changes

### Task 1 — `compose_brain` retriever assembly (`src/artemis/gateway.py`)

Inside the `if key_provider is not None:` block (after the existing memory / `recall_fn` setup, before the closing `except Exception:`), add:

```python
from artemis.adapters.lancedb_store import LanceDBVectorStore as _LanceDBVectorStore
from artemis.adapters.reranker import FakeReranker, QwenReranker
from artemis.identity.scope import GENERAL
from artemis.retrieval.agentic import AgenticRetriever
from artemis.retrieval.retriever import AdaptiveRetriever

# Build one store per scope. GENERAL has no vault lock; OWNER_PRIVATE uses
# key_provider.is_owner_unlocked as the live lock check.
_store_owner = _LanceDBVectorStore(
    OWNER_PRIVATE,
    settings,
    settings.codex_model,
    settings.embedding_dimension,
    is_unlocked=key_provider.is_owner_unlocked,
)
_store_general = _LanceDBVectorStore(
    GENERAL,
    settings,
    settings.codex_model,
    settings.embedding_dimension,
    is_unlocked=lambda: True,
)
_stores: dict[str, _LanceDBVectorStore] = {
    OWNER_PRIVATE: _store_owner,
    GENERAL: _store_general,
}

def store_for(scope: str) -> _LanceDBVectorStore:
    store = _stores.get(scope)
    if store is None:
        raise ValueError(f"No store for scope: {scope!r}")
    return store

_reranker = reranker if reranker is not None else FakeReranker()
# Mac-gated tail: replace FakeReranker with QwenReranker(settings) on the Mac Mini
# when settings.slot == "prod" and the Qwen endpoint is available.

_retriever = AdaptiveRetriever(embedder, store_for, _reranker)
_agentic = AgenticRetriever(_retriever, model)

# retrieve_fn: merge owner-private + general, deduplicate by chunk_id.
# The ADR-029 enforcer partitions the merged list; retrieval is privacy-unaware.
async def retrieve_fn(query: str) -> list[RetrievedChunk]:
    import asyncio
    owner_chunks, general_chunks = await asyncio.gather(
        _retriever.retrieve(query, OWNER_PRIVATE),
        _retriever.retrieve(query, GENERAL),
    )
    seen: set[str] = set()
    merged: list[RetrievedChunk] = []
    for chunk in owner_chunks + general_chunks:
        if chunk.chunk.chunk_id not in seen:
            seen.add(chunk.chunk.chunk_id)
            merged.append(chunk)
    return merged

agentic = _agentic
```

Also add `reranker: Reranker | None = None` to the `compose_brain` signature:

```python
def compose_brain(
    settings: Settings | None = None,
    *,
    embedder: EmbeddingModel | None = None,
    model: ModelPort | None = None,
    key_provider: KeyProvider | None = None,
    reranker: Reranker | None = None,   # None → FakeReranker (dev); inject QwenReranker for prod/Mac
) -> Brain:
```

And wire into `Brain(...)`:

```python
return Brain(
    router,
    registry,
    model,
    ...
    agentic=agentic,          # was absent / None
    retrieve_fn=retrieve_fn,  # replaces the `retrieve_fn = None` stub at line 236
    ...
)
```

Add the `Reranker` import at the top of the file (TYPE_CHECKING block or direct):

```python
from artemis.ports.retrieval import Reranker
```

Remove or replace the comment at line 235–236:
```python
# retrieve_fn unwired — no AdaptiveRetriever composed in compose_brain (same gap as the M3-c agentic= flag); planning must compose the retriever.
retrieve_fn = None
```
Delete those two lines; `retrieve_fn` and `agentic` are now assigned inside the `key_provider` block above.

### Task 2 — Spotlight retrieved chunks in `Brain._rag_messages` (`src/artemis/brain.py`)

Current `_rag_messages` (lines ~388–410) builds the retrieved-context block as raw text. Replace the chunk-assembly section with a spotlighted block:

```python
def _rag_messages(
    self,
    request_text: str,
    chunks: tuple[RetrievedChunk, ...],
    facts: tuple[Fact, ...],
) -> list[Message]:
    from artemis.untrusted.spotlight import SPOTLIGHT_INSTRUCTION, spotlight

    blocks: list[str] = []
    system_parts: list[str] = []

    if chunks:
        raw_block = "\n".join(
            f"[{r.chunk.chunk_id}] {r.chunk.text}" for r in chunks
        )
        nonce, spotlighted = spotlight(raw_block)
        system_parts.append(SPOTLIGHT_INSTRUCTION.format(nonce=nonce))
        blocks.append("Retrieved context:\n" + spotlighted)

    fact_block = render_inject_block(facts)
    if fact_block:
        blocks.append(fact_block)  # trusted — no spotlight

    if not blocks:
        return [Message(role="user", content=request_text)]

    system_content = "\n\n".join(filter(None, ["\n\n".join(system_parts)] + ([] if not system_parts else [])))
    # Simpler: prepend the spotlight instruction to the system block
    combined_system = ("\n\n".join(system_parts) + "\n\n" if system_parts else "") + "\n\n".join(blocks)
    return [
        Message(role="system", content=combined_system),
        Message(role="user", content=request_text),
    ]
```

Note: the current implementation puts both the context blocks AND the system instruction into `role="system"`. The spotlight instruction + content belong together there. Keep `facts` as-is (no spotlight — trusted owner memory). **See Ambiguity A4 for the nonce strategy choice.**

### Task 3 — Tests (`tests/test_retriever_wiring.py`)

Create typed pytest tests (async under the project async convention):

- **`test_compose_brain_no_key_provider`**: `compose_brain()` (no `key_provider`) → `Brain` with `retrieve_fn is None` and `agentic is None`. No regression on the offline path.
- **`test_compose_brain_with_key_provider_wires_retriever`**: use a `FakeKeyProvider` (already in the test suite or create a minimal stub) with `is_owner_unlocked=True`; `compose_brain(key_provider=fake_kp)` → `brain._retrieve_fn is not None` and `brain.agentic is not None`.
- **`test_retrieve_fn_merges_scopes`**: build an `AdaptiveRetriever` with a `FakeReranker` and two in-memory stores pre-populated with one chunk each in `owner-private` and `general`. Call `retrieve_fn("test query")` → both chunks appear in the merged list, no duplicates.
- **`test_retrieve_fn_deduplicates`**: inject the same `chunk_id` in both stores → merged list contains it once.
- **`test_rag_messages_spotlights_chunks`**: construct a `Brain` with a minimal fake model; call `_rag_messages("q", chunks=(one_chunk,), facts=())` → the returned `Message[role=system].content` contains `<<UNTRUSTED:` and `<</UNTRUSTED:` markers and the `SPOTLIGHT_INSTRUCTION` preamble.
- **`test_rag_messages_facts_not_spotlighted`**: facts block rendered by `render_inject_block` appears WITHOUT `<<UNTRUSTED:` markers.
- **`test_fake_reranker_default`** (dev gate): `compose_brain(reranker=None, key_provider=fake_kp)` builds without error (no QwenReranker network call).

## Acceptance Criteria

- [ ] `uv run mypy src` → exit 0 (full project, not file-scoped).
- [ ] `uv run pytest -q` → exit 0, all existing tests green + new tests pass.
- [ ] `uv run python -c "from artemis.gateway import compose_brain; b = compose_brain(); print('no-kp ok')"` → prints `no-kp ok` (no LanceDB import errors offline).
- [ ] (Mac-gated) `compose_brain(key_provider=<real_kp>, reranker=QwenReranker(settings))` with both LanceDB stores on-disk → `retrieve_fn("test")` returns chunks from the live stores.

## Commands to Run

```
uv run mypy src
uv run pytest -q tests/test_retriever_wiring.py
uv run pytest -q   # full suite regression
```

## Mac-Gated Tail

The following are confirmed dev-unbuildable and must be deferred to the Mac Mini:

- `QwenReranker` (requires the local Qwen3 endpoint at `roles.toml reranker`).
- LanceDB at scale (large on-disk store, APFS encrypted vault mount).
- Task 3 GATED acceptance criterion (end-to-end retrieval with real stores).

The wiring, `FakeReranker`, and all unit tests are dev-buildable on the 8GB Windows box now.
