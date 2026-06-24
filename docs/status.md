# Project: Artemis
_A personal assistant that integrates with everything (Jarvis-like in spirit), with a RAG-heavy second brain as its knowledge subsystem._

stack: LOCKED 2026-06-03 (ADR-001) — SwiftUI app + Swift audio sidecar · Python brain · MLX/mlx-openai-server · LanceDB · SQLite/SQLCipher · Claude-subscription teacher (bootstrapping, non-sensitive) · ntfy · MCP-at-edges · Mac Mini M4 Pro 48GB
token_profile: lean
autonomy_level: L3
specialists_default: [apex-security, apex-ai-systems]   # SP4 app defaults applied 2026-06-08
stack_skills: [apex-python, apex-swift]   # ADR-001 coverage gate. Gaps (no skill, build on base+domain): MLX, LanceDB, voice pipeline
backends: planning=claude | coding=codex/gpt-5.5   # ADR-026 §Refinement 2026-06-24: Codex is the Artemis-core build coder, now driven INSIDE apex-code mechanic A (was the standalone runbook). Opus = mechanic-A fallback (gated — see coder_models). Build host = Windows/WSL2 (ADR-022); Mini = final host + HW-gated tails.
coder_tier_policy: retired   # ADR-026: Codex is single-model — coder_tier flash/pro tags are vestigial/ignored; cross_model_review default-satisfied (Claude plans+reviews → Codex builds = cross-family). Build driver = apex-code mechanic A (ADR-026 §Refinement 2026-06-24; standalone CODEX-BUILD-RUNBOOK retired). Parallel-Codex (APEX ADR-028) + cross-spec (ADR-029) now available.
coder_models: [codex]   # flash/pro retired (APEX ADR-027). codex = gpt-5.5 via apex-code mechanic A. OPEN (owner): mechanic A defaults to Opus inline-fallback on Codex quota-out; ADR-026 chose stop-and-ask. Kept [codex] (stop-and-ask) — set [codex, opus] to enable the Opus auto-fallback.

_Last updated by planning mode:_ 2026-06-23 (**CONTINUATION — reservations APPLIED · M9 designed · client re-scope designed · dev-model-stack specced.**
(1) **Architecture-validation reservations A–J decided AND applied** across 12 corpus files (additive schema/port/runtime hooks; 77cab92):
derived-provenance · record-type-generic memory port · async-write/scope guard · RAPTOR summary-tree fields · structured-projection hook ·
shared checkpoint/idempotency convention · router→planner seam · cloud fallback ladder + recipe-quality gate · parametric-memory stance ·
prospective-memory home. **ADR-027 resolved** = intentional Artemis numbering skip (it is an APEX-system ADR; runtime routing = ADR-022, coder = ADR-026).
(2) **M9 Task Executor DESIGNED** → ADR-024 §Refinement 2026-06-23: supervised long-horizon · owner per-task unattended/supervised flag ·
plan-preview trigger · deterministic-read-back verification (never self-judged) · linear plans + reserved parallel-groups · plan-fresh +
compose **atomic recipe primitives** (reshapes M7-a1/a2 at spec time — banner added) · two-tier task-memory w/ sensitivity-defer guardrail ·
risk+milestone **agent-inbox** check-ins · per-task deadline+token budgets + **intra-GPT model tiering** (confirmed in-subscription: `codex --model`
gpt-5.5/5.4/5.4-mini, no metered API) + token-bucket retries + circuit-breaker · GPU residency priority. M9 stays post-spoke-wave.
(3) **Client re-scope DESIGNED** → ADR-028 §Refinement 2026-06-23: the CLIENT specs are stale on **3 axes** (Swift→**Tauri** ADR-023 · auth→
P-256/TPM/SE ADR-025 · tabs→**map** ADR-028) = a rewrite, only contracts carry over. **Functional-cluster, user-arrangeable + persisted** map ·
**WebKit-safe** build discipline · **7-spec Tauri carve** (core/auth/world/card/ask/screens/theme; CLIENT-f retires to a build target). Spec rewrite PENDING.
(4) **Dev-machine local-model stack DESIGNED + specced** → ready `docs/changes/dev-model-stack-ollama.md`: Ollama on the 8GB Windows box
(embedder Qwen3-0.6B + reranker 0.6B + 4B responder/classifier ≈4GB); swaps the validation slice off FakeEmbedder onto **real local models**; its
ACs (tool-calling + structured-output via Ollama/Qwen3) **answer ADR-022 parked (b)**. New memory: **dev-machine-first build/test lens**.
**RESUME — remaining dev-first threads:** sensitivity ingestion-gate · build-wave sequencing (ADR-026 de-gating map) · reservation Bucket-2
(H1 rung-2 DeepSeek-Pro-API adapter · H2 re-seed · A typed-source-ref migration). Plus the **CLIENT Tauri spec-rewrite pass** when ready.)
_Prior:_ 2026-06-23 (**CLIENT UI DIRECTION LOCKED → ADR-028 + architecture-validation research.**
(1) **Client navigation LOCKED = spatial "travel-zoom" command-map** — pannable map + central pulsing brain core; pan +
eased scroll-zoom with rubber-band bounds; travel-across-then-**expand-open** (shared-element morph) as the **top-most**
layer over a lightly-dimmed still-visible map; minimal **baseline-aligned, left, vertically-centred** glance cards (list→count,
fixed-metric→tiles); **overview never content-scrolls**; distinct floating **Ask-Artemis pop-up** (⌥Space); **photographic
background** bundled/local, season×time-driven. **Supersedes the Review/Chat/Status tab-shell**; ADR-023 (Tauri) + ADR-025
(auth/lock) unchanged. **Reconciled into the corpus:** new **ADR-028** + `design-brief.md` + re-authored `app-flow.md` +
`overview.md` ADR index + memory (`client-ui-travel-zoom-direction`). Reference mockup: `docs/research/mockups/travel-zoom-workspace.html`
(+ exploration mockups in that dir). **Remaining:** fonts pass (deferred) · **CLIENT-\* specs need re-scope to the map shell**
(world/camera + domain glance-card/detail-overlay + dock + minimap + Ask pop-up; content unchanged) · final domain set/grouping TBD.
(2) **Architecture-validation research** (3 parallel agents → `docs/research/2026-06-23-architecture-validation/`): verdict =
substrate is **SOTA-aligned** ("over-built storage, under-built cognitive layer"); **5 cheap-now/expensive-later schema
reservations** surfaced (see new Open Question) — all ADDITIVE if the hooks exist.)
_Prior:_ 2026-06-22 (**SENSITIVE-HANDLING REFINED → ADR-022 Refinement.** Resumed the scope-out
checkpoint; owner pressure-tested the hybrid and **LOCKED an upgraded version (phased), REJECTING full scope-out** (too blunt
for incidental email; gives up sensitive assistance). **Gate:** regex → a **cheap LOCAL model at the INGESTION seam** (fail-closed;
reads on-box, no cloud round-trip) — the blocked posture's **option C (local-classifier-first)**, retiring the regex false-negative
leak. **Reasoner:** base-local → **Codex-DISTILLED** (teacher trains on **synthetic** data only — real records never leave the box;
reuses `distill-datagen-pipeline`). **Phasing (additive):** NOW = local-model gate + detect-and-drop + start the Codex-teacher
distill drip; LATER (Mac+training) = the distilled reasoner graduates into `sensitive_reasoner` → detect-and-route-local.
**Recorded: ADR-022 § Refinement 2026-06-22.** Both Open Questions (scope-out-vs-gate · sensitivity posture) RESOLVED.
`brain-sensitivity-routing` unblocked but **regex mechanism SUPERSEDED — needs redraft** to the local-model/ingestion gate (banner
added at spec top); `distill-datagen-pipeline` gains sensitive-domain categories + a pluggable Codex teacher.)
_Prior:_ 2026-06-22 (**ARCHITECTURE RE-LOOK — hybrid cloud/local model layer ACCEPTED + UI/executor captured.**
A long re-look (sparked by "use agent harnesses + OpenAI") → **3 new ADRs**. **ADR-024 (Accepted): Task Executor** — general
multi-step plan→act→verify agent, background-default, +durable **task-memory** (ADR-004 unchanged), reliability spine, reuses
tools+GATE, graduates→recipes (= M9). **ADR-023 (Accepted, supersedes ADR-017): Tauri** cross-platform desktop client — `.exe`
on Windows now → Mac `.app` later; no Swift/Xcode; client of the M1-c gateway; unlock→passkeys+recovery-passphrase. **ADR-022
(Accepted): model/runtime re-architecture** — reasoning routed by sensitivity: **non-sensitive → Codex on the ChatGPT subscription** (pluggable seam, local/API fallback; no per-token bill), **sensitive → local model**; proactivity
kept via a **local always-on heartbeat that fires the cloud on-demand** (idle≈free); **embeddings stay local** (Ollama Qwen3-0.6B);
harness = **own thin spine + Pydantic AI + MCP + OTel + borrow LangGraph checkpoint/interrupt patterns + Hermes's GEPA**; **build the
full app on Windows first**, Mac = final host. Researched + REJECTED: full cloud pivot · build-on-Hermes/OpenClaw (immature/insecure/
provider-banned). **Subscription path CONFIRMED VIABLE (revised):** Codex on a ChatGPT plan is OpenAI-permitted for *personal* use → **adopted as the default reasoning engine** behind a pluggable seam with local/API fallback (eyes-open: coding-oriented · 5h/weekly rate caps · undocumented backend).
**✅ Privacy gate RESOLVED 2026-06-22 = HYBRID → ADR-022 ACCEPTED.** Sensitive (finance/health/journal/memory) reason on a
LOCAL model (never leave the box); everything else → Codex/cloud; the sensitivity router gates it. **Privacy wall KEPT** —
M2/ADR-003/005/006 + local sensitive-reasoner + recovery-passphrase/passkey all stay; **nothing retired** (change is additive).
Hardware checked: RTX 5060 Ti **8 GB** + Ryzen 7700 + 32 GB → real local embed/rerank/4B + an 8B for the sensitive path; 27B = Mac-prod.)
_Prior:_ 2026-06-22 (**Resumed the 2026-06-21 design session → closed out.**
Committed the surface-7 + provenance closeout (885e4b6, 7 files). Resolved both parked follow-ups:
(1) **phone-less unlock** — owner redirected the "first Tier-0 candidate" question into a real gap and
chose a **recovery passphrase (break-glass escrow)** → **ADR-005 Refinement 2026-06-22** (Argon2id-wrapped
escrow DEK copy; rare/audited/rate-limited; no routine override PIN; second-device deferred & non-breaking).
The original first-Tier-0-*signal* candidate stays parked (an M6-build call). (2) **`uv` dev-deps migration**
— owner chose **migrate cleanly** → new ready spec **`uv-dependency-groups-migration.md`** (`[project.optional-dependencies]`
→ PEP 735 `[dependency-groups]`; WSL2-buildable, flash; build BEFORE `tooling-cleanup`). The apex-python
Verification Recipe + RUNBOOK already use bare `uv sync`, so the migration brings the project into compliance — no recipe edit.)
_Prior:_ 2026-06-19 (**Owner-rules capture session.** Scanned ~20
automation/rule-bearing specs (6 parallel agents) → 6 capture workbooks under `docs/owner-rules/`
+ elicited owner values across all 6 surfaces. Key: SGT + 9–6 Mon–Fri · gentle-nudge posture ·
**WAKE-triggered morning digest** (say "good morning") · email rubric (notify=legal+payment only;
important≠notify; VIPs Ashley/Debby) · memory **excludes financial+health** (financial→Finance ledger
only) · A.U.D.N. keep-both+dated · **auto-tagging precision-first** (needs-review when unsure) ·
**internal-reversible autonomy boundary** (tagging auto, external-effect gated) · cloud=general-skills-only,
**email stays local**. **Surfaced 8 spec gaps for planning** → `docs/owner-rules/00-INDEX.md` §Spec gaps
(wake-hook type · working_days · needs_review tagging state · classify_safety internal tier · Gmail
Stage-1 widen · Finance reconciliation [added to finance.md] · preferred_focus_window · bank→Finance
routing). Committed 02696bf + session-end.)
_Prior:_ 2026-06-19 (**Coding handoff drained → new ready spec `tooling-cleanup`.** Drained the
2026-06-18 coding handoff to inbox-zero. The InMemoryToolIndex/VectorStore **protocol gap** [owner chose: *widen the index*
to the protocol's already-`Sequence`/`Mapping` signature — NOT narrow the protocol, which would couple the port to concrete
types] + the 5-file **ruff format drift** → `docs/changes/tooling-cleanup.md` (`status: ready`, Flash, 2 tasks, zero
behaviour change). Flaky-test handoff item discarded (coder-confirmed semantically equivalent). The **`uv` dev-deps
migration** (`[project.optional-dependencies]`→`[dependency-groups]` so `uv sync` alone installs dev deps) is **DEFERRED as
an Open Question** — the `--all-extras` flow works today and migrating ripples into the documented verify recipe across ~61
specs + RUNBOOK, so it's its own deliberate spec, not a bundled cleanup.)
_Prior:_ 2026-06-17 (**Validation-slice brief added — NO spec-corpus change.** Cross-project APEX
discussion surfaced that "build waits for the Mini" is an *inherited assumption*: the brain spine is pure Python (MLX = a
swappable OpenAI-compatible endpoint, live-checked on M1-b + M0-a), so a thin vertical slice (M0-a→M0-d→M1-a→M1-b→M1-d→M1-c)
can be built **now** in a DeepSeek/WSL2 coding session to get the corpus's first execution signal. Decision-ready brief:
`docs/findings/windows-buildable-spine-slice.md`; In-Flight + Open-Questions rows added. De-risks the batch; ADR-002 unchanged.
**Updated same session: the brief's open sub-question is CLOSED → GO** — line-audited the four un-checked slice specs
(M0-d/M1-a/M1-c/M1-d): no hidden Mac/MLX dep, only M1-b Task 5 (live-model) is gated = the swappable endpoint seam, all
else fake-testable; two trivial frictions (cosmetic Mac paths · `/opt/artemis` mkdir). Slice is GO; owner go/no-go is the only remaining gate.)
_Prior:_ 2026-06-16 (**Research / fit-eval session — NO spec-corpus change; corpus stays batch-handoff-ready.**
Three external-content fit-evals + one deep-research doc, all committed (d91b7ee, c51b4ff) and parked in their homes. (1) **MTPLX**
(native MTP / speculative-decoding MLX server) → benchmark candidate in the expansion BANK (`serving-software.md` §1.5 + README
anecdote); drop-in behind the M0-c runtime seam, on-device A/B vs mlx-openai-server/vllm-mlx when the Mini lands. (2) **Unsloth Studio**
→ candidate for the *deferred* Mac/box-side training step ONLY (NOT dataset-gen — our `distill-datagen-pipeline` front half is better-
designed + sensitivity-tiered, stays); filed in `homelab-control-plane.md` capability lane (MLX-training bug → favors the P3 GPU box).
(3) **Agent-loop reliability deep-research** (3 source-grounded agents) → `docs/research/2026-06-16-agent-loop-reliability.md`: the viral
"geometric reliability decay / cascading state contamination" loop critique is a series-vs-parallel **topology error** (+ inverted Markov
"absorption state"), but its kernel is real + measured — a loop is safe ⇔ **idempotent · bounded · clean-state · externally-verified**
(independence = master variable). Doc carries a per-loop Artemis audit (M3-c / DR-c / M6) + a 6-point guardrail checklist. Durable-home
decision (apex-system-design rule / ADR / status Open Question) deliberately **DEFERRED** — owner chose to keep it *referenceable* via
memory instead. New standing routine in memory: external content = **fit-eval, not just capture**.)
_Prior:_ 2026-06-13 (**Home-lab / local-inference expansion → standalone BANK (parked).**
Future-proofing the inference layer (local DeepSeek-coding + Kimi-class big-context; M5 Mini = orchestrator, heavy inference on a separate tailnet box). All research + decisions moved into a self-contained bank — `docs/research/2026-06-13-local-llm-expansion/` (start at `README.md`) — kept **separate from the spec corpus**: trigger-activated when hardware is bought, otherwise an info bank of options + field anecdotes ("what people have done"). Decisions A/B/C + D-plan-1/2 resolved; APEX coding+planning fit checked; software is config-only and does **not** touch the frozen ~61-spec corpus; EXP-a/EXP-b specs drafted only when a trigger fires. Field anecdotes folded: dual-GB10/ASUS-GX10 (validated), Intel B60 (declined), 8× RTX 4000 Ada CUDA (viable-but-dominated). BACKLOG.md got the future-proofing + UI-thread items.)
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
_Last updated by coding mode:_ 2026-06-22 (**First Codex build session — ADR-026.** Built + committed via Codex CLI (gpt-5.5,
owner-supervised, per-spec): `M4-d-1` entity data layer (first Codex test build), `uv-dependency-groups-migration` (PEP 735),
`tooling-cleanup` (both tasks), `codex-model-adapter`. Also committed prior planning docs: ADR-025 (Tauri client auth/wall
re-root) + ADR-026 (Codex build coder). Codex built faithfully throughout — spec-conformant, surgical, scrubbed errors. **Clean
baseline @ 1616894, 139 tests pass.** Remaining brain-Codex trio: `composite-model-routing` → `brain-sensitivity-routing`.)

<!-- Do not remove or rename the CODING:START/END or PLANNING:START/END comment markers. They are used by automated writers to locate their blocks. -->

<!-- CODING:START -->
## In-Flight
| What | Mode | State | File | Stopped at | Uncommitted |
|------|------|-------|------|------------|-------------|
| cluster prereq build ("build specs") | coding | 🔄 IN PROGRESS — prereq foundation, checkpointed (Codex-primary; owner granted standing auto-commit for green+scope-clean+fork-free specs). DONE+committed: `brain-sensitivity-routing` (c817df9) · `DR-a` (70a6391) · `M2-b` scope-wall dev-stub (8c40e5e) · `M6-a` scheduler (627dfef) · `M4-b` memory write-path (8a1f8c1) · `M7-a1` recipe store+signing (7d66719) · `M2-c` sqlcipher dev-stub seam (991350e, `artemis.data.sqlcipher.sqlcipher_open` plain-sqlite shim — shared by all owner-private SQLCipher stores; broker/SE remain Mac-gated) · `GATE-a` action-staging (8c325c0) · `M8-d-a` productivity core (07c63e2, 30-tool owned SQLCipher module over the sqlcipher seam; eager-GOAL `entity_repo` typed against a narrow `GoalEntityRepo` Protocol — **M4-d FLAG:** real wiring must reconcile the signature gap, the live `EntityRepository.resolve_or_create_entity` has no `entity_id` kwarg and returns `str` not `EntityRef`) · `M4-c-1` memory recall+auto-inject (777665c — **SCOPE EXPANSION, owner-approved 2026-06-24:** the M4-a `SqliteMemoryStore` was never built (only `BitemporalRepository` + the `MemoryStore` Protocol existed); `store.py` was CREATED with the full concrete store rather than "filled". Security-hardened: inject block gated to owner-private LOCAL responder only — never `responder_cloud`. compose_brain memory branch is on-hardware-exercised only) · `M6-chain-prereqs` (392c471 — async `on_hits` contract patch [seam → `Callable[[TickResult], Awaitable[None]]`, call relocated sync `tick()`→async `run_forever`, `tick()` annotation `-> str`→`-> TickResult`] + `Settings.ntfy_topic_secret` [`secrets.token_hex(16)` default_factory, `exclude=True`]; 3 heartbeat tests reworked + 1 added; SMALL deviation: orphan-removed the now-redundant `cast(TickResult, …)` calls + unused `cast` import the annotation fix obsoleted) · `M6-b` hit-handling (1802821 — async `HitHandler.handle` as the heartbeat's `on_hits`; template/no-LLM path + payload-free default render; ONE batched `model.complete` per tick with `<<<json>>>` injection-delimited payloads; 3-tier urgency→immediate/deferrable/digest; per-hit-dedup digest fold w/ tier=max; degrade-to-template on model-fail/line-mismatch; + briefing Tier-0/SHARED needs_llm cron manifest) · `M6-c` ntfy delivery + policy + Tier-1 queue (d78ca7d — `NtfyDelivery` deliver-sink → ntfy POST [priority/tags/click/actions, topic=`artemis-{slot}-{secret}`]; `ProactivePolicy` mute/urgency-floors/quiet-hours-hold; JSON `DedupStore` 7d TTL; durable `Tier1Queue` persists hook IDENTITY only [no payload at rest], drains-on-unlock w/ per-hook TOCTOU re-check + remove-only-on-confirmed-2xx + dead-letter@max_attempts; `compose_proactive` entry point; `attach_to_heartbeat` wires flush→drain→module steps into async `pre_tick_steps`, no monkeypatch; security invariants tested: Tier-1 quiet-hours→immediate-low not held, held.json Tier-0-only, action-URL allowlist artemis://+127.0.0.1+*.ts.net, atomic-write+corrupt→empty) · `M7-a2` escalate→distill→replay + brain seam (347402e — `DistillService`: teacher solve → INSTANCE-FREE task-class distill [never embeds request_text] → CANDIDATE → replay-verify [schema-conformance comparator] → write-only-if-verified; `CloudEgressForbiddenError` fires before any model call when `is_cloud_safe=False`+injected `teacher_origin=="cloud"` [reads injected literal, never probes ModelResponse.origin]; `apply_recipe` runtime path SCRIPT=sandbox-gated-fail-closed [`SandboxNotAvailableError` in both apply+replay] / INSTRUCTIONS=one responder call, never role=teacher; brain `decision.path=="escalate"` seam replaced: matching ENABLED recipe→apply→`path="recipe"` zero-teacher / else emit OBS telemetry→`path="escalation_queued"`; `store`/`sandbox`/`telemetry_writer` additive None-default; `ClaudeCliModelPort` [role=teacher, shutil.which, sanitised env, validate→retry-once→`TeacherMalformedResponseError`] created. **OBS-a unbuilt → telemetry tap is an injected optional Protocol, no `artemis.obs` dep.** Task 7 live-teacher GATED) · `M7-b` promotion policy #8 + review surface (1d18c9f — `classify_safety` [READ_ONLY/NO_DATA→auto-enable, else gated]; `RecurrenceStore` per-task_class_key atomic JSON; `Promoter` N≥2 auto-promote [safe→ENABLED, **gated→PENDING never auto-enabled**], owner `promote` [HMAC-verify via store.get + `RecipeAlreadyRetiredError` on RETIRED], `reject`→RETIRED; `ReviewSurface`+deterministic `explain`; brain `note_occurrence(key)` wired before the escalation_queued return when a CANDIDATE exists. **⚠ DEVIATION (review-needed):** spec wrote Promoter/ReviewSurface sync, but `RecipeStore.set_status/write` are async [ADR-015] + `note_occurrence` is awaited inside the async brain loop → built the status-changing methods ASYNC [note_occurrence/_auto_promote/promote/reject + ReviewSurface approve/reject]; classify_safety+RecurrenceStore+list-only queries stay sync; no logic change, ADR-015/016-consistent; downstream CLIENT-b will await these) · **[PARALLEL BUILD — 2 concurrent Codex subprocesses, disjoint file trees]** `M7-a3` dedupe/retire (b0dda86 — `async def dedupe_retire` [async deviation, same rationale as M7-b]: exact-dupe [same task_class_key+identical canonical instructions→retire lower version] · near-dupe [cosine≥threshold+same action_class→retire older verified_at] · superseded [higher version retires lower via set_status(version=)] · deterministic tiebreaker [lower version tuple, then lower name]; no generative LLM at library time) · `M4-c-2` decay sweep + owner surface (1133f36 — `TOMBSTONE_FLOOR=0.02`+`sweep_tombstone_candidates` [pure, returns sub-floor candidates, NO deletion]; `OwnerMemory` list/view/history + `edit_fact` [async, human-in-loop confirm-gate→auditable repo.update tagged extractor_model="owner"] + `delete_fact` [tombstone] + `purge_fact` [the ONLY hard-delete, confirm-gated]; never-hard-delete everywhere except explicit purge; `salience` param accepted-but-unused since repo.update has none). **Parallel method:** each Codex scoped to its subpackage (recipes/ vs memory/, which don't import each other) + scoped verify (mypy on own subpackage + own test, distinct cache dir, NO uv sync/full-pytest); host ran the full recipe ONCE on the integrated tree (clean: 110 mypy files, ruff, 288 tests) + committed each separately. No cross-contamination. Also baseline fix `fee6ec3` (SpyHeartbeat.tick override return-type `str`→`TickResult` — 392c471 regression that only the full `mypy` over src+tests caught; the M6-chain-prereqs verify had checked mypy only over its own touched test file). **Baseline green @ 1133f36, 288 tests.** **⚠ FLAGS (planning, M6-c, review-needed):** (1) `Tier1Queue.drain` is a SYNC method (per spec signature) that must drive the ASYNC `HitHandler.handle` — Codex bridged via `asyncio.run`/worker-thread (`_run_blocking`); works + tested, but consider making `drain` async in a refinement. (2) drain swaps `hit_handler.deliver` to a counting wrapper to capture the confirmed-delivery count (restored in `finally`); sequential-only, but a shared-handler mutation. (3) `attach_to_heartbeat` writes the PRIVATE `heartbeat._tier1_sink` (no public setter exists); spec said `heartbeat.tier1_sink`. **FINDING (planning/roadmap):** M4-a left a real prerequisite hole — no concrete `MemoryStore` impl; filled in this build. Other "fill the M4-a stub" specs (e.g. `M4-c-2`) should expect the same. **LESSON:** read the FULL spec (all task headers + reconcile Files-table vs Tasks) before dispatching — `M4-b`'s Task 4 (`__init__.py` re-exports) was omitted from its Files-table and I initially over-constrained the dispatch. **DEFERRED: `M3-a` + `M3-b`** (docling/trafilatura are heavy unexercised deps on the 8GB box — handle install deliberately / likely make docling an extra so dev stays lean). **✅ M6 delivery-chain blocker RESOLVED in planning 2026-06-24** (was PARKED-PENDING-PLANNING). All three decisions ratified by owner: (1) async `on_hits` contract — make the seam `Callable[[TickResult], Awaitable[None]]`, drop its call from sync `tick()`, `await` it in `run_forever`; (2) add `ntfy_topic_secret` to `Settings` (M0-a territory, not M6-c scope); (3) build order **M6-chain-prereqs → M6-b → M6-c** (the old pointer wrongly skipped M6-b). Captured as a new ready spec **`docs/changes/M6-chain-prereqs.md`** (2 tasks: heartbeat async patch + Settings field) + amendment banners on M6-b (handle is `async def`, wired as async on_hits) and M6-c (ntfy_topic_secret now provided externally). **Finding correction:** the blocker write-up's "tests untouched" claim was optimistic — `tests/test_heartbeat_scheduler.py` has 3 tests driving on_hits through `tick()`; 2 need rework (captured in M6-chain-prereqs Task 1). **Follow-up FLAG (planning):** M0-f secrets inventory should add `ARTEMIS_NTFY_TOPIC_SECRET` to the Keychain→`.env` inject map for prod topic stability (out of prereq-spec scope). Full write-up: `docs/findings/m6-delivery-chain-blocker.md`. **✅ M6 DELIVERY CHAIN COMPLETE (M6-chain-prereqs → M6-b → M6-c, @d78ca7d).** **✅ M7 SELF-IMPROVEMENT LINE: M7-a1 (7d66719) → M7-a2 (347402e) → M7-b (1d18c9f) COMPLETE** (owner chose build-M7-a2-first 2026-06-24 when M7-b Task 5 brain-wiring proved blocked on the unbuilt M7-a2 escalation_queued path). **M7-a3 (b0dda86) now also done.** Remaining M7: `M7-c` (curiosity loop — **needs `tldextract` dep [not installed → `uv add` mutates pyproject/uv.lock, so NOT clean-parallel-safe; build serially]**; reads M7-a2 OBS escalation tap via Protocol + builds against fakes). Also done this session in parallel: `M4-c-2` (1133f36). **▶ NEXT buildable: google-dep chain `M8-a` → `M8-b1` → `CAL-a/b` (NB `M8-a` Google OAuth likely needs credentials/external setup — confirm before dispatch); `M4-d-2` (writepath resolve tool — touches memory/ + gateway.py, sequenced-with M4-c compose_brain) · `M7-c` (after tldextract add) · OBS-a (obs/ new pkg, touches brain.py+distill.py) · docling layer `M3-a`/`M3-b` (heavy-dep); then cluster waves F0→F1→P/S/R per `BUILD-ORDER.md`. PARALLEL note: M4-d-2/OBS-a both touch brain.py/gateway.py so they're NOT mutually parallel-safe nor parallel with brain-touching work.** **✅ CLUSTER WAVE F0 COMPLETE (serial, Codex, 2026-06-24) — baseline green @ 7e45af8, 309 tests.** `X3-runtime-config` (7b811d7 — `RuntimeConfig` frozen Pydantic policy.json layer, all cluster tunables, defaults-in-code/overrides-in-file, `@lru_cache`+reload) · `M6-wake-trigger` (6f0e689 — third `HookSpec` trigger `wake` + `note_wake` latch + fallback-time + day-gate; reads X3 tasks.* tunables; scheduler regression green) · `M8-d-a-areas-drop` (c59eb81 — schema v2: dropped `areas` table + `area_id` FK/indexes, 30→22 tools; D3 GOAL eager-create + `project_id` FK PRESERVED; **DEVIATION:** `store.py` facade [build-introduced @07c63e2, absent from spec Files-table] folded into scope — required by the whole-dir sweep gate; **spec typo:** Files-table "30→27" wrong, authoritative = 22; cross_model_review=Opus-reviewed-CLEAN) · `M8-d-a2-projects` (7e45af8 — split into `projects_manifest` [6 tools, card] + `tasks_manifest` [16 incl. `tasks.suggestion.*`, card] over ONE store; **naming resolved against live registry** [fq=`{manifest.name}.{tool.name}`]: bare last-segment task/project names, suggestions keep prefix to avoid collision → `projects.create`/`tasks.create`/`tasks.suggestion.create`; `productivity_manifest`=`tasks_manifest` transitional alias; **spec miscount:** done-when said projects=5, live+partition-list = 6 incl. `project.tasks`). Specs archived to `docs/changes/done/`. **▶ NEXT: cluster Wave F1** (4 parallel-disjoint amendments: `M8-b2` urgency-widen · `CalPrefs`/CAL-a working_days+focus_window · `M8-d-b` focus-slot-pick · `M8-d-c1` wake-digest — all read X3 + the F0 wake trigger; M8-d-b/c1 also update `productivity_manifest`→`tasks_manifest` call sites per the alias migration note). Then P (sensitivity ADR-029) ∥ S (Finance) ∥ R-infra.** **✅ M8-a Google-auth foundation (52c16bc, 2026-06-24) — Tasks 1-6 dev-built behind fakes [scope registry · loopback consent PKCE/offline/prompt=consent/no-hardcoded-redirect_uris · owner-private `SqlCipherTokenStore` key.as_hex-local-only · auto-refreshing `GoogleCredentialsFactory` invalid_grant→ReauthRequired · `artemis-google-auth` CLI]; Task 7 (live OAuth + keyed SQLCipher round-trip) GATED on-hardware. +deps google-auth/-oauthlib/api-python-client (host `uv add`, pip-audit clean for them). Baseline 323 tests, security invariants spot-checked.** **⛔ FORK — M3-a docling dep decision (PLANNING/OWNER):** `M8-b1` Gmail connector is BLOCKED on `M3-a` (`IngestPipeline` for split-depth ingest). M3-a CODE is dev-buildable as written (docling lazy-import behind `DocumentParser`+`FakeParser`, real parse=Task-7 gated). Open call = M3-a's `uv add docling` (heavy torch-scale ML dep on 8GB box): make docling an **extra** (In-Flight leaning, dev stays lean, FakeParser-tested, real docling=Mac-gated) vs core dep. Gates Gmail→Finance→sensitivity-P→CAL-d. **Isolable** — buildable-without-M3-a set: `M8-d-c1` (hooks+wake-digest) · `CAL-a/b/c` · `M4-d-2` · `OBS-a` · then `M8-d-b`. Full capture: `docs/progress/cluster-build-2026-06-24.md`. **NB pre-existing pip-audit CVEs** (starlette/torch/yt-dlp — unrelated to this session's deps, predate it). **✅ M3-a-INDEPENDENT SET — 2 more landed (2026-06-24):** `M8-d-c1` wake-digest hooks (91c589c — 3 Tier-1 LLM-free counts+IDs hooks built to end-state directly [base hooks.py never existed → created]: morning-digest [wake+08:00 fallback, overdue folded T2] / weekend-review [Sat day-gate] / week-ahead [daily 0 19 cron + Sunday gate in check_ref]; wired into `tasks_manifest`; reconciled the M8-d-a2 `test_productivity_core` `proactive_hooks==[]` assertion → `len==3`) · `CAL-a` Calendar read/find-time/prefs/sync + CalPrefs folded (ac3d9a1 — full `calendar/` module [client lazy-googleapiclient+FakeCalendarApi · owner-private SQLCipher read-cache · incremental sync · find_time engine · read tools · manifest]; CalPrefs `working_days`/`preferred_focus_window` default from X3, find_time skips non-working days + biases slot ranking to focus window; live OAuth/keyed-SQLCipher/network GATED; **Codex hit the 10-min timeout but had finished writing — recovered by host-verifying the tree, not re-dispatching**; `# noqa: N802` on `calendarList` Google-API mirror). **Baseline green @ ac3d9a1, 355 tests.** **✅ CAL-b COMPLETE 2026-06-24** (Codex apex-coder, host-verified; baseline green @ 367 tests). Was BLOCKED at pre-flight on the gated-twin re-dispatch loop (2026-06-10 B1; CAL-b = first external-effect runtime-gated module) → **owner chose inline planning pass → RESOLVED via R1:** `ToolSpec.execute_callable_ref` seam (contracts.md Seam 2 D1 mechanism pinned + Seam 3 Δ); registry prefers it for the `{tool}_execute` twin (back-compat fallback to `callable_ref`). CAL-b: front-door=classify, twin=raw; B1 regression test (real registry+staging+store: approve→raw, no re-stage) green. Files: `manifest.py`(ToolSpec) · `registry/registry.py` · `modules/calendar/{client,write_tools,gating,activity_log,manifest}.py` · tests. **⚠ DEVIATION (planning review):** contract change ratified inline during a coding session (R1) — confirm next planning review. **⚠ MINOR:** update/move/cancel resolve existing event from `default_write_calendar` only (no calendar_id arg) — fails closed; resolve at on-hardware Task 7. **✅ 6334b6d** (CAL-b code+tests+contracts.md amendment; status.md In-Flight left uncommitted alongside prior-session planning edits). **✅ M3-a-INDEPENDENT SET COMPLETE (continuation 2, 2026-06-24) — baseline green @ `7006b15`, 401 tests.** `CAL-c` (f66701c — overlay + 7 §D hooks) · `M8-d-b` seam (38b67eb — `calendar.schedule_task` + `tasks.schedule` + Task↔Event link) · `M8-d-b` focus-slot-pick (a830043 — focus-window slot bias) · `M4-d-2` (f6616c8 — subject→PERSON write-path wiring + `resolve_entity` tool) · `OBS-a` (3e77934 — JSON logging + redaction + `ObservabilitySink` + error capture + brain/distill taps). All specs archived to `done/`. Reconciliations (bare ToolSpec names B9 · optional injection params to protect out-of-scope test callers · `BitemporalRepository.conn`/`person_id` properties + repo-based `memory_manifest(repo)` · `obs` on `DistillService.__init__`) logged per-spec + in handoff. **▶ NEXT — choose one (no coding-mode blocker on a/b):** (a) **OBS-b** telemetry backend — NOW UNBLOCKED (OBS-a Protocol shipped; needs only OBS-a + M2 sqlcipher seam) · (b) **M7-c** curiosity loop — buildable after `uv add tldextract` (serial, host-side) · (c) switch to **PLANNING** to resolve the **M3-a docling fork** (docling-as-extra-vs-core dep; the SOLE critical-path blocker for Gmail M8-b1/b2 → Finance → sensitivity-P → CAL-d). Handoff: `docs/handoff/2026-06-24.md` (Continuation 2). Per-spec friction (caught in pre-flight, adapted in-place, logged in each spec's Progress): every original-corpus spec carries stale `/Users/artemis-build/` paths + minor interface-drift vs live code (e.g. ModelPort keyword-only/Message, `artemis.obs` unbuilt→stdlib logging, compose_brain≠Gateway). `M2-c`/OBS are Mac-gated/unbuilt → dev stubs in place (FakeKeyProvider None-default; proactive/__init__ created by M6-a). | docs/changes/BUILD-ORDER.md + docs/findings/cluster-spec-roadmap.md |
| architecture-validation reservations | planning | ✅ COMPLETE 2026-06-23 — all A–J decided AND applied across 12 files (✅ 77cab92) | docs/drafts/architecture-validation-reservations.md | All reservations decided + applied. **A** derived-provenance · **B** record-type-generic memory port · **C** async-write+scope port (regression-guarded) · **D** RAPTOR summary-tree fields · **E** structured-projection ingest hook · **F** shared checkpoint/replay + idempotency convention (Task Executor/heartbeat/recipe-runner) · **G** first-class router→planner escalation seam · **H1** fallback ladder Codex→DeepSeek-Pro-API→local **Qwen3-Instruct** (final checkpoint benchmark-at-Mac) · **H2** recipe-quality gate + re-seed · **portfolio** 64GB reaffirmed + model-residency/load-evict seam reserved + **dev-box 8GB VRAM budget produced** · **I** parametric stance · **J** prospective-memory home (no new store). **Files (uncommitted):** ADR-004 · M4-a · M0-d · M3-a · ADR-024 · M1-b · M6-a · M7-a2 · ADR-022 · M7-b · distill-datagen-pipeline · brain.md. Full decision+application log in the draft. **ADR-027 resolved:** intentional Artemis skip (= APEX-system ADR per overview index); no Artemis ADR needed — runtime routing = ADR-022, coder = ADR-026. | ADR-004 · M4-a · M0-d · M3-a · ADR-024 · M1-b · M6-a · M7-a2 · ADR-022 · M7-b · distill-datagen-pipeline · brain.md |
| M8 first-spoke-wave | planning | ✅ COMPLETE · 0 parked | docs/changes/ | Gmail (M8-a/b1/b2) + Calendar (CAL-a/b/c/d) + Productivity (M8-d-a/b/c1/c2) + GATE (a/b) ALL READY. Module designs calendar/gmail/productivity.md complete. **M6-c was amended in place** (pre_tick_steps). Build-ready for batch handoff. | — |
| SP0 core | planning | ✅ COMPLETE — batch-handoff-ready (all sweeps + ADR-015/016 cascades done) | docs/changes/ (~61 ready specs) | Core spine M0–M7 + OBS + DR + CLIENT + M8 (Gmail/Calendar/Productivity) + GATE all specced; 2026-06-11 sweep + final spec-lint remediation COMPLETE; ADR-015 (port) + ADR-016 (dispatch) async cascades applied. No remaining handoff blockers. | — |
| corpus-remediation | planning | ✅ COMPLETE — corpus batch-handoff-ready | docs/findings/spec-lint-2026-06-11/_SUMMARY.md | Sweep remediation (Waves 0–3 + D1–D6) + final spec-lint pass (10 agents) + fix wave (9 agents) + **ADR-015 async-port cascade** + **ADR-016 uniform-async-tool-dispatch cascade** ALL DONE. ADR-016 (owner: option A) cascaded across M1-a/b + GATE-a/b + M1-d + CAL-a/b/c/d + M8-b1/b2 + M8-d-a/b/c2 + M4-d-2 (4 parallel AFK agents); contracts.md Seam 2+3 amended; both parked markers (M8-d-c2 LINT-DEFER, M4-d-2 stays-sync note) cleared; verified zero stale sync citations. **No remaining gate — the ~61-spec corpus is fully batch-handoff-ready for DeepSeek when the Mini arrives.** | M1-a/b · GATE-a/b · M1-d · CAL-a/b/c/d · M8-b1/b2 · M8-d-a/b/c2 · M4-d-2 · contracts.md · ADR-016 (new) |
| macos-client (CLIENT-f) | planning | ✅ COMPLETE — CLIENT-f `status: ready` (drafted + reviewed + fixes applied) | docs/changes/CLIENT-f-mac-app.md | Owner chose end-state Mac+iPhone+iPad (full Athena-style). **ADR-017 written**; research → `docs/research/2026-06-12-multiplatform-swift-client.md`. **CLIENT-c/d/e amended** (Authenticating→ArtemisKit; AppCoordinating screen-seam; macOS auth path). **CLIENT-f drafted AFK** + **apex-swift + apex-security review applied** — 4 BLOCKs resolved (@MainActor panel + hotkey hop · Authenticating/AppCoordinating seam · **App Sandbox ON** (reversed ADR-017 §6 per security review) · exact dep pin + Package.resolved); FLAGs folded (sharingType=.none, lastError redaction, pasteboard note, passcode posture, deploymentTarget→14). overview/ROADMAP/ADR-index updated. App-Sandbox-ON reversal ✅ owner-confirmed. 2 hardware-gated auth unknowns remain for first Mac build. | ADR-017 · CLIENT-c/d/e · CLIENT-f (new, ready) · overview.md · ROADMAP.md |

| home-lab expansion (BANK) | planning | ✅ PARKED — standalone bank, not a spec | docs/research/2026-06-13-local-llm-expansion/README.md | Self-contained future-proofing bank (separate from spec corpus). All decisions resolved; trigger-activated. **Open the bank README when a hardware trigger fires** (T1 M5 Ultra / T2 Kimi-or-training / T3 want local coding now) → draft EXP-a/EXP-b. Otherwise info-bank only. Add new expansion research to the bank, not here. | — |
| validation slice 1 — Python spine (M0-a→M1-c) | coding | ✅ COMPLETE — 73 tests, mypy + ruff clean | `docs/findings/windows-buildable-spine-slice.md` | M1-d (time tool, heartbeat skeleton, e2e brain test) + M1-c (Gateway + dev CLI + SSE streaming API) + M0-b health stubs. 73/73 tests, 12 new files. | ✅ 72cf9a6 |
| validation slice 2a — M4-a bitemporal core | coding | ✅ COMPLETE — schema + repo + golden (Tasks 2/4/6) | docs/changes/done/ | sqlite-vec column-level cosine; Tasks 1/3/5 (encryption) Mini-gated. 33 golden tests, 0 real model calls. | ✅ b234bac |
| validation slice 3 — dev enablers (flash) | coding | ✅ COMPLETE — 112/112 tests | docs/changes/done/dev-model-auth.md · dev-offline-compose.md | `ARTEMIS_MODEL_API_KEY`→Bearer on both adapters + `compose_brain(embedder=,model=)` overrides + `scripts/dev_chat.py` FakeEmbedder REPL. | ✅ b3d868a |
| validation slice 3a — LanceDB vectorstore | coding | ✅ COMPLETE — 9 tests, mypy + ruff clean | docs/changes/done/slice-3a-lancedb-vectorstore.md | `LanceDBVectorStore` (dense cosine KNN + FTS + dimension-lock). 3 files created: `knowledge/__init__.py`, `knowledge/vector_store.py`, `tests/test_vector_store.py`. | ✅ 5975b30 |
| prebuild test-review walkthrough | planning | ✅ COMPLETE — all 12 sections reviewed + synthesised 2026-06-18 | docs/findings/prebuild-test-review-findings.md | Section-by-section owner review of the 121-test validation suite DONE. Synthesis → `docs/findings/prebuild-test-review-findings.md` (3 buckets): **(1) fix-queue** ~15-min DeepSeek (mypy-scope root `mypy src tests` + F6-a flaky FakeEmbedder→hashlib + F11-a/F12-a annotations + F3-a/F6-b hollow asserts + cosmetics) — promotable to `docs/changes/fix-validation-test-quality.md`; **(2) Mini-verification checklist** (ranking quality · FTS-live · SQLCipher+crash-safety · **F8-c power-loss posture** · /readyz · token streaming); **(3) design follow-ups** F2-a/F2-b/F9-a/F8-a + video keepers **V-1 whole-doc/aggregate** + **V-2 grill-me elicitation** → BACKLOG. Live @5975b30: 121 pass · ruff clean · mypy clean on `src`, 14 errs under `src tests`. | — |
| fix-validation-test-quality | coding | ✅ COMPLETE — 121 tests, mypy+ruff clean, 0 flaky | docs/changes/done/fix-validation-test-quality.md | Mypy-scope root fixed (pyproject `files = ["src", "tests"]`); FakeEmbedder de-flaked (hashlib); annotation/tightening cosmetics. 7 files changed, archived to done/. | ✅ fff0a5f |
| owner-rules capture | planning | ✅ COMPLETE — all 6 surfaces captured/defaulted | docs/owner-rules/ + finance.md | **Scanned ~20 automation/rule-bearing specs (6 parallel agents) → 6 capture workbooks + index + elicited owner values.** Captured: S1 proactivity ✅ (quiet hrs 23:30→07:15, gentle-nudge, **WAKE-triggered morning digest**, reviews: Sat-wake weekend + Sun-eve week-ahead), S2 scheduling ✅ (tz=Asia/Singapore, 09:00–18:00 Mon–Fri, **morning focus-window**), S3 email ✅ (VIPs Ashley/Debby, notify=legal+payment only, important≠notify, Finance reconciliation), S4 memory ✅ (what-to-remember w/ Ashley anchor, **financial+health excluded**, A.U.D.N.=keep-both+dated, precision-floor; decay→Mini), S5 ✅ (autonomy boundary CONFIRMED, auto-tagging precision-first, cloud=general-skills-only/email-local; token caps→M7-c build, egress=system), S6 ✅ (defaults accepted). **8 SPEC GAPS surfaced → `docs/owner-rules/00-INDEX.md` §Spec gaps** (apply as amendments when modules build): wake-hook type · working_days · Gmail Stage-1 widen · bank→Finance routing · Finance reconciliation (done in finance.md) · needs_review tagging state · classify_safety internal tier · preferred_focus_window. | ✅ 02696bf + session-end commit |
| cross-module reactions (surface 7) | planning | ✅ COMPLETE — approach locked + ADR-021 written | docs/technical/adr/ADR-021-cross-module-reactions.md | **Cross-module "when X → then Y" reaction LAYER designed + locked.** Triage (46 reactions, A–E+D) + deep-dives (B4c amount-gated confirm @ ~S$500 · E8 reclassified = hub view) + wiring audit (27 ACCOUNTED · 17 PARTIAL · 2 GAP, both resolved) all done. **Approach LOCKED 2026-06-21 = hybrid learned-first** (owner chose opt 1 of 4; rejected built-in/declared/pure-learned) → **ADR-021** written: 3 pieces (emit · rule store · dispatcher) · shared fuzzy-match reconciler · link-integrity declared-contract+reconciler · stateful/windowed reactions first-class · hub-view carve-out (E8/E7/D4) · GATE posture · **5-capability dependency list** (M4-b module push · M4 fact-emit · finance.instrument · Trip entity+Maps de-park · gift-signal+share/clip channel) + Goals-deferred + E5 provenance OQ. D3 dropped. **Next: build specs (3 infra + reconciler + 5 amendments + per-cluster recipes) at Mini-build, against ADR-021.** | ✅ 885e4b6 |

| design session 2026-06-21→22 | planning | ✅ COMPLETE — closeout committed + both follow-ups resolved | docs/technical/adr/ADR-005 + ADR-021 + ADR-004 | **Surface 7 reactions LOCKED → ADR-021** + **cross-store provenance → typed source ref** (ADR-004) — closeout **committed 885e4b6**. Resumed 2026-06-22 + resolved both follow-ups: (1) **phone-less unlock = recovery passphrase (break-glass escrow)** → **ADR-005 Refinement 2026-06-22** (owner redirected the Tier-0 question into this; first-Tier-0-signal candidate stays parked, an M6-build call); (2) **`uv` dev-deps migration → MIGRATE** (owner: clean, regardless of work) → new ready spec `uv-dependency-groups-migration.md`. | ✅ 885e4b6 + this-session commit (ADR-005 · new spec · status.md) |

| design/build session 2026-06-22 (cont.) | planning | ✅ sensitive-handling RESOLVED → ADR-022 Refinement · UI theme still unpicked | docs/technical/adr/ADR-022 · docs/changes/brain-sensitivity-routing.md · docs/design/ | **Sensitive handling LOCKED = upgraded hybrid, phased** (scope-out REJECTED): local-model gate at the INGESTION seam (fail-closed) + Codex-distilled reasoner; posture = option C → **ADR-022 § Refinement 2026-06-22**. `brain-sensitivity-routing` **REDRAFTED → `status: ready`** (regex retired; local-model gate, loopback-guarded, fail-closed; security+python spec-review folded — 2 BLOCKs each resolved); `distill-datagen-pipeline` to gain sensitive-domain categories + pluggable Codex teacher (future). `codex-model-adapter` + `composite-model-routing` stay READY. **UI theme LOCKED 2026-06-22** → `docs/technical/architecture/design-brief.md` created: Holo Tactical panel + **ambient theming** (4 seasons × 4 time-states incl. night=quiet-hours = ~16 palettes; calendar+clock-driven; seasons decorative since SG is seasonless). 9 palettes vetted (from mockups) + 7 draft (Summer ×4, night ×3) to hand-tune. **Next: queue the ingestion-gate + distill amendments (future M3/M8); optionally extend the mockup HTML to the full 16-cell grid.** | ADR-022 · brain-sensitivity-routing.md (redraft) · design-brief.md (new) · status.md (this commit) |

_(Build status after slicing: the validation slice confirmed the brain spine is WSL2-buildable. Remaining ~60 specs are Mini-gated.)_
<!-- CODING:END -->

<!-- PLANNING:START -->
## Pending Specs
_~60 specs `status: ready` in `docs/changes/` (M4-c split into M4-c-1/M4-c-2 on 2026-06-12; fix-validation-test-quality done + archived to `done/` 2026-06-18; **`tooling-cleanup` added `status: ready` 2026-06-19** — WSL2-buildable protocol-gap fix + format drift, not Mini-gated; **`uv-dependency-groups-migration` added `status: ready` 2026-06-22** — WSL2-buildable PEP 735 dev-deps migration + 2-doc alignment, build BEFORE `tooling-cleanup`; **3 brain-Codex specs added 2026-06-22, security+python reviewed & folded:** `codex-model-adapter` (✅ done 1616894) → `composite-model-routing` (✅ done 15388f5, archived to `done/`) → `brain-sensitivity-routing` (**ready — REDRAFTED 2026-06-22** to a local-model gate; regex retired) — wire Codex (ChatGPT subscription) as the cloud reasoning engine behind the `ModelPort` seam + hybrid sensitivity routing (ADR-022); WSL2/Windows-buildable, build in that dependency order. `brain-sensitivity-routing` redraft (security+python spec-review applied — 2 BLOCKs each resolved): the gate is a **cheap local model** that classifies the typed request on-box, **loopback-guarded** (refuses non-local endpoints → fail-closed), **fail-closed at every layer**, `<user_request>` injection-delimiter, kill-switch `cloud_reasoning_enabled`. One documented residual: a 4B classifier isn't fully injection-proof (accepted v1, single-owner). The ingestion gate (corpus protection) is a separate future M3/M8 amendment.). **Zero parked spec
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
| M6 chain prereqs | **M6-chain-prereqs (1, ready)** | Blocker resolution 2026-06-24: async `on_hits` contract patch (heartbeat.py + 3 tests) + `ntfy_topic_secret` Settings field. **Build BEFORE M6-b → M6-c.** |
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
- **🟢 NEW (2026-06-23) — dev-machine local-model stack DESIGNED + specced (ready).** Ollama on the 8GB Windows box (dev
  twin of M0-c's mlx-openai-server, both behind `roles.toml`): embedder Qwen3-Embedding-0.6B + reranker Qwen3-Reranker-0.6B
  + responder Qwen3-4B (which **also serves as the sensitivity classifier** — decided) ≈ 4GB, all hot, no eviction at this
  lean scope. Swaps the validation slice off FakeEmbedder/cloud-only onto **real local models** so the brain is tested for
  real. → ready spec `docs/changes/dev-model-stack-ollama.md` (3 files: roles.toml→Ollama · `dev_chat --real` flag ·
  `DEV-MODEL-STACK.md` runbook). Its acceptance criteria (tool-calling + structured-output through Ollama/Qwen3)
  **empirically answer ADR-022 parked (b)**. Deferred: 8B sensitive reasoner (N/A till distilled post-Mac) · vision (M3-d) ·
  voice (M5); non-sensitive cloud path = Codex (separate adapter).
- **🟢 NEW (2026-06-23) — M9 Task Executor design DECIDED → ADR-024 Refinement 2026-06-23.** Supervised long-horizon
  executor fully designed (autonomy ceiling · owner per-task unattended-vs-supervised flag · plan-preview trigger ·
  plan→act→verify loop w/ deterministic-read-back verification · linear plan + reserved parallel-groups ·
  plan-fresh-compose-recipe-fragments · two-tier task-memory w/ sensitivity-defer guardrail · risk+milestone agent-inbox
  check-ins · per-task deadline+token-ceiling + intra-GPT model tiering + token-bucket retries + circuit-breaker · GPU
  residency priority). M9 stays post-spoke-wave; logic Windows-buildable. **2 follow-ups — both RESOLVED 2026-06-23:**
  (a) ✅ M7 recipes → **atomic composable primitives** (recipe = one capability; whole task = saved plan of recipe-refs);
  model-agnostic format (skill-shaped, NOT Codex AGENTS.md / vendor-tied) — reshapes M7-a1/a2 at M7 spec time (M7 not built).
  (b) ✅ Intra-GPT tiering **works in-subscription** — Codex CLI `--model` picks `gpt-5.5`/`gpt-5.4`/`gpt-5.4-mini` (no metered
  API; per-model quota → mini ~4× throughput) → `docs/research/2026-06-23-codex-subscription-model-tiering.md`.
- **🟡 CLIENT re-scope — DESIGNED 2026-06-23 (ADR-028 Refinement); spec rewrite PENDING.** The CLIENT-a..f specs are stale
  on **three axes** (platform Swift→**Tauri** per ADR-023 · auth → **P-256/TPM/Hello/SE** per ADR-025 · nav tabs→**map** per
  ADR-028) — so the re-scope is a **rewrite of the client spec layer**, not a nav tweak (only the *contracts* carry over:
  connection/lock state machine, pairing, endpoint shapes, screen content). **Design DONE this session** → ADR-028 §Refinement
  2026-06-23: domain set + **functional-cluster** default layout (Comms/Planning/Knowledge/Self) · **user-arrangeable +
  persisted** map · shell defaults (constellation links ON · reduced-motion crossfade · 4 poles) · **WebKit-safe build**
  watch-item (Tauri webview differs Win/Mac; brain→Mini is transparent to the client; client→Mac = recompile) · and the
  **spec carve** (7 SwiftUI specs → 7 new Tauri specs: core·auth·world·card·ask·screens·theme; **CLIENT-f retires** to a
  build target). **PENDING:** write the 7 new Tauri specs (the rewrite pass) + a deferred **fonts pass**. Refs: ADR-028 ·
  ADR-023/025 · `design-brief.md` · mockup `docs/research/mockups/travel-zoom-workspace.html`.
- **✅ RESOLVED 2026-06-23 — architecture-validation reservations: all decided AND applied (A–J).** Research
  (`docs/research/2026-06-23-architecture-validation/`, 3 reports): substrate SOTA-aligned but storage over-built vs the
  cognitive layer. All cheap-now/expensive-later hooks were walked one-by-one and **applied across 12 corpus files**
  (additive reservations only — nothing built yet): (A) `source_kind="derived"` + `source_ref` list + reserved
  `derivation_method`/`derivation_confidence` → ADR-004 + M4-a; (B) record-type-generic `MemoryStore` port + (C)
  async-write-default/scope-on-every-method regression-guard → M0-d; (D) RAPTOR summary-tree fields + (E)
  structured-projection ingest hook → M3-a; (F) shared checkpoint/replay + idempotency convention (Task Executor /
  heartbeat / recipe-runner) + (G) first-class router→planner escalation seam → ADR-024 + M1-b + M6-a + M7-a2; (H1)
  non-sensitive fallback ladder **Codex → DeepSeek-Pro-API → local Qwen3-Instruct** (final checkpoint benchmark-at-Mac) +
  (H2) recipe-quality gate + re-seed → ADR-022 § Refinement 2026-06-23 + M7-b + distill pipeline; (I) parametric-memory
  stance + (J) prospective-memory home (no new store) → brain.md. **64GB RAM reaffirmed** as highest-leverage + a
  model-residency/load-evict seam reserved + a **dev-box 8GB VRAM budget produced**. Decision+application log in
  `docs/drafts/architecture-validation-reservations.md`. **ADR-027 resolved 2026-06-23:** intentional Artemis numbering
  skip (= APEX-system ADR, per the overview ADR index) — no Artemis ADR needed; runtime routing lives in ADR-022, the
  build coder in ADR-026.
- **✅ RESOLVED 2026-06-22 — privacy-routing policy = HYBRID → ADR-022 ACCEPTED.** Sensitive tasks (finance/health/journal/
  memory) reason on a **LOCAL** model and never leave the box; everything else → **Codex/cloud subscription**; the sensitivity
  router gates it. **Privacy wall KEPT** — M2/ADR-003/005/006 + the local sensitive-reasoner + recovery-passphrase/passkey all
  stay in force; **nothing retired** (net change is additive — a cloud path for the non-sensitive surface). **Remaining:** model
  expected usage vs the Codex 5h/weekly rate caps (+ fallback API cost) · owner runs `codex login` + `codex exec` to confirm the
  subscription path on their plan.
- **✅ RESOLVED 2026-06-22 — sensitive-handling architecture = upgraded hybrid, phased (scope-out REJECTED; posture = option C).**
  Owner pressure-tested the hybrid and locked an improved version (→ **ADR-022 § Refinement 2026-06-22**), folding in BOTH the
  earlier "scope sensitive data out entirely" idea and the blocked posture question. **Rejected** full scope-out (too blunt for
  incidental email; gives up sensitive assistance). **Gate:** regex → a **cheap LOCAL model at the INGESTION seam**, **fail-closed**,
  reads on-box (no cloud round-trip) — this is posture **option C (local-classifier-first)**, which retires the regex
  false-negative leak the apex-security BLOCK was about. **Reasoner:** base-local → **Codex-distilled** (teacher trains on
  **synthetic** data only — real records never leave; reuses `distill-datagen-pipeline`; teacher seam pluggable Claude/Codex).
  **Phasing (additive):** now = local-model gate + detect-and-drop + start the distill drip; later (Mac+training) = the distilled
  reasoner graduates into `sensitive_reasoner` → detect-and-route-local. **Spec impact:** `brain-sensitivity-routing` unblocked
  but **regex mechanism superseded — needs redraft** to the local-model/ingestion gate (banner added at the spec top);
  `distill-datagen-pipeline` gains sensitive-domain categories + the pluggable Codex teacher.
- **🟢 NEW (2026-06-22) — open follow-ups from the re-look (ADR-022 §Parked):** (a) model a real monthly API cost for the
  local-trigger + on-demand-cloud design; (b) the **constrained-decoding × Pydantic AI** integration check on Windows/Ollama
  (does Pydantic AI wrap or fight Outlines guaranteed-valid output from a local 4B); (c) **first-hand Hermes repo read** to
  extract the GEPA self-improving-skill + layered-memory specifics for the recipe system (borrow, not build-on).
- **✅ RESOLVED 2026-06-22 — `uv` dev-deps migration → MIGRATE (own spec).** Owner chose to migrate regardless of
  work, "just ensure it is clean." Mapping the blast radius showed it's tighter than feared: the apex-python Verification
  Recipe **already** prescribes `[dependency-groups].dev` + bare `uv sync` (impl.md lines 24–25/96/119) and the RUNBOOK
  already uses bare `uv sync` — so neither needs editing; the migration brings the project *into compliance* with its own
  recipe. Most specs reference plain `uv sync` (which becomes correct post-migration). Only 3 hand-edited files:
  `pyproject.toml` (the migration) + `tooling-cleanup.md` (drop its explicit `--all-extras`) + `M0-a` (pin the layout in
  prose). → new ready spec **`docs/changes/uv-dependency-groups-migration.md`** (flash, WSL2-buildable, **build BEFORE
  `tooling-cleanup`** — after migration bare `uv sync` installs dev tools).
- **🟢 NEW (2026-06-22) — phone-less unlock = recovery passphrase (break-glass escrow) → ADR-005 Refinement.** Owner
  raised the gap (no unlock path without the phone) while reviewing the Tier-0 question and chose a **recovery passphrase**:
  Argon2id-derived KEK wraps an escrow copy of each per-scope DEK; rare / audited / rate-limited break-glass; **not** a
  routine override PIN; second-device attestation deferred (non-breaking — each paired device already enrols its own SE key).
  Resolves the standing ADR-005 consequence "phone loss = key compromise; need escrow flow." Build at M2 (Mini-gated). The
  separate **first Tier-0 *signal* candidate** (calendar-derived vs weather-only) stays **parked** — an M6-build-time call
  when the minimised-corpus schema is designed (ADR-006 Parked).
- **🟢 NEW (2026-06-17) — validation slice: build the Python spine pre-Mini. AUDITED → GO.** The "build waits for
  the Mini" rule is an **inherited assumption** (owner-confirmed), not a constraint — the brain spine is pure Python
  and MLX is a swappable OpenAI-compatible endpoint. Build a thin vertical slice (M0-a→M0-d→M1-a→M1-b→M1-d→M1-c) in a
  DeepSeek coding session on WSL2 (cloud model-port, test-only) to get the corpus's first execution signal. Full brief +
  proposed slice + caveats + how-to: **`docs/findings/windows-buildable-spine-slice.md`**. De-risks the batch;
  ADR-002 (Mini = prod) unchanged. **✅ Open sub-question CLOSED 2026-06-17** — line-audited M0-d/M1-a/M1-c/M1-d:
  no hidden Mac/MLX dep (only M1-b Task 5 live-model is gated = the endpoint seam; all else fake-testable; two trivial
  frictions = cosmetic Mac paths + `/opt/artemis` mkdir). **Endpoint config decided:** LLM → DeepSeek native
  OpenAI-compatible endpoint (`api.deepseek.com`, NOT the Anthropic proxy Claude Code uses); embeddings → keep the spec's
  `FakeEmbedder` (DeepSeek has no `/embeddings`; fine — 1–2 tools, prod embeddings are local-MLX anyway). **Build = a
  QUEUED coding task** (no context-switch yet). **Slice 2 on-deck = M4-a bitemporal core** (storage/data-model risk; sequenced
  not bundled). **🟡 M4-a pre-audit done = YELLOW:** M4-a also needs M2-b+M2-c (security wall) + a hardware-GATED Task 1
  (sqlite-vec-under-SQLCipher spike, Mini-only). Recommended **slice 2a = reduced bitemporal core** (schema/repo/golden
  tests on the plain-sqlite+sqlite-vec fallback, Tasks 2/4/6; stub M2-dependent store + skip encryption) — high signal,
  no M2 wall, no Mini, WSL2-buildable. Full M4-a (slice 2b) defers to the Mini.
  **Resume = owner spins up the DeepSeek/WSL2 coding session → build slice 1 → handoff steers slice 2.**
- **🟢 NEW (2026-06-17) — embedding layer DECIDED (de-parks "embedding tier").** Research:
  `docs/research/2026-06-17-embedding-implementation.md` (confidence: high — mostly confirms locked defaults).
  **DECIDED:** Qwen3-Embedding-0.6B @ **1024 dims**, **ONE model across BOTH stores** (M3 LanceDB docs + M4 sqlite-vec
  memory), **no MRL truncation** (saving invisible at personal scale, measurably hurts recall, dimension is locked per
  store), paired with **Qwen3-Reranker-0.6B**, served via mlx-openai-server `/v1/embeddings`. 0.6B = default; 4B only
  behind an on-hardware eval gate. **Owner decision (2026-06-17): SPLIT the `EmbeddingModel` port → `embed_query` /
  `embed_documents`** (least error-prone: encodes Qwen3's query-prefix asymmetry in the type system vs prose discipline a
  literal executor can silently drop — the ~1–5% silent-degradation footgun). **✅ AMENDMENT WAVE DONE 2026-06-17** (AFK agent; spec edits
  only, no code exists). `EmbeddingModel.embed(texts)` split → `async embed_documents(texts) -> list[Vector]` (stored text,
  no prefix) + `async embed_query(query) -> Vector` (single in/out; adapter applies the Qwen3 `Instruct:…\nQuery:…` prefix).
  Applied across (broader than first scoped — agent grep-found all call sites): **M0-d** (port split; `ModelPort.embed` +
  `dimension` untouched) · **M1-a** (descs→docs, lookup→query) · **M1-b** (`OpenAIEmbeddingModel` impls both; prefix in
  adapter) · **M3-a** (chunks→docs) · **M3-b** (query→query; reranker reframed fallback→**PRIMARY** chat-completions, no
  `/v1/rerank`) · **M3-d** (OCR chunks→docs; `VisualRetriever.embed_page` untouched) · **M4-a** (recall→query,
  add/update_fact→docs) · **M4-b** (fact-triple→docs) · **M4-c-1** (recall→query) · **M4-c-2** (edit_fact→docs) · **M7-a1**
  (recipe write→docs, retrieve→query) · **contracts.md Seam 1** · **ADR-015** (dated amendment note). Every `FakeEmbedder`
  test-double updated to both methods; consistency grep = 0 live stale call-sites. Resolves all 4 research-doc open
  questions (split = #1; #2/#3/#4 = recommended-yes, accepted). **Verify at M0-c gated probe:** Qwen3-Embedding actually loads on mlx-openai-server (RAM for 3 resident
  models: responder + embedder + reranker; named fallback `mlx-embeddings`).
- **Home-lab / local-inference expansion — PARKED in a separate BANK (not a spec).** All research +
  decisions live in `docs/research/2026-06-13-local-llm-expansion/` — **start at `README.md`** (bank
  index) → `_SYNTHESIS-PLAN.md`. Self-contained and trigger-activated: open it when a hardware trigger
  fires (T1 M5 Ultra ships / T2 Kimi-or-training need / T3 want local coding now), otherwise it's an
  info bank of options + field anecdotes ("what people have done"). Decisions A/B/C + D-plan-1/2 all
  resolved; software side is config-only and does **not** touch the frozen ~61-spec corpus; EXP-a/EXP-b
  specs drafted only when a trigger fires. **Add new expansion research to the bank, not here.**
- **✅ RESOLVED 2026-06-21 — cross-store fact provenance → typed source reference.** Traced the path: M4-b
  write path is turn-shaped (`source_turn_id` → `episodes.turn_id`); a document-sourced fact (reaction E5) had
  nowhere to point, AND the push path itself doesn't exist (audit X-cut #3). **Decision (owner, opt A): generalize
  provenance to `source_kind ∈ {turn, document, module}` + `source_ref`** (doc-fact → M3 chunk_id, chunk-level if
  stable else doc-level; module-fact → record id). Cross-store refs resolve **tool-mediated, never a DB join**
  (ADR-013 D2), preserving the M2 wall; serves every module→Memory push, not just docs. **Recorded:** ADR-004
  Refinement 2026-06-21 (provenance row + new refinement section) · ADR-021 dependency #1 (the M4-b module-push
  amendment is the build vehicle — no new build item) · E5 line. Applied at M4 finalization / the ADR-021 amendment wave.
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
- **Parked (build phase):** Graphiti vs Mem0 · local teacher 30B-A3B vs 32B · macOS 26 ·
  Swift-vs-Python AEC · mic XMOS · Pipecat vs Wyoming · local LoRA · backup device + offsite · Headscale swap ·
  2nd build box · watch LAN TLS · Litestream vs VACUUM · Tailscale ACLs · Maps connector (Calendar travel-time) ·
  Habits/Goals (Productivity deferred sub-domains, time-blocking rail reserved).
<!-- PLANNING:END -->
