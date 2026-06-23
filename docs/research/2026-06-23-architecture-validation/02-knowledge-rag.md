# Architecture Validation — Knowledge Corpus / Retrieval (RAG)

**Date:** 2026-06-23
**Scope:** Validate Artemis's knowledge-corpus + retrieval architecture against 2024–2026 SOTA retrieval research. Skeptic stance.
**Reviewer disposition:** Adversarial — looking for what's wrong, missing, or locked-in too early.

---

## 0. What Artemis actually has (corrected from the brief)

Reading the live specs (M3-a ingestion, M3-b adaptive retriever, M3-c agentic multi-hop, M3-d visual, ADR-007) rather than the brief's summary, the design is **materially more advanced** than the brief implied. The brief lists several SOTA techniques as "missing" or "backlog" that are in fact already designed-in:

| Technique | Brief framing | Actual state in specs |
|---|---|---|
| Late chunking | not mentioned | DEFAULT ingestion path (M3-a Task 4/6) |
| Contextual Retrieval (Anthropic) | not mentioned | per-doc `contextual` flag, `context_fn` seam (M3-a Task 4) |
| ColPali/ColQwen visual late-interaction | "missing?" (Q4) | LOCKED to ColQwen2.5 Light, MaxSim multi-vector table (M3-d, ADR-007) |
| Agentic multi-hop | "M3-c exists" | SHIPPED DEFAULT for complex queries (M3-c) |
| GraphRAG | "deferred" | gated build-time spike: LightRAG vs agentic on a gold-set behind the unchanged port (ADR-007 refinement) |
| Query routing | not mentioned | router → `mode` seam (hybrid/agentic/graph) is the spine of M3-b |

This changes the verdict. Artemis is not a naive top-k RAG that needs a SOTA retrofit. It is **already an adaptive, hybrid, reranked, multi-vector, agentic-routed design** — which is exactly the 2026 consensus architecture. The remaining question is narrower: are the *specific* choices right, and are the known gaps additive or foundational.

---

## 1. The 2026 SOTA consensus

The dominant 2026 position across practitioner and academic sources is **Adaptive RAG**: a query classifier/router routes each query to the cheapest pipeline that can answer it — classic hybrid for simple lookups, agentic/multi-hop for connect-the-dots, structured/SQL for aggregates, graph only where relationship-density justifies the extraction cost. "It's not GraphRAG *versus* agentic — it's a spectrum with routing on top." (starmorph, Daniel Jude / Medium, Data Nucleus 2026; confidence: HIGH — this is near-universal across sources.)

Artemis's `retrieve(query, mode)` port + router IS this architecture. The substrate is correct.

Key SOTA building blocks and where Artemis stands:

- **Hybrid (dense + BM25) + reranking** — still the universally-recommended *core* in 2026. Anthropic's Contextual Retrieval numbers anchor it: contextual embeddings cut top-20 failure 35%; +contextual BM25 → 49%; +reranking → 67%. Reranking is a first-class part of the floor, not optional. (Anthropic 2024; DataCamp; confidence: HIGH.) Artemis has this exactly (M3-b: hybrid + RRF + Qwen3-Reranker).
- **Late chunking** — Jina 2024 (arXiv 2409.04701, updated Jul 2025). Embed the long document, then pool per-chunk so each chunk vector carries doc context. "Almost always" beats naive chunking; single forward pass so it's cheap. Artemis uses it as default. (confidence: HIGH.)
- **Contextual Retrieval** — Anthropic Sep 2024. Prepend an LLM-generated 50–100 token context blurb per chunk before embedding + BM25. Bigger accuracy gain than late chunking but costs one LLM call per chunk at ingest (mitigated ~90% by prompt caching). Artemis has it as an opt-in per-doc flag. (confidence: HIGH.)
- **Late-interaction visual retrieval (ColPali/ColQwen)** — ColPali (arXiv 2407.01449) is SOTA for visual/PDF retrieval on ViDoRe; ColQwen3-4B and Nemotron ColEmbed v2 (Feb 2026) lead the leaderboard. Treats the page as an image, 1024 patch vectors @128-dim, MaxSim. Artemis locked ColQwen2.5 Light + a separate MaxSim multi-vector table. This is the correct family; only the exact model version is a sizing call. (confidence: HIGH.)
- **Hierarchical summarization (RAPTOR)** — recursive cluster→summarize tree, retrieve at multiple granularities. SOTA on multi-step QA; notably, the long-context-vs-RAG eval found *summary-based* retrieval matches long-context while *chunk-based* lags. This is the single most defensible "missing" item (see §4). (RAPTOR arXiv 2401.18059; Long Context vs RAG arXiv 2501.01880; confidence: HIGH.)
- **Graph memory (HippoRAG 2)** — Personalized-PageRank over an open KG; +7 F1 on multi-hop over strong dense baselines, and **10–30× cheaper multi-hop and far cheaper offline indexing than GraphRAG/RAPTOR/LightRAG** (arXiv 2502.14802, Mar 2025). If a graph is ever added, HippoRAG 2 — not Microsoft GraphRAG — is the one to benchmark. (confidence: MEDIUM-HIGH.)
- **Aggregation / structured queries** — the acknowledged hard frontier. Vector RAG structurally *cannot* answer "which week had highest sales" — fixed top-k can't aggregate over a corpus, and LLM arithmetic over partial context errs. 2025–2026 work (S-RAG arXiv 2511.08505; Aggregation-over-unstructured-text arXiv 2602.01355) routes these to structured extraction / text-to-SQL, not retrieval. (confidence: HIGH.)
- **Long-context vs RAG** — not a replacement. LC wins on small static single-doc QA; RAG wins on dynamic/diverse/large corpora — which is exactly a growing life-corpus. Settles that RAG remains the right substrate for a second brain. (arXiv 2501.01880; confidence: HIGH.)

---

## 2. Comparison table — Artemis vs SOTA

| Capability | SOTA 2026 | Artemis | Verdict |
|---|---|---|---|
| Core retrieval | hybrid + rerank | hybrid + RRF + Qwen3-Reranker | ✅ matches floor |
| Adaptive routing | query classifier → pipeline | router → `mode` seam | ✅ matches consensus |
| Chunk context | late chunking and/or contextual | both (late default, contextual opt-in) | ✅ ahead of median |
| Multi-hop / connect-the-dots | agentic loop or graph | agentic multi-hop default | ✅ correct default for a personal corpus |
| Visual docs | ColPali/ColQwen MaxSim | ColQwen2.5 Light MaxSim table | ✅ correct family |
| Hierarchical/whole-doc | RAPTOR tree + summary-first | planned: whole-doc routing + summary tier (read-side) | ⚠️ underbuilt — see §4 |
| Aggregates | structured extract / text-to-SQL | planned: route to structured query | ⚠️ structurally foundational, not just a route |
| Graph | HippoRAG 2 / LightRAG where dense | gated spike (LightRAG vs agentic) | ✅ correctly deferred; pick HippoRAG 2 as the comparator |
| Exact-match IDs | keyword/filter path | planned: explicit keyword handling | ✅ additive, fine |
| Versioned/temporal recall | freshness + supersession | planned (processing/verified/searchable, supersession) | ✅ additive |
| Embedding lock-in | model swap = re-index | one model, dim-locked, explicit migration | ⚠️ acceptable but watch (§3) |

---

## 3. Answers to the five questions

### Q1 — Is chunk-based hybrid on LanceDB still the right CORE?
**YES (HIGH).** Hybrid + rerank is still the 2026 floor for *all* the leading systems; graph/hierarchical/late-interaction sit *on top of or beside* it, not *instead of* it. For a single-owner, low-entity-density personal corpus, agentic-multi-hop-on-hybrid is the documented sweet spot (the "Do We Still Need GraphRAG?" line: agentic narrows the gap, more so on low-entity-density corpora). LanceDB is the right embedded store (native hybrid + WAND FTS + multi-vector Blob V2 for ColPali patches, no server, local-first). The core is not the weak link.

### Q2 — Are the planned gap-fixes the right ones, and are any FOUNDATIONAL?
The four planned fixes are the right targets, but **two are mis-classified as read-side patches when they are foundational:**

- **Whole-doc / aggregate routing** → partly foundational. The *routing* is read-side, but answering aggregates requires a **structured projection of the corpus at ingest** (a queryable table of facts/metadata, or per-doc structured records). You cannot bolt text-to-SQL onto a pure chunk index later without an ingest-time extraction step. Decide the structured-store shape now (even if empty). (HIGH.)
- **Summary-first tiered retrieval** → foundational-ish. "Store raw + summary, retrieve summary first" is the cheap cousin of RAPTOR. To do it well you want a **summary node per document (and ideally per cluster) carrying back-references** — that is an ingest-time + schema decision (a `node_level`/`is_summary` field + a parent/child link), not a read-side filter. Adding it later means re-summarizing the whole corpus. (HIGH.)
- **Contextual retrieval** → already correctly a per-doc ingest flag (foundational and present). Good. Just confirm the BM25 index is built over the *contextualized* text, not raw (Anthropic's gain depends on it). (MEDIUM.)
- **Exact-match IDs** → genuinely additive; LanceDB FTS already indexes the terms; just need a filter/keyword path. Fine to layer later. (HIGH.)

### Q3 — Is single-model + locked-dim + LanceDB future-proof, or lock-in risk?
**Acceptable, with a managed risk (MEDIUM).** Dimension-locking is correct discipline (prevents silent corruption). The real lock-in is *operational*: any embedding-model upgrade = full re-embed + re-index of the entire encrypted corpus, which on-device is slow and battery/heat-bound. Mitigations the design should bake in: (a) keep `model_id` + `dimension` in table metadata (already done); (b) store the **raw chunk text** so re-embedding never requires re-parsing (M3-a stores text — good); (c) treat migration as a first-class offline batch job, not an afterthought. The one-model-for-docs-and-memory choice is fine and simplifying. Qwen3-Embedding remains class-leading per the 2026-06-08 sweep, so no migration is warranted now. **Not a blocker; just make migration a designed path, not an emergency.**

### Q4 — What is Artemis MISSING vs world-class?
1. **Hierarchical/RAPTOR-style summary index** — the biggest real gap. The planned "summary-first" tier is a thin version; the strong version is a recursive cluster-and-summarize tree giving multi-granular retrieval and *correct* whole-document and thematic answers. Directly fixes the brief's gap (a). (HIGH.)
2. **A structured/relational projection for aggregates** — without it, "which week had highest sales" is unanswerable by any amount of retrieval tuning. (HIGH.)
3. **Cluster-level summaries with back-references** for "summarise everything about X across my corpus" — partially covered by agentic multi-hop but expensive per query; a pre-built summary layer makes it cheap. (MEDIUM.)
4. Minor: contextualized-BM25 (confirm), and a HippoRAG-2 comparator in the graph spike (currently LightRAG/fast-graphrag only — add HippoRAG 2; it's cheaper and stronger on multi-hop). (MEDIUM.)

Not missing (despite the brief): ColPali (locked), contextual retrieval (flagged), agentic multi-hop (default), reranking (default).

### Q5 — Additive vs Foundational per alternative

| Alternative | Classification | Why |
|---|---|---|
| RAPTOR / hierarchical summary tree | **FOUNDATIONAL** | needs ingest-time summarization + a node-level/parent-child schema; retrofitting = full re-summarize |
| Structured store for aggregates (text-to-SQL target) | **FOUNDATIONAL** | needs ingest-time fact/metadata extraction into a queryable table |
| Contextual Retrieval | foundational, **already present** | ingest-time blurb + contextual BM25 |
| ColPali visual | foundational, **already present** | separate multi-vector table at ingest |
| Summary-first tier | **FOUNDATIONAL (light)** | summary node + back-ref at ingest |
| GraphRAG / HippoRAG 2 | **ADDITIVE** | behind the unchanged port; correctly a gated spike. Swap comparator to HippoRAG 2 |
| Exact-match ID/keyword path | **ADDITIVE** | filter over existing FTS |
| Versioned/temporal recall | **ADDITIVE** | status field + supersession on read |
| Late chunking | additive, **already present** | read-quality boost, no schema change |
| Long-context fallback | **ADDITIVE** | route small-doc queries to LC; optional |

---

## 4. The one thing to fix now: hierarchy + structured projection are schema, not patches

The brief's gaps (a) whole-doc/aggregate and (b) summary-first are framed as "route those query shapes" — read-side. That under-reads the research. RAPTOR's whole win, and the structured-RAG/text-to-SQL win for aggregates, both come from **work done at ingest time** producing artifacts (summary tree nodes; a structured fact table) that the read path then queries. If the `Chunk`/`Document` schema and the ingest pipeline are frozen now without:
- a `node_level` / `is_summary` field + parent/child link (for hierarchy), and
- a hook to emit structured records into a queryable side table (for aggregates),

then both gaps become **expensive re-ingests** later instead of additive layers. The good news: Artemis already "pushes structured knowledge into the corpus as Documents/Chunks with back-references," and M3-a's `IngestResult` exposes parse/document locals for subclassing — so the seams exist. The recommendation is to **reserve the schema fields and the ingest hook now**, even if the summarizer and the structured extractor ship later.

Everything else (graph, IDs, temporal, long-context) is genuinely additive behind the existing port and correctly deferred.

---

## 5. Verdict

**MOSTLY YES — the RAG design is a SOTA-aligned substrate, not a liability.** Artemis already implements the 2026 adaptive-RAG consensus (hybrid+rerank core, adaptive routing, late chunking, contextual retrieval, ColPali visual, agentic multi-hop default, graph correctly deferred). The substrate (chunk hybrid on LanceDB) is the right floor and not the weak link. The single substantive architectural risk is treating **hierarchy (RAPTOR-style summary tree) and the structured/aggregate projection as read-side patches when they are ingest-time/schema decisions** — these should be reserved in the schema now. Embedding lock-in is a managed operational risk, not a design flaw, provided migration is a designed offline path (raw text is retained, so it is). Graph stays additive; swap the spike comparator to HippoRAG 2.

**Confidence: HIGH** on the core-is-right and the SOTA mapping; **HIGH** on hierarchy/aggregates being foundational; **MEDIUM** on the embedding-migration ergonomics (depends on on-device re-index cost, untested).

---

## Sources
- [RAG Techniques Compared 2026 — starmorph](https://blog.starmorph.com/blog/rag-techniques-compared-best-practices-guide)
- [Classic vs GraphRAG vs Agentic RAG — Daniel Jude, Medium (Apr 2026)](https://danieljude1992.medium.com/classic-rag-graphrag-and-agentic-rag-whats-the-difference-and-which-one-should-you-use-3ba7fc285378)
- [Agentic RAG enterprise guide 2026 — Data Nucleus](https://datanucleus.dev/rag-and-agentic-ai/agentic-rag-enterprise-guide-2026)
- [RAG vs GraphRAG: Systematic Evaluation — arXiv 2502.11371](https://arxiv.org/html/2502.11371v3)
- [When to use Graphs in RAG — arXiv 2506.05690](https://arxiv.org/pdf/2506.05690)
- [RAPTOR — arXiv 2401.18059](https://arxiv.org/html/2401.18059v1)
- [Long Context vs RAG: Evaluation and Revisits — arXiv 2501.01880](https://arxiv.org/abs/2501.01880)
- [Anthropic Contextual Retrieval](https://www.anthropic.com/news/contextual-retrieval)
- [Contextual Retrieval guide — DataCamp](https://www.datacamp.com/tutorial/contextual-retrieval-anthropic)
- [Late Chunking — Jina AI](https://jina.ai/news/late-chunking-in-long-context-embedding-models/) · [arXiv 2409.04701](https://arxiv.org/pdf/2409.04701)
- [Late Chunking vs Contextual Retrieval — KX/Medium](https://medium.com/kx-systems/late-chunking-vs-contextual-retrieval-the-math-behind-rags-context-problem-d5a26b9bbd38)
- [ColPali — arXiv 2407.01449](https://arxiv.org/abs/2407.01449)
- [Late Interaction overview (ColBERT/ColPali/ColQwen) — Weaviate](https://weaviate.io/blog/late-interaction-overview)
- [Nemotron ColEmbed V2 — arXiv 2602.03992](https://arxiv.org/html/2602.03992v1)
- [HippoRAG 2 / From RAG to Memory — arXiv 2502.14802](https://arxiv.org/pdf/2502.14802)
- [HippoRAG 2 overview — MarkTechPost](https://www.marktechpost.com/2025/03/03/hipporag-2-advancing-long-term-memory-and-contextual-retrieval-in-large-language-models/)
- [Structured RAG for Aggregative Questions — arXiv 2511.08505](https://arxiv.org/pdf/2511.08505)
- [Aggregation Queries over Unstructured Text — arXiv 2602.01355](https://arxiv.org/html/2602.01355)
- [From RAG to Context — 2025 year-end RAG review, RAGFlow](https://ragflow.io/blog/rag-review-2025-from-rag-to-context)
- [LanceDB docs / embeddings](https://docs.lancedb.com/)
