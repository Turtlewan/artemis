# Research: GraphRAG landscape for Artemis

**Date:** 2026-06-08
**Re-research after:** 2026-06-22 (14d, AI tooling moves fast)
**Authored by:** Research agent (Claude Sonnet 4.6)
**Context:** Stress-testing ADR-007 decision to defer a knowledge graph layer behind a `retrieve(query, mode)` port in favour of agentic multi-hop over LanceDB hybrid search.

---

## Summary

LazyGraphRAG is **not yet open-sourced** in the main GraphRAG library as of June 2026 — it remains an Azure/Microsoft Discovery enterprise feature with a long-broken integration promise. The OSS graph-RAG field has matured significantly since mid-2025, but the fundamental cost-quality tradeoff for **small local models** has not flipped: relation extraction still degrades badly below ~14B parameters. The 2026 consensus from peer-reviewed benchmarks confirms that agentic multi-hop RAG narrows but does not erase GraphRAG's advantage on complex multi-hop queries — and for a personal-scale corpus the gap is even smaller. The ADR-007 decision to defer the graph layer remains defensible today. The clearest trigger for un-deferring would be access to a 30B+ local model (M5 Ultra/Max hardware, H2 2026), which would put LightRAG or Graphiti within viable reach.

---

## Key Findings (tagged)

### 1. LazyGraphRAG OSS status

- Microsoft announced LazyGraphRAG in November 2024 as 0.1% the indexing cost of full GraphRAG (no pre-summarisation, iterative-deepening search). [VERIFIED — https://www.microsoft.com/en-us/research/blog/lazygraphrag-setting-a-new-standard-for-quality-and-cost/]
- As of May 2026 it is deployed in **Microsoft Discovery** (Azure enterprise) and Azure Local public preview, but has **not been merged into the `microsoft/graphrag` OSS library**. [VERIFIED — GitHub discussion #1490, last maintainer update Dec 2024; latest release v3.1.0 May 28 2026 contains no LazyGraphRAG. https://github.com/microsoft/graphrag/discussions/1490]
- Community frustration is high; maintainers gave a Q1-Q2 2026 target that was missed. Multiple community members are treating the project as effectively stalled for this feature. [VERIFIED — github.com/microsoft/graphrag/discussions/1490]
- The technical paper described the algorithm as combining BFS+DFS iterative-deepening over a **pre-built graph**, so it still requires the expensive entity-extraction index — it just defers community summarisation. [VERIFIED — Microsoft Research blog]

**Verdict: LazyGraphRAG is still not OSS. Do not plan around it.**

### 2. Small-model relation extraction quality threshold

- A benchmark study (arxiv 2605.20815) running Llama 3.1 8B, Mistral 7B, Qwen 2.5 7B, and Phi-4-mini 3.8B on the MS-GraphRAG pipeline against an EHR dataset found: models below ~7B (quantised Q4) cannot reliably complete the pipeline (JSON schema failures during summarise_entity_description stage). [VERIFIED — https://arxiv.org/html/2605.20815]
- Qwen 2.5 7B produced the best answer quality (3.3/5) despite fewest extracted entities (330 vs Llama's 1,172). There is a notable decoupling: more entities ≠ better answers. [VERIFIED — ibid]
- LightRAG explicitly recommends **32B minimum parameters** for its extraction workflow, citing extraction accuracy degradation below that threshold. [VERIFIED — https://github.com/HKUDS/LightRAG README, May 2026]
- Artemis currently runs Qwen3-4B/14B. The 14B is marginal for entity extraction (above the 7B floor, below the 32B sweet spot). Quality will be noticeably degraded vs a 30B+ model. [ASSUMED based on above data — no direct 14B extraction quality benchmark found]
- Structured-output / JSON schema failures are the most common failure mode for sub-14B models in extraction pipelines; Qwen3-14B has strong instruction following which likely reduces (but does not eliminate) this risk. [ASSUMED from community observations]

### 3. Graph-RAG vs agentic multi-hop: 2026 consensus

- arxiv 2604.09666 "Do We Still Need GraphRAG?" (April 2026): introduces RAGSearch benchmark; finds that **agentic search substantially narrows the gap to GraphRAG** (especially RL-based agentic), but GraphRAG still wins on complex multi-hop with more stable behaviour when its offline cost is amortised. Conclusion: complementary roles, not substitutes. [VERIFIED — https://arxiv.org/abs/2604.09666]
- arxiv 2506.05690 "When to use Graphs in RAG" (June 2025): finds basic RAG equals or beats GraphRAG on **simple fact retrieval**; GraphRAG excels on multi-hop reasoning and contextual synthesis. MS-GraphRAG(global) uses ~40,000 tokens per answer; HippoRAG2 ~1,000 tokens. [VERIFIED — https://arxiv.org/html/2506.05690v3]
- A-RAG (arxiv 2602.03442): hierarchical agentic RAG achieves 94.5% on HotpotQA, 89.7% on 2WikiMultiHop — closing most of the gap via iterative retrieval without a pre-built graph. [VERIFIED — https://arxiv.org/pdf/2602.03442]
- For a **personal corpus** (one user's notes/emails/docs — typically <10K documents, well-structured, no massive entity overlap): the multi-hop query load is lower; graph's advantage is most pronounced on large enterprise knowledge bases where implicit relationships are dense and buried. [COMMUNITY — synthesis of above papers + https://medium.com/@Micheal-Lanham/pipeline-rag-vs-agentic-rag-vs-knowledge-graph-rag-what-actually-works-and-when-47a26649a457]
- 2026 emerging best practice: **adaptive routing** — query classifier sends simple questions to vector RAG, complex multi-hop to agentic loop, relationship-heavy queries to graph. [COMMUNITY — https://blog.starmorph.com/blog/rag-techniques-compared-best-practices-guide]

### 4. What changed since mid-2025 that could justify un-deferring

- **HippoRAG 2** (MIT, Feb 2025): PageRank-based, NeurIPS'24, MuSiQue F1 up from 44.8→51.9, 2WikiMultiHopQA Recall@5 76.5→90.4%. Uses significantly less offline indexing cost than GraphRAG/LightRAG. Supports OpenAI-compatible local endpoints. BUT: tested primarily with Llama-3.1-8B/70B; no specific Qwen3 results. [VERIFIED — https://github.com/osu-nlp-group/hipporag, https://www.emergentmind.com/topics/hipporag-2]
- **LightRAG v1.5.0** (MIT, June 2026): EMNLP 2025 paper, dual-level graph (local entity + global concept), incremental updates without full re-index, Ollama/vLLM/OpenAI-compatible. BUT: 32B minimum LLM recommendation is a hard blocker on Artemis's current hardware. [VERIFIED — https://github.com/HKUDS/LightRAG]
- **Graphiti v0.29.1** (Apache-2.0, Zep AI, May 2026): temporal knowledge graph, episodic incremental ingestion, bi-temporal model, supports Neo4j/FalkorDB/Kuzu/Amazon Neptune. Explicit Ollama support. BUT: warns that small models produce structured output failures; recommends "most capable model you can run." [VERIFIED — https://github.com/getzep/graphiti]
- **fast-graphrag** (MIT, circlemind-ai): PageRank/HippoRAG-style, incremental ingestion, OpenAI-compatible endpoint, no formal releases published. Structured output failures documented for models under 14B. Active but pre-1.0. [VERIFIED — https://github.com/circlemind-ai/fast-graphrag]
- **nano-graphrag** (gusye1234): hackable minimal implementation, MIT, supports local Huggingface models, incremental insertion via md5 dedup. Very lightweight but research/prototype grade. [VERIFIED — https://github.com/gusye1234/nano-graphrag]
- **Microsoft GraphRAG v3.1.0** (MIT, May 2026): active development, no LazyGraphRAG, Azure-centric additions (CosmosDB). Requires large LLM for community summaries — not practical on small local model. [VERIFIED — https://github.com/microsoft/graphrag/releases]
- **MLX on M5**: Apple published benchmarks showing Qwen3 30B-A3B (MoE, 3B active) runs at ~1.25x M4 speed on M5, 17GB memory, sub-3s time-to-first-token. [VERIFIED — https://machinelearning.apple.com/research/exploring-llms-mlx-m5]
- **M5 Max/Ultra hardware**: M5 Max MacBook Pros available March 2026 (up to 128GB); M5 Ultra Mac Studio expected October 2026 (up to 192GB). This is the hardware thread that could unlock 30B-70B dense local models. [VERIFIED — https://www.macworld.com/article/2942089/macbook-pro-m5-pro-max-release-specs-price.html]

### 5. Stronger local model impact on recommendation

- Qwen3 30B-A3B (MoE) runs on current M4 48GB at ~68+ tok/s in 4-bit MLX; fits within 18GB memory headroom. **This model is borderline usable on current hardware.** [VERIFIED — https://codersera.com/blog/run-qwen3-vl-30b-a3b-thinking-on-macos-installation-guide/]
- A 30B+ model clears LightRAG's 32B recommendation threshold (30B-A3B activates ~3B per token — whether this satisfies LightRAG's extraction quality intent is uncertain). [ASSUMED — MoE active-parameter vs dense-parameter equivalence for extraction tasks is not established]
- A Qwen3-32B dense model or any model ≥30B dense on M5 Max/Ultra hardware would reliably clear all extraction thresholds for LightRAG and Graphiti. [COMMUNITY — synthesis of benchmarks above]
- **The graph question should be re-evaluated when/if**: (a) Artemis upgrades to M5 Max/Ultra hardware OR (b) a 32B+ dense model runs acceptably on current 48GB M4 hardware.

---

## OSS GraphRAG Options Comparison Table

| Tool | License | Version (June 2026) | Incremental | Min LLM for extraction | Local/OAI-compat | Small-model quality | Personal corpus fit | Status |
|------|---------|---------------------|-------------|------------------------|------------------|--------------------|--------------------|--------|
| **LazyGraphRAG** (Microsoft) | Not OSS | N/A | — | Unknown (needs pre-built graph) | No (Azure only) | Unknown | N/A | Blocked — not released |
| **Microsoft GraphRAG** | MIT | v3.1.0 | No (full re-index) | ~30B+ for summaries | Yes (OAI-compat) | Poor <14B | Poor (too heavy) | Active, Azure-centric |
| **LightRAG** | MIT | v1.5.0 | Yes (set-merge) | Recommends 32B | Yes (Ollama/vLLM) | Degrades <32B | Marginal today | Active, EMNLP'25, strong |
| **Graphiti** | Apache-2.0 | v0.29.1 | Yes (episodic) | "Most capable possible"; warns on small | Yes (Ollama) | Schema failures <14B | Good if 30B+ available | Active, Zep AI, temporal focus |
| **HippoRAG 2** | MIT | Feb 2025 | Partial (no live docs) | ~8B workable; 70B for best results | Yes (OAI-compat vLLM) | Acceptable at 8B | Best small-model option | Active, NeurIPS'24 |
| **fast-graphrag** | MIT | Pre-release (249 commits) | Yes | ~14B+ for schema reliability | Yes (OAI-compat) | Fails <14B documented | Possible at 14B | Active but pre-1.0, no releases |
| **nano-graphrag** | MIT | 0.x (hackable) | Yes (md5 dedup) | Configurable | Yes (HuggingFace) | Depends on config | Research/prototype grade | Low activity 2025-26 |

**Key:** OAI-compat = OpenAI-compatible API endpoint (mlx-lm, Ollama, vLLM all qualify)

---

## Graph vs Agentic Multi-hop Verdict

For Artemis's specific profile — one user's personal corpus (notes, emails, docs), privacy-first, small local model (Qwen3-4B/14B), Apple Silicon M4 48GB:

**Agentic multi-hop wins on:**
- Cost: zero offline indexing LLM calls; no graph build latency
- Maintenance: no graph staleness problem; ingestion is just chunking + embedding
- Query coverage: simple and moderate queries handled well; iterative loop handles most "connect the dots" cases
- Model fit: works with 4B/14B today; does not require 32B for correctness
- Small corpus: personal corpus has fewer implicit relationships than enterprise KB; graph's density advantage doesn't materialise as strongly

**Graph-RAG wins on:**
- Complex multi-hop where the chain of reasoning is 3+ hops through implicit relationships (e.g. "who influenced person X's thinking on topic Y via work Z")
- Relationship-discovery queries ("what connects A and B") where the connection is not surfaced by vector similarity
- Recall stability: agentic loop can terminate early; graph traversal is more exhaustive
- Large, dense corpora: value scales with relationship density

**For Artemis today:** agentic multi-hop is the right call. The benchmarks (2604.09666) confirm it narrows the gap substantially, and the personal-corpus context further reduces the delta. The 40x token overhead of MS-GraphRAG global vs HippoRAG2's ~1,000 tokens illustrates that even the most efficient graph approaches are expensive per-query relative to iterative vector retrieval.

---

## Recommendation

**Keep the graph layer deferred behind the `retrieve(query, mode)` port. ADR-007 holds.**

Rationale:
1. LazyGraphRAG is not OSS and timeline is unreliable — cannot be planned around.
2. All viable OSS graph options (LightRAG, Graphiti) require 30B+ LLM for reliable extraction; Qwen3-14B is below threshold.
3. 2026 benchmarks confirm agentic multi-hop narrows the quality gap enough that the extraction cost is not justified for a personal corpus.
4. The port design is correct — the decision is reversible at low cost.

**Revisit triggers (prioritised):**

1. **Hardware upgrade to M5 Max/Ultra** (≥64GB, expected H2 2026): unlocks Qwen3-32B dense or 30B+ dense at practical speeds. Re-evaluate LightRAG or Graphiti at that point.
2. **Agentic multi-hop proves empirically insufficient** for Artemis's own queries (e.g. user reports consistent connect-the-dots failures). Log these as evidence.
3. **LazyGraphRAG merges into microsoft/graphrag** OSS with local-model support — check the GitHub releases page on the 2026-06-22 re-research cycle.
4. **fast-graphrag cuts a v1.0 release** and documents 14B extraction quality — it is the lowest-friction candidate for Artemis's current hardware if quality holds.

**If re-evaluating with a 30B+ model**, the recommended candidate is **LightRAG v1.5.0** (MIT, incremental, dual-level graph, EMNLP'25 peer-reviewed, most actively maintained, best documented Ollama path). Second choice: **Graphiti** if temporal/episodic tracking of fact changes matters.

---

## Assumptions & Gaps

| # | Assumption / Gap | Impact |
|---|-----------------|--------|
| A1 | Qwen3-14B structured output quality for entity extraction is untested — inferred from 7B benchmarks + model family reputation | Medium — may be better than assumed |
| A2 | Qwen3 30B-A3B MoE "activates 3B parameters" — whether this satisfies LightRAG's 32B extraction quality intent is not established | High — needs direct empirical test |
| A3 | LazyGraphRAG algorithm still requires a pre-built graph (entity extraction) — deferred community summaries only; cost claim may be overstated for total pipeline | Medium |
| A4 | HippoRAG 2 incremental ingestion path is "partial" — the paper describes offline batch; live incremental doc addition is not well-documented | Medium for production use |
| A5 | Personal corpus size not quantified — if Artemis's corpus grows to 50K+ documents, graph value proposition increases | Low for near-term |
| A6 | No direct benchmark of agentic multi-hop on Artemis's actual query distribution exists | Medium — empirical logging would validate |

---

## Sources

1. [LazyGraphRAG announcement — Microsoft Research Blog](https://www.microsoft.com/en-us/research/blog/lazygraphrag-setting-a-new-standard-for-quality-and-cost/)
2. [LazyGraphRAG OSS timeline discussion — microsoft/graphrag #1490](https://github.com/microsoft/graphrag/discussions/1490)
3. [microsoft/graphrag releases](https://github.com/microsoft/graphrag/releases)
4. [Do We Still Need GraphRAG? — arxiv 2604.09666](https://arxiv.org/abs/2604.09666)
5. [When to use Graphs in RAG — arxiv 2506.05690](https://arxiv.org/abs/2506.05690)
6. [GraphRAG on Consumer Hardware (Qwen 7B benchmarks) — arxiv 2605.20815](https://arxiv.org/html/2605.20815)
7. [A-RAG hierarchical agentic retrieval — arxiv 2602.03442](https://arxiv.org/pdf/2602.03442)
8. [LightRAG GitHub (HKUDS/LightRAG, v1.5.0, MIT)](https://github.com/HKUDS/LightRAG)
9. [Graphiti GitHub (getzep/graphiti, v0.29.1, Apache-2.0)](https://github.com/getzep/graphiti)
10. [fast-graphrag GitHub (circlemind-ai, MIT)](https://github.com/circlemind-ai/fast-graphrag)
11. [HippoRAG GitHub (OSU-NLP-Group, MIT)](https://github.com/osu-nlp-group/hipporag)
12. [nano-graphrag GitHub (gusye1234, MIT)](https://github.com/gusye1234/nano-graphrag)
13. [Apple MLX M5 LLM benchmarks](https://machinelearning.apple.com/research/exploring-llms-mlx-m5)
14. [Qwen3-VL-30B on macOS MLX guide](https://codersera.com/blog/run-qwen3-vl-30b-a3b-thinking-on-macos-installation-guide/)
15. [MacBook Pro M5 Pro/Max specs — Macworld](https://www.macworld.com/article/2942089/macbook-pro-m5-pro-max-release-specs-price.html)
16. [GraphRAG vs HippoRAG vs PathRAG comparison — Medium/Graph Praxis](https://medium.com/graph-praxis/graphrag-vs-hipporag-vs-pathrag-vs-og-rag-choosing-the-right-architecture-for-your-knowledge-graph-a4745e8b125f)
17. [RAG architecture patterns 2026 — Starmorph blog](https://blog.starmorph.com/blog/rag-techniques-compared-best-practices-guide)
18. [HippoRAG 2 coverage — Emergent Mind](https://www.emergentmind.com/topics/hipporag-2)
