# Topology: Mac-as-Inference-Host (Apple Silicon)

**Research date:** 2026-06-13
**Scope:** Evaluating a second Apple Silicon Mac (e.g. Mac Studio) as the *inference box* in Artemis's Mac-orchestrates-Mac topology. The orchestrator Mac Mini runs the Python brain + Claude Code / APEX workflow + LiteLLM gateway; the inference box handles heavy LLM calls over Tailscale.

---

## 1. Serving Stacks on macOS

### 1.1 mlx-lm / mlx_lm.server (Apple-native)

**Maturity:** High. Apple open-sourced MLX in late 2023; by mid-2026 it is the endorsed framework (Apple dedicated three WWDC 2025 sessions to it). Active PyPI releases throughout 2025–2026.
Source: [yage.ai MLX vs llama.cpp, 2026-03-31](https://yage.ai/share/mlx-apple-silicon-en-20260331.html)

**OpenAI API compatibility:** Yes — `mlx_lm.server` exposes `/v1/chat/completions` and `/v1/completions`. Not a full feature parity drop-in (no embeddings out-of-the-box on bare mlx_lm), but sufficient for Claude Code routing via LiteLLM.

**Anthropic API compatibility:** Not natively. Requires a LiteLLM or claude-code-router shim to translate `/v1/messages` → OpenAI format. Exception: vllm-mlx (see below) adds native `/v1/messages`.

**Multi-model:** No native hot-swap. One model loaded at a time; you must stop and restart to swap. Wrapping via Ollama or LM Studio adds multi-model management on top.

**Batching / concurrency:** Basic mlx_lm.server is single-request. Continuous batching requires wrapping with vllm-mlx or using LM Studio 0.4.2+.

**Long-context:** MLX handles large contexts well in unified memory. Prompt cache (KV reuse) is supported. At 40–50k token context on M3 Ultra, one benchmark observed ~10x slowdown vs short context — large-context performance is significantly below short-context headline numbers.
Source: [Billy Newport / Medium, M3 Ultra critique, accessed 2026-06-13](https://medium.com/@billynewport/apples-m3-ultra-mac-studio-misses-the-mark-for-llm-inference-f57f1f10a56f)

---

### 1.2 mlx-openai-server / mlx-omni-server

**Maturity:** Moderate-high. mlx-openai-server v1.8.1 released 2026-05-03; v1.6.0 (2026-02) added Responses API endpoint support. Built on FastAPI. Active maintenance.
Source: [PyPI mlx-openai-server](https://pypi.org/project/mlx-openai-server/); [GitHub cubist38/mlx-openai-server](https://github.com/cubist38/mlx-openai-server)

**OpenAI API compatibility:** Full drop-in target — `/v1/chat/completions`, vision, audio, embeddings (via mlx-vlm, mlx-whisper, mlx-embeddings sub-packages).

**Anthropic API compatibility:** Not native. Needs LiteLLM shim.

**Multi-model:** Single-model sessions; no hot-swap.

**Batching / concurrency:** Not documented as a feature; single-user inference target.

**Long-context:** Inherits MLX capabilities; same caveats as above.

---

### 1.3 vllm-mlx (waybarrios/vllm-mlx)

**Maturity:** Production-ready for Apple Silicon as of mid-2026. v0.3.0, 513 commits, 1.3k GitHub stars. Requires Python 3.10+, Apple Silicon M1+, macOS.
Source: [GitHub waybarrios/vllm-mlx](https://github.com/waybarrios/vllm-mlx)

**OpenAI API compatibility:** Full — `/v1/chat/completions`, `/v1/completions`, `/v1/embeddings`, `/v1/rerank`.

**Anthropic API compatibility:** **Yes, native** — `/v1/messages` with streaming, tool use, system prompts. Explicitly confirmed "Works with Claude Code."
Source: [GitHub waybarrios/vllm-mlx](https://github.com/waybarrios/vllm-mlx)

**Multi-model:** Not documented; single-model sessions likely (inherits MLX architecture).

**Batching / concurrency:** **Continuous batching** — paged KV cache design adapted from vLLM. Independent benchmark on M4 Pro 64 GB (DeepSeek V3 Q4, May 2026): 42 tok/s single-user → 1,150 tok/s aggregate at 32 concurrent users. 3.4x throughput increase over no-batching with 5 concurrent requests.
Source: [macgpu.com inference framework benchmark 2026](https://macgpu.com/en/blog/2026-mac-inference-framework-vllm-mlx-ollama-llamacpp-benchmark.html); [codersera.com comparison 2026](https://codersera.com/blog/ollama-vs-lm-studio-vs-vllm-vs-llama-cpp-vs-mlx-2026/)

**Long-context:** KV quantization (4-bit/8-bit) enables 256 concurrent sequences; KV cache management similar to upstream vLLM design.

**Caveat:** macOS-only. Separate from vllm-metal (the official vLLM Apple Silicon plugin).

---

### 1.4 vllm-metal (official vLLM Apple Silicon plugin)

**Maturity:** Experimental / community-maintained. v0.2.0 released 2026-04 brought "unified paged varlen Metal kernel" — 83x TTFT and 3.6x throughput improvement over v0.1.0, but still described as community-maintained, not production-grade.
Source: [GitHub vllm-project/vllm-metal](https://github.com/vllm-project/vllm-metal); [contracollective.com vllm-mlx 2026](https://contracollective.com/blog/vllm-mlx-apple-silicon-integration-2026)

**OpenAI API compatibility:** Yes (inherits vLLM API surface).

**Anthropic API compatibility:** Via LiteLLM shim only.

**Batching / concurrency:** PagedAttention design — same architecture as vllm-mlx but via Metal backend. Less mature than vllm-mlx.

**Admin burden:** Higher than Ollama/LM Studio. Requires arm64 Python 3.12, no Rosetta. Docker Model Runner now integrates vLLM Metal on macOS (Docker blog, 2026).
Source: [Docker blog on vLLM Metal macOS](https://www.docker.com/blog/docker-model-runner-vllm-metal-macos/)

---

### 1.5 LM Studio (headless mode)

**Maturity:** High. v0.4.0 (2026-01) introduced headless `llmster` mode; v0.4.2 (2026-02) added continuous batching to the MLX engine. GUI-first product with server mode bolted on.
Source: [codersera.com comparison 2026](https://codersera.com/blog/ollama-vs-lm-studio-vs-vllm-vs-llama-cpp-vs-mlx-2026/)

**OpenAI API compatibility:** Yes.

**Anthropic API compatibility:** No native. Needs LiteLLM.

**Multi-model:** Yes — model browser, easy hot-swap. Automatic routing between MLX and GGUF backends per model.

**Batching / concurrency:** Continuous batching in llmster (llama.cpp parallel-slot) and in MLX engine as of v0.4.2. ~50–90 tok/s with batching on Apple Silicon.

**Long-context:** No special mechanism beyond underlying engine (MLX or llama.cpp).

**Gotcha:** GUI-first design means headless mode is secondary; Metal contention can occur under multi-client load.

---

### 1.6 Ollama

**Maturity:** Very high — the most battle-tested local LLM tool. v0.19 (2026-03-31) switched Apple Silicon inference to MLX backend (from llama.cpp Metal), delivering 57% faster prefill and 93% faster decode on M5 Max.
Source: [Ollama blog: MLX powered](https://ollama.com/blog/mlx); [gingter.org Ollama goes MLX, 2026-04-23](https://gingter.org/2026/04/23/ollama-goes-mlx/)

**OpenAI API compatibility:** Native — `localhost:11434/v1` is default target for most agentic frameworks (Cursor, Continue, Aider, OpenWebUI).

**Anthropic API compatibility:** From v0.14.0 Ollama added Anthropic-compatible API, enabling direct `ANTHROPIC_BASE_URL` pointing from Claude Code without a shim.
Source: [marc0.dev Mac Mini AI Server guide 2026](https://www.marc0.dev/en/blog/ai-agents/mac-mini-ai-server-ollama-openclaw-claude-code-complete-guide-2026-1770481256372)

**Multi-model:** Excellent — ~150 curated models in library plus any GGUF import. Easy pull/run.

**Batching / concurrency:** **Single request per model by default.** Queue-only under concurrent load. For a coding harness fanning out parallel sub-agents, this is the primary weakness: "throughput collapses" under concurrent load (~41 tok/s baseline vs vLLM's ~793 tok/s in multi-user scenarios).
Source: [codersera.com comparison 2026](https://codersera.com/blog/ollama-vs-lm-studio-vs-vllm-vs-llama-cpp-vs-mlx-2026/)

**Long-context:** Inherits MLX. Default context 4096 tokens — must be overridden via `OLLAMA_NUM_CTX` or Modelfile for agentic use.

---

### 1.7 llama.cpp (Metal backend)

**Maturity:** High as reference implementation. Powers Ollama pre-v0.19 and many wrappers. Metal backend stable.

**OpenAI API compatibility:** `llama-server` exposes compatible endpoints.

**Anthropic API compatibility:** Via LiteLLM only.

**Batching / concurrency:** Parallel-slot feature available but no native continuous batching. Memory fragmentation (30–50%) compared to paged designs.

**Long-context:** Standard context management. After Ollama switched to MLX, llama.cpp's Metal path is ~1.4–1.8x slower than raw MLX on the same chip (the "3x" advantage often cited is Ollama-wrapped llama.cpp, which adds a ~50% Go-wrapper overhead).
Source: [yage.ai MLX vs llama.cpp 2026-03-31](https://yage.ai/share/mlx-apple-silicon-en-20260331.html)

---

## 2. Capability — Real Throughput Numbers

**Confidence: Medium** (benchmarks vary by model family, quant, context length, and harness version)

### Single-stream decode tok/s (approximate, MLX unless noted)

| Hardware | Model | Quant | tok/s | Source |
|---|---|---|---|---|
| M5 Max | Llama 5 70B | — | ~18 tok/s | [llmcheck.net benchmarks](https://llmcheck.net/benchmarks) |
| M5 Max (Ollama 0.19) | — | int4 | 134 tok/s decode, 1851 tok/s prefill | [yage.ai 2026-03-31](https://yage.ai/share/mlx-apple-silicon-en-20260331.html) |
| M4 Pro | Qwen3-Coder-30B (MoE) | — | ~130 tok/s (MLX) vs ~43 tok/s (Ollama/llama.cpp) | [yage.ai 2026-03-31](https://yage.ai/share/mlx-apple-silicon-en-20260331.html) |
| M4 Pro 24 GB | 7B Q4_K_M | — | 60–80 tok/s | [contracollective.com 2026](https://contracollective.com/blog/llama-cpp-vs-mlx-ollama-vllm-apple-silicon-2026) |
| M4 Pro 24 GB | 13B Q4_K_M | — | 35–50 tok/s | [contracollective.com 2026](https://contracollective.com/blog/llama-cpp-vs-mlx-ollama-vllm-apple-silicon-2026) |
| M3 Ultra 192 GB | DeepSeek V3 671B | 4-bit | ~17–18 tok/s (MLX); ~6.2 tok/s (llama.cpp) | [VentureBeat 2025-03](https://venturebeat.com/ai/deepseek-v3-now-runs-at-20-tokens-per-second-on-mac-studio-and-thats-a-nightmare-for-openai) |
| M3 Ultra 512 GB | DeepSeek V3-0324 671B | 4-bit | >20 tok/s (MLX) | [VentureBeat 2025-03](https://venturebeat.com/ai/deepseek-v3-now-runs-at-20-tokens-per-second-on-mac-studio-and-thats-a-nightmare-for-openai) |
| M3 Ultra | Gemma-3-27B | Q4 | ~41 tok/s | [markus-schall.de 2025-11](https://www.markus-schall.de/en/2025/11/apple-mlx-vs-nvidia-how-local-ki-inference-works-on-the-mac/) |
| M3 Ultra | Qwen3-30B | 4-bit | ~2,320 tok/s (prefill) / ~30–42 tok/s (decode at 4k ctx) | [sitepoint.com local LLMs 2026](https://www.sitepoint.com/local-llms-apple-silicon-mac-2026/) |
| 4× M3 Ultra cluster | Kimi K2 Thinking 1T | — | ~28 tok/s | [Medium Kimi K2.5 guide, accessed 2026-06-13](https://medium.com/@tentenco/how-to-run-kimi-k2-5-on-two-mac-studio-m4-ultra-machines-a-complete-deployment-guide-b7f704bf09df) |
| RTX 5090 | 8B Q4 | — | ~213 tok/s | [markus-schall.de 2025-11](https://www.markus-schall.de/en/2025/11/apple-mlx-vs-nvidia-how-local-ki-inference-works-on-the-mac/) |
| H100 (baseline) | Llama 3.1 8B BF16 | — | ~12,500 tok/s | [codersera.com 2026](https://codersera.com/blog/ollama-vs-lm-studio-vs-vllm-vs-llama-cpp-vs-mlx-2026/) |

### Batched / concurrent throughput

- **vllm-mlx on M4 Pro 64 GB (DeepSeek V3 Q4):** 42 tok/s single → 1,150 tok/s aggregate at 32 concurrent users (May 2026 benchmark)
  Source: [macgpu.com 2026](https://macgpu.com/en/blog/2026-mac-inference-framework-vllm-mlx-ollama-llamacpp-benchmark.html)
- **vLLM-MLX vs Ollama at 8 concurrent users:** ~2.3x higher throughput; at peak load ~16–20x.
  Source: [codersera.com 2026](https://codersera.com/blog/ollama-vs-lm-studio-vs-vllm-vs-llama-cpp-vs-mlx-2026/)

### Apple Silicon vs CUDA for agentic/coding harness

Apple Silicon generates tokens roughly at 60–70% of equivalent VRAM on CUDA at single-user rates. For *parallel sub-agent* workloads:
- CUDA (H100/A100) is "several times" higher throughput than MLX on M5 under concurrent load (academic framing).
- Apple Silicon's ceiling for multi-agent fan-out is constrained by sequential queuing in Ollama (default) and by memory bandwidth per request rather than compute.
- With vllm-mlx continuous batching, the gap closes substantially for modest concurrency (5–32 agents), but CUDA retains a large lead for true high-throughput agent fleets.
- For a single-user home harness with occasional parallel sub-agent fans (e.g. APEX wave dispatch), Apple Silicon is viable but not optimal for the fan-out phase.

Source: [stochasticsandbox.com agents on Apple Silicon 2026-03](https://stochasticsandbox.com/posts/the-stack-apple-silicon-local-agents-2026-03-28/); [yage.ai 2026-03-31](https://yage.ai/share/mlx-apple-silicon-en-20260331.html)

---

## 3. Setup + Admin Burden + Learning Curve

**Confidence: High**

### What is required

| Task | Terminal Required? | Difficulty |
|---|---|---|
| Install Ollama | No — .pkg installer | Trivial |
| Pull a model | Yes — `ollama pull <model>` | Trivial |
| Disable sleep | No — System Settings GUI | Easy |
| Set `OLLAMA_HOST=0.0.0.0` for network exposure | Yes — shell config | Easy |
| Install Tailscale | No — .pkg installer | Trivial |
| Enable SSH | No — System Settings > Sharing | Easy |
| Install vllm-mlx (for batching) | Yes — pip install, Python env | Moderate |
| LiteLLM proxy for Anthropic shim | Yes — pip, config.yaml | Moderate |
| LaunchDaemon for persistent startup | Yes — plist authoring | Hard (but optional) |
| FileVault disable for headless reboot | No — GUI | Easy |

### Honest assessment

For Ollama + basic Tailscale + SSH: genuinely low admin. A non-technical user can do it with a guide in under 30 minutes, minimal terminal use.

For vllm-mlx or LiteLLM shim (needed for proper batching + Anthropic API): moderate — requires Python environment management, config files, and some terminal comfort. Not Linux-level but not zero-terminal either.

For truly zero-admin long-term operation (auto-restart on crash, auto-startup after power outage, LaunchDaemon): requires plist authoring and `launchctl` — one-time setup but genuinely unfamiliar to macOS-only users.

macOS is meaningfully lower barrier than Linux: no kernel module management, no driver installation, Homebrew for packages, GUI System Settings for most persistence options.

Source: [infralovers.com Mac Mini LLM endpoint 2026-02](https://www.infralovers.com/blog/2026-02-24-mac-mini-company-llm-endpoint/); [marc0.dev guide 2026](https://www.marc0.dev/en/blog/ai-agents/mac-mini-ai-server-ollama-openclaw-claude-code-complete-guide-2026-1770481256372); [astropad.com headless Mac guide 2026](https://astropad.com/blog/headless-mac-mini-setup-guide/)

---

## 4. 24/7 Headless Reliability

**Confidence: Medium** (long-term uptime data is anecdotal; no published SLA-grade reports found)

### Sleep / Wake

- **Critical:** macOS auto-sleep will kill inference mid-session unless disabled. Disabling requires:
  - `sudo pmset -a sleep 0`
  - `sudo pmset -a disablesleep 1`
  - System Settings > Energy: "Prevent automatic sleeping when display is off" ✅
  - "Start up automatically after power failure" ✅
- After these settings, the Mac runs indefinitely without display.
- `pmset -g | grep -i sleep` to verify.
Source: [ai-girls.org Mac Mini sleep/Tailscale 2026-02](https://ai-girls.org/en/2026/02/22/mac-mini-sleep-tailscale-troubleshooting-en/)

### HDMI Dummy Plug

- **Apple Silicon (M1+): not required for inference.** MLX/Metal GPU access does not require a connected display. macOS creates a default 1920×1080 virtual display automatically.
- Intel Macs: required. Not relevant for a Mac Studio (Apple Silicon).
- Optional software alternative: BetterDummy app for resolution control.
Source: [astropad.com headless guide 2026](https://astropad.com/blog/headless-mac-mini-setup-guide/)

### MLX/Ollama Server Stability

- No published multi-week uptime data found for MLX servers specifically.
- oMLX v0.3.11 (2026) added a "rewritten memory guard for enhanced stability on low-memory Macs" — implies prior OOM crashes were a known issue.
- vllm-mlx: 513 commits, active bug fixes; no published stability reports.
- Anecdotal community consensus: Ollama is the most stable for 24/7 headless (oldest, most battle-tested), but lacks concurrency.
Source: [stork.ai oMLX review 2026](https://www.stork.ai/en/omlx)

### FileVault

- **Disable FileVault** for headless server if you want auto-login after power outages. FileVault pre-boot encryption blocks network access until manual unlock. This is a meaningful gotcha for unattended restarts.
Source: [astropad.com headless guide 2026](https://astropad.com/blog/headless-mac-mini-setup-guide/)

### Power Draw

- Mac Mini M4: ~12W idle, ~30W under inference load. 24/7 cost: ~$15–20/year.
- Mac Studio M3 Ultra: higher (~60–100W estimated under full load) but still far below any discrete GPU setup.
Source: [marc0.dev guide 2026](https://www.marc0.dev/en/blog/ai-agents/mac-mini-ai-server-ollama-openclaw-claude-code-complete-guide-2026-1770481256372)

---

## 5. Remote Orchestration from Another Mac over Tailscale

**Confidence: High**

### SSH

- Built into macOS. Enable: System Settings > Sharing > Remote Login.
- Tailscale provides stable private IP/hostname regardless of local network topology.
- Combined: `ssh user@<tailscale-hostname>` works reliably.
- While SSH connection is open, Mac stays awake (caffeinate is an extra guarantee).

### Wake-on-LAN

- macOS "Wake for network access" exists but is **unreliable for standard TCP**: requires WOL magic packets (6× 0xFF + MAC × 16), not regular SSH connection attempts.
- Practical solutions in the community:
  - Raspberry Pi or ESP32 always-on device on LAN to send WOL magic packets.
  - [tailscale-wakeonlan](https://github.com/andygrundman/tailscale-wakeonlan) tool for triggering WOL via Tailscale.
  - Tailscale + UpSnap combination documented by Tailscale officially.
- **Recommended approach for Artemis:** Keep the inference Mac *never sleeping* (pmset). WOL complexity is only needed if you want the inference Mac to sleep between jobs — for a dedicated inference box, always-on is simpler.
Source: [tailscale.com WOL guide](https://tailscale.com/blog/wake-on-lan-tailscale-upsnap); [ai-girls.org 2026-02](https://ai-girls.org/en/2026/02/22/mac-mini-sleep-tailscale-troubleshooting-en/)

### Exposing the Model Endpoint

- Ollama: `OLLAMA_HOST=0.0.0.0:11434` — binds to all interfaces including Tailscale.
- vllm-mlx: `--host 0.0.0.0 --port 8000` (default).
- Tailscale ACLs can restrict access to only the orchestrator Mac's Tailscale IP.

### Tailscale Auto-Start on macOS

- Tailscale does **not** auto-start after reboot by default. Fix:
  ```
  osascript -e 'tell application "System Events" to make login item at end with properties {path:"/Applications/Tailscale.app", hidden:false}'
  ```
Source: [ai-girls.org 2026-02](https://ai-girls.org/en/2026/02/22/mac-mini-sleep-tailscale-troubleshooting-en/)

### Latency

- Tailscale DERP relay adds ~5–30ms in typical home configurations; direct peer-to-peer (same LAN subnet) is 1–3ms.
- For LLM inference (TTFT 300–2000ms dominant), Tailscale overhead is negligible.

---

## 6. Claude Code / Anthropic-API Backend on macOS

**Confidence: High**

### The Translation Problem

Claude Code speaks Anthropic Messages API (`/v1/messages`). Most Mac inference stacks speak OpenAI format. Two solutions:

**Option A — vllm-mlx (no shim needed)**
- Native `/v1/messages` with streaming + tool use.
- Set `ANTHROPIC_BASE_URL=http://<inference-mac>:8000` (or Tailscale hostname).
- Explicitly documented as "Works with Claude Code."
- Best choice for Artemis's LiteLLM gateway pattern — vllm-mlx on the inference box, LiteLLM on the orchestrator translates upstream.
Source: [GitHub waybarrios/vllm-mlx](https://github.com/waybarrios/vllm-mlx)

**Option B — LiteLLM shim (works with any stack)**
- Install on orchestrator Mac Mini: `pip install 'litellm[proxy]'`
- `config.yaml` maps Anthropic-format requests to Ollama/vllm-mlx OpenAI endpoint.
- `ANTHROPIC_BASE_URL=http://localhost:4000` in Claude Code.
- Required env: `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`, `DISABLE_PROMPT_CACHING=1`, `DISABLE_INTERLEAVED_THINKING=1`.
- **Security warning:** LiteLLM PyPI v1.82.7 and v1.82.8 shipped credential-stealing malware (2025). Always pin version and verify hash.
Source: [DEV Community: Claude Code + LiteLLM](https://dev.to/dcruver/running-claude-code-with-local-llms-via-vllm-and-litellm-599b); [morphllm.com Claude Code LiteLLM 2026](https://www.morphllm.com/claude-code-litellm)

**Option C — claude-code-router (simplest solo path)**
- Handles API translation without full LiteLLM proxy.
- Less overhead; no team/auth features.
- Simpler config; appropriate for single-user Artemis.
Source: [Medium: Two practical approaches](https://medium.com/@michael.hannecke/connecting-claude-code-to-local-llms-two-practical-approaches-faa07f474b0f)

**Option D — Ollama v0.14.0+ direct Anthropic endpoint**
- Ollama added `/v1/messages` compatibility natively; can be pointed at directly by Claude Code.
- Less feature-complete than vllm-mlx's Anthropic implementation.

### Agentic / Tool-Use Quality

- Verified working: structured tool calls, multi-turn, file generation, agentic loops (tested on Qwen3-Coder-30B-A3B, achieving a complete Flask app with 91% prefix cache hit rate).
- Known limitations: local models struggle with "complex architectural decisions" vs Claude; context window capped at 64K (vs Anthropic's 200K); no native caching as sophisticated as Anthropic's.
- Critical context-length config: Ollama defaults 4096 tokens — override via `OLLAMA_NUM_CTX` or Modelfile for APEX-style deep sessions.
Source: [DEV Community: Claude Code + vLLM](https://dev.to/dcruver/running-claude-code-with-local-llms-via-vllm-and-litellm-599b); [Medium: Two practical approaches](https://medium.com/@michael.hannecke/connecting-claude-code-to-local-llms-two-practical-approaches-faa07f474b0f)

---

## 7. Real-World Write-Ups

**Confidence: Medium** (most are from early 2026; long-term production reports rare)

### Infralovers — Mac Mini M4 Company LLM Endpoint (Feb 2026)

Small team running Mac Mini M4 32 GB with Ollama as shared internal endpoint. Models: qwen2.5-coder:7b, mistral:7b, gemma3:4b. Findings: "all four models combined use under 14GB"; output "faster than you can read it" for 7B models. Limitations: "heavy simultaneous usage can cause slowdowns or model unloading." Positioned as "one option in the toolbox" for routine high-volume tasks where privacy matters, not a universal solution.
Source: [infralovers.com 2026-02](https://www.infralovers.com/blog/2026-02-24-mac-mini-company-llm-endpoint/)

### marc0.dev — Mac Mini M4 AI Agent Server (2026)

Solo developer running Mac Mini M4 with Ollama + OpenClaw (Claude Code alternative). Setup highlights: HDMI dummy plug (believed required at time of writing — now known unnecessary for Apple Silicon), sleep disabled via System Settings, Tailscale for remote access, Spotlight indexing excluded from model directories. Clean headless SSH setup.
Source: [marc0.dev 2026](https://www.marc0.dev/en/blog/ai-agents/mac-mini-ai-server-ollama-openclaw-claude-code-complete-guide-2026-1770481256372)

### Ewan Mak — Dual Mac Studio M3 Ultra for Kimi K2.5 (2026)

Running Kimi K2 Thinking (1T parameter MoE) across a cluster of four M3 Ultra Mac Studios (1.5 TB total memory) at ~28 tok/s. Single-machine: requires 512 GB+ M3 Ultra for the full 671B–1T MoE range. Pipeline parallelism over Thunderbolt 5 RDMA: "relatively new technology with stability that may not match mature solutions." Port limitation: Thunderbolt 5 adjacent to Ethernet cannot be used for RDMA.
Source: [Medium Kimi K2.5 guide 2026](https://medium.com/@tentenco/how-to-run-kimi-k2-5-on-two-mac-studio-m4-ultra-machines-a-complete-deployment-guide-b7f704bf09df)

### Billy Newport — M3 Ultra Critique (accessed 2026-06-13)

Critical assessment: M3 Ultra is "a $10k dud for inference" — the GPU throughput is the bottleneck, not RAM. At large context (40–50k tokens), performance is ~10x slower than with short prompts. The author uses 40–50k token contexts routinely for document processing. Conclusion: enough RAM doesn't fix GPU throughput limits.
Source: [Medium: Billy Newport 2025](https://medium.com/@billynewport/apples-m3-ultra-mac-studio-misses-the-mark-for-llm-inference-f57f1f10a56f)

### VentureBeat — DeepSeek V3 on Mac Studio (Mar 2025)

DeepSeek V3-0324 (671B, 4-bit) achieves >20 tok/s on M3 Ultra 512 GB via mlx-lm. Described as a "nightmare for OpenAI" due to cost-effectiveness. Single-user practical use case confirmed.
Source: [VentureBeat 2025-03-25](https://venturebeat.com/ai/deepseek-v3-now-runs-at-20-tokens-per-second-on-mac-studio-and-thats-a-nightmare-for-openai)

---

## 8. Honest Verdict

**Confidence: High for qualitative; Medium for quantitative**

### Strengths

1. **Zero-admin hardware.** No driver management, no kernel modules, no CUDA toolkit versioning. macOS handles GPU drivers silently.
2. **Unified memory advantage.** 192–512 GB on M3/M4 Ultra means full-precision or high-quant versions of 70B–200B models fit without VRAM fragmentation. A 671B MoE at 4-bit fits in 192 GB.
3. **Silent, power-efficient 24/7 operation.** Mac Studio: ~40–80W under load. No fan noise worth mentioning. Annual power cost for 24/7 inference: < $100.
4. **macOS ecosystem fit.** Tailscale, SSH, System Settings for all persistence config. Ollama is a .pkg install with one-command model pulls. Lowest learning curve of any inference platform.
5. **MLX is Apple's own framework.** Continuously accelerated with new hardware (M5 Neural Accelerators add 4x TTFT improvement unavailable to llama.cpp). Platform lock-in is a feature here — Apple Silicon keeps getting better at it.
6. **Claude Code backend works.** vllm-mlx provides native Anthropic `/v1/messages` — no shim needed for the critical use case.

### Weaknesses

1. **Single-user throughput is adequate but not fast.** DeepSeek-class 671B MoE: 17–20 tok/s. For a coding harness, this means ~3–5 seconds/response for short outputs; fine for interactive, slow for batch. Compare: a mid-tier NVIDIA GPU server at 80–100 tok/s.
2. **Parallel sub-agent fan-out is the weakest point.** Ollama (default, easiest) queues requests serially. APEX-style parallel wave dispatch will serialize. vllm-mlx with continuous batching partially addresses this but adds setup complexity.
3. **Large context degrades severely.** At 40–50k token contexts, throughput drops ~10x on M3 Ultra. For Kimi-style large-context use cases, this is painful.
4. **Not upgradeable.** The Mac Studio you buy is the Mac Studio you keep. No adding a second GPU, no RAM upgrade. If the model size grows beyond the box's memory, you buy a new box.
5. **MLX is macOS-only.** Zero portability to Linux. If Artemis ever moves to a different platform, the inference layer must be rebuilt.
6. **No true batched training / fine-tuning at scale.** Fine-tuning is possible (LoRA via mlx-lm) but not competitive with datacenter hardware.

### Gotchas

- **Sleep:** Must be explicitly disabled; macOS will sleep by default and kill all services. FileVault must be disabled for unattended reboot recovery.
- **Tailscale auto-start:** Not enabled by default on macOS — requires login item registration.
- **Ollama context window:** Default 4096 tokens — will silently truncate APEX sessions without `OLLAMA_NUM_CTX` override.
- **LiteLLM supply chain risk:** PyPI versions 1.82.7–1.82.8 contained credential-stealing malware. Pin and verify.
- **vllm-mlx is macOS-only and single-platform:** excellent for this topology but zero transferability.
- **RDMA for multi-Mac clustering** (needed for 1T+ models): Thunderbolt 5 RDMA is immature; port restrictions apply.

### Recommendation for Artemis

A Mac Studio M3 Ultra (192 GB) or M4 Ultra is a **reasonable choice** if:
- DeepSeek Flash-class (~30B MoE active params, not 284B dense) is the primary model — 30B MoE runs at 80–130 tok/s single-stream on M4-class hardware, which is good.
- The Kimi long-context use is occasional, not primary (10x slowdown at 50k context is acceptable if infrequent).
- Owner wants the lowest possible admin burden and is comfortable with slower-but-works for the parallel fan-out phase.

A Mac Studio is a **poor choice** if:
- True 284B dense DeepSeek-class performance is required (17–20 tok/s is the ceiling, not the floor).
- Parallel sub-agent concurrency (APEX wave dispatch) needs to run quickly — queued serial processing will noticeably slow build sessions.
- The budget could instead buy a machine with 2× RTX 5090 (213 tok/s per 8B, proportionally faster at all sizes, with proper batching).

**Bottom line:** The Mac-inference-box topology is the *simplest to operate* and *cheapest to run*, but leaves significant throughput on the table compared to a dedicated Linux GPU box. For Artemis's single-user coding harness, the tradeoff is viable — the user gets a silent $3k–$5k appliance that needs zero Linux knowledge and works with `export ANTHROPIC_BASE_URL=...`. The cost is accepting ~15–20 tok/s on the largest models and serial queuing during APEX parallel waves.

---

## Sources

- [mlx-openai-server PyPI](https://pypi.org/project/mlx-openai-server/) — accessed 2026-06-13
- [GitHub cubist38/mlx-openai-server](https://github.com/cubist38/mlx-openai-server) — accessed 2026-06-13
- [Ollama blog: MLX-powered on Apple Silicon](https://ollama.com/blog/mlx) — 2026-03-31
- [yage.ai: MLX vs llama.cpp benchmarks, M5 Neural Accelerators](https://yage.ai/share/mlx-apple-silicon-en-20260331.html) — 2026-03-31
- [contracollective.com: llama.cpp vs MLX vs Ollama vs vLLM 2026](https://contracollective.com/blog/llama-cpp-vs-mlx-ollama-vllm-apple-silicon-2026) — 2026
- [codersera.com: Ollama vs LM Studio vs vLLM vs llama.cpp vs MLX 2026](https://codersera.com/blog/ollama-vs-lm-studio-vs-vllm-vs-llama-cpp-vs-mlx-2026/) — 2026
- [macgpu.com: Mac LLM concurrency & queuing 2026](https://macgpu.com/en/blog/2026-0414-mac-local-llm-concurrency-queue-ollama-lmstudio-tail-latency-remote.html) — 2026-04-14
- [macgpu.com: inference framework selection 2026](https://macgpu.com/en/blog/2026-mac-inference-framework-vllm-mlx-ollama-llamacpp-benchmark.html) — 2026
- [stochasticsandbox.com: Apple Silicon local agents](https://stochasticsandbox.com/posts/the-stack-apple-silicon-local-agents-2026-03-28/) — 2026-03-28
- [GitHub waybarrios/vllm-mlx](https://github.com/waybarrios/vllm-mlx) — accessed 2026-06-13
- [GitHub vllm-project/vllm-metal](https://github.com/vllm-project/vllm-metal) — accessed 2026-06-13
- [contracollective.com: vllm-mlx Apple Silicon 2026](https://contracollective.com/blog/vllm-mlx-apple-silicon-integration-2026) — 2026
- [VentureBeat: DeepSeek V3 on Mac Studio](https://venturebeat.com/ai/deepseek-v3-now-runs-at-20-tokens-per-second-on-mac-studio-and-thats-a-nightmare-for-openai) — 2025-03-25
- [Medium Billy Newport: M3 Ultra critique](https://medium.com/@billynewport/apples-m3-ultra-mac-studio-misses-the-mark-for-llm-inference-f57f1f10a56f) — accessed 2026-06-13
- [Medium Kimi K2.5 on Mac Studio](https://medium.com/@tentenco/how-to-run-kimi-k2-5-on-two-mac-studio-m4-ultra-machines-a-complete-deployment-guide-b7f704bf09df) — 2026
- [markus-schall.de: M3 Ultra vs RTX 5090](https://www.markus-schall.de/en/2025/11/apple-mlx-vs-nvidia-how-local-ki-inference-works-on-the-mac/) — 2025-11
- [localaimaster.com: Apple Silicon buying guide 2026](https://localaimaster.com/blog/apple-silicon-ai-buying-guide) — 2026
- [sitepoint.com: Local LLMs Apple Silicon Mac 2026](https://www.sitepoint.com/local-llms-apple-silicon-mac-2026/) — 2026
- [llmcheck.net benchmarks](https://llmcheck.net/benchmarks) — accessed 2026-06-13
- [infralovers.com: Mac Mini company LLM endpoint 2026-02](https://www.infralovers.com/blog/2026-02-24-mac-mini-company-llm-endpoint/) — 2026-02-24
- [marc0.dev: Mac Mini AI Server guide 2026](https://www.marc0.dev/en/blog/ai-agents/mac-mini-ai-server-ollama-openclaw-claude-code-complete-guide-2026-1770481256372) — 2026
- [astropad.com: headless Mac mini setup 2026](https://astropad.com/blog/headless-mac-mini-setup-guide/) — 2026
- [ai-girls.org: Mac Mini sleep/Tailscale troubleshooting 2026-02](https://ai-girls.org/en/2026/02/22/mac-mini-sleep-tailscale-troubleshooting-en/) — 2026-02-22
- [tailscale.com: Wake-on-LAN + UpSnap](https://tailscale.com/blog/wake-on-lan-tailscale-upsnap) — accessed 2026-06-13
- [gingter.org: Ollama goes MLX 2026-04-23](https://gingter.org/2026/04/23/ollama-goes-mlx/) — 2026-04-23
- [DEV Community: Claude Code + LiteLLM](https://dev.to/dcruver/running-claude-code-with-local-llms-via-vllm-and-litellm-599b) — accessed 2026-06-13
- [Medium: Two practical approaches to Claude Code + local LLMs](https://medium.com/@michael.hannecke/connecting-claude-code-to-local-llms-two-practical-approaches-faa07f474b0f) — accessed 2026-06-13
- [morphllm.com: Claude Code LiteLLM setup 2026](https://www.morphllm.com/claude-code-litellm) — 2026
- [stork.ai: oMLX review 2026](https://www.stork.ai/en/omlx) — 2026
- [Docker blog: vLLM Metal on macOS](https://www.docker.com/blog/docker-model-runner-vllm-metal-macos/) — accessed 2026-06-13
