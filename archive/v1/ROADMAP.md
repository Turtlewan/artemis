<!-- aligned 2026-06-11 to remediated corpus (contracts.md frozen, Wave 0B done) -->
# Artemis — Roadmap (build order)

_The v1 core spine + first spoke wave, in strict dependency/build order. **60 specs are READY in `docs/changes/`**
(`status: ready`). Scope = `REQUIREMENTS.md`; subsystem map =
`docs/technical/architecture/overview.md`; brain core = `brain.md`; decisions = ADR-001..014._

## ▶ Build handoff — start here (DeepSeek coding session on the Mini)

The whole core + first spoke wave is specced and queued. To build: load this repo + start a DeepSeek (coding-mode)
session and ask it to build. The coding workflow (apex-code) reads `docs/changes/` for the ready specs and
`docs/status.md` for state. Rules:

1. **Build in milestone order M0 → M7 → OBS/DR/CLIENT → GATE → M8 (Gmail) → M8 (Calendar) → M8 (Productivity) → M4-d → M0-f.**
   Within a milestone, specs may run in parallel where their Prerequisites allow — each spec lists its own
   `## Prerequisites` + `## Files to Change`.
2. **M2-d is a HARD GATE.** It is the apex-security threat-model review over the M2 wall (M2-a/b/c).
   **M3 and M4 must NOT begin until M2-d returns PASS or CONDITIONAL-PASS.** (M5/M6 depend on M1/M2 but not on
   the M2-d verdict; M5's memory/knowledge seams are stubs until M3/M4 land.)
3. **GATE-a must precede all write-enabled spokes.** CAL-b, CAL-c, and any future write spoke call
   `ActionStagingService.stage()` — GATE-a is the producer. Build GATE-a before CAL-b.
4. **M4-a/b/c + M1-a/c must precede M4-d-1/2.** The entity-backbone specs extend the live M4 store and
   ToolRegistry — M4-d-1 first, then M4-d-2 (write-path wiring). Build M4-d before Finance/Health/Comms/Travel.
5. **GATE-b soft-depends on CLIENT-b/c/e.** Schedule GATE-b after CLIENT-b (+ broker) in the CLIENT wave.
   CAL-b's gated round-trip (Task 7) also needs GATE-b built; plan accordingly or mark that task deferred-with-GATE-b.
6. **On-hardware GATED tasks are now runnable** — the build runs on the Mini, so tasks marked
   `(GATED — on-hardware)` execute here: Secure-Enclave `.userPresence`, SQLCipher + sqlite-vec under
   encryption, the encrypted-volume mount lifecycle, AEC + <200ms barge-in, vision-model sizing on 48GB, the
   A.U.D.N. accuracy eval, decay tuning. **Record each gated result in `docs/handoff/YYYY-MM-DD.md`.**
7. **Each spec is an execution script** — build exactly what it says (rich on the *what*, stripped of *why*;
   the *why* lives in ADRs). The specs were remediated (Wave 0B conformance complete; ~63/67 BLOCKs resolved);
   if a genuine fork still surfaces mid-build, stop and ask rather than guess.
8. **Per-spec close-out:** when a spec's acceptance criteria pass → move it to `docs/changes/done/`, update the
   `docs/status.md` In-Flight row, and commit (per the per-spec commit discipline in CLAUDE.md §5).
9. **Stack-skill gaps:** MLX, LanceDB, and the voice pipeline have no dedicated apex skill — build on the base
   + domain skills (`apex-python`, `apex-swift`) and the per-spec detail (ADR-001 coverage-gate note in status.md).
10. **Shared contracts doc:** `docs/technical/contracts.md` is the frozen single source-of-truth for all
    cross-module seams (ModelPort, ToolRegistry, ActionStagingService, CalendarClient, heartbeat hooks, entity
    backbone, quarantine boundary, connector ports, pipeline seams). Bind to it — do not re-derive from individual specs.

## Phases (core spine — M0..M7)

| Phase | Goal | Specs | Depends on | Status |
|-------|------|-------|------------|--------|
| **M0** Foundation | Package/config/paths (`/opt/artemis`), launchd + ntfy, mlx-openai-server 1.8.1, typed ports, build-agent isolation + backup skeleton | M0-a..e (5) | — | Ready |
| **M1** Thin brain | Manifest + RAG-for-tools registry; semantic router + router-first Brain (`respond_stream`/`pre_route`); gateway/CLI/SSE; time tool + heartbeat skeleton + e2e brain | M1-a..d (4) | M0 | Ready |
| **M2** Security wall | SE key-broker (DEK + per-scope encrypted-volume mount); scope model + data-layer crypto wall; broker client (mlock DEK, SQLCipher) + Tier-0 key + launchd/auto-login; **apex-security gate** | M2-a..d (4) | M0, M1 | Ready |
| **M2-d** Security gate | Blocking threat-model review over the M2 wall — verdict gates M3/M4 | M2-d | M2-a/b/c built + on-hardware spikes run | **GATE** |
| **M3** Knowledge / RAG | Ingestion → LanceDB on encrypted volume (idempotent, provenance); hybrid + RRF + reranker; agentic multi-hop (graph = gated spike); visual-doc (ColQwen2.5 Light/MPS-2.5.1 locked) | M3-a..d (4) | M0, M1, **M2-d PASS** | Ready (blocked on M2-d) |
| **M4** Memory | Bitemporal two-store schema (cardinality, A-MEM, never-hard-delete); A.U.D.N. write path on `sensitive_reasoner`; auto-inject + decay + owner view/edit/purge | M4-a..c (3) | M0, M1, M2, **M2-d PASS** | Ready (blocked on M2-d) |
| **M5** Voice | Audio sidecar (AEC/wake/VAD/<200ms barge-in); STT (Parakeet+Whisper) / TTS (warm Kokoro-82M); speaker-ID (ECAPA) + voice-ID≠key Tier gate; voice-loop orchestrator + instant-ack + latency budget | M5-a..d (4) | M1, M2 (M3/M4 seams stubbed) | Ready |
| **M6** Heartbeat | Scheduler tick-loop + hook contract + `pre_tick_steps` async seam; batched-LLM hit handling + urgency briefing; ntfy delivery + Tier-1 queue | M6-a..c (3) | M1, M2 | Ready |
| **M7** Teacher / recipe | Recipe format/store/signing; escalation → distill → replay + brain seam; dedupe/retire; promotion policy + review surface; curiosity loop | M7-a1/a2/a3, b, c (5) | M1–M6 | Ready |

_32 core specs. The dependency edges are also encoded per-spec in each `## Prerequisites` section — those are
the authoritative within-milestone ordering; this table is the global view._

## Post-gate backlog (build before spokes)

These were drafted pre-gate and are all READY. Build in this order:

| Area | Specs | Depends on |
|------|-------|------------|
| **OBS** Observability | OBS-a (JSON logging + redaction), OBS-b (SQLCipher telemetry + token/cost/latency) | M0–M2 |
| **DR** Deep-Research | DR-a (untrusted/quarantine primitive), DR-b (SearchProvider + Fetcher + SSRF egress), DR-c (iterative dual-LLM researcher) | M1, M2, M7-c |
| **CLIENT** Client app | CLIENT-a (paired-device auth), CLIENT-b + broker (recipe Review + IPC), CLIENT-c (ArtemisKit; +macOS auth path per ADR-017), CLIENT-d (iOS app shell), CLIENT-e (screens), **CLIENT-f (macOS app — native Athena-style; ADR-017)** | M1–M7 |
| **GATE** Action-staging | GATE-a (`PendingActionStore` + `ActionStagingService`: stage/approve→execute-once/reject/expire — ADR-012), GATE-b (client `/app/actions/*` + DTOs + "Pending actions" tab on the Review screen) | GATE-a after M1; GATE-b after CLIENT-b/c/e |

> **ADR-012 note:** gated one-off external-effect writes are **`PendingAction` instances via `ActionStagingService`**
> (stage → owner-approves on Review "Pending actions" tab → execute-once via `_execute` twin — see `contracts.md`
> §GATE). This is distinct from the recipe Review tab. Write-enabled spokes route their gated actions through
> `ActionStagingService`, NOT through `TAKES_ACTION` recipes.

_12 specs in this wave (OBS×2, DR×3, CLIENT×7 including broker + the macOS CLIENT-f). GATE×2 are technically
part of the spoke prerequisite chain but spec'd here because they unblock the entire write-enabled spoke surface.
(CLIENT-f is `status: ready` — apex-swift + apex-security review applied 2026-06-12; ADR-017.)_

## First spoke wave (M8 — all READY)

Build order within the wave: **M8-a → M8-b1/b2 (Gmail) → CAL-a → CAL-b → CAL-c → CAL-d (Calendar) →
M8-d-a → M8-d-b → M8-d-c1 → M8-d-c2 (Productivity).**

| Milestone | Specs | Key dependencies |
|-----------|-------|-----------------|
| **M8-a** Google auth foundation | M8-a (1) | M0, M1 |
| **M8 Gmail** | M8-b1 (read-only connector: History-API sync, split-depth ingest, quarantined memory, 5 tools), M8-b2 (3-stage urgency hook via M6-c `pre_tick_steps`) | M8-a, M6-c (amended `pre_tick_steps`), DR-a |
| **M8 Calendar** | CAL-a (read/find_time/prefs/sync + full write surface per `contracts.md`), CAL-b (write + STRICT attendee gate → `ActionStagingService.stage` + activity log), CAL-c (overlay + 7 Tier-1 hooks + tentative projection), CAL-d (knowledge + A.U.D.N. memory + DR-a untrusted chokepoint) | CAL-a→b→c→d; **CAL-b requires GATE-a**; CAL-d requires DR-a |
| **M8 Productivity** | M8-d-a (Tasks+Projects+Areas: owned SQLCipher, 30 auto tools, both recurrence modes), M8-d-b (time-blocking: `task.schedule` + `calendar.schedule_task` + Task↔Event link), M8-d-c1 (hooks: Morning-plan/Overdue/Weekly-review, counts+IDs-only payload), M8-d-c2 (suggestion-inbox capture + capture-recipe graduation via `RecipeStore.write` CANDIDATE → M7-b owner-gated promotion + knowledge/memory push) | M8-d-a→b→c1→c2; M8-d-b requires CAL-a; M8-d-c2 requires M7-a1/b + DR-a |

_14 spoke specs (M8-a + M8-b1/b2 + CAL-a/b/c/d + M8-d-a/b/c1/c2)._

## Entity backbone + secrets-injection (tail of the queue)

| Spec group | Specs | Depends on |
|------------|-------|------------|
| **M4-d** Entity backbone | M4-d-1 (entity data layer: `entities`/`entity_aliases` + `EntityRepository` + `person_fact_key` + `EntityRef`), M4-d-2 (write-path auto-links fact subjects→PERSON + `memory.resolve_entity` tool) | M4-a/b/c + M1-a/c; M4-d-1 before M4-d-2. Gate before Finance/Health/Comms/Travel |
| **M0-f** Env injection | M0-f (`scripts/inject_env.py`: Keychain→`0600` slot `.env`, merge-not-clobber, ntfy-preserve; wired into `deploy.sh` pre-bootstrap) | M0 (can build standalone; `cross_model_review: true`) |
| **CAP** Capability/self-training | distill-datagen-pipeline (offline Windows-PC pipeline: Claude teacher → reasoning traces → DeepSeek-judge-filter → JSONL; `tools/distill/`) | Independent — run now (pre-Mini) to build training data |

_3 + 1 + 1 = 5 specs in this tail group._

## Spec count summary

| Wave | Specs |
|------|-------|
| Core spine M0–M7 | 32 |
| Post-gate backlog (OBS + DR + CLIENT + GATE) | 13 |
| First spoke wave (M8-a + Gmail + Calendar + Productivity) | 14 |
| Entity backbone (M4-d) | 2 |
| Env injection (M0-f) | 1 |
| CAP self-training | 1 |
| **Total ready** | **60** |

_All 60 specs are `status: ready` in `docs/changes/`; `done/` is empty. Dependency graph verified (no cycles) —
see `docs/findings/sweep-2026-06-10/cross-corpus-consistency.md` §Dependency-graph verdict._

## Designed-but-deferred (no specs yet)

- **Finance spoke** — DESIGNED (`docs/technical/modules/finance.md`); FIN-* specs pending the core + entity
  backbone (M4-d). Ledger-based; email-extraction + manual entry; no bank link; read-only/no GATE. Must bind to
  `person_fact_key` per ADR-013 before speccing.
- **Vision build-assistant** — DESIGNED + deferred (ADR-014). Overhead desk-vision HUD + voice-first
  guided-build assistant; a vision *input* subsystem (sibling to voice), Mini-local. Capability ladder:
  Rung 0 snapshot-ID → Rung 1 live HUD → Rung 2 assisted-verify → Rung 3 autonomous watch-and-verify.
  Rung 0/1 become the first specs when M3/M4/M5/DR/Projects/CLIENT land. Design:
  `docs/findings/desk-vision-hud-deep-dive.md`.
- **Later spoke waves** — Knowledge & capture, Awareness & inbound, Home & living, Health & body, Comms,
  Dev & meta. Travel parked.

## Corpus state (2026-06-11)

- **`docs/technical/contracts.md` FROZEN** — single source-of-truth for all 9 cross-module seams.
  All specs wave-0B-conformed (~63/67 BLOCKs resolved).
- **Wave 0B conformance: COMPLETE.** Pilot + 8 parallel agents covered all spec areas.
- **Remaining pre-handoff items:** owner decision queue (6 out-of-contract design calls) · Wave 2 doc-drift
  (overview.md, brain.md, data-model.md, calendar.md alignment) · final spec-lint pass against DeepSeek V4-Flash
  profile (`docs/findings/2026-06-11-deepseek-v4flash-executor.md`).

## How this roadmap was produced

SP0 phases 1–6: vision/scope → capability map → subsystem decomposition (`overview.md`) → conceptual data
model (`data-model.md`) → stack lock (ADR-001) → roadmap + spec queue. The M0–M7 specs were drafted, reviewed
(dispatched domain reviewers), readiness-gated, and the gate edit-manifests applied milestone-by-milestone
(record: `docs/drafts/gate-manifests/`). The M8 first spoke wave (Gmail + Calendar + Productivity), GATE,
OBS, DR, CLIENT, M4-d entity backbone, and M0-f were specced 2026-06-08–10. Hardware: wait for M5 (Pro) Mac
Mini → buy 64GB (ADR-001 §Refinement 2026-06-09).
