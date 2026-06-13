# Windows GPU Box as Headless LLM Inference Host

**Research date:** 2026-06-13  
**Scope:** Evaluating a Windows CUDA PC as the inference node in the "Mac orchestrates Windows" topology for Artemis. Target models: DeepSeek V4-Flash-class (~284B MoE, 13B active); secondary: large-context models (Kimi-class). Single-user home; owner knows Windows, does not want to learn Linux.

---

## Q1. Serving Stack on Windows: Native vs WSL2

### Native Windows (100% no-WSL)

#### Ollama (native Windows)
- **Maturity:** Production-grade. Ollama runs natively on Windows 11 with full GPU support. Install via `.exe` or `winget`. Runs as a background process (port 11434). Can be wrapped as a Windows service using NSSM or AlwaysUp.
- **OpenAI-API compat:** Full OpenAI-compatible REST API at `localhost:11434`. As of **Ollama v0.14.0 (January 2026)**, native Anthropic Messages API support was added, enabling Claude Code to connect directly without a LiteLLM shim.
  - Source: [Running Claude Code Locally with Ollama and LiteLLM, n1n.ai, 2026-01-25](https://explore.n1n.ai/blog/running-claude-code-locally-with-ollama-and-litellm-2026-01-25)
- **Multi-model:** Yes — multiple models can be loaded; `OLLAMA_NUM_PARALLEL` controls concurrency (default: auto, typically 1–4 depending on VRAM).
- **Batching/concurrency:** Moderate. Single-user fine. At 8+ concurrent users, Ollama queues and can time out (13–30% error rate under heavy load). vLLM handles concurrency ~2× better at 8+ parallel requests.
  - Source: [Ollama vs vLLM throughput benchmark 2026, Markaicode](https://markaicode.com/ollama-vs-vllm-performance/)
  - Source: [Ollama vs. vLLM: Why Ollama is Slow for Multiple Users, Arsturn](https://www.arsturn.com/blog/ollama-vs-homl-the-real-reason-ollama-is-slower-for-multiple-users)
- **Tensor-parallel multi-GPU:** Basic multi-GPU support (Ollama splits model layers across GPUs) but not true tensor parallelism. No NCCL-based communication.
- **Cap for Artemis:** Good enough for single-user Artemis coding agent use. Hits a ceiling for the heavy batched throughput vLLM provides.

#### LM Studio (headless `llmster` daemon)
- **Maturity:** LM Studio 0.4+ ships a headless daemon called `llmster`, installable on Windows via PowerShell one-liner (`irm https://lmstudio.ai/install.ps1 | iex`). Managed via `lms` CLI.
- **OpenAI-API compat:** Yes — full OpenAI-compatible API server + Anthropic-compatible endpoints.
  - Source: [LM Studio headless docs, lmstudio.ai](https://lmstudio.ai/docs/advanced/headless)
  - Source: [LM Studio 0.4 Headless Deployment, SitePoint](https://www.sitepoint.com/lm-studio-04-headless-deployment-local-llm-apis-without-the-gui/)
- **Multi-model:** Yes, via model management CLI.
- **Batching/concurrency:** Similar ceiling to Ollama — designed for developer/single-user use, not high-concurrency production.
- **Tensor-parallel multi-GPU:** No advanced TP. GUI-lineage; the daemon is a thin CLI wrapper around the same inference core.
- **Assessment:** Easier setup than Ollama for some users; no meaningful performance advantage; Ollama is the better headless server pick.

#### llama.cpp (native CUDA)
- **Maturity:** Mature, pre-built Windows CUDA binaries available. Runs as `llama-server` exposing OpenAI-compatible API.
- **OpenAI-API compat:** Yes — `llama-server` exposes OpenAI-compatible endpoint.
- **Batching/concurrency:** Better than Ollama for parallel requests at moderate concurrency; inferior to vLLM.
- **Tensor-parallel multi-GPU:** Limited — `--split-mode` for layer/row splitting, but not production NCCL-grade TP.
- **Throughput on RTX 3090 (27B Q4_K_M):** ~45–55 tok/s single stream.
  - Source: [Running LLMs on Windows: Native vLLM vs WSL vs llama.cpp, DEV Community](https://dev.to/alanwest/running-llms-on-windows-native-vllm-vs-wsl-vs-llamacpp-compared-37a9)

#### Native vLLM (community forks)
vLLM has **no official Windows support** as of June 2026. The vLLM team's position: maintenance cost is too high relative to Windows-first inference audience; WSL2 is the recommended path.
- Source: [vLLM on Windows in 2026, fazm.ai](https://fazm.ai/t/vllm-windows-support-2026)
- Source: [RFC: vLLM Windows CUDA support, GitHub issue #14981](https://github.com/vllm-project/vllm/issues/14981)

Three community paths exist:

**a) aivrar/vllm-windows-build (vLLM 0.21.0)**
- Pure native Windows, no WSL/Docker. Pre-built wheel for Python 3.13 + CUDA 12.8 + PyTorch 2.11. Supports RTX 50-series Blackwell (sm_120).
- OpenAI API server now functional (fixed four Windows-specific bugs).
- **Multi-GPU: SINGLE GPU ONLY.** `FakeProcessGroup` workaround — NCCL not available on Windows. Multi-GPU requires separate vLLM instances + external load balancer.
- Missing: FlashInfer, FlashAttention 3/4, fastsafetensors.
- Triton JIT cold-start: 1–2 min first inference.
- Maturity: 23 GitHub stars, 7 releases, tested on RTX 3090. Nascent for production multi-GPU serving.
  - Source: [aivrar/vllm-windows-build, GitHub](https://github.com/aivrar/vllm-windows-build)

**b) devnen/vllm-windows (patched SystemPanic 0.19.0)**
- Adds CPU-relay for Gloo collectives (enables tensor/pipeline parallelism as a workaround, staging through pinned CPU buffers — performance impact unquantified).
- Fixes Qwen3 reasoning parser, tool calling, wildcard model names.
- 8-test tool-call harness included.
- Requires NVIDIA drivers 553+ (Ampere) or 596+ (Blackwell).
- Locked to SystemPanic 0.19.0 internals; not tracking vLLM main.
  - Source: [devnen/vllm-windows, GitHub](https://github.com/devnen/vllm-windows)

**c) SystemPanic/vllm-windows fork (v0.20.0, April 30 2026)**
- First community build offering NCCL + tensor and pipeline parallelism on Windows.
- Built for Python 3.12, CUDA 13, PyTorch 2.11.
- Community-maintained; not blessed by vLLM project.
  - Source: [vLLM on Windows in 2026, fazm.ai](https://fazm.ai/t/vllm-windows-support-2026)

**Confidence: High** — multiple corroborating sources including GitHub issue trackers and dated community builds.

---

### WSL2 Path (effectively Linux)

- **Maturity:** Production-grade as of 2025–2026. WSL2 runs a real Linux kernel with NVIDIA GPU passthrough that "just works" with recent Windows NVIDIA drivers. No Linux CUDA driver inside WSL2 — Windows driver is stubbed as `libcuda.so`.
  - Source: [CUDA on WSL User Guide, NVIDIA](https://docs.nvidia.com/cuda/wsl-user-guide/index.html)
  - Source: [WSL2 for Local AI Complete Guide, InsiderLLM](https://insiderllm.com/guides/wsl2-local-ai-windows-guide/)
- **Tools available:** Full vLLM, SGLang, Docker + NVIDIA Container Toolkit — everything that runs on Linux.
- **OpenAI-API compat:** Full (vLLM/SGLang serve on localhost ports accessible from Windows host and LAN via mirrored networking mode).
- **Multi-model and batching:** Same as Linux — vLLM's continuous batching, SGLang's RadixAttention.
- **Tensor-parallel multi-GPU:** Full NCCL-based TP, same as Linux. This is the **only path on Windows** that gives you real production-grade multi-GPU TP.
- **Setup time:** ~20 minutes from fresh Windows to running first model.
- **Critical caveat:** File I/O via Windows mounts (`/mnt/c/`) runs at only 30–50% throughput. Models should be stored on native WSL2 ext4 filesystem (a virtual disk image on the Windows NVMe) for full I/O speed.
  - Source: [WSL2 for Local AI Complete Guide, InsiderLLM](https://insiderllm.com/guides/wsl2-local-ai-windows-guide/)
- **Docker Model Runner (Dec 2025):** Docker Desktop 4.54+ added a vLLM-on-Windows path using the WSL2 backend. Requires NVIDIA GPU compute capability ≥ 8.0 (Ampere+). Simplest single-command setup; inherits WSL2 virtualization overhead.
  - Source: [vLLM on Windows in 2026, fazm.ai](https://fazm.ai/t/vllm-windows-support-2026)

**SGLang on Windows:** No native Windows support documented as of June 2026. WSL2 only.

**Confidence: High** — NVIDIA official documentation + multiple community guides.

---

## Q2. Capability: Real Throughput on Windows CUDA

### Single-stream tok/s (RTX 3090 24GB, ~27B model)

| Stack | Format | Throughput | VRAM |
|---|---|---|---|
| Native vLLM (community fork) | FP16/BF16 | ~72 tok/s | ~22 GB |
| WSL2 vLLM | FP16/BF16 | ~65–70 tok/s | ~22 GB + small overhead |
| llama.cpp native | Q4_K_M GGUF | ~45–55 tok/s | ~16 GB |
| Ollama native | Q4_K_M | ~40–50 tok/s | ~16 GB |

Source: [Running LLMs on Windows: Native vLLM vs WSL vs llama.cpp, DEV Community / Hashnode](https://alan-west.hashnode.dev/running-llms-on-windows-native-vllm-vs-wsl-vs-llamacpp-compared)

### WSL2 overhead
- **Ollama/llama.cpp (GPU-bound):** 10–13% performance gap WSL2 vs native. "The bottleneck is GPU memory bandwidth, not the OS layer."
- **vLLM (WSL2 vs native):** 20–40% throughput loss due to GPU passthrough overhead and CPU-side scheduling.
- Source: [Ollama on Windows 11: Native App vs. WSL, Windows Forum](https://windowsforum.com/threads/ollama-on-windows-11-native-app-vs-wsl-for-local-llms.379552/)
- Source: [WSL2 for Local AI, InsiderLLM](https://insiderllm.com/guides/wsl2-local-ai-windows-guide/)

### Concurrent/batched throughput (A100 baseline, scales proportionally)
- Ollama at 1 concurrent: ~45 tok/s; at 8 concurrent: ~82 tok/s total.
- vLLM at 1 concurrent: ~38 tok/s; at 8 concurrent: ~187 tok/s total.
- At 8+ concurrent requests, vLLM handles load ~2.3× more efficiently than Ollama.
- Source: [Ollama vs vLLM Deep Dive, Red Hat Developer (August 2025)](https://developers.redhat.com/articles/2025/08/08/ollama-vs-vllm-deep-dive-performance-benchmarking)

### DeepSeek V4-Flash (284B total / 13B active)
- Fits on a **single 80GB GPU** quantized; runs on a **2×48GB box** with Unsloth GGUF builds.
- On a consumer 2×24GB setup (e.g., dual RTX 3090), GGUF quantized serving is viable via llama.cpp or Ollama with layer splitting.
- True tensor parallelism for DeepSeek MoE on Windows requires WSL2 (for NCCL) or the SystemPanic fork (v0.20.0 with tensor-parallel, maturity unproven).
- Source: [DeepSeek V4 deployment guide, Clore.ai](https://docs.clore.ai/guides/language-models/deepseek-v4)

**Confidence: Medium** — benchmark data from community sources with stated hardware configs; no controlled Windows-vs-Linux head-to-head for DeepSeek V4-Flash specifically.

---

## Q3. Does Windows Actually Avoid Linux?

**Blunt verdict: No, not for the heavy stack.**

| Goal | Can you avoid Linux? | Reality |
|---|---|---|
| Simple single-GPU Ollama/llama.cpp serving | **Yes** | 100% native Windows viable, well-supported |
| vLLM with production batching | **Partial** | Community fork (single-GPU only); or WSL2 (= Linux) |
| vLLM with multi-GPU tensor parallelism | **No** | No NCCL on native Windows. WSL2 required. |
| SGLang | **No** | No native Windows support. WSL2 only. |
| Docker-based stacks | **Technically yes** | Docker Desktop on Windows uses WSL2 backend anyway |

The ceiling of staying 100% native Windows:
- **Ollama or LM Studio daemon:** Works well. OpenAI-compatible API. Single GPU VRAM limit. No true TP. Concurrency capped at ~4–8 parallel requests before degradation.
- **llama.cpp:** Works well. GGUF quantized models. Basic multi-GPU layer splitting. No NCCL.
- **Native vLLM fork:** Single-GPU only (aivrar build). Multi-GPU workaround exists (devnen/SystemPanic) but CPU-relay TP is a workaround, not real NCCL, and performance impact is unquantified.

For DeepSeek V4-Flash at 284B parameters, a single-GPU Ollama/llama.cpp path is feasible if the GPU has enough VRAM (80GB for FP16; ~2×24GB for Q4 GGUF). But for serious throughput — continuous batching, RadixAttention, expert parallelism, true TP — you end up in WSL2, which is Linux.

**"Using WSL2" does not mean "learning Linux"** in the sysadmin sense. WSL2 installs with a few PowerShell commands. Ollama, vLLM, and Docker inside WSL2 behave identically to Linux. The user never needs to touch boot loaders, partitioning, or kernel configs. But it does mean the server process runs inside a Linux environment, and the user will see Ubuntu (or Debian) prompts.

Source: [WSL2 for Local AI Complete Guide, InsiderLLM](https://insiderllm.com/guides/wsl2-local-ai-windows-guide/)
Source: [vLLM on Windows in 2026, fazm.ai](https://fazm.ai/t/vllm-windows-support-2026)

**Confidence: High.**

---

## Q4. 24/7 Headless Reliability on Windows

### Windows Update / Auto-Reboot

This is the **primary reliability risk** for a 24/7 headless Windows inference server.

- Windows Update **will attempt automatic reboots** on consumer Windows 11. This can kill a running inference job or bring down the API endpoint.
- Mitigations available:
  - Group Policy: "No auto-restart with logged-on users for scheduled automatic updates" — prevents reboots while any session is active.
  - Registry key: `NoAutoRebootWithLoggedOnUsers = 1` in `HKLM\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU`.
  - Task Scheduler: Disable the `Reboot` task under `Microsoft > Windows > UpdateOrchestrator`.
  - Services: Set Windows Update service to "Manual" start.
  - Source: [How to disable Windows auto update, Microsoft Q&A](https://learn.microsoft.com/en-us/answers/questions/5550379/how-can-i-disable-windows-automatic-updating)
- **None of these are permanent** — Windows can re-enable them via major feature updates or policy resets.
- **Real incident (April 2026):** Windows Server 2025 entered repeated reboot cycles caused by LSASS crashes from a Patch Tuesday update. An emergency out-of-band fix (KB5091157) was required.
  - Source: [KB5091157 April 2026 Out-of-Band Fix, Windows Forum](https://windowsforum.com/threads/kb5091157-april-2026-out-of-band-fix-for-windows-server-2025-reboot-loops.414371/)
  - Source: [Windows Server 2025 Cumulative Update Stuck Pending Reboot, ProgressiveRobot (May 2026)](https://www.progressiverobot.com/2026/05/19/windows-server-2025-cumulative-update-stuck-pending-reboot-fix-prevention/)
- **Honest assessment:** Windows Update is a genuine ongoing management burden for a headless inference server. It requires periodic attention that Linux's `unattended-upgrades` with `NeedsRestart` control handles more gracefully.

### Running Headless (No Display)

- Ollama can run as a background service via **NSSM** (Non-Sucking Service Manager) or **AlwaysUp** (commercial, ~$30). Service runs in Session 0.
  - Source: [How to Run Ollama as a Windows Service, CoreTechnologies](https://www.coretechnologies.com/products/AlwaysUp/Apps/OllamaWindowsService.html)
- **Session 0 / CUDA concern:** Historically, CUDA could not run in Windows Session 0 (headless service mode) under WDDM. As of NVIDIA driver r361.75+, this limitation was removed for WDDM-mode GeForce/Quadro GPUs. Confirmation needed for specific driver version.
  - Source: [NVIDIA Developer Forums — CUDA services with WDDM](https://forums.developer.nvidia.com/t/we-are-able-to-runing-cuda-service-with-wddm/41461)
- **Practical reality:** Multiple GitHub issues show Ollama on Windows failing GPU detection after version updates or driver changes. The root cause is typically installer-time CUDA detection — if CUDA drivers aren't present at install time, reinstallation is required.
  - Source: [Ollama does not detect GPU (Windows 11, WDDM), GitHub issue #13593](https://github.com/ollama/ollama/issues/13593)
  - Source: [Ollama Not Using GPU: Complete Fix Guide, InsiderLLM](https://insiderllm.com/guides/ollama-not-using-gpu-fix/)
- **Auto-login for headless:** Windows 11 supports auto-login via `netplwiz` or registry, but this creates a security exposure and is not recommended best practice. Alternatively, the service approach (NSSM) does not require auto-login.

### Licensing
- Windows 11 Home/Pro: No server licensing restrictions for personal use. Running an HTTP inference API on a home network is fine.
- No CAL (Client Access License) concerns for personal Tailscale+SSH access.

### Honest comparison
- **Linux:** `systemd` service; process survives reboots and restarts automatically; update reboots controlled precisely via `needrestart`; no GUI overhead (Ubuntu Server is headless by default).
- **Windows:** Requires third-party service wrapper (NSSM); Windows Update is an ongoing management burden; GUI overhead consumes ~1–2 GB RAM even without a display connected; background services can lose GPU context after certain driver updates.

**Confidence: Medium-High** — reliability facts grounded in documented incidents; CUDA Session 0 limitation based on driver forum posts which lack official documentation confirmation.

---

## Q5. Remote Orchestration from Mac over Tailscale

### SSH
- **OpenSSH Server is built into Windows 11** (optional feature, pre-installed on Windows Server 2025). Enable via Settings > Optional Features, or `Add-WindowsCapability -Online -Name OpenSSH.Server`.
  - Source: [Get started with OpenSSH Server for Windows, Microsoft Learn](https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh_install_firstuse)
  - Source: [Configure SSH Server on Windows Server 2025, Microsoft TechCommunity (Feb 2026)](https://techcommunity.microsoft.com/blog/itopstalkblog/configure-ssh-server-on-windows-server-2025/4419325)
- Key-based auth works (copy public key to `~/.ssh/authorized_keys` on the Windows box). Default shell can be set to PowerShell.
- **Firewall:** Must manually add inbound rule for port 22 — no automatic rule created.
- **Mac → Windows SSH over Tailscale:** Works natively. Mac `ssh user@windows-tailscale-ip` connects to the Windows OpenSSH server. Tailscale handles NAT traversal; no port forwarding needed.
- The Mac can then use SSH tunneling to forward the Windows inference port (e.g., `ssh -L 11434:localhost:11434 user@windows-box`) so Claude Code on Mac sends requests to local port 11434, which proxies through to Windows Ollama.

### Exposing the Inference Endpoint
- Ollama on Windows binds to `127.0.0.1:11434` by default. Set `OLLAMA_HOST=0.0.0.0:11434` environment variable to bind to all interfaces, then it's reachable at the Tailscale IP directly (no tunneling needed).
- LiteLLM or claude-code-router on the Mac can then point `ANTHROPIC_BASE_URL` directly at `http://windows-tailscale-ip:11434`.

### Wake-on-LAN
- WoL works on Windows with a supported NIC. Enable in BIOS ("Wake on LAN" / "Power on by PCI-E") and Windows Device Manager (NIC > Power Management > "Allow this device to wake the computer").
- **Tailscale + WoL:** Tailscale does not natively send WoL magic packets. The recommended pattern is a lightweight always-on device (Raspberry Pi, or the Mac itself if wired) that forwards WoL packets. Community tools: `andygrundman/tailscale-wakeonlan` Docker container, UpSnap.
  - Source: [Making a Wake-on-LAN server using Tailscale, UpSnap, and Raspberry Pi, Tailscale Blog](https://tailscale.com/blog/wake-on-lan-tailscale-upsnap)
- **Simpler path for Artemis:** If the Windows box runs 24/7 (no sleep/hibernate), WoL is irrelevant. For a box that sleeps when idle, the Mac Mini itself can send the WoL packet over the local LAN.

### RDP
- RDP works for interactive GUI access from Mac (use Microsoft Remote Desktop app). Not required for inference server operation but useful for maintenance/troubleshooting.

**Confidence: High** — all components (OpenSSH, WoL, Tailscale) are well-documented with official sources.

---

## Q6. Claude Code / Anthropic-API Backend on Windows

### The Stack
Claude Code requires an Anthropic-format API. Local Windows inference servers expose OpenAI-format APIs. Two translation approaches:

**Option A: LiteLLM proxy (Mac-side)**
- LiteLLM runs on the Mac, accepts Anthropic-format requests from Claude Code, translates to OpenAI-format, forwards to Windows Ollama/vLLM.
- `ANTHROPIC_BASE_URL=http://localhost:4000` on Mac; LiteLLM config points `anthropic/claude-*` → `openai/localhost:11434`.
  - Source: [Run Claude Code with local agents using LiteLLM and Ollama, Medium](https://medium.com/@kamilmatejuk/run-claude-code-with-local-agents-using-litellm-and-ollama-ab88869cbd00)
  - Source: [Claude Code Quickstart, LiteLLM Docs](https://docs.litellm.ai/docs/tutorials/claude_responses_api)

**Option B: claude-code-router (npm, Mac-side)**
- Simpler setup for this specific use case. npm install, edit config.json, routes Claude Code requests to Ollama.
  - Source: [Claude Code Router, DEV Community](https://dev.to/stevengonsalvez/claude-code-router-use-any-model-with-claude-codes-interface-c6a)

**Option C: Ollama direct (Ollama v0.14.0+ only)**
- Ollama v0.14.0+ supports native Anthropic Messages API. Point `ANTHROPIC_BASE_URL=http://windows-box:11434` and Claude Code connects directly — no shim required.
  - Source: [Running Claude Code Locally with Ollama, n1n.ai (January 2026)](https://explore.n1n.ai/blog/running-claude-code-locally-with-ollama-and-litellm-2026-01-25)

### Agentic/Tool-Use Quality
This is the most important quality dimension for the APEX coding workflow:

- **DeepSeek V3/V4:** Switches from Claude Opus 4.6 to DeepSeek V3.2 cuts output token cost ~95%. However: "DeepSeek and Gemini have partial support — simple tool calls work, but complex chains can fail."
  - Source: [Cut Claude Code Bill 90%: OpenRouter, Ollama, LiteLLM, Techsy.io](https://techsy.io/en/blog/claude-code-use-different-models)
- **Qwen3 Coder:** Requires `--enable-auto-tool-choice` and `--tool-call-parser qwen3_coder` flags in vLLM for agentic use. "Writes decent code but struggles with complex tool chains."
- **General local model quality:** "Local models show lower accuracy on complex multi-step agentic tasks, less reliable tool calling, and more hallucinated file paths."
  - Source: [Claude Code with Other LLMs Guide 2026, Morph](https://www.morphllm.com/use-different-llm-claude-code)
- **Real test (LiteLLM + Ollama):** Testing with file-counting agentic task — Qwen 3.5 9B performed adequately; many models failed to use Bash tool correctly.
  - Source: [Run Claude Code with local agents using LiteLLM and Ollama, Medium](https://medium.com/@kamilmatejuk/run-claude-code-with-local-agents-using-litellm-and-ollama-ab88869cbd00)

**Windows-specific consideration:** LiteLLM and claude-code-router run on the **Mac orchestrator**, not Windows. The Windows box only serves the raw OpenAI-format inference API. No Windows-specific complications for the translation layer.

**Confidence: Medium** — tool-use quality reports are model-dependent and evolve rapidly; DeepSeek V4-Flash specifically is too new for stable quality assessments.

---

## Q7. Real-World Write-Ups: Windows GPU Box as Headless LLM Server

### Documented experiences

**1. Dev.to home lab write-up (RTX 4090, Pop!_OS → Linux, June 2026)**
The author ran a home GPU server for 7+ months. Explicitly chose Linux (Pop!_OS) for NVIDIA driver reliability. Achieved stable 24/7 headless operation with systemd, Tailscale for remote access, VS Code Remote SSH. No Windows alternative was evaluated; Windows was dismissed implicitly due to NVIDIA driver stability and containerization concerns.
- Source: [Building My AI Home Lab: From Laptop to Dedicated Server, Pedro Alonso](https://www.pedroalonso.net/blog/ai-home-lab-setup/)

**2. Home AI Server Build Guide 2026 (Compute Market)**
Recommends Ubuntu Server 24.04 LTS as the OS — "lightweight, headless by default, well-supported by NVIDIA drivers." Windows is not mentioned as an alternative. The omission is telling.
- Source: [Home AI Server Build Guide 2026, Compute Market](https://www.compute-market.com/blog/home-ai-server-build-guide-2026)

**3. LM Studio remote headless setup (2026 guide)**
Documents connecting LM Studio headless daemon on a Windows machine to remote clients. Specifically notes llmster daemon runs on Windows. Practical pattern for Windows users who want GUI-adjacent tooling.
- Source: [How to Connect LM Studio to a Remote Server, QuantizeLab 2026](https://www.quantizelab.dev/articles/how-to-connect-lm-studio-to-a-remote-server-headless-guide)

**4. WSL2 + vLLM write-up (InsiderLLM 2025)**
Comprehensive guide documenting WSL2 as a viable production path on Windows. Confirms 90–100% of native Linux inference performance for GPU-bound workloads. The "Windows user avoids Linux" framing is accurate for user-facing experience, even if the underlying execution is Linux.
- Source: [WSL2 for Local AI: The Complete Windows Setup Guide, InsiderLLM](https://insiderllm.com/guides/wsl2-local-ai-windows-guide/)

**5. Bridging Windows Ollama from WSL (Roman Klis, Medium)**
Documents the inverse: running Ollama natively on Windows and accessing it from WSL for development. Shows Windows Ollama GPU mode works reliably for developer workflows.
- Source: [Bridging the Gap: Running Windows Ollama on GPU, Medium](https://medium.com/@romanklis/bridging-the-gap-running-windows-ollama-on-gpu-accessed-flawlessly-from-wsl-bd9d27462e33)

**6. Self-hosting on RTX 5060 (TechFuel HQ, 2026)**
Documents the full headless setup: Ollama as Windows service, NSSM wrapper, KEEP_ALIVE settings, GPU driver version requirements (575+). Single-GPU inference.
- Source: [How to Self-Host a Local LLM on a Single RTX 5060 in 2026, TechFuelHQ](https://techfuelhq.com/tutorials/self-host-local-llm-rtx-5060-2026/)

**Pattern across all sources:** Experienced home lab operators choose Linux for the inference box. Windows appears in "getting started" guides and developer laptop use cases. The closest match to "production headless Windows GPU inference server" is the LM Studio headless + Ollama service pattern — documented but not widely written up in home lab contexts.

**Confidence: Medium** — limited direct "Windows GPU box as headless server" real-world narratives; most narratives are Linux-side.

---

## Q8. Honest Verdict: Windows as Home Inference Appliance

### When Windows makes sense

1. **Owner knows Windows and that's the only GPU rig they have.** No forced OS migration needed.
2. **Single-GPU box, moderate model size (fits in one GPU's VRAM).** Ollama + NSSM service works reliably.
3. **Agentic coding workflow, single user, no concurrency.** Ollama single-user throughput is adequate. DeepSeek V4-Flash at GGUF quantization fits this profile.
4. **Dev/prototyping use.** LM Studio daemon or Ollama, low operational overhead, easy model switching.
5. **WSL2 is acceptable.** If the owner is willing to run WSL2, they get full vLLM capability with minimal Linux surface — install Ubuntu once, never open it again unless something breaks.

### When Windows does NOT make sense

1. **Need serious multi-GPU tensor parallelism (2×, 4× GPU for large model).** Native Windows has no NCCL. WSL2 required. Community fork multi-GPU is experimental.
2. **Need maximum concurrency/batching throughput.** vLLM's continuous batching under WSL2 beats Ollama native by 2× at 8+ concurrent requests.
3. **Need FlashAttention 3/4, FlashInfer, FP8 quantization.** Not available in native Windows vLLM forks.
4. **Want a "set it and forget it" server with minimal maintenance.** Windows Update is an ongoing risk; Linux systemd + unattended-upgrades is lower overhead.
5. **Need SGLang.** Not available natively on Windows.

### Realistic assessment for Artemis topology
- **DeepSeek V4-Flash (284B MoE, 13B active):** At Q4 quantization (~140–160 GB model weight / 13B active weight per forward pass), this can run on a multi-GPU consumer rig. Native Windows + Ollama will work for single-stream agentic coding tasks but hits a ceiling.
- **The 90% solution:** WSL2 + Ollama (inside WSL2 or native Windows Ollama) covers the Artemis single-user coding agent workload. The user interacts with Windows normally; the inference server runs silently.
- **The 100% solution:** WSL2 + vLLM (inside WSL2) gives full Linux-grade throughput while Windows stays the user-facing OS. This requires ~20 min of WSL2 setup once, then it's transparent.
- **Hard ceiling of staying native Windows:** Large quantized models, single-GPU serving, Ollama-grade concurrency. Fine for Artemis today; may constrain future scaling.

### Reliability gap vs Linux/macOS
- Linux: `systemd`, no forced reboots, driver stability well-understood, 24/7 server use is the primary design target.
- macOS: GPU constraints (no CUDA), but extremely stable for background services.
- Windows: Windows Update reboots are the biggest risk. Manageable with Group Policy but not zero-risk. LSASS/NCCL issues documented (April 2026 incident). Not designed for headless server operation — every quality-of-life improvement requires third-party tools (NSSM, WoL utilities, auto-login workarounds).

**Net verdict:** For a Windows user who does not want to learn Linux, the practical path is: **Windows 11 + WSL2 + Ollama/vLLM inside WSL2**, managed from the Windows side. This gives Linux-grade inference capability while keeping the user-facing environment entirely Windows. The "avoid Linux" goal is achievable in the sense that the user never runs a Linux desktop or manages Linux at a sysadmin level — but the inference process does run inside a Linux kernel. If that is acceptable, Windows is a legitimate topology choice. If the owner truly wants zero Linux at any layer, the native Ollama path works well for single-GPU single-user workloads, with the understanding that multi-GPU TP and high-concurrency batching are off the table.

**Confidence: High** — verdict synthesized from multiple corroborating sources across all eight question areas.

---

## Source Index

| Source | Date | URL |
|---|---|---|
| vLLM on Windows in 2026 (fazm.ai) | 2026 | https://fazm.ai/t/vllm-windows-support-2026 |
| aivrar/vllm-windows-build (GitHub) | 2026 | https://github.com/aivrar/vllm-windows-build |
| devnen/vllm-windows (GitHub) | 2026 | https://github.com/devnen/vllm-windows |
| WSL2 for Local AI Complete Guide (InsiderLLM) | 2025–2026 | https://insiderllm.com/guides/wsl2-local-ai-windows-guide/ |
| Running LLMs on Windows: Native vLLM vs WSL vs llama.cpp (DEV Community) | 2025–2026 | https://dev.to/alanwest/running-llms-on-windows-native-vllm-vs-wsl-vs-llamacpp-compared-37a9 |
| Running LLMs on Windows (Hashnode mirror) | 2025–2026 | https://alan-west.hashnode.dev/running-llms-on-windows-native-vllm-vs-wsl-vs-llamacpp-compared |
| Ollama vs vLLM Deep Dive (Red Hat Developer) | August 2025 | https://developers.redhat.com/articles/2025/08/08/ollama-vs-vllm-deep-dive-performance-benchmarking |
| Ollama vs. vLLM: Why Ollama Is Slow for Multiple Users (Arsturn) | 2025–2026 | https://www.arsturn.com/blog/ollama-vs-homl-the-real-reason-ollama-is-slower-for-multiple-users |
| Ollama on Windows 11: Native App vs. WSL (Windows Forum) | 2025–2026 | https://windowsforum.com/threads/ollama-on-windows-11-native-app-vs-wsl-for-local-llms.379552/ |
| RFC: vLLM Windows CUDA support (GitHub issue #14981) | 2025–2026 | https://github.com/vllm-project/vllm/issues/14981 |
| CUDA on WSL User Guide (NVIDIA Docs) | Current | https://docs.nvidia.com/cuda/wsl-user-guide/index.html |
| Run Ollama as a Windows Service (AlwaysUp/CoreTechnologies) | 2025–2026 | https://www.coretechnologies.com/products/AlwaysUp/Apps/OllamaWindowsService.html |
| Ollama does not detect GPU – WDDM (GitHub issue #13593) | 2025–2026 | https://github.com/ollama/ollama/issues/13593 |
| Ollama Not Using GPU Fix (InsiderLLM) | 2026 | https://insiderllm.com/guides/ollama-not-using-gpu-fix/ |
| CUDA services with WDDM (NVIDIA Developer Forums) | 2016, still current | https://forums.developer.nvidia.com/t/we-are-able-to-runing-cuda-service-with-wddm/41461 |
| KB5091157 April 2026 reboot loop fix (Windows Forum) | April 2026 | https://windowsforum.com/threads/kb5091157-april-2026-out-of-band-fix-for-windows-server-2025-reboot-loops.414371/ |
| Windows Server 2025 update pending reboot (ProgressiveRobot) | May 2026 | https://www.progressiverobot.com/2026/05/19/windows-server-2025-cumulative-update-stuck-pending-reboot-fix-prevention/ |
| How to disable Windows auto update (Microsoft Q&A) | 2025–2026 | https://learn.microsoft.com/en-us/answers/questions/5550379/how-can-i-disable-windows-automatic-updating |
| Get started with OpenSSH Server for Windows (Microsoft Learn) | Current | https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh_install_firstuse |
| Configure SSH Server on Windows Server 2025 (TechCommunity) | 2025–2026 | https://techcommunity.microsoft.com/blog/itopstalkblog/configure-ssh-server-on-windows-server-2025/4419325 |
| Making a Wake-on-LAN server using Tailscale + UpSnap (Tailscale Blog) | 2025–2026 | https://tailscale.com/blog/wake-on-lan-tailscale-upsnap |
| Run Claude Code with LiteLLM and Ollama (Medium) | 2025–2026 | https://medium.com/@kamilmatejuk/run-claude-code-with-local-agents-using-litellm-and-ollama-ab88869cbd00 |
| Running Claude Code Locally with Ollama (n1n.ai) | January 2026 | https://explore.n1n.ai/blog/running-claude-code-locally-with-ollama-and-litellm-2026-01-25 |
| Claude Code Router (DEV Community) | 2025–2026 | https://dev.to/stevengonsalvez/claude-code-router-use-any-model-with-claude-codes-interface-c6a |
| Cut Claude Code Bill 90% with Ollama/LiteLLM (Techsy.io) | 2025–2026 | https://techsy.io/en/blog/claude-code-use-different-models |
| Claude Code with Other LLMs Guide 2026 (Morph) | 2026 | https://www.morphllm.com/use-different-llm-claude-code |
| Building My AI Home Lab (Pedro Alonso) | June 2026 | https://www.pedroalonso.net/blog/ai-home-lab-setup/ |
| Home AI Server Build Guide 2026 (Compute Market) | 2026 | https://www.compute-market.com/blog/home-ai-server-build-guide-2026 |
| How to Connect LM Studio to Remote Server (QuantizeLab 2026) | 2026 | https://www.quantizelab.dev/articles/how-to-connect-lm-studio-to-a-remote-server-headless-guide |
| How to Self-Host Local LLM on RTX 5060 (TechFuelHQ 2026) | 2026 | https://techfuelhq.com/tutorials/self-host-local-llm-rtx-5060-2026/ |
| Bridging Windows Ollama from WSL (Roman Klis, Medium) | 2025–2026 | https://medium.com/@romanklis/bridging-the-gap-running-windows-ollama-on-gpu-accessed-flawlessly-from-wsl-bd9d27462e33 |
| LM Studio Headless Docs (lmstudio.ai) | Current | https://lmstudio.ai/docs/advanced/headless |
| LM Studio 0.4 Headless Deployment (SitePoint) | 2025–2026 | https://www.sitepoint.com/lm-studio-04-headless-deployment-local-llm-apis-without-the-gui/ |
| DeepSeek V4 deployment guide (Clore.ai) | 2026 | https://docs.clore.ai/guides/language-models/deepseek-v4 |
| andygrundman/tailscale-wakeonlan (GitHub) | 2025–2026 | https://github.com/andygrundman/tailscale-wakeonlan |
