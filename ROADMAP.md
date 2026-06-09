# Artemis — Roadmap (build order)

_The v1 core spine, in strict dependency/build order. **32 specs are READY in `docs/changes/`**
(`status: ready`, gated + manifest-applied 2026-06-08). Scope = `REQUIREMENTS.md`; subsystem map =
`docs/technical/architecture/overview.md`; brain core = `brain.md`; decisions = ADR-001..007. Spokes
(M8+) come after the core._

## ▶ Build handoff — start here (DeepSeek coding session on the Mini)

The whole core is specced and queued. To build: load this repo + start a DeepSeek (coding-mode) session and
ask it to build. The coding workflow (apex-code) reads `docs/changes/` for the ready specs and `docs/status.md`
for state. Rules:

1. **Build in milestone order M0 → M7.** Within a milestone, specs may run in parallel where their
   Prerequisites allow — each spec lists its own `## Prerequisites` + `## Files to Change`.
2. **M2-d is a HARD GATE.** It is the apex-security threat-model review over the M2 wall (M2-a/b/c).
   **M3 and M4 must NOT begin until M2-d returns PASS or CONDITIONAL-PASS.** (M5/M6 depend on M1/M2 but not on
   the M2-d verdict; M5's memory/knowledge seams are stubs until M3/M4 land.)
3. **On-hardware GATED tasks are now runnable** — the build runs on the Mini, so tasks marked
   `(GATED — on-hardware)` execute here: Secure-Enclave `.userPresence`, SQLCipher + sqlite-vec under
   encryption, the encrypted-volume mount lifecycle, AEC + <200ms barge-in, vision-model sizing on 48GB, the
   A.U.D.N. accuracy eval, decay tuning. **Record each gated result in `docs/handoff/YYYY-MM-DD.md`.**
4. **Each spec is an execution script** — build exactly what it says (rich on the *what*, stripped of *why*;
   the *why* lives in ADRs). The specs were gated clean (zero unresolved `[NEEDS CLARIFICATION]`); if a genuine
   fork still surfaces mid-build, stop and ask rather than guess.
5. **Per-spec close-out:** when a spec's acceptance criteria pass → move it to `docs/changes/done/`, update the
   `docs/status.md` In-Flight row, and commit (per the per-spec commit discipline in CLAUDE.md §5).
6. **Stack-skill gaps:** MLX, LanceDB, and the voice pipeline have no dedicated apex skill — build on the base
   + domain skills (`apex-python`, `apex-swift`) and the per-spec detail (ADR-001 coverage-gate note in status.md).

## Phases (core spine)

| Phase | Goal | Specs | Depends on | Status |
|-------|------|-------|------------|--------|
| **M0** Foundation | Package/config/paths (`/opt/artemis`), launchd + ntfy, mlx-openai-server 1.8.1, typed ports, build-agent isolation + backup skeleton | M0-a..e (5) | — | Ready |
| **M1** Thin brain | Manifest + RAG-for-tools registry; semantic router + router-first Brain (`respond_stream`/`pre_route`); gateway/CLI/SSE; time tool + heartbeat skeleton + e2e brain | M1-a..d (4) | M0 | Ready |
| **M2** Security wall | SE key-broker (DEK + per-scope encrypted-volume mount); scope model + data-layer crypto wall; broker client (mlock DEK, SQLCipher) + Tier-0 key + launchd/auto-login; **apex-security gate** | M2-a..d (4) | M0, M1 | Ready |
| **M2-d** Security gate | Blocking threat-model review over the M2 wall — verdict gates M3/M4 | M2-d | M2-a/b/c built + on-hardware spikes run | **GATE** |
| **M3** Knowledge / RAG | Ingestion → LanceDB on encrypted volume (idempotent, provenance); hybrid + RRF + reranker; agentic multi-hop (graph = gated spike); visual-doc (ColQwen2.5 Light/MPS-2.5.1 locked) | M3-a..d (4) | M0, M1, **M2-d PASS** | Ready (blocked on M2-d) |
| **M4** Memory | Bitemporal two-store schema (cardinality, A-MEM, never-hard-delete); A.U.D.N. write path on `sensitive_reasoner`; auto-inject + decay + owner view/edit/purge | M4-a..c (3) | M0, M1, M2, **M2-d PASS** | Ready (blocked on M2-d) |
| **M5** Voice | Audio sidecar (AEC/wake/VAD/<200ms barge-in); STT (Parakeet+Whisper) / TTS (warm Kokoro-82M); speaker-ID (ECAPA) + voice-ID≠key Tier gate; voice-loop orchestrator + instant-ack + latency budget | M5-a..d (4) | M1, M2 (M3/M4 seams stubbed) | Ready |
| **M6** Heartbeat | Scheduler tick-loop + hook contract; batched-LLM hit handling + urgency briefing; ntfy delivery + Tier-1 queue | M6-a..c (3) | M1, M2 | Ready |
| **M7** Teacher / recipe | Recipe format/store/signing; escalation → distill → replay + brain seam; dedupe/retire; promotion policy + review surface; curiosity loop | M7-a1/a2/a3, b, c (5) | M1–M6 | Ready |

_32 specs total. The dependency edges are also encoded per-spec in each `## Prerequisites` section — those are
the authoritative within-milestone ordering; this table is the global view._

## After the core — spokes (M8+, not yet specced)
Each spoke plugs into the hub via the **module contract** (manifest + typed tools + knowledge push + proactive
hooks + scope tags — see `overview.md` §"The module contract"). Order:
- **First wave:** Productivity & time (Calendar · Tasks · Projects · Habits/Goals) + the **Gmail** connector
  (feeds Comms + Finance). **Travel parked.** Later waves (Knowledge & capture, Awareness & inbound, Home &
  living, Health & body, Money, Dev & meta) are soft.
- **Post-gate backlog specs (drafted before the spokes — all READY):** observability/telemetry (OBS-a/b,
  ADR-008) · Deep-Research engine (DR-a/b/c, ADR-009) · **the CLIENT client app** (CLIENT-a/b/broker/c/d/e,
  ADR-010 + app-flow.md) — the owner-approval Review surface + Chat + Status, native iPhone/iPad, paired-device
  auth over the tailnet. The client sits at the **core→spoke boundary**: build it before the spokes, since
  write-enabled spokes (create event / send / complete) route their gated `TAKES_ACTION` recipes through its
  Review screen. Build order within CLIENT: a → b (+ broker) → c → d → e (per-spec `## Prerequisites`).

## How this roadmap was produced
SP0 phases 1–6: vision/scope → capability map → subsystem decomposition (`overview.md`) → conceptual data
model (`data-model.md`) → stack lock (ADR-001) → roadmap + spec queue. The M0–M7 specs were drafted, reviewed
(dispatched domain reviewers), readiness-gated, and the gate edit-manifests applied milestone-by-milestone
(record: `docs/drafts/gate-manifests/`). Hardware finalisation (ADR-001 §Deployment) is WWDC-pending.
