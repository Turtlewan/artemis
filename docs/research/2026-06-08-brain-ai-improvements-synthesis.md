# Research synthesis: Brain/AI improvements + M5 Pro re-evaluation

**Date:** 2026-06-08
**Trigger:** Owner may buy a Mac Mini with an "M5 Pro" chip instead of the locked M4 Pro 48GB; wants a brain/AI improvement sweep (graph RAG + anything else).
**Method:** 5 parallel research agents (Sonnet gather), grounded in the locked SP0 design. Full briefs:
- `2026-06-08-m5-pro-hardware.md` · `2026-06-08-graphrag-landscape.md` · `2026-06-08-retrieval-embeddings.md` · `2026-06-08-agent-memory.md` · `2026-06-08-local-model-tier.md`
**Re-research after:** 2026-06-22 (AI tooling 14d) · hardware re-check immediately after WWDC 2026 (this week).
**Confidence:** MEDIUM-HIGH. Most claims VERIFIED to primary sources; hardware (unannounced M5 Pro Mini) and Apple-Silicon tok/s are COMMUNITY/ASSUMED — flagged inline in the source briefs.

---

## Headline

**The SP0 brain architecture holds — five days later, nothing structural is wrong.** No framework adoption beats the build-custom calls; the retrieval and embedding stack stays; the graph stays deferred. The research surfaced **three incremental wins** and **one timing decision**, not a redesign:

1. **Upgrade the sensitive reasoner** Qwen3-14B → **Qwen3.6-27B** (fits even on 48GB). [biggest free win]
2. **Hold the hardware lock — but wait for WWDC this week.** The real lever is the **RAM tier (48→64GB)**, not the M5 chip. M5 Pro adds speed (3–4× prefill), not headroom (still 64GB max on any Mini).
3. **The GraphRAG un-defer trigger is now within reach** — a 64GB box (or arguably 48GB + the 27B) clears the model threshold that kept the graph deferred. Move it from "hard-deferred" to "build-time spike."
4. **Absorb three memory patterns + lock the visual-doc retriever** — small refinements to ADR-004 and ADR-007.

---

## The dependency chain (how the threads connect)

```
Hardware (RAM tier) ──┬──► Local-teacher feasibility ──► collapse cloud/local split?
                      └──► Model tier (27B fits?) ──────► clears GraphRAG extraction threshold
```

The owner's instinct was right that hardware is upstream of the AI design — but the **binding constraint is RAM, not the chip generation**:
- M4 Pro Mac Mini already supports **64GB BTO**. M5 Pro Mini (unannounced) also caps at **64GB**.
- So "go 64GB" is a decision available on *either* chip. The M5 Pro's distinct contribution is **GPU speed** (per-core Neural Accelerators: +12.5% bandwidth, **3–4× faster prefill/TTFT**, +20–30% generation) — which improves the *experience* (voice latency, agentic-loop turns) but not *what fits*.

---

## Per-thread verdicts

### 1. Hardware — HOLD the lock, decide after WWDC (this week)
- [VERIFIED] M5 Pro ships in MacBook Pro (since 2026-03-03). **No M5 Pro Mac Mini exists** — unannounced. **WWDC 2026 is this week** = the watch window; could also slip to late 2026 on DRAM supply.
- [VERIFIED] Mac Mini RAM ceiling = **64GB on M4 Pro and (expected) M5 Pro alike**. 70B-class local models stay impossible on any Mini.
- [COMMUNITY] 64GB unlocks a dense-32B / Qwen3.6-27B local teacher (~40–70 tok/s) → sensitive reasoning fully on-device; demotes DeepSeek to *optional* for sensitive work.
- [VERIFIED] 2026 DRAM shock: +90–98% Q1, +58–63% Q2 → 64GB BTO estimated S$2,800–3,400.
- **Decision rule:** if WWDC announces an M5 Pro Mini with a 64GB BTO ≤ ~S$3,600 → buy it (GPU speedup + local-teacher headroom in one). If not announced → the cheaper move is **M4 Pro at 64GB** (same headroom, no GPU speedup, available now). Either way, **going 64GB is the lever**; 48GB was a budget compromise that constrains the teacher *and* graph stories.

### 2. GraphRAG — stays deferred, but PROMOTE to a build-time spike
- [VERIFIED] LazyGraphRAG **still not OSS** (Azure-only; `microsoft/graphrag` v3.1.0 has no LazyGraphRAG). Don't plan around it.
- [VERIFIED] Best OSS options: **LightRAG** v1.5.0 (strongest all-round, MIT, incremental) but **needs 32B+** for reliable extraction; **HippoRAG 2** (works at 8B, ~1k tok/query vs 40k for MS-GraphRAG); **Graphiti** (temporal, same 32B warning).
- [VERIFIED] April 2026 paper "Do We Still Need GraphRAG?" — agentic multi-hop substantially narrows the gap; personal-corpus low entity-density narrows it further. Agentic-first was the right default.
- **Reconciliation with threads 1+5:** the un-defer trigger was "stronger local model (32B-class)." That model now **exists and fits** — Qwen3.6-27B (dense, ~18GB 4-bit) benchmarks above the 32B proxy (GPQA 87.8, SWE-bench 77.2) and runs even on 48GB; constrained decoding (Outlines, already in the stack) guarantees extraction *JSON validity*, leaving only extraction *judgment* to validate. → **Change ADR-007's trigger from "defer until a stronger local model is available" (now satisfied) to a gated build-time spike:** evaluate **LightRAG** (or fast-graphrag if it cuts a 14B-verified v1.0) against agentic multi-hop on a personal gold-set, behind the existing `retrieve(query, mode)` port. Keep agentic as default until the spike proves the graph earns its extraction cost.

### 3. Retrieval & embeddings — NO change (keep Qwen3 stack)
- [VERIFIED] Qwen3-Embedding-0.6B (MTEB-EN 70.70, full Matryoshka 32–1024 dims, 32K ctx, verified MLX path ~44k tok/s@900MB) + 4B eval tier (+3.9 pts) — no challenger justifies a re-index migration. EmbeddingGemma disqualified (2K ctx); Stella English-only.
- [VERIFIED] Qwen3-Reranker-0.6B (MTEB-R 65.80) beats bge-reranker-v2-m3 by +8.8; 4B tier peaks 69.76. No displacement.
- **One improvement:** resolve the ADR-007 "ColPali-style" placeholder → **ColQwen2.5 Light via PyTorch MPS (2.5.1, *not* 2.6.0)** for PDFs/screenshots/video-keyframes; Lance v2.2 Blob V2 makes patch-vector storage practical. (Argus-Retriever, arXiv 2606.04300, <1wk old — revisit 06-22, don't adopt.)
- Late chunking + Contextual Retrieval = still consensus. LanceDB FTS now 3–8× faster (WAND); still no at-rest encryption → the ADR-007 encrypted-volume approach remains the correct workaround.

### 4. Agent-memory — KEEP build-custom; absorb 3 patterns
- [VERIFIED] No framework satisfies all of {SQLCipher at-rest + bitemporal + small-model robustness + per-person partition + no external graph DB} at once. Graphiti (only truly bitemporal) warns models <~70B emit schema-invalid JSON; Mem0 benchmarks best (LongMemEval 94.4 / LoCoMo 92.5) but no bitemporality, no at-rest encryption. Custom stays justified.
- **Absorb into ADR-004:**
  - **Composite forgetting score** `I(m,t)=α·exp(−λΔt)+β·access_count+γ·cosine(m,query)` as a **retrieval-time re-rank multiplier** (recent ×1.5, stale ×0.3) — *not* eager deletion — on the **semantic** store; keep TTL-only on episodic.
  - **A-MEM structured note metadata** columns (keywords + contextual_description + linked_ids) on the semantic store → multi-hop recall.
  - **Graphiti's four-timestamp bitemporal schema** as the reference implementation for our event-time/ingestion-time stamping.
- [VERIFIED] sqlite-vec fine for the (small) memory store — 17ms @ 1M×128-dim on M1; **pin the version** (pre-v1 API instability).

### 5. Local model tier — one upgrade, responder unchanged
- [VERIFIED] **Responder stays Qwen3-4B-Instruct-2507** (BFCL-v3 61.9; best sub-5GB tool-caller on MLX). Qwen3.5-4B scores lower + has a 14× llama.cpp latency regression (Gated DeltaNet) → skip.
- [VERIFIED/COMMUNITY] **Sensitive reasoner: Qwen3-14B → Qwen3.6-27B** (dense, ~18GB 4-bit; GPQA 87.8, AIME 94.1, SWE-bench 77.2; ~18 tok/s on M4 Pro with native MTP speculative decoding). **Fits 48GB with ~23GB headroom** after resident+OS. Prefer the dense 27B over the 35B-A3B MoE (MoE faster but lower quality for a reasoning tier).
- **Local teacher displacing DeepSeek:** not clean on 48GB (unload gymnastics); on **64GB**, Qwen3.6-27B dual-roles as sensitive-reasoner + non-sensitive teacher for ~80% of workloads. 128GB/70B is the only "displace V4-Pro" tier but the **cost case never pencils for a personal assistant — the real case is the privacy perimeter, not $.**
- **Runtime gotchas (carry to build):** mlx-openai-server **1.8.1** is production-ready (multi-model YAML, idle-unload TTL, qwen3 tool-parser). **Do NOT enable standard mlx-lm speculative decoding on Qwen3** (skipped-token bug #846) — use Qwen3.6's **native MTP** instead. DeepSeek V4-Flash stays cloud teacher; V4-Pro only for long-horizon agentic.

---

## Recommended changes (proposed — not yet applied)

| # | Change | Doc(s) | Type |
|---|--------|--------|------|
| A | Sensitive reasoner Qwen3-14B → **Qwen3.6-27B** (fits 48GB) | `brain.md` §Inference+models, §Hardware; ADR-001 model list | content edit |
| B | GraphRAG: "hard-deferred" → **gated build-time spike** (LightRAG vs agentic on gold-set, behind the port; default stays agentic) | ADR-007 §Decision + §Build-time spikes | content edit |
| C | Lock visual-doc retriever = **ColQwen2.5 Light / MPS 2.5.1** | ADR-007 §Ingestion (resolve the ColPali placeholder) | content edit |
| D | Absorb forgetting-score + A-MEM metadata + Graphiti 4-timestamp ref | ADR-004 | content edit |
| E | Runtime pins/gotchas: mlx-openai-server 1.8.1, no mlx-lm spec-decode on Qwen3 (use MTP), pin sqlite-vec, ColQwen MPS 2.5.1 | `brain.md` / relevant M-drafts (M0-c, M3, M4) | note/annotation |
| F | **Hardware: hold lock; re-decide after WWDC this week.** If M5 Pro Mini @64GB ≤~S$3,600 → buy; else 64GB-on-M4-Pro is the lever. Update ADR-001 §Hardware once WWDC resolves. | ADR-001 | decision (pending WWDC) |

**Not changing:** thin orchestrator · router-first · tool-registry/RAG-for-tools · LanceDB · Qwen3 embeddings+reranker · two-store memory · responder Qwen3-4B · cloud sensitivity-router · ports-everywhere · voice stack. All validated.

## Open items for the owner
1. **WWDC watch (this week):** M5 Pro Mac Mini announced? 64GB BTO price?
2. **Go 64GB regardless of chip?** It's the single lever that (a) makes the local teacher real for sensitive work, (b) clears the GraphRAG spike's hardware bar, (c) removes teacher/reasoner unload gymnastics. Cost: +DRAM-shock premium.
3. **Apply changes A–E to the ADRs/drafts now, or stage them for the Monday readiness-gate pass?**

## Sources
The 5 source briefs in this folder carry the tagged, per-claim citations.
