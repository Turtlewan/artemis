# ADR-015 — Async port surface for network-I/O ports (embedding / rerank / retrieval / LLM)

- **Status:** Accepted · **Date:** 2026-06-11 · **Deciders:** owner + planning
- **Relates:** M0-d (`src/artemis/ports/` — the producer of every port) · contracts.md Seam 1 (LLM `ModelPort`; this ADR extends the async rule to the rest of the I/O port surface) · ADR-004/M4 (MemoryStore — recall/add embed) · M3-a/b/c (ingestion + adaptive retriever + agentic multi-hop) · ADR-001 (mlx-openai-server — all model calls are HTTP to a local server). Trigger: the 2026-06-11 spec-lint pass found M3-c's agentic loop (which `await`s the LLM) could not be threaded through M3-b's **sync** `Retriever.retrieve` port (the `agentic_fn` seam was sync).

## Context

The brain, gateway (FastAPI/SSE), voice loop, heartbeat, and quarantine reader all run inside a single
asyncio event loop. `ModelPort.complete` was already `async` (contracts.md Seam 1). But the rest of the
model-server-facing ports — `EmbeddingModel.embed`, `Reranker.rerank`, and the orchestrating
`Retriever.retrieve` — were defined **sync** in M0-d, even though each performs network I/O to
mlx-openai-server (embeddings, reranking) or transitively calls the async LLM (agentic retrieval).

Two problems followed:
1. **Seam break (the trigger).** Once M3-c's multi-hop loop became `async def run` (it `await`s
   `ModelPort.complete`), M3-b's sync `Retriever.retrieve` — which routes `mode="agentic"` to a sync
   `agentic_fn: Callable[..., list[RetrievedChunk]]` — could no longer hold it. A sync seam cannot
   return the result of an async loop, and the `asyncio.run`-inside-a-running-loop bridge raises at
   runtime. The seam had to become async one way or another.
2. **Latent event-loop blocking.** A *sync* port doing network I/O blocks the entire event loop while it
   waits — one retrieval would stall the voice loop, heartbeat, and other concurrent requests
   (apex-performance "never block the loop"). The reranker call is the heaviest; the query-embedding is
   lighter but pervasive.

Options weighed (spec-lint discussion 2026-06-11):
- **B — route agentic outside the sync retriever** (keep all ports sync; the Brain calls `agentic.run`
  directly). Smallest, preserves the just-frozen contract, but splits retrieval into two entry points
  and leaves the blocking issue unfixed.
- **A — make the retrieval ports async.** Fixes the seam *and* the blocking. Sub-scoped into
  A1 (retrieve + rerank) and A2 (also embed → cascades through everything that embeds).

## Decision

1. **Adopt option A2 — the full async surface for network-I/O ports.** A port method that performs
   **network I/O** (LLM / embedding / rerank calls to the model server) is `async def`. A method that
   only touches **local disk / SQLCipher / returns a cached value** stays sync. This is the standing
   rule for all current and future ports.

2. **Concrete async set** (`src/artemis/ports/`): `ModelPort.complete` (pre-existing), `ModelPort.embed`,
   `EmbeddingModel.embed`, `Reranker.rerank`, `Retriever.retrieve`, and
   `MemoryStore.{recall, inject_context, add_fact, update_fact}` (all embed).
   **Sync set:** `VectorStore.*` (local LanceDB disk I/O), `EmbeddingModel.dimension` (cached int),
   `MemoryStore.delete_fact` (tombstone, no embed), `Router.route`, all voice ports (M5 audio I/O is a
   separate model handled in its own milestone).

3. **The agentic seam is async.** M3-b's `agentic_fn` is `Callable[..., Awaitable[list[RetrievedChunk]]]`;
   `AdaptiveRetriever.retrieve` is `async` and `await`s it. The unified single-entry mode seam
   (`retrieve(query, scope, mode, k)`) is preserved — agentic is not split off to a second door.

4. **VectorStore stays sync deliberately.** LanceDB access is local-disk, not network; keeping it sync
   avoids pulling in the async LanceDB API surface for no event-loop benefit. Revisit only if profiling
   shows large local reads stalling the loop.

## Consequences

- **Cascade (mechanical, ~12–15 specs):** every caller of an async port `await`s it, and any method that
  calls one becomes `async`. Affected: M0-d (ports), M1-a (tool retrieve embeds), M1-b (router embed),
  M3-a/M3-d (ingestion embed), M3-b/M3-c (retriever + agentic), M4-a (store embed on add/update/recall),
  M4-b (write path), M4-c-1 (recall + Brain memory-injection), M4-d-2 (resolve tool), M7-a1 (recipe-store
  embed). contracts.md Seam 1 amended; M0-d is the producer of record.
- **Re-opens a frozen contract.** This is a conscious post-freeze amendment (the freeze stops *drift*,
  not deliberate decisions). The async rule is now part of the binding contract, so later ports inherit it.
- **Tests:** retriever/memory/router/ingestion tests `await` the calls; `mypy --strict` enforces the
  coroutine typing, so a missed `await` fails the gate rather than silently returning a coroutine.
- **Fixes the latent blocking** end-to-end: no model-server call blocks the event loop.
