# ADR-007 — Knowledge layer: storage encryption + retrieval strategy (M3)

**Status:** Accepted (SP0 phase 6, M3 design, 2026-06-04)
**Builds on:** ADR-001 (LanceDB) · ADR-004 (memory: sqlite-vec in SQLCipher) · ADR-005 (key-broker) · ADR-006 (proactivity tiers) · brain.md §§ Retrieval, Ingestion. Preference forks #3 (embed 0.6B), #4 (visual-docs IN).

## Context
The document/"second-brain" corpus is **sensitive** (owner's docs/notes/extracted media) → must be per-scope encrypted behind the M2 wall. It needs **scale** (a growing life-corpus) → indexed ANN search → **LanceDB**. But **LanceDB OSS cannot encrypt at rest**, and sqlite-vec (used for the small memory store) is brute-force and won't scale to the document corpus. So the doc corpus needs a different encryption mechanism than memory.

## Decision

### Storage + encryption
- **Sensitive document corpus = LanceDB inside a per-scope encrypted volume** (encrypted APFS volume / sparsebundle), volume key SE-wrapped, **mounted by the M2 key-broker on a phone-attested unlock** (extends ADR-005 — the broker now mounts the volume *and* releases the SQLCipher DEK).
- **Unified per-scope vault:** the per-scope encrypted volume holds the scope's **SQLCipher memory DB (ADR-004) + the LanceDB document index + vector indexes** — **one unlock opens everything**. LanceDB keeps its native ANN + hybrid search (encryption is transparent at the filesystem layer).
- **Document search is Tier-1** (unlock-required). A non-sensitive/public always-available knowledge tier (plain LanceDB, ADR-006 Tier-0 style) is **deferred** — add later only if needed.

### Retrieval strategy (adaptive, behind the `retrieve(query, mode)` port)
- **Default:** hybrid (vector + BM25/FTS) + **RRF** + **Qwen3-Reranker** (local cross-encoder).
- **Complex / connect-the-dots:** **agentic multi-hop** — a query-time iterative loop (search → read → follow-up query → search → synthesise). No upfront relationship extraction; cheap + reliable on the small local model; fits the "ack → streamed answer" UX for heavy queries.
- **Knowledge graph = DEFERRED** behind the same port: lazy/on-demand extraction (fast-graphrag, extract only the queried slice) → full pre-built graph only if agentic proves insufficient AND a stronger local model is available. No pre-built community-summary index.

### Ingestion
Per-source connectors → normalized **`Document`** → Docling parse → **late chunking** (+ Contextual Retrieval for high-value) → embed (**Qwen3-Embedding-0.6B**, #3) → LanceDB (dense + FTS). **Idempotent via `content_hash`**; **provenance + locator** (page/timestamp/bbox) on every chunk. **Visual-document understanding IN (#4):** Apple Vision OCR + Qwen3-VL scene description + ColPali-style visual retrieval = **ColQwen2.5 Light via PyTorch MPS 2.5.1** (locked 2026-06-08; Lance v2.2 Blob V2 makes patch-vector storage practical); resident-vs-lazy = **build-time sizing spike**.

## Runner-ups ruled out
- **sqlite-vec for documents** — brute-force, won't scale to a life-corpus (brain.md-disqualified).
- **Per-chunk app-side encryption in LanceDB** — breaks the ANN vector index.
- **Pre-built knowledge graph now** — heavy LLM relation-extraction per chunk; small-model quality/latency cost for a feature only rare multi-hop queries use. Agentic multi-hop delivers connect-the-dots far cheaper.

## Consequences
- Document search is **unlock-gated (Tier-1)** — consistent with the security model; covered by the same broker unlock as memory.
- **Broker gains a volume-mount responsibility** (refines ADR-005).
- **Connect-the-dots from day one** via agentic multi-hop, without the graph's extraction cost.
- Deferring the graph reduces M3 scope and dodges the small-model extraction problem (see ADR-004 / Graphiti findings).
- **Cross-milestone:** M3 builds ingestion + adaptive RAG on the encrypted volume; depends on M2 (broker/volume) + uses ADR-004's vault.

## Build-time spikes (gated tasks at M3)
Encrypted-volume mount lifecycle + perf + clean-snapshot backup · visual-doc RAM (ColQwen2.5 resident vs lazy on 48GB) · agentic-loop iteration/stop tuning · LanceDB sizing (brain.md) · **GraphRAG eval (see 2026-06-08 refinement): LightRAG vs agentic multi-hop on a personal gold-set behind the `retrieve(query,mode)` port — extraction-judgment quality on Qwen3.6-27B is the open question.**

## Refinement (2026-06-08 — brain/AI research sweep)
Re-validation pass (`docs/research/2026-06-08-brain-ai-improvements-synthesis.md`):
- **Retrieval stack unchanged** — Qwen3-Embedding (0.6B + 4B eval tier) + Qwen3-Reranker still lead their class with a verified MLX path; no re-index migration warranted. (LanceDB FTS now 3–8× faster via WAND; still no at-rest encryption → the encrypted-volume approach above stays the correct workaround.)
- **GraphRAG: "hard-deferred" → gated build-time spike.** The defer condition above ("full pre-built graph only if agentic proves insufficient AND a stronger local model is available") now has its model half satisfied — **Qwen3.6-27B** (ADR-001 refinement) clears the ~32B extraction bar and constrained decoding guarantees relation-JSON validity, leaving only extraction *judgment* to validate empirically. **LazyGraphRAG remains non-OSS** (Azure-only; `microsoft/graphrag` v3.1.0 has none) — do not wait for it. **Spike:** evaluate **LightRAG** (MIT, incremental; fall back to `fast-graphrag` if it ships a 14B-verified v1.0) vs the agentic-multi-hop default, behind the unchanged port. **Agentic multi-hop stays the default** until the graph proves it earns its extraction cost (April-2026 "Do We Still Need GraphRAG?" shows agentic narrows the quality gap, more so on a low-entity-density personal corpus). A 64GB box (ADR-001) makes this a clean experiment.
- **Visual-doc retriever locked** — ColQwen2.5 Light / MPS 2.5.1 (resolves the §Ingestion placeholder).

## Parked (build-phase / later)
Non-sensitive always-available knowledge tier · lazy then full graph layer · ColPali specifics · Marker/MinerU escalation for hard tables/CJK.
