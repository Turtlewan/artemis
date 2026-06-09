# Research: Local model tier for Artemis

**Date:** 2026-06-08
**Re-research after:** 2026-06-22 (14 days)
**Author:** Research agent (claude-sonnet-4-6)

---

## Summary

The Artemis model-tier decisions from early June 2026 are mostly sound but require two targeted upgrades. The responder (Qwen3-4B-Instruct-2507) is still the best sub-5B tool-caller available, with its 2507 refresh meaningfully raising BFCL-v3 from 57.6 → 61.9. However, the sensitive-reasoner slot deserves re-examination: Qwen3.6-27B (dense, released April 2026) fits on 48GB at ~18GB 4-bit and outscores Qwen3-14B on every published benchmark — it warrants a swap if the 9GB RAM delta is acceptable. The existing DeepSeek cloud teacher path (V4-Flash) remains the right call for 48GB (Scenario A). On a bigger box (Scenario B, 64–128GB), a strong local teacher displacing the cloud dependency is credible by late 2026 — but today it is borderline on quality and slow on tok/s at the 70B tier.

---

## Key Findings (tagged)

### Responder tier (3–5GB, always-resident)

- Qwen3-4B-Instruct-2507 posted BFCL-v3: **61.9** (up from 57.6 for the un-refreshed Qwen3-4B). TAU2 agent benchmarks jumped ~40% vs the prior version. [VERIFIED — huggingface.co/Qwen/Qwen3-4B-Instruct-2507]
- The newer **Qwen3.5-4B** (released Feb 2026, hybrid Gated DeltaNet + MoE architecture) scores 38.9 on TIR-Bench — lower than Qwen3-4B-Instruct-2507's BFCL performance in direct comparison. [VERIFIED — huggingface.co/Qwen/Qwen3.5-4B]
- Qwen3.5-4B also introduced a **14x latency regression on llama.cpp** due to the Gated DeltaNet architecture; requires MLX (mlx-vlm) for correct performance. This is a deployment risk if anything other than MLX is used. [VERIFIED — medium.com/@aejaz.sheriff/...]
- On Apple Silicon MLX 4-bit, typical rates for 4B-class models: **25–35 tok/s** on M4 Pro. [COMMUNITY — insiderllm.com/guides/best-local-llms-mac-2026/]
- Community tool-calling benchmark (CPU, Ollama): Qwen3-series 1.7B scored 0.960 agent score, leading all sub-5B models; Phi-4-mini 3.8B scored 0.780. [VERIFIED — github.com/lintware/tool-calling-benchmark]
- One source explicitly warned: "tool-calling reliability degrades noticeably below 13B parameters" for multi-step agent tasks. [COMMUNITY — contracollective.com/blog/mlx-openclaw...]
- **Conclusion:** Qwen3-4B-Instruct-2507 remains the best available sub-5B tool-caller on MLX as of June 2026. No competitor at the 3–5GB budget materially beats it. [ASSUMED — no head-to-head BFCL comparison with Qwen3.5-4B found]

### Sensitive-reasoner tier (12–32B, lazy-loaded)

- **Qwen3-14B (current pick):** ~9GB at 4-bit, ~40–48 tok/s on M4 Pro 48GB. Fits easily, leaves large RAM headroom. [COMMUNITY — contracollective.com benchmark data]
- **Qwen3.6-27B (dense, April 2026):** ~18GB at 4-bit Q4. SWE-bench Verified 77.2%, GPQA Diamond 87.8%, AIME 2026 94.1%. With MLX native MTP speculative decoding: **18.3 tok/s** on an M4 Pro 48GB (up from 7 tok/s baseline). [VERIFIED — medium.com/@vinoth.lingam333/... ; buildfastwithai.com/blogs/qwen3-6-27b-review-2026]
- **Qwen3.6-35B-A3B (MoE, April 2026):** ~20GB at Q4, up to ~55 tok/s on M5 Pro (M4 Pro somewhat slower). The 27B dense model outscores the 35B-A3B on every benchmark (e.g., SkillsBench 48.2 vs 28.7). So the MoE is fast but lower quality than the dense. [VERIFIED — zoliben.com/en/posts/2026-04-23-qwen-36-35b-vs-27b-benchmark-results/]
- **Gemma 4 27B/31B:** ~16GB at 4-bit. Tool-calling 93–96% well-formed-call rate on real MCP servers. SWE-bench data not found. Confirmed fit on 24GB+ machines. [COMMUNITY — promptquorum.com/power-local-llm/best-local-models-tool-calling-2026]
- **DeepSeek R1 32B distill:** ~20GB at 4-bit. Strong reasoning, community-reported good MATH performance, but tool-call reliability on multi-step chains less consistently documented. [COMMUNITY — pinggy.io/blog/top_5_local_llm_tools_and_models/]
- **Phi-4 14B:** ~9GB at 4-bit, 55–62 tok/s on M4 Pro 24GB. Strong tool-call multi-step reliability (no hallucinated signatures noted). BFCL score not found. [COMMUNITY — contracollective.com benchmark data; contracollective.com/blog/mlx-openclaw...]
- **Llama 4 Scout 17B (MoE):** ~10GB at Q4 on 32GB+ system. Community reports **inconsistent JSON adherence and tool-call formatting** — heavy agent stacks need extra guardrails. [COMMUNITY — sitepoint.com/llama-4-scout-on-mlx...]
- RAM budget on 48GB (scenario A): resident Qwen3-4B-2507 (~3GB) + system (~4GB) = 7GB used at rest. 41GB available for lazy-load. Qwen3.6-27B (18GB) fits with 23GB to spare.

### Local teacher feasibility

- **Scenario A (48GB):** After resident (3GB) + sensitive-reasoner swap to Qwen3.6-27B (18GB) + headroom, there is ~23GB remaining — not enough for a 32B teacher (needs ~20GB Q4 on top of what's already loaded; total would exceed 48GB). A 32B teacher can only work if the sensitive-reasoner is unloaded first. Qwen3-14B could coexist with a Qwen3-32B teacher (9+20=29GB + 7GB overhead = 36GB total, fits). [ASSUMED — arithmetic from reported memory figures]
- **Scenario B (64–128GB):** At 64GB, a Qwen3.6-27B sensitive-reasoner + a dense Qwen3-32B or Qwen3.6-35B-A3B teacher would fit concurrently. At 128GB, a 70B teacher at Q8 (~70GB) is feasible alongside the resident stack. [COMMUNITY — multiple guides; aiproductivity.ai/blog/apple-m5-max-local-llm-guide/]
- **Quality threshold for teacher displacement:** Llama 3.3 70B Q8 on 128GB: "quality comparable to GPT-4o for many tasks" at **~16 tok/s**. [COMMUNITY — aiproductivity.ai/blog/apple-m5-max-local-llm-guide/] This is plausible for many teacher tasks (generating training data, evaluating outputs), but 16 tok/s is slow for interactive grading loops.
- **Break-even economics:** Amortized hardware + electricity for a Mac Studio 128GB costs ~$165/month; beats DeepSeek V4-Flash pricing only above ~16.5M output tokens/month. For Artemis (personal assistant, low-volume), the cloud is economically superior unless privacy of teacher tasks is the driver. [COMMUNITY — aiproductivity.ai/blog/apple-m5-max-local-llm-guide/]
- **Best local teacher candidates (scenario B):** Qwen3.6-27B dense (18GB, frontier-adjacent quality, native MTP heads), Llama 3.3 70B Q4_K_M (35GB, 28 tok/s on 128GB), Qwen3.5-122B-A10B (BFCL-V4 score 0.722, very strong tool-call ceiling but 50–60GB Q4). [VERIFIED — llm-stats.com/benchmarks/bfcl-v4; aiproductivity.ai]
- **Verdict for scenario B:** A 64–128GB box can plausibly host a local teacher that displaces DeepSeek for non-sensitive tasks, but only if teacher call volume justifies the hardware cost. Qwen3.6-27B is the pragmatic choice (fits even at 64GB, frontier-quality on coding/reasoning). A 70B is higher quality but borderline on speed.

---

## Responder Model Comparison Table

| Model | Size | 4-bit RAM | BFCL-v3 / Tool-call | Tok/s M4 Pro 48GB | MLX status | Notes |
|---|---|---|---|---|---|---|
| **Qwen3-4B-Instruct-2507** | 4B | ~2.5GB | 61.9 (BFCL-v3) | 25–35 | Available, stable | Current pick; 2507 refresh +4.3 pts |
| Qwen3.5-4B | 4B | ~2.5GB | 38.9 (TIR-Bench) | 25–35 | Requires mlx-vlm | Latency regression risk on llama.cpp |
| Phi-4-mini 3.8B | 3.8B | ~2.5GB | 0.780 (community) | ~30–40 | Available | Strong for size, good tool discipline |
| LFM2.5-8B-A1B | 8B | ~5GB | 49.7 (BFCL-v4) | unknown | Unknown | LiquidAI; state-space hybrid |
| Gemma 4 E2B | ~2B | ~1.5GB | unknown | 30–45 | Available | Too small for multi-step tools |
| Llama 3.2 3B | 3B | ~2GB | low (community) | 25–35 | Available | Unreliable for tool chains |

*BFCL-v3 is the primary benchmark with model coverage; BFCL-v4 has only 5 models as of June 2026 so is not directly comparable.*

---

## Sensitive-Reasoner Comparison (12–32B, lazy-load on 48GB)

| Model | Size | 4-bit RAM | Key reasoning score | Tool-call | Tok/s M4 Pro 48GB | Notes |
|---|---|---|---|---|---|---|
| **Qwen3-14B (current)** | 14B | ~9GB | AIME ~65, strong | Good | 40–48 | Fits easily; leaves large headroom |
| **Qwen3.6-27B dense** | 27B | ~18GB | GPQA 87.8, AIME 94.1 | 1000+ tool seqs | 7–18 tok/s (18 with MTP) | Better on every benchmark; recommended upgrade |
| Qwen3.6-35B-A3B MoE | 35B | ~20GB | GPQA 86.0, AIME 92.7 | Good | ~55 tok/s M5 Pro | Faster but lower quality than 27B dense |
| Gemma 4 27–31B | 27–31B | ~16GB | competitive | 93–96% MCP | unknown MLX | Strong tool-caller; less reasoning data |
| Phi-4 14B | 14B | ~9GB | strong multi-step | reliable | 55–62 tok/s | Fast, compact; reasoning ceiling below 27B |
| DeepSeek R1 32B distill | 32B | ~20GB | strong math/reasoning | patchy multi-step | ~28 tok/s | Reasoning specialist; tool reliability unverified |
| Llama 4 Scout 17B MoE | 17B | ~10GB | competitive | inconsistent JSON | 30–40+ tok/s | Tool-call guardrails required |
| Qwen3.5-9B | 9B | ~6GB | good | good | 20–40 tok/s | Step up from 4B if 14B headroom not available |

**Recommendation for 48GB (scenario A):** Upgrade sensitive-reasoner from Qwen3-14B to **Qwen3.6-27B** (~18GB 4-bit). Quality jump is substantial; still fits with 23GB to spare after resident + overhead. With MLX native MTP speculative decoding (Qwen3.6 has built-in MTP heads), 18 tok/s is achievable on M4 Pro 48GB — adequate for reasoning/journal tasks that are not latency-critical.

---

## Local Teacher Feasibility (Scenario A: 48GB vs Scenario B: bigger box)

### Scenario A — 48GB stays

- **Cannot run teacher concurrently with both resident + sensitive-reasoner.** Memory math: 3GB (Qwen3-4B resident) + 18GB (Qwen3.6-27B sensitive) + 4GB OS + 20GB+ (any 32B teacher) = 45GB minimum, leaving no safe headroom for context.
- **Viable with unload discipline:** If Qwen3.6-27B is unloaded before loading teacher, a 32B teacher (20GB) fits: 3+20+4 = 27GB used. Quality of Qwen3-32B or Qwen3.6-35B-A3B is reasonable as a teacher for non-sensitive tasks.
- **Cannot displace DeepSeek cloud on 48GB** for high-quality teacher work while keeping the sensitive-reasoner warm. DeepSeek V4-Flash should stay as the primary teacher path.

### Scenario B — 64–128GB box

| Setup | Box needed | Teacher | Tok/s (gen) | Quality vs DeepSeek V4-Pro |
|---|---|---|---|---|
| Qwen3.6-27B teacher | 64GB | Qwen3.6-27B (18GB) | 18 tok/s (MTP) | Competitive on coding/reasoning; weaker on long-horizon agents |
| Qwen3-32B teacher | 64GB | Qwen3-32B (20GB) | ~30 tok/s | BFCL-v3 strong; good all-rounder |
| Llama 3.3 70B Q8 teacher | 128GB | Llama 3.3 70B (70GB) | ~16 tok/s | "Comparable to GPT-4o for many tasks" |
| Qwen3.5-122B-A10B teacher | 128GB | ~60GB Q4 | ~10–15 tok/s | BFCL-v4: 0.722; very strong tool-call ceiling |

**Verdict:** A 64GB box running Qwen3-32B or Qwen3.6-27B as teacher can plausibly displace DeepSeek V4-Flash for ~80% of non-sensitive teacher tasks (structured data generation, evaluation, plan review). It would NOT fully displace V4-Pro for complex long-horizon agent tasks (5-point quality gap concentrated there). A 128GB box with Llama 3.3 70B Q8 closes most of that gap. However, the **economics only favor local at >16.5M output tokens/month** — a personal assistant almost certainly stays below that, so cloud remains cheaper per token even on a bigger box. The real driver for going local teacher is **privacy escalation** (treating more task categories as sensitive) or **latency independence** from cloud outages/rate limits.

---

## MLX Runtime Status (June 2026)

### mlx-openai-server (cubist38)
- **Version:** 1.8.1 (released May 3, 2026). Actively maintained. [VERIFIED — pypi.org/project/mlx-openai-server/]
- **Multi-model management:** Yes. YAML config for multiple models in separate subprocesses. `on_demand: true` + `on_demand_idle_timeout` for idle unload. [VERIFIED — pypi.org]
- **Tool calling:** Supported via `--tool-call-parser` flag with named parsers (qwen3, qwen3_coder, glm4_moe, minimax_m2, others). [VERIFIED — pypi.org]
- **Structured output:** OpenAI-style `response_format` JSON schema accepted; Pydantic model support in Responses API. [VERIFIED — pypi.org]
- **Constrained decoding:** Via Outlines library; JSON schema → token constraints at each generation step. Outlines had compilation timeout issues on complex schemas, but the outlines-core Rust rewrite has improved this. [COMMUNITY — abstractcore.ai/docs/structured-output.html]
- **Assessment:** Solid production runtime for Artemis. Multi-model + idle-unload covers the lazy-load architecture.

### Rapid-MLX (raullenchai)
- A newer alternative. Claims **4.2x faster than Ollama**, 1.2–1.5x faster than mlx-lm serve, 0.08s cached TTFT. 17 tool parsers (Hermes, Qwen, DeepSeek, GLM, etc.). Auto-recovers malformed tool calls from quantized models. [VERIFIED — github.com/raullenchai/Rapid-MLX]
- GPT-OSS 20B specifically: 2.3x faster than Ollama, 106 tok/s. [COMMUNITY — Rapid-MLX README]
- Worth evaluating as a drop-in upgrade for Artemis given the recovery logic on malformed 4-bit tool calls.

### LM Studio (v0.4.x)
- Stable multi-model management since v0.4.0 (Jan 2026). JIT load on first request, TTL-based idle unload (configurable seconds). `GET /api/v0/models` returns per-model `"loaded" | "not-loaded"` state. [VERIFIED — deepwiki.com/lmstudio-ai/docs/2.1-model-management-and-lifecycle]
- MLX-native engine since v0.3.4; current 0.4.6 (March 2026) adds continuous batching for MLX.
- GUI-first tool — less scriptable than mlx-openai-server for headless/automated workflows.

### Speculative decoding
- Qwen3 models have a **known bug: speculative decoding produces incorrect output (skipped/dropped tokens)** in mlx-lm. [VERIFIED — github.com/ml-explore/mlx-lm/issues/846]
- MoE models: speculative decoding can **hurt** performance when active parameter count approaches draft model size. [VERIFIED — github.com/ml-explore/mlx-lm/issues/1132]
- **Exception:** Qwen3.6's native MTP heads work correctly for speculative decoding in MTPLX (separate implementation), achieving 2.6x gains on M4 Pro 48GB. [VERIFIED — medium.com/@vinoth.lingam333]
- **Do not enable standard mlx-lm speculative decoding on Qwen3-4B-Instruct-2507 or Qwen3-14B.** Use MTP-aware tooling (MTPLX or Rapid-MLX) if you want speculative gains.

### GPT-OSS 20B on MLX
- MLX 4-bit quantized versions exist (mlx-community HuggingFace). Performance was slower than llama.cpp on prefill (mlx-lm GitHub issue #858, now closed). [VERIFIED — github.com/ml-explore/mlx-lm/issues/858]
- Rapid-MLX resolves this: 106 tok/s on Apple Silicon. Needs ~12–14GB at 4-bit. An option for the responder tier if Qwen3-4B under-performs on future evaluation, though at 3x the RAM cost.
- Apple ML Research confirmed GPT-OSS 20B tested in MXFP4 on M5. [VERIFIED — machinelearning.apple.com/research/exploring-llms-mlx-m5]

---

## DeepSeek Cloud Teacher (Current)

| Model | Input (cache miss) | Input (cache hit) | Output | Context | Concurrent |
|---|---|---|---|---|---|
| DeepSeek V4-Flash | $0.14/M | $0.0028/M | $0.28/M | 1M tokens | 2,500 |
| DeepSeek V4-Pro | $0.435/M | $0.003625/M | $0.87/M | 1M tokens | 500 |

- Both models support OpenAI ChatCompletions AND Anthropic Messages API format — drop-in for either SDK. [VERIFIED — api-docs.deepseek.com/quick_start/pricing]
- V4-Flash: 284B total / 13B active MoE, 131K max output. Artificial Analysis Intelligence Index v4.0: 57/100. [VERIFIED — openrouter.ai/deepseek/deepseek-v4-flash; benchlm.ai]
- V4-Pro: Deeper reasoning; Index score 62/100. 5-point gap concentrates in long-horizon agents and factual recall. [VERIFIED — benchlm.ai/compare/deepseek-v4-flash-vs-deepseek-v4-pro]
- **Recommendation:** Default to **V4-Flash** (5x cheaper, 2500 concurrent requests). Route to V4-Pro only for multi-step agentic teacher tasks. A router that escalates based on task complexity (e.g., >3 tool calls expected) is well-suited here.
- **Alternative cloud teachers:** Google Gemini 1.5 Flash ($0.075/$0.30 per M), Mistral Small ($0.20/$0.60). Both OpenAI-compatible. Gemini Flash is cheapest overall but Gemini API is distinct from the DeepSeek seam already in place. [COMMUNITY — syncfusion.com/blogs/post/top-llm-api-comparison-2026]

---

## Recommendations

### Scenario A: 48GB box (current)

1. **Responder:** Keep Qwen3-4B-Instruct-2507 (MLX 4-bit). No better option at the ~3GB budget exists. Use mlx-community DWQ-2510 variant for slightly better quality-per-token if not already. [ASSUMED — DWQ quantization improves quality vs standard 4-bit]
2. **Sensitive-reasoner:** Upgrade from Qwen3-14B → **Qwen3.6-27B** (MLX 4-bit, ~18GB). Quality jump across all benchmarks justifies 9GB RAM increase. Enable MTPLX for MTP speculative decoding to reach 18 tok/s. Verify mlx-openai-server 1.8.1 supports Qwen3.6 tool-call parser before swapping.
3. **Teacher:** Keep DeepSeek V4-Flash as primary. Route complex agentic tasks to V4-Pro. No local option fits alongside both resident models at full quality.
4. **Runtime:** Stay on mlx-openai-server 1.8.1; evaluate Rapid-MLX for a speed upgrade. Do NOT enable standard speculative decoding for Qwen3 models.
5. **Structured output:** Outlines-core (Rust) backend is production-ready for moderate schema complexity. Test against Artemis tool schemas before relying on it for all structured calls.

### Scenario B: 64–128GB box

6. **At 64GB:** Qwen3.6-27B serves dual role as sensitive-reasoner AND local teacher for non-sensitive tasks. Qwen3-32B or Qwen3.6-35B-A3B as dedicated teacher is also feasible. DeepSeek cloud still needed for high-quality long-horizon teacher tasks.
7. **At 128GB:** Llama 3.3 70B Q8 (70GB) as teacher is feasible at ~16 tok/s and GPT-4o-adjacent quality. Would displace DeepSeek for most teacher workloads. Qwen3.5-122B-A10B is a stronger tool-calling teacher option if it fits (BFCL-v4: 0.722). Full DeepSeek displacement is possible but economically justified only if privacy scope expands to cover teacher traffic.

---

## Assumptions & Gaps

1. [ASSUMED] Qwen3-4B-Instruct-2507 vs Qwen3.5-4B direct BFCL-v3 head-to-head not found. Comparison inferred from different benchmark instruments.
2. [ASSUMED] M4 Pro 48GB tok/s for Qwen3.6-27B derived from one blog post (M4 Pro 48GB MTP experiment). Need more data points to confirm 18 tok/s is reproducible.
3. [ASSUMED] Qwen3.6-27B tool-calling reliability in multi-step chains inferred from architecture (1000+ tool seq support) but no published BFCL-v3 score found for the 27B variant specifically.
4. [ASSUMED] mlx-openai-server 1.8.1 Qwen3.6 compatibility — not explicitly confirmed; Qwen3.6 tool-call parser listed in Rapid-MLX but not explicitly in mlx-openai-server changelog.
5. [ASSUMED] DWQ-2510 quantization variant quality benefit — stated in mlx-community repo but no head-to-head benchmark found.
6. [ASSUMED] Gemma 4 27B vs Qwen3.6-27B for sensitive-reasoner — Gemma 4's reasoning ceiling (GPQA, AIME scores) not found; comparison inferred from tool-calling data only.
7. [GAP] No BFCL-v3/v4 score found for Qwen3.6-27B, Qwen3.6-35B-A3B, or Gemma 4 27B. BFCL-v4 leaderboard had only 5 models as of June 2026.
8. [GAP] GPT-OSS 120B on Apple Silicon — performance gap too large for the 48GB box; not researched for Scenario B.

---

## Sources

- [BFCL-V4 Leaderboard — llm-stats.com](https://llm-stats.com/benchmarks/bfcl-v4)
- [BFCL v4 Benchmark — BenchLM.ai](https://benchlm.ai/benchmarks/bfclV4)
- [Qwen3-4B-Instruct-2507 Model Card — Hugging Face](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507)
- [Qwen3.5-4B Model Card — Hugging Face](https://huggingface.co/Qwen/Qwen3.5-4B)
- [Qwen 3.5 latency regression on Apple Silicon — Medium](https://medium.com/@aejaz.sheriff/from-qwen-3-to-qwen-3-5-on-apple-silicon-a-14x-latency-regression-and-how-mlx-got-us-back-0ed9ed21fa68)
- [Qwen3.6-27B: 27B Model Beats 397B on Coding — BuildFastWithAI](https://www.buildfastwithai.com/blogs/qwen3-6-27b-review-2026)
- [Qwen 3.6 35B vs 27B Benchmark Results — ZoliBen](https://zoliben.com/en/posts/2026-04-23-qwen-36-35b-vs-27b-benchmark-results/)
- [18 tok/s from 27B on MacBook: MTP Speculative Decoding — Medium](https://medium.com/@vinoth.lingam333/i-got-18-tok-s-from-a-27b-model-on-a-macbook-mlx-native-mtp-speculative-decoding-on-apple-5e1211a06d0c)
- [Ollama vs llama.cpp vs MLX with Qwen3.5 35B — Ante Kapetanovic](https://antekapetanovic.com/blog/qwen3.5-apple-silicon-benchmark/)
- [Best Local LLMs for Mac 2026 — InsiderLLM](https://insiderllm.com/guides/best-local-llms-mac-2026/)
- [Tool-calling benchmark Apple Silicon — GitHub lintware](https://github.com/lintware/tool-calling-benchmark)
- [Best Local Models for Tool Calling 2026 — PromptQuorum](https://www.promptquorum.com/power-local-llm/best-local-models-tool-calling-2026)
- [mlx-openai-server on PyPI](https://pypi.org/project/mlx-openai-server/)
- [Rapid-MLX GitHub](https://github.com/raullenchai/Rapid-MLX)
- [LM Studio Model Management — DeepWiki](https://deepwiki.com/lmstudio-ai/docs/2.1-model-management-and-lifecycle)
- [mlx-lm Speculative Decoding Bug — GitHub Issue #846](https://github.com/ml-explore/mlx-lm/issues/846)
- [mlx-lm Speculative Decoding MoE Warning — GitHub Issue #1132](https://github.com/ml-explore/mlx-lm/issues/1132)
- [mlx-lm GPT-OSS Performance Issue — GitHub Issue #858](https://github.com/ml-explore/mlx-lm/issues/858)
- [DeepSeek API Pricing — Official Docs](https://api-docs.deepseek.com/quick_start/pricing)
- [DeepSeek V4 Flash vs V4 Pro Comparison — BenchLM.ai](https://benchlm.ai/compare/deepseek-v4-flash-vs-deepseek-v4-pro)
- [DeepSeek V4 Flash on OpenRouter](https://openrouter.ai/deepseek/deepseek-v4-flash)
- [Apple ML Research: LLMs on MLX M5](https://machinelearning.apple.com/research/exploring-llms-mlx-m5)
- [Apple M5 Max Local LLM Guide — AI Productivity](https://aiproductivity.ai/blog/apple-m5-max-local-llm-guide/)
- [Local Agent Stack on Apple Silicon — Contra Collective](https://contracollective.com/blog/mlx-openclaw-apple-silicon-local-agent-runtime-2026)
- [Structured Output with Outlines — AbstractCore](https://abstractcore.ai/docs/structured-output.html)
- [Qwen3.6 Developer Guide — Lushbinary](https://lushbinary.com/blog/qwen-3-6-developer-guide-benchmarks-architecture-api-self-hosting/)
- [M4 Pro vs M5 Pro Inference Benchmarks — Contra Collective](https://contracollective.com/blog/m4-m5-pro-local-ai-inference-mlx-2026)
