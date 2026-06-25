# Retriever wiring (Item 2) — decision record

_Decided 2026-06-25 (planning, owner-led). Closes two carried composition flags: ADR-029 `retrieve_fn=None` and M3-c `agentic=` unwired. The retrieval stack is built but never assembled in `compose_brain` — this connects it._

## Problem
`compose_brain` composes no `AdaptiveRetriever`, so:
- `retrieve_fn = None` (`gateway.py:236`) → the ADR-029 enforcer gates an empty retrieved-context set; ingested knowledge never reaches the responder.
- `Brain.agentic = None` → the M3-c multi-hop search→read→refine→synthesise path is dead.

All parts already exist: `AdaptiveRetriever` (`retrieval/retriever.py`), `AgenticRetriever` (`retrieval/agentic.py`), `LanceDBVectorStore` (`knowledge/vector_store.py`), `QwenReranker` + `FakeReranker` (`adapters/reranker.py`). Nobody assembled them.

## Decision: wire BOTH wires (owner, 2026-06-25)
1. **`retrieve_fn`** — assemble `AdaptiveRetriever(embedder, store_for, reranker)`; set `retrieve_fn = lambda q: retriever.retrieve(q, ...)`. Turns on knowledge-grounded answers + gives the enforcer real context to gate.
2. **`agentic`** — set `Brain.agentic = AgenticRetriever(retriever, ...)`. Closes the M3-c flag.

## Settled defaults
- **Reranker:** `FakeReranker` on the dev box (8GB), real `QwenReranker` gated to the Mac (dev-machine-first lens). Wiring + tests build now behind the fake.
- **Scope policy:** retrieve **broadly** across `owner-private` + `general`; hand all to the wall. The ADR-029 enforcer partitions (sensitive→local-only, general→cloud-safe). Retrieval stays privacy-unaware by design; the wall is the single filter.
- **`store_for(scope)`** → `LanceDBVectorStore(scope_knowledge_dir, dimension)`, the same store ingestion writes to (so retrieval reads what was ingested).
- **Mode:** hybrid default (existing `AdaptiveRetriever` default); agentic mode via the existing `agentic_fn` seam / Brain's escalate path.

## Injection coverage (folded in from the 2026-06-25 prompt-injection discussion)
Retrieved chunks originate from ingested **external** documents (web/email can carry hidden instructions). When chunks are fed toward any responder, **spotlight them as untrusted data** (`untrusted/` spotlight markers), as the quarantine reader does. Owner-curated **memory facts** (`recall_fn`) are trusted and need no spotlighting. This is the Item-2 half of the "is every untrusted-content consumer protected?" coverage sweep (Item 3 is the other half).

## Dependencies / sequencing
- Build **after** the Item-1 sensitivity fix lands (so retrieved chunks carry correct tags for the wall to gate). Functionally independent, but verify together.
- Real reranker + LanceDB-at-scale = Mac-gated tail; wiring + fakes = dev-buildable now.

## To author at session end
Build spec: `compose_brain` retriever assembly (`store_for` + reranker + `AdaptiveRetriever` + `AgenticRetriever`), `retrieve_fn`/`agentic` wiring, retrieved-chunk spotlighting before responder, FakeReranker dev tests + Mac-gated real-reranker tail.
