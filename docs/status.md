# Project: Artemis
_A personal assistant that integrates with everything (Jarvis-like in spirit), with a RAG-heavy second brain as its knowledge subsystem._

stack: LOCKED 2026-06-03 (ADR-001) — SwiftUI app + Swift audio sidecar · Python brain · MLX/mlx-openai-server · LanceDB · SQLite/SQLCipher · Claude-subscription teacher (bootstrapping, non-sensitive) · ntfy · MCP-at-edges · Mac Mini M4 Pro 48GB
token_profile: lean
autonomy_level: L3
specialists_default: [apex-security, apex-ai-systems]   # SP4 app defaults applied 2026-06-08
stack_skills: [apex-python, apex-swift]   # ADR-001 coverage gate. Gaps (no skill, build on base+domain): MLX, LanceDB, voice pipeline
backends: planning=claude | coding=deepseek-v4-flash

_Last updated by planning mode:_ 2026-06-13 (**LOCAL-LLM HARDWARE/SOFTWARE EXPANSION PLAN — researched, decided, PARKED (complete).**
Future-proofing the inference layer: run local DeepSeek-coding + Kimi-class-big-context with the M5 Mac Mini as orchestrator, heavy inference on a separate tailnet box. Research via 5 info-pull agents (4× Sonnet web + 1× Haiku corpus); synthesis + plan in `docs/research/2026-06-13-local-llm-expansion/` (`_SYNTHESIS-PLAN.md` + 5 source docs, every number cited). **All decisions resolved:** **A** model-flexible (ways-to-achieve menu + standing model-update process §7, not named models); **B** keep all buy paths open, trigger-gated T0–T3 (only certainty = buy the M5 Mini; box = live menu P-Apple/P-Xeon/P-Strix/P-RAG); **C** → C-2 extend trust boundary to the box under 5 binding controls (FDE · no-persistence serving · Tailscale-only · ADR+runbook+mini-security-review · fail-safe validator keeps sensitive inference Mini-local until verified). Key finding: **DeepSeek V4-Flash (284B, 1M ctx, ~128–192 GB Q4) may cover BOTH roles**, dropping the floor from 512 GB (Kimi-class). **APEX fit checked (§8 coding, §8b planning):** mode is set by the backend URL string (`*deepseek*`→coding, else→planning) → same weights can serve both via two LiteLLM aliases; coding endpoint MUST speak the Anthropic Messages API (Claude Code only speaks Anthropic). **D-plan-1 → "1 then 3"** (planning stays cloud-frontier now → fully-local distilled-from-Claude planner as end-state via CAP/M7); **D-plan-2 → research pullers local** (synth stays frontier). Software side is config-only (ModelPort already async/OpenAI-compat; LiteLLM gateway on Mini) — additive, does NOT touch the frozen ~61-spec corpus. Future specs **EXP-a** (remote routing) + **EXP-b** (box bring-up + C-2 review) drafted when a hardware trigger fires. 8 future-proofing items + 1 UI thread parked to BACKLOG.md.)
_Prior:_ 2026-06-13 (**Transcript review ("personal AI computer" video) — validation pass, no corpus change.**
The video's stack (Mac Mini · MLX/Ollama runtime · model portfolio · owned memory · MCP-with-permissions · scoped agents · local voice · cloud-as-visitor routing) maps ~1:1 onto locked Artemis decisions — nothing to change.
Checked its one substantive prompt, **auditable provenance**, against M4: covered + ahead (`facts.source_turn_id`/`extractor_model`/`extracted_at`/`confidence` + bitemporal `history()` + owner `view/history` "with provenance" + owner-edit tagged `extractor_model="owner"` + dimension-lock re-index guard). One open thread logged below: cross-store provenance (memory fact → M3 source doc). Lift-worthy framings noted only (no spec): "many surfaces / one stack underneath" feeds the paused UI thread.)
_Prior:_ 2026-06-12 (**ADR-016 (uniform async tool-dispatch) DECIDED + CASCADED — CORPUS IS BATCH-HANDOFF-READY.**
The last gate is cleared. Owner chose **option A (uniform async)** for the tool-dispatch surface: `ToolSpec.callable_ref`
is `Callable[..., Awaitable[BaseModel]]` — **every** tool callable is `async def` (front-door, `_execute` twin, read-only,
no-I/O alike), dispatched via `await` at the one uniform site in Brain (M1-b) + GATE (`approve` now `async def`). Rejected
heterogeneous-B (sync|async union) because it forces `inspect.isawaitable` branching `mypy --strict` can't enforce — the very
gate the spec-lint effort was built around. Wrote **ADR-016**; amended **contracts.md Seam 2 + Seam 3** (frozen rule). Ran the
**async cascade** (4 parallel AFK agents, area-grouped) across M1-a/M1-b/GATE-a/GATE-b/M1-d (core), CAL-a/b/c/d, M8-b1/b2,
M8-d-a/b/c2, M4-d-2 — every `callable_ref`→`async def`, every dispatch→`await`, test fakes→async; `HookSpec.check_ref` left
**sync** (Seam 5, not a tool callable). **Cleared both parked markers:** M8-d-c2 `LINT-DEFER` (RecipeStore.write await) +
M4-d-2 "resolve_entity stays sync" note. Verified corpus-wide: **zero stale `Callable[[BaseModel], BaseModel]` citations**
remain. No remaining sync/async inconsistency across the port (ADR-015) + dispatch (ADR-016) surfaces. **The ~61-spec corpus
is now fully batch-handoff-ready for DeepSeek when the Mini arrives.** **Also this session — macOS client surface decided
+ locked → ADR-017:** owner chose end-state **Mac + iPhone + iPad** (native, Athena-style, not a website). Research +
spec-audit confirmed the base is already cross-platform (ArtemisKit platform-agnostic; screens adaptive), so it's additive:
a separate native `ArtemisMac` target sharing ArtemisKit + an Athena-style scene (menu-bar + global-hotkey panel + window
+ Settings); Mac = another paired device. CLIENT-c amended (macOS auth path); CLIENT-f spec drafting AFK (then apex-swift +
apex-security review). Additive — does NOT gate the existing corpus. Research: `docs/research/2026-06-12-multiplatform-swift-client.md`.)
_Prior:_ 2026-06-12 (**FINAL SPEC-LINT PASS + FIX WAVE + ADR-015 async cascade — one decision from handoff-ready.**
Ran the **final DeepSeek V4-Flash spec-lint** over all 60 specs (10 parallel reviewers, 5-check executor profile) →
~32 BLOCK/18 specs, all amendment-drift residue + a few structural gaps; reports in `docs/findings/spec-lint-2026-06-11/`.
Applied an **AFK fix wave** (9 agents) — all mechanical + determinate-structural BLOCKs fixed (M4-a `FactRow`/`EpisodeRow`
defined, M3-c async, M3-d `IngestResult`, OBS-b usage→object, DR-c imperative-strip+canary, M7-a2 `DistillService`,
M7-c eTLD+1, GATE-a AC, CAL-c `cancel_event`, M8-d-b/c1/c2 counts+signatures, CLIENT `require_session`/keychain/D6).
Folded the `embedding_dimension` reconcile (it was a one-line doc-drift, no real Settings field). **Split M4-c** (owner)
→ **M4-c-1** (recall+auto-inject) + **M4-c-2** (decay+owner-surface). Resolved the M3-c async-seam fork → **ADR-015
(async port surface)**: owner chose **A2 (full)** — network-I/O ports (`ModelPort`/`EmbeddingModel`/`Reranker`/`Retriever`/
`MemoryStore` embed methods) are `async`, local-disk/cached stay sync; cascade applied across M0-d/M1/M3/M4/M7-a1 +
consumer sweep; contracts.md Seam 1 amended; `pytest-asyncio`+`asyncio_mode=auto` added to M0-a. Spec count 60 → 61.)
_Prior:_ 2026-06-11 (**CORPUS REMEDIATION — sweep actioned; corpus near handoff-ready.**
Calibrated the 2026-06-11 sweep (3/3 high-sev BLOCKs hand-verified real → B1 GATE-loop, B2/B5 interface fictions),
wrote `docs/findings/sweep-2026-06-10/REMEDIATION-PLAN.md`, cleared **Decision Gate D1–D4**, froze
**`docs/technical/contracts.md`** (10 cross-module seams; hardened with `EXECUTING`, `Usage`, Seam-6 GOAL, Seam-10
storage). Ran **Wave 0B conformance** (pilot + 8 parallel agents → ~63/67 BLOCKs; Wave 1 design-bugs subsumed),
**Wave 2 doc-drift** (ROADMAP 32→60, ADR-012 §3 EXECUTING, overview/brain/data-model/calendar aligned, skill→recipe),
**Wave 3 research** (DeepSeek-executor · Docling 2.99 Granite-VLM · voice stack — 3 docs in `docs/research/`), and
resolved + applied the **6-item decision queue D1–D6** (cloud-detect inject · Gmail {PRIMARY,UPDATES} · eager GOAL ·
hybrid SQLCipher+vault storage · per-slot git worktrees · iOS URL at pairing). **REMAINING (fresh session): final
DeepSeek spec-lint pass over all 60 specs + `embedding_dimension` reconcile = last gate to batch-handoff-ready.**
See the `corpus-remediation` In-Flight row + REMEDIATION-PLAN.md.)
_Prior:_ 2026-06-11 (**Camera/vision → vision build-assistant DESIGNED + deferred → ADR-014.**
Dedicated discussion reframed the camera backlog item from a home-cameras spoke into an overhead **desk-vision HUD +
voice-first guided-build assistant** (a vision *input*, sibling to voice; Mini-local, NOT an ACI edge box). apex-deep-dive
(3 research agents) pinned the pipeline: Apple Vision detect/track/OCR + open-vocab YOLOE in a new Swift **vision sidecar**
→ Qwen3-VL/MLX ID → M3/M4/web enrich; cloud-Claude escalation gated/opt-in/default-OFF. Honest verdict: the full
autonomous/general/verify-from-loose-context version is past reliable 2026 tech → build via a capability **LADDER**
(Rung 0 snapshot → 1 live HUD → 2 assisted-verify → 3 autonomous-watch). Locked DESIGNED-deferred (like Finance);
**Rung 0/1 = first specs when M3/M4/M5/DR/Projects/CLIENT land.** Findings: `docs/findings/desk-vision-hud-deep-dive.md`
(+ 2 widening-research agents FOLDED into ADR-014: alt-implementations + capability-menu). Also **DISCUSSED (not
specced)** the relationship/personal-CRM backlog cluster → converged on an on-demand **Person Briefing** core
(`docs/findings/person-briefing-discussion.md`; BACKLOG annotated, 4 facets reframed as opt-in extras). NB the
corpus-sweep remediation is still pending — see In-Flight.)
_Prior:_ 2026-06-11 (**FULL-CORPUS SWEEP (Fable 5, 11 parallel reviewers) —
corpus NOT handoff-ready.** 67 BLOCK · 62 UPGRADE · 130 FLAG · 39 RESEARCH across all ~60 specs.
Dominant failure = cross-spec interface fictions; worst bug = GATE-a approval re-dispatch loop;
quarantine leaks in M8-b1/b2 + M6-c. Synthesis + remediation sequence:
`docs/findings/sweep-2026-06-10/_SUMMARY.md` + 11 per-area reports. **Next session: review findings,
then plan the remediation wave starting with the contracts-freeze pass.** Session ended before
review — findings are unreviewed by owner.)
_Prior:_ 2026-06-10 (**Cross-module-links ADR — LOCKED → ADR-013.** Locked the 6
keystone decisions from `docs/research/cross-module-links.md` §Part 7: (1) canonical person pointer =
M4 `person_fact_key` (not ad-hoc strings); (2) logical `{module, entity_id}` ref resolved via ToolRegistry,
never cross-store joins; (3) lifecycle-sync (no orphans, generalizes M8-d-b auto-cancel); (4) hub views =
Brain query-time synthesis, not module joins; (5) bidirectional + auto-suggested links (no over-linking);
(6) **extend M4 as the entity backbone** + home **Person + Place + Goal** as M4 entity types — owner chose
end-state lock (all three committed now; detailed schema deferred to implementing specs). **The M4 entity-
backbone build is now SPECCED:** `M4-d-1` (entity data layer — entities/aliases/`person_fact_key`/`EntityRef`/
`EntityRepository`) + `M4-d-2` (write-path subject→PERSON wiring + `memory.resolve_entity` tool registered in
the ToolRegistry) — both `status: ready` in `docs/changes/`, drafted AFK + 4-reviewer pass (security+data ×2;
2 BLOCKs on `facts_for_entity` bitemporal predicate + index sargability resolved, all FLAGs folded). overview.md
+ data-model.md reconciled. Flagged follow-up: shared `artemis.untrusted` helper refactor. **Also specced `M0-f`**
(Keychain→`0600` slot `.env` injection — resolves SECRETS-INVENTORY P1/P5; persisted-`.env` mechanism; security
review folded; RUNBOOK/INVENTORY updated). ~59 specs ready.)
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
| SP0 core | planning | ✅ COMPLETE — batch-handoff-ready (all sweeps + ADR-015/016 cascades done) | docs/changes/ (~61 ready specs) | Core spine M0–M7 + OBS + DR + CLIENT + M8 (Gmail/Calendar/Productivity) + GATE all specced; 2026-06-11 sweep + final spec-lint remediation COMPLETE; ADR-015 (port) + ADR-016 (dispatch) async cascades applied. No remaining handoff blockers. | — |
| corpus-remediation | planning | ✅ COMPLETE — corpus batch-handoff-ready | docs/findings/spec-lint-2026-06-11/_SUMMARY.md | Sweep remediation (Waves 0–3 + D1–D6) + final spec-lint pass (10 agents) + fix wave (9 agents) + **ADR-015 async-port cascade** + **ADR-016 uniform-async-tool-dispatch cascade** ALL DONE. ADR-016 (owner: option A) cascaded across M1-a/b + GATE-a/b + M1-d + CAL-a/b/c/d + M8-b1/b2 + M8-d-a/b/c2 + M4-d-2 (4 parallel AFK agents); contracts.md Seam 2+3 amended; both parked markers (M8-d-c2 LINT-DEFER, M4-d-2 stays-sync note) cleared; verified zero stale sync citations. **No remaining gate — the ~61-spec corpus is fully batch-handoff-ready for DeepSeek when the Mini arrives.** | M1-a/b · GATE-a/b · M1-d · CAL-a/b/c/d · M8-b1/b2 · M8-d-a/b/c2 · M4-d-2 · contracts.md · ADR-016 (new) |
| macos-client (CLIENT-f) | planning | ✅ COMPLETE — CLIENT-f `status: ready` (drafted + reviewed + fixes applied) | docs/changes/CLIENT-f-mac-app.md | Owner chose end-state Mac+iPhone+iPad (full Athena-style). **ADR-017 written**; research → `docs/research/2026-06-12-multiplatform-swift-client.md`. **CLIENT-c/d/e amended** (Authenticating→ArtemisKit; AppCoordinating screen-seam; macOS auth path). **CLIENT-f drafted AFK** + **apex-swift + apex-security review applied** — 4 BLOCKs resolved (@MainActor panel + hotkey hop · Authenticating/AppCoordinating seam · **App Sandbox ON** (reversed ADR-017 §6 per security review) · exact dep pin + Package.resolved); FLAGs folded (sharingType=.none, lastError redaction, pasteboard note, passcode posture, deploymentTarget→14). overview/ROADMAP/ADR-index updated. App-Sandbox-ON reversal ✅ owner-confirmed. 2 hardware-gated auth unknowns remain for first Mac build. | ADR-017 · CLIENT-c/d/e · CLIENT-f (new, ready) · overview.md · ROADMAP.md |

| local-llm-expansion | planning | ✅ PARKED — plan complete, all decisions resolved | docs/research/2026-06-13-local-llm-expansion/_SYNTHESIS-PLAN.md | Future-proof inference layer (local DeepSeek-coding + Kimi-big-context; Mini=orchestrator, heavy inference→tailnet box). A/B/C + D-plan-1/2 all resolved. APEX fit checked (§8 + §8b). Software = config-only, does NOT touch frozen corpus. **Triggered follow-ups when a hardware trigger fires (T1 M5 Ultra ships / T2 Kimi-or-training need / T3 want local coding now):** draft EXP-a (remote-inference routing) + EXP-b (box bring-up + C-2 security review). | — |

_(no build until the Mini arrives — planning/specs only)_
<!-- CODING:END -->

<!-- PLANNING:START -->
## Pending Specs
_~61 specs `status: ready` in `docs/changes/` (M4-c split into M4-c-1/M4-c-2 on 2026-06-12). **Zero parked spec
drafts. Zero open gates** — ADR-015 (port async) + ADR-016 (dispatch async) cascades both applied 2026-06-12, so the
corpus is **fully batch-handoff-ready** for DeepSeek when the Mini arrives. Listed by milestone in dependency/build order._

| Milestone | Specs | Summary |
|-----------|-------|---------|
| M0 foundation | M0-a..e (5) | repo/package layout + data-root `/opt/artemis`, launchd + ntfy, mlx-openai-server, ports, build-agent isolation |
| M0 secrets-injection | **M0-f (1, ready)** | `scripts/inject_env.py`: Keychain→`0600` slot `.env` (merge-not-clobber; ntfy preserve-not-rotate), wired into `deploy.sh` pre-bootstrap. Locks the Keychain item map (P1) + the injection mechanism (P5). `cross_model_review: true`. |
| M1 thin brain | M1-a..d (4) | module-manifest + RAG-for-tools, semantic router + router-first Brain, gateway/CLI/SSE, time tool + heartbeat skeleton |
| M2 security wall | M2-a..d (4) | SE key-broker, scope + crypto wall, brain broker-client + Tier-0 key, **M2-d security gate** |
| M3 knowledge | M3-a..d (4) | ingestion (Docling→LanceDB), hybrid retriever, agentic multi-hop, visual-doc |
| M4 memory | M4-a, M4-b, M4-c-1, M4-c-2 (4) | bitemporal schema; A.U.D.N. write path; **M4-c-1** recall + auto-inject; **M4-c-2** decay + owner view/edit/delete/purge (M4-c split per owner 2026-06-12; M4-c-2 depends on M4-c-1). All async per ADR-015. |
| M4 entity backbone | **M4-d-1, M4-d-2 (2, ready)** | ADR-013 build. M4-d-1: `entities`/`entity_aliases` tables + `subject_entity_id` fact link + `EntityRepository` (resolve/alias/merge) + `person_fact_key` + `EntityRef`. M4-d-2: write-path auto-links fact subjects→PERSON entities + the `memory.resolve_entity` read-tool (ToolRegistry-registered cross-module resolver). Build M4-d-1→M4-d-2 (after M4-a/b/c + M1-a/c). Gate before Finance/Health/Comms/Travel. |
| M5 voice | M5-a..d (4) | Swift audio sidecar, STT/TTS, speaker-ID + voice-Tier gate, voice-loop orchestrator |
| M6 heartbeat | M6-a..c (3) | scheduler tick-loop + hooks, batched-LLM HIT handling, ntfy delivery + Tier-1 queue. **M6-c amended 2026-06-09: `pre_tick_steps` async seam on `attach_to_heartbeat`/`compose_proactive` (for M8-b2).** |
| M7 teacher/recipe | M7-a1/a2/a3, b, c (5) | recipe format/store/signing, escalation→distill→replay, dedupe/retire, promotion + review surface, curiosity loop |
| OBS observability | OBS-a, OBS-b (2) | JSON logging + redaction; SQLCipher telemetry + token/cost/latency |
| DR deep-research | DR-a, DR-b, DR-c (3) | untrusted/quarantine primitive; SearchProvider+Fetcher+SSRF egress; iterative dual-LLM researcher |
| GATE action-staging | GATE-a, GATE-b (2) | ADR-012 owner-approval staging for one-off external-effect actions (distinct from recipe Review). GATE-a: `PendingActionStore` + `ActionStagingService` (stage/approve→re-dispatch-execute-once/reject/expire). GATE-b: client `/app/actions/*` + DTOs + Review "Pending actions" tab. The unblock for ALL write-enabled spokes. |
| M8 Gmail | **M8-a, M8-b1, M8-b2 (3, ready)** | M8-a Google auth; M8-b1 read-only connector (History-API sync, split-depth ingest, read-cache, quarantined memory, 5 tools); M8-b2 end-state 3-stage urgency hook (Stage-3 quarantined scoring via M6-c `pre_tick_steps`). All under `modules/gmail/`. |
| M8 Calendar | **CAL-a, CAL-b, CAL-c, CAL-d (4, ready)** | Full Calendar module. CAL-a read/find_time/prefs/sync; CAL-b write + STRICT attendee gate → `ActionStagingService.stage` + activity log; CAL-c overlay + 7 Tier-1 hooks + tentative projection; CAL-d knowledge + A.U.D.N. memory + DR-a untrusted chokepoint. Build a→b→c→d. |
| M8 Productivity | **M8-d-a, M8-d-b, M8-d-c1, M8-d-c2 (4, ready)** | M8-d-a Tasks+Projects+Areas core (owned SQLCipher, 30 auto tools, both recurrence modes); M8-d-b time-blocking seam (`task.schedule` + new `calendar.schedule_task` self-only focus-block + Task↔Event link + auto-cancel-old-block on reschedule); M8-d-c1 hooks (Morning-plan/Overdue/Weekly-review, payload=counts+IDs only); M8-d-c2 suggestion-inbox capture (quarantine-gated email detection → inert suggestion) + capture-recipe graduation (`RecipeStore.write` CANDIDATE → M7-b owner-gated promotion) + knowledge/memory push. |
| CLIENT client app | CLIENT-a, b, broker, c, d, e + **CLIENT-f (macOS)** — 7 ready | Paired-device auth + recipe Review + chat/status client (ADR-010). GATE-b extends its Review screen + endpoints. **CLIENT-f (ADR-017): native macOS Athena-style target** (menu-bar + global-hotkey panel + window + Settings) sharing ArtemisKit; CLIENT-c/d/e amended (Authenticating→ArtemisKit, AppCoordinating seam, macOS auth path). `status: ready` — apex-swift + apex-security review applied (App Sandbox ON; 2 hardware-gated auth items remain). |
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
0. ✅ **ALL HANDOFF GATES CLEARED 2026-06-12.** Full-corpus sweep + final spec-lint + fix wave + **ADR-015 (port async)**
   + **ADR-016 (dispatch async)** cascades ALL DONE. The ~61-spec corpus is **fully batch-handoff-ready** for DeepSeek
   when the Mini arrives — no remaining blockers. (Optional pre-handoff polish only: a final mypy-consistency read of the
   async cascade once code exists; the agents flagged a couple of cosmetic import-line / closure-style judgment calls — see
   below.) Next planning work is forward-looking (CAP build-drip, second-spoke-wave, camera Rung 0/1, or hardware re-look).
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
- **NEW (local-LLM expansion plan 2026-06-13) — hardware expansion PLANNED, two decisions open.**
  Researched future-proofing the inference layer (run local DeepSeek-coding + Kimi-big-context;
  Mini = orchestrator, heavy inference → separate tailnet box). Plan + full research:
  `docs/research/2026-06-13-local-llm-expansion/` (`_SYNTHESIS-PLAN.md` + 5 source docs). **Resolved:**
  Decision A (model-flexible — plan a ways-to-achieve menu + a standing model-update process §7, not
  named models); Decision B (keep all buy paths open, trigger-gated T0–T3 — only certainty is buying
  the M5 Mini; inference box = live menu P-Apple/P-Xeon/P-Strix/P-RAG). Key finding: **DeepSeek
  V4-Flash (284B, 1M ctx, ~128–192 GB Q4) may cover BOTH roles**, dropping the floor from 512 GB
  (Kimi-class) to ~192 GB. Software side is **config-only** (ModelPort already async/OpenAI-compat;
  LiteLLM gateway on Mini; roles.toml alias swap) — additive, does NOT touch the frozen ~61-spec corpus.
  Decision C (sensitive-data boundary) **resolved → C-2**: the box MAY process sensitive data under 5
  binding controls (full-disk encryption · no-persistence serving config · Tailscale-only ingress ·
  ADR + bring-up runbook + mini security review · fail-safe validator keeps sensitive inference
  Mini-local until controls verified). **All three decisions A/B/C resolved — plan complete, no open
  gates.** Next action is owner-triggered (T1 M5 Ultra ships / T2 Kimi-or-training need / T3 want
  local coding now); then draft **EXP-a** (remote-inference routing) + **EXP-b** (inference-box
  bring-up + C-2 security review) specs. 7 future-proofing items added to BACKLOG.md.
  **APEX coding-system fit checked (`_SYNTHESIS-PLAN.md` §8):** fits — dual-backend design
  anticipated this — with 1 hard req + 4 adjustments. Hard req: the local coding endpoint MUST
  speak the **Anthropic Messages API** (Claude Code only speaks Anthropic; needs claude-code-router/
  LiteLLM passthrough; route URL must contain "deepseek" so the detection + write-gate hooks fire).
  Adjustments: A1 Claude Code runs on the Mini (box = pure inference, reinforces C-2); A2 serve
  coding on vLLM/SGLang for continuous batching + a max-parallel-workers cap (wave fan-out vs
  single-box throughput); A3 AFK build→big local model, Edit mode→fastest/cloud; A4 add OOM/
  server-down pause triggers + supervise the server. Cross-model review, planning mode, autonomy,
  hard blocks, and the frozen corpus all unchanged. A tiny future APEX-side tweak (per-backend
  worker cap + pause trigger) touches `~/.claude/skills/apex-code/`, NOT the Artemis corpus.
  **Planning-mode + research-models fit checked (`_SYNTHESIS-PLAN.md` §8b):** APEX mode is set by
  the backend *URL string* (`*deepseek*`→coding, else→planning), so a route named "deepseek" can
  only be coding; a non-"deepseek" local model is accepted as planning; the same weights can serve
  both modes via two LiteLLM aliases. **Recommendation: planning stays cloud-frontier by default** —
  it's low-volume, quality-critical (spec quality = the pipeline's failure variable), non-sensitive
  (design docs, not C-2 personal data), and subscription-flat-cost; local planning is an optional
  *resilience/independence* tier only (offline, de-correlated 2nd family, or a future distilled-from-
  Claude planner). Research fan-out: **puller tier** (web-fetch+extract; web access is the
  orchestrator's tool, model just summarises) is the best local target — saves the most cloud tokens
  at near-zero quality risk; **synthesizer/planner tiers stay frontier**. **D-plan-1 resolved →
  "1 then 3":** planning + research-synthesis stay **cloud-frontier** near/mid term (local-fallback
  middle option skipped); **end-state goal = a fully-local planner distilled from Claude via the
  CAP/M7 lane** (names spec-authoring as a distillation target, gated on a §7.3 spec-authoring eval
  reaching frontier parity). Follow-on: `distill-datagen-pipeline` should reserve a planning/
  spec-authoring generation category (→ BACKLOG). **D-plan-2 resolved → move pullers local:** research
  puller tier (web-fetch+extract) runs on a cheap local model (Mini/box small model); planner+synth
  stay cloud-frontier; web access stays the orchestrator's tool. EXP-a wires a `research-puller` local
  alias. **All expansion decisions (A/B/C + D-plan-1/2) now resolved — plan complete; EXP-a/EXP-b
  drafted when a hardware trigger fires.**
- **NEW (transcript provenance check 2026-06-13) — cross-store fact provenance unverified.** M4 within-memory
  provenance is solid (`source_turn_id` → episodic turn; `extractor_model`/`extracted_at`/`confidence`; bitemporal
  `history()`; owner view/edit "with provenance"). Open: does a fact extracted during **M3 document ingestion** carry a
  pointer back to its **source M3 chunk/document**, or does `source_turn_id` bottom out at a conversational turn only?
  Lives in **M4-b** (write path) + the **M3↔M4 seam** — not checked this session. If the latter, it's a small provenance
  gap. **Resume = read M4-b + M3↔M4 seam, decide whether document-sourced facts need a chunk pointer.**
- **✅ TOOL-DISPATCH ASYNC — RESOLVED + CASCADED 2026-06-12 → ADR-016.** Owner chose **option A (uniform async)**:
  `ToolSpec.callable_ref` is `Callable[..., Awaitable[BaseModel]]` — every tool callable is `async def`, dispatched via
  `await` at the one uniform site in Brain (M1-b) + GATE (`approve` now `async def`). Rejected heterogeneous-B (sync|async
  union) because its `inspect.isawaitable` branching defeats `mypy --strict`. contracts.md Seam 2+3 amended; cascade applied
  across M1-a/b + GATE-a/b + M1-d + CAL-a/b/c/d + M8-b1/b2 + M8-d-a/b/c2 + M4-d-2 (4 parallel AFK agents). Both parked
  markers cleared (M8-d-c2 LINT-DEFER, M4-d-2 stays-sync note → now async). `HookSpec.check_ref` stays sync (Seam 5).
  Verified zero stale sync citations. **This was the last gate — the corpus is now batch-handoff-ready.**
- **✅ macOS client surface — DECIDED 2026-06-12 → ADR-017.** Owner wants end-state **Mac + iPhone + iPad** (one
  SwiftUI codebase, three surfaces), native "like Athena," not a website. Research (`docs/research/2026-06-12-multiplatform-swift-client.md`)
  + spec audit → the foundation is already cross-platform (ArtemisKit is platform-agnostic; screens already adaptive), so
  Mac is **additive, not a rewrite**. Chose: a **separate native `ArtemisMac` target** (not Catalyst, not Designed-for-iPad)
  sharing ArtemisKit; **Athena-style scene** (menu-bar popover + global-hotkey floating NSPanel + full window + Settings);
  Mac = another paired device (own SE key); Developer-ID + notarization for personal-use distribution. **This is ADDITIVE —
  it does NOT gate the existing ~61-spec corpus** (which stays batch-handoff-ready). **CLIENT-f is now `status: ready`** —
  drafted AFK + apex-swift + apex-security review applied (4 BLOCKs resolved). **Open follow-ups:** (a) ✅ **App Sandbox ON — owner-confirmed 2026-06-12.**
  ADR-017 §6 originally said *skip* sandbox (research's "personal appliance" call); the apex-security review BLOCKed that and it
  was reversed to **App Sandbox ON** (compatible: data-protection keychain + KeyboardShortcuts' Carbon hotkeys both work
  sandboxed) — owner confirmed. (b) **2 hardware-gated auth unknowns** for the first Mac build — the Touch-ID-less Mini's SE-key passcode fallback (an
  accepted NIST-AAL1 downgrade for the single-owner appliance), and macOS 26's `.biometryCurrentSet .or .devicePasscode` prompt
  behaviour.
- **✅ Corpus remediation (sweep 2026-06-11) + final spec-lint — DONE 2026-06-12.** Sweep Waves 0–3 + decision
  queue D1–D6 complete; final DeepSeek spec-lint pass (10 agents) + AFK fix wave (9 agents) applied — all mechanical
  + determinate BLOCKs resolved. M4-c split; ADR-015 async cascade applied. Reports: `docs/findings/spec-lint-2026-06-11/_SUMMARY.md`.
  Only the tool-dispatch async decision (above) remains before handoff.
- **⚠️ Hardware re-look flagged by research-currency agent:** M5 Mini now expected late Aug–Oct 2026
  with prices rising — agent assessed this *strengthens buy-M4-Pro-64GB-now* over the locked WAIT
  decision (ADR-001 §Refinement). Owner to re-confirm or flip when reviewing sweep findings.
- **✅ Research refreshes DONE 2026-06-11** (all 3, build-impact order): (1) **DeepSeek V4-Flash** —
  conditionally reliable; spec quality is the failure variable; 5-check spec-lint checklist → run a
  spec-lint pass as the final pre-handoff gate (`2026-06-11-deepseek-v4flash-executor.md`); (2)
  **Docling** — pin `docling==2.99.0`, Granite-Docling VLM pipeline (MLX export; resolves Seam 9
  PageImage) (`2026-06-11-docling-pipeline.md`); (3) **Voice stack** — Parakeet MLX (STT) · Kokoro-82M
  (TTS) · FluidAudio/Sortformer (diarization) · SmartTurn v3.2 (EOU) · Pipecat v1.3+
  (`2026-06-11-voice-stack-refresh.md`).
- **NEW (from voice research) — owner-voice enrollment/verification undesigned (pre-M5-c):** no
  diarization lib ships owner enrollment/verification. Artemis must build a speaker-embedding store
  (e.g. WeSpeaker cosine-sim vs an enrolled owner vector) spanning the Swift sidecar (enrollment flow)
  + Python brain (comparison). Decide before M5 build.
- **⚠️ contracts.md (Wave 0A) — PENDING OWNER SIGN-OFF.** `docs/technical/contracts.md` freezes 9
  cross-module seams; it is the binding source-of-truth for the Wave 0B conformance amendments. Review
  before fanning out conformance agents.
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
  deferred to implementing specs). **✅ BUILD SPECCED: `M4-d-1` (entity data layer) + `M4-d-2` (write-path
  wiring + `memory.resolve_entity` tool)**, both ready in `docs/changes/` (drafted AFK; security+data review
  pass, 2 BLOCKs resolved). Build before Finance/Health/Comms/Travel — they bind to the `person_fact_key`
  pointer. PLACE/GOAL entities are supported now but created on-demand by their owning spokes
  (Productivity→Goal, Maps/Travel→Place).
- **⚠️ Follow-ups spun out of ADR-013 (not locked there):** (a) shared `artemis.untrusted` boundary-helper
  refactor (currently re-implemented per-module); (b) ✅ `overview.md` updated 2026-06-10 — M4 named as the
  entity backbone + ADR-012/013 added to the ADR index; (c) first Tier-0 entity candidate still undecided.
- **✅ Camera/vision — RESOLVED + LOCKED 2026-06-11 → ADR-014 (DESIGNED, deferred).** Reframed from a home-cameras
  spoke into a **vision build-assistant** (overhead desk-vision HUD + voice-first guided builds; a vision *input*
  sibling to voice, Mini-local — NOT an ACI edge box). Pipeline pinned (Apple Vision + open-vocab YOLOE in a Swift
  vision sidecar → Qwen3-VL/MLX ID → M3/M4/web enrich; gated/opt-in cloud-Claude escalation). Built via a capability
  **LADDER** (Rung 0 snapshot → 3 autonomous-watch); Rung 0/1 = first specs when M3/M4/M5/DR/Projects/CLIENT land.
  Findings: `docs/findings/desk-vision-hud-deep-dive.md`. **Widening research FOLDED into ADR-014** (alt-implementations
  + capability-menu): `desk-vision-alt-implementations.md` · `desk-vision-capability-menu.md`.
- **✅ launchd→Keychain `.env`-injection — RESOLVED 2026-06-10 → spec `M0-f` (ready).** `scripts/inject_env.py`
  reads the owner Keychain (6 Medium-tier secrets, item map locked = P1) and writes a `0600` slot `config/.env.<slot>`,
  MERGING into the existing non-secret config (not clobbering), generating+preserving the ntfy topic secret;
  wired into `deploy.sh` before `launchctl bootstrap`. Mechanism = persisted-`.env` (chosen over wrapper-exec to
  avoid the launchd-keychain-at-boot footgun; Medium-tier-only at rest, behind FileVault+0600; HIGH-tier S3 stays
  in SQLCipher). Security review folded (no BLOCKs); `cross_model_review: true`. RUNBOOK §P8 + INVENTORY P1/P5 updated.
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
