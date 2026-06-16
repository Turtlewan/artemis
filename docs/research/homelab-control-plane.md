# Research: Mac Mini as Homelab Control Plane — "Artemis Cognitive Infrastructure"
**Date:** 2026-06-09
**Confidence:** MEDIUM — practitioner-consensus (r/homelab, r/LocalLLaMA, ServeTheHome) + official-doc grounding for HA/vLLM/LiteLLM/Tailscale, per the research agent. Throughput numbers are directional.
**Re-research after:** 2026-08-08 (60-day infra clock)

> Synthesis-level capture of a Sonnet research agent run (2026-06-09).

## Summary
Mac-Mini-as-control-plane is sound: the Mini runs the Artemis brain + voice + fast MLX inference and
orchestrates everything else over the network. Expansion should be **phased and trigger-gated** (software
architecture matters more than hardware in year 1). The single highest-leverage future addition is a
**networked NVIDIA GPU box** exposing an OpenAI-compatible endpoint — because Apple Silicon can't drive
NVIDIA GPUs, *and* this is where serious fine-tuning runs belong (ties directly to the self-training
thread). Integration is clean via a **LiteLLM proxy** on the Mini → zero Artemis Python changes.

## Recommended phased plan
| Phase | Add | Artemis impact | Trigger to start |
|---|---|---|---|
| **P1 — now** | Mini runs MLX, LanceDB, SQLCipher, voice; Colima/Docker for HA + monitoring | **New milestone:** launchd plist authoring for all Artemis daemons | Hardware in hand |
| **P1b — infra** | Tailscale subnet routing, VLAN topology, Grafana/Prometheus | Pure infra, no Artemis code | Mini stable |
| **P2 — NAS** | TrueNAS SCALE, 10Gb switch, NFS + MinIO for RAG corpus | **New spoke `aci-storage`:** RAG ingest targets MinIO S3 URI | Corpus >50GB or NVMe <20% free |
| **P3 — GPU** | NVIDIA box (RTX 3090/4090), vLLM, LiteLLM proxy | **New spoke `aci-inference-router`:** route >14B + fine-tune jobs to GPU; MLX stays for voice/fast | 70B latency locally unacceptable |
| **P4 — edge** | ESPHome mics, ESP32 sensors, Jetson vision, IoT VLAN, HA MCP server | **New spoke `aci-home`:** voice → brain → MCP → HA → devices | P3 stable + smart-home HW acquired |

## GPU-offload deep-dive (the key lever)
- **Capability gap is real:** Mini M4 Pro MLX ≈ 14B @ 25–40 tok/s, 70B-Q4 @ 6–10 tok/s, *no* RLHF/DPO.
  RTX 4090 vLLM ≈ 14B @ 69–104 tok/s, 70B-Q4 @ 8–15 tok/s, full fine-tune stack. `[COMMUNITY]`
- **Clean integration:** a **LiteLLM proxy on the Mini** presents one `localhost:4000/v1` OpenAI-compatible
  URL; routing rules live in LiteLLM config — **zero Artemis code changes**. Fast/voice → MLX; heavy
  inference + fine-tune → GPU box. `[VERIFIED — LiteLLM docs, per agent]`
- **Network:** route GPU inference over **raw LAN, not Tailscale** (WireGuard overhead bites at high
  throughput). Tailscale stays for remote/control. RTX 3090 (~$700–900 used) = minimum viable entry.

## Capability / self-training workstream (cross-phase lane)
A distillation-for-capability pipeline (not just style personalization) threads through every ACI phase.
The teacher is **Claude via subscription** (flat-rate → marginal $0; bounded by rate limits → a slow
background drip) generating **reasoning traces with full chain-of-thought**; **DeepSeek-API-as-judge**
quality-filters. Detail + sizing: `docs/research/self-training-local-model.md`. **The GPU box (P3) now has
a dual driver — 70B inference latency OR serious training need — which can pull P3 earlier.**

| ACI phase | Self-training role | Output |
|---|---|---|
| **P0 — now (PC, pre-hardware)** | Build + run the data-gen pipeline. Define 5–8 task categories; generate reasoning traces (Claude); judge-filter (DeepSeek); build eval harness + hand-curated hold-out set. **The productive-wait job.** | versioned `datasets/distill/*.jsonl` + eval set (Git; ~tens of MB) |
| **P1 — Mini** | 14B QLoRA LoRA runs (`mlx-lm`) on the corpus; adapter eval vs hold-out; hot-swap into responder/reasoner | trained LoRA adapters |
| **P2 — NAS** | Corpus + adapters + raw teacher transcripts migrate to NAS as versioned training assets | NAS-backed training corpus |
| **P3 — GPU box** | Serious distillation (bigger student / more data) + **DPO/RLAIF** using DeepSeek-judged preference pairs (RLHF stack is CUDA-only) | higher-capability student + preference-tuned adapters |
| **Ongoing** | Scheduled **active-learning loop** on the Mini: capture local-model misses → Claude solves with CoT → append → periodic retrain (`pre_tick_steps`/heartbeat-adjacent or n8n) | self-improving corpus |

**Dataset sizing:** pilot 1k–2k (validate lift) → v1 5k–10k curated across categories (gen ~1.5–2× raw,
judge-filter) → +200–500/month active-learning. Hold out 10–15% for eval, never trained on. LoRA 1–3
epochs; maximize cross-category diversity; dedup. `[COMMUNITY — LIMA (~1k aligns) / R1-distill (~800k SOTA) bracket the range]`

**Tooling candidate for the TRAINING step (P1/P3) — Unsloth Studio** `[added 2026-06-16 from a field video — fit-eval, not adopted]`: free OSS local LoRA/QLoRA trainer (optimized kernels + dynamic-2.0 quant) — a strong default to evaluate for the deferred Mac-side training spec (the `mlx_lm.lora` run that `distill-datagen-pipeline` feeds). Scope it to the **training-execution** role only. NOT for dataset-gen: its "recipes" (PDF→Q&A via OpenRouter) lack our judge-filter / category-balance / eval hold-out, AND would send content to a cloud model — our P0 `distill-datagen-pipeline` is the better-designed, sensitivity-tiered front half and stays. Fit notes: (1) the field video hit an **MLX-on-Apple-Silicon training bug** (metal allocation, not RAM) → Unsloth's maturity + core value is **CUDA/Linux**, which favors the **P3 GPU box** over P1-on-MLX for serious runs; (2) it's a localhost GUI — use it as a spec-invoked engine, not the workflow; (3) terminology: Unsloth "recipes" ≠ Artemis recipes. **Status: evaluate when the Mac-side training spec is drafted (post-Mac).**

## Integration seams with locked Artemis architecture
- **NAS:** TrueNAS SCALE + MinIO; RAG ingest writes to an S3 URI; respects `/opt/artemis` data-root + ADR-002 local-only-backup posture (NAS is on-LAN, not cloud).
- **Home Assistant:** native **MCP Server** integration (HA 2026.5, agent-reported) is an exact fit for MCP-at-edges — no custom HA code.
- **Monitoring:** Grafana/Prometheus **complements** OBS, not overlaps — OBS = app layer (tokens/cost/latency), Prometheus = infra layer (CPU/disk/uptime). Bridge with a ~50-line Python Prometheus exporter over existing OBS JSON.
- **Containers on macOS:** Colima/Docker works but is the rough edge — HA + monitoring in containers on Apple Silicon; some practitioners prefer these on a separate Linux box long-term.

## New spokes vs pure infra vs skip
- **New Artemis milestones/spokes:** P1 launchd milestone, `aci-storage` (P2), `aci-inference-router` (P3), `aci-home` (P4).
- **Pure infra (no Artemis code):** Tailscale subnet routing, VLANs, Grafana/Prometheus, Colima, non-Artemis n8n.
- **Skip/premature:** all Phase-4 edge hardware until P2–P3 run.

## Recommended name
**Artemis Cognitive Infrastructure (ACI)** — infra layer; spoke prefix `aci-`. Artemis stays the cognitive layer on top.

## Assumptions / gaps
- HA 2026.5 native MCP Server claim is agent-reported — verify before specing `aci-home`.
- Throughput numbers are community benchmarks, not measured on our exact hardware.

## Sources
- Home Assistant, TrueNAS, vLLM, LiteLLM, Tailscale docs `[agent-cited Tier 1/3]`
- r/homelab, r/selfhosted, r/LocalLLaMA, ServeTheHome `[COMMUNITY]`
