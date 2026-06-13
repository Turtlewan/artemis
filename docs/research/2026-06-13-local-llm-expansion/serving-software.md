# Local LLM Serving Software Research
**Date:** 2026-06-13  
**Scope:** Serving stacks, gateway/routing, Claude Code proxy, batch/queue patterns, Tailscale, wake/sleep orchestration  
**Context:** Artemis (Python brain, Mac Mini) dispatching heavy jobs to a dedicated inference box — either Apple Silicon or Linux/x86. Two job roles: DeepSeek-class agentic coding executor, Kimi-class big-context reader.

---

## 1. Serving Stacks per Platform

**Confidence: High** — Multiple 2026 sources, active GitHub repos, cross-corroborating reviews.

### 1.1 llama.cpp / llama-server

| Dimension | Assessment |
|---|---|
| OpenAI API compat | Native (`--server` binary at `localhost:8080`). Drop-in for any OpenAI SDK. |
| Multi-model / hot-swap | Manual: one model per process. No native model registry. Hot-swap = kill+relaunch or use Ollama/LM Studio on top. |
| Request queueing | Built-in: `--cont-batching` enables concurrent request interleaving. Without it, requests serialize. Default queue depth is configurable. |
| Long-context quality | Supports 128K–1M+ via RoPE scaling/YaRN. MoE CPU offload via `--n-gpu-layers` partial offload. Coherence drops in middle of very long contexts (standard LLM behavior). As of May 2026, first million-token open models (Llama 4 Scout, Qwen 3.6 with YaRN) tested. |
| 24/7 headless maturity | Very high. Statically compiled C++ binary, minimal dependencies. Standard headless daemon pattern well-documented. |
| Platform | Linux/x86 (CUDA, ROCm, Vulkan), Apple Silicon (Metal), CPU-only — widest portability. |
| Notes | The "raw" option: 15–25% faster than Ollama wrapper on same hardware. Exposes low-level knobs (KV cache quant, Flash Attention, TurboQuant) Ollama hides. Best for power users who want maximum control. |

**Sources:**  
- [llama.cpp 2026 Guide](https://weavai.app/blog/en/2026/04/24/llama-cpp-2026-guide-local-ai-inference-setup/) (Apr 2026)  
- [Ollama vs llama.cpp vs vLLM vs SGLang comparison](https://sesamedisk.com/local-inference-engines-2026-comparison/) (2026)  
- [LLM Inference Servers Compared — TensorFoundry](https://tensorfoundry.io/blog/llm-inference-servers-compared)

---

### 1.2 vLLM

| Dimension | Assessment |
|---|---|
| OpenAI API compat | Native `/v1/*` OpenAI-compatible server. Considered the production standard. |
| Multi-model / hot-swap | Supports multi-LoRA serving; base model stays loaded, adapters swap. Full model hot-swap requires separate processes or orchestration layer. |
| Request queueing | Best-in-class: PagedAttention, continuous batching, disaggregated prefill/decode (V1 engine default since v0.6.0/2025). Priority queuing available. Offline batch mode (`LLMEngine`) for non-latency-sensitive jobs. |
| Long-context quality | Strong: prefix caching, chunked prefill, disaggregated prefill prevents long fills blocking decode. Checkpoint-and-resume for batch jobs (checkpoint every 1K–5K docs). |
| 24/7 headless maturity | Production-grade on NVIDIA. ROCm support improving. |
| Platform | Primary: Linux/NVIDIA. Apple Silicon: `vllm-metal` plugin (released Jan 2026, v0.2.0 Apr 2026) — community-maintained, MLX backend, 83x TTFT improvement in v0.2.0 vs v0.1.0. Not yet production-recommended for Apple Silicon (contracollective.com assessment: "development local, production Linux"). |
| Notes | Overkill for single-user home lab in terms of complexity. But best batch/queue story. ~800 tok/s ceiling on server hardware vs Ollama's ~40. |

**Sources:**  
- [vLLM Production Deployment 2026](https://www.sitepoint.com/vllm-production-deployment-guide-2026/) (2026)  
- [vLLM Apple Silicon / vllm-metal](https://github.com/vllm-project/vllm-metal)  
- [vllm-mlx — community Apple Silicon server](https://github.com/waybarrios/vllm-mlx) (last release May 9, 2026)  
- [Batch LLM Inference 2026 Guide](https://www.spheron.network/blog/batch-llm-inference-gpu-cloud/) (2026)

---

### 1.3 SGLang

| Dimension | Assessment |
|---|---|
| OpenAI API compat | Full `/v1/*` OpenAI-compatible, plus structured output, constraint grammars. |
| Multi-model / hot-swap | Single-model focus per instance; intended for high-throughput single-model serving. |
| Request queueing | RadixAttention (prefix reuse), continuous batching, expert parallelism load balancer (EPLB) for MoE. Disaggregated prefill-decode available. |
| Long-context quality | Strong MoE story: official DeepSeek-V4 (Flash 284B / Pro 1.6T) support, verified launch commands. 52.3K input tok/s per node at scale. Million-token models (MiniMax-01, Kimi architecture) tested. |
| 24/7 headless maturity | Production-grade on NVIDIA at scale. For single-GPU home lab: functional but grammar crash fault tolerance and server crash fault tolerance are on Q1 2026 roadmap — implies not yet fully hardened for unattended ops. |
| Platform | Linux/NVIDIA primary. No native Apple Silicon support. |
| Notes | Best choice for the Linux/x86 inference box for MoE serving at medium scale. KTransformers integration in SGLang (announced Oct 2025) enables CPU/GPU hybrid for massive MoE on consumer hardware. |

**Sources:**  
- [SGLang DeepSeek-V4 Docs](https://docs.sglang.io/cookbook/autoregressive/DeepSeek/DeepSeek-V4)  
- [KTransformers + SGLang integration — LMSYS Blog](https://www.lmsys.org/blog/2025-10-22-KTransformers/) (Oct 2025)  
- [SGLang 2026 Q1 Roadmap](https://github.com/sgl-project/sglang/issues/12780)

---

### 1.4 KTransformers (hybrid CPU/GPU for MoE)

| Dimension | Assessment |
|---|---|
| OpenAI API compat | Not a primary feature — research framework first. OpenAI-compatible endpoint available but not the focus. Integrates with SGLang for production serving. |
| Multi-model / hot-swap | Not designed for this. |
| Request queueing | Inherited from SGLang when used together. |
| Long-context quality | Specializes in massive MoE (DeepSeek-V3/R1/V4 671B–1.6T). CPU/GPU hybrid: experts offloaded to DRAM, hot experts promoted to VRAM. AMX kernel acceleration. 4.62–19.74x prefill speedup over existing hybrid systems. ~20 TPS on DeepSeek-V3 full 671B with consumer GPU (~$10K server). |
| 24/7 headless maturity | Research/experimental. Presented at SOSP'25. Not yet packaged for easy home deployment. |
| Platform | Linux (x86 with AVX-512/AMX). Requires modern Intel Xeon or AMD EPYC for full benefit. |
| Notes | Most relevant if you want to run full 671B+ MoE locally on a Linux box that has large DRAM (512GB+) but limited VRAM. Not the right tool for the Mac Mini side. |

**Sources:**  
- [KTransformers SOSP'25 paper](https://madsys.cs.tsinghua.edu.cn/publication/ktransformers-unleashing-the-full-potential-of-cpu/gpu-hybrid-inference-for-moe-models/)  
- [ktransformers GitHub](https://github.com/kvcache-ai/ktransformers)  
- [KTransformers DeepSeek-V4-Flash support](https://github.com/kvcache-ai/ktransformers/blob/main/doc/en/DeepSeek-V4-Flash.md)

---

### 1.5 MLX-LM / mlx-openai-server (Apple Silicon)

| Dimension | Assessment |
|---|---|
| OpenAI API compat | Official `mlx_lm.server` exposes `/v1/chat/completions` OpenAI-compatible endpoint. |
| Multi-model / hot-swap | Single model per process. No native model registry; requires process management layer. |
| Request queueing | Basic: serial by default. No advanced batching as of 2026. |
| Long-context quality | Good for standard models (128K–262K). Some Qwen variants and MoE setups "slower or unsupported." MLX uses Apple Neural Accelerators — 30–60% better than llama.cpp on M4/M5 for prompt processing. |
| 24/7 headless maturity | Moderate. Widely used but lacks enterprise hardening. Fine for single-user personal server. |
| Platform | Apple Silicon only (M1–M5). Native Metal, zero-copy unified memory. |
| Notes | Correct tool for the Mac Mini side. 4-bit models: ~38 tok/s on M4 Max for 8B class. |

**Variants worth knowing:**

- **vllm-mlx** (`waybarrios/vllm-mlx`): Community server, vLLM-style API, continuous batching, paged KV, prefix caching, SSD-tier cache, exposes both OpenAI and Anthropic `/v1/messages` from one process. Explicitly claims "Works with Claude Code." 1.3K stars, v0.3.0 released May 9, 2026. Recommended for Artemis Mac Mini side if you need Anthropic-API passthrough without a proxy.
- **vllm-metal** (official `vllm-project/vllm-metal`): Newer (Jan 2026), v0.2.0 Apr 2026, Docker Model Runner integration. More aligned with upstream vLLM but community-maintained, experimental paged attention.

**Sources:**  
- [MLX: The Next Inference Engine for Apple Silicon](https://yage.ai/share/mlx-apple-silicon-en-20260331.html) (Mar 2026)  
- [vllm-mlx GitHub](https://github.com/waybarrios/vllm-mlx)  
- [vllm-metal GitHub](https://github.com/vllm-project/vllm-metal)  
- [Apple Silicon MLX Inference 2026](https://branch8.com/posts/apple-silicon-mlx-llm-inference-optimization-tutorial)

---

### 1.6 LM Studio (headless / llmster)

| Dimension | Assessment |
|---|---|
| OpenAI API compat | Full `/v1/*` OpenAI-compatible. |
| Multi-model / hot-swap | Yes: GUI model switcher, multi-model warm loading in v0.4.2+. Continuous batching added for MLX in v0.4.2. |
| Request queueing | Basic queuing. Not production-grade for high concurrency. |
| Long-context quality | Supports GGUF and MLX backends; context limit model-dependent. |
| 24/7 headless maturity | Good: `llmster` daemon (v0.4+) decouples GUI from inference. Can run as background service via `--server` flag or launchd/systemd. The recommended Windows/Mac path for users who want a polished experience without manual process management. |
| Platform | macOS, Windows, Linux (llmster). |
| Notes | Best fit for the Mac Mini if you want a polished multi-model UX with headless support. Less control than mlx-openai-server directly. LM Link (Tailscale partnership) gives native device-to-device discovery. |

**Sources:**  
- [LM Studio Headless Mode Docs](https://lmstudio.ai/docs/developer/core/headless)  
- [Server Management and Headless Mode](https://deepwiki.com/lmstudio-ai/docs/2.6-server-management-and-headless-mode)  
- [LM Studio MLX Apple Silicon 2026](https://markaicode.com/lm-studio-mlx-apple-silicon-models/)

---

### 1.7 Ollama

| Dimension | Assessment |
|---|---|
| OpenAI API compat | Full `/v1/*` OpenAI-compatible. |
| Multi-model / hot-swap | Yes: `OLLAMA_MAX_LOADED_MODELS` (default 3×GPU count) keeps multiple models warm. `OLLAMA_KEEP_ALIVE` controls eviction. Model switching transparent to callers. |
| Request queueing | `OLLAMA_MAX_QUEUE` (default 512). Parallel via `OLLAMA_NUM_PARALLEL` (default 1; must be manually set). Returns HTTP 503 when queue full. |
| Long-context quality | Not specifically addressed in 2026 reviews. GGUF-only (no GPTQ/AWQ). Context limit model-dependent. |
| 24/7 headless maturity | High: `ollama serve` runs headlessly, systemd/launchd well-documented. Easiest to operate. |
| Platform | macOS (MLX + llama.cpp), Linux, Windows. |
| Notes | 15–25% slower than direct llama.cpp. Max ~40 tok/s total throughput for multi-user scenarios. Good for dev/experimentation; single-user home server performance is acceptable. GGUF-only is a real constraint (no bitsandbytes/GPTQ quantization support). Not recommended for multi-user or high-concurrency scenarios. |

**Sources:**  
- [Ollama 2026 Review](https://aifoss.dev/blog/ollama-review-2026/) (2026)  
- [Ollama FAQ](https://docs.ollama.com/faq)  
- [Ollama parallel requests](https://www.glukhov.org/llm-performance/ollama/how-ollama-handles-parallel-requests/)

---

## 2. Gateway / Routing Layer

**Confidence: High** — LiteLLM is clearly the 2026 standard; alternatives well-documented.

### 2.1 LiteLLM Proxy

The dominant open-source multi-backend LLM gateway in 2026. Supports 100+ providers in OpenAI format. Key features for Artemis:

- **Model-name routing**: YAML config maps virtual model names (`artemis/deepseek-coder`) to backend endpoints. A request for `artemis/local-small` hits Mac Mini's mlx-openai-server; `artemis/deepseek-big` hits the Linux box.
- **Fallback chains**: If local box is saturated or down, fallback to cloud API (Anthropic, OpenAI, DeepSeek API) — configured per model with failure budgets and cooldowns.
- **Retries + backoff**: Fixed and exponential backoff across providers.
- **Cost tracking, rate limiting, guardrails**: Optional but available.
- **Local backend support**: Native connectors for Ollama, vLLM, llama.cpp, LM Studio, SGLang via their OpenAI-compatible endpoints.

**Deployment pattern for Artemis:**
```yaml
model_list:
  - model_name: local/qwen-coder-27b
    litellm_params:
      model: openai/qwen3-coder-next
      api_base: http://mac-mini.tailnet:8080
      api_key: none
  - model_name: local/deepseek-v4-flash
    litellm_params:
      model: openai/deepseek-v4-flash
      api_base: http://inference-box.tailnet:8000
      api_key: none
      fallback: [anthropic/claude-sonnet-4-5]
```

**Alternatives noted but less mature for home use:**
- **Nginx/Caddy with upstream routing**: Works but no LLM-aware features (retries, model aliases, fallback chains).
- **agentgateway**: Kubernetes-first, overkill for home lab.
- **OpenRouter as cloud-side gateway**: Good for cloud fallback, not for local-to-local routing.

**2026 status**: LiteLLM 100K+ GitHub stars, actively maintained (BerriAI). Standard tool in enterprise AI teams and home lab setups alike.

**Sources:**  
- [LiteLLM GitHub](https://github.com/BerriAI/litellm/)  
- [LiteLLM load balancing docs](https://docs.litellm.ai/docs/proxy/load_balancing)  
- [Hybrid Cloud-Local LLM Architecture 2026](https://www.sitepoint.com/hybrid-cloudlocal-llm-the-complete-architecture-guide-2026/) (2026)  
- [LiteLLM proxy multi-backend guide (askem.eu)](https://askem.eu/en/2026/04/08/litellm-un-proxy-unifie-pour-router-ses-requetes-llm-entre-ollama-vllm-et-le-cloud/) (Apr 2026)

---

## 3. Claude Code Local Backend: Anthropic-API Proxies

**Confidence: High** — Multiple maintained projects confirmed, quality assessments available.

### The Core Problem

Claude Code speaks Anthropic Messages API (`/v1/messages`, Anthropic-specific headers, streaming format). Local models speak OpenAI format. A translation proxy is required unless the inference server natively emits Anthropic-format responses.

### 3.1 Proxy Options (2026)

**Option A: claude-code-router (`musistudio/claude-code-router`)**  
- 34.9K stars, 2.9K forks — the most popular Claude Code router as of 2026.
- Sits as local proxy between Claude Code and any backend.
- Supports: OpenRouter, DeepSeek, Ollama, Gemini, Volcengine, SiliconFlow, ModelScope, DashScope, custom.
- Has `tooluse` transformer that optimizes tool-use/function-calling per model. Has `enhancetool` transformer adding error tolerance to tool call parameters (disables streaming).
- Model routing: route background tasks, thinking, long-context to different models.
- Active: strong community. **Best choice for routing from Claude Code to local OpenAI-format backends.**

**Option B: y-router**  
- Translates OpenAI-compatible services (e.g., OpenRouter) to Anthropic-native format for Claude Code.
- Lighter than claude-code-router, fewer features.

**Option C: LiteLLM with Anthropic passthrough**  
- LiteLLM can expose an Anthropic-format endpoint (`/v1/messages`) that translates to OpenAI backends. Standard enterprise approach.
- Works for teams: `ANTHROPIC_BASE_URL=http://localhost:4000` where LiteLLM runs.

**Option D: vllm-mlx (Mac Mini native, no proxy needed)**  
- Exposes both OpenAI `/v1/*` AND Anthropic `/v1/messages` natively.
- Explicitly states "Works with Claude Code" in README.
- Best option if you're already using vllm-mlx on the Mac Mini — zero proxy layer.

**Option E: free-claude-code / deepclaude / deepseek-claude-proxy**  
- Simpler one-off scripts. Lower maintenance. Backends: Ollama, LM Studio, llama.cpp, OpenRouter, NVIDIA NIM, DeepSeek API.
- Adequate for personal use, less feature-rich.

**Official DeepSeek path**: DeepSeek API has an official `/anthropic` passthrough endpoint — `ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic`. Direct, no local proxy needed for the cloud API path.

### 3.2 Quality of Local Models as Claude Code Backend (4-bit quant)

**Confidence: Medium** — Community reports available; hard benchmarks limited.

**Best performers for agentic/tool-use coding loops at 4-bit:**

| Model | VRAM needed (Q4) | SWE-bench Verified | Agentic loop quality |
|---|---|---|---|
| Qwen3-Coder-Next 27B | ~16–24GB | 77.2% | Best local option; dense arch, consistent multi-step |
| Qwen3-Coder-Next 35B-A3B (MoE) | ~16GB active | 73.4% | Faster per step, but MoE can lose coherence on long tasks |
| DeepSeek-V4-Flash (local) | Large — "homelab not consumer-GPU" | High | Designed for agentic loops, strong on algo/math code; local deployment challenging |
| Qwen 3.6 27B | ~24GB+ for real agent work | Good | Community-confirmed Claude Code compatible, "workable rather than optimal" |

**Key caveats:**
- Tool-use protocol compliance is model-dependent. claude-code-router's `enhancetool` transformer adds tolerance.
- Context window at Q4: practical coding ~16–64K depending on VRAM tier. 4–8K at 8GB, 64K+ comfortable at 24GB+.
- Community reports from r/LocalLLaMA: Qwen 3.6-27B + Claude Code = "workable, not optimal." Gap vs. real Claude is real.
- Anthropic's April 2026 policy change reduced third-party harness coverage, pushing some users to OpenCode/Aider alternatives. Claude Code itself still works with ANTHROPIC_BASE_URL.
- Multi-step agentic coherence: Qwen3-Coder-Next dense 27B outperforms its MoE 35B-A3B variant for sustained long tasks.

**Sources:**  
- [claude-code-router GitHub](https://github.com/musistudio/claude-code-router)  
- [Claude Code Router DEV.to](https://dev.to/stevengonsalvez/claude-code-router-use-any-model-with-claude-codes-interface-c6a)  
- [DeepSeek Claude Code integration docs](https://api-docs.deepseek.com/quick_start/agent_integrations/claude_code)  
- [free-claude-code guide](https://knightli.com/en/2026/05/01/free-claude-code-anthropic-compatible-proxy/) (May 2026)  
- [Best local coding models 2026](https://insiderllm.com/guides/best-local-coding-models-2026/) (2026)  
- [Qwen3-Coder-Next guide](https://dev.to/sienna/qwen3-coder-next-the-complete-2026-guide-to-running-powerful-ai-coding-agents-locally-1k95) (2026)

---

## 4. Background / Batch Job Patterns

**Confidence: Medium** — vLLM batch mode well-documented; simple-queue patterns for llama.cpp are community-informal.

### 4.1 vLLM Offline Batch Mode

vLLM's `LLMEngine` offline mode is the cleanest off-the-shelf solution for overnight/batch jobs:
- Pass list of prompts, get completions back asynchronously.
- Checkpoint-and-resume every 1K–5K documents — losing at most minutes of progress on interruption.
- Prefix caching: when all batch prompts share a system prompt, KV cache computed once. 25–35% compute reduction for batch jobs with fixed preamble.
- Priority queuing available in the HTTP server (latency-sensitive foreground requests can preempt batch).
- Disaggregated prefill/decode (V1 engine, default 2025+): long prefill jobs don't block ongoing decode of other requests.

**Recommended pattern for Artemis overnight coding builds:**
1. Submit batch via vLLM HTTP server to the Linux inference box.
2. Long-running jobs queue behind interactive requests at lower priority.
3. Use LiteLLM proxy with timeout+retry to handle server restarts gracefully.

### 4.2 llama.cpp Simple Queue

llama.cpp server serializes by default. With `--cont-batching`, interleaves decode phases across concurrent requests, but there's no built-in job priority or batch API. **No off-the-shelf queue layer** — community approaches:
- Python wrapper (asyncio queue) that serializes calls to llama-server endpoint.
- llama-cpp-python's `generate`/`create_completion` methods support iteration but not priority.
- HN thread (June 2025): "almost nobody using llama.cpp does batch inference" — confirms no standard solution.

For overnight batch jobs against llama.cpp, a thin Python asyncio queue (50–100 lines) sending requests serially is the practical approach. Not elegant but works for single-user.

### 4.3 SGLang Priority Queue

SGLang supports priority in its scheduler. Combined with RadixAttention prefix reuse, it's efficient for repeated-system-prompt batch jobs. Less documented for home-lab single-instance use; designed for multi-GPU multi-tenant.

**Sources:**  
- [Batch LLM Inference GPU Cloud 2026](https://www.spheron.network/blog/batch-llm-inference-gpu-cloud/) (2026)  
- [vLLM LLM Serving in Production](https://ammarab.medium.com/llm-serving-with-vllm-23e3b1e0c617)  
- [llama.cpp batch inference discussion (HN)](https://news.ycombinator.com/item?id=44367827) (Jun 2025)

---

## 5. Tailscale for LAN Model Serving

**Confidence: Medium** — Practical implementations well-documented; hard latency numbers absent from public sources.

### Network Overhead

Tailscale uses WireGuard under the hood — cryptographically authenticated, end-to-end encrypted. On a LAN where devices can connect directly (same subnet), Tailscale will use **direct peer-to-peer connections** (not relay) via UDP. Overhead is:
- WireGuard handshake: one-time, sub-millisecond after first connection.
- Per-packet encryption: typically adds <0.5ms on LAN; negligible vs. inference latency (seconds).
- **Practical verdict**: "The actual AI processing still happens locally — performance remains the same as sitting at the desk" (multiple community sources). No measurable degradation for inference workloads where generation time dominates.

### HTTPS / Auth on Tailnet

- Tailscale provides **HTTPS certificates for tailnet devices** (`device.tailnet.ts.net`) via MagicDNS and Let's Encrypt. No reverse proxy needed.
- For OpenAI-compatible endpoints: expose on Tailscale IP (`100.x.x.x:8080`), wrap with `https://device.tailnet.ts.net:8080` or use Caddy on the inference box for automatic TLS.
- **Auth options:**
  1. Tailscale ACL (network-level) — trusted devices implicitly trusted; no API key needed. Simple for personal setup.
  2. API key header (`Authorization: Bearer <key>`) — add at LiteLLM layer for explicit per-caller auth.
  3. Tailscale Aperture — new service (2025) that holds API keys and tracks usage for AI agents; more complex but gives audit trail.

### LM Link (Tailscale + LM Studio)

Tailscale and LM Studio partnered on **LM Link**: devices auto-discover each other on the tailnet, serve model requests P2P. Specifically for Mac-to-Mac or Mac-to-remote scenarios. Available in LM Studio 0.4+.

### Patterns for Artemis

- Mac Mini and inference box on same Tailscale tailnet → direct peer connection.
- Python ModelPort targets `http://inference-box.tailnet:8000/v1` (or HTTPS variant).
- No firewall rules, no port forwarding, no public exposure.
- LiteLLM proxy runs on Mac Mini; its backends are Tailscale addresses.

**Sources:**  
- [Tailscale self-host local AI stack](https://tailscale.com/blog/self-host-a-local-ai-stack)  
- [LM Link — Tailscale blog](https://tailscale.com/blog/lm-link-remote-llm-access)  
- [Ollama + Tailscale remote access](https://logarithmicspirals.com/blog/using-tailscale-to-access-private-llms/)  
- [AI agents + Tailscale security (xda-developers)](https://www.xda-developers.com/tailscale-helps-secure-ai-agents/) (2026)  
- [Private AI + Tailscale setup (Medium)](https://medium.com/@bhargavaganti/i-built-my-own-private-ai-chatgpt-copilot-setup-using-local-llms-gpus-and-tailscale-b049168d00ff) (May 2026)

---

## 6. Wake / Sleep + Power Orchestration

**Confidence: Medium** — Practical implementations exist; no polished off-the-shelf LLM-specific solution found.

### 6.1 Linux Inference Box — Wake on LAN

**Standard approach (well-documented, 2025–2026):**
1. Enable WoL on NIC: `sudo ethtool -s eno1 wol ug` (must persist across reboots via systemd or udev rule).
2. Send magic packet from Mac Mini: `wakeonlan <mac-address>` or Python's `wakeonlan` library.
3. Idle-detect + auto-sleep: cron job every 5–10 minutes checks for active connections (e.g., `lsof -i:8000 | wc -l` for vLLM port); if idle X minutes, runs `sudo systemctl suspend`.
4. ARP stand-in trick (advanced): a Raspberry Pi or always-on device responds to ARP on the sleeping server's behalf so the tailnet address remains reachable — useful if you need the server to be "addressable" even while asleep.

**vLLM sleep/wake endpoints**: There's active GitHub issue (`llm-d/llm-d-inference-sim #218`) to add sleep/wakeup endpoints to vLLM server directly. Not yet released, but indicates direction.

**Python wrapper pattern** (confirmed working in community):
```python
def wake_inference_box():
    send_magic_packet("aa:bb:cc:dd:ee:ff")
    # poll until port 8000 responds, timeout 60s
    wait_for_port("inference-box.tailnet", 8000, timeout=60)

class ModelPortClient:
    def complete(self, prompt, **kwargs):
        wake_inference_box()  # no-op if already awake
        return openai_client.chat.completions.create(...)
```

**Cold start time**: Typical Linux + vLLM server boot = 30–90 seconds (BIOS POST + model load). WoL magic packet to first token: ~2–3 minutes for large models. Acceptable for overnight batch, not interactive.

### 6.2 Mac as Inference Box — Wake Patterns

- **Wake on network access**: macOS supports `pmset -a womp 1` (Wake on Magic Packet) and `pmset -a networkaccesswake 1` (wake on any network access) — requires Ethernet, not reliable on Wi-Fi.
- **Power Nap**: M-series Macs can respond to wake requests from Ethernet while in Power Nap mode. Inference server (Ollama/LM Studio) must be configured as a launch daemon to start on wake.
- **Launchd + pmset pattern** (LM Studio community): launchd plist starts `ollama serve` on login/wake; pmset maintains network access. Verified working in community (referenced in Medium article by Michael Hannecke, now 404 but approach confirmed in other sources).

### 6.3 Is Anyone Doing On-Demand Wake in Practice?

Yes — multiple 2025–2026 examples confirmed:
- Team sharing a Mac Studio across a dev team with auto-wake Python wrapper (Hannecke, Medium, 2026).
- Linux home server auto-sleep + WoL pattern (dgross.ca — detailed technical walkthrough, 2025).
- DreamServer project (Light-Heart-Labs/DreamServer on GitHub) — open-source "turn your PC/Mac/Linux into an AI server" with inference + agent support.

**Caveats:**
- WoL requires Ethernet. Wi-Fi WoL is unreliable on both Linux and Mac.
- Mac Mini must have a static DHCP lease or Tailscale address so WoL packet reaches it.
- After wake, model load time dominates cold-start latency. Pre-load model at startup (keep alive) to reduce to seconds rather than minutes.

**Sources:**  
- [Linux server auto-sleep + WoL (dgross.ca)](https://dgross.ca/blog/linux-home-server-auto-sleep) (2025)  
- [sleep-on-lan GitHub](https://github.com/SR-G/sleep-on-lan)  
- [DreamServer GitHub](https://github.com/Light-Heart-Labs/DreamServer)  
- [vLLM sleep/wake endpoint issue](https://github.com/llm-d/llm-d-inference-sim/issues/218)

---

## Summary Table: Recommended Stack per Platform

| Platform | Primary Serving Stack | Secondary / Alternative | Gateway |
|---|---|---|---|
| **Mac Mini (Apple Silicon)** | `vllm-mlx` (Anthropic + OpenAI API, Claude Code native) | `mlx-openai-server` (official, simpler) or LM Studio headless | LiteLLM proxy on Mac Mini |
| **Linux/x86 — NVIDIA GPU** | vLLM (production, best batch) or SGLang (best for MoE DeepSeek) | llama.cpp server (portability, no Python dep) | LiteLLM routes to local or cloud fallback |
| **Linux/x86 — Large RAM, small GPU (CPU/GPU hybrid)** | KTransformers + SGLang | llama.cpp with partial offload | LiteLLM |
| **Claude Code backend proxy** | `claude-code-router` (musistudio) | `vllm-mlx` native Anthropic API (no proxy needed) | — |

---

*Research compiled 2026-06-13. Sources cited per section. Web research; not empirically tested. Treat medium-confidence sections as starting points requiring hands-on validation.*
