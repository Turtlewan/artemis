# Local LLM Expansion Hardware Research
**Date:** 2026-06-13  
**Scope:** Inference box for DeepSeek-class (~671B MoE, ~37B active) and Kimi K2-class (~1T MoE) models on home LAN. Slow-but-works acceptable. Orchestrator is a Mac Mini.

---

## Model Target Calibration (Updated)

Before evaluating hardware, note the target landscape has shifted since early 2025:

| Model | Total Params | Active Params | Min RAM (Q2) | Min RAM (Q4) | Status |
|---|---|---|---|---|---|
| DeepSeek R1 | 671B MoE | ~37B | ~192 GB | ~376 GB | Released Jan 2025 |
| DeepSeek V3 | 671B MoE | ~37B | ~192 GB | ~400 GB | Released Mar 2025 |
| DeepSeek V4-Pro | 1.6T MoE | ~49B | ~500 GB+ | ~800 GB+ | Released Apr 2026 |
| DeepSeek V4-Flash | 284B MoE | ~13B | ~80 GB | ~160 GB | Released Apr 2026 |
| DeepSeek R2 | 32B dense | 32B | ~16 GB | ~20 GB | Released Apr 2026 |
| Kimi K2 / K2.5 / K2.6 | ~1T MoE | ~32B | ~350 GB (Q2) | ~600 GB (Q4) | 2025–2026 |

**Key planning implication:** DeepSeek V4-Pro (1.6T) is effectively datacenter-only even quantized. DeepSeek R2 (32B dense) fits a single 4090. The practical home frontier for "DeepSeek-class big coding model" is currently V4-Flash (284B) or R1/V3 (671B at Q4). Kimi K2 at Q2 needs ~350 GB combined.

---

## Option Class 1: Big-RAM CPU + 1 GPU (MoE Offload Path)

### Architecture

CPU handles MoE expert weights (the bulk of RAM); a single consumer/prosumer GPU handles attention layers and KV cache. KTransformers is purpose-built for this; llama.cpp with partial GPU offload is the fallback.

### KTransformers Benchmark Data (Intel Xeon + RTX 4090D, 1TB DDR5)

**Source:** [ktransformers DeepSeek R1/V3 Tutorial](https://github.com/kvcache-ai/ktransformers/blob/main/doc/en/DeepseekR1_V3_tutorial.md) — 2025

**Hardware:** Intel Xeon Gold 6454S (2×32 cores), RTX 4090D 24GB, 1TB DDR5-4800

| Version | Config | Prefill tok/s | Decode tok/s |
|---|---|---|---|
| v0.2.1 | Single socket, 8 experts, Q4_K_M | 54 | 8.7 |
| v0.2.1 | Dual socket, 8 experts, Q4_K_M | 80 | 12.4 |
| v0.2.1 | Dual socket, 6 experts, Q4_K_M | 101 | 13.9 |
| v0.3-preview | Dual socket, 8 experts, BF16/int8 | 185–255 | ~14 (est.) |
| v0.3-preview | Dual socket, 6 experts, BF16/int8 | 203–286 | ~14 (est.) |

**Minimum config:** 14 GB VRAM + 382 GB+ system RAM  
**vs llama.cpp baseline:** Up to 27.79× faster on prefill (llama.cpp achieves ~10 tok/s prefill on same hardware)  
**Critical caveat:** AMX instruction support (Intel Sapphire/Emerald Rapids Xeon) is required for the v0.3 speeds. AMD EPYC lacks AMX; AMD performance on ktransformers is substantially lower (community reports show 2–4× speedup vs baseline, not 28×).

**Confidence: High** — from official benchmark docs and community corroboration

### AMD EPYC / Threadripper + llama.cpp Benchmarks

**Sources:** [llama.cpp Discussion #11765](https://github.com/ggml-org/llama.cpp/discussions/11765) (2025); [DigitalSpaceport EPYC article](https://digitalspaceport.com/how-to-run-deepseek-r1-671b-fully-locally-on-2000-epyc-rig/) (Feb 2025)

| Hardware | RAM | Quant | Model | Decode tok/s | Notes |
|---|---|---|---|---|---|
| AMD EPYC 7702 (64c), DDR4-2400 | 512 GB | Q4 | DeepSeek R1 671B | 3.5–4.25 | Via Ollama |
| AMD EPYC 7552 (48c), DDR4-2666 | 512 GB | Q3-K-XL | GLM-5 309B | 5.2 | +RTX 3090: +17% |
| AMD EPYC 7K62 single socket (48c) | varies | Q5_K_S | DeepSeek R1 671B | 4.2 | NUMA tuned |
| AMD EPYC 7K62 dual socket (96c) | varies | Q5_K_S | DeepSeek R1 671B | 2.9 | Dual socket hurts |
| AMD EPYC 9654, DDR5-4800 | varies | Q8 | DeepSeek R1 671B | 6.2 | Single socket optimal |
| Threadripper Pro 3955WX (16c) | varies | Q5_K_S | DeepSeek R1 671B | 2.8 | CPU-only |
| Dual EPYC 9654, DDR5, 1TB | 1 TB | IQ4_XS | DeepSeek R1 671B | 5–8 | Community avg |

**NUMA dual-socket finding:** Dual-socket barely helps or actively hurts for generation (cross-NUMA latency). Single socket is generally faster for decode. NUMA-disabled settings improved some configs from 4 to 8 tok/s.

**Threadripper Pro 7995WX / 9995WX with DDR5:**  
- 8-channel DDR5-6400 on WRX90: ~350 GB/s theoretical bandwidth  
- 512 GB config: 8×64 GB DDR5 RDIMM  
- Expected decode tok/s on 671B Q4: ~5–9 (extrapolating from bandwidth and core count)  
- No direct 2025–2026 benchmark found for 7995WX on 671B specifically

**Confidence: High** for EPYC numbers, Medium for Threadripper 7000-series extrapolation

### Build Cost Breakdown (EPYC Path, ~2025–2026 prices)

| Component | Option A (Budget) | Option B (Performance) |
|---|---|---|
| CPU | EPYC 7702 used (~$150–300) | EPYC 9654 (~$3,000–4,000) |
| Motherboard | Gigabyte MZ32-AR0 (~$400) | Supermicro H13 SP5 (~$800–1,200) |
| RAM | 16×32 GB DDR4 ECC (~$600–800) | 12×64 GB DDR5 ECC (~$2,400–3,600) |
| GPU | RTX 3090 used (~$400–600) | RTX 4090 (~$1,800–2,200) |
| PSU | 850W (~$120) | 1,600W (~$300) |
| Storage | 1 TB NVMe (~$80) | 2 TB NVMe (~$150) |
| Cooling | 420mm AIO (~$150) | Custom loop (~$400) |
| Case | Tower ATX (~$100) | Server chassis (~$300) |
| **Total** | **~$2,000–2,500** | **~$9,000–13,000** |

**Source:** [DigitalSpaceport $2000 EPYC build](https://digitalspaceport.com/how-to-run-deepseek-r1-671b-fully-locally-on-2000-epyc-rig/) (Feb 2025)

### Power, Noise, Admin Burden

- **Power (EPYC 7702 build, CPU-only):** 60 W idle, 260 W loaded  
  [Source: DigitalSpaceport Feb 2025]
- **Power (Threadripper Pro 9995WX full system):** 487 W peak under full load; 350 W TDP  
  [Source: Notebookcheck via search result, 2025]
- **Noise (Threadripper Pro build):** 52 dB at full load — audible in most home rooms, not living-room friendly. Server-grade EPYC 1U/2U chassis fans: 60–75 dB, effectively a jet. Mid-tower ATX build with quality fans: ~40–48 dB under load.
- **EPYC cooling specific problem:** Noctua has zero SP5-compatible coolers as of 2026. Silverstone XE04_SP5 is 43 dBA. Custom water loop is the main quiet option.
- **Admin burden:** Medium–High. Ubuntu Server 24.04 is stable. llama.cpp/Ollama are mature. KTransformers requires Intel AMX for peak performance (AMD works but slower). Driver churn is modest for CPU-only paths. GPU (ROCm for AMD cards) can be rocky; CUDA (NVIDIA) is stable.

**Confidence: High** for power numbers; Medium for noise (varies hugely by chassis/cooling choice)

---

## Option Class 2: Multi-GPU Path

### VRAM Requirements Reality Check

| Model | Q4 VRAM needed | Q8 VRAM needed | BF16 VRAM needed |
|---|---|---|---|
| DeepSeek R1/V3 671B | ~376 GB | ~671 GB | ~1,342 GB |
| Kimi K2 1T | ~500 GB (Q2) | ~1,000 GB | impractical |
| DeepSeek V4-Pro 1.6T | ~800 GB+ (Q2) | multi-node only | no |
| DeepSeek V4-Flash 284B | ~160 GB (Q4) | ~285 GB | ~570 GB |

**Verdict for full 671B Q4:** Need ~376 GB VRAM. Consumer GPUs (24–32 GB each) cannot reach this without CPU offloading. Even 4×RTX 4090 = 96 GB total VRAM — utterly insufficient without heavy CPU offload.

**Consumer GPU NVLink note:** RTX 5090 does NOT support NVLink. No consumer Ampere/Ada/Blackwell card supports NVLink. Multi-card consumer rigs must use PCIe tensor/pipeline parallelism, which adds significant overhead and is often slower than a single large-VRAM card for single-user decode.

**Sources:** [WillItRunAI VRAM guide](https://willitrunai.com/blog/deepseek-r1-vram-requirements-guide); [RunPod RTX 5090 guide](https://www.runpod.io/articles/guides/nvidia-rtx-5090) (2025)

### RTX PRO 6000 Blackwell (96 GB GDDR7) — Single Card

**Source:** [GamersNexus RTX PRO 6000 review](https://gamersnexus.net/gpus/nvidia-rtx-pro-6000-blackwell-benchmarks-tear-down-thermals-gaming-llm-acoustic-tests)

| Model | Decode tok/s | Notes |
|---|---|---|
| DeepSeek Llama 8B distil | 81 tok/s | In VRAM |
| Mistral Small 26B | 42.4 tok/s | Fits in 96 GB |
| Gemma 3 27B | 29 tok/s | Fits; vs 5090's 5 tok/s |
| Llama 3.3 70B | full speed | 928% lead over 5090 (70B exceeds 5090's 32 GB) |

**For 671B:** Does not fit (needs ~376 GB). Partial offload to CPU RAM needed — performance degrades to CPU-path territory.

- **Price:** $8,000–$11,000 MSRP (April 2025 launch)
- **Power:** 600 W TDP
- **Noise:** ~32.5 dBA under load (GPU only; workstation PSU/fans add more)
- **Verdict:** Excellent for ≤70B models. For 671B MoE, becomes a ktransformers-style offload card at much higher cost than a $600 used 3090.

**Confidence: High** — reviewed by GamersNexus with direct measurements

### Multiple RTX PRO 6000 (8× = 768 GB VRAM) — Comino Grando Class

**Source:** [StorageReview Comino Grando RTX PRO 6000 review](https://www.storagereview.com/review/comino-grando-rtx-pro-6000-review-768gb-of-vram-in-a-liquid-cooled-4u-chassis)

8× RTX PRO 6000 in a 4U liquid-cooled chassis = 768 GB VRAM. This IS enough for DeepSeek 671B Q4 (~376 GB) with enormous headroom.

| Model | Prefill tok/s (BS128) | Decode tok/s (BS64) |
|---|---|---|
| GPT-OSS 20B | 32,061 | 11,187 |
| GPT-OSS 120B | (high) | 11,726 |
| MiniMax M2.5 230B MoE | 7,357 | 2,555 |
| Llama 3.1 8B FP8 | — | 12,109 |

- **Power:** 4,800 W sustained (8× 600 W), up to 8,000 W PSU headroom
- **Noise:** 39–70 dB range; 70+ dB at full load
- **Price:** Not published; estimated $75,000–$120,000 for full system (8× $8,500 GPUs alone = $68,000)
- **Verdict:** Absurd for home use. Server room / dedicated space only.

**Confidence: High** for specs; Medium for price estimate

### 4× RTX 4090 (Consumer Multi-GPU)

No NVLink. 96 GB total VRAM — insufficient for 671B Q4 without massive CPU offload. Can run 671B via ktransformers/llama.cpp with CPU RAM carrying most weights. Throughput approximately same as CPU-only path (CPU becomes bottleneck). Each card draws 450 W; 4× system = ~2,000+ W. Loud. Not meaningfully better than CPU+1 GPU path for 671B MoE at a fraction of the cost.

**tinybox pro (8× RTX 4090):**  
- 192 GB GPU RAM total  
- $40,000 asking price  
- Described as "Loud" in spec sheet  
- ~1.36 PF FP16  
- Still insufficient for 671B Q4 in pure VRAM; needs CPU offload  
- **Source:** [Tom's Hardware tinybox pro](https://www.tomshardware.com/tech-industry/artificial-intelligence/ai-accelerator-tinybox-pro-goes-up-for-preorder-for-usd40-000-the-device-features-eight-rtx-4090s-and-two-amd-genoa-epyc-processors)

**Confidence: High** — well documented across multiple sources

---

## Option Class 3: Small-Box / Integrated Platform

### NVIDIA DGX Spark / GB10 (128 GB, $4,699)

**Sources:** [LMSYS Org DGX Spark review](https://www.lmsys.org/blog/2025-10-13-nvidia-dgx-spark/) (Oct 2025); [StorageReview dual-Spark cluster](https://www.storagereview.com/review/nvidia-dgx-spark-cluster-review-distributed-inference-on-dell-gigabyte-and-hp); [Apertus.ai review](https://apertus.ai/en/blog/nvidia-dgx-spark-review-vs-ai-box/)

**Single unit specs:** GB10 Grace Blackwell Superchip, 128 GB LPDDR5X unified memory, 273 GB/s bandwidth, 1 PF sparse FP4, 240 W external adapter (~100–170 W actual draw)

**Single-unit benchmarks:**

| Model | Prefill tok/s | Decode tok/s | Notes |
|---|---|---|---|
| Llama 3.1 8B FP8 (batch 1) | 7,991 | 20.5 | SGLang |
| Llama 3.1 8B FP8 (batch 32) | 7,949 | 368 | SGLang |
| DeepSeek-R1 14B FP8 (batch 8) | 2,074 | 83.5 | SGLang |
| GPT-OSS 20B MXFP4 (batch 1) | 2,053 | 49.7 | Ollama |
| Llama 3.1 70B FP8 | 803 | 2.7 | Decode collapses |
| GPT-OSS 120B MXFP4 | — | 11.66 | Prototyping only |

**Decode collapse on 70B+:** The 70B decode at 2.7 tok/s is the signature failure. Memory bandwidth (273 GB/s) is the hard wall — LPDDR5X is 6× narrower than GDDR7. For single-user use, 70B is painful; 120B is nearly unusable for real work.

**Dual-unit cluster (via 200 Gb ConnectX-7 link):** Two units = 256 GB unified, handles up to 405B FP4

| Model (dual, batch 64) | tok/s |
|---|---|
| GPT-OSS 20B | 916–977 |
| GPT-OSS 120B | 464–505 |
| Mistral Small 3.1 24B | 239–255 |
| Qwen3-30B | 780–817 |

- No 405B benchmark published yet by StorageReview despite being the advertised capability
- "Per-user throughput at tail end drops to single-digit tok/s" at high concurrency on 120B+
- For DeepSeek 671B: does NOT fit even on dual Spark (256 GB < 376 GB Q4 minimum)

**Price:** $4,699 single unit (retail, Oct 2025 launch); $9,398 for dual  
**Power (single):** ~100–170 W load; 240 W max  
**Noise:** ~35 dB at max load; near-silent at idle — home-livable  
**Software:** CUDA-native NIM stack; SGLang, Ollama supported; mature  
**Admin burden:** Low — ships with full NVIDIA AI stack, validated  

**Verdict:** Excellent for ≤30B; workable for 70B at low concurrency (~2.7 tok/s). Not viable for 671B. For the stated use case (DeepSeek-class 671B), the Spark falls short unless accepting V4-Flash (284B) or R2 (32B).

**Confidence: High** — multiple independent reviews with direct measurements

### AMD Ryzen AI Max+ 395 / Strix Halo (128 GB)

**Sources:** [Framework Desktop community thread](https://community.frame.work/t/amd-strix-halo-ryzen-ai-max-395-gpu-llm-performance-tests/72521); [Level1Techs Strix Halo benchmarks](https://forum.level1techs.com/t/strix-halo-ryzen-ai-max-395-llm-benchmark-results/233796); [Minisforum MS-S1 Max review](https://akitaonrails.com/en/2026/03/31/minisforum-ms-s1-max-amd-ai-max-395-review/) (Mar 2026); [Tweaktown AMD Strix Halo article](https://www.tweaktown.com/news/103977/amds-new-ryzen-ai-max-395-strix-halo-apu-is-3x-faster-in-deepseek-r1-bench-than-rtx-5080/index.html)

**Hardware:** Ryzen AI Max+ 395, 16c Zen 5, 40 CU RDNA 3.5 iGPU, 128 GB LPDDR5X-8000, ~215–256 GB/s effective memory bandwidth, 59 FP16 TFLOPS theoretical

**Key benchmarks (llama.cpp, ROCm/Vulkan, single-user):**

| Model | Prefill (PP512) tok/s | Decode (TG128) tok/s | Notes |
|---|---|---|---|
| Llama 2 7B Q4_0 | 998 (Vulkan) | 45.8 | |
| Qwen 3 30B-A3B MoE | 604.8 | 72.0 | MoE, ~3B active |
| Llama 4 Scout 109B MoE | 264.1 | 19.3 | 17B active |
| Shisa V2 70B | 94.7 | 5.0 | Dense 70B |
| Qwen 3.5 35B (MoE) | — | 43.2 | Minisforum review |
| Qwen 3.5 122B Q4_K_M | — | 19.2 | 81 GB model |
| Dense Qwen 2.5 72B | — | 4.5 | Dense 70B-class |
| DeepSeek-R1 32B | — | 7.4 | |

**Vs RTX 5090:** "RTX 5090 is ~7× faster" for models fitting within its 32 GB VRAM, due to GDDR7 bandwidth (~1,792 GB/s vs ~256 GB/s). But for models exceeding 32 GB, Strix Halo wins because it doesn't need CPU offload.

**For DeepSeek 671B Q4 (~376 GB):** Does NOT fit in 128 GB. Partial CPU+GPU offload path possible via ktransformers, but AMD lacks AMX — decode speed expected ~3–8 tok/s at best, similar to pure CPU EPYC systems.

**Devices and prices (June 2026):**

| Device | Config | Price |
|---|---|---|
| Framework Desktop | Ryzen AI Max+ 395, 128 GB | ~$1,999–$2,566 |
| Minisforum MS-S1 Max | Ryzen AI Max+ 395, 128 GB | ~$2,099–$2,959 |
| BOSGAME M5 AI Mini | Ryzen AI Max+ 395, 128 GB | ~$1,489–$1,795 |
| GMKtec Evo X2 | Ryzen AI Max+ 395, 128 GB | ~$1,795 |
| AMD Ryzen AI Halo Dev Kit | Ryzen AI Max+ 395, 128 GB | $3,999 (pre-order June 2026) |

**Power:** Under 100 W total system load (Minisforum review)  
**Noise:** Quiet — mini-PC form factor, low TDP, home-livable  
**Admin burden:** Medium. ROCm on Linux is improving but still has rough edges vs CUDA. Vulkan backend works as fallback. Software stack maturing fast (50% perf improvement observed over 3 months in community thread).

**Verdict:** Best value for models ≤128 GB (fits 70B dense at Q4, 109B Scout MoE, 122B Qwen MoE). Quiet, cheap, low power. Not a solution for 671B+.

**Confidence: High** for benchmarks; Medium for AMD ROCm stability claim (improving but not fully stable per community reports)

### Intel Equivalents

Intel Panther Lake (Core Ultra 300 series, launched CES 2026) supports up to 128 GB DDR5 or LPCAMM, 120 GPU TOPS + 50 NPU TOPS = 180 total TOPS. Memory bandwidth is lower than Strix Halo (Lunar Lake was 68 GB/s; Panther Lake improved but specific numbers not published). No LLM benchmarks yet for Panther Lake mini-PCs as of June 2026 — hardware shipping but community testing sparse.

**Intel path: Low confidence** — insufficient real-world benchmark data as of research date

---

## Option Class 4: Prebuilt / Turnkey

### NVIDIA DGX Spark

Covered above. $4,699. Low admin burden. Not viable for 671B.

### AMD Ryzen AI Halo Dev Kit

$3,999 pre-order June 2026. Same Strix Halo silicon as cheaper OEM mini-PCs ($1,800–$2,100). Premium is for AMD developer ecosystem support, validated packages, 15 AI playbooks. Not justifiable for pure inference use.

**Source:** [ServeTheHome AMD Ryzen AI Halo announcement](https://www.servethehome.com/amd-details-ryzen-ai-halo-ai-dev-mini-pc-pre-orders-in-june-for-3999/)

### tinybox / tinybox pro (tinygrad)

- **tinybox** (6× RTX 4090 variant): ~$15,000  
- **tinybox pro** (8× RTX 4090 + 2× EPYC Genoa): $40,000  
- 8× 4090 = 192 GB GPU RAM — still insufficient for 671B Q4 without CPU offload  
- Described as "Loud"  
- **Sources:** [Tom's Hardware tinybox pro preorder](https://www.tomshardware.com/tech-industry/artificial-intelligence/ai-accelerator-tinybox-pro-goes-up-for-preorder-for-usd40-000-the-device-features-eight-rtx-4090s-and-two-amd-genoa-epyc-processors)  
- **Verdict:** Very expensive. Loud. Only a marginal improvement for 671B vs much cheaper CPU build.

### Comino Grando

- Multi-GPU liquid-cooled server line (4U chassis)  
- Options: 8× RTX 4090 (inference focus), 8× L40S, 8× RTX PRO 6000 (768 GB)  
- 8× RTX 4090 Grando: ~$15,000–$25,000 estimated (pricing not publicly listed)  
- 8× RTX PRO 6000: GPU cost alone ~$68,000+  
- 39–70 dB; requires 240V circuit or higher; dedicated server space  
- **Source:** [Comino Grando website](https://www.grando.ai/en/deep-learning); [StorageReview Comino Grando RTX PRO 6000 review](https://www.storagereview.com/review/comino-grando-rtx-pro-6000-review-768gb-of-vram-in-a-liquid-cooled-4u-chassis)  
- **Verdict:** Only the 8× RTX PRO 6000 config (768 GB VRAM) natively handles 671B. Overkill and wildly expensive for home use.

---

## Option Class 5: Power / Noise / Admin Burden Summary

| Option | Est. Load Power | Noise | Admin Burden | Home-Livable? |
|---|---|---|---|---|
| EPYC 7702 build (CPU+1 GPU, tower) | 260–350 W | 40–48 dB (tower) / 65–75 dB (1U chassis) | Medium | Tower: Yes (adjacent room). Rack: No. |
| Threadripper Pro 9995WX build | 487 W peak | 52 dB | Medium | Tolerable in server closet |
| DGX Spark (single) | 100–170 W | ~35 dB max | Low | Yes — desktop-friendly |
| Strix Halo mini-PC | <100 W | <40 dB | Medium (ROCm) | Yes — near-silent |
| 4× RTX 4090 tower | ~2,000 W | 60–70 dB | High | No |
| tinybox pro | ~3,500 W | "Loud" | High | No — server room only |
| Comino Grando 8× PRO 6000 | 4,800 W | 39–70 dB | High | No — 240V circuit, dedicated room |

---

## Option Class 6: Horizon (6–12 Months from June 2026)

### AMD Gorgon Halo (Strix Halo Refresh, late 2026)

Engineering samples circulating with board partners as of mid-2026. Expected late Q4 2026. Will remain Zen 5 / RDNA 3.5 but with LPDDR6 memory support — bandwidth improvement likely 20–30% over current Strix Halo. Still 128 GB max. Still insufficient for 671B+ without offload.  
**Source:** [KitGuru Strix Halo refresh](https://www.kitguru.net/components/cpu/joao-silva/amd-is-reportedly-readying-strix-halo-refresh-for-ryzen-ai-max-400-series/)

### AMD Medusa Halo / Ryzen AI Max 500 (2027–2028)

Zen 6 + RDNA 5. CES 2028 timeframe. Not relevant to 6–12 month horizon.

### Apple M5 Ultra Mac Studio (expected WWDC June 2026 or Oct 2026)

- Expected: 96–256 GB unified memory, ~1,100 GB/s bandwidth (vs M3 Ultra's 819 GB/s)  
- At 256 GB: Can fit DeepSeek R1/V3 671B at Q2/IQ2 or aggressive quants  
- For Mac orchestrator owner: natural pairing for Athena-style macOS client (ADR-017)  
- Not a dedicated inference box but may serve dual purpose  
- **Source:** [Macworld M5 Ultra rumors](https://www.macworld.com/article/2973459/2026-mac-studio-m5-release-date-specs-price-rumors.html)

### DeepSeek V4-Flash (284B, April 2026)

Already released. ~160 GB Q4 — fits in dual DGX Spark (256 GB), fits in 2× Strix Halo nodes (impractical), fits in a large 256 GB RAM CPU server. Changes the calculus: V4-Flash is the practical frontier target, not V4-Pro (1.6T).

### Intel Panther Lake Mini-PCs (2026)

Up to 128 GB DDR5/LPCAMM, 120 GPU TOPS. Potential Strix Halo competition but no LLM benchmark data yet. Memory bandwidth likely lower than Strix Halo.

---

## Synthesis: Which Path for This Use Case?

**Target:** Single home LAN inference box. Slow-but-works acceptable. Mac Mini orchestrator. Priority models: DeepSeek R1/V3 671B AND Kimi K2-class 1T MoE.

| Path | Best Config | 671B decode tok/s | Kimi K2 Q2 (350 GB) | Cost | Livability |
|---|---|---|---|---|---|
| CPU + 1 GPU (Intel+ktransformers) | Xeon 6454S dual ×2 + RTX 4090 + 1TB DDR5 | 12–14 (decode) / 200–286 (prefill) | ~8–12 (est.) | ~$8,000–14,000 | Medium — tower, ~350W |
| CPU + 1 GPU (AMD EPYC, llama.cpp) | EPYC 9654 + RTX 4090 + 512 GB DDR5 | 5–8 | ~3–6 | ~$6,000–10,000 | Medium — tower, ~350W |
| Dual DGX Spark | 2× GB10, 256 GB total | Does not fit (256 GB < 376 GB Q4) | Does not fit (350 GB > 256 GB) | $9,398 | Excellent |
| Strix Halo 128 GB | Minisforum MS-S1 Max | Does not fit (128 GB) | Does not fit | ~$2,100 | Excellent |
| 4× RTX 4090 (no NVLink) | DIY | Does not fit in VRAM; CPU-offload ~5–8 tok/s | Does not fit | ~$8,000–12,000 | Poor (loud/hot) |
| RTX PRO 6000 single | Workstation | Does not fit | Does not fit | ~$12,000+ ws | Moderate |

**Winner for the stated use case (671B + Kimi K2):** Intel Xeon + ktransformers path. It is the only cost-effective home option that actually achieves workable decode speeds (12–14 tok/s) AND covers the RAM requirement for both models at reasonable quant. A 1TB DDR5 config handles Kimi K2 Q2 (~350 GB). AMD EPYC is half the speed for the same price; the AMX gap is decisive.

**If accepting DeepSeek V4-Flash (284B) as the "big model" target instead:** Dual DGX Spark becomes competitive — it fits Flash in VRAM, delivers solid single-user throughput, and is the quietest / lowest-admin option. But Flash is a step down from R1/V3 671B quality.

---

## Source Index

1. [DigitalSpaceport: $2000 EPYC DeepSeek build](https://digitalspaceport.com/how-to-run-deepseek-r1-671b-fully-locally-on-2000-epyc-rig/) — Feb 2025
2. [ktransformers DeepSeek R1/V3 tutorial benchmarks](https://github.com/kvcache-ai/ktransformers/blob/main/doc/en/DeepseekR1_V3_tutorial.md) — 2025
3. [llama.cpp Discussion #11765: CPU-only 671B benchmarks](https://github.com/ggml-org/llama.cpp/discussions/11765) — 2025
4. [LMSYS Org DGX Spark In-Depth Review](https://www.lmsys.org/blog/2025-10-13-nvidia-dgx-spark/) — Oct 2025
5. [StorageReview DGX Spark cluster review](https://www.storagereview.com/review/nvidia-dgx-spark-cluster-review-distributed-inference-on-dell-gigabyte-and-hp) — 2025
6. [Apertus.ai DGX Spark vs AI-Box](https://apertus.ai/en/blog/nvidia-dgx-spark-review-vs-ai-box/) — 2025
7. [Framework community: Strix Halo LLM benchmarks](https://community.frame.work/t/amd-strix-halo-ryzen-ai-max-395-gpu-llm-performance-tests/72521) — 2025–2026
8. [Level1Techs Strix Halo benchmark thread](https://forum.level1techs.com/t/strix-halo-ryzen-ai-max-395-llm-benchmark-results/233796) — 2025–2026
9. [Minisforum MS-S1 Max review (AkitaOnRails)](https://akitaonrails.com/en/2026/03/31/minisforum-ms-s1-max-amd-ai-max-395-review/) — Mar 2026
10. [GamersNexus RTX PRO 6000 review](https://gamersnexus.net/gpus/nvidia-rtx-pro-6000-blackwell-benchmarks-tear-down-thermals-gaming-llm-acoustic-tests) — 2025
11. [StorageReview Comino Grando RTX PRO 6000](https://www.storagereview.com/review/comino-grando-rtx-pro-6000-review-768gb-of-vram-in-a-liquid-cooled-4u-chassis) — 2026
12. [Unsloth Kimi K2.6 local guide](https://unsloth.ai/docs/models/kimi-k2.6) — 2026
13. [Tom's Hardware tinybox pro preorder](https://www.tomshardware.com/tech-industry/artificial-intelligence/ai-accelerator-tinybox-pro-goes-up-for-preorder-for-usd40-000-the-device-features-eight-rtx-4090s-and-two-amd-genoa-epyc-processors) — 2025
14. [Julien Simon: What to buy for local LLMs (April 2026)](https://julsimon.medium.com/what-to-buy-for-local-llms-april-2026-a4946a381a6a) — Apr 2026
15. [DeepSeek V4 architecture guide](https://www.morphllm.com/deepseek-v4) — 2026
16. [ServeTheHome AMD Ryzen AI Halo Dev Kit](https://www.servethehome.com/amd-details-ryzen-ai-halo-ai-dev-mini-pc-pre-orders-in-june-for-3999/) — June 2026
17. [KitGuru Strix Halo refresh (Gorgon Halo)](https://www.kitguru.net/components/cpu/joao-silva/amd-is-reportedly-readying-strix-halo-refresh-for-ryzen-ai-max-400-series/) — 2026
18. [WillItRunAI VRAM guide](https://willitrunai.com/blog/deepseek-r1-vram-requirements-guide) — 2025
19. [Macworld M5 Ultra rumors](https://www.macworld.com/article/2973459/2026-mac-studio-m5-release-date-specs-price-rumors.html) — 2026
20. [Notebookcheck Threadripper Pro 9995WX](https://www.notebookcheck.net/AMD-launches-Ryzen-Threadripper-9000-Shimada-Peak-series-led-by-the-96C-192T-350-W-Ryzen-Threadripper-Pro-9995WX.1021230.0.html) — 2025
