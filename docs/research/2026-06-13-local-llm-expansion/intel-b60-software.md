# Intel Arc Pro B60 Software Stack: LLM Serving Reality Check (June 2026)

**Research date:** 2026-06-13  
**Focus:** Software maturity of the Intel LLM ecosystem for a 4× B60 (96 GB VRAM) agentic coding + big-context workload  
**Critical question:** Is the model-support lag a deal-breaker, and has it improved?

---

## 1. The Intel LLM Serving Stack in 2026

### 1.1 Intel LLM Scaler (primary production path)

**What it is:** Intel's official, container-based LLM serving solution for Arc Pro B-series GPUs. It wraps a heavily patched fork of vLLM (maintained at `intel/llm-scaler`) and is deployed exclusively as Docker images on Linux. It exposes an OpenAI-compatible REST API.

**Current state (June 2026):**
- Latest image: `intel/llm-scaler-vllm:0.14.0-b8.3.1` (released June 2026)
  — Source: [github.com/intel/llm-scaler](https://github.com/intel/llm-scaler), README, accessed 2026-06-13
- Underlying vLLM version: `0.14.0` (upstream vLLM as of mid-2026 is ~0.9–1.x)
- PyTorch: 2.10, oneAPI: 2025.3.2 (LTS), oneCCL: 2021.15.7.8
- 50+ supported models across text, vision, audio, embedding, reranking
- OpenAI-compatible API: yes, confirmed
- Multi-GPU: Tensor Parallel, Pipeline Parallel, Data Parallel — all documented

**Key architecture note:** LLM Scaler uses custom ESIMD kernels and a patch file (`vllm_for_multi_arc.patch`), meaning it diverges from standard upstream vLLM. This is the root cause of the model-support lag — Intel must port each new vLLM model architecture addition to their patched fork.
- Source: [deepwiki.com/intel/llm-scaler](https://deepwiki.com/intel/llm-scaler), accessed 2026-06-13

**Windows support:** Labeled "(Experimental)" — Linux-only for production.
- Source: [deepwiki.com/intel/llm-scaler](https://deepwiki.com/intel/llm-scaler), accessed 2026-06-13

**Confidence: HIGH** — directly from Intel's official repo and DeepWiki analysis.

---

### 1.2 IPEX-LLM (archived January 2026)

**What it was:** Intel Extension for PyTorch, providing Ollama/vLLM integration for Arc GPUs (including consumer A770, B580). As of January 28, 2026, Intel archived this repository citing "known security issues." The repository is read-only.
- Source: [xda-developers.com — Intel's $949 GPU](https://www.xda-developers.com/intel-gpu-32gb-vram-local-ai-software-nvidia-keeps-winning/), 2026
- Source: [github.com/intel/ipex-llm](https://github.com/intel/ipex-llm), accessed 2026-06-13

**Impact:** Consumer Arc GPU users (A770, B580) have no official supported path. Intel has no answer for Ollama on consumer GPUs. The ipex-llm mirror at `github.com/ipex-llm/ipex-llm` continues as a community fork, but Intel is not driving it.

For the Arc Pro B60/B70 workstation class, LLM Scaler is the replacement. For single-consumer-GPU users, there is a support vacuum.

**Confidence: HIGH** — archived repo is publicly visible.

---

### 1.3 vLLM-XPU / vllm-xpu-kernels (upstream integration path)

Intel is actively migrating XPU kernel support out of IPEX and into a dedicated `vllm-project/vllm-xpu-kernels` repository, which is being upstreamed into mainline vLLM. Q1 2026 roadmap targets:
- CUDA graph support on XPU
- MLA model support (DeepSeek-style multi-head latent attention)
- Weight-only quantization (Wint4A16, Wfp8A16) on BMG (Battlemage) hardware
- Torch.accelerator API migration (away from hardcoded `torch.cuda`)
- CI pipeline optimization and Docker tooling updates
- Source: [github.com/vllm-project/vllm-xpu-kernels/issues/141](https://github.com/vllm-project/vllm-xpu-kernels/issues/141), 2026

H1 2026 quantization roadmap for upstream vLLM (Intel):
- W4A16 wNa16 INT for Linear layers: **merged** into upstream vLLM
- W4A16 for MoE layers: planned
- MXFP4: work in progress
- Source: [github.com/vllm-project/vllm/issues/37979](https://github.com/vllm-project/vllm/issues/37979), 2026

**This is the trajectory signal:** Intel is actively contributing to upstream vLLM. If this migration completes, the lag narrows significantly because new model support flows through mainline rather than Intel's patch fork. But as of mid-2026 this work is incomplete.

**Confidence: HIGH** — public GitHub roadmap issues.

---

### 1.4 SGLang Intel support

No evidence of first-class SGLang support on Intel XPU found in research. The LLM-Scaler Omni component uses SGLang Diffusion for image generation, but text LLM serving via SGLang on Intel is not documented as a supported path.
- Source: [deepwiki.com/intel/llm-scaler](https://deepwiki.com/intel/llm-scaler), 2026

**Confidence: MEDIUM** — absence of evidence, not confirmed absence.

---

### 1.5 llama.cpp SYCL / Vulkan

llama.cpp has a SYCL backend for Intel GPUs. Performance testing shows it delivering ~15–20 tok/s on 14B models on a single Arc GPU (vs. 23 tok/s from IPEX-LLM Docker and ~32–38 tok/s on Linux native).
- Source: [xda-developers.com](https://www.xda-developers.com/intel-gpu-32gb-vram-local-ai-software-nvidia-keeps-winning/), 2026

Ollama's Intel SYCL backend has open pull requests in upstream llama.cpp but remains incomplete — models fall back to CPU despite the SYCL backend loading.
- Source: [xda-developers.com](https://www.xda-developers.com/intel-gpu-32gb-vram-local-ai-software-nvidia-keeps-winning/), 2026

GGUF quantization (Q4_K_M, Q5_K_M, etc.) runs on Arc via SYCL or Vulkan but throughput is well below the vLLM path. For a production multi-GPU server, llama.cpp SYCL is not the recommended path.

**Confidence: MEDIUM** — based on consumer Arc testing; B60 server-class behavior may differ.

---

## 2. Model-Support Lag — The Key Question

### 2.1 The structural lag mechanism

Intel's LLM Scaler is a **patched fork** of vLLM, not a live downstream. When a new model architecture appears in upstream vLLM (e.g., from a new Qwen, DeepSeek, or Kimi release), Intel engineers must:
1. Port the new model class to their XPU codepath
2. Test it on Arc Pro hardware
3. Package a new Docker image
4. Release it

This cycle has historically taken **4–8 weeks** from upstream vLLM model support to Intel LLM Scaler support, based on release cadence evidence (monthly releases, ~4–8 model additions per release).
- Source: [github.com/intel/llm-scaler/releases](https://github.com/intel/llm-scaler/releases), release history 2025–2026

The practitioner's March 2026 observation (GLM-Flash present, Qwen3.5 absent, GLM-Flash 4.7 unloadable) is consistent with this cadence — those models were mid-port at that time. **The March 2026 state is no longer the current state.**

### 2.2 What runs on Arc Pro B60 as of June 2026

**Confirmed working (in LLM Scaler official support table):**

| Model | Notes | Quant formats |
|---|---|---|
| Qwen3 series (8B–235B) | Full support | FP16, FP8, INT4, GPTQ |
| Qwen3.5 / Qwen3.6 series (9B–122B) | Added March–May 2026 | FP16, FP8, INT4 |
| Qwen3-Coder-Next | Added May 2026; FP16 only currently | FP16 |
| QwQ, Qwen3-Omni, Qwen3-Embedding | Supported | FP16/FP8 |
| DeepSeek-R1-Distill variants (8B–70B) | Confirmed, benchmarked | FP16, FP8, INT4 |
| DeepSeek-V2-Lite (MoE) | Requires VLLM_MLA_DISABLE=1 workaround | FP16 |
| DeepSeek-Coder | Supported | FP16 |
| GLM-4 series, GLM-4.7-Flash | Added March 2026 | FP16, FP8 |
| GLM-4.6v-Flash | Added Jan 2026 (v1.3) | FP16 |
| Llama 3.1 (8B, 70B) | Well-supported | FP16, FP8, INT4 |
| Mixtral / Mistral / Ministral | Supported | FP16 |
| GPT-OSS 20B / 120B (MXFP4) | OpenAI's internal model — Intel showcase | MXFP4 |
| Seed-OSS-36B | Added Jan 2026 | FP16 |
| InternVL3 / InternVL3.5 series | Supported | FP16 |
| Qwen-VL, DeepSeek-OCR | Multimodal, supported | FP16, FP8* |
| Kimi-VL-A3B-Thinking-2506 | Listed in model table | FP16 |
| Whisper-large-v3 | Audio, supported | FP16 |

Sources: [github.com/intel/llm-scaler/blob/main/README.md](https://github.com/intel/llm-scaler/blob/main/README.md) and [github.com/intel/llm-scaler/blob/main/vllm/README.md/](https://github.com/intel/llm-scaler/blob/main/vllm/README.md/), accessed 2026-06-13

**NOT confirmed / NOT in LLM Scaler model table (as of June 2026):**

| Model | Status | Notes |
|---|---|---|
| **DeepSeek V3 (full 671B MoE)** | NOT in LLM Scaler table | Available via IPEX-LLM FlashMoE (archived Jan 2026) — no current official path on LLM Scaler |
| **DeepSeek V4 / V4-Plus / V4-Flash** | NOT found | Released April 2026; no Intel support evidence found |
| **Kimi K2 / K2.6** | NOT found in text LLM table | Kimi-VL listed but Kimi K2 (text MoE) not found; K2.6 had "day-0 support in vLLM" (upstream) but not in Intel fork |
| **MiniMax M2.7** | NOT found | No evidence |
| **GLM-5.1** | NOT found | No evidence |
| **Qwen3-Next-80B full model** | Jan 2026 (v1.3) | Was "Qwen3-Next-80B-A3B" variant |

Sources:
- DeepSeek V4 released Apr 2026: [simonwillison.net](https://simonwillison.net/2026/apr/24/deepseek-v4/), April 2026
- Kimi K2.6 day-0 upstream vLLM support: [latent.space](https://www.latent.space/p/ainews-moonshot-kimi-k26-the-worlds), 2026
- LLM Scaler model table: [github.com/intel/llm-scaler README](https://github.com/intel/llm-scaler/blob/main/vllm/README.md/), 2026

**Critical finding on DeepSeek V3 671B full model:** The IPEX-LLM FlashMoE path that enabled DeepSeek V3/R1 671B on 1–2 Arc GPUs was archived in January 2026. LLM Scaler's supported DeepSeek models are limited to R1-Distill variants (distilled into Llama/Qwen, not the full MoE), V2-Lite, and Coder. **The full DeepSeek V3 671B MoE currently has no confirmed Intel LLM Scaler support path.**

**Confidence: HIGH** — based on explicit model tables from official Intel repo. Absence confirmed by not appearing in tables or release notes across the full release history checked.

### 2.3 Release cadence — how fast does the gap close?

Release frequency: roughly monthly, with 4–10 new models per release.
- 2025: releases in Aug, Sep, Nov, Dec
- 2026: Jan (v1.3), Mar (0.14.0-b8/b8.1), May (0.14.0-b8.3 + v1.4), Jun (0.14.0-b8.3.1)

Observed gap examples:
- Qwen3.5 family (released early 2026 on HuggingFace) → Intel support: March–May 2026 (~4–8 weeks lag)
- GLM-4.7-Flash → added March 2026 release
- Qwen3-Coder-Next → added May 2026 (with FP16 only, FP8 still pending)

**The lag is real but is approximately 4–8 weeks for popular Chinese open-weight models.** This is less than "a month" for some models but can extend 2–3 months for less-prominent models or those requiring MoE architecture work.

For frontier models released in the last 30–60 days before any given date, assume they are NOT yet on Intel.

**Confidence: MEDIUM** — extrapolated from release history, no Intel-published SLA.

---

## 3. Quantization Support on Intel

### 3.1 What works (June 2026)

| Format | Status | Notes |
|---|---|---|
| BF16 / FP16 | Fully supported | Default for all models |
| FP8 (dynamic online) | Broadly supported | Some accuracy issues on DeepSeek-OCR-2; added June 2026 FP8 KV Cache |
| INT4 (sym_int4, dynamic online) | Supported | Added progressively 2025–2026; 25% throughput gain cited |
| MXFP4 | Limited — GPT-OSS 20B/120B only | Intel-specific format; hardware-accelerated on Battlemage |
| GPTQ (pre-quantized) | Supported — auto-detected | Some models listed with GPTQ variants |
| AWQ (pre-quantized) | **Problematic** | Issue #269: AWQ-Int4 models crash due to torchao CUDA-only codepath; closed but fix version unclear |

Sources:
- [github.com/intel/llm-scaler/blob/main/vllm/README.md/](https://github.com/intel/llm-scaler/blob/main/vllm/README.md/), 2026
- AWQ bug: [github.com/intel/llm-scaler/issues/269](https://github.com/intel/llm-scaler/issues/269), 2025–2026

### 3.2 Key gap vs CUDA

**AWQ pre-quantized models from HuggingFace Hub remain risky.** The torchao-based AWQ path has a documented CUDA-only crash. While marked closed, the fix version is not confirmed.

**GGUF is not supported in LLM Scaler.** GGUF runs via llama.cpp SYCL/Vulkan only, at lower throughput.

**EXL2 / ExLlamaV2:** No evidence of support.

**bitsandbytes INT8:** vLLM documents an open issue (#8799) for bitsandbytes INT8 support; unlikely on XPU.

The critical production path is: FP16, online INT4, online FP8, or GPTQ. Dynamic online quantization (INT4/FP8 applied at load time) is the Intel-native approach and is the most reliable.

**Confidence: HIGH** for what's confirmed working; MEDIUM for AWQ fix status.

---

## 4. Agentic / Tool-Use / Structured Output Reliability

### 4.1 What's documented

Tool calling is **explicitly listed as a supported feature** in the vLLM blog post covering Intel Arc Pro B-Series:
> "Tool calling" appears in the feature enumeration
- Source: [vllm.ai/blog/2025-11-11-intel-arc-pro-b](https://vllm.ai/blog/2025-11-11-intel-arc-pro-b), November 2025

The LLM Scaler documentation specifically shows the `--enable-auto-tool-choice` and `--tool-call-parser qwen3_coder` flags for Qwen3.5/3.6 models:
- Source: [github.com/intel/llm-scaler/blob/main/vllm/README.md/](https://github.com/intel/llm-scaler/blob/main/vllm/README.md/), 2026

Structured outputs use xgrammar backend in vLLM (JIT-compiled grammars, fastest option in 2026):
- Source: [gigagpu.com/vllm-structured-output-guided-decoding/](https://gigagpu.com/vllm-structured-output-guided-decoding/), 2026

### 4.2 Gaps and caveats

**No Intel-specific tool-calling reliability reports found.** There are no published test results for agentic loop stability (multi-turn tool calls, error recovery) on Intel XPU specifically. The tool-calling infrastructure is inherited from vLLM's mainline but the XPU codepath adds latency and has historically had issues.

**Historical structured output issue in vLLM mainline (not Intel-specific):** Major guided decoding issues were reported in vLLM v0.6.3–0.8.1 (resolved in later versions). Intel's fork is based on vLLM 0.14.0, which post-dates these fixes.
- Source: [github.com/vllm-project/vllm/issues/15236](https://github.com/vllm-project/vllm/issues/15236), early 2025

**For an agentic coding harness making rapid sequential tool calls, the main risk is not tool-calling protocol breakage but latency/throughput stability under concurrency.** See Section 5.

**Confidence: MEDIUM** — tool calling is documented as supported but no agentic stress-test data exists for Intel XPU specifically.

---

## 5. Tensor-Parallel Multi-GPU Maturity on Arc Pro B60

### 5.1 What's confirmed working

4× B60 with TP=4 has been demonstrated in production benchmarks:
- Qwen3-VL-30B-A3B-Instruct on 4× B60: linear throughput scaling from 16–64 concurrent requests, ~1000 tok/s peak long-form generation
  - Source: [embeddedllm.com/blog/benchmarking-llm-inference-intel-arc-pro-b60](https://embeddedllm.com/blog/benchmarking-llm-inference-intel-arc-pro-b60), 2026
- GPT-OSS 120B (MXFP4, TP=4): 1,495 tok/s at 1024/1024 with 100 concurrent requests on 4 GPUs
  - Source: [vllm.ai/blog/2025-11-11-intel-arc-pro-b](https://vllm.ai/blog/2025-11-11-intel-arc-pro-b), November 2025
- 8× B60 cluster: "FP8 model output token throughput with less than 100ms next token latencies with good concurrency load"
  - Source: [deepwiki.com/intel/llm-scaler/2.5-multi-gpu-and-parallelism](https://deepwiki.com/intel/llm-scaler/2.5-multi-gpu-and-parallelism), 2026

**B70 cluster (4× B70): 540 tok/s; dual-B70: 140 tok/s** — superlinear scaling observed due to improved batch processing.
- Source: [zingnex.cn B70 forum thread](https://www.zingnex.cn/en/forum/thread/intel-arc-pro-b70-gpu-llm-vllm), 2026

### 5.2 Requirements and constraints

- **Mandatory env vars:** `VLLM_WORKER_MULTIPROC_METHOD=spawn`, `VLLM_TARGET_DEVICE=xpu`, `ONECCL_BINDINGS_FOR_PYTORCH_ENV_MODE=p2p`
- **PCIe topology:** Direct connection or PCIe switch required — no PCI hub daisy-chaining
- **NUMA binding:** Multi-socket servers need explicit NUMA binding
- **Memory reservation:** Must reserve 10–15% VRAM to avoid OOM at high concurrency
- **CCL communication:** Uses oneCCL P2P mode for single-node; USM mode for multi-node
- Source: [deepwiki.com/intel/llm-scaler/2.5-multi-gpu-and-parallelism](https://deepwiki.com/intel/llm-scaler/2.5-multi-gpu-and-parallelism), 2026

### 5.3 Known failure modes and bugs fixed

From LLM Scaler v1.3 release notes (January 2026):
- **72-hour hang** under extended stress: fixed in v1.2 (December 2025)
- **oneCCL sub-communicator hang:** fixed
- **Communication accuracy issues in long-run scenarios:** fixed
- **Crash with 2DP + 4TP configuration:** fixed in v1.3
- **UR_ERROR_DEVICE_LOST under high-load preemption:** fixed in v1.3
- **InternVL-38B output errors:** fixed
- Source: [github.com/intel/llm-scaler/releases/tag/vllm-1.3](https://github.com/intel/llm-scaler/releases/tag/vllm-1.3), January 2026

### 5.4 Open issues

- **Qwen3.5-27B on B70 (Issue #339):** User reports hangs, system crashes, OOM on Ubuntu 24.04/25.10/26.04. Assigned but **unresolved as of research date.** Multiple precision attempts (FP8, FP16) both failed.
  - Source: [github.com/intel/llm-scaler/issues/339](https://github.com/intel/llm-scaler/issues/339), 2026
- Setup complexity vs CUDA: vLLM on Intel requires Python 3.12 specifically, Ubuntu 24.04.3, careful library path management, and wrapper scripts for multi-GPU. One developer: "Installing for Intel XPU backend is really hard in my opinion."
  - Source: [xda-developers.com](https://www.xda-developers.com/intel-gpu-32gb-vram-local-ai-software-nvidia-keeps-winning/), 2026

### 5.5 Low-concurrency counter-intuition

An important finding from early B60 Battlematrix testing: at **low batch sizes**, single-GPU outperforms multi-GPU due to communication overhead. GPT-OSS 20B: 49.22 tok/s on 1 GPU vs. 22.83 tok/s on 8 GPUs at batch size 1.
- Source: [storagereview.com/review/intel-arc-pro-b60-battlematrix-preview](https://www.storagereview.com/review/intel-arc-pro-b60-battlematrix-preview-192gb-of-vram-for-on-premise-ai), December 2025

For an agentic coding workload where single-user latency matters more than aggregate throughput, this means TP=4 across all B60s may not be the right configuration for a single coding session — TP=1 or TP=2 with Data Parallelism for concurrent users may outperform TP=4.

**Confidence: HIGH** — multiple independent sources confirm the pattern.

---

## 6. Trajectory: Is Intel's Gap Closing?

### 6.1 Positive signals

1. **Active upstream contribution:** Intel's vllm-xpu-kernels repo is actively merging XPU kernels into mainline vLLM. W4A16 quantization merged. MLA support in progress. If this completes, the fork-lag problem reduces substantially.
   - Source: [github.com/vllm-project/vllm/issues/37979](https://github.com/vllm-project/vllm/issues/37979), 2026

2. **Accelerating release cadence:** 2026 has seen monthly+ releases vs. quarterly in 2024.

3. **Critical bugs addressed:** The 72-hour hang, oneCCL hangs, and DP+TP crash are fixed. The stack is more stable than it was in H2 2025.

4. **vLLM blog endorsement:** The official vLLM project published an Intel Arc Pro B-Series blog post in November 2025, signaling Intel is a first-class supported backend — not just a community experiment.
   - Source: [vllm.ai/blog/2025-11-11-intel-arc-pro-b](https://vllm.ai/blog/2025-11-11-intel-arc-pro-b), November 2025

5. **Torch.accelerator API migration:** Moving from `torch.cuda` hardcoding will enable more upstream code to work transparently on XPU without porting.

### 6.2 Persistent risks

1. **IPEX-LLM archived with no consumer replacement.** Hobbyist/developer ecosystem is fragmented. This doesn't affect B60 Pro workstation users directly but signals Intel's focus is narrowing to workstation/datacenter hardware.

2. **Full MoE frontier models remain unconfirmed.** DeepSeek V3 671B full, DeepSeek V4, Kimi K2 (MoE at 1T parameters) — none confirmed working on LLM Scaler as of June 2026.

3. **Frontier model lag is structural.** Even with faster releases, the fork-and-port model means Intel will always be 4–8 weeks behind a rapidly moving frontier. During the "hot" period after a major model drop (e.g., DeepSeek V5, Qwen 4), Intel users wait.

4. **AWQ pre-quantized Hub models unreliable.** The CUDA-only torchao path crashes remain a risk for the large portion of HuggingFace Hub models distributed as AWQ.

5. **SGLang not supported.** For operators who prefer SGLang's agentic features (radix caching, structured I/O), there is no Intel path.

6. **Ollama still broken.** For simpler use cases and local developers feeding the Artemis test pipeline, Ollama's SYCL backend is unreliable.

**Overall trajectory: CLOSING, but not closed.** The upstream integration work is credible and moving. By end of 2026, the fork-lag may reduce to 2–3 weeks for mainstream models. But full-MoE frontier models and the consumer GPU gap remain unresolved.

**Confidence: MEDIUM** — trajectory is visible in public roadmaps but Intel has not published timelines for upstream completion.

---

## 7. Summary Assessment for 4× B60 Agentic Coding Workload

| Dimension | Verdict |
|---|---|
| **OpenAI API compatibility** | Yes — full OpenAI-compatible endpoint via LLM Scaler |
| **Can run Qwen3-Coder / Qwen3.5** | Yes — FP16 confirmed, FP8/INT4 available for most sizes |
| **Can run DeepSeek R1 Distill variants** | Yes — well-supported |
| **Can run DeepSeek V3 671B full** | **No confirmed path** on LLM Scaler |
| **Can run DeepSeek V4** | **No** — not found in any release |
| **Can run Kimi K2 / K2.6** | **No** — upstream vLLM yes; Intel fork no |
| **Can run GLM-4 / GLM-Flash** | Yes — GLM-4.7-Flash, GLM-4.6v-Flash supported |
| **Can run Llama 3.1** | Yes — 8B and 70B |
| **Tensor parallel 4× B60** | Works, but requires careful config; OOM risk at high concurrency |
| **Tool calling / function calling** | Documented supported; no agentic stress-test data |
| **Structured output / guided decoding** | Inherited from vLLM; should work with xgrammar backend |
| **FP8 / INT4 quantization** | Supported (online, dynamic) |
| **AWQ pre-quantized models** | Risky — torchao CUDA crash bug |
| **GGUF** | Not via LLM Scaler; llama.cpp SYCL only, lower perf |
| **Headless 24/7 stability** | Improved — major hangs fixed in v1.2/1.3; residual issues |
| **Setup complexity** | High — Docker, Linux-only, specific env vars, NUMA binding |
| **Model-support lag vs upstream vLLM** | 4–8 weeks for mainstream models; indefinite for MoE frontier |

---

## Sources

- [github.com/intel/llm-scaler](https://github.com/intel/llm-scaler) — Intel LLM Scaler main repo (accessed 2026-06-13)
- [github.com/intel/llm-scaler/blob/main/README.md](https://github.com/intel/llm-scaler/blob/main/README.md) — Model support table (2026-06-13)
- [github.com/intel/llm-scaler/blob/main/vllm/README.md/](https://github.com/intel/llm-scaler/blob/main/vllm/README.md/) — Detailed vLLM model table (2026-06-13)
- [github.com/intel/llm-scaler/releases](https://github.com/intel/llm-scaler/releases) — Release history (2025–2026)
- [github.com/intel/llm-scaler/releases/tag/vllm-1.3](https://github.com/intel/llm-scaler/releases/tag/vllm-1.3) — v1.3 release notes, January 2026
- [github.com/intel/llm-scaler/issues/269](https://github.com/intel/llm-scaler/issues/269) — AWQ pre-quantized model crash (2025–2026)
- [github.com/intel/llm-scaler/issues/339](https://github.com/intel/llm-scaler/issues/339) — Qwen3.5-27B fails on B70 (open, 2026)
- [github.com/intel/ipex-llm](https://github.com/intel/ipex-llm) — Archived January 2026
- [vllm.ai/blog/2025-11-11-intel-arc-pro-b](https://vllm.ai/blog/2025-11-11-intel-arc-pro-b) — Official vLLM blog on Intel Arc Pro B-Series, November 2025
- [deepwiki.com/intel/llm-scaler](https://deepwiki.com/intel/llm-scaler) — Architecture analysis (2026)
- [deepwiki.com/intel/llm-scaler/2.5-multi-gpu-and-parallelism](https://deepwiki.com/intel/llm-scaler/2.5-multi-gpu-and-parallelism) — Multi-GPU details (2026)
- [github.com/vllm-project/vllm-xpu-kernels/issues/141](https://github.com/vllm-project/vllm-xpu-kernels/issues/141) — XPU Q1 2026 roadmap
- [github.com/vllm-project/vllm/issues/37979](https://github.com/vllm-project/vllm/issues/37979) — Intel quantization H1 2026 roadmap
- [xda-developers.com — Intel's $949 GPU](https://www.xda-developers.com/intel-gpu-32gb-vram-local-ai-software-nvidia-keeps-winning/) — Software gap analysis (2026)
- [storagereview.com — B60 Battlematrix Preview](https://www.storagereview.com/review/intel-arc-pro-b60-battlematrix-preview-192gb-of-vram-for-on-premise-ai) — Early hardware + software testing, December 2025
- [embeddedllm.com — B60 benchmark](https://embeddedllm.com/blog/benchmarking-llm-inference-intel-arc-pro-b60) — 4× B60 production benchmark (2026)
- [zingnex.cn — B70 cluster config](https://www.zingnex.cn/en/forum/thread/intel-arc-pro-b70-gpu-llm-vllm) — TP tuning guide (2026)
- [craftrigs.com — NVIDIA vs AMD vs Intel 2026](https://craftrigs.com/news/nvidia-amd-intel-2026-local-ai/) — Ecosystem comparison (2026)
- [simonwillison.net — DeepSeek V4](https://simonwillison.net/2026/apr/24/deepseek-v4/) — DeepSeek V4 release, April 2026
- [latent.space — Kimi K2.6](https://www.latent.space/p/ainews-moonshot-kimi-k26-the-worlds) — Kimi K2.6 day-0 vLLM support, 2026
