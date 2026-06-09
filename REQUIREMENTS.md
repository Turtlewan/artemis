# Artemis — Requirements

_Scope boundaries for the Artemis v1 core. Derived from SP0 (vision → capability map → subsystem
decomposition → conceptual data model → stack lock). The full subsystem map is
`docs/technical/architecture/overview.md`; the brain core is `docs/technical/architecture/brain.md`;
the decisions are ADR-001..007. This file is the in/out-of-scope contract; the **build order is
`ROADMAP.md`**; the live state is `docs/status.md`._

## Product intent
Artemis is a private, **local-first** personal assistant — "Jarvis in spirit" — for a single **owner**
(plus light, cryptographically walled-off access for trusted **guests** in physical vicinity). Voice and
text are co-equal surfaces; it reacts in <1s on the home LAN; all data stays on a dedicated **Mac Mini
appliance** and never touches the cloud (only an encrypted tunnel to the owner's own box). A RAG-heavy
"second brain" is its knowledge subsystem.

## In scope — v1 core spine (M0–M7)
The v1 deliverable is the **brain core + the security / knowledge / memory / voice / proactive / teacher
spine**, built *before* any domain spoke. Each milestone:

- **M0 — Foundation.** Python package + config/paths (data root `/opt/artemis`), launchd services + ntfy,
  mlx-openai-server 1.8.1 (YAML multi-model: resident responder + lazy `sensitive_reasoner` Qwen3.6-27B +
  embedder + reranker), the typed `ports/` scaffolding, build-agent isolation + a backup skeleton.
- **M1 — Thin brain.** The in-code module-manifest contract + RAG-for-tools registry; an embedding-based
  semantic router + the router-first reactive Brain (with `respond_stream` + `pre_route`); gateway + dev CLI
  + loopback SSE surfaces; a `get_current_time` tool + Heartbeat skeleton + the smallest end-to-end brain.
- **M2 — Security wall.** The Secure-Enclave key-broker (per-scope DEK wrap/unwrap, phone `UnlockProof`,
  per-scope encrypted-volume mount-on-unlock); the owner/guest scope model + the data-layer crypto wall;
  the brain-side broker client (mlock'd DEK, raw-hex SQLCipher open) + the Tier-0 proactive key + the broker
  LaunchAgent + owner auto-login. **M2-d is a blocking apex-security threat-model gate before M3/M4.**
- **M3 — Knowledge / RAG.** Ingestion (connector → Docling → late-chunk → embed → LanceDB on the encrypted
  volume, content-hash idempotent, provenance); the adaptive hybrid + RRF + Qwen3-Reranker retriever; the
  agentic multi-hop loop (GraphRAG = a gated build-time spike, agentic is the shipped default); visual-document
  understanding (Apple Vision OCR + Qwen3-VL + ColQwen2.5 Light / MPS 2.5.1 — locked).
- **M4 — Memory.** Two-store bitemporal schema (SQLCipher + sqlite-vec, relation-cardinality registry, A-MEM
  metadata, never-hard-delete); the A.U.D.N. write path (extraction + decision on the local `sensitive_reasoner`,
  grammar-constrained); auto-inject into the turn loop + decay scoring + the owner view/edit/delete/purge surface.
- **M5 — Voice.** The Swift audio sidecar (VoiceProcessingIO AEC, openWakeWord, Silero VAD + <200ms barge-in);
  STT (Parakeet + Whisper fallback) / TTS (warm Kokoro-82M, sentence-streaming); speaker-ID (ECAPA) + the
  voice-ID≠key Tier gate (Tier-1-while-locked → ask phone unlock); the voice-loop orchestrator + instant-ack +
  latency budget.
- **M6 — Proactive engine (Heartbeat).** The scheduler tick-loop + hook contract; batched-LLM hit handling +
  urgency briefing; ntfy delivery policy + the Tier-1 queue.
- **M7 — Teacher + recipe / curiosity loop.** Recipe format / store / signing; the escalation → distill → replay
  pipeline + the brain seam; dedupe / retire; the promotion policy + review surface; the curiosity loop.

**Stack (LOCKED — ADR-001):** SwiftUI app + Swift audio/broker sidecars · Python brain · MLX /
mlx-openai-server · LanceDB · SQLite/SQLCipher + sqlite-vec · Claude-subscription teacher (bootstrapping,
non-sensitive, quota-capped) · ntfy · MCP-at-edges · Mac Mini M4 Pro 48GB.

**Cross-cutting (every layer):** security (assume-injection / spotlighting, crypto owner↔guest wall,
least-privilege per module, human-in-loop on high-stakes, unlock-once-per-session); backup/durability
(one encrypted data dir + clean DB dumps; backup-ready now, device deferred); observability (self-confidence
+ escalation + token/cost logging); runtime token-frugality (cheap local/RAG path default).

**First interaction surfaces:** voice (one room) + the dev CLI / loopback API. The full chat app is a later
milestone; M1 ships the text surfaces + the gateway scope seam.

## Out of scope — v1
- **Domain modules / spokes (M8+)** — Finance, Calendar, Tasks, Projects, Notes/Journal, Comms (Gmail +
  Telegram, incl. Contacts), Cooking, Shopping, Health & Fitness, Doctor/Vet, News, Web crawler, Smart home,
  Dev workstation, Travel, Quote-of-the-day, etc. (full map in `overview.md`). First spoke wave =
  **Productivity & time + Gmail**; Travel parked; later waves soft.
- **Full chat app client + Telegram surface + vision input + remote multi-room satellites** — seamed in the
  core, built later.
- **The owner-approval Review screen (client surface)** — required by M7 (IG1=B) but its spec is TBD
  (post-gate backlog); until it lands, gated recipes park in PENDING and clearly-safe ones auto-enable.
- **Observability/telemetry engine + Deep-Research engine** — M7-c stubs them; concrete specs are post-gate backlog.
- **Offsite backup / NAS / 2nd build box / low-power clients (watch) / Headscale swap** — parked; the data
  layer is architected backup-ready now.
- **GraphRAG in v1** — a gated build-time spike only; agentic multi-hop is the shipped default.
- **Anti-spoof / liveness + per-guest voiceprint clustering** — noted-for-later, not v1.

## Open questions
- **Hardware re-decision** — M5 Pro Mac Mini vs the locked M4 Pro 48GB; the real lever is the 64GB RAM tier
  (unlocks a local Qwen3.6-27B teacher + the GraphRAG spike). Pending **WWDC 2026** (week of 2026-06-08).
  Decision rule + research in `docs/status.md` Open Questions.
- **On-hardware gated tasks** — many specs carry GATED tasks (Secure-Enclave `.userPresence`, SQLCipher +
  sqlite-vec under encryption, the encrypted-volume mount lifecycle, AEC + <200ms barge-in, vision-model
  sizing on 48GB, the A.U.D.N. accuracy eval, decay half-life tuning) that can only be proven **on the Mini**.
- **Post-gate spec backlog** — (1) observability/telemetry spec, (2) Deep-Research engine spec, (3) client-app
  Review screen — draft after `apex-init`, before the spokes.
