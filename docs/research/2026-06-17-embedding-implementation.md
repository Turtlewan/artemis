# Embedding-layer implementation research — Artemis (M3 docs + M4 memory)

_Planning-mode research doc. 2026-06-17. Research only — no code, no spec change._
_Grounds out the PARKED "embedding tier" item (status.md) into a concrete, build-ready embedder + dimension + reranker + serving recommendation for the two dimension-locked vector stores._

---

## ⬛ Bottom line / recommendation — confidence: **HIGH**

> **Embedder:** **Qwen3-Embedding-0.6B** (MLX 4-bit/8-bit), served via **mlx-openai-server `/v1/embeddings`**.
> **Dimension:** **lock 1024** (the model's native default) in **both** stores' metadata. Do **not** truncate via MRL at personal scale — the storage/KNN saving is negligible and you'd trade away recall.
> **One model, not two:** the **same embedder + same 1024-dim** for M3 (LanceDB docs) **and** M4 (sqlite-vec memory). Operational simplicity + a single re-index migration story decisively beat any specialization argument at one-owner scale.
> **Reranker:** **Qwen3-Reranker-0.6B** (MLX), same family as the embedder. mlx-openai-server has **no `/v1/rerank`** endpoint → reach it through the chat-completions seam (constrained-decoded relevance score), exactly as M3-b already drafts.
> **Instruction prefix (the footgun):** Qwen3-Embedding is **asymmetric** — **queries** get an `"Instruct: {task}\nQuery:{q}"` prefix, **documents/facts get NO prefix**. This must be wired into the adapter, not the store.

**Plain-English:** Artemis already picked the right tools across its specs (Qwen3-Embedding-0.6B at 1024 dims, Qwen3-Reranker). This research confirms that pick against the 2026 field and nails down the two things the specs left soft: (a) keep both "filing cabinets" (documents and personal memory) using the **same ruler** (1024 numbers per item) so they never need separate upgrades, and (b) when you look something *up* you must phrase the lookup with a little "I'm searching for…" preamble, but when you *file* something you store it plain. Getting (b) wrong silently halves search quality with zero error message — it's the one easy mistake to guard against.

**Net effect on the corpus:** this **validates the locked defaults**; the only sharpening vs the current specs is (1) confirm 1024 (already the `embedding_dimension: int = 1024` default in M1-b/config) and (2) make the asymmetric query-prefix an explicit adapter responsibility (currently unstated). No locked decision is contradicted.

---

## Per-model comparison (2026 field, self-hostable-on-MLX lens)

| Model | Params | Native dim | MRL (truncatable) | Max ctx | Multilingual | License | MLX port | ~RAM (4-bit) | Verdict for Artemis |
|-------|--------|-----------|-------------------|---------|--------------|---------|----------|--------------|---------------------|
| **Qwen3-Embedding-0.6B** | 0.6B | **1024** | Yes (32–1024) | 32K | 100+ langs | Apache-2.0 | Yes (mlx-community, mlx-embeddings) | ~0.4–0.6 GB | **✅ RECOMMENDED — the pick** |
| Qwen3-Embedding-4B | 4B | 2560 | Yes | 32K | 100+ | Apache-2.0 | Yes | ~2.5 GB | Eval-gated quality tier (already noted in brain.md); dim ≠ 0.6B → a re-index, not a drop-in |
| Qwen3-Embedding-8B | 8B | 4096 | Yes | 32K | 100+ | Apache-2.0 | Yes | ~5 GB | MTEB-multilingual #1 (70.58, Jun-2025) but overkill + RAM-heavy for an always-resident embedder |
| EmbeddingGemma-300M | 0.3B | 768 | Yes (768→512/256/128) | 2K | 100+ | Gemma terms | Yes (MLX/Ollama/llama.cpp) | <0.3 GB | Strong on-device runner-up; **2K ctx kills late-chunking** (M3 wants long-context embed-then-pool) → disqualified for the docs path |
| BGE-M3 | 0.56B | 1024 | No | 8K | 100+ | MIT | Partial (community) | ~0.6 GB | Solid, multi-vector (dense+sparse+ColBERT) but **no MRL** + weaker instruction-awareness; documented fallback |
| Nomic-embed-text-v2 (MoE) | ~475M act. | 768 | Yes | ~512 useful | multilingual (v2) | Apache-2.0 | Partial | ~0.5 GB | Short effective ctx; MoE serving on MLX immature → not worth the risk |
| mxbai-embed-large-v1 | 0.34B | 1024 | partial (MRL-trained) | 512 | English-focused | Apache-2.0 | Yes | ~0.4 GB | English-only + 512 ctx → loses to Qwen3 on both axes |
| Snowflake arctic-embed 2.0 | 0.3–0.6B | 1024 | partial | 8K | multilingual (v2) | Apache-2.0 | community only | ~0.5 GB | Good, but no MLX-first momentum + no instruction-tuning edge over Qwen3 |

_Closed-API leaders (Gemini Embedding 2, Voyage, Cohere v4, OpenAI te-3-large) top the 2026 Milvus/CCKM benchmark but are **disqualified** — Artemis is local-first, sensitive memory must never leave the box (brain.md sensitivity router). They are listed only to confirm we're not missing a self-hostable contender that beats Qwen3._

---

## 1. Model candidates runnable via MLX in 2026

**Qwen3-Embedding (0.6B / 4B / 8B)** is the strongest self-hostable family and is already the Artemis pick. All three are Apache-2.0, 32K context, 100+ languages, **MRL-enabled**, and have MLX ports (`mlx-community/*`, convertible via `mlx-embeddings` / `mlx-lm`). The 0.6B at 1024 dims is the sweet spot for an always-resident embedder (brain.md budgets embeddings+reranker into the ~15GB resident set). The 8B holds MTEB-multilingual #1 (70.58 as of Jun-2025) — kept as the documented quality ceiling, not the default.

**EmbeddingGemma-300M** (Google, Sep-2025) is the headline on-device entrant: 768-dim, MRL to 512/256/128, <200MB RAM, 100+ langs, broad tooling incl. MLX. **But its 2K-token context is the dealbreaker for M3**, which relies on *late chunking* (embed a long context, then pool per chunk — brain.md/M3-a Task 6) — that needs the 32K window Qwen3 has. EmbeddingGemma would force a smaller, weaker chunking strategy. Fine for a phone; wrong for Artemis's doc corpus.

**BGE-M3 / Nomic-v2 / mxbai / arctic-embed 2.0** are all viable open models but each loses to Qwen3-0.6B on at least one axis Artemis cares about (no MRL, short context, English-only, or immature MLX serving). They are documented fallbacks, not reasons to switch.

**Technical note:** "MRL" (Matryoshka Representation Learning) = the model is trained so the *first N* dimensions of its vector are themselves a usable smaller embedding. You can slice 1024→256 and still get a coherent (lower-quality) vector. **Layman:** the model writes its answer "most-important facts first," so you can read just the top of the page and still get the gist.

## 2. Dimension strategy — lock **1024**, do not truncate

Qwen3-Embedding-0.6B is natively 1024 and MRL-truncatable to 256/128/etc. The temptation is to truncate for storage/speed. **Recommendation: don't, at Artemis scale.**

- **Memory (M4):** thousands–tens-of-thousands of facts (ADR-004). At 1024 float32, 50k vectors ≈ **205 MB** raw; sqlite-vec brute-force KNN over that is ~tens of ms (ADR-004 cites ~17ms @ 1M×128). Truncating to 256 saves ~150MB and a few ms — **invisible** on an M4/M5 Pro with 48–64GB, while measurably hurting recall on the owner's most precious store.
- **Documents (M3):** larger (life-corpus), but LanceDB uses a real ANN index (IVF/HNSW), so KNN cost scales sub-linearly and 1024-dim is standard. Storage at doc scale is still GBs, not a constraint on this box.
- **The asymmetry that matters:** truncation is **reversible only by re-embedding** (you can't recover dropped dims), and the dimension is **locked per store** (M3-a + M4-a both write `dimension` into metadata and refuse mismatches). Picking a smaller dim now to "save space" buys a migration later for a saving you won't feel. **Keep the full 1024; spend the trivial storage.**

**Plain-English:** MRL lets you store shorter, cheaper vectors. But your data is small enough that "cheaper" saves nothing you'd notice, while "shorter" makes search a bit dumber — and the choice is baked in per store, so changing your mind means re-processing everything. Use the full-length vector.

**If scale ever changes** (e.g. a massive media corpus), MRL truncation is the right lever to reach for *then*, on the docs store only, behind the re-index migration — not pre-emptively.

## 3. One model or two? — **ONE** (high confidence)

Use **one embedder + one dimension (1024)** across M3 (docs) and M4 (memory).

**Why one wins:**
- **Operational simplicity** — one model resident in mlx-openai-server, one `embedder` role in config, one instruction convention to get right, one upgrade to test. Two models = double the resident footprint, double the eval surface, double the migration cost, and a real risk of the asymmetric-prefix bug landing in only one path.
- **The dimension-lock makes "two" expensive forever** — each store independently locks its dim and treats a model change as a re-index migration. Two models = two migration tracks to maintain in perpetuity.
- **The specialization argument is weak here.** The theoretical case for two: a memory-tuned vs document-tuned embedder. In practice Qwen3-Embedding is a strong *general* retrieval model, and Artemis already gets task-specialization **for free** via the **instruction prefix** — you can pass a *different task instruction* for memory-fact queries vs document queries through the **same model** (§6), capturing most of the specialization benefit with zero extra model.

**Counter-consideration (documented, not adopted):** memory facts are short (subject-relation-object triples) while doc chunks are ~512 tokens; a hypothetical short-text-tuned model could edge out Qwen3 on facts. This does not survive the operational-cost test at one-owner scale — and the per-query instruction prefix already lets you tune retrieval intent per store. Revisit only if a memory-recall eval shows a real, measured gap.

**Plain-English:** Run one "translator" for both filing cabinets. Two translators would mean twice the upkeep and twice the chance of a silent bug, to win a quality difference you probably can't even measure. And you can already whisper a different "what I'm looking for" hint to the one translator depending on which cabinet you're searching.

## 4. Serving — mlx-openai-server `/v1/embeddings` (confirmed)

**mlx-openai-server does serve `/v1/embeddings`** (OpenAI-compatible), enabled with `--model-type embeddings --model-path <embedding-model>`. Current release **v1.8.1 (May 2026)**. This is exactly the seam M1-b's `OpenAIEmbeddingModel` adapter targets (`await /v1/embeddings` for the `embedder` role). ✅ The locked serving path is real and current.

**Quirks / things the build must know:**
- **Multi-model = subprocess-per-model.** In multi-model mode each model runs in a **spawned subprocess** — so the responder (Qwen3-4B), embedder (Qwen3-Embedding-0.6B), and reranker each occupy their own process. This matches brain.md's "one process, multiple resident models, on-demand load + idle-unload" intent but is worth confirming on-hardware at the M0-c runtime spike (RAM accounting: 3 resident MLX processes).
- **No documented embeddings batch-size cap**, but the adapter already batches per-document (`embed([...all chunks...])`, M3-a Task 6) — confirm a single large request doesn't OOM on the 0.6B at the M3 gated probe.
- **Qwen3-Embedding not in the README example list** (it shows Qwen3-Coder etc.) — it *should* work via the generic embeddings model-type, but this is the **one thing to verify at the M0-c / M1-b gated on-hardware step** (Task 5): serve `Qwen3-Embedding-0.6B` and confirm `/v1/embeddings` returns 1024-dim vectors. **Fallback if it doesn't load:** `mlx-embeddings` (Blaizzy) is a purpose-built MLX embedding server, or run the embedder via the `mlx-embeddings` library directly behind the same port. The port abstraction (ADR-015) makes this swap a config change.

**Confidence:** the endpoint exists (high); Qwen3-Embedding-specific serving on this exact server is **medium** until the gated probe — hence the named fallback.

## 5. Reranker pairing — Qwen3-Reranker-0.6B (same family)

**Qwen3-Reranker-0.6B** is the natural pair: same Qwen3 family as the embedder, 32K context, 100+ langs, MLX ports available (`mlx-community/Qwen3-Reranker-0.6B-mxfp8`, `*-mlx-8Bit`). This is already the M3-b pick (`QwenReranker` via the `reranker` role).

**Critical serving fact:** **mlx-openai-server has NO `/v1/rerank` endpoint** (confirmed against the v1.8.1 endpoint list — only chat/responses/embeddings/images/audio). So the reranker **cannot be a drop-in rerank API call**. M3-b already anticipates this with the right design: a `_score(query, texts) -> list[float]` seam that "falls back to constrained-decoded scores via `/v1/chat/completions`." **This research promotes that fallback to the *primary* path** — there is no native rerank endpoint to try first on this server. The build should treat chat-completions-with-constrained-score as *the* transport, not the fallback.

- **Alternative reranker:** `bge-reranker-v2-m3` (MIT, multilingual, widely MLX-converted) is the documented runner-up if Qwen3-Reranker's chat-scoring proves fiddly. Same family as BGE-M3; same `_score` seam.
- **Plain-English:** the reranker is the "second-opinion judge" that re-sorts the first batch of search hits. The serving software doesn't have a dedicated door for judges, so you ask the judge through the normal chat door, constrained to answer with just a relevance number.

## 6. Query vs document asymmetry — **the correctness footgun**

**Qwen3-Embedding uses an asymmetric instruction template:**
- **Queries** are wrapped: `"Instruct: {task_description}\nQuery:{query}"` — e.g. `Instruct: Given a search query, retrieve relevant passages\nQuery:where do I live`
- **Documents / passages / memory facts** get **NO instruction** — embed the raw text. Official guidance: *"No need to add instruction for retrieval documents."*

This is **load-bearing and silent-on-failure.** If the adapter prefixes documents too, or fails to prefix queries, retrieval quality degrades with **no error**. The Qwen team reports the instruction is worth **~1–5% retrieval quality** and is *required* to match published benchmark numbers.

**Where this must live (build guidance):** the asymmetry is an **`OpenAIEmbeddingModel` adapter responsibility**, not a store concern. But the M0-d port is symmetric — `async def embed(texts) -> list[Vector]` — it doesn't distinguish query from document. **This is a real gap to resolve at build time.** Options (for a future M1-b/M3/M4 amendment, NOT changing the locked port lightly):
- (a) Add an `embed_query` vs `embed_documents` distinction at the adapter (sentence-transformers convention), OR
- (b) Keep one `embed()` but have **callers** pass already-prefixed text (the retriever prefixes the query string before calling `embed`; ingestion/memory-write pass raw text). Option (b) preserves the locked symmetric port and pushes the asymmetry to the two call sites that already know whether they hold a query or a document (M3-b `retrieve` embeds the query; M3-a/M4 embed documents/facts).
- **Recommended: (b)** — smallest blast radius, no port change, the prefix becomes a documented convention at the two embed-call sites. Flag for the owner (open question below).

**Per-store task instruction (the free specialization from §3):** M3 doc queries use a "retrieve relevant passages" instruction; M4 memory recall can use a "retrieve facts about the owner relevant to…" instruction — same model, different `{task_description}`. This is where one-model still gets store-aware retrieval.

## 7. Migration / re-index cost — what changing the embedder later actually costs

Both stores **lock `{embedder_model_id, dimension}` in metadata at creation** and raise `DimensionMismatchError` on a mismatched reopen (M3-a `LanceDBVectorStore`, M4-a `meta` table + `open_memory_db`). So a model change is an **explicit, guarded re-index migration** — never a silent corruption. Cost profile:

- **Same dimension, different model** (e.g. Qwen3-0.6B → a future Qwen3.x-0.6B at 1024): still a full re-embed (vectors aren't comparable across models even at equal dim), but **no schema change** — re-run ingestion / re-embed facts into a fresh table, swap. Idempotency (`content_hash` in M3; `fact_key` in M4) makes re-ingest safe.
- **Different dimension** (e.g. → 4B at 2560): re-embed **and** the sqlite-vec `vec0` / LanceDB table is re-declared at the new dim. Same migration shape, plus the dimension-lock metadata changes.
- **Practical approach (recommended pattern, not a spec):** build-new-then-swap behind the port — create a new scoped table/index, re-embed from source-of-truth (M3: re-ingest from connectors via `content_hash`; M4: re-embed `facts` rows from their stored `object`/`subject`/`relation` text — the text survives, only vectors are regenerated), verify, atomically swap, drop old. The bitemporal `facts` rows and the LanceDB provenance all retain their **source text**, so re-embedding never needs the original documents for memory and only needs re-ingest for docs.
- **Two-store consequence of §3:** because both stores share **one** embedder+dim, a model upgrade is **one decision, two parallel re-index jobs with identical mechanics** — not two independent migration tracks. This is the concrete operational payoff of the one-model recommendation.

**Plain-English:** Swapping the translator later means re-translating everything once — but the system refuses to mix old and new translations (it errors loudly instead of returning garbage), and because your memory facts keep their original words, re-translating memory is cheap and safe. Sharing one translator means one upgrade project, not two.

---

## Open questions for the owner

1. **Asymmetric-prefix wiring (the only real build gap).** The locked `EmbeddingModel.embed(texts)` port is symmetric; Qwen3-Embedding needs queries prefixed and documents not. Recommended fix = **option (b)**: keep the port, make callers (M3-b retriever vs M3-a/M4 writers) responsible for query-prefixing, documented as a convention. **Confirm this, or prefer an explicit `embed_query`/`embed_documents` adapter split?** This wants a small targeted amendment to M1-b/M3-b/M4 at build time (not now).
2. **Per-store task instructions.** Adopt store-specific `{task_description}` strings (docs vs memory) to get free retrieval specialization from one model? (Recommended yes; trivial.)
3. **4B eval gate.** brain.md already flags "0.6B vs 4B (eval-gated)." Keep 0.6B as the locked default and only revisit 4B if an on-hardware RAGAS/recall eval shows a gap? (Recommended: yes — 0.6B default, 4B is a same-family re-index if ever needed.)
4. **Reranker transport.** Accept that "constrained-decoded score via `/v1/chat/completions`" is the **primary** reranker path (no native `/v1/rerank` on mlx-openai-server), and have M3-b document it as primary rather than fallback? (Recommended yes.)

_None of these contradict a locked decision; #1 is the only one that touches spec text, and only at build time._

---

## Sources

- [Qwen3-Embedding-0.6B model card (HF)](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B) — 1024 dim, MRL 32–1024, 32K ctx, Apache-2.0, asymmetric `Instruct:/Query:` prefix, "no instruction for documents"
- [Qwen3-Embedding GitHub](https://github.com/QwenLM/Qwen3-Embedding) — family overview (0.6B/4B/8B)
- [Qwen3-Embedding blog](https://qwenlm.github.io/blog/qwen3-embedding/) — MTEB #1, MRL, instruction-awareness
- [Qwen3-Embedding paper (arXiv 2506.05176)](https://arxiv.org/pdf/2506.05176)
- [vLLM issue #20899 — Qwen3-Embedding-8B MRL support](https://github.com/vllm-project/vllm/issues/20899) — confirms MRL across the family
- [mlx-openai-server GitHub (cubist38)](https://github.com/cubist38/mlx-openai-server) — `/v1/embeddings` via `--model-type embeddings`; NO `/v1/rerank`; multi-model = subprocess-per-model; v1.8.1 (May 2026)
- [mlx-openai-server PyPI](https://pypi.org/project/mlx-openai-server/)
- [Qwen3-Reranker-0.6B model card (HF)](https://huggingface.co/Qwen/Qwen3-Reranker-0.6B) and [MLX conversion](https://huggingface.co/mlx-community/Qwen3-Reranker-0.6B-mxfp8)
- [EmbeddingGemma — Google Developers Blog](https://developers.googleblog.com/en/introducing-embeddinggemma/) and [HF blog](https://huggingface.co/blog/embeddinggemma) — 308M, 768-dim, MRL→128, **2K ctx**, MLX support
- [Best Embedding Model for RAG 2026 — Milvus blog](https://milvus.io/blog/choose-embedding-model-rag-2026.md) — 2025–2026 field comparison (BGE-M3 1024/100+langs; dimension-compression quality-loss notes)
- [mlx-embeddings (Blaizzy)](https://github.com/Blaizzy/mlx-embeddings) — named fallback embedding server for Apple Silicon
- Internal: `docs/technical/adr/ADR-004-memory-engine.md`, `docs/technical/architecture/brain.md` §"Inference + models"/§Retrieval/§"Upgradeability — the ports", `docs/changes/M0-d-ports-scaffolding.md`, `docs/changes/M1-b-router-brain.md`, `docs/changes/M3-a-ingestion-pipeline.md`, `docs/changes/M3-b-adaptive-retriever.md`, `docs/changes/M4-a-store-schema-bitemporal-repo.md`
