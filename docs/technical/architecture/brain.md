# Artemis Brain — Architecture Decisions (SP0-consolidated)

_Status: **decision layer, LOCKED where marked.** This is the crystallised output of the brain
super-deep-research (5 waves / 18 agents). Full reasoning, alternatives, and source URLs live in
[`../../research/brain-architecture.md`](../../research/brain-architecture.md) — this doc carries only
the decisions and where the open ones get resolved. Feeds the phase-3 System Overview (brain section)
and seeds the ADRs written at post-SP0 apex-init._

The brain is **the core of Artemis** (the hub, not a spoke): orchestrator + central knowledge layer +
episodic memory + ingestion pipeline + tool registry + identity/scoping + proactive engine.

---

## Research refinements — 2026-06-08 sweep (supersedes specific lines below)
A 5-agent brain/AI research pass (`../../research/2026-06-08-brain-ai-improvements-synthesis.md`)
re-validated this architecture; nothing structural changed. Four deltas — where they conflict with text
below, **these win:**
- **Sensitive reasoner: Qwen3-14B → Qwen3.6-27B** (dense, ~18GB 4-bit; fits the 48GB box with ~23GB headroom). Responder stays Qwen3-4B-Instruct-2507. → ADR-001.
- **GraphRAG: hard-deferred → gated build-time spike** — the "needs a stronger local model" trigger is now met (27B clears the extraction bar; constrained decoding guarantees relation-JSON validity). Evaluate LightRAG vs agentic multi-hop on a gold-set behind the `retrieve(query,mode)` port; **agentic stays the default** until proven. → ADR-007.
- **Memory:** absorb composite forgetting-score (retrieval-time re-rank, not deletion) + A-MEM note metadata + Graphiti 4-timestamp reference. Still custom SQLCipher+sqlite-vec. → ADR-004.
- **Visual-doc retriever locked: ColQwen2.5 Light (PyTorch MPS 2.5.1).** → ADR-007.
- **Runtime pins:** mlx-openai-server 1.8.1; do NOT enable mlx-lm speculative decoding on Qwen3 (bug #846) — use native MTP; pin sqlite-vec.
- **Hardware:** lock held (M4 Pro 48GB) pending WWDC this week; the lever is the **64GB RAM tier**, not the M5 chip (a Mini caps at 64GB either way — M5 Pro = GPU speed, not headroom).

---

## Invariants (the constraints every decision serves)
- **Local-first** — single Mac Mini, OSS. Cloud (DeepSeek) allowed for **non-sensitive** heavy work only.
- **Conversational-instant** — <1s react on LAN (instant answer, or instant ack + streamed result).
- **Runtime token-frugality** — cheap local path is the default; escalate only on need.
- **Automation-over-AI** — repeatable/deterministic tasks use scripts/rules, never the LLM.
- **Per-person** — owner full access / light guests, resolved by voice ID before routing.
- **Remember-almost-everything** — full episodic log, retrieved locally.
- **Upgradeability** — every internal choice sits behind a swappable port ("best today, replaceable tomorrow").

---

## Locked decisions

### Shape — thin custom orchestrator
**Gateway → Brain → Skills/Modules → Heartbeat.** No heavyweight framework (LangGraph/CrewAI = lock-in).
Borrow best-of-breed primitives behind ports.
- **Gateway** — voice/text ingress; resolves person (voice ID) + owner/guest scope, attaching scope to
  every request *before* the Brain sees it.
- **Brain** — small reactive loop, **router-first**.
- **Skills/Modules** — the ~25 self-built modules behind the internal tool registry.
- **Heartbeat** — always-on proactive engine (scheduled ticks, silent-success, ntfy).

### Routing — router-first (the frugality core)
Semantic router (embedding-based, ~3–7ms CPU, zero LLM tokens) classifies each request → picks a small
candidate tool set + path → **deterministic/automation path** for known tasks → **cheap local responder**
for simple turns → **escalate** (local teacher, or cloud DeepSeek for non-sensitive) only on a
confidence/complexity threshold. A **distilled-skill cache** short-circuits known task classes.
**Degrade-don't-crash:** model fallback → cached/static → per-module circuit breaker.

### Tool registry — keep all 25 modules' tools OUT of context
The single most important frugality decision (tool-selection accuracy collapses past ~30–50 in-context
tools). Each module ships a **manifest** (`tools[]`, `data_scope`, owner/guest `permissions`,
`proactive_hooks[]`, `ui`); manifests are indexed in the local vector store; only the relevant handful is
retrieved per turn (**RAG-for-tools**). Internal modules = local function/code calls; **MCP only at the
edges** (third-party / cross-machine / cross-language / risky-isolation).

### Retrieval — modern adaptive RAG (the document second brain)
- **Store:** **LanceDB** (embedded, ANN, MPS on Apple Silicon, multimodal, built-in hybrid + RRF).
  _sqlite-vec = brute-force → v0 prototype only, disqualified at life-corpus scale._
- **Embeddings:** Qwen3-Embedding-0.6B default (MLX); 4B as eval-gated quality tier.
- **Pipeline:** Docling parse → chunk (late chunking bulk; Contextual Retrieval for high-value) → embed →
  LanceDB (dense + BM25/FTS) → hybrid + **RRF** → local cross-encoder rerank (**Qwen3-Reranker**) →
  conditional agentic / graph.
- **Adaptive routing:** simple→hybrid+rerank (no LLM); complex→agentic; relationship→graph. Eval with RAGAS on a fixed gold-set.
- **Graph layer:** lazy/optional behind a `retrieve(query, mode)` port; default hybrid-flat, route only
  multi-hop "connect-the-dots" to graph. **fast-graphrag** (MIT) is today's candidate; design the adapter
  so real LazyGraphRAG swaps in when OSS. No pre-built community-summary index.

### Memory — two loosely-coupled stores (distinct from doc RAG)
- **Episodic** = bitemporal event log (event-time + ingestion-time, so corrections don't destroy history);
  **semantic** = (subject,relation,object) facts (vector+graph, conflict-resolution on write). Two logical
  stores, different indexes, **not** one unified engine.
- **Write path:** extract → **A.U.D.N.** (ADD/UPDATE/DELETE/NOOP, Mem0 pattern) to dedupe + resolve
  contradictions; run async/batched. Entity/relation extraction runs on the **teacher**, not the 4B.
- **Recall is a system property:** auto-inject relevant *structured facts* every turn (don't make the model
  decide to call a memory tool); retrieve from distilled tiers, never re-feed the raw log.
- **Forgetting:** recency × salience × access-frequency decay; **distill facts up to semantic before
  discarding** raw episodes; temporal invalidation (`invalid_at`) + explicit supersession for stale-confident facts.
- **Per-person:** `person_id` is a hard **partition key** on every node/edge/vector — owner gets full
  episodic+semantic; guests get only a tiny semantic preference profile.
- **Owner control:** facts atomic + provenance-linked → view/edit/delete; exposed via an OpenMemory-style MCP control surface.

### Inference + models
- **Runtime:** **`mlx-openai-server`** on MLX — one process, multiple resident models, on-demand load +
  idle-unload, OpenAI-compatible streaming + tool-calling + embeddings. **The OpenAI-compatible API is the
  swap seam** (swap runtime/relocate a model = change a base URL).
- **Responder (always resident):** **Qwen3-4B-Instruct-2507** (MLX 4-bit, ~3GB) — strongest small-model tool-calling.
- **Structured output:** **constrained decoding** (Outlines + mlx-lm) for ALL structured output — schema-valid
  JSON/tool-calls even from the 4B; no validate-retry loop.
- **Latency:** keep responder warm; cache the static system-prompt prefix; stream tokens; instant ack masks TTFT.

### Voice (cascaded, streaming every stage)
- Wake: openWakeWord ("Hey Jarvis" built-in) → STT: Parakeet-TDT-0.6B (FluidAudio/ANE) + MLX-Whisper-turbo
  multilingual fallback → local LLM → TTS: Kokoro-82M (persistent server, sentence-by-sentence as LLM streams).
- VAD: Silero (barge-in kills TTS <200ms). Speaker ID: **SpeechBrain ECAPA-TDNN** (enrol voiceprints →
  person scope; unknown → guest least-privilege). Voice-ID = **identity, not auth.**
- **AEC / barge-in:** Apple **VoiceProcessingIO** via a small Swift audio sidecar (TTS must render through the
  same engine) + Silero VAD on post-AEC audio + playback-state-aware threshold. Behind an `AudioFrontend` port;
  multi-room satellites are just more `AudioFrontend`s. XMOS USB mic array = fallback for far-field/loud rooms.
- **Latency budget:** end-of-speech → first audio ~750–800ms (LLM TTFT dominates; mask with an instant ack).

### Ingestion
Per-source connectors → normalized **`Document`** → **shared** chunk/embed/LanceDB. Docling = convergence hub
(Marker/MinerU escalation for hard tables/CJK); Apple Vision OCR; Qwen3-VL scene description; trafilatura
(+Playwright) web; yt-dlp + Parakeet/Whisper + ffmpeg keyframes for video/reels; parakeet-mlx + senko audio.
Idempotent via `content_hash`; provenance + locator (page/timestamp/bbox) on every chunk → deep-link +
selective re-embed on extractor upgrade.

### Proactive engine (Heartbeat)
Scheduled-tick-dominant + event injection only for true push sources. Per-module `proactive_hooks` manifest
(interval/cron · deterministic `check` · urgency · delivery · dedup_key · needs_llm). **Silent-success**
(`HEARTBEAT_OK`, zero idle tokens); only HITs escalate; deterministic checks + templates avoid the LLM;
**one batched LLM call per tick** for needs_llm hits. 3-tier urgency + defer-to-interruptible + batch-low→digest.
Briefing = a cron hook assembling module summaries in one LLM call. Delivery via **ntfy** (priority/tags/
quiet-hours-delay/action-buttons). Owner-tunable thresholds.

### Self-improvement — the "Curiosity Loop"
**IN, RAG/skill-only, NEVER weight fine-tuning.** Idle-triggered gap scan (escalation clusters · low-confidence
answers · recurring topics · staleness) → curriculum picks top gap → Deep-Research engine fills it (spotlighting
+ CaMeL on untrusted web) → **grounding gate** (≥2 independent EXTERNAL sources, URLs reachable — never
self-generated, anti-collapse) → distill to a RAG chunk or a self-verified **SKILL.md** → **stage → owner-gated
commit** via Heartbeat digest. Hard per-cycle + weekly token caps. Borrows Voyager auto-curriculum + ACE
delta-merge. Explicitly NOT SEAL weight updates nor self-code-rewrite.
- **Skill distillation:** Anthropic-standard SKILL.md (frontmatter + instructions + optional script); write a
  *candidate* on a verified teacher success; **promote only after the task class recurs (N≥2) or on owner
  command**; verify by replay against the original outcome; embed the *description* for retrieval; rule-based
  dedupe/retire (no LLM at library time); promotion owner-gated; sign skills.

### Security — assume the planning LLM WILL be injected
Enforce in deterministic code OUTSIDE the model.
- **Dual-LLM / CaMeL:** Privileged-LLM never sees raw untrusted content; Quarantined-LLM reads it with no tools;
  capability+provenance layer gates tools. **Spotlighting** on every retrieved chunk. All ingested content = untrusted data.
- **Tool execution:** typed function dispatch default for all ~25 modules + **one gated sandboxed code-exec
  module** (Apple `container` VM-per-exec on macOS 26, or `sandbox-exec`/Seatbelt fallback; no in-process/Pyodide/
  plain-Docker). Default-deny egress on code-exec; sensitive access + PII redaction + authz stay in the trusted runtime.
- **Owner↔guest wall by CRYPTOGRAPHY:** separate **SQLCipher** DB + separate vector index per scope; key in
  **Keychain/Secure Enclave** gated to owner biometric (a guest session physically lacks the key). FileVault + Keychain for secrets.
- **High-stakes:** risk-classified human-in-loop ladder (preview before send-money/email/delete); egress filtering
  (block markdown-image exfil). Remote = Tailscale deny-default ACLs + tagged devices, no public ports. Redacted audit log.
- **Multi-agent rule (Odysseus cautionary tale):** never wire a self-preservation / deletion incentive into any
  scorer; judges independent, agents stateless re their own "survival", rewards outcome-grounded.

### Cloud / privacy policy — sensitivity router (three trust tiers)
The model endpoint is a config-mapped role behind `ModelPort`; the sensitivity router gates **what data may
reach which tier**:

| Tier | Endpoint | May process |
|------|----------|-------------|
| **Local** (MLX) | on-box | anything, incl. sensitive (finance/health/journal/episodic/PII) |
| **Claude** (subscription) | Claude Code headless (consumer sub) | non-sensitive heavy reasoning + distillation. Consumer-sub data handling ≠ API no-train default → set training opt-out; **non-sensitive only** |
| **DeepSeek** (trains, CN) | API | **non-sensitive only** — hardest gate |

Router rules: (1) deterministic **provenance gate** — anything from a sensitive store or carrying PII is
hard-blocked from cloud (structural, via the CaMeL data plane); (2) local zero-shot classifier for free-text;
(3) **fail-safe → LOCAL when unsure.** Cloud only on affirmative `public` from both gates. Offline kill-switch.
**What must NEVER leave the box:** finance, health, journal, episodic/personal memory, PII, secrets, any RAG
chunk from personal stores. DeepSeek (first-party) trains on inputs with no opt-out + CN jurisdiction →
categorically unsafe for sensitive. Subscription-Claude is higher-trust (US, training opt-out available) but
consumer-tier, not the API's default-no-train → **both cloud tiers stay non-sensitive-only**; sensitive heavy
reasoning stays on the lazy local Qwen3-14B.

### Teacher model — Claude Opus is THE single teacher, via subscription, during bootstrapping (DECIDED 2026-06-03)
`teacher` role → **Claude Opus**, driven through the owner's **Claude subscription (Claude Code headless,
`claude -p` / Agent SDK)** — **NOT the Anthropic API.** Bootstrapping window only. Rationale: the teacher's
solution is **distilled into a permanent local skill**, so teacher quality is baked into every future local
execution of that task class — invest in the strongest reasoner while the skill library is being **seeded**;
also lifts Curiosity-Loop / Deep-Research distillation quality.

**Single teacher across ALL domains, incl. sensitive — boundary: Claude teaches the *how*, never sees the
sensitive *what*.** Two-role split:
- **Claude (teacher)** — reasons over non-sensitive tasks directly; for sensitive domains (finance/health/
  journal) it writes the *procedure* as a SKILL.md from the task description + **synthetic/representative
  examples, never real values**; drives deep research + curiosity loop.
- **Local model (executor + sensitive reasoner)** — runs Claude's skills against the **real** sensitive data
  on-box, and handles novel sensitive judgment no skill covers.
- The skill is the bridge: sensitive data and the teacher **never meet**.
- **Residual gap (unavoidable):** a *novel, judgment-heavy* sensitive question that no skill covers AND the
  local model can't crack — Claude can't help (can't see the data) → capped by local-model ability; only lever
  is a stronger *local* model (Studio path). The literal price of "sensitive never leaves the box."
- **Safeguard:** sensitive-domain skills run on real finance/health data → go through the standard skill
  guardrails (replay-verify · recurrence-gated · owner-gated promotion) before they ship; doctor/vet stay "fast
  answers, not advice" (caps blast radius).
- **DeepSeek demoted** to an optional cheap non-sensitive fallback (no longer the primary teacher).
- **Cost model = flat-rate quota, not per-token $.** The subscription removes the per-token cost objection
  entirely — the constraint becomes **usage caps shared with the owner's own planning/Claude Code work**
  (don't starve planning during heavy cold-start escalation).
- **Adapter note:** the subscription path is **not** an OpenAI-compatible base-URL swap — the `ModelPort`
  adapter for this tier wraps the **Claude Code CLI/SDK** (subprocess/SDK), constrained to a clean
  prompt→response teacher call (no agent tools needed). Thicker than the API adapter, but still behind the port.
- **Auth/ops note:** subscription auth = an OAuth login on the Mac Mini (`claude` CLI kept logged in + token
  refresh), not a static API key → re-auth fragility; if the login lapses the teacher path falls back to
  DeepSeek (non-sensitive) / local until re-logged-in.
- **Guardrail (set now):** a **usage/quota ceiling** so the teacher can't exhaust the subscription; on cap →
  fall back to DeepSeek (non-sensitive) / local. Owner-gated escalation; spend observable from the escalation +
  self-confidence telemetry the brain already logs.
- **Wind-down trigger = DEFERRED to build** (owner chose to decide later). For sustained/long-term load the
  "proper" backend is the API or a local 30B-32B teacher (added with a Mac Studio); subscription suits the
  bounded seeding phase. Candidate taper signals: escalation-rate · skill-library maturity · quota.
- Hardware unaffected: still **no resident local teacher**; lazy local Qwen3-14B stays for sensitive heavy reasoning.

### Hardware / deployment — DECIDED (owner call, 2026-06-03)
**Start box: Mac Mini M4 Pro, 48GB, ~1TB** (~S$2.4–2.8k; confirm BTO). Budget-driven; Mac Studio deferred.
**Dev stays on the owner's PC** — the Mini is a dedicated always-on Artemis appliance. **Strategy: push the
heavy/teacher tier to DeepSeek cloud (non-sensitive); keep a lean local core + a lazy-loaded local model for
sensitive work** — works because the teacher sits behind the OpenAI-compatible seam (cloud→local is a config
change when a Studio is added).
- **Local, always-resident (~15GB incl. macOS):** responder Qwen3-4B · voice (wake/STT/TTS/VAD/speaker-ID) ·
  embeddings + reranker (Qwen3 0.6B) · LanceDB + SQLite · orchestrator / sensitivity router / security.
- **Local, lazy-loaded (~33GB free):** a mid model (**Qwen3-14B** ~9GB) for **sensitive heavy reasoning**
  (finance/health/journal) + sensitive memory extraction — DeepSeek must never see this data.
- **Cloud (DeepSeek, NON-sensitive only):** the whole teacher tier — hard reasoning, deep research, analysis,
  non-sensitive extraction/distillation, bulk ingestion — run at SGT off-peak (00:30–08:30). No resident local teacher.
- **Cost control:** distillation loop turns each cloud solution into a local skill (cloud calls decline over
  time); automation-over-AI; DeepSeek prompt-caching.
- **Upgrade path:** add a Mac Studio later → strong local sensitive teacher + less cloud; or add a Mini over
  Thunderbolt 5, **role-split not model-split** (Mini = responder/voice/edge; Studio = teacher/memory/ingestion/research).

### Upgradeability — the ports (hard requirement)
Ports-and-adapters everywhere; the Brain depends only on ports:
`Retriever` · `MemoryStore` (with `person_id` + `as_of` in signatures) · `EmbeddingModel` (dimension locked in
store metadata; model change = explicit re-index migration) · `VectorStore` · `Reranker` · `Router` ·
`ModelPort` (OpenAI-compatible; models referenced by logical role "responder"/"teacher", mapped in config) ·
voice `WakeWord`/`STT`/`TTS`/`VAD`/`SpeakerID` as separate processes · module manifest = a versioned contract;
modules are plugins; an internal event bus carries proactive hooks; **skills are data** (declarative, loaded at runtime).

---

## Deferred — and where each gets resolved

### → Phase-5 stack re-confirm (apex-stack, before any build)
The brain research validates the **SwiftUI app + Python brain + MLX local** seed but does not formally lock it.
Carry these into stack re-confirm: Python brain/services runtime · MLX inference stack · LanceDB + SQLite/
SQLCipher · the OpenAI-compatible model seam · Swift audio sidecar (a non-Python component in an otherwise
Python brain).

### → Owner-judgment (decide at stack-confirm or first build)
Embedding tier 0.6B vs 4B (eval-gated) · teacher 30B-A3B vs dense 32B (the cloud-DeepSeek decision largely
moots a *local* teacher, but keep for the upgrade-to-Studio path) · TTS quality vs RAM (Kokoro vs Voxtral) ·
skill auto-promote for a low-risk class vs always owner-gated · multimodal/ColPali in v1 or later · target
**macOS 26** (unlocks Apple `container`) · Swift audio sidecar vs pure-Python AEC · mic plain vs XMOS upfront ·
**Graphiti-on-Kuzu vs Mem0 OSS** as the memory primary · Pipecat vs HA/Wyoming voice orchestration ·
**sensitive heavy-reasoning: default local Qwen3-14B vs allow Claude** (privacy call — DeepSeek NEVER allowed here).

### → Build-time empirical spikes (defer to build)
LanceDB sizing · inline-vs-async extraction · reranker in-process vs sidecar · GPU-contention/concurrency ·
fast-graphrag on small local models · CaMeL Q-LLM feasibility on local models · per-module action-risk ladder ·
barge-in tuning · PDF-class routing.

### → Parked (later phase)
Multi-room satellite rollout · speech-to-speech models (track, don't adopt) · skill dependency-graph (until the library is large).

---

## What this feeds
- **Phase-3 System Overview** (`overview.md`) — the brain section lifts the LOCKED layers above as the core subsystem.
- **Post-SP0 ADRs** (`../adr/`) — the load-bearing calls become individual ADRs: thin-orchestrator-not-framework ·
  router-first + automation-over-AI · LanceDB + adaptive RAG · two-store memory · cloud sensitivity-router +
  owner↔guest crypto wall · 48GB-Mini + cloud-teacher deployment · ports-everywhere upgradeability.
- **Phase-5 stack re-confirm** — the deferred stack items above.
