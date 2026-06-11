# Corpus Remediation — Master Plan

_Bridges the 2026-06-10/11 sweep synthesis (`_SUMMARY.md`) into an ordered, executable wave plan.
Goal state: the ~60-spec corpus is batch-handoff-ready for the DeepSeek build on the Mac Mini._

**Owner calibration (2026-06-11):** 3 of the highest-severity BLOCKs hand-verified against the
actual specs — all genuine, all precisely located:
- **B2** — GATE-b calls `ActionStagingService.list_pending()`; GATE-a defines it only on the *store*. ✅ real
- **B5** — CAL-b calls 9 write methods on CAL-a's read-only `CalendarClient`. ✅ real
- **B1** — GATE `approve()` re-dispatches the *gated* tool entrypoint → re-classifies GATED → re-stages;
  approved actions never execute. ✅ real (worst single design bug)

Verdict: the sweep is trustworthy. The per-area reports in this folder are the authoritative
task-lists; this plan orders them.

---

## The model: one Decision Gate, then six waves

```
DECISION GATE (owner) ──► Wave 0 Contracts Freeze ──► Waves 1–4 (mostly AFK / parallel) ──► Exit
```

The 67 BLOCKs are dominated by *interface fictions* — symbol/shape mismatches between specs drafted
in separate sessions. Most are mechanical once the canonical contract is decided. A small set of
seam shapes are genuine **architectural decisions** that must be made before the freeze, because the
fix changes an interface that many consumers bind to. Those are the Decision Gate.

---

## Decision Gate — architectural calls that must precede the freeze

These block Wave 0. Each is a design decision, not an edit. Some warrant an ADR amendment.

| # | Decision | Affects | Options (lead = recommended) |
|---|----------|---------|------------------------------|
| **D1** ✅ | **GATE approval-execution bypass** (fixes B1). **DECIDED: execute-only internal tool target.** approve() dispatches a `<tool>_execute` twin (raw write, no classify). Invariants: (1) the twin is registered **for staging-dispatch only — never exposed to the brain/LLM tool surface**; (2) `PendingAction` stores the **front-door** tool name; `approve()` maps front-door→`_execute` at dispatch (one rule, in contracts.md). | GATE-a, ADR-012, every write-spoke (CAL-b/c, future) | ~~(b) approved-context flag~~ · ~~(c) staging-bypass token~~ |
| **D2** ✅ | **`ModelPort` canonical shape** (fixes M1-b/DR-c/M7-a2 fictions). **DECIDED:** producer = M0-d. Keep M1-b's `stream: bool`→`AsyncIterator`; add `temperature` + `max_tokens` to `complete()`; **`ModelResponse` carries `origin: Literal['local','cloud']` + `model_id`** (response-level egress provenance — M7-a2 reads it, OBS logs it). | M0-d (producer), M1-b, DR-c, M7-a2, all LLM callers | — |
| **D3** ✅ | **Heartbeat hook execution model** (fixes B12, M6-c seam). **DECIDED: async pre-flight + sync `check_ref`.** `check_ref` stays synchronous; ALL async/quarantine work runs in `pre_tick_steps` (awaited before `tick()`), writing laundered safe claims the sync `check_ref` reads. **Pin `pre_tick_steps` ownership in M6-a's runner** (resolves the M6-a/M6-c seam fiction). M8-b2 already conforms; CAL-d migrates onto it (stop awaiting inside `check_ref`). | M6-a/b/c, CAL-c/d, Gmail/Productivity hooks | ~~async hook contract~~ · ~~M6-b render-stage quarantine~~ |
| **D4** ✅ | **Off-hardware SQLCipher behaviour** (fixes F1/R3). **DECIDED: plain-SQLite fallback + hard prod-guard.** `M2-c.sqlcipher_open` falls back to plain `sqlite3` when SQLCipher isn't importable → off-hardware tests run the REAL store over an unencrypted tmp file. **Prod refuses to start unless real SQLCipher is active** (fallback can never silently run unencrypted in prod). Real keyed round-trip stays GATED on-Mini. All stores conform (CAL-a migrates off dict-shims). | M2-c, GATE-a, all 4 Calendar/GATE stores, every SQLCipher store test | ~~gated import + dict-shims~~ |

Tool-name convention (bare vs `module.tool`) is **already decided** (M1-a = bare names, registry
composes the fq id) — it is conformance, not a decision (see Wave 0).

**DECISION GATE COMPLETE — D1–D4 all resolved 2026-06-11.** Ready for Wave 0A (author `contracts.md`
+ amend ADR-012/013). The four decisions feed directly into the seam definitions.

---

## Wave 0 — Contracts Freeze ⭐ (keystone; kills the majority of the 67 BLOCKs)

Two sub-steps. **0A is one new authoritative doc; 0B is per-spec conformance amendments.**

### 0A — Author the frozen shared-contracts doc
`docs/technical/contracts.md` — the single source of truth every consumer binds to. One section per
cross-module seam, each pinning the exact signature/shape (incorporating D1–D4):

1. **LLM `ModelPort`** (D2) — producer M1-b.
2. **ToolRegistry / `callable_ref` contract + tool-name rule** — producer M1-a. (`callable_ref:
   Callable[[Model], BaseModel]`; bare `ToolSpec.name`; registry id = `f"{manifest}.{tool}"`;
   `stage(tool=...)` uses the fq id.)
3. **GATE / `ActionStagingService`** (D1) — producer GATE-a. Add `list_pending()` to the service;
   define the execute-only path; `approve()` execute-once semantics (U1 at-most-once).
4. **`CalendarClient` port — full read + write surface** — producer CAL-a. One canonical signature
   set for the 9 write methods (resolves B5/B6 three-incompatible-shapes).
5. **Heartbeat hook contract** (D3) — producer M6-a/b. `check_ref` shape, payload rules (ids + times
   only), template registration, `pre_tick_steps` seam.
6. **Memory entity backbone** — producer M4-d-1/2. `person_fact_key`, `EntityRef`, `resolve_entity`.
7. **Quarantine / untrusted boundary** — producer DR-a. `QuarantinedReader` shape, sync/async, the
   `artemis.untrusted` helper (folds the ADR-013 follow-up refactor).
8. **Connector ports** — `GmailApiPort` thread methods (M8-a/b1), `CalendarCache.invalidate`
   signature + `EventCacheStore` naming (CAL-a), `CalPrefs` vs `CalendarPrefs` naming.
9. **Pipeline seams** — `PageImage` (M3-d needs, no producer); `Connector`→`IngestPipeline`
   registration (CAL-d F7).

> Decisions D1–D4 + any ADR-significant seam → amend **ADR-012** (GATE execute path) and note in
> **ADR-013**. Record the architectural *why* there, not in the contracts doc.

### 0B — Conformance amendments (per spec, AFK-parallel)
One amendment spec per spec-area, each: (i) fix the *defining* spec to expose the frozen contract;
(ii) patch every *consumer* to call it correctly; (iii) fix the literal-executor syntax traps
(B3 non-default-after-default param ×3; CLIENT-b same). Work-lists = the per-area reports' BLOCK
sections. Areas: M0-M1 · M2/OBS/DR · M3-M4 · M5-M6 · M7/CAP · CAL+GATE · Gmail · Productivity ·
CLIENT · cross-corpus.

---

## Wave 1 — Design-bug fixes (logic, not symbols)

Each is a real "build would be wrong" defect. Spec-by-spec amendments.

- **B1 GATE loop** — implemented via D1 (the execute-only path). The keystone; CAL-b/c bind to it.
- **Quarantine leaks** — raw email subject/snippet reaching privileged models (M8-b1 tool returns,
  M8-b2 urgency payload); M6-c `held.json` persists full bodies plaintext. Close to ids/scores only.
- **M7-a1 verify-before-resign** — `set_status` re-signs unverified recipes (tamper-laundering).
- **M8-d-c2 clean rewrite** — twice-defined `CaptureService` + "Wait — simpler approach"
  self-revisions; also the silent owner-approved→CANDIDATE demotion.
- **Acceptance criteria that ship green on broken behaviour** — DR-b egress (exact-host only; all
  subdomains denied in prod); CAL-a `showDeleted=true` (deletions never propagate, B11);
  `pytest -m integration` exits 5 with zero tests and aborts `pipeline.sh`.
- **`.gitignore`** does not cover the secret-bearing `config/.env.<slot>` files (M0-f).
- **distill-datagen** Windows-PowerShell-5.1 incompatibilities (`&&`, bare `claude` subprocess).

## Wave 2 — Doc-drift alignment

- **ROADMAP.md** — the designated build authority; still says "32 specs READY, spokes not specced"
  (actual: 60, full M8/CAL/GATE/M4-d wave). Rewrite. **Highest priority** — DeepSeek builds from it.
- **overview.md / calendar.md** — gated writes still described as `TAKES_ACTION` recipes (superseded
  by ADR-012). Align.
- **brain.md / data-model.md** — memory extraction described as "runs on the teacher"; it runs on the
  local `sensitive_reasoner`. **Privacy-load-bearing** — fix the line.

## Wave 3 — Research refreshes (build-impact order; AFK-parallel, deferrable)

1. **DeepSeek V4-Flash executor profile** + a spec-lint pass against it — gates handoff quality.
2. **Docling pin** + pipeline choice (Heron vs Granite-Docling) — before M3-a.
3. **Voice-stack refresh** (STT/TTS/speaker-ID/EOU; Kokoro no longer unambiguous) — before M5.

(Also re-confirm the M5-Mini-timing / buy-now-vs-wait hardware question flagged by research-currency.)

## Wave 4 — UPGRADE folding (62 items; security-first, else opportunistic)

Do the security-relevant ones now: DNS-rebinding TOCTOU, redaction substring bug, backfill cursor
ordering, GATE at-most-once (U1), least-privilege scope (CAL-a U4). Fold the rest into the Wave-0/1
amendments as they touch each file.

---

## Sequencing & parallelism

| Stage | Work | Mode | Gating |
|-------|------|------|--------|
| 1 | Decision Gate D1–D4 | **owner, interactive** (one at a time) | blocks 0A |
| 2 | Wave 0A contracts doc + ADR-012/013 amend | planning (owner-reviewed) | blocks 0B |
| 3 | Wave 0B conformance amendments | **AFK parallel** (1 agent/area) | after 0A frozen |
| 3 | Wave 3 research refreshes | **AFK parallel** | independent — runs alongside |
| 4 | Wave 1 design-bug fixes | AFK draft + owner review | after 0A (some bind to D1/D3) |
| 5 | Wave 2 doc-drift | AFK parallel | after ADR amendments land |
| 6 | Wave 4 UPGRADE folding | folded into 0B/1, residue last | opportunistic |

Per the AFK workflow: **owner present = decisions/briefs only** (the Decision Gate + 0A review +
spec-review sign-off). Drafting (0B, Wave 1, Wave 2, Wave 3) runs via pre-authorised background
agents returning bounded findings, synthesised back into specs.

## Decision queue — RESOLVED 2026-06-11 (the 6 out-of-contract design calls)

| # | Decision | Resolution | Applied to |
|---|----------|------------|-----------|
| 1 | M7-a2 cloud detection | **Inject `teacher_origin` at composition; drop the probe call.** `ModelResponse.origin` stays audit-only (D2 unchanged). | M7-a2 |
| 2 | Gmail urgency candidate set | **`{PRIMARY, UPDATES}`** (drop Forums). | M8-b2 + gmail.md §E |
| 3 | Project→GOAL entity | **Eager** — `create_project` creates GOAL `entity_id=goal:{project_id}` (always-linkable). Fills Seam 6. | M8-d-a + contracts Seam 6 |
| 4 | Per-scope storage | **Hybrid** — SQLCipher DBs at `scope_dir`; APFS volume at `scope_dir/vault/` for LanceDB only. No double-encrypt. New contracts Seam 10. | M2-a, M2-b, M3-a, M0-a (paths) + ADR storage note |
| 5 | dev/UAT/PROD slot layout | **Per-slot git worktrees** pinned to refs; promotion = advance worktree to next tag. | M0-a, M0-b/deploy.sh + ADR-002 note |
| 6 | iOS client brain URL | **Captured at pairing**, stored Keychain/UserDefaults, Settings-editable. | CLIENT-c/d (+ pairing payload) |

## Exit criteria — handoff-ready

- [ ] D1–D4 decided; ADR-012/013 amended.
- [ ] `contracts.md` frozen; every BLOCK in every per-area report resolved or consciously deferred.
- [ ] Re-sweep (or targeted re-review) shows zero remaining cross-spec interface fictions.
- [ ] ROADMAP.md reflects true spec count + build order.
- [ ] Quarantine leaks closed; GATE approve executes once and reaches the external API in a test.
- [ ] `status.md` In-Flight `corpus-remediation` row → COMPLETE; SP0 row → handoff-ready.
