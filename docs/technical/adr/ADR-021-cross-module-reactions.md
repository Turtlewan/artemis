# ADR-021 — Cross-module reactions: the "when X → then Y" layer (hybrid learned-first)

- **Status:** Accepted
- **Date:** 2026-06-21
- **Deciders:** owner + planning
- **Relates:** ADR-013 (cross-module links — this ADR is the *active* sibling of that *structural* one: ADR-013 says how modules **reference** each other, ADR-021 says how one module **reacts** to another) · ADR-012 (gated-action staging — every external-effect reaction routes through `ActionStagingService`) · ADR-011 (spoke source-of-truth — reactions never write another spoke's owned records; they call its tools) · ADR-006 (two-tier proactivity — reactions run in the heartbeat/Brain, surfaced via ntfy/Review, not as module side-channels) · ADR-009 (`artemis.untrusted` — email/doc-triggered reactions read through the quarantine chokepoint) · M7 (recipe loop — the suggestion→confirm→graduate machinery this ADR reuses; precedent: M8-d-c2 capture-recipe graduation). Source workbook: `docs/owner-rules/7-cross-module-reactions.md`. Wiring audit: `docs/findings/2026-06-20-reaction-wiring-audit.md`. I/O map: `docs/findings/cross-module-io-map.md`.

## Context

Artemis's value is not in any single spoke but in the **connective tissue between them**: a flight email becomes a calendar event + a packing task + an airport-leave block; a payment notification marks a bill paid and completes its task; a charge with no matching receipt becomes a fraud signal. The owner-rules elicitation (surface 7) triaged **46 such reactions** across five clusters (A email · B finance · C tasks · D calendar · E cross-cutting), settling **which** reactions are wanted.

What the triage did **not** settle — and what blocked moving to specs — is the **runtime model**: *how a reaction comes to exist and become active.* And the wiring audit surfaced a hard premise: **there is no reaction infrastructure today.** The ✅ "already in specs" rows are **time-polled heartbeat pushes** (they poll, they don't subscribe); they are not a uniform, observable, learnable layer. Every 🆕 reaction is only "accounted for" *given new infrastructure is built.*

This ADR locks (a) the runtime model, (b) the infrastructure shape, and (c) the dependency list that gates when each reaction can be specced. It must be locked **before the write-enabled spokes (Finance, the A5/A8 playbooks, the reaction-bearing M8 hooks) are specced**, because they all bind to this layer.

The runtime-model choice was made against the owner's already-locked posture: **precision-first** (uncertain → ask, never silently act), **gentle-nudge** (no acting unbidden), and the **internal-reversible autonomy boundary** (internal/reversible effects may be automatic; external-effect actions gate). Four models were weighed — built-in-first, owner-declared-first, pure-learned-first, and hybrid-learned-first. Built-in-first violates gentle-nudge (judgment reactions fire unbidden); declared-first is high-friction and slow; pure-learned taxes even zero-judgment reactions for no safety gain. **Owner chose hybrid learned-first** (2026-06-21).

## Decision

Eight decisions, locked together.

| # | Decision | Statement |
|---|----------|-----------|
| **1** | **Runtime model = hybrid, learned-first** | A reaction becomes active through one of **three tiers**: **(A) safe built-ins** — auto-enabled from day one; **(B) judgment reactions** — `suggest → owner-confirm → graduate to auto` via the M7 recipe loop; **(C) owner-declare** — manual force-enable/disable/hand-write, always available on top of A and B. This is the project-wide default for *every* reaction; a reaction's tier is a property of the reaction, set at spec time per Decision 2's gate. |
| **2** | **Tier-A gate (what may be a built-in)** | A reaction is Tier-A **only if it is universally correct AND internal AND reversible AND zero-judgment.** The day-one built-in set is exactly: **E1** (entity resolve+link), **C1/C4** (task↔focus-block create/clear), **D2** (lifecycle-sync — cancel meeting → cancel block), **A6** (bill email → pay-bill task). Everything else is Tier-B by default. Any reaction with an external effect, a judgment call, or a precision risk is **forbidden** from Tier-A and must graduate through B. |
| **3** | **Three infrastructure pieces** | The layer is built from exactly three new pieces, none of which exist today: **(i) emit events** — modules publish domain events at write points (`email-ingested`, `txn-recorded`, `task-completed`, `fact-added`, …); **(ii) a rule store** — persisted reaction definitions with their tier + state (suggested / confirmed-N / enabled / disabled), reusing the M7 `RecipeStore` for Tier-B graduation rather than a parallel store; **(iii) a reaction dispatcher** — subscribes to emitted events, matches rules, and dispatches reaction callables (async per ADR-016), routing any external-effect reaction through GATE. |
| **4** | **One shared fuzzy-match reconciler** | A9 (payment↔bill), B4c (charge↔receipt), B5/B6 (purchase↔intent-task), Finance dedup (L1), and the link-integrity reconciler (Decision 6) are **the same primitive**: `stable-key + amount/date-window + precision-first → owner-review on uncertainty`. Build it **once** as a shared reconciler service; every loop binds to it. No per-loop matcher. |
| **5** | **Stateful / windowed reactions are first-class** | The rule store + dispatcher MUST support reactions that **accumulate evidence over a window and revise** (idempotent on a stable key — re-fire updates, never duplicates), not only fire-once-per-event. Proof cases: A5 trip-assembly (itinerary pieces arrive across multiple emails/formats → one revisable Trip), A9 bill reconciliation (open→paid across a window), B4c (receipt lags/precedes charge), C5c (overdue-count escalation). |
| **6** | **Link-integrity = declared contract + reconciler** | Each reaction **declares its wiring**: *emit event · entity/link join · reverse link · GATE? · idempotency key.* A periodic **link-integrity reconciler** (an instance of the Decision-4 primitive) sweeps for half-wired links — a task with no calendar block, a charge with no receipt, a bill marked paid with its task still open — and repairs or flags them. "Properly wired" is a **verifier + contract**, not trust. Builds on ADR-013's already-locked guarantees (one join/no copies; bidirectional + lifecycle-sync; idempotent reconciliation; precision-first linking). |
| **7** | **Hub views are carved out — they are NOT reactions** | "What's due this week" (E8) and on-demand person briefing (E7/D4) are **query-time Brain synthesis** (ADR-013 Decision 4): *pulled*, not event-triggered. They need **none** of the three pieces (no emit, no rule, no dispatcher) and live in the **brain/hub spec**, not the rule store. They are the *read* side of the same links reactions *write*. |
| **8** | **Task ⇄ Calendar always linked (cross-cutting)** | Any reaction that creates or links to a dated/deadlined task MUST also wire it into Calendar (due-date marker and/or focus block) via the existing Task→Calendar integration, bidirectionally (completing the task clears the block, per C4). Deadline source = the triggering event (renewal date, dispute window, due date). Applies across B2b, B4b, B5/B6, the A5/A7 playbook tasks, and C/E reactions. |

### GATE posture (consequence of Decisions 1–3, recorded for builders)

The dispatcher MUST route every external-effect reaction through `ActionStagingService` (ADR-012). **But the currently-accepted reaction set is almost entirely internal/reversible** — ledger writes, memory facts, self-only focus blocks, suggestions/nudges. No accepted reaction auto-sends external comms: gift/dinner = *suggestion*, flight check-in = *reminder only* (no stored credentials). So GATE is wired but rarely hit by today's set — which is exactly the internal-reversible boundary working as intended.

## Dependencies — 5 missing capabilities + amendments (gates per-reaction spec timing)

No reaction is structurally impossible, but **17 of 46 are PARTIAL**, clustering on five capabilities that must be built/amended before the reactions that need them can ship:

1. **Module-initiated Memory fact-push** — M4-b's A.U.D.N. write path is currently Brain-turn-driven; a `MemoryStore.add_fact` path callable *by a module* must be specced. Blocks B3, B8, C3, C4b, C6b, E5, A8-memory. → **M4-b amendment.** This amendment also carries the **typed source-reference provenance generalization** (ADR-004 Refinement 2026-06-21): `source_turn_id` → `source_kind ∈ {turn, document, module}` + `source_ref`, so a module-pushed or document-sourced fact records a resolvable origin (cross-store refs resolve tool-mediated per ADR-013 D2). Closes the cross-store-provenance open question (E5).
2. **Memory fact-write emit point** — Memory today emits only `resolve_entity` results; date-facts and gift-signal facts need Memory to emit fact-write events. Blocks E3/E4/E6/E6b. → **M4 emit point** (feeds Decision 3-i).
3. **`transaction.instrument` / `account` field** — finance.md's `transaction` has `type` but no instrument; needed to record *which* card/PayLah!/PayNow and to dedup. Blocks A3a/A3b. → **finance.md amendment** (already noted in workbook §Finance deltas).
4. **Trip aggregation entity + de-park Maps connector** — A5/B6 need a TripIt-style **Trip** entity (not in corpus) to correlate multi-email itineraries, and the **Maps/travel-time connector** (currently PARKED) for airport-timing blocks (degrades to fixed-buffer guess without it). → likely a small **Travel** capability + de-park Maps before A5 ships.
5. **Gift-signal memory category + "share/clip to Artemis" channel** — A8/E4/E6b need a gift-signal flag on M4 extraction and a universal inbound clip channel (iOS Share Extension on CLIENT; email-to-self fallback exists). → **M4 extraction amendment + a CLIENT spec.**

**Also gating (not new capabilities):**
- **Goals sub-domain deferred** — C3c/C7 are correctly Goal-gated; the GOAL *entity* exists eagerly (ADR-013 Decision 6) but the progress model is deferred. Build when Goals land.
- **Cross-store provenance (E5)** — ✅ RESOLVED 2026-06-21 (ADR-004 Refinement): typed source reference (`source_kind`/`source_ref`), applied in the dependency-#1 M4-b amendment above.

## Resolved during triage (recorded, no further action)

- **D3 (free gap → propose scheduling a pending task) — DROPPED.** Conflicts with the locked 2026-06-09 Productivity opt-out of the gap-fill hook; free gaps stay focus-protect only. The overdue case is covered by C5b (propose-not-auto).
- **E8 / E7 / D4 — reclassified as hub views** (Decision 7), not reactions.
- **D4 merges into E7** (one calendar-triggered person-briefing).

## Consequences

- **The layer is buildable on top of M7 with no parallel machinery** — Tier-B reuses the recipe suggest→confirm→graduate loop and `RecipeStore`; the only genuinely new code is the emit/dispatcher plumbing (Decision 3-i, 3-iii) and the shared reconciler (Decision 4).
- **The posture is enforced by construction** — Tier-A's four-part gate (Decision 2) means nothing with judgment or external effect can act unbidden; everything else must earn automation through owner confirmations. This *is* gentle-nudge + precision-first + internal-reversible, expressed as a runtime rule rather than per-spec discipline.
- **One reconciler, many loops** — the same fuzzy-match primitive serves reconciliation *and* link-integrity verification, so the "is everything properly wired" guarantee comes free with the matcher every Finance loop already needs.
- **Reactions are observable and learnable** — because they flow through emit→rule→dispatch (not buried module pushes), they can be logged, surfaced on the Review screen, and graduated/demoted. The ✅ legacy polled pushes should migrate onto this layer for uniformity.
- **Spec sequencing is now explicit** — the 5-capability dependency list tells the build which reactions are shippable in the first write-enabled wave and which wait on Trip/Maps, gift-signal, or the Memory push/emit points.
- **This ADR locks the decision; it does not produce build specs.** Concrete specs (the three pieces, the shared reconciler, the per-cluster reaction recipes, and the five amendments) are drafted at Mini-build time against this contract.

## Alternatives considered

- **Built-in-first (all reactions ship enabled as code)** — *rejected*: instant value but rigid, unpersonalized, and acts unbidden; collides head-on with gentle-nudge + precision-first for the judgment-heavy majority. (Its *one* correct use — zero-judgment reactions — is preserved as Tier-A.)
- **Owner-declared-first (nothing fires until switched on)** — *rejected*: full control but high upfront friction and slow value; owner would hand-enable dozens of rules before the system did much, and the suggestion machinery still has to exist anyway.
- **Pure learned-first (no built-ins; everything graduates)** — *rejected*: uniform and maximally cautious, but taxes zero-judgment reactions (entity-link, task↔block, lifecycle-sync) with a suggestion phase that buys no safety — those reactions cannot be wrong. Hybrid keeps the uniformity for everything that *has* a judgment call and exempts only the four that don't.
- **A parallel reaction-rule store separate from M7's RecipeStore** — *rejected*: would duplicate the suggest→confirm→graduate state machine already built and proven (M8-d-c2). Tier-B rules ARE recipes.
- **Per-loop matchers (separate matcher for A9, B4c, B5, dedup, link-integrity)** — *rejected*: five near-identical fuzzy matchers to maintain and keep consistent; Decision 4 builds one.

## Parked (build-phase)

The three infrastructure specs (emit events · rule store/dispatcher · shared reconciler) · the five capability amendments (M4-b module push · M4 fact-write emit · finance.md `instrument` · Trip entity + Maps de-park · gift-signal category + share/clip CLIENT channel) · per-cluster reaction recipe specs · B4c reverse-direction (charge-without-email → fraud) deep-dive · cross-store provenance resolution (E5) · migration of the legacy polled ✅ pushes onto the layer · Goals progress model (C3c/C7, build when Goals land).
