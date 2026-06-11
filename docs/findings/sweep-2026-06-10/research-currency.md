# Research Currency Audit — 2026-06-10

**Scope:** All of `docs/research/` (17 files) + the status.md "Parked (build phase)" list, spot-checked
against the live web as of 2026-06-10. Stack is LOCKED — verdicts are about research freshness only.

**Verdict legend:** CURRENT = research still holds · STALE = named facts changed · GAP = no research
exists but the build needs it.

---

## Axis 1 — Local model tier · **CURRENT**

**Doc:** `2026-06-08-local-model-tier.md` (2 days old, re-research clock 2026-06-22).

**Spot-check:** June 2026 roundups still converge on the doc's picks. Qwen3.6-35B-A3B is widely cited
as the best general 32GB-class MLX model ("instruction-following on par with hosted Claude Sonnet"),
and the doc already tables it (correctly noting the 27B dense outscores it on quality). Rapid-MLX is
still the noted speed alternative. `mlx-openai-server` latest is **1.8.1 (2026-05-03)** — exactly what
the doc records; no breaking changes since; v1.8.x emphasizes correct `--reasoning-parser` /
`--tool-call-parser` flags for new models. mlx-lm/MLX core actively maintained (MLX 0.31.0, Feb 2026).

**Residual open items (the doc's own ASSUMED list, still unresolved — carry into build gates):**
- mlx-openai-server tool-call-parser support for Qwen3.6 (doc ASSUMED #4) — verify before the
  sensitive-reasoner swap.
- Qwen3.6-27B 18 tok/s MTP figure rests on one blog post.

**Sources:** pypi.org/project/mlx-openai-server (verified 1.8.1 / 2026-05-03) ·
github.com/raullenchai/Rapid-MLX · insiderllm.com/guides/best-local-llms-mac-2026 ·
apxml.com/posts/best-local-llm-apple-silicon-mac · github.com/ml-explore/mlx-lm

---

## Axis 2 — Embeddings + reranking + LanceDB · **CURRENT** (one watch item)

**Doc:** `2026-06-08-retrieval-embeddings.md` (2 days old).

**Spot-check:** June 2026 guides still name **Qwen3-Embedding** as the open self-host default
("the open-source surprise of 2025-2026 … if you're self-hosting, this is the model to start with").
The only new entrant of note is Microsoft Harrier-OSS-v1 (MIT, MTEB v2 74.3) — but at 27B it is far
outside Artemis's embedding RAM budget; no sub-1B challenger to Qwen3-Embedding-0.6B surfaced.
Qwen3-Reranker remains unchallenged locally. LanceDB hybrid search (RRFReranker, `query_type="hybrid"`)
unchanged; 2026 LanceDB news (DuckDB SQL retrieval, HF Hub native Lance, git-style branching) matches
the doc.

**Watch item:** LanceDB blog references a "Lance SDK v1.0.0" milestone, but the Python `lancedb`
package is still 0.x (a GitHub releases fetch returned cached/ambiguous data — could not confirm a
Python 1.0). Pin the `lancedb` version at `uv add` time in M3-a and check the changelog then; the
encryption-at-rest gap the doc flags remains real (FileVault/encrypted-volume workaround stands).

**Sources:** knowledgesdk.com/blog/embedding-model-comparison-2026 ·
innovativeais.com/blog/best-embedding-models-for-rag-in-2026 · docs.lancedb.com/search/hybrid-search ·
lancedb.com/blog · duckdb.org/2026/05/21/test-driving-lance

---

## Axis 3 — Docling · **GAP**

**Coverage today:** No research doc exists. Docling appears only as an architectural reference
(brain.md, overview.md) and as an unpinned `uv add docling` in `docs/changes/M3-a-ingestion-pipeline.md`,
with real parsing gated on-hardware (Task 7) and Marker/MinerU escalation parked.

**What changed that the project has never absorbed:**
- **Heron layout model** (Dec 2025): new RT-DETRv2-based default layout engine — +23.5% mAP, much
  faster, much better reading order. Pipeline-choice-relevant.
- **Granite-Docling-258M** (Jan 2026, Apache 2.0): production VLM pipeline — an alternative *mode*
  to the classic convert pipeline.
- Project donated to **Linux Foundation AAIF** (early 2026) — governance/health positive.
- Version now **2.99.x**; Python 3.9 support dropped at 2.70 (Artemis is 3.11+, fine, but signals
  fast-moving release cadence — pin the version).

**Build need:** M3-a is early-spine. The spec leaves "which Docling pipeline" implicit. A short
currency dive should decide: classic (Heron) pipeline vs VLM (Granite-Docling) pipeline for the
PDF/docx corpus, MPS/macOS behavior, and a version pin.

**Sources:** github.com/docling-project/docling/releases · pypi.org/project/docling ·
docling-project.github.io/docling · idp-software.com/vendors/docling

---

## Axis 4 — M5 Mac Mini · **CURRENT** (timeline refined post-WWDC)

**Docs:** `2026-06-08-m5-pro-hardware.md` + `wwdc-2026-stack-implications.md` (06-09).

**Spot-check (post-WWDC press, i.e., newer than both docs):** Confirmed — **no hardware at WWDC 2026,
no M5 Mac Mini**. The wwdc doc's correction (M4 Pro 64GB configs sell today) and status.md's
re-decision ("wait for M5 Mini → buy M4 Pro 64GB", ADR-001 refinement 2026-06-09) are consistent with
reality. New data points since 06-09:
- Analysts now put the M5/M5 Pro Mac Mini at **late August–early October 2026**, with possible slips
  due to DRAM/supply constraints and AI-driven demand.
- Entry price expected to rise to ~$699–799 after the $599 model was discontinued; DRAM contract
  prices still climbing (Q2 2026 +58–63% projected) — waiting gets more expensive, not less.

**Net:** the buy-now-64GB decision is *strengthened* by post-WWDC reporting. Nothing to redo; fold the
Aug–Oct window into the next hardware re-research (clock 2026-07-08).

**Sources:** macrumors.com/2026/06/05/will-apple-launch-new-hardware-at-wwdc-next-week ·
macworld.com/article/2964754 · techrepublic.com/article/news-apple-m5-mac-mini-studio-ai-demand-wwdc ·
zaapgadget.com (buy-or-wait advice)

---

## Axis 5 — DeepSeek V4 Flash as coding executor · **GAP**

**Coverage today:** `2026-06-08-local-model-tier.md` covers V4-Flash only as a *teacher* (pricing,
Intelligence Index 57, API compat). No doc profiles it as the *spec executor* — yet ~59 ready specs in
`docs/changes/` will be batch-handed to it.

**What the June 2026 evidence says (executor-relevant):**
- **Coding is its strongest category**; on pure coding benchmarks Flash sits within 1.6 pts of V4-Pro.
  Fast (≈84 tok/s, ~1s TTFT), cheap, 1M context.
- **Agentic gap is large:** Terminal-Bench 2.0 Flash 56.9% vs Pro 67.9% — multi-step
  explore-decide-execute loops are its weak spot.
- **Weak factual recall:** SimpleQA-Verified 34.1% (vs Pro 57.9%) — it will not reliably "know" API
  details; the spec must carry them.
- Community reports describe output as "benchmark-maxed … execution often feels subpar, sloppy, and
  lazy"; a test produced syntactically correct code with logical flaws needing 3 prompt iterations.

**Build implication (validates + sharpens existing APEX spec rules):** specs must be literal execution
scripts — exact files, exact signatures, code-level snippets, zero exploration, one runnable check per
task, and per-task verify loops that catch logic flaws (acceptance tests, not eyeballing). A short
research note should turn these findings into a checked spec-authoring lint before batch handoff.

**Sources:** benchlm.ai/models/deepseek-v4-flash · blog.kilo.ai/p/we-tested-deepseek-v4-pro-and-flash ·
docs.bswen.com/blog/2026-05-25-deepseek-v4-pro-vs-flash-coding · artificialanalysis.ai/models/deepseek-v4-flash

---

## Axis 6 — Local STT/TTS/speaker-ID · **STALE**

**Coverage today:** No dedicated research file. The picks live inside `brain-architecture.md`
(2026-06-03): Parakeet-TDT-0.6B-v3 via FluidAudio + MLX-Whisper-large-v3-turbo (STT), Kokoro-82M via
MLX-Audio persistent server (TTS), Silero VAD, **SpeechBrain speaker-ID**, openWakeWord, Apple VPIO
AEC. Plus `wwdc-2026-stack-implications.md` separately recommends **Apple SpeechAnalyzer** for the
voice sidecar STT/VAD — an unresolved internal conflict with the Parakeet pick.

**What moved (named facts changed):**
- **TTS:** mlx-audio now ships **Qwen3-TTS** and **CosyVoice 3** (streaming, voice cloning, emotion
  tags) as built-in engines alongside Kokoro — Kokoro-82M is no longer the unambiguous local pick.
- **Speaker-ID/diarization:** **Sortformer** and Pyannote now run on Apple Silicon via MLX/CoreML
  (speech-swift toolkit, Feb 2026) — likely supersedes the SpeechBrain choice for speaker-ID.
- **Turn-taking:** **SmartTurn EOU** (ML end-of-utterance prediction) is replacing fixed
  silence-timer VAD in local Mac voice agents (e.g., jarvis-v3: Parakeet + Kokoro + SmartTurn + dual
  VAD — a working reference implementation of nearly the exact Artemis stack).
- Full-duplex speech-to-speech (NVIDIA PersonaPlex 7B on Apple Silicon, Feb 2026) exists as a
  watch-item, not a pick.

**Build need:** voice is a later milestone, but the picks are baked into brain.md. A refresh should
(a) resolve SpeechAnalyzer-vs-Parakeet, (b) re-pick TTS among Kokoro/Qwen3-TTS/CosyVoice 3,
(c) re-pick speaker-ID (Sortformer vs SpeechBrain), (d) add EOU/turn-taking (SmartTurn) to the design.

**Sources:** github.com/soniqo/speech-swift · github.com/Blaizzy/mlx-audio ·
github.com/mp-web3/jarvis-v3 · soniqo.audio · pypi.org/project/mlx-audio

---

## Axis 7 — Search providers (deep-research module) · **CURRENT**

**Doc:** `2026-06-08-search-providers.md` (2 days old).

**Spot-check:**
- **Tavily/Nebius:** ZDR survives the acquisition — Nebius is *marketing* Zero Data Retention
  ("inputs and outputs are never stored or reused") as a platform pillar post-deal. The doc's watch
  item is satisfied for this cycle; keep the periodic re-verify (status.md already mandates it).
- **Jina/Elastic:** Elastic states Reader/Embedding/Reranker APIs "continue as before"; pricing not
  materially changed. **One discrepancy:** current reviews cite **1M free tokens (non-commercial)**
  for new keys vs the doc's 10M — re-verify the free allowance at integration time. Long-term
  consolidation under Elastic's ML stack still expected within ~12 months.
- Brave default rationale unchanged (no contrary news found in this sweep).

**Sources:** futurumgroup.com (Nebius/Tavily ZDR) · nebius.com/newsroom ·
finance.yahoo.com (Elastic completes Jina acquisition) · linkstartai.com/en/agents/jina ·
jina.ai/reader

---

## Axis 8 — Parked decisions · mixed (two now have clearer answers)

| Parked item | Verdict | June 2026 state |
|---|---|---|
| **Graphiti vs Mem0** | CURRENT | No flip. Graphiti 1.x still requires structured-output-capable (large) models; small-model ingestion failures still documented. Build-custom verdict (agent-memory doc) holds. |
| **Pipecat vs Wyoming** | Clearer answer | 2026 consensus: **Wyoming is HA-ecosystem plumbing; Pipecat is the general Python voice-agent framework** (frame-streaming, interruption handling). For Artemis's own pipeline the likely answer is Pipecat-or-neither (custom Swift sidecar + Python), Wyoming only if/when the `aci-home` HA edge ships. Decide at voice-milestone time; no longer a 50/50. |
| **Litestream vs VACUUM** | STALE data point | Litestream **v0.5.0 shipped a full storage rewrite (LTX transaction-aware format, compaction windows)**; active through ≥Apr 2026. The parked comparison predates this — refresh briefly before the backup spec executes. VACUUM INTO remains the high-write-volume alternative. |
| **Headscale swap** | CURRENT | v0.28.0 (Feb 2026), healthy, 38.5k stars, explicitly aimed at self-hosters; single-tailnet design fits. No urgency; Tailscale-first plan stands. |
| **Local LoRA on Apple Silicon** | Minor STALE | mlx-lm LoRA/QLoRA/DoRA all current and well-documented. **Changed fact:** `mlx-tune` now claims native **SFT, DPO, GRPO** (plus vision/TTS/STT/embedding fine-tunes) on MLX — `homelab-control-plane.md`'s "RLHF/DPO stack is CUDA-only" (a P3 GPU-box driver) is no longer strictly true. Weakens (does not kill) the GPU-box pull-forward argument; verify mlx-tune maturity before relying on it. |
| 30B-A3B vs 32B teacher · embedding tier · macOS 26 · mic XMOS · backup device · 2nd box · watch LAN TLS · Tailscale ACLs · Maps connector · Habits/Goals | CURRENT (still correctly parked) | Nothing surfaced this sweep that ripens them early. |

**Sources:** github.com/getzep/graphiti · vectorize.io/articles/mem0-vs-zep ·
github.com/pipecat-ai/pipecat · home-assistant.io/integrations/wyoming ·
github.com/benbjohnson/litestream/releases · github.com/juanfont/headscale/releases ·
github.com/ARahim3/mlx-tune · github.com/ml-explore/mlx-lm

---

## Recommended follow-up research, ranked by build impact

1. **DeepSeek V4-Flash executor profile → spec-authoring lint** (Axis 5, GAP). Highest leverage: the
   batch handoff of ~59 specs is the very first build event, and Flash's documented failure modes
   (agentic weakness, weak recall, logic-flaw sloppiness) directly determine whether those specs
   execute clean. Output: a one-page executor profile + a checklist pass over existing specs (exact
   API facts inlined, per-task runnable verification, no exploration steps).
2. **Docling currency dive** (Axis 3, GAP). M3-a is early spine. Decide classic-Heron vs
   Granite-Docling-VLM pipeline, pin the version, note macOS/MPS behavior. Small (half-day) dive;
   prevents an on-hardware surprise at M3-a Task 7.
3. **Voice-stack refresh** (Axis 6, STALE). Resolve SpeechAnalyzer-vs-Parakeet, re-pick TTS
   (Kokoro vs Qwen3-TTS vs CosyVoice 3), speaker-ID (Sortformer vs SpeechBrain), add SmartTurn EOU.
   Later milestone, so third — but do it before any voice spec is written; the jarvis-v3 and
   speech-swift repos are ready-made reference implementations to study.
4. *(Smaller)* Litestream v0.5/LTX note before the backup spec · mlx-tune DPO/GRPO maturity check
   before ACI P3 sizing · confirm `lancedb` Python version + changelog at M3-a install · re-verify
   Jina free-token allowance at DR integration.
