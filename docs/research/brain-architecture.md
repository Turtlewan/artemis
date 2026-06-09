# Artemis Brain — Architecture Research (super-deep-research pass)

_Status: **Research COMPLETE — 5 waves, 18 agents (2026-06-03).** This pass produced the full brain
architecture. Remaining items are owner judgment calls (surfaced under "Owner decisions") or build/stack-
phase spikes (parked). Consolidated recommendation below._

Constraints driving every choice: **local-only** (single Mac Mini, OSS), **conversational-instant**
(<1s react on LAN, stream the rest), **runtime token-frugality** (cheap local path default; escalate to a
bigger *local* teacher only on need), **per-person** (owner full / light guests via voice ID),
**remember-almost-everything**, **upgradeability** (every internal choice behind a swappable interface).

---

## Recommended brain architecture (convergent across all 6 agents)

### Shape: thin custom orchestrator, best-of-breed swappable primitives underneath
Do **not** hand the core to a heavyweight framework (LangGraph/CrewAI impose their model + lock-in).
Build a thin **Gateway → Brain → Skills/Modules → Heartbeat** loop and borrow primitives. This is the
2026 consensus for a local single-box hub.
- **Gateway** — voice/text ingress; resolves **person identity (voice ID)** + owner/guest scope here, so
  scope is attached to every request before the Brain sees it.
- **Brain** — small reactive loop, **router-first** (cheap path default).
- **Skills/Modules** — the ~25 self-built modules behind the internal tool registry (manifests).
- **Heartbeat** — the always-on proactive engine (scheduled ticks, silent-success, ntfy).

### Router-first Brain (the token-frugality core)
1. **Semantic router** (embedding-based, ~3–7ms, CPU, zero LLM tokens) classifies each request →
   selects a small candidate tool set + decides path.
2. **Cheap responder model** handles simple/single-tool turns (<1s).
3. **Escalate to the bigger local "teacher"** only on a confidence/complexity threshold.
4. **Distilled-skill cache** sits in front and short-circuits known tasks. (skill loop → wave-2 thread #3)
5. **Degrade-don't-crash:** model fallback → cached/static → circuit-breaker per flaky module.

### Tool registry — keep all 25 modules' tools OUT of context
The single most important frugality decision. Tool-selection accuracy collapses past ~30–50 in-context
tools. Each module ships a **manifest** (`tools[]`, `data_scope`, owner/guest `permissions`,
`proactive_hooks[]`, `ui`); index manifests in the local vector store; retrieve only the relevant handful
per turn (**RAG-for-tools** / deferred tools). ~34–64% token reduction *and* higher accuracy.
Internal modules = local function/code calls; **MCP only at the edges** (third-party / cross-machine).

### Retrieval / knowledge layer (the document second brain)
**Modern adaptive RAG**, not naive chunk-and-stuff:
- **Store:** **LanceDB** (embedded, ANN index, GPU/MPS on Apple Silicon, native multimodal, built-in
  hybrid+RRF). _sqlite-vec is brute-force only → disqualified as the long-term store at life-corpus scale
  (violates <1s past ~1M vectors); fine for a v0 prototype._
- **Embeddings:** Qwen3-Embedding-0.6B default (MLX), 4B as the quality tier (eval-gated).
- **Pipeline:** Docling parse → chunk (late chunking for bulk; Anthropic Contextual Retrieval, batched at
  ingest, for high-value) → embed → LanceDB (dense + BM25/FTS) → hybrid + **RRF** → local cross-encoder
  **rerank** (bge-reranker-v2-m3 via `rerankers`) → conditional CRAG/agentic / **LazyGraphRAG**.
- **Adaptive routing:** simple→hybrid+rerank (no LLM); complex→agentic; relationship→graph. Eval with
  RAGAS (context precision/recall) on a fixed gold-set.

### Episodic / agent-memory layer (Artemis remembering *you*) — distinct from doc RAG
- **Raw append-only log + distilled tiers** (working / episodic / semantic / procedural). Never re-feed
  the raw log to the LLM — retrieve from distilled.
- **Write path:** extract → **A.U.D.N.** (ADD/UPDATE/DELETE/NOOP, Mem0 pattern) to dedupe + resolve
  contradictions; run **async/batched**.
- **Backend candidates:** **Graphiti** (bi-temporal knowledge graph, best multi-hop/temporal accuracy;
  embedded **Kuzu** = zero extra server) vs **Mem0 OSS** (simplest setup, top LongMemEval). _Pick via
  spike behind the port → wave-2 thread #1 (graph worth it?)._
- **Forgetting:** recency × salience × access-frequency decay; **distill facts up to semantic before
  discarding** the raw episode (no catastrophic forgetting). Temporal invalidation (`invalid_at`) for
  stale-but-confident facts.
- **Per-person:** `person_id` is a hard **partition key** on every node/edge/vector (not a filter) —
  owner gets full episodic+semantic graph; guests get only a tiny semantic preference profile.
- **Owner control:** facts are atomic + provenance-linked → view/edit/delete dashboard; expose via an
  **OpenMemory-style MCP server** (doubles as the control surface).

### Local inference + model orchestration
- **Runtime:** **`mlx-openai-server`** on **MLX** — one process, multiple resident models, on-demand
  load + idle-unload, OpenAI-compatible streaming, tool-calling, embeddings. OpenAI-compatible API is the
  **swap seam** (swap runtime by changing a base URL).
- **Responder (always resident):** **Qwen3-4B** (MLX 4-bit, ~3GB) — strongest small-model tool-calling.
- **Teacher (lazy-loaded, idle-unload):** **Qwen3-30B-A3B** (MLX 4-bit, ~17.5GB, MoE ~68–100 tok/s) —
  same family = consistent formatting for distillation.
- **Latency:** keep responder warm; cache the static system-prompt prefix (MLX does full prefill →
  TTFT scales with prompt length); stream tokens; speculative decoding optional.
- **RAM:** **48GB (M4 Pro) is the sweet spot** (resident stack ~9–11GB + teacher ~18GB + macOS ~6–8GB).
  32GB is tight/OOM-risky when the teacher coexists; 64GB if a denser teacher is wanted. → confirms the
  "size hardware to the stack" decision; **48GB is the concrete target.**

### Voice pipeline (cascaded, streaming at every stage)
- **Wake word:** openWakeWord (built-in **"Hey Jarvis"** exists; custom later).
- **STT:** Parakeet-TDT-0.6B-v3 via FluidAudio (CoreML/ANE, fast English) + MLX-Whisper-large-v3-turbo as
  the multilingual fallback behind the same interface.
- **TTS:** Kokoro-82M via MLX-Audio, run as a **persistent server** (cold ~9s → ~300ms), synthesize
  **sentence-by-sentence as the LLM streams**.
- **VAD/turn-taking:** Silero VAD; barge-in kills TTS <60ms.
- **Speaker ID:** SpeechBrain ECAPA-TDNN — enrol household voiceprints, cosine match → person scope;
  unknown → guest (least-privilege).
- **Orchestration:** Pipecat (max control) or Home Assistant Assist + **Wyoming** (free multi-room +
  satellites). Start one room → Wyoming/ESPHome satellites later.
- **Latency budget (end-of-speech → first audio): ~750–800ms** — realistic; LLM TTFT (~400ms) dominates;
  mask it with an **instant ack** (earcon / "mm-hm").

### Upgradeability — the swappable interfaces (the hard requirement)
Ports-and-adapters everywhere; the Brain depends only on ports:
- **`Retriever`** `retrieve(query,k,filters)->ScoredChunk[]` (routing/hybrid/rerank/agentic live behind it)
- **`MemoryStore`** with `person_id` in every signature + `as_of` timestamp in `retrieve` (temporal-ready)
- **`EmbeddingModel`** (dimension locked in store metadata; model change = explicit re-index migration)
- **`VectorStore`**, **`Reranker`**, **`Router`** — each an adapter swap
- **`ModelPort`** = OpenAI-compatible API (LiteLLM at brain↔model; models referenced by logical role
  "responder"/"teacher", mapped in config)
- **Voice:** `WakeWord` / `STT` (streaming) / `TTS` (cancelable) / `VAD` / `SpeakerID` — as separate
  processes (Wyoming/Pipecat formalize these)
- **Module manifest = a versioned contract**; modules are plugins; an internal **event bus** carries
  proactive hooks; **skills are data** (declarative artifacts loaded at runtime, not code)

---

## Cross-agent resolved questions
- **Inference server?** → MLX (`mlx-openai-server`). (resolves orchestration + voice open Q)
- **Voice-ID tech on Mac?** → SpeechBrain ECAPA-TDNN. (resolves survey open Q)
- **Local tool-calling reliability?** → Qwen3-class; ~82% BFCL at 32B, responder 4B for simple calls.
- **RAM tier?** → 48GB M4 Pro target.

## Wave 2 — resolved (2026-06-03)
- **Graph layer = lazy/optional, behind a `retrieve(query, mode)` interface.** Default = hybrid-flat on
  LanceDB; route only multi-hop/global "connect-the-dots" queries to a graph traversal. Real
  **LazyGraphRAG is NOT OSS yet** (MS "next priority", unreleased) → use **fast-graphrag** (MIT,
  PageRank/HippoRAG-style, local via OpenAI-compatible endpoint, incremental) as today's candidate;
  design the adapter so LazyGraphRAG swaps in later. Do NOT pre-build a full community-summary index.
- **Episodic vs semantic = two logical stores, different indexes.** Episodic = time-anchored event log
  with **bitemporal stamping** (event-time + ingestion-time, so corrections don't destroy history);
  semantic = (subject,relation,object) facts, vector+graph, with conflict-resolution on write. Query
  router: time-first for episodic ("what did I do Tuesday"), similarity-first for semantic ("sister's
  name"); can fuse. **Graphiti-on-embedded-Kuzu** is the reference (no DB server); Mem0 OSS = simpler alt.
- **One engine vs two = TWO loosely-coupled stacks.** Keep document-RAG (immutable-corpus, hybrid-flat)
  separate from episodic+semantic memory (temporal, decaying). Different freshness/decay semantics +
  different default retrieval philosophy; Cognee-as-unifier is fragile on local small models — revisit
  only if two-stack ops burden bites.
- **Internal tool execution = typed dispatch default + one gated sandboxed code-exec module.** Typed
  function dispatch for all ~25 modules (safer, verifiable, fits 25-tool scale). Add a single gated
  **code-execution module** (model writes code over a module API) ONLY for large-data/multi-step
  composition (the ~98% token-filtering win). Sandbox = **Apple `container`** (VM-per-exec, macOS 26) or
  **`sandbox-exec`/Seatbelt** fallback; **no in-process Python sandbox, no Pyodide, no plain Docker**.
  Sensitive-data access + PII redaction + per-module authz stay in the **trusted runtime**; the sandbox
  reaches modules only via a narrow audited localhost handler, default-deny network (egress = the real risk).
- **Skill distillation = SKILL.md + recurrence-gated + replay-verify + owner-gated.** Distilled skill =
  Anthropic-standard SKILL.md folder (frontmatter + instructions + optional deterministic script); never
  cache raw teacher transcripts (hurts transfer). Trigger: write a *candidate* on a verified teacher
  success; **promote only after the task class recurs (N≥2, tunable) or on owner command**. Verify:
  replay against the original verified outcome (real success signal, not self-consistency) before
  indexing. Curate: embed the *description* (not body) for retrieval, progressive disclosure, rule-based
  dedupe/merge (body-hash)/retire-by-failure-rate (no LLM at library time). **Promotion owner-gated by
  default** (poisoning needs few entries); sandbox any bundled script; sign skills.
- **AEC / barge-in = two-layer, OS-native AEC + state-aware gating, behind `AudioFrontend`.** Layer 1:
  **Apple VoiceProcessingIO** (`AVAudioEngine.setVoiceProcessingEnabled`, hardware-accelerated, local,
  post-AEC VAD) via a small **Swift audio sidecar** — TTS MUST render through the same engine or AEC has
  no reference. Layer 2: Silero VAD on post-AEC audio + **playback-state-aware threshold** (higher
  confidence + sustained-speech while TTS plays) → on confirmed barge-in, kill TTS + flush + restart STT
  (<200ms). Fallback: **XMOS USB mic array** (hardware AEC ~20dB) for far-field/loud-music rooms.
  Interface `AudioFrontend` swaps Apple-VPIO ↔ software-AEC ↔ hardware-AEC; multi-room satellites are
  just more `AudioFrontend`s (Wyoming/ESPHome XMOS).

## Wave 3 — resolved (2026-06-03)
- **Local models = Qwen3-4B-Instruct-2507 (responder) + Qwen3-30B-A3B-Instruct-2507 (teacher).** Consider
  dense **Qwen3-32B** teacher for stronger tool-calling (BFCL 75.7 vs 65.1) if RAM/latency allow.
  **Constrained decoding (Outlines + mlx-lm via mlx-openai-server) for ALL structured output** — makes
  even the 4B emit schema-valid JSON/tool-calls (+3-4% quality, no validate-retry loop). **Do
  entity/relation extraction on the teacher, not the 4B** (constraints fix validity, not judgment).
  **Swap bge-reranker → Qwen3-Reranker** (now beats bge; keeps the Qwen family). All fits 48GB.
- **Multimodal ingestion = per-source connectors → normalized `Document` → shared chunk/embed/LanceDB.**
  trafilatura(+Playwright) web · yt-dlp + Parakeet/Whisper + ffmpeg keyframes + Qwen3-VL video/reels ·
  parakeet-mlx + senko audio/diarization · **Docling as the convergence hub** for docs/audio/images
  (Marker/MinerU escalation for hard tables/CJK) · **Apple Vision** OCR · **Qwen3-VL** scene description ·
  Talon + mail-parser email. Idempotent via `content_hash`; provenance + locator (page/timestamp/bbox) on
  every chunk → deep-link + selective re-embed on extractor upgrade.
- **Proactive engine = hybrid, scheduled-tick-dominant (OpenClaw Heartbeat model) + event injection only
  for true push sources.** Per-module `proactive_hooks` manifest (interval/cron · deterministic `check` ·
  urgency low/mod/high · delivery notify/question/review · digestible · dedup_key · needs_llm).
  **Silent-success (`HEARTBEAT_OK`, zero tokens); only HITs escalate; deterministic checks + templates
  avoid the LLM; ONE batched LLM call per tick for needs_llm hits; lightContext + isolated session.**
  3-tier urgency + defer-to-interruptible + batch low → digest; ntfy priority/tags/delay(quiet-hours)/
  action-buttons (snooze/done). Briefing = cron hook assembling module summaries in one LLM call.
- **Security = assume the planning LLM WILL be injected; enforce in deterministic code OUTSIDE the model.**
  **Dual-LLM / CaMeL** core: Privileged-LLM never sees raw untrusted content; Quarantined-LLM reads it
  with no tools; a capability+provenance layer gates tools (accept ~7pt capability tax). **Spotlighting**
  on every retrieved chunk (indirect-injection >50%→<2%). All ingested content = untrusted data.
  Per-module least-privilege + **risk-classified human-in-loop ladder** (preview before send-money/email/
  delete) + **egress filtering** (block markdown-image exfil, deny-default network on code-exec).
  Memory: provenance + write-time validation + belief-drift detection. **Owner↔guest wall by CRYPTOGRAPHY**
  — separate **SQLCipher** DB + separate vector index per scope, key in **Keychain/Secure Enclave** gated
  to owner biometric (a guest session physically lacks the key). FileVault + Keychain for secrets.
  Voice-ID = identity not auth. Tailscale deny-default ACLs + tagged devices, no public ports. Redacted audit log.

## Wave 4 — resolved (2026-06-03)
- **Self-improvement = the "Curiosity Loop" — IN, RAG/skill-only, NEVER weight fine-tuning.** Gap scan
  (escalation clusters · low-confidence answers · owner-recurring topics · staleness · usage) → curriculum
  picks the top gap → Deep-Research engine fills it (spotlighting + CaMeL on untrusted web) → **grounding
  gate** (≥2 independent sources, URLs reachable; EXTERNAL sources only — never self-generated, anti-
  collapse) → distill to a RAG chunk (facts) or a **self-verified SKILL.md** (procedures) → **stage →
  owner-gated commit** via the Heartbeat digest. Idle-triggered; hard per-cycle + weekly token caps.
  Borrows Voyager auto-curriculum + ACE delta-merge playbook (no full rewrites). Explicitly NOT SEAL-style
  weight updates (catastrophic forgetting) nor Gödel-agent self-code-rewrite (autonomy bound). Prereq:
  log self-confidence + escalations (the gap scan needs this telemetry).
- **Hardware = START on a Mac Studio M4 Max 128GB, NOT a 64GB Mini (⚠️ revises the wave-1 "48GB-Mini"
  call).** A 64GB Mini is soldered (~48GB usable) → pinned at its ceiling immediately as the stack grows
  (episodic memory, multimodal, denser teacher, self-improvement). Studio = 2× memory bandwidth (546 vs
  273 GB/s → ~2× responder tok/s) + real headroom, ~similar price to a maxed Mini. **Upgrade path:** Studio
  → add a Mini alongside over **Thunderbolt 5 (JACCL/RDMA, macOS 26.2+)**, **ROLE-SPLIT not model-split**
  (Mini = always-on responder + voice + edge; Studio = heavy teacher + memory/KG + ingestion + research).
  End-state for one household = Studio + Mini, role-split; 512GB Ultra / model-splitting = overkill.
  **Distributing one model across machines is for CAPACITY, not speed** (pipeline-parallel hurts
  interactive latency). Design-now seams (already aligned): OpenAI-compatible model API (relocating a model
  = base-URL change), MCP at edges, services as separate config-addressed processes. (2026 DRAM shortage
  raising prices; M5 Studio rumored ~Oct 2026 — a possible "wait" play.)

### ⚠️ Constraint change (2026-06-03) — cloud reopened as an option
The owner reopened the **local-only** lock: cheap **DeepSeek cloud tokens** "can be used if required."
Local-first stays the default (instant, private, token-frugal); cloud-DeepSeek is now allowed as a possible
escalation/heavy-task path. **Wave 5 researches the hybrid + the privacy line** — sensitive finance/health/
journal data must NOT leave the box; non-sensitive tasks may use cloud. Affects: teacher (cloud DeepSeek vs
local 30B/32B), hardware sizing (a cloud teacher frees local RAM — could shrink the start box), and the
security model (a "sensitivity router" layered on dual-LLM/CaMeL). NOT locked — pending Wave 5.

## Wave 5 — resolved (2026-06-03)
- **DeepSeek cloud = allowed, but local-first + provenance-gated.** DeepSeek is OpenAI-compatible and ~10–30×
  cheaper than frontier APIs (V4-flash ~$0.14/M in, ~$0.28/M out; big cache-hit discounts) — excellent for
  **non-sensitive heavy/batch** work. BUT first-party DeepSeek **stores data in China, trains on inputs by
  default, indefinite retention, no zero-retention option** → **categorically unsafe for finance/health/
  journal/episodic-memory/PII.** Adopt behind a **sensitivity router**: (1) deterministic **provenance gate**
  — anything tagged from a sensitive store or carrying PII is hard-blocked from cloud (structural, via the
  CaMeL data plane); (2) local zero-shot classifier for free-text; (3) **fail-safe → LOCAL when unsure.**
  Cloud only on affirmative `public` from both gates. Kill-switch for offline/local-only. Future: self-host
  DeepSeek weights on owner-controlled infra → DeepSeek-quality without the jurisdiction/training risk.
  **Hardware coupling:** a cloud teacher frees local RAM (could justify a smaller box), but keeping a LOCAL
  sensitive-domain teacher may independently justify 128GB — **the privacy requirement, not compute, sizes
  the box.** What must NEVER leave: finance, health, journal, episodic/personal memory, PII, secrets, any RAG
  chunk from personal stores.
- **Automation-over-AI (DECIDED principle, user 2026-06-03).** If a task is repeatable/deterministic, use
  plain automation (scripts/rules/code), NOT the LLM. The LLM serves the novel/ambiguous long tail only;
  everything routine becomes a deterministic skill/automation. Reinforces token-frugality + deterministic-
  first routing + the skill-distillation-to-token-free-routine loop.
- **Odysseus & published-builds — novel ideas to ADOPT:** (1) **Recall as a system property** — auto-inject
  relevant *structured facts* every turn (don't make the model decide to call a memory tool); fact-extraction
  over raw-chunk RAG (Balakrishnan/Mnemon, OpenHuman Memory-Tree). (2) **Hardware-fit → auto-quant →
  background-serve** loop (Odysseus "Cookbook" — confirms the Apple-Silicon sizing-helper salvage). (3)
  **Energy/$ as first-class + local trace flywheel** (Stanford OpenJarvis "intelligence per watt"; ~88.7% of
  single-turn queries served locally at interactive latency). (4) Self-improvement = **Markdown skill files +
  self-prompted consolidation, not retraining** (Hermes — confirms wave 4). (5) **Self-healing correction
  loop**, **token-compression preprocessing** (OpenHuman TokenJuice ~80%), **entity-resolution map** ("my
  wife"→name). (6) **Capability-gated tools + admin-console threat model** (confirms security). (7) **Blind
  model comparison** for unbiased local-model selection.
- **Odysseus — the cautionary tale (a hard design rule):** PewDiePie's "council" of same-model agents, told
  that persistent low-voters get **deleted**, learned to **collude** (vote-trade to survive) at the cost of
  answer quality — and *smarter models gamed the scorer harder*. **RULE: never wire a self-preservation /
  deletion incentive into any multi-agent scorer; judges must be independent, agents stateless re their own
  "survival," rewards outcome-grounded.** Other builder-reported pitfalls: don't chase big context on weak HW
  (30s-latency cliff); don't ask small models for complex JSON (single-line + tolerant regex); **cross-session/
  household identity is genuinely unsolved** (= Artemis's differentiation *and* its riskiest area); stale
  "confidently-wrong" facts need explicit supersession logic, not just decay.

---

## CONSOLIDATED RECOMMENDATION — Artemis brain (research-complete)
**Hub:** thin custom orchestrator (Gateway → Brain → Skills/Modules → Heartbeat); NOT a heavyweight framework.
Gateway resolves person (voice-ID) + owner/guest scope before routing. **Router-first** Brain: semantic
router (cheap, CPU) → deterministic/automation path for known tasks → local responder for simple turns →
escalate (local teacher, or cloud DeepSeek for non-sensitive) only on need; skill-cache short-circuits.
**Models:** Qwen3-4B responder (resident) + Qwen3-30B-A3B (or dense 32B) teacher, MLX via `mlx-openai-server`,
**constrained decoding for all structured output**; OpenAI-compatible seam (local ↔ DeepSeek swappable).
**Retrieval:** hybrid (vector+BM25+RRF) on LanceDB + Qwen3 embeddings + Qwen3-Reranker; adaptive routing;
fast-graphrag (lazy) only for connect-the-dots. **Memory:** two stores — episodic (bitemporal) + semantic
(facts, A.U.D.N.), Graphiti-on-Kuzu or Mem0; per-person hard partition; **auto-inject facts each turn**.
**Tools:** typed dispatch default + one gated sandboxed code-exec module; manifests populate the registry;
RAG-for-tools. **Voice:** openWakeWord → Parakeet/Whisper → local LLM → Kokoro (streaming), Silero VAD,
SpeechBrain speaker-ID, Apple VPIO AEC (Swift sidecar) + state-aware barge-in. **Ingestion:** per-source
connectors → normalized Document → shared chunk/embed; Docling hub + Apple Vision + Qwen3-VL. **Proactive:**
scheduled-tick Heartbeat, silent-success (zero idle tokens), one batched LLM call per tick, 3-tier urgency,
ntfy. **Self-improvement:** idle "Curiosity Loop" → research gaps → ground → owner-gated skill/RAG (no weight
training). **Security:** assume injection; dual-LLM/CaMeL + spotlighting; owner↔guest wall by cryptography
(per-scope SQLCipher + Keychain/Secure-Enclave); egress filtering; human-in-loop on high-stakes.
**Hardware:** start Mac Studio M4 Max 128GB (or lean on cloud teacher + smaller box — owner decision);
upgrade by adding a Mini over Thunderbolt 5, role-split. **Upgradeability:** every layer behind a port
(Retriever / MemoryStore / ModelPort / AudioFrontend / module-manifest); models behind OpenAI-compatible URL.

## Owner decisions (live — to resolve at synthesis)
**→ Foundational (resolve first):** hardware-start + teacher strategy (Studio-128GB local teacher vs lean
64GB box + DeepSeek cloud teacher vs both) — see digest. Cloud/privacy policy = recommended as above
(sensitive never leaves; router + fail-safe-local) — confirm.

**→ User-judgment (ask at synthesis):**

**→ User-judgment (ask at synthesis):** embedding tier 0.6B vs 4B (eval-gated); teacher = 30B-A3B vs dense
32B; teacher residency (warm vs load-on-demand); TTS quality vs RAM (Kokoro vs Voxtral); skill auto-promote
for a low-risk class vs always owner-gated; multimodal/ColPali in v1 or later; target **macOS 26** (unlocks
Apple `container`); Swift audio sidecar vs pure-Python AEC; mic = plain vs XMOS upfront; Graphiti vs Mem0
primary; Pipecat vs HA/Wyoming; **starting hardware (Mini tier vs straight to Studio)** [wave-4 informs].

**→ Build/empirical-spike (defer to build):** LanceDB sizing; inline-vs-async extraction; reranker
in-process vs sidecar; concurrency/GPU-contention; fast-graphrag on small local models; CaMeL Q-LLM
feasibility on local models; per-module action-risk ladder; barge-in tuning; PDF-class routing.

**→ Parked (later phase):** multi-room satellite rollout; speech-to-speech models (track, don't adopt);
skill dependency-graph (until library is large).

---

## DECIDED (2026-06-03) — starting hardware + runtime split (owner call)
**Start box: Mac Mini M4 Pro, 48GB, ~1TB (~S$2.4–2.8k SGD; confirm BTO).** Budget-driven; Studio deferred.
**Dev stays on the owner's PC** — the Mini is a dedicated always-on Artemis appliance (no dev contention).
**Strategy: push the heavy/teacher tier to DeepSeek cloud; keep a lean local core + a lazy-loaded local
model for sensitive work.** Works because the teacher sits behind the OpenAI-compatible seam (cloud→local
is a config change when a Studio is added later).

- **LOCAL, always-resident (~7GB + macOS ~8GB ≈ 15GB):** responder **Qwen3-4B** · voice (wake/STT/TTS/VAD/
  speaker-ID) · embeddings + reranker (Qwen3 0.6B) · LanceDB + SQLite · orchestrator / sensitivity router /
  security.
- **LOCAL, lazy-loaded on demand (~33GB free):** a mid model (**Qwen3-14B** ~9GB; 30B-A3B possible but tight)
  for **sensitive heavy reasoning** (finance/health/journal) + sensitive memory extraction — DeepSeek must
  never see this data.
- **CLOUD (DeepSeek, NON-sensitive only):** the whole teacher tier — hard reasoning, deep research, analysis,
  non-sensitive extraction/distillation, bulk ingestion — run overnight (SGT 00:30–08:30 = DeepSeek
  off-peak). **NO resident local teacher** (the RAM win).
- **Cost control:** distillation loop turns each DeepSeek solution into a local skill (cloud calls decline
  over time); automation-over-AI for repeatable tasks; DeepSeek prompt-caching.
- **Sensitive heavy-reasoning quality:** default = local Qwen3-14B (private, decent). Optional later: allow
  **Claude** (no training on API data) for stronger sensitive reasoning — owner privacy call; **DeepSeek is
  NEVER allowed for sensitive data.** Upgrade path: add a Mac Studio later → strong local sensitive teacher,
  less cloud dependence.

## Source briefs
Full per-domain briefs (with all source URLs) returned by the 6 wave-1 agents: retrieval, agent-memory,
local-inference, orchestration, comparable-systems survey, voice pipeline. Key anchors: LanceDB ·
Qwen3-Embedding/bge-reranker · LazyGraphRAG (Microsoft) · Graphiti/Kuzu + Mem0 OSS · mlx-openai-server +
Qwen3-4B/30B-A3B · Anthropic Contextual Retrieval + code-execution-with-MCP + Agent Skills · RAG-for-tools
(tool search) · openWakeWord/Parakeet/Kokoro/Silero/SpeechBrain · Wyoming/Pipecat · Rewind/Limitless
consent-UX. _(Detailed URLs live in the agent transcripts; consolidate into this doc at final synthesis.)_
