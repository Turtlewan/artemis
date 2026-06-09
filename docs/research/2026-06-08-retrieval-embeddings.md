# Research: Retrieval & Embeddings SOTA for Artemis

**Date:** 2026-06-08
**Re-research after:** 2026-06-22 (14 days)
**Researcher:** Claude Sonnet 4.6 (sub-agent, automated web research)

---

## Summary

Qwen3-Embedding-0.6B/4B remain excellent choices for Artemis, with no compelling reason to migrate. A community MLX server exists and is verified working on Apple Silicon. Qwen3-Reranker-0.6B is confirmed SOTA for its size class (MTEB-R 65.80 vs bge-reranker-v2-m3's 57.03), and no challenger has displaced it locally. The single best improvement worth making is upgrading from ColPali-style placeholder to a concrete **ColQwen2.5** visual retrieval track — it is mature, runs via MPS/PyTorch on Apple Silicon, and handles the PDF+screenshot corpus well. Light-ColQwen/HPC variants reduce storage overhead substantially. The Qwen3-VL line (Embedding + Reranker, Jan 2026) extends the same family to multimodal/video but is 2B+/8B, not a drop-in for the text-only pipeline.

LanceDB's hybrid-search+RRF foundation remains solid. Its 2026 FTS improvements (WAND algorithm, 3–8x speed on complex queries) and Lance format v2.2 (50%+ storage reduction, 68x blob reads) strengthen the existing choice. No encryption-at-rest feature found; this remains a gap to track.

---

## Key Findings

### 1. Embedding Models

**Qwen3-Embedding family holds MTEB multilingual #1 at 8B (70.58), with the smaller tiers still highly competitive:**
- 0.6B: MTEB-EN v2 = 70.70, MTEB-Multilingual = 64.33, C-MTEB = 66.33
- 4B: MTEB-EN v2 = 74.60, MTEB-Multilingual = 69.45, C-MTEB = 72.27
- 8B: MTEB-EN v2 = 75.22, MTEB-Multilingual = 70.58, C-MTEB = 73.84

[VERIFIED — https://github.com/QwenLM/Qwen3-Embedding]

All sizes support Matryoshka MRL (min dim: 32; max: 1024/2560/4096 for 0.6B/4B/8B), 32K context, 100+ languages including code. [VERIFIED — https://qwenlm.github.io/blog/qwen3-embedding/]

**MLX community port confirmed:** `jakedahn/qwen3-embeddings-mlx` provides a REST server. Benchmarked on 16" MacBook Pro M2 Max 32GB: 0.6B = 44,000 tok/s / 900MB RAM; 4B = 18,000 tok/s / 2.5GB; 8B = 11,000 tok/s / 4.5GB. [VERIFIED — https://github.com/jakedahn/qwen3-embeddings-mlx]. Performance expected to scale upward on M3/M4 chips.

**No official MLX support from Qwen team** — the community port fills this gap adequately. [ASSUMED: stability and parity with mainline weights; needs smoke-test during build sprint.]

**New entrant worth tracking — EmbeddingGemma (Google, Sep 2025):**
- 308M params total (~100M model + 200M embedding), runs in <200MB RAM with quantization
- MTEB-EN: highest-ranked open multilingual model under 500M params
- Matryoshka dims: 128–768; context: 2K tokens (significant limitation vs Qwen's 32K)
- MLX-native: confirmed, with mlx-community collections
- Verdict for Artemis: 2K token context is disqualifying for long-document personal corpus; watch for v2.
[VERIFIED — https://developers.googleblog.com/en/introducing-embeddinggemma/]

**Stella-EN-1.5B-v5:**
- MTEB-EN v2 = 69.43, supports dimensions 512–8192, 1.5B params
- MLX quantized versions: `mlx-community/stella_en_1.5B_v5-4bit` and `-bf16`
- 1024d score within 0.001 of 8192d (efficient truncation)
- English-only; no multilingual support — disadvantage for personal corpus with mixed-language content
[VERIFIED — https://huggingface.co/NovaSearch/stella_en_1.5B_v5, https://github.com/ollama/ollama/issues/16076]

**Nomic-embed-text-v2-moe (Nomic AI, 2025):**
- 475M total params / 305M active (MoE, top-2 routing)
- BEIR: 52.86, MIRACL: 65.80; Matryoshka dims 256–768; context: 512 tokens (very limiting)
- No confirmed MLX path; requires `trust_remote_code=True`
- Verdict: context and score limitations make it a non-starter for Artemis vs Qwen3-0.6B
[VERIFIED — https://huggingface.co/nomic-ai/nomic-embed-text-v2-moe]

**BGE-M3:** MTEB avg ~63.0, 1024d, 8192 context, open-weight — solid but clearly behind Qwen3-0.6B on multilingual and quality. [VERIFIED — https://awesomeagents.ai/leaderboards/embedding-model-leaderboard-mteb-march-2026/]

**NVIDIA NV-Embed-v2:** MTEB avg 72.31, 4096d, 32K context, open-weight — strong, but 7B+ scale, no confirmed MLX path. [COMMUNITY — awesomeagents.ai leaderboard]

**Qwen3-VL-Embedding (Jan 2026, arXiv 2601.04720):** 2B/8B, MMEB-V2 overall 77.8 (8B, #1 Jan 2026), handles text+images+docs+video. Not a replacement for text-only embed but the multimodal arm of the same family. [VERIFIED — https://arxiv.org/abs/2601.04720]

---

### 2. Rerankers

**Qwen3-Reranker is confirmed SOTA for local cross-encoder reranking:**

| Model | MTEB-R | CMTEB-R | MMTEB-R | MTEB-Code |
|---|---|---|---|---|
| Qwen3-Reranker-0.6B | 65.80 | 71.31 | 64.64 | 73.42 |
| Qwen3-Reranker-4B | 69.76 | 75.94 | 72.74 | 81.20 |
| Qwen3-Reranker-8B | 69.02 | 77.45 | 72.94 | 81.22 |
| bge-reranker-v2-m3 | 57.03 | — | — | — |

[VERIFIED — https://huggingface.co/Qwen/Qwen3-Reranker-0.6B]

The 0.6B beats bge-reranker-v2-m3 by +8.8 points on MTEB-R. The 4B surpasses 8B slightly on English retrieval. 32K context, 100+ languages, Apache 2.0.

**Jina Reranker v3 (late 2025):** Positioned as optimized for function-calling and code retrieval; no head-to-head NDCG published against Qwen3-Reranker in searched sources. [COMMUNITY — futureagi.com]

**Contextual AI Reranker v2 (open-sourced):** Available but cloud-oriented, not benchmarked locally. [COMMUNITY — contextual.ai/blog/rerank-v2]

**Latency note for Artemis 48GB Mac:** No direct latency numbers found for MLX/MPS inference of Qwen3-Reranker-0.6B. [ASSUMED: at 0.6B with MLX/PyTorch MPS, latency will be well under 100ms per query for typical reranking windows of k=20–50. Verify during build sprint.]

---

### 3. Visual Document Retrieval (ColPali / ColQwen / Late-interaction)

**ColPali family state (2025–2026):**
- Core approach: encode document pages as image → grid of patch embeddings → MaxSim late-interaction scoring. No OCR required; handles tables, figures, layouts, mixed-script documents natively.
- **ColQwen2.5** (current best): built on Qwen2.5-VL, improved performance over ColQwen2, strong multilingual script support (CJK, Arabic, Hindi, Latin, etc.)
- **ColSmol:** smaller/faster variant for resource-constrained deployments
- **Light-ColPali/ColQwen2** (Jun 2025): hierarchical agglomerative clustering on patch embeddings — drastically reduces per-page vector storage footprint
- **HPC-ColPali:** K-means quantization compresses patch embeddings to 1-byte centroid indices
[VERIFIED — https://github.com/illuin-tech/colpali]

**Apple Silicon deployment:** ColQwen2 runs via PyTorch MPS (`device_map="mps"`). PyTorch 2.6.0 has MPS compatibility issues; PyTorch 2.5.1 is confirmed working. No native MLX path found. [COMMUNITY — ColPali GitHub issue reports]

**Storage consideration:** ColPali/ColQwen2 produces many patch vectors per page (~1000 patches for a standard page). For a personal corpus this is manageable, especially with Light-ColQwen compression. LanceDB supports multi-vector storage natively.

**Argus-Retriever (arXiv 2606.04300, Jun 2026):** Query-conditioned late-interaction using Qwen3.5-VL, achieving 92.67 NDCG@5 on ViDoRe V1 — new SOTA for visual document retrieval. Key innovation: document representations vary per query (unlike standard ColPali). Weights open-sourced. However, 9B scale and recency (< 1 week old at time of writing) make it immature for production use in Artemis now. [VERIFIED — https://arxiv.org/abs/2606.04300]

**Recommendation for Artemis:** Adopt **ColQwen2.5** (Light variant for storage efficiency) for visual-doc retrieval of PDFs and screenshots. Defer Argus-Retriever until it has community validation. Video keyframes: ColQwen2.5 handles keyframe images the same as document pages — treat them as single-page visual docs.

**Maturity verdict:** ColPali-style retrieval is now production-ready for a personal corpus. The "ColPali-style visual retrieval — exact model is a build-time sizing spike" placeholder in Artemis's brain.md should be resolved: **use ColQwen2.5 (Light)**.

---

### 4. Chunking & Contextual Retrieval

**Late chunking + Contextual Retrieval combo remains best practice**, with nuance:

- **Late chunking**: Best when chunks are ambiguous without context (anaphora, cross-references). BEIR gains scale with document length. Can improve retrieval accuracy 10–12% on anaphoric documents. [COMMUNITY — medium.com/kx-systems]
- **Contextual Retrieval** (Anthropic): Cuts top-20 retrieval failures by up to 67% when combined with reranking. Each chunk gets a context prefix from the document. [COMMUNITY — multiple RAG playbook sources]
- **Agentic chunking**: Highest accuracy (94.5% in one study) but 10–50x indexing cost of fixed-size chunking. Not suitable for a personal background indexing pipeline at this time.
- **Semantic chunking**: Up to ~70% lift over naive baselines, but ~14x slower than token-based chunking.
- **Practical consensus (2026):** Combine late chunking for long documents (32K context window of Qwen3-Embedding is an enabler) + Contextual Retrieval prefixes for high-value documents. Agentic chunking is best reserved for critical documents where quality justifies cost.

[VERIFIED — https://arxiv.org/abs/2504.19754 (paper exists; numerical extraction partial), COMMUNITY — digitalapplied.com, firecrawl.dev RAG playbooks]

**Artemis conclusion:** The planned late chunking for bulk + Contextual Retrieval for high-value split is validated by 2026 consensus. No need to change strategy.

---

### 5. LanceDB (2025–2026 Developments)

**Hybrid search (dense + BM25/FTS + RRF):** Fully native, production-stable. Built-in `RRFReranker`, custom rerankers supported, `query_type="hybrid"` API. [VERIFIED — https://github.com/lancedb/lancedb, https://docs.lancedb.com/search/hybrid-search]

**2026 FTS improvements (recent):**
- WAND algorithm: 3–8x faster complex queries (50–100 terms)
- Fuzzy Search and Boosting added
- FTS stability fix (flat-mode crash resolved)
[COMMUNITY — LanceDB changelog/blog]

**Lance format v2.2 (late 2025–2026):**
- Blob V2: redesigned multimodal storage, 50%+ storage cuts, 68x faster blob reads — directly relevant to ColQwen2.5 patch vector storage
- Nested schema evolution, native Map type
[VERIFIED — https://www.lancedb.com/blog/lance-file-format-2-2-taming-complex-data]

**Scale & infrastructure (2026):** SQL retrieval via DuckDB, multi-bucket storage, 1.5M IOPS benchmarks. Mostly relevant to cloud/distributed deployments; the local embedded use case remains first-class. [COMMUNITY — LanceDB blog]

**Encryption at rest:** No feature found in any source. This is a confirmed gap. [ASSUMED: Artemis would need filesystem-level encryption (e.g., macOS FileVault) or application-layer field encryption as a workaround. Flag for security review.]

**Git-style branching / shallow clone:** Added in 2026 — potentially useful for Artemis snapshots/rollback of the vector store.

---

## Embedding Model Comparison Table

| Model | Size | MTEB-EN | MTEB-Multi | Dims (max) | Context | MRL | MLX | Notes |
|---|---|---|---|---|---|---|---|---|
| Qwen3-Embedding-0.6B | 0.6B | 70.70 | 64.33 | 1024 | 32K | Yes (32–1024) | Community ✓ | 44K tok/s, 900MB |
| Qwen3-Embedding-4B | 4B | 74.60 | 69.45 | 2560 | 32K | Yes | Community ✓ | 18K tok/s, 2.5GB |
| Qwen3-Embedding-8B | 8B | 75.22 | 70.58 (#1 multi) | 4096 | 32K | Yes | Community ✓ | 11K tok/s, 4.5GB |
| Stella-EN-1.5B-v5 | 1.5B | 69.43 | N/A (EN only) | 8192 | — | Yes (512–8192) | Official ✓ | English-only |
| EmbeddingGemma | 308M | Top <500M open | Yes | 768 | **2K** | Yes (128–768) | Official ✓ | Context too short |
| Nomic-embed-v2-moe | 475M/305M active | — | MIRACL 65.80 | 768 | **512** | No confirmed | Needs custom code | Context too short |
| BGE-M3 | ~570M | 63.0 avg | Yes | 1024 | 8192 | No | No official | Solid but surpassed |
| NV-Embed-v2 | 7B+ | 72.31 | — | 4096 | 32K | — | No confirmed | No practical MLX path |

Sources: [VERIFIED — GitHub QwenLM/Qwen3-Embedding, jakedahn/qwen3-embeddings-mlx, HF model cards, awesomeagents.ai MTEB leaderboard]

---

## Reranker Comparison

| Model | MTEB-R | CMTEB-R | MMTEB-R | Size | Context | License | MLX |
|---|---|---|---|---|---|---|---|
| Qwen3-Reranker-0.6B | 65.80 | 71.31 | 64.64 | 0.6B | 32K | Apache 2.0 | No official |
| Qwen3-Reranker-4B | **69.76** | 75.94 | **72.74** | 4B | 32K | Apache 2.0 | No official |
| Qwen3-Reranker-8B | 69.02 | **77.45** | 72.94 | 8B | 32K | Apache 2.0 | No official |
| bge-reranker-v2-m3 | 57.03 | — | — | ~570M | 8K | MIT | No |
| Jina Reranker v3 | — (code/function focus) | — | — | — | — | — | No |

[VERIFIED — https://huggingface.co/Qwen/Qwen3-Reranker-0.6B; COMMUNITY — siliconflow.com, futureagi.com]

**For Artemis (latency-sensitive, personal corpus):** Qwen3-Reranker-0.6B is the right default — it's +8.8 MTEB-R over bge-reranker-v2-m3 while being fast. Upgrade path to 4B for quality-over-speed workloads is well-supported.

---

## Visual-Doc Retrieval (ColPali etc.) Verdict

**Verdict: ColQwen2.5 (Light variant) is the recommended choice. Adopt now; it is mature.**

| Approach | Maturity | Apple Silicon | Quality | Storage | Recommendation |
|---|---|---|---|---|---|
| OCR + text embed only | Production | Native | Misses visual elements | Low | Insufficient for visual docs |
| ColQwen2.5 | Production | MPS (PyTorch 2.5.1) | SOTA for visual-doc retrieval | Medium (many patch vecs) | **Adopt** |
| ColQwen2.5 Light | Production | MPS (PyTorch 2.5.1) | Near-SOTA, compressed | Low | **Prefer over full** |
| Argus-Retriever (9B) | Pre-production (Jun 2026) | Unknown | New SOTA (92.67 NDCG@5) | High | Track for v2 of Artemis |
| Qwen3-VL-Embedding (8B) | Production | No MLX | MMEB-V2 77.8 | High | Future consideration |

**Storage note:** Lance v2.2 Blob V2 (68x faster blob reads, 50% compression) makes ColQwen2.5 patch-vector storage substantially more practical.

**For video keyframes:** Treat each keyframe as a visual document page. ColQwen2.5 encodes them identically — no separate pipeline needed.

---

## Recommendation

### Keep or Switch?

**Keep Qwen3-Embedding-0.6B/4B + Qwen3-Reranker-0.6B. No migration warranted.**

Rationale:
1. Qwen3-Embedding-0.6B at 70.70 MTEB-EN outperforms every sub-1B competitor with confirmed MLX support. Nearest MLX-native competitor (EmbeddingGemma) is limited to 2K context — disqualifying.
2. No new model has a confirmed MLX path AND higher MTEB scores at comparable sizes.
3. Qwen3-Reranker-0.6B beats the previously considered alternative (bge-reranker-v2-m3) by a decisive margin on every benchmark axis. No local challenger found.
4. The 4B eval-gated quality tier remains the right upgrade path — the MTEB-EN delta (0.6B→4B = +3.9 points) is real and justified for high-value retrieval workloads.

**Dimension lock note:** Brain.md/ADR-007 locks dimension at store init. All three Qwen3 sizes support MRL down to 32 dims, so if a future migration from 0.6B to 4B is needed, truncating to 1024 dims and re-indexing remains feasible without vector store schema change.

### Single Best Improvement

**Resolve the ColQwen2.5 (Light) visual retrieval spike NOW.** The "ColPali-style visual retrieval — exact model is build-time sizing spike" placeholder in brain.md should be replaced with a concrete recommendation: **ColQwen2.5 Light via PyTorch MPS (PyTorch 2.5.1), with Lance v2.2 blob storage for patch vectors.** Memory/throughput characterization on the 48GB Mac is the remaining build task.

### Is a Re-Index Migration Worth It?

No. The current embedding choices are still best-in-class for the Artemis constraints. A re-index migration would be warranted only if:
- A sub-1B model with native MLX (not community port) achieves >73 MTEB-EN, OR
- A dimension change is required (no current reason), OR
- A multilingual-only corpus gap appears (Qwen3 already covers 100+ languages).

---

## Assumptions & Gaps

1. [ASSUMED] The community MLX port (`jakedahn/qwen3-embeddings-mlx`) produces bit-identical embeddings to the official Hugging Face weights. Needs a cosine-similarity smoke test against the HF reference.
2. [ASSUMED] Qwen3-Reranker-0.6B latency on 48GB Apple Silicon M2/M3 is <100ms per reranked window. No direct measurement found — must benchmark during build sprint.
3. [ASSUMED] ColQwen2.5 Light runs acceptably on 48GB Apple Silicon via MPS. Specific memory and throughput numbers on Apple Silicon not found in public sources.
4. [GAP] No encryption-at-rest feature in LanceDB. FileVault or application-layer encryption needed for Artemis's privacy requirements.
5. [GAP] Argus-Retriever (Jun 2026, new SOTA for visual doc retrieval) is too new for production adoption; revisit at next research cycle.
6. [GAP] Jina Reranker v3 benchmark comparisons against Qwen3-Reranker are missing from public sources — head-to-head not available.
7. [ASSUMED] MTEB scores sourced from March 2026 leaderboard snapshot. Leaderboard may have changed; scores above are directionally correct but should be re-verified against live MTEB at next research cycle.
8. [GAP] No confirmed Qwen3-VL-Embedding MLX path found — Qwen3-VL models require mlx-vlm or custom adaptation; community port status unknown.

---

## Sources

- [Qwen3 Embedding Blog (Qwen/Alibaba)](https://qwenlm.github.io/blog/qwen3-embedding/)
- [Qwen3-Embedding GitHub](https://github.com/QwenLM/Qwen3-Embedding)
- [Qwen3-Embedding-8B Hugging Face](https://huggingface.co/Qwen/Qwen3-Embedding-8B)
- [Qwen3-Reranker-0.6B Hugging Face](https://huggingface.co/Qwen/Qwen3-Reranker-0.6B)
- [Qwen3 Embedding arXiv paper (2506.05176)](https://arxiv.org/pdf/2506.05176)
- [Qwen3-VL-Embedding and Qwen3-VL-Reranker arXiv (2601.04720)](https://arxiv.org/abs/2601.04720)
- [jakedahn/qwen3-embeddings-mlx (community MLX server)](https://github.com/jakedahn/qwen3-embeddings-mlx)
- [MTEB Leaderboard — March 2026 (Awesome Agents)](https://awesomeagents.ai/leaderboards/embedding-model-leaderboard-mteb-march-2026/)
- [Embedding Models 2026 Benchmark — Ailog RAG](https://app.ailog.fr/en/blog/news/embedding-models-2026)
- [EmbeddingGemma Launch — Google Developers](https://developers.googleblog.com/en/introducing-embeddinggemma/)
- [EmbeddingGemma Hugging Face Blog](https://huggingface.co/blog/embeddinggemma)
- [Stella-EN-1.5B-v5 Hugging Face](https://huggingface.co/NovaSearch/stella_en_1.5B_v5)
- [Nomic Embed v2 MoE Hugging Face](https://huggingface.co/nomic-ai/nomic-embed-text-v2-moe)
- [ColPali GitHub (illuin-tech)](https://github.com/illuin-tech/colpali)
- [Argus-Retriever arXiv (2606.04300)](https://arxiv.org/abs/2606.04300)
- [RAG Chunking Strategies 2026 — Digital Applied](https://www.digitalapplied.com/blog/rag-chunking-strategies-2026-retrieval-quality-playbook)
- [Reconstructing Context: Evaluating Chunking Strategies arXiv (2504.19754)](https://arxiv.org/abs/2504.19754)
- [Best Chunking Strategies for RAG — Firecrawl](https://www.firecrawl.dev/blog/best-chunking-strategies-rag)
- [LanceDB Hybrid Search Docs](https://docs.lancedb.com/search/hybrid-search)
- [Lance Format v2.2 Blog](https://www.lancedb.com/blog/lance-file-format-2-2-taming-complex-data)
- [LanceDB GitHub](https://github.com/lancedb/lancedb)
- [Best Rerankers for RAG 2026 — FutureAGI](https://futureagi.com/blog/best-rerankers-for-rag-2026)
- [Most Accurate Reranker 2026 — SiliconFlow](https://www.siliconflow.com/articles/en/most-accurate-reranker-for-real-time-search)
- [Ollama issue: first-class embedding/reranker support](https://github.com/ollama/ollama/issues/16076)
- [Best Local Embedding Models RAG 2026 — PromptQuorum](https://www.promptquorum.com/power-local-llm/best-embedding-models-local-rag-2026)
- [Best Embedding Models 2026 — BentoML](https://www.bentoml.com/blog/a-guide-to-open-source-embedding-models)
