# Cluster Spec-Writing Roadmap — Gmail · Calendar · Tasks · Finance · Integration · UI

_Generated 2026-06-23 from `docs/findings/cluster-decisions/DECISIONS-LOG.md` (LOCKED answers) + the six per-area inventories + status.md build state + ADR-021/022/024/028/029 + module designs. This is the **ordered queue of specs to AMEND or WRITE** that implements the locked cluster decisions, in dependency order, dev-box-first._

**How to read:** AMEND = edit an existing `status: ready` spec in `docs/changes/`. NEW = author a new spec. "Dev" = buildable + testable on the 8 GB Windows box now (per the dev-machine-first lens + the Ollama stack `dev-model-stack-ollama.md`). "Mac-gated tail" = a sub-task that needs the Mini (real API keys, SQLCipher keyed round-trip, distilled models, iOS). Decision IDs cite the DECISIONS-LOG / per-area inventories (X#=cross-cutting, G#=Gmail (their "D#"), C#=Calendar, T#=Tasks, F#=Finance "F-D#", I#=Integration "I-#"/inventory D#, U#=UI).

**Deep-prerequisite stance (unchanged from corpus):**
- **M2 security wall** — STUB on dev (`FakeKeyProvider(owner_unlocked=True)` + plain-sqlite fallback behind the `_connect()` seam), per the slice-2a precedent. Real keyed SQLCipher = Mac-gated tail on every owned-store spec.
- **M8-a Google auth** — prereq for any live Gmail/Calendar I/O; the connectors are fake/replay-testable on dev, live OAuth = Mac-gated.
- **DR-a quarantine** — prereq for every untrusted-email→X path (capture, finance extraction, calendar event-from-email).
- **M7 recipe system** (M7-a1/a2/b) — prereq for capture-graduation AND the reaction Tier-B suggest→graduate loop AND per-cluster reaction recipes (recipes = atomic primitives, ADR-024 Refinement).
- **M3/M4** — prereq for the sensitivity producers/carriers and for Finance/reaction memory pushes.
- **M6 heartbeat** — prereq for all hooks; gains a new **wake/intent trigger class** (T1).

---

## Wave map (dependency-ordered)

| Wave | Theme | Specs | Parallelism |
|------|-------|-------|-------------|
| **F0** | Foundation: config layer + M6 wake trigger + Areas-drop/module-split | X3-config, M6-wake, M8-d-a (AMEND), M8-d-a2-projects (NEW) | F0 internal: M6-wake ∥ X3-config; module-split is serial after both land conceptually but file-independent |
| **F1** | Cluster amendments to frozen Gmail/Calendar/Tasks specs | M8-b2 (AMEND), CalPrefs/CAL-a (AMEND), M8-d-b (AMEND), M8-d-c1 (AMEND) | All 4 ∥ (disjoint files) |
| **P** | Sensitivity gate (ADR-029) — producers → carriers → enforcer | SENS-prod-M3a, SENS-prod-M8b1, SENS-prod-M4b (AMEND ×3) → SENS-carry-M3b, SENS-carry-M4c1 (AMEND ×2) → SENS-enforce-ragcompose (NEW) | producers ∥ (3), carriers ∥ (2), enforcer serial last |
| **S** | Finance spoke (FIN-*) — no prior specs | FIN-a, FIN-b, FIN-c, FIN-d (NEW ×4) | serial a→b→c→d (each builds on prior schema/extraction) |
| **R** | Reaction layer (ADR-021) — infra → capabilities → recipes | RXN-emit, RXN-rulestore, RXN-dispatcher, RXN-reconciler (NEW ×4) → TRIP-entity, MAPS-connector, CAL-create-from-extract (NEW ×3) → RXN-recipes-comms/planning/self (NEW ×3) | infra ∥ (emit+rulestore, then dispatcher+reconciler); capabilities ∥ (3); recipes ∥ (3) |
| **U** | UI Tauri client (ADR-028 carve) — shell → cards → detail views | CLIENT-core, CLIENT-auth, CLIENT-world, CLIENT-card, CLIENT-ask, CLIENT-screens, CLIENT-theme (NEW ×7, rewrite) | core+auth first; world+theme ∥; card+ask+screens ∥ after world |

**Parallel-wave note:** **P (sensitivity)**, **S (Finance)** and **R-infra** can run **concurrently** once F0/F1 land — they touch disjoint files and have no ordering dependency between them (P amends M3/M4/M8-b1; S creates `modules/finance/`; R-infra creates the reaction package). **U** can begin its shell specs (core/auth/world/theme) in parallel with P/S/R since the client binds to *contracts*, not implementations; the **detail-view** screens (card/screens) should follow their domain's data spec (Finance detail ← FIN-a/c; reaction surfaces ← R-infra). The hard serialization is only *within* each wave.

---

## Wave F0 — Foundation (config + wake trigger + structural re-architecture)

| Spec | A/N | Implements | Prereqs | Dev/Mac | One-line scope |
|------|-----|-----------|---------|---------|----------------|
| **X3-runtime-config** | NEW | X3, I-9, F-D6/D8/D9, G-D2/D3/D6, U (settings) | M0-a | **Dev** | Thin owner-editable config layer (`policy.json`-style load+validate) for all tunable values — VIP list, keyword sets, sender excludes, schedules, thresholds (S$500/±7d, recurrence cadence, focus window, hook cadences). Structural constants stay in code; client settings UI reads/writes it later (deferred). The forcing-function home the deferred OQ was waiting for. |
| **M6-wake-trigger** | AMEND (M6-a) | T1, C (hook schedules) | M6-a | **Dev** | Add a wake/intent trigger class to the M6 scheduler: event=wake (`"good morning"` / first-interaction detection) + per-day-of-week gating (Sat-wake) + fixed-time fallback. Reused by Tasks digest + Calendar daily briefing + Weekend review. |
| **M8-d-a** | AMEND | T8, structural (Areas DROPPED) | — (frozen spec) | **Dev** | **Remove `areas` table + `area_id` FK** from schema/repository/tools. Two levels only: Projects→Tasks; standalone tasks float. T8 archived-area decision now moot. Re-scope the 30 auto-tools: drop area CRUD. |
| **M8-d-a2-projects** | NEW (split from M8-d-a) | Structural (spoke split: Tasks + Projects = separate modules/cards) | M8-d-a (amended) | **Dev** | Split Projects into its own module surface (separate Planning-cluster card per UI lock): project CRUD + GOAL-entity eager-create (Decision D3) + project↔task linkage. Tasks module keeps task/subtask/recurrence/suggestions. The 30 tools split across two modules. |

**Notes.** X3 is genuinely foundational — every downstream tunable (reactions, finance thresholds, calendar prefs, gmail keywords) reads it, so building it first avoids transcribing dozens of constants then re-externalizing. M6-wake unblocks **both** the Tasks digest re-spec (F1) and the Calendar daily-briefing hook. The module split is the single biggest *structural* ripple from this pass — see Risk R1.

---

## Wave F1 — Cluster amendments to frozen Gmail/Calendar/Tasks specs

| Spec | A/N | Implements | Prereqs | Dev/Mac | One-line scope |
|------|-----|-----------|---------|---------|----------------|
| **M8-b2** (Gmail urgency) | AMEND | G-D1, G-D2, G-D3 (Gmail D1/D2/D3) | M8-b1, M6-c, X3-config | **Dev** (live scan Mac-gated) | Widen Stage-1 admit: OR-in topic/keyword (legal·fraud·payment-warning) **+** VIP-sender admit (not just boost) on top of Gmail-IMPORTANT (D1=A). Add `URGENCY_SENDER_EXCLUDE` bank-sender set so UOB/SCB/DBS never become urgency candidates (D2=A). Hybrid VIP = static `VIP_SENDERS` (Ashley/Debby) ∪ memory-derived, force-admit (D3=A). Keyword/VIP/exclude lists read from X3. `check_ref` stays LLM-free (deterministic keyword pass). |
| **CalPrefs / CAL-a** | AMEND | X1, X2, T3, T4, C1, C2 | CAL-a (frozen) | **Dev** | Add `working_days: tuple[int,...]` (default Mon–Fri; `find_time` + free-gap hook skip non-working days) per X1. Add `preferred_focus_window: tuple[str,str]` (morning bias ~09:00–12:00, earliest fallback) per X2 — biases slot *ranking* (not the frozen find_time band algorithm). |
| **M8-d-b** (time-blocking) | AMEND | X2, T3 | M8-d-a (amended), CAL-a (amended) | **Dev** | `schedule_task` slot-pick biases to `preferred_focus_window` (prefer earliest slot *within* window, else earliest overall) instead of bare `slots[0]`. Drop any `area_id` references (Areas dropped). |
| **M8-d-c1** (hooks) | AMEND | T1, T2, C (briefing merge) | M6-wake, M8-d-a (amended) | **Dev** | Re-spec the three hooks to the **wake-triggered rhythm** (T1): Morning digest on wake (fixed-time fallback) with overdue **folded in** (~1–2/day, gentle — T2, drop hourly interval); **Weekend review** on Sat-wake (day-gated); **Week-ahead** Sun ~19:00 clock. Calendar daily-briefing merges into the Morning digest. Payload stays counts+IDs only. |

**Notes.** Gmail **D4 (send)** and **D5 (mailbox writes)** are LOCKED *deferred* — no spec, recorded as a decided no (post-CLIENT if ever). G-D6 (backfill/cap defaults) and G-D7 (no Gmail-side needs_review floor) = accept-defaults, no spec. Calendar C3 (Maps) → handled in Wave R (de-park). C4/C5 nuances: C5 (hold-tentative-until-approved) is a CAL-c overlay tweak folded into the reaction wave's `calendar.create_from_extract` posture; C4 (other-people scheduling) stays deferred (needs Gmail send). All F1 specs are pure amendments to disjoint files → fully parallel.

---

## Wave P — Sensitivity gate (ADR-029): tag-at-ingestion → carry → enforce-at-RAG-compose

_ADR-029 supplies its own integral build wave; reproduced here as spec entries. All dev-box-buildable + end-to-end testable against real Ollama models; the only Mac tail is the distilled `sensitive_reasoner` quality upgrade (a separate ADR-022 phase, NOT part of this gate's logic)._

| Spec | A/N | Implements | Prereqs | Dev/Mac | One-line scope |
|------|-----|-----------|---------|---------|----------------|
| **SENS-prod-M3a** | AMEND (M3-a) | ADR-029 §1 (U10) | M3-a, brain-sensitivity-routing (builds `SensitivityClassifier`) | **Dev** | Classify each ingested doc on-box (per-source, NOT per-chunk) → stamp `sensitivity: Literal["general","sensitive"]` + reserved nullable `category` on Document/chunk/LanceDB row; tag propagates to all chunks. Reuses the exact classifier/role/taxonomy; fail-closed. |
| **SENS-prod-M8b1** | AMEND (M8-b1) | ADR-029 §1 | M8-b1, brain-sensitivity-routing | **Dev** | Tag each signal email + its extracted memory fact at ingestion. |
| **SENS-prod-M4b** | AMEND (M4-b) | ADR-029 §1 | M4-b, brain-sensitivity-routing | **Dev** | Facts inherit source-derived sensitivity (residual sensitive memory = journal/credentials/identity, since owner-rules already exclude finance/health from memory). |
| **SENS-carry-M3b** | AMEND (M3-b) | ADR-029 §2 | SENS-prod-M3a | **Dev** | Surface the `sensitivity` tag on `RetrievedChunk` (materialize the LanceDB column — ~one line; M3-b's existing FLAG already reserved this). |
| **SENS-carry-M4c1** | AMEND (M4-c-1) | ADR-029 §2 | SENS-prod-M4b | **Dev** | Surface the tag on the recalled fact shape. |
| **SENS-enforce-ragcompose** | NEW | ADR-029 §3, U10 | carriers + brain-sensitivity-routing | **Dev** | The missing call-site: RAG-compose-with-gate — retrieve+recall → assemble → **enforcer** (filter sensitive items out of cloud prompt; if request itself sensitive, whole turn local) → responder/responder_cloud. Surface held-back items per-item + inline one-time release (NOT GATE staging) + audit-log every release. Enforcer extends `sensitivity.py` (one home for classifier+router+enforcer). |

**Notes.** 6 specs total (3 producer amendments + 2 carrier amendments + 1 enforcer/seam NEW), matching the DECISIONS-LOG "~6". Wave-0 foundation (`brain-sensitivity-routing`) is **already in flight** (the In-Flight Codex batch — next to build) and proceeds as-is. Producers ∥, carriers ∥ (each gated on its producer), enforcer serial last. The RAG-compose seam is genuinely new corpus surface (nothing wires retrieval→responder prompt yet) — see Risk R2.

---

## Wave S — Finance spoke (FIN-*) — no prior build specs

_Least-specced spoke: a design doc (`modules/finance.md`), zero FIN-* specs. Build phasing LOCKED: FIN-a (ledger core + manual/CSV) → FIN-b (email extraction) → FIN-c (recurring + hooks) → FIN-d (knowledge/memory push). Serial. All owner-private SQLCipher (M2-stub on dev); **always-local reasoning** (ADR-022/F-D13 — no Codex/cloud may touch ledger data); awareness-first, design-for-end-state schema (F-D1=B)._

| Spec | A/N | Implements | Prereqs | Dev/Mac | One-line scope |
|------|-----|-----------|---------|---------|----------------|
| **FIN-a** (ledger core) | NEW | F-D1, F-D2, F-D3, F-D5, F-D11, F-b | M0-a, M2-b/c (stub), M4-d-1 (entity backbone), X3-config | **Dev** (keyed SQLCipher Mac-gated) | Freeze the 4-table schema (`account`/`transaction`/`subscription`/`bill`) designed for end-state, awareness fields used in v1 (one schema, no migration — F-D1=B). `instrument` = FK to `account` (F-D11=A; 5 SG channels seeded). Fixed SG seed categories + owner add/rename, flat (F-D3=C). Manual single-entry + generic column-mapped CSV importer with saved profiles (F-D5=C). No bank link, ever (F-b=A). SGD default + multi-currency fields. |
| **FIN-b** (email extraction) | NEW | F-D4, F-D7 | FIN-a, M8-b1, DR-a (quarantine), local model | **Dev** | Bank sender-allowlist (UOB/SCB/DBS) + receipt classifier fallback (F-D4=C), quarantine-first via QuarantinedReader. `TransactionExtract` schema (date/amount/currency/merchant/instrument/type-hint/confidence/raw_ref). Type inference = model-first classify + deterministic bank-phrase post-rules; ambiguous (incl. PayNow) → L3 owner-review (F-D7=C). |
| **FIN-c** (recurring + hooks + reconciliation) | NEW | F-D6, F-D8, F-D9, F-a (awareness) | FIN-b, M6-a | **Dev** | Recurring detection (subscription/bill) at **2-occurrence suggestion** hardening on confirm/3rd-hit (F-D8=C). Reconciliation ladder L0–L4 with tight tunable defaults (date ±1d, exact amount, fuzzy merchant; below auto-merge bar → inert "possible duplicate?" suggestion — F-D6=C). 4 hooks (renewal+price-increase · new-recurring · bill-due · spending-summary+unusual-spend). Unusual-spend = statistical outlier vs merchant/category history (F-D9=C); **no budget envelopes** (locked out). Thresholds read from X3. |
| **FIN-d** (knowledge/memory push) | NEW | F-a, ADR-029 (sensitivity) | FIN-c, M4-b, M3-a | **Dev** | Durable non-record facts ("owner pays ~$X/mo for Y", recurring merchants, patterns) → M4/M3; raw financial records do NOT (memory excludes financial). Sensitivity tag rides the push (inherits ADR-029). |

**Notes.** Finance's "handling" verb (bill→task + payment→mark-paid lifecycle, F-a) is a **reaction** — its emit points (`txn-recorded`/`bill-recorded`/`subscription-detected`) and the A6 bill→task Tier-A built-in live in Wave R, not here (F-D12 defers all reaction detail to Integration). Net-worth view DEFERRED (F-a). Finance has **no GATE** — all writes are internal local-ledger edits (F-D13). The S$500 figure is the **fraud-alert** threshold (a reaction notification), not a finance UI gate.

---

## Wave R — Reaction layer (ADR-021): infra → capabilities → per-cluster recipes

_Full reaction layer per ADR-021 (hybrid learned-first). Decision I-4/5 = **ALL reactions** (full A–E surviving set) + **de-park Trip entity + Maps connector** — the fullest scope (owner prefers end-state). Pulls in the 5-capability dependency set. 3 infra pieces + reconciler + the 2 de-parked capabilities + the email→event seam + per-cluster recipes._

| Spec | A/N | Implements | Prereqs | Dev/Mac | One-line scope |
|------|-----|-----------|---------|---------|----------------|
| **RXN-emit** | NEW | I-1, ADR-021 (emit piece) | M1-a (tool registry), spokes emitting | **Dev** | The emit seam: spokes publish domain events (`email-ingested`, `txn-recorded`, `bill-recorded`, `subscription-detected`, `task-done`, …). Thin, uniform, observable. |
| **RXN-rulestore** | NEW | I-6, ADR-021 (rule store) | M7-a1 (RecipeStore), X3 | **Dev** | Rule store reusing M7 `RecipeStore` for rule *definitions*; Tier-A built-in set + the **ratified extended Tier-A list** (A1, A9-link, C2, E2, E3 — all gate-passing: universal∧internal∧reversible∧zero-judgment per I-6=B). Everything else Tier-B suggest→graduate. |
| **RXN-dispatcher** | NEW | I-1, I-8, I-10, ADR-021 (dispatcher) | RXN-emit, RXN-rulestore, GATE-a | **Dev** | Matches emitted events to rules → fires reactions. **Thin idempotency/last-fire ledger** (I-8=C: spoke owns domain state, dispatcher keeps only dedup ledger keyed by stable key). GATE posture (I-10): internal/reversible → auto + passive undoable notice; external-effect → ActionStagingService (GATE). A4 (email→task suggestion) = first dispatcher consumer (proof reaction). |
| **RXN-reconciler** | NEW | I-7, F-D6 (shared primitive) | RXN-dispatcher | **Dev** | The shared fuzzy-match reconciler (one primitive for A9/B4c/B5/B6/dedup/link-integrity). Link-integrity sweep (I-7=A): auto-repair deterministic half-links, flag fuzzy → needs-review lane; **nightly** cadence + on-demand from hub view. |
| **TRIP-entity** | NEW | I-4/5 (de-park Trip), D5 | M4-d-1 (entity backbone) | **Dev** | TripIt-style Trip aggregation entity (M4-homed beside Place) — correlates multi-email itineraries; stateful/windowed assembly (the A5 flight-playbook proof case). Co-travel detection. |
| **MAPS-connector** | NEW | I-4/5 (de-park Maps), C3, I-3 | (external API) | **Dev (faked) / Mac (real key)** | Maps/travel-time connector (Distance Matrix) for airport-timing blocks; degrades to fixed-buffer (intl-3h/domestic-1.5h) without it. **Real API key owner-present on Mac, faked on dev** — see Risk R3. |
| **CAL-create-from-extract** | NEW | I-2, C5 | CAL-b, DR-a | **Dev** | New `calendar.create_from_extract(Extract)` seam (I-2=B): one Calendar entry point taking a quarantined extract + event-type tag → builds a **held tentative event** (C5=B: NOT written to Google until approved). Home for all email→event reactions (A5/A7 playbooks). |
| **RXN-recipes-comms** | NEW | I-4/5 (Comms reactions), I-11, I-12 | dispatcher + capabilities | **Dev** | Per-cluster reaction recipes for Comms/email reactions: A4 (commitment→task suggestion), A5/A7 (email→event via create-from-extract), gift-signal memory category + email-to-self clip channel (I-11=B; iOS Share Extension deferred). Migrate legacy pushes only where observability/links add value (I-12=C). |
| **RXN-recipes-planning** | NEW | I-4/5 (Planning reactions) | dispatcher + capabilities | **Dev** | Per-cluster reaction recipes for Planning: Task↔Calendar link reactions (C1/C4), task-done→mark-paid (C2), Trip-assembly blocks, focus-block reactions. |
| **RXN-recipes-self** | NEW | I-4/5 (Self/Finance reactions), I-3 | dispatcher + capabilities, FIN-c | **Dev** | Per-cluster reaction recipes for Self/Finance: A1 (CC-bill→settlement), A6 (bill→task Tier-A), A9 (payment→mark-paid+complete), B4c (~S$500 fraud-confirm, ±7d window — thresholds from X3, re-tune on Mac per I-3), B-cluster bill lifecycle. |

**Notes.** This is the **largest wave** (10 specs). De-parking Trip+Maps was an explicit owner choice for fullest scope — Trip is the load-bearing stateful-reaction proof; Maps degrades gracefully. Gift-signal ships now (memory category + email fallback); iOS Share Extension is **Mac/hardware-gated** and deferred (I-11=B). E8 (hub view) and D3-dropped were reclassified out of reactions (never were). Per-cluster recipe specs are ∥ once infra+capabilities land.

---

## Wave U — UI Tauri client (ADR-028 carve) — 7-spec rewrite

_The CLIENT-a..f Swift specs are **stale on 3 axes** (Swift→Tauri ADR-023 · auth→P-256/TPM/SE ADR-025 · tabs→map ADR-028) = a rewrite; only contracts carry over. CLIENT-f retires to a build target. 7 new Tauri specs per the ADR-028 carve. Plus the per-domain detail views from the UI lock._

| Spec | A/N | Implements | Prereqs | Dev/Mac | One-line scope |
|------|-----|-----------|---------|---------|----------------|
| **CLIENT-core** | NEW (rewrite) | U14 (lock-state), ADR-023/028 | CLIENT contracts | **Dev (WebKit-safe watch)** | Tauri shell + connection/lock state machine; glance counts **mask while Vault-locked**, map shape stays visible (U14). WebKit-safe build discipline (webview differs Win/Mac). |
| **CLIENT-auth** | NEW (rewrite) | ADR-025 | CLIENT-core | **Dev (TPM/SE Mac-gated)** | P-256/TPM/Windows-Hello/SE auth + pairing + recovery-passphrase; unlock flow. Hardware-key path Mac-gated. |
| **CLIENT-world** | NEW (rewrite) | U1, U9, U12, ADR-028 | CLIENT-core | **Dev** | The pannable functional-cluster map (Comms/Planning/Knowledge/Self poles) — these four domains on inner ring (U1=A+C); user-arrangeable + persisted layout. Global top-bar pending indicator + minimap (U9=A+C). ntfy = remote echo, tap→Home (U12=C+A; deep-link deferred). |
| **CLIENT-card** | NEW (rewrite) | U2, U3, U4, U5, U6, U7, U8, U11 | CLIENT-world, domain data specs | **Dev** | Glance cards (one-number+label+accent-badge rule): Gmail="N need you" (U5=B), Calendar="N events today"+RSVP/conflict accent (U2), Tasks="N due today"+overdue accent (U3), Finance="S$X this month"+bill-due badge (U4=C, excl. transfers). **Detail overlays:** Gmail triage (needs-you list + browsable signal mail + reader + accept-suggestion/approve-held), Calendar (Month/Week toggle + selected-day panel showing events AND tasks-due; held-tentatives distinct; self-edit inline, invites→Review — U6=B), Tasks (Due/Overdue/Upcoming + capture inbox + check/reschedule/time-block/accept — U7=B), Finance (daily-spend bar + category pie, week/month toggle; transactions+Bills+unusual-spend+dup-merge; recategorize/mark-paid; instant local edits, inline confirm only on dup-merge — U8=B/B2). Capture/suggestion inboxes on originating card + glance badge (U11=C). |
| **CLIENT-ask** | NEW (rewrite) | U10, U13 | CLIENT-world | **Dev** | Ask-Artemis pop-up: answers + acts (inline auto-writes; gated→Review — same server gate, U13=B+C); spans all four domains. **Sensitivity held-back chip row** under the answer with one-tap "include & redo", accent colour, audited (U10=A, ADR-029). Deep-link chips for full views. |
| **CLIENT-screens** | NEW (rewrite) | U9 (Review), U6/U8 (gated surfacing) | CLIENT-world | **Dev** | Review screen = authoritative pending-action count + recipe approvals (the one approval surface; no ntfy-button actions). Needs-review "broken link" lane (I-7). Per-domain detail screens that don't fit the card overlay (full Calendar month grid, full Finance dashboard, **Projects** detail). |
| **CLIENT-theme** | NEW (rewrite) | U15, design-brief | CLIENT-core | **Dev** | Holo Tactical theme + 16-cell ambient theming tokens (4 seasons × 4 time-states); Space Grotesk + Inter as named (fonts pass DEFERRED — U15=A). |

**Notes.** Projects gets its own card (new Planning-cluster surface, detail designed in its own pass — covered in CLIENT-screens). The "~S$500 confirm gate" the brief flagged is **NOT built in v1** (no external finance action; reserved for end-state — U8 confirms the brief/scope mismatch). All four domain glance cards mask while locked (U14, privacy-required near-lock). CLIENT shell specs (core/auth/world/theme) can start parallel to P/S/R; detail views (card/screens) follow their domain data specs.

---

## Biggest / riskiest items

**R1 — Productivity spoke split (Tasks + Projects + Areas-drop).** The single biggest *structural* ripple. M8-d-a is a frozen, heavily-amended spec (async cascade, contracts Seams 3/5/6, eager-GOAL); removing `areas`/`area_id` and splitting Projects into its own module touches the schema, repository, all 30 tools, the manifest, M8-d-b (time-blocking refs), M8-d-c2 (capture refs `project_id`/`area_id`), and the UI (new Projects card). Risk: stale `area_id` citations across the corpus. **Mitigation:** grep-sweep all `area`/`area_id`/`areas` references before freezing the amendment; treat as an amendment *wave* (like the ADR-015/016 cascades), not a single edit.

**R2 — The RAG-compose enforcer seam (SENS-enforce-ragcompose) is genuinely new corpus surface.** ADR-029's own finding: nothing currently wires retrieval (M3-b) + recall (M4-c) into the responder prompt — the "RAG-compose" step is unspecced. This is not just a sensitivity gate; it's the first spec that *assembles the full cloud-bound prompt*. It's load-bearing for the whole hybrid privacy wall (covers all 3 prompt terms) and for correct cloud/local routing. **Mitigation:** spec it as its own seam with explicit assemble→enforce→route stages; build integrally with the gate so the wall is never retrofitted onto a live retrieval path.

**R3 — Reaction layer breadth (Wave R = 10 specs, fullest scope).** Owner chose ALL reactions + de-park Trip + Maps — the largest new surface in the cluster. Trip is a new stateful M4 entity; Maps is an external connector with a **dev/Mac key split** (faked on dev, real on Mac — a Mac-gated tail that must not block dev build/test); the dispatcher+reconciler are new always-on infra with idempotency correctness requirements (the agent-loop-reliability guardrails apply: idempotent · bounded · clean-state · externally-verified). **Mitigation:** build A4 (email→task suggestion, inert) as the first dispatcher consumer to validate emit→rule→dispatch on a zero-risk reaction before wiring external-effect reactions.

**R4 — Finance spoke from zero (Wave S = 4 specs, no prior specs, always-local invariant).** FIN-* is the least-specced spoke and carries a hard invariant: **no Codex/cloud path may ever touch ledger data** (ADR-022/F-D13). Every code path (extraction, categorization, reconciliation, hooks) must run on the local sensitive-reasoner. The schema freeze (FIN-a, design-for-end-state) is gating and irreversible-ish (SQLCipher migration on owner-private data is costly). **Mitigation:** freeze the full 4-table end-state schema once (F-D1=B); pin the `instrument`→`account` FK and multi-currency fields up front; verify the local-only routing in the spec's acceptance criteria.

**R5 — UI is a 7-spec rewrite, not an amendment.** The CLIENT layer is stale on 3 axes; only contracts carry over. The new detail views (Gmail triage, Calendar month/week + tasks-due link, Finance bar+pie dashboard, Projects) are substantial new surface, and the detail specs depend on their domain data specs landing first. **Mitigation:** start the shell specs (core/auth/world/theme) in parallel early (they bind to contracts); sequence card/screens after the matching domain data spec.

---

_This roadmap is the input to spec-writing. Build dev-box-first; Mac-gated tails (live OAuth, keyed SQLCipher, real Maps key, distilled sensitive_reasoner, iOS Share Extension) are flagged per-spec and must not block dev build/test._
