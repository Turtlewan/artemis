# Research: Self-Training / Fine-Tuning the Artemis Local Model
**Date:** 2026-06-09
**Confidence:** MEDIUM — practitioner-consensus + MLX-docs-grounded research agent; agent could not write its own file or be source-audited inline, so treat tool/throughput numbers as directional until hands-on.
**Re-research after:** 2026-06-23 (14-day AI-tooling clock)

> Synthesis-level capture of a Sonnet research agent run (2026-06-09).

## Summary
Local self-training is **worth doing — but reframed**: not "make the 30B smarter," instead **fine-tune a
smaller ~14B student on the owner's style, preferences, and recurring task patterns**, privately, while
the larger model stays the inference workhorse. Crucially, **RAG + good system prompting already covers
~80%** of personalization value — fine-tune only where a *repeating* gap is observed (tone, output
format, domain jargon). **Most of the pipeline is doable NOW on the Windows PC** using Claude/Codex/
DeepSeek; only the actual MLX LoRA runs need the Mac.

## Key findings
- **Target a 14B student, not the 30B.** Qwen3-14B is the best-documented, most reliable QLoRA target on 48GB. Keep Qwen3-30B-A3B as inference-only. `[COMMUNITY]`
- **Fine-tuning earns its keep** for: stable output-format prefs, tone/voice, recurring behaviours, weak domain jargon — *after* RAG is exhausted. `[COMMUNITY]`
- **Teachers as data-generators:** Claude Opus generates synthetic instruction data; DeepSeek-as-judge quality-filters. Exactly the right use of the three available APIs. `[COMMUNITY]`
- **On Mac: `mlx-lm` LoRA/QLoRA only.** Unsloth and Axolotl are CUDA-only. `mlx-tune` adds an Unsloth-compatible API for code portability. `[VERIFIED — ml-explore/mlx-examples LoRA docs, per agent]`
- **Cloud GPU fallback** (RunPod/Vast.ai A100 spot, ~$3–5/run, Unsloth) is 10–30× faster than the Mac and lets dataset quality be validated **before the Mac arrives**. `[COMMUNITY]`

## NOW vs LATER
| Task | Now (Windows PC) | Needs Mac |
|---|---|---|
| Define 5–8 Artemis task categories | ✅ | — |
| Generate 1,500–3,000 synthetic JSONL examples (Claude/Codex) | ✅ | — |
| Quality-filter (DeepSeek-as-judge) | ✅ | — |
| Eval harness + 50–100 golden Q/A | ✅ | — |
| Chat-format / prompt-template decisions | ✅ | — |
| One-off cloud-GPU validation run (Unsloth) | ✅ | — |
| `mlx_lm.lora` QLoRA training runs | — | ✅ |
| Adapter eval, hot-swap, deployment | — | ✅ |

## Recommended minimal high-value path
1. **Now:** define 5–8 task categories (summarization, scheduling, writing, code review, …).
2. **Now:** generate 1,500–3,000 synthetic JSONL examples (200–400/category) via Claude Opus; filter with DeepSeek-as-judge.
3. **Now:** write 50–100 eval questions + golden answers; simple Python eval harness.
4. **Now (optional):** one cloud-GPU run (A100, ~$3–5) to validate dataset quality pre-Mac.
5. **On Mac, week 1:** `mlx_lm.lora` QLoRA on Qwen3-14B-4bit; ~2–4h.
6. **Ongoing:** ~100–200 correction examples/month → retrain adapter → hot-swap → track in Git.

## Model-size feasibility on 48GB vs 64GB
| Model | QLoRA mem (approx) | 48GB | 64GB |
|---|---|---|---|
| 7B dense | 7–12 GB | trivial | trivial |
| 14B dense | 14–22 GB | **sweet spot** | comfortable |
| 32B dense | 20–30 GB | needs `--grad-checkpoint` | comfortable |
| Qwen3-30B-A3B (MoE) | 25–35 GB (uncertain) | risky | safe |

→ **64GB meaningfully widens the local fine-tune envelope** (32B-dense + safe 30B-A3B). Feeds the hardware decision.

## Tooling
| Tool | Platform | Use |
|---|---|---|
| mlx-lm / mlx-tune | Apple Silicon | the Mac training path |
| Unsloth | CUDA only | cloud-GPU fast path / future NVIDIA box |
| Axolotl | CUDA only | heavier cloud configs |
| lm-eval-harness + custom | any | eval |

## Assumptions / gaps
- 30B-A3B-on-48GB feasibility is genuinely uncertain — validate empirically.
- The "RAG covers ~80%" figure is practitioner heuristic, not measured for Artemis — our own eval harness should confirm before investing in fine-tuning.

## Sources
- ml-explore/mlx-examples (LoRA) — https://github.com/ml-explore/mlx-examples `[agent-cited]`
- r/LocalLLaMA, HF forums on MLX fine-tuning + distillation `[COMMUNITY]`
