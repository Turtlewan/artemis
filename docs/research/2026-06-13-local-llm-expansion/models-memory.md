# Local LLM Expansion Research — Models & Memory
**Date:** 2026-06-13  
**Purpose:** Hardware sizing for Artemis Mac Mini expansion — two roles: (1) agentic coding (DeepSeek-class), (2) big-context jobs (Kimi-class)

---

## 1. DeepSeek Model Family (as of mid-2026)

**Confidence: High** — V3/V3.1/V4 have published HF model cards and multiple independent deployment guides; R2 info is from early post-release sources so some specs provisional.

### DeepSeek V3 Lineage

| Version | Release | Total Params | Active Params | Context | Architecture | Open Weights | License |
|---|---|---|---|---|---|---|---|
| V3 (original) | Dec 2024 | 671B | 37B | 128K | MoE + MLA | Yes, HF | MIT |
| V3-0324 | Mar 2025 | 685B | ~37B | 128K | MoE + MLA | Yes, HF | MIT |
| V3.1 | Aug 2025 | 671B | 37B | 128K | MoE + MLA + hybrid reasoning | Yes, HF | MIT |
| V3.2 | Late 2025 | 685B | ~37B | 128K | MoE + upgraded attention | Yes, HF | MIT |

**Sources:**
- [DeepSeek V3-0324 vs V3.1 analysis](https://www.runpod.io/blog/deepseek-v3-1-a-technical-analysis-of-key-changes) (2025)
- [BentoML complete guide](https://www.bentoml.com/blog/the-complete-guide-to-deepseek-models-from-v3-to-r1-and-beyond) (2025)

**Notes on V3 lineage:**
- V3-0324: same base as V3, improved post-training from R1's RL techniques; better coding/tool use
- V3.1: 671B total (slightly smaller than 685B in 0324), introduces dynamic reasoning toggle (fast vs chain-of-thought)
- V3.2: serves as both `deepseek-chat` (non-thinking) and `deepseek-reasoner` (thinking) on the API; V3.2-Exp is the experimental upgraded variant
- All versions use MLA (Multi-head Latent Attention) for KV cache compression

### DeepSeek V4 Family (April 2026)

| Version | Release | Total Params | Active Params | Context | Architecture | Open Weights | License |
|---|---|---|---|---|---|---|---|
| V4-Flash | Apr 2026 | 284B | 13B | 1M tokens | MoE + hybrid sparse attention (CSA+HCA) | Yes, HF | MIT |
| V4-Pro | Apr 2026 | 1.6T | 49B | 1M tokens | MoE + hybrid sparse attention (CSA+HCA) | Yes, HF (access terms) | MIT |

**Sources:**
- [MorphLLM V4 specs](https://www.morphllm.com/deepseek-v4) (Apr 2026)
- [SitePoint V4 release](https://www.sitepoint.com/deepseek-v4-released-whats-new-in-the-latest-model-2026/) (Apr 2026)
- [vLLM blog on V4 attention](https://vllm-project.github.io/2026/04/24/deepseek-v4.html) (Apr 2026)

**Key V4 architectural notes:**
- V4 replaces MLA with hybrid Compressed Sparse Attention (CSA) and Heavily Compressed Attention (HCA)
- At 1M token context: V4-Pro needs only 9.62 GiB KV cache per sequence (bf16) vs 83.9 GiB for V3.2 — ~8.7× reduction
- V4-Pro benchmarks: 80.6% SWE-bench Verified (highest open-weights as of Apr 2026, tied with Gemini 3.1 Pro)

### DeepSeek R2 (April 2026)

| Version | Release | Total Params | Active Params | Context | Architecture | Open Weights | License |
|---|---|---|---|---|---|---|---|
| R2 | Apr 2026 | 32B | 32B (dense) | 256K (reported) | Dense transformer | Yes, MIT | MIT |

**Sources:**
- [DecodetheFuture R2 explained](https://decodethefuture.org/en/deepseek-r2-explained/) (2026)
- [SitePoint R2 guide](https://www.sitepoint.com/deepseek-r2-what-developers-need-to-know-before-august/) (2026)

**Notes:** R2 is a 32B DENSE model (not MoE) — a sharp pivot from the 671B MoE R1. Scores 92.7% AIME 2025. Fits on a single RTX 4090 (24GB). Technical report not yet published as of research date; some architecture claims provisional.

---

## 2. Kimi / Moonshot AI Model Family (as of mid-2026)

**Confidence: High for K2–K2.6; Medium for K2.7 Code** (K2.7 appeared on HF June 12, 2026, one day before this research; specs from early post)

### Kimi K2 Lineage

| Version | Release | Total Params | Active Params | Experts | Context | Open Weights | License |
|---|---|---|---|---|---|---|---|
| K2 (original) | Mid-2025 | ~1T | 32B | 384 (8+1 shared) | 128K | Yes, HF | Modified MIT |
| K2.5 | Jan 2026 | ~1T | 32B | 384 | 128K–256K | Yes, HF | Modified MIT |
| K2.6 | Apr 20 2026 | ~1T | 32B | 384 (8+1) | 256K | Yes, HF | Modified MIT |
| K2.7 Code | Jun 12 2026 | ~1T (≈1.1T on disk) | 32B | 384 (8+1) | 256K | Yes, HF | Modified MIT |

**Sources:**
- [Kimi K2.6 explained — MiraFlow](https://miraflow.ai/blog/kimi-k2-6-explained-moonshot-ai-open-source-model-ties-gpt-5-5-coding) (Apr 2026)
- [Kimi K2.7 guide — CoderSera](https://codersera.com/blog/kimi-k2-7-complete-guide-2026/) (Jun 2026)
- [HowAIWorks K2.6 release](https://howaiworks.ai/blog/moonshot-kimi-k2-6-release-announcement) (Apr 2026)

**Key notes:**
- All K2.x use MLA (Multi-head Latent Attention) — same efficiency technique as DeepSeek
- Architecture: 61 layers (1 dense), 64 attention heads, 160K vocabulary
- K2.6 includes MoonViT (400M param vision encoder) — image/video input
- K2.7 Code: forces reasoning mode on (cannot disable thinking tokens); described as SOTA for 12-hour long-horizon coding agents
- K2.6 benchmark: ties GPT-5.5 on coding per community reports; 76.8% SWE-bench Verified (K2.5)

---

## 3. Quantization Footprints — Actual RAM/VRAM Requirements

**Confidence: High for smaller models; Medium for 1T+ MoE** (large MoE numbers extrapolated from GGUF file sizes + community deployment reports; no single authoritative benchmark)

### 3a. DeepSeek V3/V3.1/V3.2 (671–685B MoE, 37B active)

| Quant | File Size | Min RAM (weights only) | Practical Min (w/ KV+overhead) | Notes |
|---|---|---|---|---|
| BF16 | ~1.4 TB | ~1.4 TB | ~1.6 TB | Impractical for local |
| Q8_0 | ~680 GB | ~680 GB | ~720 GB | Near-lossless |
| Q4_K_M | ~380–405 GB | ~380 GB | ~420 GB | Community-reported; fits M3 Ultra 512GB |
| Q2_K (extreme) | ~170 GB | ~170 GB | ~200 GB | Quality degradation |

**Apple Silicon measured:**
- M3 Ultra 512GB: runs Q4_K_M at ~6.2 tok/s (14-min prefill for 8K prompt)
- M4 Ultra 256GB: int4 variant reported runnable (tight)
- MLX is 1.5–2× faster than llama.cpp on Apple Silicon for this model

**Sources:**
- [Hardware Corner M3 Ultra test](https://www.hardware-corner.net/mac-studio-m3-ultra-deepseek-llamacpp/) (2025)
- [apxml Mac system requirements](https://apxml.com/posts/deepseek-system-requirements-mac-os-guide) (2025)

### 3b. DeepSeek V4-Flash (284B MoE, 13B active)

| Quant | File Size | Min VRAM/RAM | Safer Target | Notes |
|---|---|---|---|---|
| FP8 (native) | ~160 GB | ~175 GB | ~192 GB | Best quality |
| Q6 | ~120 GB | ~160 GB | ~192 GB | |
| Q5 | ~100 GB | ~128 GB | ~160 GB | |
| Q4_K_M | ~80 GB | ~96 GB | ~128 GB | Community sweet spot |
| Q3 | ~60 GB | ~80 GB | ~96 GB | |
| Q2 (extreme) | ~40 GB | ~48 GB | ~64 GB | Quality loss |

**Mac Apple Silicon:**
- 128 GB unified: runs IQ2XXS "antirez path" (experimental fork), ~90 GB footprint
- 192 GB+: Q4_K_M comfortable
- 256 GB: Q5/Q6 range

**Sources:**
- [CoderSera V4 VRAM guide](https://codersera.com/blog/deepseek-v4-vram-gpu-requirements-2026/amp/) (2026)
- [KnightLi V4 VRAM table](https://knightli.com/en/2026/05/01/deepseek-v4-local-vram-quantization-table/) (May 2026)
- [DeepSeekV4Pro Flash Mac guide](https://deepseekv4pro.com/guides/deepseek-v4-flash-local-mac) (2026)

### 3c. DeepSeek V4-Pro (1.6T MoE, 49B active)

| Quant | File Size | Min VRAM/RAM | Safer Target | Notes |
|---|---|---|---|---|
| FP8 (native) | ~865 GB | ~1.0 TB | ~1.2 TB | |
| Q6 | ~648 GB | ~768 GB | ~1 TB | |
| Q5 | ~540 GB | ~640 GB | ~768 GB | |
| Q4 | ~432 GB | ~512 GB | ~640 GB | |

**Not feasible on single-box Mac. Multi-node only.**

**Sources:**
- [KnightLi V4-Pro VRAM table](https://knightli.com/en/2026/05/01/deepseek-v4-local-vram-quantization-table/) (May 2026)

### 3d. DeepSeek R2 (32B dense)

| Quant | File Size | Min VRAM/RAM | Notes |
|---|---|---|---|
| BF16 | ~64 GB | ~64 GB | Fits 64GB Mac |
| Q8 | ~32 GB | ~35 GB | Near-lossless; 1 RTX 4090 |
| Q4_K_M | ~20 GB | ~22 GB | 1× RTX 4090 or 24GB Mac |
| Q2 | ~10 GB | ~12 GB | Consumer GPU |

**Sources:**
- [DecodetheFuture R2](https://decodethefuture.org/en/deepseek-r2-explained/) (2026)
- Extrapolated from R1-distill 32B community measurements (same parameter count)

### 3e. Kimi K2 / K2.6 / K2.7 Code (1T MoE, 32B active)

| Quant | File Size | Min RAM+VRAM | Speed (est.) | Notes |
|---|---|---|---|---|
| BF16 | ~2 TB | ~2+ TB | N/A | Impractical |
| UD-Q8_K_XL | ~595 GB | ~610 GB | 4–6 tok/s | Lossless |
| UD-Q4_K_XL | ~585 GB | ~600 GB | 5–8 tok/s | Near-lossless; practical target |
| UD-Q2_K_XL | ~340 GB | ~350 GB | 7–10 tok/s | Dynamic 2-bit with 8-bit upcast on critical layers |

**Note:** Q4 and Q8 are almost the same file size for K2.x — the UD dynamic quants use 8-bit for critical layers, bloating Q8 only slightly beyond Q4. The practical minimum for quality deployment is ~350 GB at Q2.

**Deployment paths:**
- 2× Mac Studio M4 Ultra (2×192 GB = 384 GB): Q2 fits; Q4 tight
- 4× RTX 3090 + 256 GB RAM (352 GB total): Q2 fits; ~7 tok/s
- CPU-only 384 GB DDR5: Q2 fits; ~10 tok/s

**Sources:**
- [RunAIHome Kimi K2 hardware guide](https://runaihome.com/blog/kimi-k2-local-inference-hardware-guide-2026/) (2026)
- [Unsloth Kimi K2.6 docs](https://unsloth.ai/docs/models/kimi-k2.6) (2026)
- [Mem0 Kimi K2.6 memory traces](https://mem0.ai/blog/reading-the-traces-what-two-charts-tell-us-about-kimi-k2.6%E2%80%99s-memory) (2026)

---

## 4. KV-Cache Scaling (Context Length Extra Memory)

**Confidence: High for DeepSeek V3 MLA numbers (from published technical report + vLLM blog); High for V4 at 1M (from vLLM official blog); Medium for V4 at shorter contexts (linear extrapolation only)**

### MLA (DeepSeek V3/V3.1/V3.2) KV Cache

MLA compresses K/V into a 512-dim latent vs standard 4096-dim, achieving ~70 KB per token.

| Context Length | KV Cache Memory (bf16) | Notes |
|---|---|---|
| 4K | ~0.27 GB | Negligible |
| 32K | ~2.2 GB | Negligible |
| 128K | ~8.7 GB | Very manageable |
| 256K | ~17.4 GB | Linear extrapolation |

**Compare:** LLaMA 405B uses 516 KB/token → 64.2 GB at 128K context. DeepSeek V3 MLA is ~7× more efficient.

**Source:** [vLLM blog DeepSeek V4 context analysis](https://vllm-project.github.io/2026/04/24/deepseek-v4.html) (Apr 2026); [MLA deep dive Medium](https://medium.com/foundation-models-deep-dive/deepseeks-multi-head-latent-attention-mla-is-shrinking-the-kv-cache-27328f7dda27)

### V4 Hybrid Attention KV Cache

V4's new CSA+HCA mechanism compresses even further than MLA:

| Context Length | V4-Pro KV Cache (bf16/sequence) | V3.2 equivalent | Reduction |
|---|---|---|---|
| 1M tokens | 9.62 GiB | 83.9 GiB | ~8.7× |
| 256K | ~2.5 GiB | ~21 GiB | ~8.7× (linear) |
| 128K | ~1.25 GiB | ~10.5 GiB | ~8.7× (linear) |
| 32K | ~0.31 GiB | ~2.6 GiB | ~8.7× (linear) |

With FP4/FP8 cache (V4 default): further 2× reduction beyond the bf16 figures above.

**Source:** [vLLM DeepSeek V4 blog](https://vllm-project.github.io/2026/04/24/deepseek-v4.html) (Apr 2026)

### Kimi K2.x KV Cache

K2.x also uses MLA. No published per-token breakdown found; community guidance recommends "keep context short" to manage RAM pressure. Expected to be in same ballpark as DeepSeek V3 MLA (~70 KB/token), but not confirmed.

---

## 5. Fallback Models by Role

**Confidence: High for benchmarks; Medium for exact memory at smaller quants** (memory numbers from community guides; benchmarks from published leaderboards)

### Role 1: Coding (fits in 64 / 128 / 256 GB)

| Model | Params (total/active) | Context | SWE-bench % | Q4 Memory | Fits in |
|---|---|---|---|---|---|
| DeepSeek R2 | 32B dense | 256K | ~60%+ (reasoning) | ~20 GB | 64 GB ✓ |
| Devstral Small 2 | 24B dense | 256K | 68.0% | ~15 GB | 64 GB ✓ |
| Qwen3-Coder-30B (30B/3B active) | 30B MoE | 256K | ~65%+ | ~18 GB | 64 GB ✓ |
| Devstral 2 | 123B dense | 256K | 72.2% | ~75 GB | 128 GB ✓ |
| Qwen3-Coder-Next (80B/3.9B active) | 80B MoE | 256K | 70.6% | ~46 GB | 64 GB ✓ |
| Qwen3-Coder-480B (480B/35B active) | 480B MoE | 256K | ~70% | ~290 GB | 512 GB |
| DeepSeek V4-Flash | 284B/13B | 1M | 80.6%* | ~96 GB | 128 GB (tight) |
| DeepSeek V3.2 | 685B/37B | 128K | 73% | ~405 GB | 512 GB |

*V4-Pro score; V4-Flash will be lower but not yet published separately.

**Best 64 GB picks:** Qwen3-Coder-Next (80B MoE, only 46 GB at Q4, 70.6% SWE-bench), Devstral Small 2 (24B, 68.0%)  
**Best 128 GB pick:** Devstral 2 (123B, 72.2%), or DeepSeek V4-Flash at Q2 extreme  
**Best 256 GB pick:** DeepSeek V4-Flash at Q4 (96 GB with room to spare), or Qwen3-Coder-480B at Q2

**Sources:**
- [MorphLLM best coding models 2026](https://www.morphllm.com/best-open-source-coding-model-2026) (2026)
- [Devstral 2 VentureBeat](https://venturebeat.ai/ai/mistral-launches-powerful-devstral-2-coding-model-including-open-source) (2026)
- [Devstral DigitalOcean guide](https://www.digitalocean.com/community/tutorials/devstral-2-mistral-coding-open-weight-model) (2026)
- [Qwen3-Coder Unsloth docs](https://unsloth.ai/docs/models/tutorials/qwen3-coder-how-to-run-locally) (2026)

### Role 2: Long Context (fits in 64 / 128 / 256 GB)

| Model | Params (total/active) | Context | Quality Notes | Q4 Memory | Fits in |
|---|---|---|---|---|---|
| Qwen3-30B-A3B | 30B/3B MoE | 256K (extendable 1M) | Strong general; widely used | ~18 GB | 64 GB ✓ |
| Gemma 4 26B (26B/3.8B MoE) | 26B/3.8B | 256K | Google; good long-context handling | ~16 GB | 64 GB ✓ |
| Mistral Small 4 | 119B/6.5B MoE | 256K | Apache 2.0; multimodal | ~60 GB | 128 GB ✓ |
| Llama 4 Scout | 109B/17B MoE | 10M | Best open context window; 10M tokens | ~55 GB | 128 GB ✓ |
| Llama 4 Maverick | 402B MoE | 1M | Strong; needs ~122 GB at 1.78-bit | ~122 GB | 256 GB ✓ |
| DeepSeek V4-Flash | 284B/13B MoE | 1M | Coding + long context; best open-weights | ~96 GB | 192 GB ✓ |
| Kimi K2.6 | 1T/32B MoE | 256K | Best-in-class long-context + coding | ~350 GB Q2 | 512 GB |

**Best 64 GB long-context pick:** Llama 4 Scout at Q2 (~32 GB) or Qwen3-30B for 256K tasks  
**Best 128 GB pick:** Llama 4 Scout at Q4 (~55 GB) for 10M context capability  
**Best 256 GB pick:** DeepSeek V4-Flash at Q4 (96 GB) — handles 1M context natively with tiny KV cache overhead

**Sources:**
- [PromptQuorum long context LLMs](https://www.promptquorum.com/local-llms/long-context-local-llms) (2026)
- [SiliconFlow long context guide](https://www.siliconflow.com/articles/en/top-LLMs-for-long-context-windows) (2026)
- [Llama 4 hardware guide — Compute Market](https://www.compute-market.com/blog/llama-4-local-hardware-guide-2026) (2026)

---

## 6. Fit Table: Model × Quant → Minimum Memory Tier

**Confidence: High** (built from sections 3 & 5 above; numbers are practical minimums including KV cache at moderate context)

| Model | Quant | File Size | Min Tier | Notes |
|---|---|---|---|---|
| DeepSeek R2 (32B dense) | Q4_K_M | ~20 GB | **64 GB** | Comfortable; 1× RTX 4090 or any Mac |
| DeepSeek R2 (32B dense) | Q8 | ~32 GB | **64 GB** | Near-lossless |
| DeepSeek R2 (32B dense) | BF16 | ~64 GB | **64 GB** | Tight; needs exactly 64 GB |
| Devstral Small 2 (24B) | Q4_K_M | ~15 GB | **64 GB** | Easy |
| Qwen3-Coder-Next (80B/3.9B) | Q4_K_M | ~46 GB | **64 GB** | Top-class coding at 64 GB |
| Qwen3-Coder-30B (30B/3B) | Q8 | ~32 GB | **64 GB** | |
| Llama 4 Scout (109B/17B) | Q2 dynamic | ~32 GB | **64 GB** | 10M context; low quant |
| Llama 4 Scout (109B/17B) | Q4_K_M | ~55 GB | **64 GB** | Tight; 10M context |
| Gemma 4 26B | Q4_K_M | ~16 GB | **64 GB** | 256K context |
| Devstral 2 (123B) | Q4_K_M | ~75 GB | **128 GB** | 72.2% SWE-bench |
| Mistral Small 4 (119B/6.5B) | Q4_K_M | ~60 GB | **128 GB** | 256K context; Apache 2.0 |
| Llama 4 Scout | Q6 | ~82 GB | **128 GB** | Better quality |
| DeepSeek V4-Flash (284B/13B) | Q2 extreme | ~40 GB | **64 GB** (experimental) | Antirez fork; quality hit |
| DeepSeek V4-Flash (284B/13B) | Q3 | ~60 GB | **128 GB** | |
| DeepSeek V4-Flash (284B/13B) | Q4_K_M | ~80 GB | **128 GB** (tight) / **192 GB** (safe) | 1M context; recommended tier |
| DeepSeek V4-Flash (284B/13B) | Q5 | ~100 GB | **192 GB** | |
| DeepSeek V4-Flash (284B/13B) | Q6 | ~120 GB | **192 GB** | |
| DeepSeek V4-Flash (284B/13B) | FP8 | ~160 GB | **256 GB** | |
| Llama 4 Maverick (402B MoE) | Q1.78-bit | ~122 GB | **256 GB** | |
| Qwen3-Coder-480B (480B/35B) | Q2_K | ~175 GB | **256 GB** | |
| Qwen3-Coder-480B (480B/35B) | Q4_K_M | ~290 GB | **512 GB** | |
| Qwen3-Coder-480B (480B/35B) | Q5_K_M | ~340 GB | **512 GB** | |
| DeepSeek V3.2 (685B/37B) | Q4_K_M | ~380–405 GB | **512 GB** | M3 Ultra 512 GB tested |
| DeepSeek V3.2 (685B/37B) | Q2 | ~170 GB | **256 GB** | Quality degraded |
| Kimi K2.6 (1T/32B) | UD-Q2_K_XL | ~340 GB | **512 GB** | Dynamic 2-bit with 8-bit upcasts |
| Kimi K2.6 (1T/32B) | UD-Q4_K_XL | ~585 GB | **multi-box / 512 GB+** | |
| DeepSeek V4-Pro (1.6T/49B) | Q4 | ~432 GB | **multi-box** | Cluster-class only |
| DeepSeek V4-Pro (1.6T/49B) | FP8 | ~865 GB | **multi-box** | |

---

## Source Index

| Source | URL | Date |
|---|---|---|
| MorphLLM DeepSeek V4 | https://www.morphllm.com/deepseek-v4 | Apr 2026 |
| SitePoint DeepSeek V4 | https://www.sitepoint.com/deepseek-v4-released-whats-new-in-the-latest-model-2026/ | Apr 2026 |
| vLLM V4 context blog | https://vllm-project.github.io/2026/04/24/deepseek-v4.html | Apr 2026 |
| CoderSera V4 VRAM | https://codersera.com/blog/deepseek-v4-vram-gpu-requirements-2026/amp/ | 2026 |
| KnightLi V4 VRAM table | https://knightli.com/en/2026/05/01/deepseek-v4-local-vram-quantization-table/ | May 2026 |
| Kimi K2.7 guide | https://codersera.com/blog/kimi-k2-7-complete-guide-2026/ | Jun 2026 |
| RunAIHome Kimi K2 hardware | https://runaihome.com/blog/kimi-k2-local-inference-hardware-guide-2026/ | 2026 |
| Unsloth Kimi K2.6 | https://unsloth.ai/docs/models/kimi-k2.6 | 2026 |
| Unsloth Kimi K2 GGUF | https://huggingface.co/unsloth/Kimi-K2-Instruct-GGUF | 2026 |
| Unsloth Qwen3-Coder | https://unsloth.ai/docs/models/tutorials/qwen3-coder-how-to-run-locally | 2026 |
| Qwen3-Coder-480B GGUF HF | https://huggingface.co/unsloth/Qwen3-Coder-480B-A35B-Instruct-GGUF | 2026 |
| Hardware Corner M3 Ultra DS | https://www.hardware-corner.net/mac-studio-m3-ultra-deepseek-llamacpp/ | 2025 |
| MorphLLM coding model 2026 | https://www.morphllm.com/best-open-source-coding-model-2026 | 2026 |
| Devstral 2 DigitalOcean | https://www.digitalocean.com/community/tutorials/devstral-2-mistral-coding-open-weight-model | 2026 |
| Llama 4 Compute Market | https://www.compute-market.com/blog/llama-4-local-hardware-guide-2026 | 2026 |
| PromptQuorum long context | https://www.promptquorum.com/local-llms/long-context-local-llms | 2026 |
| DecodetheFuture R2 | https://decodethefuture.org/en/deepseek-r2-explained/ | 2026 |
| RunPod V3.1 technical | https://www.runpod.io/blog/deepseek-v3-1-a-technical-analysis-of-key-changes | 2025 |
| apxml Mac system reqs | https://apxml.com/posts/deepseek-system-requirements-mac-os-guide | 2025 |
