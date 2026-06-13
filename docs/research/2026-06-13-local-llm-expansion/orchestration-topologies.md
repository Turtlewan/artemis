# Orchestration Topologies — Mac→Mac vs Mac→Windows vs Mac→Linux (2026-06-13)

_Deep research: 3 parallel Sonnet info-pull agents (one per inference-host OS), same 8-question
template for apples-to-apples comparison. Sources: `topology-mac-host.md` · `topology-windows-host.md`
· `topology-linux-host.md` (every claim cited there). Synthesis: Opus (owner protocol names Fable —
flagged). The Mac Mini is the constant orchestrator (Python brain + Claude Code/APEX + LiteLLM); the
variable is the inference-box OS._

## TL;DR
For **this owner** (low-admin, would-rather-not-learn-Linux, already all-Apple), **Mac→Mac with
`vllm-mlx` is the recommended topology** — and a key finding strengthens it vs the earlier hedge:
**`vllm-mlx` speaks the Anthropic API natively AND does continuous batching**, which (a) satisfies the
APEX coding requirement R with no shim, and (b) **dissolves the earlier "Mac can't batch for parallel
workers" worry** (measured ~1,150 tok/s aggregate at 32 concurrent on an M4 Pro). **Linux** remains the
raw-capability + 24/7 champion if you'll pay a bounded admin tax. **Windows** is largely dominated —
it only avoids Linux at the *light* tier; the heavy stack is WSL2 (= Linux anyway).

## Comparison matrix

| Axis | **Mac → Mac** | **Mac → Windows** | **Mac → Linux** |
|---|---|---|---|
| Linux to learn | **None** | None (native Ollama) / **Yes** (WSL2 for heavy stack) | **Yes** — bounded, scriptable |
| Best serving stack | `vllm-mlx` (native Anthropic + batching), MLX, Ollama | native: Ollama/llama.cpp (capped); heavy: WSL2 vLLM | **vLLM / SGLang** (TP, best) |
| Single-stream tok/s | ~17–35 (big MoE) / ~130 (30B MoE) | ~40–72 (1 GPU) | ~45–84 (datacenter GPU) |
| Concurrent / agentic (parallel workers) | **Good via vllm-mlx** (~1,150 tok/s @32); Ollama serializes | native Ollama caps ~4–8 (weak); WSL2 vLLM good | **Best** (linear TP; SGLang prefix-cache 75–95%) |
| 24/7 headless reliability | Good (disable sleep+FileVault; launchd not prod-grade) | **Worst** (Windows Update reboot loops; Apr-2026 incident) | **Best** (systemd `Restart=always`) |
| V4-Flash fit | **Unified memory fits** (192–512 GB Mac) | GPU-VRAM-bound → needs 96 GB+ (multi-GPU) | GPU-VRAM-bound → 96 GB+ (H200 / RTX Pro 6000 / 4×3090) |
| Claude Code backend (req. R) | `vllm-mlx` **native /v1/messages** (best) | Ollama v0.14+ native Anthropic, or shim | LiteLLM/router shim (well-documented) |
| Power / noise | silent, <$100/yr (but $$ for a big Mac) | varies (GPU rig) | varies; + driver-break risk |
| Admin tax over time | lowest | medium-high (Win Update vigilance) | one-time setup + kernel/driver hazard |

## Findings that update the plan
1. **`vllm-mlx` = native Anthropic API + continuous batching (Confidence High).** This is the headline.
   It satisfies requirement **R** (Claude Code only speaks Anthropic) with **no claude-code-router/
   LiteLLM shim**, and it **batches** — so APEX's wave-parallel `code-worker` fan-out works on a Mac
   (the §8 A2 concern was specifically about Mac/Ollama serialization; vllm-mlx resolves it). Adds ~1 h
   of Python setup over plain Ollama. → **Amend §8 A2: "serve coding on vLLM/SGLang **or vllm-mlx**."**
2. **Ollama v0.14+ (Jan 2026) speaks Anthropic Messages API natively on all 3 OSes.** The simplest
   Claude-Code-backend path everywhere — no shim for the easy case (but Ollama *serializes*, so it's the
   low-concurrency path; use vllm-mlx/vLLM/SGLang where parallel workers matter).
3. **V4-Flash is MoE (13B active), not dense** (per `models-memory.md`) — so the pessimistic
   "284B dense ~10–12 tok/s on Mac" caveat in `topology-mac-host.md` does **not** apply; expect the
   ~25–35 tok/s MoE figures. And **unified memory fits V4-Flash where GPU VRAM struggles** — a Mac packs
   it into 192 GB unified, while a GPU box needs ~96 GB VRAM (datacenter card or multi-GPU). This is a
   real, specific **Mac advantage for the Artemis target model.**
4. **Windows, blunt: does NOT avoid Linux for the heavy stack.** Native Windows = Ollama/llama.cpp
   (single-GPU, ~4–8 concurrency, no NCCL TP) or immature community vLLM forks (single-GPU / CPU-relay
   TP). SGLang: WSL2 only. Multi-GPU tensor-parallel: WSL2 only (= Linux). So "Windows to dodge Linux"
   holds **only at the light tier**.
5. **Windows 24/7 reliability is the weakest** — Windows Update auto-reboots (documented Apr-2026
   Server reboot-loop incident); needs active management. Least set-and-forget.
6. **Linux's one genuine hazard = kernel-update → NVIDIA-driver breakage**, which can strand a headless
   box with no console. Fix is a one-time proactive `apt-mark hold` (or Pop!_OS NVIDIA ISO / IPMI / Pi
   WoL-relay). **Hours-to-competent:** ~3–5 h AI-scripted (an APEX session writes one Ansible playbook),
   ~8–15 h learning-as-you-go, +4–8 h if driver hell; ongoing ~1–2 h/month.

## Per-topology verdict

**Mac → Mac (RECOMMENDED for this owner).** Zero Linux, unified memory fits V4-Flash, `vllm-mlx` gives
native-Anthropic + batching (APEX-ready), silent, ~<$100/yr, set-and-forget enough. *Costs:* single-
stream ceiling on the largest models, ~10× degradation at 40–50k+ context, Mac price, and full Kimi
needs a fragile multi-Mac cluster (TB5 RDMA, immature). *Gotchas:* disable sleep **and** FileVault before
going headless (or a power-cut locks you out); override Ollama's 4096 default context; pin LiteLLM
version if used (a 2026 release shipped credential-stealing malware).

**Mac → Linux (best raw capability + 24/7).** vLLM/SGLang, linear TP scaling for parallel agents,
SGLang prefix-cache is a free multiplier for APEX's shared-prompt fan-out, best unattended reliability.
*Costs:* the Linux tax — bounded and scriptable (AI writes the Ansible), but the kernel/driver-break
hazard is real for a headless box, and V4-Flash needs serious VRAM (96 GB+ → datacenter/multi-GPU).
Pick this if you want max concurrency / cheaper CUDA / a training box and will pay the admin tax.

**Mac → Windows (largely dominated).** Sensible **only** as a light, native (Ollama, single-GPU) box for
someone who refuses both Linux and Mac — adequate for single-stream agentic coding, capped on
concurrency. Anything heavier = WSL2 = Linux, at which point a real Linux box is cleaner. Worst 24/7
reliability. Main legitimate use: reuse the existing Windows PC for light/occasional inference or the
distill pipeline.

## Net effect on Decision B
Strengthens **P-Apple** as the default for this owner's constraints (and the vllm-mlx finding removes the
batching objection). **P-GB10 / P-Xeon / P-CUDA = the Mac→Linux branch** (capability at an admin cost).
**A "P-Windows" rung is not worth adding as primary** — native-Windows is a light-tier-only niche, and
the heavy path collapses into Mac→Linux. (No decision reopened; this is a weighting + the A2 amendment.)
