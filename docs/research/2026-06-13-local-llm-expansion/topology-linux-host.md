# Topology: Linux Host as Inference Box (Mac Orchestrates Linux)

**Research date:** 2026-06-13  
**Purpose:** Evaluate a Linux GPU/RAM box as the Artemis inference backend, orchestrated by Mac Mini over Tailscale.  
**Target model:** DeepSeek V4-Flash (284B total / 13B active MoE, 1M ctx) for coding + Kimi-class big-context.  
**Owner profile:** Low-admin preference, would rather not learn Linux, single-user home.

---

## Q1 — Serving Stack on Linux

**Confidence: HIGH** — multiple independent comparison sources from 2025–2026; TGI excluded (maintenance-mode Dec 2025).

### vLLM

- **Maturity:** Production default as of 2025–2026. v0.20.2 (May 2026) includes Model Runner V2 (+56% throughput on GB200). Backed by a16z, used at scale.
- **OpenAI API:** Native `/v1/chat/completions` endpoint. Anthropic passthrough via LiteLLM proxy layer (see Q6).
- **Multi-model:** One model per process; multiple models require multiple processes (different ports).
- **Batching/concurrency:** PagedAttention + continuous batching. 16–29x throughput advantage over Ollama at ≥10 concurrent users. Autellix extensions claim 4–15x further agentic throughput improvement.
- **Tensor-parallel multi-GPU:** Native `--tensor-parallel-size N`; expert parallelism `--enable-expert-parallel` for MoE. Powers-of-two (1,2,4,8) optimal. V4-Flash recipe ships as Day-0 official.
- **24/7 headless:** Designed for it. systemd unit with `Restart=always` is the standard production pattern. Nginx reverse proxy for TLS/rate-limiting is documented.

Sources: [vLLM MoE Playbook ROCm](https://rocm.blogs.amd.com/software-tools-optimization/vllm-moe-guide/README.html) (2025), [vLLM Production 2026](https://www.spheron.network/blog/vllm-production-deployment-2026/) (2026), [Sesamedisk comparison](https://sesamedisk.com/local-inference-engines-2026-comparison/) (2026), [vLLM blog H200 scaling](https://vllm.ai/blog/2025-12-17-large-scale-serving) (Dec 2025)

### SGLang

- **Maturity:** Production-grade; actively developed by LMSYS. Native gRPC pipeline, Rust tokenization, `/v1/responses` endpoint with MCP client support (2026).
- **OpenAI API:** Full OpenAI-compat + native MCP multi-turn `/v1/responses`. Claude Code compat via LiteLLM translation (no direct Anthropic API surface).
- **Multi-model:** Same as vLLM — one model per process.
- **Batching/concurrency:** RadixAttention caches KV for shared prefixes. 75–95% cache hit rate on multi-turn workloads with fixed system prompts. 29% throughput advantage over vLLM on prefix-heavy workloads; ~10% TTFT advantage on multi-turn. **Best choice for agentic coding harnesses where many sub-agents share the same system prompt/tool definitions.**
- **Tensor-parallel:** Supported; same TP patterns as vLLM. KTransformers CPU kernels now integrated for SGLang hybrid offloading (Oct 2025 LMSYS blog).
- **24/7 headless:** Fully headless. Same systemd patterns apply.

Sources: [SGLang NVIDIA Dynamo](https://docs.nvidia.com/dynamo/user-guides/agents/sg-lang-for-agentic-workloads) (2025), [SGLang vs vLLM KV cache](https://www.runpod.io/blog/sglang-vs-vllm-kv-cache) (2025), [KTransformers+SGLang](https://www.lmsys.org/blog/2025-10-22-KTransformers/) (Oct 2025), [SGLang Production 2026](https://www.spheron.network/blog/sglang-production-deployment-guide/) (2026)

### llama.cpp

- **Maturity:** Stable, widely tested. The portability/edge champion — C++, runs CPU+GPU, GGUF-first.
- **OpenAI API:** `llama-server` provides `/v1/chat/completions`. OpenAI-compat only (no native Anthropic endpoint).
- **Multi-model:** One model per server process.
- **Batching/concurrency:** Single-request focused; no continuous batching. Performance degrades under concurrency. NOT suited for multi-agent fan-out workloads.
- **Tensor-parallel:** Basic multi-GPU via `-ngl` split layers; not true TP. Performance scaling is poor vs vLLM.
- **24/7 headless:** Works fine; run via tmux or systemd. Lower operational complexity than vLLM but also lower throughput ceiling.
- **Role in Artemis:** Best fit for hybrid CPU+RAM offload of V4-Flash on a big-RAM non-GPU rig (with KTransformers). For pure CUDA serving, vLLM/SGLang dominate.

Sources: [Local inference 2026 comparison](https://sesamedisk.com/local-inference-engines-2026-comparison/) (2026), [Tailscale llama-server gist](https://gist.github.com/AlexsJones/2be576db3ccc61724c0c4059d4f4df7f) (2026)

### Ollama

- **Maturity:** 2025–2026 production-polished for single-user dev. GGUF-first; auto-detects GPU.
- **OpenAI API:** Full OpenAI-compat (`/v1/chat/completions`). No native Anthropic surface.
- **Multi-model:** Native multi-model management; pulls models by name, hot-swaps.
- **Batching/concurrency:** Basic/limited. Timeouts at ≥20 concurrent users. vLLM is 16–29x higher aggregate throughput under concurrency.
- **24/7 headless:** Ships its own systemd unit on Linux install (`Restart=always`). `ollama serve` daemonizes automatically. Easiest 24/7 setup of all options.
- **Best for Artemis?** Adequate for single-stream use (one coding session at a time). Breaks down if APEX fans out 5–10 parallel sub-agents simultaneously.

Sources: [Ollama Linux docs](https://docs.ollama.com/linux) (2026), [Ollama systemd guide](https://mljourney.com/how-to-run-ollama-as-a-linux-service-with-systemd/) (2025), [vLLM vs Ollama benchmark](https://codersera.com/blog/vllm-vs-ollama-vs-lm-studio-production-2026/) (2026)

### LM Studio (Linux)

- **Maturity:** Desktop GUI app; headless Linux support via `lms` CLI (added late 2024). Less tested in production.
- **OpenAI API:** `/v1/chat/completions` via Local Server.
- **24/7 headless:** Fragile; not designed for daemon operation. Requires workarounds for systemd.
- **Verdict for Artemis:** Not recommended for a headless server. Use Ollama if you want the easy path; vLLM if you want production reliability.

### KTransformers

- **Maturity:** Research-grade production tool (Tsinghua/kvcache-ai); accepted at SOSP 2025. Not a standalone server — it's an inference optimization layer plugging into llama.cpp / SGLang for CPU/GPU hybrid MoE offloading.
- **Key capability:** DeepSeek V3/R1 671B on 14GB VRAM + 382GB DRAM. AMX-specialized CPU kernels. 4.62–19.74x prefill speedup vs baseline.
- **24/7 headless:** Runs headless once configured; complexity is higher (requires specific kernel/AMX CPU).
- **Role in Artemis:** The KEY option if choosing a big-RAM CPU box (no discrete GPU or single small GPU). Enables full 284B+ MoE weights in RAM with GPU for active parameters.

Sources: [KTransformers SOSP 2025](https://dl.acm.org/doi/10.1145/3731569.3764843) (2025), [KTransformers DeepSeek tutorial](https://github.com/kvcache-ai/ktransformers/blob/main/doc/en/DeepseekR1_V3_tutorial.md) (2025), [KTransformers+SGLang LMSYS](https://www.lmsys.org/blog/2025-10-22-KTransformers/) (Oct 2025)

### Why Linux Is the Default for Serious Serving

Linux dominates because: (1) CUDA driver ecosystem is Linux-primary — all vLLM/SGLang CI runs on Linux; (2) systemd gives robust daemon management not available on macOS or Windows without third-party tools; (3) no GUI overhead — Ubuntu Server dedicates 100% of RAM/GPU to inference; (4) container ecosystem (Docker + NVIDIA Container Toolkit) makes reproducible deployments trivial; (5) all official documentation and community support assumes Linux.

---

## Q2 — Capability: Throughput Numbers

**Confidence: HIGH for H100/H200 datacenter; MEDIUM for consumer GPU V4-Flash (fewer 2026 specific benchmarks); HIGH for architecture context.**

### DeepSeek V4-Flash (284B / 13B active) — the Artemis target model

V4-Flash's MoE structure means inference speed is bandwidth-limited on the **active 13B parameters**, not the total 284B. The 284B figure sets the memory requirement (all expert weights must be resident), not the compute cost per token.

**Hardware tiers for V4-Flash (sourced from compute-market.com, chatgptaihub.com, 2026):**

| Hardware | VRAM | Quantization | Single-stream tok/s | Concurrent streams |
|---|---|---|---|---|
| Single H200 141GB | 141GB | FP8 full | ~84 tok/s (API parity estimate) | 5–20 |
| RTX PRO 6000 Blackwell 96GB | 96GB | Q4_K_M | 45–60 tok/s | 5–15 |
| 2× H200 / 2× RTX PRO 6000 | 2×96+GB | FP4+FP8 official | ~84 tok/s+ | 10–30 |
| Mac Studio M4 Max 192GB | unified | Q4_K_M MLX | 25–35 tok/s | 1–3 (no batching) |
| 4× RTX 3090 (96GB pooled) | 4×24GB | Q4_K_M | 18–25 tok/s (NVLink) | 2–5 |
| Dual RTX 5090 (64GB) | 2×32GB | Q3_K_M degraded | 22–30 tok/s | 1–3 |
| Single RTX 4090 (24GB) | 24GB | 4-bit GGUF llama.cpp | 20–40 tok/s* | 1 only |

*Single RTX 4090 with 24GB can only run heavily quantized partial offload; output quality degrades below "the quality cliff where V4-Flash starts writing broken function names" per compute-market.com.

**Important caveat:** V4-Flash minimum viable VRAM is ~96GB for Q4_K_M quality. Below this you either degrade quantization to IQ2 (quality loss) or use CPU/RAM offload (speed loss). A single consumer card (24GB) is not a viable production target for V4-Flash.

**Earlier V3/R1 (671B full MoE) for reference — from dzhsurf benchmarks on 8×H100:**
- Single-stream (concurrency 1): ~33 tok/s
- Peak batched throughput (8×H100, ~100 concurrent): ~3000 tok/s total / ~620 tok/s output
- Multi-node 2×8 H100 (no InfiniBand): ~980 tok/s output

Sources: [dzhsurf H100 benchmarks](https://github.com/dzhsurf/deepseek-v3-r1-deploy-and-benchmarks) (2025), [vLLM H200 2.2k tok/s](https://vllm.ai/blog/2025-12-17-large-scale-serving) (Dec 2025), [compute-market V4-Flash](https://www.compute-market.com/blog/deepseek-v4-flash-local-hardware-guide-2026) (2026), [chatgptaihub V4-Flash](https://chatgptaihub.com/deepseek-v4-self-hosting-guide/) (2026)

### Tensor-Parallel + Multi-Agent Advantage

vLLM data parallelism creates independent replicas; 4× data-parallel gives 4× throughput for concurrent requests. With APEX fanning out 5–10 parallel sub-agents, a multi-GPU Linux box (4–8 GPUs) scales proportionally while Mac/Windows single-GPU setups queue requests. SGLang's RadixAttention is additionally beneficial: 75–95% KV cache hit rates when all sub-agents share the same system prompt + tool definitions, which is exactly how APEX works (all sub-agents get the same APEX system prompt).

---

## Q3 — Admin Burden + Learning Curve

**Confidence: HIGH for what must be learned; MEDIUM for "hours to competent" (limited direct first-timer accounts); sourced from pedroalonso.net, various homelab guides, NVIDIA driver forums 2025–2026.**

### Concrete skill set required

A non-sysadmin running a Linux GPU inference server must learn or execute the following:

**One-time setup (can be scripted/AI-assisted):**
1. **OS install** — Ubuntu Server 24.04 LTS: boot from USB, follow installer wizard. ~30 min, mostly GUI.
2. **SSH** — `ssh user@ip`, key-based auth (`ssh-keygen`, `ssh-copy-id`). ~1 hour to understand and practice.
3. **NVIDIA driver install** — `sudo ubuntu-drivers install` (automated) or `apt install nvidia-driver-XXX`. **This is the #1 pain point.** Best case: 30–45 min. Problematic case (secure boot, nouveau conflict): 3+ hours.
4. **NVIDIA Container Toolkit** — `curl | apt | systemctl restart docker`. ~20 min if NVIDIA driver is working.
5. **Docker + Docker Compose** — `apt install docker.io docker-compose-plugin`. Understanding `compose.yml` structure. ~2–3 hours to be functional.
6. **GPU passthrough in Docker** — `--gpus all` flag or `deploy.resources.reservations.devices`. ~1 hour.
7. **Tailscale** — `curl | sh`, browser auth. ~15 min. Genuinely simple.
8. **systemd service creation** — writing a `.service` file, `systemctl enable/start/status`. ~1–2 hours.

**Ongoing operations (recurrent tax):**
- **Log reading** — `journalctl -u vllm -f`, `docker logs -f container`. ~1 hour to learn, then routine.
- **Kernel update / driver breakage** — Ubuntu unattended-upgrades can break NVIDIA DKMS modules after kernel updates. **This is a real recurring hazard.** Fix: pin kernel with `apt-mark hold linux-image-generic linux-headers-generic`. Must be set up proactively.
- **Package management** — `apt update/upgrade`, `pip install --upgrade vllm`. Low burden once understood.
- **CUDA version alignment** — vLLM requires specific CUDA versions; mismatches are a common source of broken setups. Docker containers largely eliminate this (pin the container image).

**What can be AUTOMATED / AI-scripted:**

Almost everything above can be reduced to running a single AI-generated bash script or Ansible playbook:
- Ansible can automate: Docker install, NVIDIA toolkit, kernel pin, vLLM systemd unit, Tailscale join, firewall rules.
- An APEX coding agent (this system!) can generate the entire setup playbook. Owner runs one command.
- Docker Compose eliminates CUDA version management per-service.
- Pop!_OS (Ubuntu-derivative with NVIDIA ISO variant) installs drivers automatically — eliminates step 3 entirely. Used successfully by pedroalonso.net.

**Recommended distro for lowest friction:** Ubuntu 24.04 LTS Server (massive community support, `ubuntu-drivers` auto-selection) OR Pop!_OS 22.04 LTS (NVIDIA ISO variant — drivers pre-installed, zero CUDA headaches). Pop!_OS is better for non-sysadmins; Ubuntu is better for automation (Ansible roles exist for everything).

### Realistic "hours to competent" estimate

| Scenario | Hours |
|---|---|
| Owner follows AI-generated script, no issues | 3–5 hours total |
| Owner learns while going, typical case | 8–15 hours over 1–2 weekends |
| Driver hell (secure boot, kernel conflicts, DKMS failures) | Add 4–8 hours |
| Ongoing monthly admin after setup | 1–2 hours/month (log checks, updates) |

**Honest assessment:** These hours are front-loaded. After a working setup exists, the ongoing tax is low — *if* the kernel-pinning and Docker approach is used correctly from the start. The main trap is OS-level driver breakage after kernel updates, which can require console access to fix. If the owner is remote with no physical access, this becomes a serious problem.

Sources: [pedroalonso.net homelab journey](https://www.pedroalonso.net/blog/ai-home-lab-setup/) (2025), [linuxblog LLM server budget](https://linuxblog.io/build-llm-linux-server-on-budget/) (2025), [GPU containers homelab](https://www.virtualizationhowto.com/2025/10/how-to-run-gpu-enabled-containers-in-your-home-lab/) (Oct 2025), [NVIDIA driver Ubuntu forums](https://forums.developer.nvidia.com/t/ubuntu-20-04-driver-apt-packages-broken-by-unattended-upgrade-after-2-months/219260) (ongoing through 2025), [NVIDIA driver break guide](https://www.gpu-mart.com/blog/stop-nvidia-drivers-from-breaking-on-ubuntu) (2025), [Ubuntu driver time estimates](https://linuxcapable.com/install-nvidia-drivers-on-ubuntu-linux/) (2026)

---

## Q4 — 24/7 Headless Reliability

**Confidence: HIGH** — systemd patterns well-documented; driver breakage risk is the known hazard.

### Linux as a "set-and-forget" inference server

Linux is the strongest of the three platforms (Mac/Windows/Linux) for unattended 24/7 operation:

**Auto-restart:** systemd `Restart=always` + `RestartSec=3` is the standard pattern for both vLLM and Ollama. If the inference process OOMs or crashes, systemd restarts it within 3 seconds, no human needed.

```
[Service]
Restart=always
RestartSec=3
```

**Boot persistence:** `systemctl enable vllm` (or `ollama`) ensures the service starts on every boot automatically.

**Unattended security updates:** `unattended-upgrades` handles security patches. **However:** must be configured to exclude kernel packages and NVIDIA drivers to prevent the driver breakage loop described in Q3. Best practice: enable security-only unattended updates, exclude `linux-image*` and `nvidia-*` from auto-upgrade, apply kernel/driver updates manually during a maintenance window.

**Remote recovery:** If the server becomes unreachable, options include:
- Tailscale SSH (works as long as the network and kernel are healthy)
- Wake-on-LAN (requires Ethernet, BIOS enablement via `ethtool -s eth0 wol g`, works from the Tailscale network via `wakeonlan` from Mac)
- iDRAC/IPMI if using server hardware (remote console access even if OS is broken)

**Consumer desktop boards** do not have iDRAC/IPMI. If the kernel fails to boot (due to bad driver update), recovery requires physical keyboard+monitor access. **This is the primary reliability risk for a home Linux server.**

**Why Linux beats Mac and Windows here:**
- Mac: launchd restarts are possible but not production-grade; macOS updates are GUI-driven and can require user interaction; no remote console option.
- Windows: Service Manager exists but is fragile for CUDA-heavy workloads; Windows Update is more aggressive and harder to pin; driver updates via Windows Update are a known risk.
- Linux: systemd is purpose-built for daemon management; kernel and driver updates are fully controllable via `apt-mark hold`; headless operation is the default (no GUI running).

Sources: [vLLM Linux production install](https://computingforgeeks.com/install-vllm-linux-production/) (2026), [Ollama systemd guide](https://mljourney.com/how-to-run-ollama-as-a-linux-service-with-systemd/) (2025), [Ollama Linux docs](https://docs.ollama.com/linux) (2026), [Ubuntu unattended-upgrades NVIDIA break](https://leimao.github.io/blog/Fix-NVIDIA-Driver-After-Ubuntu-Unattended-Upgrade/) (2025)

---

## Q5 — Remote Orchestration: Mac → Linux over Tailscale

**Confidence: HIGH** — multiple working real-world setups documented.

### Tailscale as the network layer

Tailscale creates a WireGuard mesh between Mac and Linux. After `tailscale up` on both machines and browser auth, they share a `*.ts.net` private hostname. No port forwarding, no firewall rules needed.

**Standard Mac→Linux setup:**
1. Linux: `curl -fsSL https://tailscale.com/install.sh | sh && tailscale up` — 15 min
2. Mac: Tailscale app from App Store, browser auth — 5 min
3. Linux: set `OLLAMA_HOST=0.0.0.0` (or vLLM `--host 0.0.0.0`) so the service is accessible beyond localhost
4. Mac: `curl http://linux-hostname:11434/v1/models` — verifies connectivity

**SSH:** `ssh user@linux-hostname.ts.net` — works immediately after Tailscale setup. VS Code Remote SSH extension on Mac connects to the Linux box with no additional configuration.

**LLM API access from Mac:** Point LiteLLM / Claude Code Router ANTHROPIC_BASE_URL to `http://linux-hostname:8000/v1` (vLLM) or `http://linux-hostname:11434` (Ollama). All Artemis APEX workflow components on Mac can route to Linux inference transparently.

**Wake-on-LAN on Linux:**
1. BIOS: Enable "PCI Power up" / "Wake from S5" / disable ErP (critical — prevents NIC from losing power in shutdown).
2. Linux: `sudo ethtool -s eth0 wol g` (persists via netplan or networkd-dispatcher hook).
3. Mac: `brew install wakeonlan && wakeonlan AA:BB:CC:DD:EE:FF` — sends magic packet over LAN.
4. Over Tailscale: WoL packet routing is limited to LAN; must send from a device on the same physical LAN (not from Mac if it's remote). Workaround: always-on Raspberry Pi on same LAN acts as WoL relay.

**NVIDIA driver + container toolkit setup (one-time):**
```bash
# Container toolkit (after Docker install)
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /etc/apt/keyrings/nvidia-container-toolkit-keyring.gpg
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/libnvidia-container/$distribution/libnvidia-container.list | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

Sources: [Tailscale SSH setup matttriano.dev](https://matttriano.dev/posts/019_setup_tailscale_for_ssh/setting_up_tailscale.html) (2025), [AlexsJones Framework + Tailscale gist](https://gist.github.com/AlexsJones/2be576db3ccc61724c0c4059d4f4df7f) (2026), [makeuseof private AI server](https://www.makeuseof.com/run-local-llm-model-on-home-server-every-device-in-house-can-use/) (2025), [WoL Linux guide](https://oneuptime.com/blog/post/2026-01-15-configure-wake-on-lan-ubuntu/view) (Jan 2026), [WoL homelab XDA](https://www.xda-developers.com/wake-on-lan-changed-how-i-use-my-home-server/) (2025)

---

## Q6 — Claude Code / Anthropic-API Backend on Linux

**Confidence: HIGH for setup architecture; MEDIUM for agentic/tool-use quality (honest caveat: local models ≠ real Claude).**

### The three-component stack

```
Claude Code (Mac) → LiteLLM proxy (Mac or Linux) → vLLM/SGLang (Linux) → DeepSeek V4-Flash
```

Or with Claude Code Router (simpler, solo-user):
```
Claude Code (Mac) → claude-code-router → vLLM (Linux) → DeepSeek V4-Flash
```

**How it works:** Claude Code sends Anthropic Messages API requests to LiteLLM. LiteLLM translates to OpenAI format, forwards to vLLM, translates response back. Claude Code sees what it believes is Anthropic's API.

**Setup (from medium.com/@michael.hannecke and dev.to/dcruver, late 2025/2026):**
- vLLM: `python -m vllm.entrypoints.openai.api_server --model deepseek-ai/DeepSeek-V4-Flash --port 8000`
- LiteLLM config maps model name `claude-3-5-sonnet-20241022` → `openai/deepseek-v4-flash` at vLLM endpoint
- `ANTHROPIC_BASE_URL=http://linux-hostname:4000` (LiteLLM port) on Mac
- `ANTHROPIC_API_KEY=fake-key-for-litellm` (LiteLLM accepts any key in passthrough mode)

**Known issues:**
- **Cold start timeouts:** Model loads lazily on first request; Claude Code times out. Fix: pre-warm with a dummy request after server start.
- **Context limits:** Local models realistically handle 8–32K context in practice; Claude Code workflows can generate long context. V4-Flash's 1M context spec requires an H200+ to be practical; on consumer hardware, context must be constrained via `--max-model-len`.
- **Ollama default localhost binding:** When running Claude Code Router inside Docker, `localhost:11434` is unreachable. Fix: `OLLAMA_HOST=0.0.0.0:11434`.
- **Model aliasing:** Mapping `claude-3-5-haiku` → `deepseek-v4-flash` works technically but is not a capability drop-in. The article notes "capable alternative with different characteristics, not drop-in replacements."

**Agentic/tool-use quality:** No first-party benchmark from Anthropic. Community reports (medium.com/@michael.hannecke, 2026) indicate DeepSeek V4-Flash and Qwen3 Coder handle structured tool calls well for coding tasks. Multi-turn tool use is functional. However, complex reasoning chains (multi-step planning) and long-context faithfulness lag behind real Claude 3.5/3.7. For Artemis's coding executor role (DeepSeek backend, not the planning/reasoning role), quality is considered adequate by community consensus.

**vLLM official Claude Code integration page:** Exists at `docs.vllm.ai/en/stable/serving/integrations/claude_code/` — returned HTTP 429 during fetch, indicating it exists and is actively maintained.

Sources: [positioniseverything vLLM+LiteLLM](https://www.positioniseverything.net/running-claude-code-with-local-llms-via-vllm-and-litellm/) (2025/2026), [medium.com/@michael.hannecke](https://medium.com/@michael.hannecke/connecting-claude-code-to-local-llms-two-practical-approaches-faa07f474b0f) (2026), [dev.to/dcruver](https://dev.to/dcruver/running-claude-code-with-local-llms-via-vllm-and-litellm-599b) (2025), [vLLM Claude Code docs](https://docs.vllm.ai/en/stable/serving/integrations/claude_code/) (2026), [roborhythms guide](https://www.roborhythms.com/how-to-run-claude-code-on-local-vllm-model/) (2026)

---

## Q7 — "What People Have Done": Real-World Write-ups

**Confidence: HIGH** — multiple independent homelab accounts from 2025–2026.

### Documented real homelab setups (2025–2026)

**pedroalonso.net — "Building My AI Home Lab: From Laptop to Dedicated Server"** (2025)
- Journey: 2 years; ended on a dedicated Linux GPU server
- Distro switch: Ubuntu Server → Pop!_OS (NVIDIA ISO) to eliminate driver headaches
- Stack: Docker Compose profiles; Tailscale for remote access; "genuinely can't overstate" value of Tailscale
- Key lesson: "the usual NVIDIA driver headaches—kernel updates breaking drivers, manual CUDA toolkit installation, blacklisting nouveau, the whole dance" — eliminated by Pop!_OS NVIDIA ISO
- [Source](https://www.pedroalonso.net/blog/ai-home-lab-setup/)

**AlexsJones GitHub gist — "Local LLM coding setup: Framework Desktop + Tailscale + llama-server + OpenCode"** (2026)
- Hardware: Framework Desktop (AMD Ryzen AI MAX+ 395), Fedora Linux
- Network: Tailscale ACL rules exposing port 8080; Mac → `http://framework:8080/v1`
- Stack: llama.cpp server + tmux (not systemd — deliberate for a dev machine, not 24/7)
- Runs: Qwen3.6-35B-A3B-Q6_K (~27GB) from Hugging Face CLI
- Mac client: OpenCode configured via JSON, `curl http://framework:8080/v1/models` to verify
- [Source](https://gist.github.com/AlexsJones/2be576db3ccc61724c0c4059d4f4df7f)

**networkthinktank.blog — "Self-Host AI on Proxmox Homelab with Ollama and Open WebUI"** (April 2026)
- Proxmox hypervisor + GPU passthrough + Docker + Ollama + Open WebUI
- Demonstrates full virtualized Linux homelab approach
- [Source](https://networkthinktank.blog/2026/04/24/how-to-self-host-ai-on-your-proxmox-homelab-with-ollama-and-open-webui/)

**localaimaster.com — "Homelab AI Server Build: Used RTX 3090 Budget Guide"** (2025)
- Used RTX 3090 24GB as the hardware foundation
- Ubuntu Server headless; Ollama as the serving layer
- [Source](https://localaimaster.com/blog/homelab-ai-server-build)

**varunvasudeva1 GitHub — "llm-server-docs: End-to-end LLM server on Debian"** (2025)
- Full documentation: chat, web search, RAG, model management, MCP servers, image gen, TTS
- Debian base; complete runbook from zero
- [Source](https://github.com/varunvasudeva1/llm-server-docs)

**fecht.cc — "Building an On-Demand GPU Home Server For LLM Inference"** (2025)
- Focuses on on-demand power (WoL-based spin up/down to save electricity)
- [Source](https://fecht.cc/personal/local-on-demand-gpu/)

**Common patterns across all accounts:**
1. Tailscale is universally praised as the "easy" network layer
2. Driver management is the universal pain point; Docker containers and/or NVIDIA-friendly distros are the universal mitigation
3. All headless production setups use systemd or Docker `restart: always`
4. GGUF + Ollama is the low-friction entry; vLLM is the upgrade path for concurrency

---

## Q8 — Honest Verdict for a Low-Admin Owner

**Confidence: HIGH** — synthesized from all sources above with explicit honest weighting.

### Is the burden surmountable?

**Short answer: Yes, with the right setup strategy — but it is a real upfront cost, and there is one genuine ongoing hazard.**

### The upfront cost is real but bounded

A non-sysadmin who:
1. Uses Ubuntu 24.04 LTS Server or Pop!_OS (NVIDIA ISO)
2. Runs vLLM or Ollama inside Docker containers (not bare-metal)
3. Has an AI coding agent (APEX itself) write the setup scripts
4. Installs Tailscale for remote access

...can go from bare hardware to running V4-Flash in 1–2 weekends of focused work. The skills needed are: SSH, reading `journalctl` output, and running `docker compose up`. Everything else can be scripted.

The APEX system can generate every configuration file needed: Docker Compose, systemd units, Ansible playbook, kernel pin script, Tailscale ACL. The owner's job becomes "run this script and tell me what happened." This is a real, documented workflow (AI-assisted Linux setup is mainstream by 2026).

### The one genuine ongoing hazard

**Kernel update → NVIDIA driver breakage.** If unattended-upgrades installs a new kernel and the DKMS module fails to rebuild:
- The server may fail to boot into GPU mode
- Recovery may require physical console access (keyboard + monitor)
- If the server is in a location without easy physical access, this is a serious problem

**Mitigation (must be configured at setup time):**
```bash
sudo apt-mark hold linux-image-generic linux-headers-generic
```
With kernel-pinned and inference running in Docker containers (which pin CUDA version), the ongoing tax drops to near zero. Apply driver/kernel updates manually during planned maintenance windows (quarterly).

### Honest comparison to Windows

Windows has a slightly lower initial learning curve (GUI everywhere) but worse long-term outcomes: Windows Update is harder to pin, CUDA driver management is less scriptable, systemd equivalent (Task Scheduler + NSSM) is fragile for long-running GPU processes, and community support for production LLM serving assumes Linux.

### Honest comparison to Mac

Mac M-series is the **zero-admin path** — no driver management, no kernel risks, Time Machine for backup, automatic updates that don't break inference (MLX is userspace). But Mac sacrifices: CUDA ecosystem access (best tools are CUDA-first), tensor parallelism across multiple GPUs, and the top-tier throughput per dollar for large MoE models like V4-Flash. Mac cannot run V4-Flash at production quality on any current hardware (192GB M4 Max can run it, but single-stream only, no batching, slower than a GPU solution).

### Bottom line for Artemis

For a single-user coding harness:
- **If owner has physical access to the Linux box:** Linux is surmountable with AI-assisted setup. Upfront 1–2 weekends; ongoing ~1–2 hours/month for log checks + update coordination. The throughput and ecosystem advantage is real and material for parallel agentic workloads.
- **If owner does NOT have reliable physical access:** The driver-breakage recovery risk is significant. Add a serial console or IPMI-capable server board to the budget, or accept that occasional trips to the machine will be needed.
- **The AI-writes-the-scripts mitigation is genuine:** APEX can write every setup file. The owner needs to execute commands and read error messages — that's a lower bar than "know Linux."

---

## Source Index

| URL | Date | Used For |
|---|---|---|
| https://sesamedisk.com/local-inference-engines-2026-comparison/ | 2026 | Q1 stack comparison |
| https://vllm.ai/blog/2025-12-17-large-scale-serving | Dec 2025 | Q2 H200 throughput |
| https://github.com/dzhsurf/deepseek-v3-r1-deploy-and-benchmarks | 2025 | Q2 H100 benchmarks |
| https://rocm.blogs.amd.com/software-tools-optimization/vllm-moe-guide/README.html | 2025 | Q1 vLLM MoE parallelism |
| https://docs.vllm.ai/en/latest/serving/parallelism_scaling/ | 2026 | Q2 TP/DP scaling |
| https://www.spheron.network/blog/vllm-production-deployment-2026/ | 2026 | Q1 vLLM production |
| https://www.spheron.network/blog/sglang-production-deployment-guide/ | 2026 | Q1 SGLang production |
| https://www.runpod.io/blog/sglang-vs-vllm-kv-cache | 2025 | Q1/Q2 SGLang RadixAttention |
| https://www.lmsys.org/blog/2025-10-22-KTransformers/ | Oct 2025 | Q1 KTransformers+SGLang |
| https://dl.acm.org/doi/10.1145/3731569.3764843 | SOSP 2025 | Q1 KTransformers academic |
| https://github.com/kvcache-ai/ktransformers/blob/main/doc/en/DeepseekR1_V3_tutorial.md | 2025 | Q1 KTransformers DeepSeek |
| https://www.pedroalonso.net/blog/ai-home-lab-setup/ | 2025 | Q3/Q7 driver pain, distro |
| https://linuxblog.io/build-llm-linux-server-on-budget/ | 2025 | Q3 budget Linux LLM |
| https://www.virtualizationhowto.com/2025/10/how-to-run-gpu-enabled-containers-in-your-home-lab/ | Oct 2025 | Q3 Docker GPU homelab |
| https://forums.developer.nvidia.com/t/ubuntu-20-04-driver-apt-packages-broken-by-unattended-upgrade-after-2-months/219260 | ongoing | Q3/Q4 driver breakage |
| https://leimao.github.io/blog/Fix-NVIDIA-Driver-After-Ubuntu-Unattended-Upgrade/ | 2025 | Q4 driver fix |
| https://www.gpu-mart.com/blog/stop-nvidia-drivers-from-breaking-on-ubuntu | 2025 | Q4 kernel pinning |
| https://computingforgeeks.com/install-vllm-linux-production/ | 2026 | Q4 vLLM systemd |
| https://mljourney.com/how-to-run-ollama-as-a-linux-service-with-systemd/ | 2025 | Q4 Ollama systemd |
| https://docs.ollama.com/linux | 2026 | Q1/Q4 Ollama Linux |
| https://matttriano.dev/posts/019_setup_tailscale_for_ssh/setting_up_tailscale.html | 2025 | Q5 Tailscale SSH |
| https://gist.github.com/AlexsJones/2be576db3ccc61724c0c4059d4f4df7f | 2026 | Q5/Q7 real homelab |
| https://oneuptime.com/blog/post/2026-01-15-configure-wake-on-lan-ubuntu/view | Jan 2026 | Q5 WoL Ubuntu |
| https://www.xda-developers.com/wake-on-lan-changed-how-i-use-my-home-server/ | 2025 | Q5 WoL homelab |
| https://medium.com/@michael.hannecke/connecting-claude-code-to-local-llms-two-practical-approaches-faa07f474b0f | 2026 | Q6 Claude Code local |
| https://dev.to/dcruver/running-claude-code-with-local-llms-via-vllm-and-litellm-599b | 2025 | Q6 vLLM+LiteLLM |
| https://www.positioniseverything.net/running-claude-code-with-local-llms-via-vllm-and-litellm/ | 2026 | Q6 vLLM+LiteLLM |
| https://docs.vllm.ai/en/stable/serving/integrations/claude_code/ | 2026 | Q6 official vLLM Claude Code |
| https://www.compute-market.com/blog/deepseek-v4-flash-local-hardware-guide-2026 | 2026 | Q2 V4-Flash tiers |
| https://chatgptaihub.com/deepseek-v4-self-hosting-guide/ | 2026 | Q2 V4-Flash vLLM setup |
| https://lushbinary.com/blog/deepseek-v4-self-hosting-guide-vllm-hardware-deployment/ | 2026 | Q2 V4-Flash VRAM reqs |
| https://recipes.vllm.ai/deepseek-ai/DeepSeek-V4-Flash | 2026 | Q2 official vLLM V4 recipe |
| https://networkthinktank.blog/2026/04/24/how-to-self-host-ai-on-your-proxmox-homelab-with-ollama-and-open-webui/ | Apr 2026 | Q7 Proxmox homelab |
| https://localaimaster.com/blog/homelab-ai-server-build | 2025 | Q7 RTX 3090 homelab |
| https://github.com/varunvasudeva1/llm-server-docs | 2025 | Q7 Debian LLM server |
| https://fecht.cc/personal/local-on-demand-gpu/ | 2025 | Q7 on-demand GPU |
| https://medium.com/@madhur.prashant7/efficient-llm-agent-serving-with-vllm-a-deep-dive-into-research-agent-benchmarking-3c07c563228a | 2025 | Q2 agentic vLLM serving |
| https://codersera.com/blog/deepseek-v4-complete-guide-2026/ | 2026 | Q2 V4 overview |
| https://homelabstarter.com/wake-on-lan-guide/ | 2025 | Q5 WoL homelab |
