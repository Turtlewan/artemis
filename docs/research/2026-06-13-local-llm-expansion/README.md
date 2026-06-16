# Home-Lab / Local-Inference Expansion — BANK

**This folder is a reference BANK, not a spec.** It is intentionally separate from `docs/changes/`
so it does not enter the build queue. Two uses:

1. **Trigger-activated:** when a hardware trigger fires (see *Triggers* below), **start here** — read
   `_SYNTHESIS-PLAN.md`, then draft the EXP-a / EXP-b specs.
2. **Otherwise:** an info bank of options + **what people have done** (field anecdotes). Drop new
   research / build write-ups **into this folder** (and append to the lists below) — **not** into
   `docs/status.md`. Keep `status.md` about the actual spec corpus; keep this self-contained.

_Nothing here gates the frozen ~61-spec corpus. The only certainty is buying the M5 Mac Mini
(orchestrator). The inference box is future hardware — picked when a trigger fires, not before._

---

## Start here
- **`_SYNTHESIS-PLAN.md`** — the consolidated plan: requirement, model menu, hardware ladder,
  software stack, model-update process, APEX fit (coding + planning), and **all resolved decisions**.
- **`orchestration-topologies.md`** — deep comparison of **Mac→Mac vs Mac→Windows vs Mac→Linux**
  inference-host options (the OS/learning-curve axis). TL;DR: **Mac→Mac with `vllm-mlx`** is the
  low-admin recommendation (native Anthropic API + batching → APEX-ready, no Linux); Linux = best
  capability at an admin cost; Windows = largely dominated (light-tier-only or WSL2=Linux).

## Decisions already made (detail in `_SYNTHESIS-PLAN.md`)
- **A — model-flexible:** size for a capability class, not named models; standing model-update
  process (alias-swap + quarterly refresh + eval-before-swap + rollback). (§7)
- **B — keep all buy paths open, trigger-gated** (T0–T3). Box = live menu (§2).
- **C → C-2 — extend trust boundary to the box** under 5 binding controls (FDE · no-persistence
  serving · Tailscale-only · ADR+runbook+mini-security-review · fail-safe validator). (§4)
- **D-plan-1 → "1 then 3":** planning stays cloud-frontier now → fully-local distilled planner as
  end-state (CAP/M7). **D-plan-2 → research pullers local**, synth stays frontier. (§8b)
- **Key finding:** DeepSeek V4-Flash (284B, 1M ctx, ~128–192 GB Q4) may cover **both** roles →
  floor drops from 512 GB (Kimi-class). ADR-019 refinement: **Flash both-roles local + V4-Pro cloud.**

## Hardware menu (§2 + field sections)
| Tag | Box | Memory | Verdict |
|---|---|---|---|
| P-RAG | Mini only (M3 RAG brain) | — | day-1 baseline, free |
| P-Strix | AMD Strix Halo 128 GB | 128 GB | cheap silent bridge |
| **P-GB10** | ASUS GX10 ×2 (field-validated §10) | 256 GB | path (i) NOW, ~$7.1k |
| P-Apple | M5 Ultra Studio (~Oct 2026) | 256–512 GB | quiet end-state; 512 = +Kimi Q2 |
| P-Xeon | Xeon-AMX + 1 TB DDR5 + GPU | 1 TB sys | only path to Kimi Q4 + training box |
| ~~Intel B60 multi-GPU~~ | 4–8× Arc Pro B60 | 96–192 GB | **DECLINED §11** (model-lag, livability) |
| P-CUDA-MultiGPU | 8× RTX 4000 Ada-class | 160 GB | **viable but dominated §12** (fallback only) |

## Triggers — when to come back to this bank
- **T1** — M5 Ultra ships (~Oct 2026): check 512 GB price/availability → P-Apple.
- **T2** — Kimi-Q4 / fast huge-doc prefill / a local training box becomes a felt need → P-Xeon.
- **T3** — want local coding before any big box → P-Strix or P-GB10 now.
- **T0** — until a trigger fires: P-RAG (Mini-only) + Rung-0 Mini coding. Zero spend.

## Future hardware items & build checklist (single home — was scattered in BACKLOG)
_Open/buy these only when a trigger fires; they hang off whichever path is chosen._

**Common to any box:**
- UPS + power monitoring (smart plug) for the 24/7 box.
- Wired Mini↔box Ethernet (Wake-on-LAN needs wired); 10 GbE + NAS for model-weight storage (weights are 40–600 GB each).
- Model-weight storage management — versioning + eviction policy (hundreds of GB per model).
- Wake-on-demand power orchestration — Mini wakes the box per queued job, sleeps it after (the ~50 W idle-hold cost, §10).
- Inference-box bring-up runbook + C-2 disk-encryption/secrets posture (→ EXP-b).

**Path-specific accessories:**
- **P-GB10:** 2× ASUS GX10 + QSFP112 ConnectX cable (~$100); note no GPU-Direct RDMA (§10).
- **P-Apple:** HDMI dummy plug + `pmset`/LaunchDaemon for stable headless 24/7 (§ apple-path).
- **P-Xeon:** 1 TB DDR5, must be **Intel AMX** (not EPYC) for the ktransformers prefill speedup (§2).
- **P-CUDA-MultiGPU:** Threadripper Pro/EPYC board with native lanes (avoid modded-BIOS bifurcation), low-TDP pro cards, dual PSU, open-air/staggered cooling, **TP = power-of-2 GPUs** (§12).

**Capability-lane convergence:** an x86/GPU box doubles as the DPO/RLAIF training home (`homelab-control-plane.md`); reserve a planning/spec-authoring generation category in `distill-datagen-pipeline` (supports the D-plan-1 distilled-planner end-state).
**Watch item:** re-check exo/TB5 RDMA Mac-clustering maturity in 2027 (changes the top-rung calculus).
**Open decision (EXP-a):** coding-agent harness — keep Claude-Code + Anthropic-shim (preserves APEX) vs OpenCode-native (simpler serving, abandons APEX). See §10.

_(Full rationale for each: `_SYNTHESIS-PLAN.md` §6 + §10 + §12.)_

## Field anecdotes — "what people have done" (append new ones here)
- **Dual GB10 / ASUS GX10 ×2** (Techno Tim) — §10. Validated A1/A2/A3 + the agentic quality ladder;
  corrected GB10 clustering (no GPU-Direct RDMA). Confidence Med.
- **Intel Arc Pro B60 ×4** (96 GB cheap-VRAM) — §11 (+ `intel-b60-*.md`). Declined: software lag,
  fit, livability. Confidence Med (3 cited research agents).
- **8× RTX 4000 Ada CUDA build ("Odysseus", PewDiePie)** — §12. Viable-but-dominated; reusable build
  notes (TP power-of-2, avoid modded-BIOS bifurcation, low-TDP pro cards). Confidence Low–Med (anecdote).
- _"Personal AI computer" video_ — `../2026-06-12-...` / status prior-entry; stack maps ~1:1 onto
  locked Artemis decisions (validation pass, no change).
- **MTPLX (native MTP / speculative-decoding MLX runtime)** — Joe Medalone video, 2026-06-16. A
  quality-neutral speed-up for the Mac-side runtime; OpenAI-compatible → drop-in behind the M0-c seam.
  **Benchmark candidate only** (brand-new, model-lock-in, single confounded ~23% claim). Park for
  on-device A/B vs `mlx-openai-server`/`vllm-mlx` when the Mini lands. Detail: `serving-software.md` §1.5.

## Files in this bank
| File | What |
|---|---|
| `_SYNTHESIS-PLAN.md` | the plan (entry point) |
| `models-memory.md` | model family fit table + quant/KV memory math |
| `apple-path.md` | Mac Studio / M5 Ultra / clustering |
| `x86-gpu-path.md` | EPYC/Xeon CPU-offload, GPU rigs, small-box newcomers |
| `serving-software.md` | vLLM/SGLang/MLX serving, LiteLLM gateway, Claude-Code backend |
| `artemis-integration-constraints.md` | how Artemis binds models (config-only swap seam) |
| `intel-b60-hardware.md` / `-software.md` / `-benchmarks-fit.md` | Intel B60 evaluation |
| `orchestration-topologies.md` | Mac→Mac vs Mac→Windows vs Mac→Linux comparison (synthesis) |
| `topology-mac-host.md` / `topology-windows-host.md` / `topology-linux-host.md` | per-OS deep-dive sources |

## Future specs (drafted only when a trigger fires — these are NOT yet specs)
- **EXP-a** — remote-inference routing (LiteLLM aliases incl. Anthropic-protocol coding endpoint +
  research-puller local alias + Flash/Pro tier fallback).
- **EXP-b** — inference-box bring-up runbook + C-2 security review.
