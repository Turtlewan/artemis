# Project: Artemis
_A personal assistant that integrates with everything (Jarvis-like in spirit), with a RAG-heavy second brain as its knowledge subsystem._

stack: LOCKED 2026-06-03 (ADR-001) — SwiftUI app + Swift audio sidecar · Python brain · MLX/mlx-openai-server · LanceDB · SQLite/SQLCipher · Claude-subscription teacher (bootstrapping, non-sensitive) · ntfy · MCP-at-edges · Mac Mini M4 Pro 48GB
token_profile: lean
autonomy_level: L3
specialists_default: [apex-security, apex-ai-systems]   # SP4 app defaults applied 2026-06-08
stack_skills: [apex-python, apex-swift]   # ADR-001 coverage gate. Gaps (no skill, build on base+domain): MLX, LanceDB, voice pipeline
backends: planning=claude | coding=deepseek-v4-flash

_Last updated by planning mode:_ 2026-06-10 (**Cross-module-links ADR — LOCKED → ADR-013.** Locked the 6
keystone decisions from `docs/research/cross-module-links.md` §Part 7: (1) canonical person pointer =
M4 `person_fact_key` (not ad-hoc strings); (2) logical `{module, entity_id}` ref resolved via ToolRegistry,
never cross-store joins; (3) lifecycle-sync (no orphans, generalizes M8-d-b auto-cancel); (4) hub views =
Brain query-time synthesis, not module joins; (5) bidirectional + auto-suggested links (no over-linking);
(6) **extend M4 as the entity backbone** + home **Person + Place + Goal** as M4 entity types — owner chose
end-state lock (all three committed now; detailed schema deferred to implementing specs). **Next concrete
build step = an M4-c amendment spec** (`memory.resolve_entity` + `person_fact_key` + Place/Goal schema) —
NOT yet written. Flagged follow-ups: shared `artemis.untrusted` helper refactor; overview.md should name
M4 as the entity backbone. ~56 specs ready (unchanged — ADR-only session).)
_Prior:_ 2026-06-09 (**WWDC + homelab + self-training research session.** Hardware DECIDED: wait for M5 Mini
→ 64GB (ADR-001 §Refinement). 4 research docs in `docs/research/`. Homelab framed as **ACI**, phased+trigger-
gated. Self-training reframed to **capability via reasoning-distillation** → ready spec `distill-datagen-pipeline`.
**Bring-up artifacts DONE** (RUNBOOK + SECRETS-INVENTORY). 2 gaps surfaced (env-injection script · repo-transfer,
since resolved). Camera module → BACKLOG.)
_Last updated by coding mode:_ never

<!-- Do not remove or rename the CODING:START/END or PLANNING:START/END comment markers. They are used by automated writers to locate their blocks. -->

<!-- CODING:START -->
## In-Flight
| What | Mode | State | File | Stopped at | Uncommitted |
|------|------|-------|------|------------|-------------|
| M8 first-spoke-wave | planning | ✅ COMPLETE · 0 parked | docs/changes/ | Gmail (M8-a/b1/b2) + Calendar (CAL-a/b/c/d) + Productivity (M8-d-a/b/c1/c2) + GATE (a/b) ALL READY. Module designs calendar/gmail/productivity.md complete. **M6-c was amended in place** (pre_tick_steps). Build-ready for batch handoff. | — |
| SP0 core | planning | ✅ complete · build-ready | docs/changes/ (~56 ready specs) | Core spine M0–M7 + OBS + DR + CLIENT + M8 (Gmail/Calendar/Productivity) + GATE. Batch handoff to DeepSeek when the Mini arrives (`ROADMAP.md` §"Build handoff"). | — |

_(no build until the Mini arrives — planning/specs only)_
<!-- CODING:END -->

<!-- PLANNING:START -->
## Pending Specs
_~56 specs `status: ready` in `docs/changes/`. **Zero parked spec drafts** — the first spoke wave is
complete. Listed by milestone in dependency/build order. Batch handoff to DeepSeek when the Mini arrives._

| Milestone | Specs | Summary |
|-----------|-------|---------|
| M0 foundation | M0-a..e (5) | repo/package layout + data-root `/opt/artemis`, launchd + ntfy, mlx-openai-server, ports, build-agent isolation |
| M1 thin brain | M1-a..d (4) | module-manifest + RAG-for-tools, semantic router + router-first Brain, gateway/CLI/SSE, time tool + heartbeat skeleton |
| M2 security wall | M2-a..d (4) | SE key-broker, scope + crypto wall, brain broker-client + Tier-0 key, **M2-d security gate** |
| M3 knowledge | M3-a..d (4) | ingestion (Docling→LanceDB), hybrid retriever, agentic multi-hop, visual-doc |
| M4 memory | M4-a..c (3) | bitemporal schema, A.U.D.N. write path, auto-inject + decay + owner surface |
| M5 voice | M5-a..d (4) | Swift audio sidecar, STT/TTS, speaker-ID + voice-Tier gate, voice-loop orchestrator |
| M6 heartbeat | M6-a..c (3) | scheduler tick-loop + hooks, batched-LLM HIT handling, ntfy delivery + Tier-1 queue. **M6-c amended 2026-06-09: `pre_tick_steps` async seam on `attach_to_heartbeat`/`compose_proactive` (for M8-b2).** |
| M7 teacher/recipe | M7-a1/a2/a3, b, c (5) | recipe format/store/signing, escalation→distill→replay, dedupe/retire, promotion + review surface, curiosity loop |
| OBS observability | OBS-a, OBS-b (2) | JSON logging + redaction; SQLCipher telemetry + token/cost/latency |
| DR deep-research | DR-a, DR-b, DR-c (3) | untrusted/quarantine primitive; SearchProvider+Fetcher+SSRF egress; iterative dual-LLM researcher |
| GATE action-staging | GATE-a, GATE-b (2) | ADR-012 owner-approval staging for one-off external-effect actions (distinct from recipe Review). GATE-a: `PendingActionStore` + `ActionStagingService` (stage/approve→re-dispatch-execute-once/reject/expire). GATE-b: client `/app/actions/*` + DTOs + Review "Pending actions" tab. The unblock for ALL write-enabled spokes. |
| M8 Gmail | **M8-a, M8-b1, M8-b2 (3, ready)** | M8-a Google auth; M8-b1 read-only connector (History-API sync, split-depth ingest, read-cache, quarantined memory, 5 tools); M8-b2 end-state 3-stage urgency hook (Stage-3 quarantined scoring via M6-c `pre_tick_steps`). All under `modules/gmail/`. |
| M8 Calendar | **CAL-a, CAL-b, CAL-c, CAL-d (4, ready)** | Full Calendar module. CAL-a read/find_time/prefs/sync; CAL-b write + STRICT attendee gate → `ActionStagingService.stage` + activity log; CAL-c overlay + 7 Tier-1 hooks + tentative projection; CAL-d knowledge + A.U.D.N. memory + DR-a untrusted chokepoint. Build a→b→c→d. |
| M8 Productivity | **M8-d-a, M8-d-b, M8-d-c1, M8-d-c2 (4, ready)** | M8-d-a Tasks+Projects+Areas core (owned SQLCipher, 30 auto tools, both recurrence modes); M8-d-b time-blocking seam (`task.schedule` + new `calendar.schedule_task` self-only focus-block + Task↔Event link + auto-cancel-old-block on reschedule); M8-d-c1 hooks (Morning-plan/Overdue/Weekly-review, payload=counts+IDs only); M8-d-c2 suggestion-inbox capture (quarantine-gated email detection → inert suggestion) + capture-recipe graduation (`RecipeStore.write` CANDIDATE → M7-b owner-gated promotion) + knowledge/memory push. |
| CLIENT client app | CLIENT-a, b, broker, c, d, e (6) | Paired-device auth + recipe Review + chat/status client (ADR-010). GATE-b extends its Review screen + endpoints. |
| CAP capability/self-training | **distill-datagen-pipeline (1, ready)** | Offline Windows-PC pipeline (`tools/distill/`): Claude-subscription teacher → reasoning traces (6 categories) → DeepSeek-judge-filter → versioned training-ready JSONL + eval hold-out. P0 of the ACI capability lane (`docs/research/homelab-control-plane.md`). Runs pre-Mac to fill the M5 wait; output feeds a later Mac-side MLX training spec. |

## Module design docs (per-spoke source-of-truth)
- `docs/technical/modules/calendar.md` — full/final Calendar surface (CAL-* source).
- `docs/technical/modules/gmail.md` — Gmail read-only mirror (M8-b source).
- `docs/technical/modules/productivity.md` — Tasks+Projects+Areas + time-blocking (M8-d source). All decisions LOCKED 2026-06-09.
- `docs/technical/modules/finance.md` — Finance spoke (DESIGNED 2026-06-09; **FIN-* specs PENDING core**). Owns ledger; email-extraction + manual, no bank link; awareness-first → full-brain end-state; 4 hooks; read-only/no GATE. A *later* spoke (needs M8-b/M3/M4/M6/M7/CLIENT).

## Idea capture
**`BACKLOG.md`** (project root) is the raw feature inbox — throw ideas in anytime ("backlog: <idea>").

## Next step — first spoke wave COMPLETE; remaining items are housekeeping/external
**RESUME HERE (next planning session):**
1. ✅ **Bring-up artifacts DONE 2026-06-09** — `docs/bring-up/BRING-UP-RUNBOOK.md` + `SECRETS-INVENTORY.md`
   written (drafted via AFK agents, persisted by planning). Both carry a Parked table for build-time seams.
2. ✅ **WWDC hardware re-decision DONE** — wait for M5 Mini → buy 64GB (ADR-001 §Refinement 2026-06-09).
3. **NEW gaps surfaced by bring-up drafting (see Open Questions):** (a) the launchd→Keychain `.env`-injection
   script is unspecced; (b) repo-transfer-to-Mini path undefined. Both are small specs/decisions.
4. **CAP workstream:** `distill-datagen-pipeline` is ready — build it in a coding session to start the
   pre-Mac data-gen drip (fills the M5 wait). Then define the 6-category generation prompts in detail.
5. (Optional) second-spoke-wave planning · **camera module** (BACKLOG, flagged for dedicated discussion) ·
   docs/spec-hygiene cleanup.

The entire first spoke wave (Gmail + Calendar + Productivity) + the owner-approval staging subsystem is
fully build-ready for the batch handoff. ~56 specs ready in `docs/changes/`.

**Build:** the owner does NOT build code on this machine — planning/specs only; DeepSeek builds on the
Mac Mini when it arrives (`ROADMAP.md` §"Build handoff — start here").

## Open Questions
- **✅ M8-d-c2 capture-recipe graduation — RESOLVED + built.** A recurring owner-approved capture becomes
  an **owner-behaviour-distilled CANDIDATE recipe** written directly via `RecipeStore.write` (M7-a1), then
  promoted through M7-b's `Promoter`/`RecurrenceStore`/`ReviewSurface` (TOUCHES_DATA → gated → PENDING →
  owner approves → ENABLED). It is a THIRD recipe-author alongside teacher (M7-a2) + curiosity (M7-c). NOT
  M7-c: its grounding gate requires ≥2 external web sources, which owner-derived automation can never have.
- **✅ Gated-action staging — RESOLVED (ADR-012 + GATE-a/b).** One-off external-effect actions are
  *pending actions* (`PendingActionStore` + `ActionStagingService`; stage → approve-on-Review → execute-once),
  NOT recipes. Complementary to the recipe Review (permission-now vs automate-later); recurrence feeds the
  recipe loop. CAL-b/c + future write spokes bind to it.
- **✅ Module-layout convention — RESOLVED.** Domain modules under `src/artemis/modules/<name>/`; shared
  Google auth stays in `src/artemis/integrations/google/`. M8-b1 migrated to `modules/gmail/`.
- **✅ Productivity design — COMPLETE** (`productivity.md`): Tasks+Projects+Areas; full 3-level time-blocking
  (gap-fill/completion-check hooks opted out); suggestion-inbox→learned-recipe capture; no Google-Tasks;
  both recurrence modes; hooks = Morning/Overdue/Weekly-review.
- **✅ M8-b2 pre-flight — RESOLVED.** M6-c gained an optional `pre_tick_steps` async seam (one param +
  await-loop + test); M8-b2's QuarantinedReader pre-flight runs there, keeping `check_ref` LLM-free and the
  full dual-LLM quarantine posture (raw mail never reaches the scoring model). NB: `pre_tick_steps` is global
  to the `compose_proactive` call — the composition root collects all modules' pre-flight callables.
- **✅ HARDWARE re-decision — DECIDED 2026-06-09 (ADR-001 §Refinement 2026-06-09).** WWDC was software-only
  (no M5 Mini). **Owner chose: WAIT for the M5 (Pro) Mac Mini, then buy the 64GB tier.** 64GB ceiling is
  identical M4 Pro vs M5 Pro, so waiting = free chip speed-up, no headroom cost (build is front-loaded). Now
  **pending: M5 (Pro) Mac Mini announcement** → confirm 64GB BTO at acceptable price, then purchase. Research:
  `docs/research/wwdc-2026-stack-implications.md`.
- **✅ Arrival-readiness artifacts — DONE 2026-06-09.** `PRE-ARRIVAL-PREP.md` + `docs/bring-up/BRING-UP-RUNBOOK.md`
  + `docs/bring-up/SECRETS-INVENTORY.md` all written. The runbook/inventory Parked tables list build-time seams.
- **✅ cross-module-linking — RESOLVED + LOCKED 2026-06-10 → ADR-013** (research basis:
  `docs/research/cross-module-links.md`). All 6 §Part 7 decisions locked: M4 `person_fact_key` canonical
  pointer · `{module,entity_id}` logical ref via ToolRegistry (no cross-store joins) · lifecycle-sync (no
  orphans) · hub views = Brain query-time synthesis · bidirectional + auto-suggested links · **extend M4 as the
  entity backbone homing Person + Place + Goal** (owner chose end-state lock — all three committed now, schema
  deferred to implementing specs). **NEXT BUILD STEP (not yet specced): M4-c amendment spec** adding
  `memory.resolve_entity` read-tool + `person_fact_key` convention + Place/Goal entity schema. Decide before
  Finance/Health/Comms/Travel are specced — they bind to the fixed pointer.
- **⚠️ Follow-ups spun out of ADR-013 (not locked there):** (a) shared `artemis.untrusted` boundary-helper
  refactor (currently re-implemented per-module); (b) ✅ `overview.md` updated 2026-06-10 — M4 named as the
  entity backbone + ADR-012/013 added to the ADR index; (c) first Tier-0 entity candidate still undecided.
- **⚠️ NEW gap — launchd→Keychain `.env`-injection script unspecced** (SECRETS-INVENTORY §P5 / RUNBOOK §P8).
  Referenced by M8-a/M0-b/DR-b/DR-c (Keychain → slot `.env` at service start) but the injection script itself
  is never specced. Load-bearing for the secrets-loading step. → small M0-b follow-up spec needed.
- **✅ repo-transfer — DONE 2026-06-09.** Local repo initialized + pushed to private GitHub
  **`Turtlewan/artemis`** (`main`, initial commit `8caa9b1`, 118 files = planning corpus only). `.gitignore`
  guards secrets/`.env`/`*.db`/keys + `.research/` + `.claude/settings.local.json`; `.gitattributes` = LF.
  On the Mini: clone via SSH **deploy key** (RUNBOOK Step 2c). Migrate origin to self-hosted Tailscale git
  later (ACI). Planning machine pushes over HTTPS (Git Credential Manager).
- **Capability self-training (ADR-001 §Refinement) — direction SET.** Make-it-smarter = reasoning-distillation
  from Claude (+DeepSeek judge) into a ~14B student; RAG+test-time-compute first (Tier 1). Pipeline = the CAP
  `distill-datagen-pipeline` spec; runs as the cross-phase ACI capability lane (`homelab-control-plane.md`).
- **DR / OBS follow-ups (deferred):** full CaMeL capability data-plane; `artemis.untrusted` reuse (M8-b1 +
  CAL-d are the first reuse); `TelemetrySource` rename + `trace_id` plumbing. Re-verify Tavily/Jina retention periodically.
- **First spoke wave (M8) — source-of-truth RESOLVED (ADR-011).** Email=read-only mirror; Calendar=mirror+
  write-through+overlay; Tasks/Projects/Areas=own. External-effect writes gate through GATE-a/b. Designs: calendar/gmail/productivity.md.
- **SP0 COMPLETE (all phases + bootstrap).** Reference: overview.md · data-model.md · brain.md · REQUIREMENTS.md ·
  ROADMAP.md · ADR-001..012 · research/*. ~55 specs ready in `docs/changes/`.
- **Build strategy = front-load ALL specs → batch handoff (2026-06-04).** Plan now (PC), accumulate in `docs/changes/`, hand the queue to DeepSeek when the Mini lands.
- **Stack LOCKED (ADR-001).** Teacher = Claude Opus via subscription (non-sensitive, bootstrapping). DeepSeek = optional fallback.
- **Deployment LOCKED (ADR-002).** Native + launchd · build-on-Mini · isolated build agent · Tailscale · dev→UAT→PROD · expand/contract migrations · local-only backups · native clients.
- **Parked (build phase):** Graphiti vs Mem0 · embedding tier · local teacher 30B-A3B vs 32B · macOS 26 ·
  Swift-vs-Python AEC · mic XMOS · Pipecat vs Wyoming · local LoRA · backup device + offsite · Headscale swap ·
  2nd build box · watch LAN TLS · Litestream vs VACUUM · Tailscale ACLs · Maps connector (Calendar travel-time) ·
  Habits/Goals (Productivity deferred sub-domains, time-blocking rail reserved).
<!-- PLANNING:END -->
