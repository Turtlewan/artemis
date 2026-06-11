# Cross-corpus consistency audit — 2026-06-10

_Sweep scope: governing docs (architecture/, adr/, modules/, ROADMAP, REQUIREMENTS, status.md, PROJECT.md) vs the 60-spec `docs/changes/` corpus. Checks: ADR↔architecture drift · dependency/build-order sanity · naming/terminology · coverage · status.md accuracy · stale aux docs. Per-spec depth is out of scope (other agents)._

**Ground truth established:** `docs/changes/` contains **60 spec files**, all `status: ready`; `done/` is empty. The status.md Pending-Specs table enumerates exactly these 60 (its per-milestone counts sum to 60) — only the prose counts drift (see F-04).

---

## BLOCK — contradictions that would mislead the build

### B-01 · ROADMAP.md build-handoff is the designated build authority and is ~28 specs out of date
- `ROADMAP.md:3` claims "**32 specs are READY**"; `ROADMAP.md:45` "32 specs total"; `ROADMAP.md:48` says spokes "(M8+, **not yet specced**)". Actual: **60 ready specs**, including 14 spoke specs (M8-a/b1/b2, CAL-a..d, M8-d-a/b/c1/c2), GATE-a/b, M4-d-1/2, M0-f, and distill-datagen-pipeline.
- The §"Build handoff — start here" rules cover only M0→M7 + the OBS/DR/CLIENT backlog. They give **no build order for GATE → CAL → M8-d → M4-d → M0-f**, yet both `docs/status.md` (lines 39, 47, 95) and `docs/changes/` specs route the builder to "ROADMAP §Build handoff" as the authority. A DeepSeek session following ROADMAP literally would (a) believe the spoke wave is unspecced, (b) not know GATE-a must precede CAL-b, CAL-b must precede M8-d-b, M4-a/b/c (+M1-a/c) must precede M4-d-1/2, or M6-c (amended `pre_tick_steps`) must precede M8-b2.
- Also stale in the same file: header cites "ADR-001..007" (13 ADRs exist); `ROADMAP.md:65` "Hardware finalisation … WWDC-pending" (decided 2026-06-09, ADR-001 §Refinement).
- **Fix:** rewrite ROADMAP phases + handoff to the 60-spec graph (the status.md Pending table is already correct and can seed it).

### B-02 · "Gated writes = TAKES_ACTION *recipes*" survives in three governing docs despite ADR-012 superseding it
ADR-012 (2026-06-09) decided gated one-off external writes are **`PendingAction` instances via `ActionStagingService`/GATE-a — explicitly NOT recipes**. The spec corpus complies (CAL-b Identity: "stages gated one-off actions as owner-pending `PendingAction` instances (not recipes — see ADR-012)"; CAL-c prerequisites: "M7-b is NOT a prerequisite … ADR-012 §1"). But:
- `docs/technical/architecture/overview.md:211` — "**All external-effect writes are gated `TAKES_ACTION` recipes through the Review screen**" (the exact ADR-011 §6 wording ADR-012 refined), while the same file's ADR index lists ADR-012.
- `ROADMAP.md:58` — "write-enabled spokes … route their gated `TAKES_ACTION` recipes through its Review screen."
- `docs/technical/modules/calendar.md:53-56` (§B "Gating mechanism") — "a gated action … becomes a **`TAKES_ACTION` recipe staged for the Review screen** (CLIENT-b / M7-b)". calendar.md declares itself "Source-of-truth for the CAL-* specs", so this is a live contradiction with the CAL-b spec it governs.
- **Fix:** replace with the ADR-012 wording (PendingAction → ActionStagingService → GATE-b pending-actions tab) in all three.

### B-03 · Memory-extraction model: brain.md + data-model.md say "teacher"; REQUIREMENTS + M4-b spec say local `sensitive_reasoner` — privacy-load-bearing
- `docs/technical/architecture/brain.md:80` — "Entity/relation extraction runs on the **teacher**, not the 4B."
- `docs/technical/architecture/data-model.md:69` (§3 SemanticFact) — "extraction runs on the teacher."
- vs `REQUIREMENTS.md:34-36` — "the A.U.D.N. write path (**extraction + decision on the local `sensitive_reasoner`**, grammar-constrained)" and `docs/changes/M4-b-write-path-audn-extraction.md` prerequisites — "roles.toml already defines `sensitive_reasoner` (Qwen3.6-27B) — M4-b reuses it; NO new role."
- Owner memory content is sensitive; brain.md's own privacy policy and ADR-003 forbid the cloud teacher seeing it. The "teacher" wording predates the 2026-06-08 Qwen3.6-27B refresh (which made local extraction viable) and was never corrected. A builder reconciling docs could wire extraction to the teacher tier — a privacy violation. data-model.md was "reconciled 2026-06-09/10" yet kept the stale line.
- **Fix:** correct both lines to `sensitive_reasoner` (local).

---

## FLAG — drift / staleness worth fixing

### F-01 · overview.md spec-map and entity-backbone build references are stale despite the 2026-06-10 reconcile
- `overview.md:3-5` + §"Build status & spec map" (lines 243-259): "**43 specs `status: ready`**", table sums 43 (M0–M7=32, OBS=2, DR=3, CLIENT=6) — omits GATE(2), M8 Gmail(3), CAL(4), M8-d(4), M4-d(2), M0-f(1), distill(1) = 60. Header also says "locked across ADR-001…011" while the index lists 13.
- `overview.md:124` — "(Build: a deferred **M4-c amendment** spec adds the tool + key + Place/Goal schema.)" — superseded: the build specs exist as **M4-d-1 / M4-d-2** (ready, commit 88410a8). Same stale "M4-c amendment" naming in `ADR-013` §Consequences + §Parked (acceptable as a point-in-time ADR record, but overview was reconciled the same day the specs landed).
- `overview.md:214` — "**First wave (M8, next to spec)**" — the wave is fully specced.

### F-02 · REQUIREMENTS.md Open Questions + scope framing are resolved-but-not-updated
- `REQUIREMENTS.md:74-76` hardware question "Pending **WWDC 2026**" — resolved 2026-06-09 (ADR-001 §Refinement: wait for M5 Mini, buy 64GB).
- `REQUIREMENTS.md:65-67` — "owner-approval Review screen … its spec is TBD"; "Observability/telemetry engine + Deep-Research engine — concrete specs are post-gate backlog"; `:80-81` "Post-gate spec backlog — draft after `apex-init`". All drafted and ready (CLIENT-a..e, OBS-a/b, DR-a/b/c).
- `REQUIREMENTS.md:58-62` lists spokes as out-of-scope "M8+ … First spoke wave = Productivity & time + Gmail" with no acknowledgment that 14 spoke specs + GATE are now ready. The in/out contract is still *true* for the v1 core, but the file no longer reflects corpus reality; also cites "ADR-001..007" only. Note `:60` still says Comms "incl. Contacts" — ADR-013 rejected a Contacts module (M4 is the entity home).

### F-03 · Hardware-pending wording lingers in architecture docs
- `overview.md:13` — "(M4 Pro 48GB, ADR-001; 64GB re-decision **WWDC-pending**)" and `brain.md:23` — "lock held … **pending WWDC this week**" — both superseded by ADR-001 §Refinement 2026-06-09 (decision made: wait for M5 Mini, 64GB; 48GB stays the minimum-spec floor). `docs/status.md:4` stack line also still reads "Mac Mini M4 Pro 48GB" while line 116-120 of the same file records the new decision.

### F-04 · status.md spec-count prose is internally inconsistent (table is correct)
`docs/status.md` says "~59 specs ready" (lines 24, 46), "~56" (lines 39, 92), "~55" (line 155). Actual = **60**, and the Pending-Specs table itself enumerates 60. Harmless to a careful reader, confusing to an automated one; normalize to 60 (or drop the prose counts and trust the table).

### F-05 · app-flow.md predates ADR-012/013 and shows it
- `app-flow.md:4` — "keep them coherent with this one anchor (**ADR-013 technique**)" — written 2026-06-08 when no ADR-013 existed; the number now resolves to *cross-module links*, which is unrelated. Broken/misleading reference.
- §Review screen describes **recipes only**. ADR-012 §4 + GATE-b add a "Pending actions" section/tab with distinct approve semantics ("execute once" vs "auto-enable"), and Status gains nothing but Review's source list changes (`/app/actions/*`). The "navigation + journey anchor" should carry the second Review surface, or GATE-b's UI sits outside the anchor it is supposed to cohere with.

### F-06 · calendar.md + finance.md trail the ADRs they feed
- `calendar.md:108-112` §Spec decomposition lists CAL-a/b/c ("likely 3 specs") — 4 shipped (CAL-d split out knowledge/memory/untrusted). Minor, but the doc says it is the CAL-* source of truth.
- `finance.md:85-87` — "the cross-module-linking *contract* … needs a dedicated dive — **likely a future ADR** … finance.md applies the M8-d-b pattern ad hoc pending that." That ADR now exists (ADR-013, locked 2026-06-10) and finance.md never binds the **`person_fact_key`** pointer ADR-013 mandates for exactly the Finance-class spokes ("must be locked before Finance … is specced"). Update before FIN-* drafting.

### F-07 · Stale forward references inside spec headers (cosmetic but in the corpus)
- `M7-b-promotion-policy-review-surface.md` prerequisites — "client-app spec TBD"; `M7-c-curiosity-loop.md` — "the observability/telemetry spec … and the Deep-Research engine spec" listed as *to spec separately*. All three exist (CLIENT-*, OBS-b, DR-c). The Protocol-fake build path still works, so no build impact.
- `M8-d-c1-hooks.md` "Specs this enables: **M8-d-c** … parked pending c1" — the successor is named `M8-d-c2` and is ready, not parked.

### F-08 · docs/briefs/CAL-* carry the pre-ADR-012 recipe-staging wording (historical — flag only)
`docs/briefs/CAL-b-write-gating-activitylog.md:12,31` — "stage a `TAKES_ACTION` recipe (Review seam)". Briefs are dated 2026-06-08 (pre-ADR-012) and the final CAL-b spec corrected this, so they are safely historical; consider a one-line "superseded by ADR-012" banner since `CAL-shared.md` tells drafters to "bind to" these decisions. `docs/archive/sp0/` and `docs/bring-up/` checked: no contradictions found (SECRETS-INVENTORY/RUNBOOK reflect M0-f and the M5-Mini decision).

### F-09 · PROJECT.md is frozen at pre-SP0
`PROJECT.md:11-18` — "Success looks like _TBD — defined by SP0 requirements-gathering_" and "REQUIREMENTS.md … the System Overview … **not yet written**". SP0 closed weeks ago; every named artifact exists. Lowest-traffic file, but it is the project's front door.

### F-10 · brain.md "skill" terminology vs the locked "recipe" vocabulary
`brain.md` §Self-improvement + §Teacher use "skill / SKILL.md / skill library" throughout; the project's locked term is **recipe** (data-model.md:105 carries the terminology note; M7/overview comply). brain.md is a pre-rename research-decision layer, so this is expected drift — a one-line "(now: recipe)" gloss at §Self-improvement would prevent a builder reintroducing `Skill` types.

---

## UPGRADE — doc-structure improvements

### U-01 · One authoritative build-order table
The only complete 60-spec dependency view today is the status.md Pending table (a PLANNING block that gets rewritten every session). Move/copy the per-milestone table into ROADMAP (fixing B-01) so the build authority and the live tracker can't diverge again, and have status.md point at it.

### U-02 · "Tier" is overloaded across three vocabularies
Tier-0/Tier-1 proactivity (ADR-006) · sensitivity Tier voice gate (M5, reads `data_scope`) · HIGH/Medium secret tiers (SECRETS-INVENTORY) · "Tier-2 distillation" (distill-datagen title) · local/Claude/DeepSeek trust tiers (brain.md). Each is internally consistent, but `SECRETS-INVENTORY.md` row S3 already has to write "HIGH — Tier-1 owner-private" to disambiguate. A 5-line glossary in overview.md would inoculate the build.

### U-03 · data-model.md status header still reads "SP0 phase 4"
The doc is being maintained as the living conceptual model (reconciled 2026-06-09/10) but presents itself as a phase artifact "feeding phase-5/phase-6". Retitle the status line to "living conceptual model" so its currency is not misjudged (it is *more* current than overview.md in places — see B-03 for the one stale line).

---

## RESEARCH — open questions surfaced

### R-01 · The CAP/self-training lane has no home in the scope contract
`distill-datagen-pipeline` (ready) + the ACI capability lane exist only in status.md + research docs. REQUIREMENTS.md (the in/out-of-scope contract) and ROADMAP.md never mention the CAP workstream, the Windows-PC pipeline, or the later Mac-side MLX training spec. Decide where this lane lives (a REQUIREMENTS §, its own roadmap lane, or an ADR) before more CAP specs accumulate.

### R-02 · CAL-b on-hardware Task 7 soft-depends on GATE-b
CAL-b's review-chain note says "verify CLIENT-b has been extended with `/app/actions/*` per ADR-012 §4 **before executing Task 7**" — i.e. the gated round-trip needs GATE-b, which itself needs CLIENT-e. The hard prerequisites (GATE-a) are correct; just confirm the batch build order schedules GATE-b before CAL-b's gated on-hardware task, or marks that task deferred-with-GATE-b. No cycle exists.

---

## Dependency-graph verdict (check 2)

All six prompted edges verified present and correctly ordered in spec headers; **no circular dependencies found**:
- **M4-d-1 → M4-a**; **M4-d-2 → M4-d-1 + M4-b + M1-a + M1-c**, sequenced-with M4-c ✓
- **M8-b2 → M6-c `pre_tick_steps`** ✓ (string present in both M6-c and M8-b2; M6-c amendment recorded in status.md)
- **CAL-b → GATE-a** ✓ (and correctly NOT → M7-b)
- **M8-d-b → CAL-a + CAL-b** (write surface) ✓
- **M8-d-c2 → M7-a1 + M7-b + DR-a** (+ M3-a, M4-b, M8-d-a/c1) ✓
- **GATE-b → GATE-a + CLIENT-b/c/e** ✓
Notable but intended: DR-b → M7-c (grounding-gate code reuse) puts DR after M7 — consistent with the post-gate-backlog ordering; M5-d carries a declared cross-milestone back-fill dep on M1-b `respond_stream`. Naming conventions are clean: spokes under `src/artemis/modules/<name>/`, shared Google auth under `src/artemis/integrations/google/` (matches the resolved status.md convention); `person_fact_key`/`EntityRef` usage is consistent across ADR-013, data-model.md, overview.md, and M4-d-1/2.
