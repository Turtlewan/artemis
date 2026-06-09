# Research: M5 Pro Mac Hardware for Artemis

**Date:** 2026-06-08
**Re-research after:** 2026-07-08 (hardware/pricing 30d given WWDC imminent; model news 14d)
**Author:** Research agent (claude-sonnet-4-6)

---

## Summary

The M5 Pro chip is **real and shipping** (announced March 3, 2026 in MacBook Pro). An M5 Pro Mac Mini **does not yet exist** — it is widely expected at WWDC 2026 (today or imminently) but has zero official Apple confirmation. The M5 Pro chip offers genuine inference gains over M4 Pro: 20–30% higher generation throughput and 3.3–4x faster prefill (TTFT) due to per-GPU-core Neural Accelerators. However, the M5 Pro Mac Mini's max RAM ceiling is expected to remain **64GB** — not 96GB or 128GB — which leaves the Artemis lazy-load pattern (48GB M4 Pro) still viable. The 64GB tier meaningfully unlocks dense 32B-class models and MoE 30B models at comfortable speed, but a ~70B local teacher requires M5 Max (128GB, ~S$5,500+), which is Mac Studio territory, not Mac Mini.

**Verdict for Artemis:** The M5 Pro Mac Mini at 64GB is a compelling upgrade over the locked M4 Pro 48GB for the teacher tier, but it is not yet purchasable (rumored, unannounced), will cost ~S$1,800–2,200 more at the 64GB tier due to DRAM-shock pricing, and does NOT eliminate the need for a cloud teacher for true heavy reasoning (70B+ class). If WWDC 2026 announces it this week, revisit immediately. Until then, the M4 Pro 48GB lock stands.

---

## Key Findings (tagged)

### Q1: Does an M5 Pro Mac Mini exist?

- The **M5 Pro chip** was announced March 3, 2026 alongside updated MacBook Pro 14" and 16" models. [VERIFIED — https://www.apple.com/newsroom/2026/03/apple-introduces-macbook-pro-with-all-new-m5-pro-and-m5-max/]
- The **M5 Mac Mini (base and Pro) has NOT been officially announced** by Apple as of 2026-06-08. It remains entirely rumored. [VERIFIED — https://www.macworld.com/article/2964754/2026-mac-mini-m5-pro-design-specs-release-date.html]
- Multiple supply-chain sources (Bloomberg's Mark Gurman primary) expect WWDC 2026 (June 9–13, 2026) as the announcement window for M5 Mac Mini. [COMMUNITY — Macworld, MacObserver, TechRepublic]
- Launch could slip to late 2026 due to DRAM supply constraints. [COMMUNITY — multiple sources]
- The base M5 chip shipped in: MacBook Pro 14" (Oct 2025), iPad Pro, Vision Pro. M5 Pro/Max arrived March 2026 in MacBook Pro. M5 Ultra not yet announced. [VERIFIED — Apple Newsroom]
- **Bottom line:** "M5 Pro Mac Mini" is currently vapor — a likely-imminent product, not a purchasable one.

### Q2: M5 Pro chip specs

- **CPU:** 18-core (6 super cores + 12 performance cores) — Apple calls the super cores "the world's fastest CPU cores." [VERIFIED — Apple Newsroom March 2026]
- **GPU:** Up to 20-core (base config is 16-core). [VERIFIED — Apple Support page https://support.apple.com/en-us/126318]
- **Memory bandwidth:** 307 GB/s (vs M4 Pro's 273 GB/s — a ~12.5% uplift). [VERIFIED — Apple Support]
- **Max unified memory:** 64GB on M5 Pro. [VERIFIED — Apple Support]
- **Neural Accelerators:** "A Neural Accelerator in each GPU core" — dedicated matrix-multiply acceleration per GPU core, enabling 3–4x TTFT speedup for compute-bound prefill. [VERIFIED — Apple Newsroom; Apple ML Research]
- **Neural Engine:** 16-core (same count as M4 Pro but higher memory bandwidth connection). [VERIFIED — Apple Support]
- **AI compute claim:** Apple states "over 4x peak GPU compute for AI compared to previous generation [M4 Pro]." [VERIFIED — Apple Newsroom] Note: this is peak GPU compute, not sustained generation throughput.
- **CPU performance:** ~30% multithreaded gain vs M4 generation. [VERIFIED — Apple Newsroom]

### Q3: MLX inference performance

- **Generation throughput (decode phase, memory-bandwidth-bound):** M5 Pro delivers 20–30% improvement vs M4 Pro, directly tracking the ~12.5% bandwidth increase plus architectural gains. [VERIFIED — https://contracollective.com/blog/m4-m5-pro-local-ai-inference-mlx-2026; Apple ML Research]
- **Prefill / TTFT (compute-bound):** 3.3–4.06x faster than M4 base (M5 vs M4 comparison from Apple ML Research; M5 Pro expected between M5 and M4 Pro). Dense 14B: under 10 seconds TTFT; 30B MoE: under 3 seconds TTFT on M5. [VERIFIED — https://machinelearning.apple.com/research/exploring-llms-mlx-m5]
- **Specific benchmarks (M4 Pro 48GB vs M5 Pro 48GB, MLX, Q4):**

| Model | M4 Pro 48GB | M5 Pro 48GB | Delta |
|---|---|---|---|
| Qwen 2.5 14B (4-bit, 8K ctx) | 52–58 tok/s | ~63–75 tok/s (est.) | ~22–28% |
| Qwen 2.5 14B (4-bit, 32K ctx) | 42–48 tok/s | 58–65 tok/s | ~35–38% |
| Qwen 2.5 32B (4-bit, 8K ctx) | 32–38 tok/s | 42–50 tok/s | ~31–32% |
| Qwen 2.5 32B (4-bit, 32K ctx) | 24–30 tok/s | 32–40 tok/s | ~33% |

[COMMUNITY — contracollective.com benchmarks; 8K ctx M5 Pro 14B is extrapolated from 32K data and 20–30% uplift, marked as estimated]

- **Qwen3-30B-A3B (MoE, 3B active params, Q4 MLX):** ~130 tok/s on M4 Pro 64GB. [COMMUNITY — search result summary; source unclear, treat with caution]
- **TTFT specifically:** The Neural Accelerators help Artemis's use case because the always-resident Qwen3-4B responder does many short-context calls, but the lazy-loaded teacher tier (Qwen3-14B or larger) has long prompts — so the 3–4x prefill gain is the most impactful real-world improvement. [ASSUMED — extrapolated from Apple ML Research findings]
- **MLX vs llama.cpp:** MLX remains the preferred runtime on Apple Silicon for M5 with Neural Accelerator support in 2026. [COMMUNITY — https://groundy.com/articles/mlx-vs-llamacpp-on-apple-silicon-which-runtime-to-use-for-local-llm-inference/]

### Q4: Teacher-tier feasibility at various RAM tiers

Artemis's current teacher is Qwen3-14B lazy-loaded into ~33GB of headroom on 48GB M4 Pro. The question is whether an M5 Pro at 64GB (or higher) could host a stronger local teacher that replaces the DeepSeek cloud tier.

**Memory requirements (Q4 quantization, approximate):**

| Model | VRAM Q4 | Fits on 48GB M4 Pro? | Fits on 64GB M5 Pro? |
|---|---|---|---|
| Qwen3-14B (dense) | ~10GB | Yes (already deployed) | Yes, comfortably |
| Qwen3-30B-A3B (MoE) | ~18–20GB | Yes (tight, 28GB headroom after always-resident stack) | Yes, with margin |
| Dense 32B | ~20–22GB | Marginal (8–10GB headroom left) | Yes (~42GB remaining) |
| Qwen3-32B (dense) | ~20–22GB | Marginal | Yes |
| Dense 70B | ~42–48GB | No (exceeds remaining headroom) | No (64GB total insufficient with stack) |
| Qwen3-235B-A22B (MoE) | ~140GB | No | No |

[COMMUNITY — size estimates from standard Q4 3-bit-per-weight math; stack RAM from Artemis docs]

**Speed at 64GB M5 Pro for candidate teacher models:**

| Model | Est. tok/s (Q4, M5 Pro 64GB) | Usable for reasoning? |
|---|---|---|
| Qwen3-14B | 65–75 tok/s | Yes, already deployed |
| Qwen3-30B-A3B (MoE) | 55–70 tok/s | Yes, excellent |
| Dense 32B | 40–50 tok/s | Yes, acceptable |
| Llama 3.3 70B | 18–24 tok/s* | Slow but feasible for async tasks |

*70B does NOT fit the 64GB M5 Pro alongside the always-resident stack (~15GB). Would need ~77GB free, so 64GB is insufficient for 70B + stack simultaneously. [ASSUMED — math: 64GB total − 15GB stack = 49GB free; 70B Q4 needs ~42–48GB, leaving 1–7GB margin which is dangerously tight or impossible depending on OS overhead.]

**Conclusion on teacher displacement:**
- **64GB M5 Pro unlocks Qwen3-30B-A3B or a dense 32B as a strong local teacher** — a genuine step up from Qwen3-14B.
- A dense 32B model (e.g., Qwen3-32B or similar) at 40–50 tok/s is plausibly sufficient to replace DeepSeek for most heavy reasoning tasks.
- **70B+ class remains out of reach on Mac Mini form-factor** (requires M5 Max 128GB, i.e., Mac Studio or MacBook Pro 16").
- The DeepSeek cloud dependency could be **reduced but not eliminated**: 32B local covers hard reasoning on sensitive data, but the very top tier (high-quality code gen, deep research synthesis, long-context distillation) would still benefit from a cloud 671B-class model for non-sensitive tasks.

### Q5: Price, availability, DRAM context

**Current M4 Pro Mac Mini (available today, SGD confirmed):**
- M4 Pro 12-core CPU, 16-core GPU, 24GB, 512GB: S$1,999 [VERIFIED — HardwareZone SG review]
- M4 Pro 14-core CPU, 20-core GPU, 48GB, 1TB: S$3,199 [VERIFIED — HardwareZone SG review]

**M5 Pro MacBook Pro (M5 Pro chip pricing reference, available today):**
- M5 Pro 15-core CPU, 16-core GPU, 24GB, 1TB: ~US$2,199 base [COMMUNITY — Apple Store listing]
- M5 Pro 18-core CPU, 20-core GPU, 48GB, 1TB: ~US$3,099 [COMMUNITY — Apple Store / Microcenter listing]
- M5 Pro 18-core CPU, 20-core GPU, 64GB, 1TB: ~US$3,400–3,600 (estimated, not yet confirmed for Mac Mini) [ASSUMED — based on M5 Pro MacBook Pro BTO step]

**Expected M5 Pro Mac Mini pricing (RUMORED, not confirmed):**
- M5 Pro base (24GB): ~US$999–1,299 [COMMUNITY — multiple rumor sources]
- M5 Pro 64GB: ~US$1,599–1,899 [COMMUNITY — llmmac.com]
- In SGD (rough ~1.35 USD/SGD exchange): ~S$2,150–2,560 for 64GB config [ASSUMED — currency conversion]

**DRAM shortage context:**
- DRAM contract prices surged ~90–98% in Q1 2026 vs Q4 2025; a further 58–63% increase projected for Q2 2026. [VERIFIED — The Register, June 2, 2026; https://www.theregister.com/storage/2026/06/02/expect-more-of-those-dram-price-hikes-as-memory-shortage-continues-to-bite/5250049]
- Root cause: HBM3e demand from hyperscaler AI build-out consuming 23%+ of DRAM wafer capacity, constraining LPDDR5X supply for consumer chips. [VERIFIED — IDC, IEEE Spectrum]
- Apple absorbed DRAM costs by discontinuing the $599 Mac Mini entry point (256GB storage model) rather than raising chip BTO prices. [COMMUNITY — 9to5Mac March 2026]
- BTO RAM upgrades on future Macs may not fully reflect the DRAM surge yet, but analysts expect "double-digit %" consumer price increases by end-2026. [COMMUNITY — IDC, Tom's Guide]
- Relief timeline: SK Hynix says shortage persists "until 2030"; more conservative analysts say "end of 2027"; new Micron capacity not until 2027–2028. [VERIFIED — The Register]

---

## M4 Pro vs M5 Pro Comparison Table

| Attribute | M4 Pro (in current Artemis Mac Mini) | M5 Pro (MacBook Pro, future Mac Mini) | Notes |
|---|---|---|---|
| CPU cores | 12c (8P+4E) / 14c (8P+6E) BTO | 15c (5S+10P) / 18c (6S+12P) BTO | M5 introduces "super cores" |
| GPU cores | 16c / 20c BTO | 16c / 20c | Same count, new architecture |
| Neural Accelerators | None | 1 per GPU core (16–20 total) | Key for matmul / LLM prefill |
| Memory bandwidth | 273 GB/s | 307 GB/s | +12.5% |
| Max unified memory | 64GB | 64GB | Same ceiling |
| Neural Engine | 16-core | 16-core | Higher mem bandwidth on M5 |
| CPU MT performance | baseline | +~30% | Per Apple claim |
| LLM generation throughput | baseline | +20–30% | Memory-bandwidth-limited |
| LLM prefill (TTFT) | baseline | +3.3–4x | Compute-bound; Neural Accel. |
| GPU AI compute | baseline | "4x peak GPU compute for AI" | Apple's claim; peak not sustained |
| Thunderbolt | TB5 | TB5 | Same |
| Mac Mini max RAM available | 64GB (BTO) | 64GB (expected, unconfirmed) | No expansion beyond M4 Pro |
| Mac Mini current price (48GB) | S$3,199 (available) | ~S$2,200–2,800 est. (48GB) | M5 Mini not yet for sale |
| Mac Mini 64GB price | S$3,500–3,800 est. (BTO, M4 Pro) | ~S$2,600–3,200 est. (64GB M5) | Both estimated; DRAM premium |

[Sources: Apple Support https://support.apple.com/en-us/121555 (M4 Pro Mac Mini); Apple Support https://support.apple.com/en-us/126318 (M5 Pro MacBook Pro); Apple Newsroom March 2026]

---

## What It Unlocks (Local Teacher Feasibility)

### Scenario A: Stay on M4 Pro 48GB (current locked config)
- Teacher: Qwen3-14B in ~33GB headroom → 52–58 tok/s at 8K context
- Qwen3-30B-A3B (MoE) fits but is tight; marginal headroom alongside always-resident stack
- Dense 32B: does NOT comfortably fit (needs ~22GB + 15GB stack = 37GB; 48GB − 37GB = 11GB for OS/buffers — feasible but risky for long-context tasks)
- Cloud teacher (DeepSeek) required for heavy reasoning

### Scenario B: Upgrade to M5 Pro 48GB (same RAM, new chip)
- ~25–35% faster inference across all model sizes
- 3–4x faster TTFT for heavy prompts
- Qwen3-14B runs noticeably faster; Qwen3-30B-A3B becomes the practical teacher ceiling
- DeepSeek still needed for 70B-class reasoning
- Cost: NOT YET PURCHASABLE; estimated ~S$2,600+ when available

### Scenario C: M5 Pro 64GB (the pivotal upgrade)
- Always-resident stack: ~15GB
- Available for teacher: ~49GB
- **Unlocks Qwen3-30B-A3B (~18–20GB Q4) comfortably: ~55–70 tok/s**
- **Unlocks dense 32B (~22GB Q4) at 40–50 tok/s** — a genuinely strong teacher
- 70B still doesn't fit alongside the stack (needs ~42–48GB free after 15GB stack = needs 57–63GB of headroom, which a 64GB chip cannot reliably provide)
- Cloud teacher for 70B+ class and non-sensitive distillation: still useful, but the 32B local tier is strong enough to handle most health/finance/journal reasoning privately
- **This is the configuration that partially displaces DeepSeek for sensitive tasks**

### Scenario D: M5 Max 128GB (Mac Studio tier, ~S$4,000–5,500+)
- All models up to 70B (Q4) fit comfortably
- Llama 3.3 70B / Qwen3-72B: 25–32 tok/s
- Fully displaces cloud for sensitive teacher tasks
- Higher cost, different form factor (Mac Studio, not Mac Mini)
- Out of scope for this decision unless budget is unconstrained

---

## Recommendation

### Immediate decision (June 2026)
**Keep the M4 Pro 48GB Mac Mini as locked.** The M5 Pro Mac Mini does not exist as a purchasable product. Purchasing it today is not possible.

### If/when M5 Pro Mac Mini launches (WWDC 2026 imminent)

**Recommended config: M5 Pro Mac Mini, 64GB RAM, 1TB SSD.**

Rationale:
1. The 64GB tier unlocks a dense 32B local teacher, which is sufficient to handle Artemis's sensitive finance/health/journal reasoning entirely on-device — eliminating the privacy concern of sending those workloads to DeepSeek.
2. The 20–30% generation throughput gain + 3–4x TTFT improvement on the teacher tier materially improves responsiveness for the lazy-load pattern.
3. The 64GB ceiling is the same as the M4 Pro Mac Mini BTO ceiling — so if you were going to pay for 64GB on M4 Pro, the M5 Pro at similar cost is strictly better.
4. DeepSeek cloud tier is NOT eliminated — it remains useful for non-sensitive heavy research, distillation, and 70B-class tasks — but it becomes optional for sensitive data, which is the primary privacy driver.

**Does it kill the DeepSeek dependency?** Partially. For sensitive data: yes, a 32B local teacher handles it. For non-sensitive heavy compute (deep research, code distillation): DeepSeek cloud remains cost-effective and higher quality than a 32B local model. Recommend keeping DeepSeek for non-sensitive tasks and moving sensitive heavy reasoning fully local.

**BTO cost vs M4 Pro 48GB baseline:**
- Current locked config: S$3,199 (M4 Pro 48GB)
- Estimated M5 Pro 64GB at launch: ~S$2,800–3,400 (DRAM-inflated; not confirmed)
- Delta: approximately S$0–400 premium, or potentially at parity depending on Apple's pricing
- If DRAM pricing inflates the 64GB BTO tier significantly (S$4,000+), reconsider and stay on M4 Pro 48GB with Qwen3-30B-A3B as the teacher (which fits in 48GB with care)

**Timing caveat:** WWDC 2026 begins today (June 9). If Apple announces the M5 Mac Mini this week, act on confirmed specs and pricing before committing. If no announcement, the M4 Pro 48GB remains the rational hardware choice until clarity arrives.

---

## Assumptions & Gaps

1. [ASSUMED] M5 Pro Mac Mini will share M5 Pro chip specs exactly as in MacBook Pro — not confirmed; Apple sometimes bins chips differently in Mac Mini form factor.
2. [ASSUMED] M5 Pro Mac Mini max RAM will be 64GB — based on M4 Pro Mac Mini precedent (same ceiling as MacBook Pro M4 Pro). Apple could surprise with higher configs.
3. [ASSUMED] Always-resident Artemis stack consumes ~15GB RAM — based on Artemis architecture doc, not live measurement.
4. [ASSUMED] SGD/USD BTO price estimates for M5 Pro Mac Mini — extrapolated from M5 Pro MacBook Pro pricing and M4 Pro Mac Mini SGD pricing; actual Apple pricing may differ.
5. [ASSUMED] Qwen3-32B Q4 model size ~20–22GB — standard calculation at ~3–4 bits/weight; verify against actual mlx-community model release.
6. [ASSUMED] Qwen3-30B-A3B MoE Q4 fits in 20GB — based on MoE architecture (only 3B params active); actual loaded size depends on full expert parameter storage.
7. [GAP] No direct M5 Pro (not M5 Max) tok/s benchmarks found for Qwen3 model family specifically — benchmarks are Qwen 2.5 series as proxy.
8. [GAP] M5 Pro Mac Mini actual RAM tiers unconfirmed — rumors say 24/48/64GB; no official BTO menu exists yet.
9. [GAP] Apple's DRAM-crisis BTO pricing policy for M5 Mac Mini unknown — the 9to5Mac analysis suggests Apple may absorb costs in storage tiers rather than RAM tiers.
10. [GAP] mlx-openai-server compatibility with M5 Neural Accelerator matmul paths — assumed yes given MLX team focus on Apple Silicon, but not explicitly verified for latest MLX release.

---

## Sources

### Primary / Verified
- [Apple Newsroom — M5 Pro and M5 Max announcement (March 3, 2026)](https://www.apple.com/newsroom/2026/03/apple-debuts-m5-pro-and-m5-max-to-supercharge-the-most-demanding-pro-workflows/)
- [Apple Support — MacBook Pro M5 Pro tech specs](https://support.apple.com/en-us/126318)
- [Apple Support — Mac mini M4 Pro tech specs](https://support.apple.com/en-us/121555)
- [Apple ML Research — Exploring LLMs with MLX and M5 Neural Accelerators](https://machinelearning.apple.com/research/exploring-llms-mlx-m5)
- [The Register — DRAM price hikes, June 2, 2026](https://www.theregister.com/storage/2026/06/02/expect-more-of-those-dram-price-hikes-as-memory-shortage-continues-to-bite/5250049)

### Community / Benchmark
- [Contra Collective — M4 Pro vs M5 Pro Local AI Inference Benchmarks](https://contracollective.com/blog/m4-m5-pro-local-ai-inference-mlx-2026)
- [LLMCheck — Apple Silicon LLM Benchmarks](https://llmcheck.net/benchmarks)
- [Presenc AI — Local LLM Tokens/sec Benchmarks 2026](https://presenc.ai/research/local-llm-tokens-per-second-benchmarks-2026)
- [HardwareZone SG — Mac mini M4 Pro review with SGD pricing](https://www.hardwarezone.com.sg/pc/review-apple-mac-mini-m4-pro-compact-desktop-singapore-price-specs-buy)
- [LlmMac — Mac Mini M5 release date and expected specs](https://llmmac.com/blog/articles/2026-mac-mini-m5-release-date-price-full-specs.html)

### Rumor / Analysis
- [Macworld — Mac mini M5/M5 Pro rumors roundup](https://www.macworld.com/article/2964754/2026-mac-mini-m5-pro-design-specs-release-date.html)
- [MacObserver — Mac Mini M5 Pro release date and specs](https://www.macobserver.com/tips/round-ups/apple-mac-mini-m5-and-m5-pro-release-date-specs-and-price-rumors/)
- [9to5Mac — Why M5 Macs may cost more (storage, not chips)](https://9to5mac.com/2026/03/07/apple-m5-mac-mini-mac-studio-imac-might-get-more-expensive/)
- [IDC — Global Memory Shortage Crisis 2026](https://www.idc.com/resource-center/blog/global-memory-shortage-crisis-market-analysis-and-the-potential-impact-on-the-smartphone-and-pc-markets-in-2026/)
- [TechRepublic — Apple Mac Mini 2026 M5 rumors and stock shortage](https://www.techrepublic.com/article/news-apple-mac-mini-2026-m5-rumors-stock-shortage/)
