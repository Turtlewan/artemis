<!-- amended 2026-06-11 per contracts.md (Seam 8) — M3-a connector_for note: the connector_for dispatch wiring must be named at the composition root (Seam 8); no structural changes to M3-b required (retriever is a consumer, not a producer of connectors) -->
---
spec: m3-b-adaptive-retriever
status: ready
token_profile: balanced
autonomy_level: L2
---

# Spec: M3-b — Adaptive retriever (hybrid vector+FTS + RRF + Qwen3-Reranker) behind `Retriever`/`retrieve(query, mode)` with the mode-routing seam (simple→hybrid · complex→agentic-stub · graph→deferred-stub)

**Identity:** Implements the M0-d `Retriever` port as an adaptive retriever: the DEFAULT `mode="hybrid"` path runs LanceDB hybrid search (vector + BM25/FTS) → RRF fusion → Qwen3-Reranker cross-encoder rerank over the M3-a doc index; the `mode` parameter routes `"hybrid"` → this path, `"agentic"` → a seam consumed by M3-c, `"graph"` → a deferred NotImplemented stub. Includes the `Reranker` adapter (Qwen3-Reranker via the `ModelPort` seam) and RRF fusion.
→ why: see docs/technical/adr/ADR-007-knowledge-layer.md (retrieval strategy: default hybrid+RRF+reranker; mode seam; graph deferred) · docs/technical/architecture/brain.md § Retrieval.

<!-- A spec is an EXECUTION SCRIPT, not a design doc. DeepSeek executes literally. -->

<!-- Split rule: ONE logical phase (the hybrid retrieve path + the mode seam) across 3 src files (the retriever, the reranker adapter, the RRF helper) + 1 test = at the file limit, within bounds. The agentic loop body is the separate M3-c (M3-b only ships the `mode="agentic"` seam/dispatch + a stub so the port is total); the graph path is a permanent deferred stub. The doc index it reads is M3-a's `LanceDBVectorStore`. Flagged per rules. -->

## Assumptions
- M0-d (`Retriever`, `Reranker`, `VectorStore`, `EmbeddingModel`, `RetrievedChunk`, `Mode = Literal["hybrid","agentic","graph"]`, `Scope`), M0-a (`config`/`Settings`), M1-b (`OpenAIModelPort`/`OpenAIEmbeddingModel` adapters + the M0-c base-URL seam), M3-a (`LanceDBVectorStore` with `search` + the on-volume doc table + dimension-lock) are complete. → impact: Stop (the retriever consumes `VectorStore`/`EmbeddingModel`/`Reranker` ports and the M3-a table schema; `Mode` is the exact M0-d literal).
- LanceDB exposes **native hybrid search** (dense + FTS/BM25) and built-in RRF. M3-b uses LanceDB's hybrid query where available; if the installed LanceDB version's hybrid API is unstable, the fallback is: run a dense `search` + a separate FTS `search` and fuse with an explicit RRF helper (Task 2). → impact: Caution. Decision: build `hybrid_search` to TRY LanceDB native hybrid+RRF first, FALL BACK to explicit dense+FTS+our-RRF on AttributeError/NotImplementedError; explicit RRF helper unit-tested off-hardware. GATED Task 5: record which path is primary on the installed LanceDB version (WAND FTS). Does not change the Retriever shape. (LanceDB FTS uses WAND — fast; sqlite-vec is pinned per brain.md but is NOT used for the doc corpus, only memory.)
- The **Qwen3-Reranker** is a local cross-encoder reached via the `ModelPort`/mlx-openai-server seam (the `reranker` role in M0-a `roles.toml`). The reranker takes `(query, [candidate texts])` → relevance scores. M3-b implements a `Reranker` adapter (`QwenReranker`) that calls this role; off-hardware tests use a deterministic `FakeReranker`. → impact: Caution. Decision: drafted default transport = `/v1/rerank` behind the `_score(query, texts) -> list[float]` seam; if absent, fall back to constrained-decoded scores via `/v1/chat/completions`. GATED Task 5: confirm the live Qwen3-Reranker-0.6B endpoint shape. Off-hardware = FakeReranker.
- The retriever is **stateless per call** and **scope-bound**: `retrieve(query, scope, mode, k)` opens (or reuses) the scope's M3-a `LanceDBVectorStore`; it never crosses scopes (the wall is enforced by the store's `CrossScopeError`). Retrieval requires the encrypted volume mounted (owner unlocked) — the store raises `ScopeLockedError` if not. → impact: Stop (wall + unlock are inherited from M3-a, not re-implemented).
- `mode="agentic"` in M3-b is a **dispatch seam**: M3-b accepts an OPTIONAL injected `agentic_fn: Callable[[str, Scope, int], Awaitable[list[RetrievedChunk]]] | None` (ASYNC callable per ADR-015 — `Retriever.retrieve` is now async, so the agentic delegate is awaited inside it); if `mode=="agentic"` and `agentic_fn` is set, `await` it (M3-c provides the real loop and wires it in); if it is None, fall back to the hybrid path (so the port is always total — never raises for `agentic`). `mode="graph"` raises a typed `GraphModeNotImplemented` (the clean deferred seam per ADR-007 — "leave a clean mode=graph seam", do NOT build it). → impact: Stop (graph is DEFERRED; agentic body is M3-c).
- Spotlighting / CaMeL gating of retrieved untrusted chunks (brain.md security) is a SECURITY-LAYER concern applied by the consumer (the Brain / sensitivity layer), not inside the retriever. M3-b returns raw `RetrievedChunk`s with their provenance intact so the consumer can spotlight them. → impact: Caution (FLAG: the consumer must spotlight; M3-b does not pass chunks to any model itself except the reranker, which scores text without acting on instructions).

Simplicity check: considered building the agentic loop and a graph adapter into M3-b — rejected: ADR-007 defers the graph entirely (clean stub only) and the brief splits the agentic loop into M3-c; M3-b's job is the default hybrid path + the mode seam. Considered skipping the reranker for M3 — rejected: ADR-007 locks reranker in the default path. Considered an explicit-only RRF (ignore LanceDB native hybrid) — kept both behind one method so we use the engine's optimised path when stable but always have a deterministic fallback. This is the minimum adaptive-retrieve surface.

## Prerequisites
- Specs that must be complete first: **M0-a**, **M0-d** (`Retriever`/`Reranker`/`Mode`/`RetrievedChunk`), **M1-b** (`ModelPort`/`EmbeddingModel` adapters + base-URL seam), **M3-a** (`LanceDBVectorStore` + doc table + `search`/`hybrid_search`). 
- Environment setup required: none new off-hardware (reuses M3-a's `lancedb` + M1-b's model client). Off-hardware tests use `FakeEmbedder`/`FakeReranker` + a temp LanceDB seeded by the M3-a writer; **the live Qwen3-Reranker + LanceDB native-hybrid + the end-to-end reranked retrieve are GATED on-hardware** (Task 5).

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| /Users/artemis-build/artemis/src/artemis/retrieval/__init__.py | create | retrieval package marker |
| /Users/artemis-build/artemis/src/artemis/retrieval/rrf.py | create | `reciprocal_rank_fusion(rankings, k=60) -> fused list` (deterministic, unit-tested) |
| /Users/artemis-build/artemis/src/artemis/adapters/reranker.py | create | `QwenReranker` implementing the M0-d `Reranker` port via the `reranker` ModelPort role; `_score` seam |
| /Users/artemis-build/artemis/src/artemis/retrieval/retriever.py | create | `AdaptiveRetriever` implementing the M0-d `Retriever` port: hybrid→RRF→rerank; mode seam (agentic delegate / graph stub) |
| /Users/artemis-build/artemis/src/artemis/adapters/lancedb_store.py | modify | add `hybrid_search(scope, query_vector, query_text, k)` (native-hybrid-or-explicit-fallback) used by the retriever |
| /Users/artemis-build/artemis/tests/test_retriever.py | create | RRF, reranker, hybrid path, mode-routing (agentic-delegate + graph-NotImplemented) against fakes |

## Tasks
- [ ] Task 1: Implement RRF fusion — files: `/Users/artemis-build/artemis/src/artemis/retrieval/rrf.py` (+ `retrieval/__init__.py`) — `def reciprocal_rank_fusion(rankings: Sequence[Sequence[str]], *, k: int = 60) -> list[tuple[str, float]]`: standard RRF — for each id, sum `1/(k + rank)` across the input rankings (rank is 0-based or 1-based — document the choice; use 1-based per the canonical RRF paper); return ids sorted by fused score descending. Pure, deterministic, no engine. — done when: `uv run mypy --strict src` passes; a doc that ranks high in two lists outranks one high in a single list (asserted in Task 6).

- [ ] Task 2: Add `hybrid_search` to the LanceDB store — files: `/Users/artemis-build/artemis/src/artemis/adapters/lancedb_store.py` (modify) — add `def hybrid_search(self, scope: Scope, query_vector: Sequence[float], query_text: str, k: int) -> list[RetrievedChunk]`: assert `scope`==self.scope (wall); attempt LanceDB's native hybrid query (vector=`query_vector`, full-text=`query_text`, RRF) returning the top-`k` rows as `RetrievedChunk`s (chunk carries the M3-a provenance metadata); on `AttributeError`/`NotImplementedError` from an older LanceDB, FALL BACK to: dense `search(scope, query_vector, k*2)` + a separate FTS query on `text` for `query_text` (k*2) → `reciprocal_rank_fusion([dense_ids, fts_ids])` → take top-`k`, re-materialise rows. Document which path ran (a `self._hybrid_native: bool` flag set on first call). — done when: `uv run mypy --strict src` passes; against a temp table seeded with rows, `hybrid_search` returns ≤k `RetrievedChunk`s carrying provenance (Task 6).

- [ ] Task 3: Implement the Qwen3-Reranker adapter — files: `/Users/artemis-build/artemis/src/artemis/adapters/reranker.py` — `class QwenReranker` implementing the M0-d `Reranker` Protocol, constructed from `Settings` (resolves the `reranker` role endpoint/model via the M1-b/M0-c base-URL seam). `async def rerank(self, query, chunks, top_k)` (async per ADR-015): `await self._score(query, [c.chunk.text for c in chunks]) -> list[float]`, attach scores, sort descending, return the top-`top_k` as `RetrievedChunk`s with the reranker score in `.score`. `async def _score(self, query, texts) -> list[float]`: the swappable transport (the `/v1/rerank`-vs-chat seam from Assumptions; the HTTP call to the local model is awaited) — bind `127.0.0.1` only. `class FakeReranker` (TEST): deterministic — `async def rerank` scores by descending lexical overlap of `query` tokens with each text (so a known-relevant chunk sorts first), no network. — done when: `uv run mypy --strict src` passes; `await FakeReranker.rerank(...)` returns chunks reordered so the most query-overlapping chunk is first; `_check: Reranker = QwenReranker(...)` type-checks.

- [ ] Task 4: Implement the AdaptiveRetriever with the mode seam — files: `/Users/artemis-build/artemis/src/artemis/retrieval/retriever.py` — `class AdaptiveRetriever` implementing the M0-d `Retriever` Protocol, constructed with `(embedder: EmbeddingModel, store_for: Callable[[Scope], LanceDBVectorStore], reranker: Reranker, *, agentic_fn: Callable[[str, Scope, int], Awaitable[list[RetrievedChunk]]] | None = None, candidate_k: int = 30)` (`agentic_fn` is an ASYNC callable per ADR-015). `async def retrieve(self, query: str, scope: Scope, mode: Mode = "hybrid", k: int = 10) -> list[RetrievedChunk]` (async per ADR-015 — `Retriever.retrieve` is now async; awaits the async embedder, reranker, and agentic delegate):
  - `if mode == "graph": raise GraphModeNotImplemented("graph mode is deferred per ADR-007; use hybrid or agentic")` (define `GraphModeNotImplemented(NotImplementedError)`).
  - `if mode == "agentic" and self.agentic_fn is not None: return await self.agentic_fn(query, scope, k)` (M3-c's loop; `agentic_fn` is async per ADR-015 — `await` it); `if mode == "agentic" and self.agentic_fn is None:` fall through to hybrid (document: agentic not wired → degrade to hybrid, total port).
  - hybrid (default + agentic-fallback): `qv = (await embedder.embed([query]))[0]` (`EmbeddingModel.embed` is async — `await` then index); `store = store_for(scope)`; `candidates = store.hybrid_search(scope, qv, query, candidate_k)` (sync — `VectorStore` stays sync per ADR-015, NO `await`); `reranked = await reranker.rerank(query, candidates, top_k=k)` (`Reranker.rerank` is async — `await`); return `reranked`. Propagate `ScopeLockedError`/`CrossScopeError` from the store (the wall/unlock; never swallow them). Static `_check: Retriever = AdaptiveRetriever(...)` asserted in the test. — done when: `uv run mypy --strict src` passes; `await retrieve(..., mode="graph")` raises `GraphModeNotImplemented`; `mode="agentic"` with an injected async fn delegates; default routes hybrid→rerank.

- [ ] Task 5 (GATED — on-hardware): Live hybrid + Qwen3-Reranker end-to-end — files: (uses Tasks 2/3/4 + M3-a-ingested data + served models) — on the Mini with mlx-openai-server serving Qwen3-Embedding-0.6B + Qwen3-Reranker and a small corpus ingested via M3-a onto the mounted encrypted volume: run `await AdaptiveRetriever.retrieve("<a query with a known-relevant doc>", "owner-private", mode="hybrid", k=5)` (`retrieve` is async per ADR-015); confirm (a) LanceDB native-hybrid path is used (or the explicit fallback, recorded), (b) the reranker reorders candidates, (c) the known-relevant chunk appears in the top-k with its provenance (page/url) intact. Build-time spikes: LanceDB native-hybrid stability; reranker endpoint shape; reranker in-process-vs-sidecar latency (brain.md). — done when: a real reranked hybrid retrieve returns the expected chunk with provenance; the native-vs-fallback hybrid choice + the reranker endpoint shape are recorded in handoff.

- [ ] Task 6: Write the off-hardware retriever tests — files: `/Users/artemis-build/artemis/tests/test_retriever.py` — typed pytest with `FakeEmbedder` (`async def embed`) + `FakeReranker` (`async def rerank`) + a real `LanceDBVectorStore` seeded (via the M3-a writer or direct sync `add`) with a few chunks at a temp `ARTEMIS_DATA_ROOT` (D4: no `ARTEMIS_VOLUME_ROOT` setting; `vault_dir` resolves under `ARTEMIS_DATA_ROOT`). NOTE: `retrieve` is now `async def` — the retrieve tests are `async def test_*` under `@pytest.mark.asyncio` (no prior async-test convention in this spec; add `pytest-asyncio` if not already a dev dep) and `await retriever.retrieve(...)`; the seeded `LanceDBVectorStore` `add`/`hybrid_search` calls stay sync (no `await`):
  - RRF: `reciprocal_rank_fusion` ranks a doc appearing in two lists above one in a single list (pure/sync — no await).
  - hybrid_search: returns ≤k `RetrievedChunk`s carrying provenance fields (sync call).
  - retriever default: `await retrieve("known query", scope, k=3)` returns the seeded known-relevant chunk first (FakeReranker overlap ordering), `escalated`-free, provenance present.
  - mode seam: `await retrieve(query, scope, mode="graph")` raises `GraphModeNotImplemented`; `await retrieve(query, scope, mode="agentic")` with an injected ASYNC `agentic_fn` returns that fn's output; with `agentic_fn=None` it degrades to the hybrid result.
  - wall/unlock: a store with `is_unlocked=lambda:False` → `await retrieve` propagates `ScopeLockedError`.
  - static port: `_r: Retriever = AdaptiveRetriever(...)` type-checks under mypy.
  — done when: `uv run pytest -q` passes AND `uv run mypy --strict src tests/test_retriever.py` passes.

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | /Users/artemis-build/artemis/src/artemis/retrieval/__init__.py, /Users/artemis-build/artemis/src/artemis/retrieval/rrf.py, /Users/artemis-build/artemis/src/artemis/adapters/reranker.py, /Users/artemis-build/artemis/src/artemis/retrieval/retriever.py, /Users/artemis-build/artemis/tests/test_retriever.py |
| Modify | /Users/artemis-build/artemis/src/artemis/adapters/lancedb_store.py |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict src tests/test_retriever.py` | Type gate |
| `uv run ruff check . ; uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q` | Test gate (fakes + temp LanceDB) |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | src/artemis/retrieval/**, src/artemis/adapters/reranker.py, src/artemis/adapters/lancedb_store.py, tests/test_retriever.py |
| `git commit` | "feat: M3-b adaptive retriever — hybrid+RRF+Qwen3-Reranker behind retrieve(query,mode); agentic seam + graph deferred stub" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_ENV_FILE` | Slot Settings (embedder/reranker roles, paths) |
| `ARTEMIS_DATA_ROOT` | Data root; `vault_dir` resolves the LanceDB doc table under it (D4: replaces the removed `ARTEMIS_VOLUME_ROOT`) |

### Network
| Action | Purpose |
|--------|---------|
| local `127.0.0.1` calls to mlx-openai-server (GATED) | Live embedder + Qwen3-Reranker |

## Specialist Context
### Security
The retriever inherits the M3-a wall + unlock invariants (scope-bound store; `CrossScopeError`/`ScopeLockedError` propagated, never swallowed). Retrieved chunks are UNTRUSTED data — M3-b returns them with provenance for the CONSUMER to spotlight/CaMeL-gate before any privileged model sees them (brain.md). The reranker scores text and must not be allowed to act on instructions inside chunk text (it returns scores only). [FLAG for apex-security: the Brain/sensitivity layer that consumes `retrieve()` (M3-c / a later wiring) must spotlight retrieved chunks before feeding a privileged model, and must enforce the provenance gate (no sensitive chunk to cloud). M3-b does not bypass this.]

### Performance
Default path is hybrid (zero LLM tokens for retrieval) + one local cross-encoder rerank pass over `candidate_k` (default 30) candidates → top-k — the brain.md "simple→hybrid+rerank (no LLM)" path. RRF fusion is O(candidates). Reranker in-process-vs-sidecar latency is a build-time spike (Task 5). The agentic path (multiple LLM-driven hops) is M3-c and is reserved for complex queries only.

### Accessibility
(none — no frontend)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | src/artemis/retrieval/*.py, src/artemis/adapters/reranker.py | Type + docstring all exports; document the mode seam (hybrid default · agentic delegate · graph deferred) + RRF + the dense+FTS fallback |

## Acceptance Criteria
- [ ] Run `uv run mypy --strict src tests/test_retriever.py` → verify: exit 0 (incl. `Retriever`/`Reranker` structural assertions).
- [ ] Run `uv run pytest -q tests/test_retriever.py` → verify: RRF ordering, hybrid_search provenance, default `await`ed reranked retrieve returns the known chunk first, `mode="graph"` raises `GraphModeNotImplemented`, `mode="agentic"` delegates to the awaited async fn (or degrades), `ScopeLockedError` propagates.
- [ ] Run `uv run python -c "from artemis.retrieval.retriever import AdaptiveRetriever, GraphModeNotImplemented; print(issubclass(GraphModeNotImplemented, NotImplementedError))"` → verify: prints `True` (clean deferred seam).
- [ ] Run `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.
- [ ] (GATED, on Mini) Live hybrid + Qwen3-Reranker retrieve returns the known-relevant chunk with provenance; native-vs-fallback hybrid + reranker endpoint recorded → verify in handoff.

## Progress
_(Coding mode writes here — do not edit manually)_
