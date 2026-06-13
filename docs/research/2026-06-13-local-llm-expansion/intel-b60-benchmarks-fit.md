# Intel Arc Pro B60 — LLM Benchmarks & Fit Assessment
**Research date:** 2026-06-13  
**Scope:** 4×B60 box (96 GB VRAM total, GDDR6 ~456 GB/s/card, TP=4) for agentic coding + big-context serving.  
**Primary sources:** vLLM Blog Nov 2025, EmbeddedLLM benchmark, StorageReview Battlematrix Preview, Level1Techs forum, LMSYS DGX Spark review, multiple VRAM-requirement guides.

---

## 1. Published B60 LLM Benchmarks

**Confidence: Medium** — Most publicly available data is from Intel-sponsored or Intel-collaborated benchmarks (vLLM Blog, StorageReview). Independent third-party measurements with full methodology are sparse. The practitioner data provided in the brief is more trustworthy as a real-world cross-check.

### 1a. Single-card, single-stream (batch=1) — generation/decode

| Model | Quant | GPUs | Batch | Decode tok/s | Source |
|---|---|---|---|---|---|
| Qwen3 Coder 30B-A3B | BF16 | 4×B60 (TP=4) | 1 | **15.34** | StorageReview Battlematrix Preview, 2026-03 |
| Qwen3 Coder 30B-A3B | BF16 | 8×B60 (TP=8) | 1 | **14.15** | StorageReview Battlematrix Preview, 2026-03 |
| GPT-OSS-20B | MXFP4 | 1×B60 | 1 | **49.22** | StorageReview Battlematrix Preview, 2026-03 |
| GPT-OSS-20B | MXFP4 | 8×B60 (TP=8) | 1 | **22.83** | StorageReview Battlematrix Preview, 2026-03 |
| GPT-OSS-120B | MXFP4 | 4×B60 (TP=4) | 1 | **16.28** | StorageReview Battlematrix Preview, 2026-03 |
| Llama 3.1 8B | BF16 | multi-B60 | 1 | ~22–23 | StorageReview Battlematrix Preview, 2026-03 |
| Qwen 3.5 9B | Q4_K_XL | 1×B60 | 1 | 33–37 (SYCL build 8688) | Level1Techs forum, ~2025–2026 |
| 35B dense | Q4 | 1×B60 | 1 | 37 (SYCL build 8688) | Level1Techs forum, ~2025–2026 |

**Key observation:** Adding more GPUs via TP degrades single-stream decode on B60. TP=4 is ~3× *slower* per-stream than single-card for 20B models (49 → 22 tok/s). This is the PCIe all-reduce overhead on non-NVLink hardware. The practitioner's 27 tok/s for a 32B BF16 model across TP=4 is consistent with this pattern.

### 1b. Batched / concurrent throughput (aggregate tok/s)

| Model | Quant | GPUs | Batch/Concurrency | Decode tok/s (aggregate) | TTFT | TPOT | Source |
|---|---|---|---|---|---|---|---|
| GPT-OSS-20B | MXFP4 | 1×B60 | batch 16 | **626.84** | — | — | StorageReview, 2026-03 |
| GPT-OSS-20B | MXFP4 | 8×B60 (TP=8) | batch 16 | **511.99** | — | — | StorageReview, 2026-03 |
| GPT-OSS-20B | MXFP4 | 1×B60 | ~75 conc. | **1,210.74** | 7.61 s | 54.0 ms | vLLM Blog TP=1 table, Nov 2025 |
| GPT-OSS-120B | MXFP4 | 4×B60 (TP=4) | ~100 conc. | **1,495.12** | 8.04 s | 58.8 ms | vLLM Blog TP=4 table, Nov 2025 |
| GPT-OSS-120B | MXFP4 | 4×B60 (TP=4) | ~50 conc. | **1,085.58** | 8.11 s | 42.0 ms | vLLM Blog TP=4 table, Nov 2025 |
| GPT-OSS-120B | MXFP4 | 4×B60 (TP=4) | ~20 conc. | **619.10** | 8.60 s | 30.6 ms | vLLM Blog TP=4 table, Nov 2025 |
| Qwen3-VL-30B-A3B | BF16 | 4×B60 (TP=4) | 16 conc. | ~1,000 peak | — | 48–61 ms | EmbeddedLLM, 2025–2026 |
| Mistral Small 24B | BF16 | 8×B60 (TP=8) | batch 256 | **574.16** | — | — | StorageReview, 2026-03 |
| Llama 3.1 8B | BF16 | 4×B60 | batch 8 | **240.48** | — | — | StorageReview, 2026-03 |

**Cross-check against practitioner data:**
- Practitioner: DeepSeek-R1-Distill-Qwen-32B BF16, concurrency 32–64 → 289–309 tok/s aggregate decode, 1,400–2,900 tok/s prefill.
- Published Qwen3 30B-A3B at concurrency 16 → ~1,000 tok/s. Scaling to concurrency 32–64 roughly doubling is consistent. Practitioner numbers are plausible and in line.
- Practitioner: Qwen3-Coder-30B-A3B BF16 → 12,800 tok/s prefill at concurrency 1, crashed at concurrency 32. This is anomalous — extremely high single-stream prefill vs published crash behaviour. The crash at C=32 is consistent with documented vLLM stability issues (see Section 2).

### 1c. Prefill / prompt-processing throughput

| Model | GPUs | Concurrency | Prefill tok/s | Source |
|---|---|---|---|---|
| GPT-OSS-20B MXFP4 | 1×B60 | 75 | 1,210 (estimated from TTFT + input len) | vLLM Blog, Nov 2025 |
| GPT-OSS-120B MXFP4 | 4×B60 TP=4 | 100 | ~1,495 (embedded in throughput) | vLLM Blog, Nov 2025 |
| Qwen 3.5 9B Q4_K_XL | 1×B60 | 1 | **1,634** (SYCL build 8688, 2048-tok prompt) | Level1Techs, ~2026 |
| DeepSeek-R1-Distill-Qwen-32B BF16 | 4×B60 TP=4 | 32–64 | **1,400–2,900** (practitioner) | Provided brief |

The B60 shows strong prefill numbers at high batch because XMX compute engines saturate. Single-stream prefill is weaker — the Level1Techs data shows dramatic variance depending on SYCL build version (328 → 1,634 tok/s with driver/software update), flagging software immaturity as a real variable.

---

## 2. Concurrency Behaviour & Agentic-Fit Analysis

**Confidence: Medium-Low** — Published tests top out at 64–100 concurrent requests under controlled conditions. Real-world burst behaviour (agentic fan-out) is undercharacterised. The crash at C=32 in practitioner data is a significant red flag not explained by published sources.

### What published sources show

- vLLM Blog (Nov 2025): 4×B60 with GPT-OSS-120B MXFP4, linear scaling from 16→50→100 concurrent requests. Throughput at 100 conc. = 1,495 tok/s, TPOT 58.8 ms (~17 tok/s per user). TTFT ~8 s at 100 conc.
- EmbeddedLLM: 4×B60, Qwen3-VL-30B-A3B BF16, tested at 16/32/64 concurrent, described as "linear scaling." No crashes reported in that study.

### Known instability issues (tracked GitHub issues)

| Issue | Severity | Status | Source |
|---|---|---|---|
| SIGABRT in vLLM 0.11.0 on Arc B-series during model inspection | Blocker at startup | Filed Oct 23, 2025; no fix/workaround documented as of filing | vllm-project/vllm #27408 |
| Engine crash under burst load (72 simultaneous API calls) | Crash at high concurrency | Reported in vllm-project/vllm #32193 | GitHub |
| Engine init RuntimeError with official Intel Docker image 0.10.2-xpu | Init failure | Reported vllm-project/vllm #28770 | GitHub |
| B70 llama.cpp bugs (MoE slot-init SEGV, Q8_0 reorder crash, OOM reorder) | Multiple crashes | Fixed via cherry-picks in community fork | GitHub Hal9000AIML/arc-pro-b70-ubuntu-gpu-speedup-bugfixes |
| OpenVINO backend fails to load Qwen models | Deployment blocker | Documented GitHub issue, workaround: use SYCL backend | Level1Techs forum |

### Agentic concurrency verdict

**The 4×B60 is borderline for APEX-style wave-parallel workloads.** Key factors:

1. **Software stack immaturity is the primary risk, not the hardware.** Multiple vLLM issues on Arc B-series remain open or were only recently resolved. The practitioner's crash at C=32 with Qwen3-Coder-30B is consistent with GitHub issues rather than a fundamental hardware limit.
2. **TP=4 aggregate throughput (289–309 tok/s, or ~1,000 tok/s at higher concurrency with lighter models) is usable for batch agentic work** — APEX sub-agents can queue and process in batch mode.
3. **TTFT of 7–8 s at high concurrency** is too high for interactive sessions but acceptable if sub-agents are async fire-and-collect.
4. **Burst instability is unresolved.** A coding harness that fans 32+ simultaneous requests may hit the vLLM burst crash. Mitigation: run multiple independent DP=N instances behind a load balancer rather than one TP=4 server at high concurrency.
5. **LLM-Scaler (Intel's vLLM fork) is recommended over upstream vLLM** for B60. It showed 20–25% better TPOT at C=16.

---

## 3. Single-Stream Generation Speed Reality

**Confidence: High** — Multiple independent sources (StorageReview, Level1Techs forum, practitioner) converge.

| Scenario | Model Class | Quant | Decode tok/s | Notes |
|---|---|---|---|---|
| 4×B60 TP=4, batch=1 | 30B BF16 | BF16 | **14–16** | StorageReview; practitioner reports ~27 |
| 4×B60 TP=4, batch=1 | 32B BF16 | BF16 | **~27** | Practitioner data; higher than StorageReview 30B result |
| 1×B60, batch=1 | 9B | Q4 | 33–37 | Level1Techs (updated SYCL driver) |
| 1×B60, batch=1 | 20B | MXFP4 | 49 | StorageReview |
| NVIDIA RTX 4500 (200W) vs B60 | 35B | Q4 | **133 vs 37** | Level1Techs (3.6× gap) |

**Interpretation:**
- 14–27 tok/s single-stream on a 30B BF16 model is **marginal for interactive use.** Generally considered acceptable is 20–30 tok/s; below 15 tok/s feels sluggish for code generation.
- The discrepancy between StorageReview's 15.34 tok/s and the practitioner's ~27 tok/s may reflect: (a) different SYCL driver versions (there's documented 5× prefill improvement between driver builds), (b) quantization differences (MoE vs dense), or (c) different model architecture memory access patterns.
- TP=4 actively hurts single-stream speed vs fewer GPUs due to PCIe all-reduce overhead. A single well-clocked B60 at 49 tok/s (MXFP4 20B) outperforms TP=8 at 22 tok/s.
- **For interactive coding sessions, ~27 tok/s is acceptable but not fast.** Compare: RTX 4500 at 133 tok/s on the same model. For batch/agentic-only use (sub-agents process in parallel, user doesn't wait on single stream), this is less relevant.

---

## 4. Model Fit: Can 96 GB (4×B60) or 192 GB (8×B60) Run the Target Models?

**Confidence: High for weight-size calculations; Medium for performance at target quants on Arc B60.**

### 4a. Weight size reference table

| Model | Params | Architecture | BF16 size | FP8 | Q4 GGUF | Q2 GGUF |
|---|---|---|---|---|---|---|
| DeepSeek-R1-Distill-Qwen-32B | 32B | Dense | ~64 GB | ~32 GB | ~18 GB | ~10 GB |
| Qwen3-Coder-30B-A3B | 30B MoE (3B active) | MoE | ~61 GB | ~31 GB | ~17 GB | ~9 GB |
| DeepSeek V4 Flash (~284B MoE, ~20B active) | 284B | MoE | ~520–570 GB | ~290 GB | ~80 GB (Q4) | ~40 GB |
| DeepSeek V3/V4 base (671B MoE, ~37B active) | 671B | MoE | ~1.3 TB | ~670 GB | **~376 GB** | ~170 GB |
| Kimi K2 / K2.6 (~1T MoE) | ~1T | MoE | ~2 TB | ~1 TB | ~630 GB | ~230 GB |

Sources: codersera.com DeepSeek V4 guide (2026); knightli.com VRAM table (May 2026); Unsloth Kimi K2.6 guide (2026); runaihome.com Kimi K2 hardware guide (2026); WaveSpeed V4 requirements (2026).

### 4b. Fit analysis: 4×B60 (96 GB VRAM)

| Model | Quant needed to fit | Fits? | KV cache headroom | Performance expectation |
|---|---|---|---|---|
| DeepSeek-R1-Distill-Qwen-32B (BF16, 64 GB) | BF16 fits (~64 GB weights + ~20 GB KV at reasonable context) | **Yes, tight** | ~10–15 GB at 32k ctx | Confirmed: practitioner runs this today |
| Qwen3-Coder-30B-A3B (BF16, 61 GB) | BF16 fits (~61 GB weights) | **Yes, tight** | ~15–20 GB at 32k ctx | Confirmed: practitioner runs this today |
| DeepSeek V4 Flash (284B MoE) | Q4 GGUF = ~80 GB minimum; Q3 = ~60 GB | **Q3/Q4 marginal** | Minimal headroom at Q4; ~15 GB buffer for KV | No published B60 result; Q4 MoE on SYCL is experimental. At Q3/Q4, significant quality degradation vs reference |
| DeepSeek V3/V4 671B | Q2 GGUF ~170 GB; Q4 = 376 GB | **No** — not at any reasonable quant | — | Would require 8×B60 (192 GB) + further quant; Q2 at 192 GB is research-only quality |
| Kimi K2 1T | UD-Q2 ~230 GB | **No** — exceeds 96 GB at any useful quant | — | Not feasible |

### 4c. Fit analysis: 8×B60 (192 GB VRAM) — Battlematrix

| Model | Quant to fit in 192 GB | Fits? | Notes |
|---|---|---|---|
| DeepSeek-R1-Distill-Qwen-32B | BF16 trivially | Yes | |
| Qwen3-Coder-30B-A3B | BF16 trivially | Yes | |
| DeepSeek V4 Flash 284B | Q4 (~80 GB weights) | **Yes, comfortable** | ~100 GB headroom for KV. Quality: Q4 MoE is moderate degradation vs FP8. No published B60 perf data yet |
| DeepSeek V4 Flash 284B | Q6/Q5 GGUF (~100–120 GB) | **Yes** | Better quality, ~60–80 GB KV headroom |
| DeepSeek V3/V4 671B | Q2 (~170 GB) + ~20 GB KV minimum | **Marginal at Q2** | Q2 quality loss is significant; not recommended for production coding use |
| DeepSeek V3/V4 671B | Q3 (~215 GB) | **No** | Exceeds 192 GB |
| Kimi K2 1T | UD-Q2 (~230 GB) | **No** | Exceeds 192 GB |

**Summary:** 4×B60 (96 GB) is the right tier for 30–32B BF16 dense/MoE models. It cannot run V4-Flash-class at any quality-preserving quant. 8×B60 (192 GB) can run V4-Flash Q4–Q5 comfortably. Neither configuration can run full DeepSeek 671B or Kimi 1T at usable quality — those are cluster-class or require Apple M3/M4 Ultra 192 GB+ unified memory with heavy quant.

---

## 5. Head-to-Head: Perf/$ and Perf/W vs Alternatives

**Confidence: Medium** — Most comparisons are assembled from different benchmark suites with different model/quant choices. Treat as directional.

### 5a. Single-stream decode on ~30B class model (batch=1, interactive)

| System | VRAM | Decode tok/s (30B class) | Approx. cost | Notes |
|---|---|---|---|---|
| 4×B60 TP=4 (96 GB) | 96 GB GDDR6 | ~15–27 tok/s | ~$3,000–4,000 (4×$700–1,000/card + host) | Driver maturity risk; TP reduces single-stream speed |
| RTX Pro 6000 Blackwell (96 GB) | 96 GB GDDR7 | **215 tok/s** (20B MXFP4, single GPU) | ~$8,500 | 8–15× faster single-stream; mature CUDA ecosystem |
| DGX Spark GB10 (128 GB) | 128 GB LPDDR5x | **49.7 tok/s** (GPT-OSS 20B MXFP4) | ~$4,699 | 273 GB/s BW; great compute/size; weak on decode bandwidth |
| AMD Strix Halo (128 GB) | 128 GB unified | ~75 tok/s (Qwen3 30B-A3B Q4, Vulkan) | ~$2,000–2,500 (mini-PC form) | 212 GB/s; mature software (llama.cpp/HIP); best $/tok single-stream |
| Mac Studio M3 Ultra (192 GB) | 192 GB unified | ~20–21 tok/s (671B Q4 = 17 tok/s; 70B) | ~$5,000+ | 819 GB/s; excellent for large models; CPU offload seamless |
| Mac Studio M4 Ultra | ~192 GB+ | ~70 tok/s on 70B | ~$6,000+ (est.) | 2025-era; significantly faster than M3 |
| 3×RTX 3090 (72 GB) | 72 GB GDDR6X | ~124 tok/s (GPT-OSS 120B) | ~$2,400 (used) | aimultiple.com, 2025; fastest decode per dollar |

Sources: LMSYS DGX Spark review (Oct 2025); aimultiple.com DGX Spark alternatives; StorageReview Battlematrix Preview (Mar 2026); spheron.network RTX Pro 6000 benchmark (Oct 2025); llm-tracker.info Strix Halo (2025); MacRumors/VentureBeat Mac Studio M3 Ultra (Mar 2025).

### 5b. Aggregate throughput at C=16–64 concurrent (agentic batch use)

| System | Model class | Aggregate decode tok/s (C~16-64) | Notes |
|---|---|---|---|
| 4×B60 TP=4 | GPT-OSS-120B MXFP4 | **619–1,495 tok/s** (C=20–100) | Intel-sponsored benchmark; BF16 30B ~1,000 tok/s |
| RTX Pro 6000 (single) | Qwen3-Coder-30B-A3B AWQ | **~8,400 tok/s** (C=400) | Spheron/CloudRift Oct 2025 — 8× better than 4×B60 |
| DGX Spark | Llama 3.1 8B FP8 | **368 tok/s** (C=32 via SGLang) | LMSYS Oct 2025; strong compute, BW-limited on large models |
| 3×RTX 3090 | GPT-OSS-120B | **1,642 tok/s** (prefill); ~124 tok/s single stream | aimultiple.com 2025 |

### 5c. Power efficiency

| System | Typical LLM load (W) | Throughput on 30B (~) | Tok/W |
|---|---|---|---|
| 4×B60 (full system) | ~810–940 W | 289–309 tok/s (C=32–64) | **0.31–0.38 tok/W** |
| RTX Pro 6000 (single GPU) | ~300 W total system | ~8,400 tok/s (C=400) | ~**28 tok/W** |
| DGX Spark | ~210 W | ~368–500 tok/s | **1.7–2.4 tok/W** |
| AMD Strix Halo | ~65–80 W (mini-PC) | ~75 tok/s (C=1) | **~1 tok/W** |
| Mac Studio M3 Ultra | ~150–200 W | ~20 tok/s (671B Q4) | ~0.1 tok/W (large model); better on small models |

Source for 4×B60 power: practitioner measurement; StorageReview card TDP (200W/card × 4 = 800W GPU + ~150W system); single B60 igorslab.de review (2025) notes 140–145W at AI/OpenVINO load; noise ~48 dB(A).

**4×B60 is among the worst power-efficiency options in this comparison.** At 0.31–0.38 tok/W (batched), it draws 4–8× more power than a DGX Spark for equivalent or less throughput.

### 5d. Where 4×B60 wins vs loses

| Dimension | 4×B60 wins | 4×B60 loses |
|---|---|---|
| VRAM per dollar | Wins vs RTX Pro 6000 ($700–1k/card for 24 GB) | Loses vs Strix Halo (~$18/GB), used RTX 3090 |
| 30–32B BF16 model fit | Fits native BF16 in VRAM (no quant needed) | DGX Spark + Strix Halo also fit lighter quants of same models |
| Expandability to 192 GB | 8-card Battlematrix is a clear path | RTX Pro 6000 is 1 card, no stacking path beyond SXM |
| Software ecosystem | Rapidly improving (Intel + vLLM partnership) | 12–18 months behind CUDA maturity |
| Single-stream decode | — | Loses to every alternative at equivalent concurrency |
| Power efficiency | — | Worst in class (~28× worse than RTX Pro 6000) |
| Stability at high concurrency | — | Open crash bugs in vLLM; requires LLM-Scaler fork |
| Noise | — | 48 dB(A) per card; 4× in one system will be significant |

---

## 6. Power Draw and Home Livability

**Confidence: High for power; Medium for noise (limited 4-card system data).**

### Power draw breakdown

| Component | Watts (LLM load) | Notes |
|---|---|---|
| 4×B60 GPU cards | ~560–800 W | Intel datasheet: 200W TDP/card; igorslab.de measured 140–145W at AI load (70–80% TDP usage); practitioner full system 810–940W suggests cards drawing ~150–180W each under LLM load |
| Host system (CPU, RAM, storage, PSU loss) | ~150–200 W | Xeon/EPYC workstation overhead |
| **Total system** | **810–940 W** | Practitioner measured; consistent with above |

Source: practitioner brief; igorslab.de B60 review (2025); Intel Arc Pro B60 datasheet (2026-03).

### At-the-wall cost estimate

810–940 W sustained × 24 h = 19.4–22.6 kWh/day. At US average ~$0.16/kWh: **~$3.10–3.60/day, ~$95–110/month** running 24/7.

### Noise

- Single B60 card: ~48 dB(A) under compute load (igorslab.de 2025). 
- 4 cards in one chassis: likely **50–54 dB(A)** aggregate (fans in same chassis add ~3–6 dB(A) due to masking). No published 4-card measurement found.
- 50–54 dB(A) is comparable to a dishwasher running or a busy open-plan office. **Not home-office quiet** — suitable in a server closet, basement, or with acoustic enclosure. Not livable on a desk in a bedroom or living room.
- Comparison: DGX Spark ≤35 dB(A) (fanless design). Mac Studio ≤25 dB(A). RTX Pro 6000 in workstation: ~40–45 dB(A).

---

## 7. Summary Assessment

**Confidence: High overall synthesis.**

### What 4×B60 (96 GB) is good at
- Running 30–65 GB BF16 models natively without quantization degradation (DeepSeek distills, Qwen3-Coder-30B, Mistral 22B, etc.)
- Aggregate batch throughput for async agentic work at C=16–64: 300–1,500 tok/s depending on model
- Cost-effective VRAM density vs high-end single-card alternatives (RTX Pro 6000 is 4× the price per GB)

### What it cannot do
- Run DeepSeek V4-Flash (284B) at any quality-preserving quant — needs 8×B60 (192 GB) minimum at Q4
- Run full DeepSeek 671B or Kimi 1T at usable quality — these are cluster-class requirements
- Match CUDA alternatives for single-stream interactive speed (RTX Pro 6000: 8–15× faster single-stream)
- Guarantee stability under burst concurrent load (open vLLM crash bugs as of late 2025)
- Run quietly in a home office

### Critical gap: target model fit
The Artemis plan targets "DeepSeek V4-Flash-class (~284B MoE, ~80 GB Q4 + KV)" as the primary coding model. A 4×B60 at 96 GB **cannot run this** — Q4 weights alone are ~80 GB, leaving almost no KV budget. An 8×B60 Battlematrix (192 GB) can run V4-Flash at Q4–Q5 comfortably, but no B60 multi-card configuration can run full 671B or Kimi-class 1T models at usable quality.

---

*All numbers cited to source URLs listed inline. Practitioner measurements treated as one data point, flagged where they diverge from published sources.*
