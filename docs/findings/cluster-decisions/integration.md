# Open Design Decisions — Cross-Spoke Integration / Reactions layer

_Decision-resolution pass before writing the reaction build specs. Generated for the
CROSS-SPOKE INTEGRATION / REACTIONS cluster — the connective tissue routing a Gmail email
into Calendar, Tasks, and Finance (and the other "when X → then Y" reactions among spokes)._

**Scope guard.** This inventory lists only GENUINELY-OPEN build decisions. The following are
LOCKED and NOT re-litigated: the overall approach (ADR-021 hybrid learned-first; 3 pieces =
emit · rule store · dispatcher; shared reconciler; link-integrity contract; stateful-first-class;
hub-view carve-out; Tier-A built-in set), and the cross-module link backbone (ADR-013:
`person_fact_key`, logical `EntityRef`, ToolRegistry-mediated resolution, lifecycle-sync). The
surface-7 triage (WHICH reactions are wanted) is settled. What remains open is concrete
**wiring · thresholds · sequencing · UX surfacing** the owner must decide before per-reaction
specs can be authored.

Sources: ADR-021, ADR-013, `docs/owner-rules/7-cross-module-reactions.md`,
`docs/findings/2026-06-20-reaction-wiring-audit.md`, `docs/changes/M8-d-c2-capture-integration.md`,
`docs/status.md` In-Flight + Open-Questions.

Decisions ordered by importance — the email→spoke routing wiring first (it's what the owner asked for).

---

## D1 — Email→Task trigger wiring: who calls `CaptureService` on an ingested email?

**Context.** The task-capture engine exists (M8-d-c2 `CaptureService.suggest_from_text` already
accepts `source: Literal["chat","email","calendar"]` with an `untrusted=True` quarantine path),
but **nothing calls it on an email**. M8-d-c2 explicitly states "no proactive capture hook is in
scope — capture is reactive only," and Gmail's ingest (M8-b1) has no hook into Productivity. So
the A4 commitment→suggestion reaction, and every other email→task reaction, has a built engine
with no trigger. This is the single highest-priority gap: it is the literal "route a Gmail email
into Tasks" path.

**Options**
- **A. Dispatcher-mediated (ADR-021 native).** Gmail emits `email-ingested`; the reaction
  dispatcher matches an A4 rule and calls `CaptureService.suggest_from_text(source="email",
  untrusted=True)`. — Trade-off: correct end-state, uniform/observable/learnable, but requires the
  emit+dispatcher pieces built first (gates A4 behind infra).
- **B. Direct Gmail→Productivity hook (point-to-point).** Add a capture call-site in the Gmail
  ingest path now, bypassing the dispatcher. — Trade-off: ships A4 sooner without the layer, but is
  exactly the ad-hoc push ADR-021 exists to replace; would need migrating onto the layer later.
- **C. Heartbeat-polled capture sweep.** A Productivity hook polls recent ingested emails and runs
  capture. — Trade-off: reuses the existing polled-hook pattern, but is the legacy non-subscribed
  model ADR-021 deprecates; latency = tick interval.

**Recommended default: A.** It is the ADR-021-native path; building A4's trigger as the *first*
dispatcher consumer validates the emit→rule→dispatch plumbing on a low-risk internal reaction
(suggestion is inert until accepted). Sequence: emit point + dispatcher land in the first infra
wave; A4 is the proof reaction.

**UI implication: Y** — accepted suggestions surface in the suggestion-inbox / Review screen
(already exists); flag to UI agent that the email→task path's *first touch* is an inert suggestion,
not a created task.

---

## D2 — Email→Calendar event path: there is no email→event trigger at all

**Context.** Calendar (CAL-a..d) has read/find_time/write/hooks but **no email→event ingestion
path**. The A5 (flight), A7 (interview), and D1-adjacent flows all need "email arrives → create a
calendar event/block." Unlike Tasks (which at least has the capture engine), Calendar has no
equivalent service that takes extracted email content and produces an event. The owner specifically
wants email→{calendar} routing, so this path must be designed, not just triggered.

**Options**
- **A. Reuse `calendar.schedule_task` / write tools via dispatcher.** The dispatcher, on
  `email-ingested`, runs a playbook that extracts event fields (quarantined) and calls the existing
  Calendar write tool (self-only events, no attendee gate). — Trade-off: reuses CAL-b write seam, no
  new Calendar service; needs a new extraction→event-fields mapper per reaction (flight vs interview).
- **B. New shared `calendar.create_from_extract(Extract)` seam.** One Calendar entry point that takes
  a quarantined extract + an event-type tag and builds the event. — Trade-off: cleaner single seam all
  email→event reactions bind to; small new Calendar surface to spec.
- **C. Route through Tasks first (task→focus-block), never a bare event.** Every email→calendar item
  becomes a dated task whose Task→Calendar link (C1) creates the block. — Trade-off: maximally reuses
  existing wiring + satisfies "task⇄Calendar always linked" (Decision 8), but mis-models true events
  (a flight departure is an event, not a task focus-block).

**Recommended default: B.** A single `calendar.create_from_extract` seam is the clean home for all
email→event reactions (A5/A7 playbooks plus future ones), keeps the extraction→event mapping in one
place, and routes self-only events (no GATE — no external attendees). Reserve C for the cases that
are genuinely deadlines (packing task) rather than events.

**UI implication: Y** — auto-created calendar events/blocks need a visible "created by Artemis +
source email" provenance affordance and an undo. Flag to UI agent.

---

## D3 — Confirm the B4c fraud confirmation threshold (~S$500) and the ±7d match window

**Context.** The B4c deep-dive set an **amount-gated** fraud-confirm rule: charge **< ~S$500** with
no matching receipt → silent link only, never ping; charge **≥ ~S$500** with no match → ping owner
to confirm ("Did you make this S$X at Y?"). Match window = amount + fuzzy merchant token + date
**±7d**. ADR-021 records these as tunable. Before the B4c spec, the owner should confirm the actual
numbers (or accept the placeholders as defaults).

**Options**
- **A. Confirm S$500 / ±7d as shipped defaults.** — Trade-off: zero further elicitation; numbers are
  reasonable for SG retail but unverified against owner's real spend distribution.
- **B. Owner sets explicit values now** (e.g. S$300 or S$1000; ±3d or ±14d). — Trade-off: tuned to
  owner, but premature precision before live data exists.
- **C. Make threshold a runtime knob, ship S$500, re-tune on Mini with real charges.** — Trade-off:
  best precision long-term; depends on D9 (config-layer decision) for owner-editability.

**Recommended default: C.** Ship S$500 / ±7d as the constant, but spec the threshold + window as a
named tunable so it re-tunes against real Finance data on the Mini without a code edit (pairs with D9).
Precision-first means a wrong threshold should be cheaply correctable, not recompiled.

**UI implication: Y** (small) — the ≥threshold confirm is a GATE-style prompt ("Did you make this
S$X at Y?"); confirm it surfaces on Review/ntfy, not a blocking modal.

---

## D4 — v1 reaction set: which reactions ship in the first write-enabled wave vs later

**Context.** 46 reactions triaged; the wiring audit found 27 ACCOUNTED · 17 PARTIAL · 2 GAP. The
PARTIALs cluster on 5 missing capabilities (module→Memory push · Trip entity · Maps · gift-signal +
share-channel · transaction.instrument). The owner must decide the **v1 cut line** so the first
reaction specs are scoped, rather than waiting on all 5 amendments.

**Options**
- **A. v1 = all ACCOUNTED reactions only (the 27).** Tier-A built-ins (E1, C1/C4, D2, A6) + the
  ACCOUNTED Finance/Tasks/Calendar loops (A1, A4, A9, B1/B2/B4, B2b/B4b, C2/C3/C5/C5b/C5c, D1, E1/E2/E3/E7).
  — Trade-off: shippable with only the 3 infra pieces + reconciler, no capability amendments; defers
  every email→travel and gift flow.
- **B. v1 = ACCOUNTED + the cheap amendments** (add `transaction.instrument` and module→Memory push,
  unlocking A3a/A3b + B3/B8/C3/C4b/C6b/E5/E6). — Trade-off: ~2 small amendments buy the Finance
  instrument loop and all "→memory" reactions; still defers Trip/Maps/gift.
- **C. v1 = end-state (all 46), build all 5 capabilities first.** — Trade-off: complete but gates the
  whole layer behind Trip entity + Maps de-park + gift-signal + share-channel CLIENT spec.

**Recommended default: B.** ACCOUNTED + the two cheapest amendments (instrument field, module→Memory
push) is the high-value/low-cost wave: it lights up the full bill-lifecycle + buy-it + memory-enrichment
loops and the Finance instrument tracking, while deferring only the genuinely heavy Trip/Maps/gift
work to a second wave. (Owner-preference note: owner tends to pick fullest scope — if owner elects C,
sequence the 5 capabilities as their own wave 0.)

**UI implication: N** (sequencing only; surfaces inherit existing Review/inbox).

---

## D5 — De-park the Trip entity + Maps connector now, or defer to a second wave?

**Context.** A5 (flight playbook) and B6 (travel-booking purchase) need a TripIt-style **Trip
aggregation entity** (not in the corpus) to correlate multi-email itineraries, plus the **Maps/
travel-time connector** (currently PARKED) for airport-timing blocks (degrades to fixed-buffer guess
without it). ADR-013 already homed a **Place** entity in M4; ADR-021 calls A5 the proof case for
stateful/windowed reactions. The owner flagged "de-park Trip + Maps" as an explicit open thread.

**Options**
- **A. De-park both now; build a small Travel capability + Maps connector before A5.** — Trade-off:
  A5/B6 ship complete (real airport timings, true trip assembly); largest new surface (new entity +
  external connector + travel-time API choice).
- **B. De-park Trip entity only; ship A5 with fixed-buffer airport timing (no Maps).** — Trade-off:
  trip assembly + co-travel detection work; airport blocks use intl-3h / domestic-1.5h fixed buffers
  (already specced as the fallback). Maps de-parks later when a route needs real travel time.
- **C. Defer both; A5/B6 wait for wave 2.** — Trade-off: keeps v1 lean; owner's richest email
  reaction (flight playbook) is absent at launch.

**Recommended default: B.** The Trip entity is the load-bearing piece (it makes stateful trip
assembly possible and is a clean M4-homed entity beside Place); Maps is a refinement that the
fixed-buffer fallback already covers. De-park Trip now, ship A5 with buffer timings, de-park Maps as
a fast-follow. This gets the flagship email→calendar+task playbook live without blocking on an
external connector decision.

**UI implication: Y** — a Trip is a new aggregate surface (one card grouping flights/hotel/blocks
across emails, revisable as pieces arrive). Flag to UI agent: needs a "Trip" view distinct from
single events.

---

## D6 — Per-reaction tiering: confirm the learned-vs-declared (Tier-A/B) assignment for the v1 set

**Context.** ADR-021 Decision 2 fixed the day-one Tier-A built-in set (E1, C1/C4, D2, A6) and made
everything else Tier-B (suggest→confirm→graduate). But each v1 reaction's tier is "a property set at
spec time per the Tier-A gate." A few reactions sit near the gate boundary and need an owner call
before their spec freezes — specifically the internal-reversible ones that are *universally correct*
but were not in the named Tier-A four.

**Options** (per borderline reaction)
- **A. Strict ADR reading: only the named four are Tier-A; everything else graduates.** e.g. A1
  (CC-bill→settlement), A9 (payment→mark-paid+complete), C2 (task-done→mark-paid), E3 (entity-change
  propagate) all start as Tier-B suggestions. — Trade-off: maximally cautious; but taxes zero-judgment
  reactions (A1/C2/E3 cannot really be wrong) with a suggestion phase that buys no safety — the exact
  thing ADR-021 rejected "pure-learned" for.
- **B. Extend Tier-A to all reactions that pass the four-part gate** (universal ∧ internal ∧ reversible
  ∧ zero-judgment), pulling A1, A9, C2, E2, E3 into built-ins. — Trade-off: consistent with the gate's
  *intent*; needs owner to ratify each addition so the day-one auto set is explicit.
- **C. Owner reviews a candidate Tier-A list per reaction at spec time.** — Trade-off: most accurate,
  but adds a per-reaction decision gate to each spec.

**Recommended default: B.** Apply the four-part gate honestly: any v1 reaction that is universal +
internal + reversible + zero-judgment is Tier-A, not just the originally-named four. Produce the
explicit extended Tier-A list (candidates: A1, A9-as-the-reconciler-link, C2, E2, E3) for one-shot
owner ratification, so the day-one auto set is decided once rather than per spec.

**UI implication: N** (governance/tiering; Tier-B graduation already uses the existing Review surface).

---

## D7 — Link-integrity reconciler: repair-silently vs flag-for-review, and sweep cadence

**Context.** ADR-021 Decision 6 mandates a periodic link-integrity reconciler (an instance of the
shared fuzzy-match primitive) that sweeps for half-wired links (task with no calendar block, charge
with no receipt, bill paid but task still open) and "repairs or flags them." Open: **when does it
auto-repair vs surface to the owner**, and **how often does it run**.

**Options (repair posture)**
- **A. Auto-repair deterministic half-links; flag only ambiguous ones.** A task missing its block where
  the link field is intact → recreate block silently; a charge with no receipt where match is
  uncertain → flag. — Trade-off: matches precision-first (certain→act, uncertain→ask); needs a clear
  "deterministic vs ambiguous" rule per link type.
- **B. Flag everything for owner confirmation (never auto-repair).** — Trade-off: maximally safe but
  noisy; defeats the point of a reconciler for the trivially-correct repairs.
- **C. Auto-repair everything the reconciler is confident about, including fuzzy matches above
  threshold.** — Trade-off: lowest friction; risks a silent wrong link (the precision-first failure
  mode the whole layer guards against).

**Options (cadence):** nightly sweep · per-heartbeat-tick · on-demand from the "what's due" hub view.

**Recommended default: A + nightly sweep.** Auto-repair only structurally-determined half-links
(reverse-link present, no fuzzy judgment); route every fuzzy/uncertain case to needs-review. Run
nightly (low cost, off the interactive path); the hub view (E8) can trigger an on-demand sweep when
opened. This is the Decision-4 reconciler's precision-first posture applied to integrity.

**UI implication: Y** (small) — flagged half-links need a "needs review: broken link" lane on the
Review screen, distinct from new-reaction suggestions and GATE pending-actions. Flag to UI agent.

---

## D8 — Stateful reaction state: where does accumulate-over-window state live?

**Context.** ADR-021 Decision 5 makes stateful/windowed reactions first-class (trip assembly across
emails, bill reconciliation open→paid, charge↔receipt lag, overdue-count escalation), idempotent on
a stable key. Open: **where the accumulating state is stored.** The rule store reuses M7's
`RecipeStore` for *rule definitions*, but per-instance *evidence state* (the partial Trip, the open
bill awaiting payment, the overdue counter) is a different shape.

**Options**
- **A. State lives in the owning spoke's store, keyed by the idempotency key.** Trip state in the
  Travel/M4 entity; bill open→paid state in Finance; overdue-count in Tasks. — Trade-off: keeps state
  with its source-of-truth (ADR-011), no new store; the dispatcher is stateless and re-derives on each
  emit.
- **B. A new reaction-instance state table in the rule store.** One generic "reaction run state" table
  the dispatcher owns. — Trade-off: uniform handling of all windowed reactions, but creates a parallel
  state store crossing spoke scopes (privacy-wall friction) and duplicates what spokes already track.
- **C. Hybrid: spoke owns domain state; dispatcher keeps only a thin "last-fired/idempotency" ledger.**
  — Trade-off: dispatcher gets the dedup/idempotency guarantee centrally while domain state stays in
  the spoke; small dispatcher-side table, no cross-scope domain data.

**Recommended default: C.** Domain accumulation (the partial Trip, the open bill) lives in the owning
spoke per ADR-011; the dispatcher keeps a minimal idempotency/last-fire ledger keyed by the stable key
so re-fires update rather than duplicate (the Decision-5 invariant) without holding cross-scope data.
This respects the M2 crypto wall and the source-of-truth rule.

**UI implication: N** (internal mechanics; the assembled Trip surfaces per D5).

---

## D9 — Reaction thresholds/offsets: runtime config layer vs code constants

**Context.** Reactions carry many tunables: B4c threshold (S$500) + window (±7d); A5 offsets (packing
T-2d, check-in T-48h, airport buffer intl-3h/domestic-1.5h, pickup 45m); gift-nudge lead (~1 month);
overdue-count escalation. status.md carries a standing open question (also in owner-rules INDEX
§"Deferred architecture question") on whether owner values become a real **externalized runtime-config
layer** (owner-editable, no code edit) or stay **code constants the coder transcribes**. The reaction
layer is the densest consumer of tunables, so this decision now has a forcing function.

**Options**
- **A. Code constants the coder transcribes (status quo).** — Trade-off: simplest to build; every
  re-tune is a code edit + redeploy — heavy for the Mini's many reaction knobs.
- **B. A small reaction-config layer (owner-editable values, defaults baked, override file/store).**
  — Trade-off: one config surface for all reaction tunables; matches "unpack and go" on the Mini and
  lets B4c/A5/gift offsets re-tune against live data; modest new mechanism.
- **C. Per-reaction config on the rule store row** (each Tier-B recipe carries its own params). —
  Trade-off: tunables travel with the rule; but Tier-A built-ins + shared-reconciler thresholds aren't
  recipe-rows, so it doesn't cover everything.

**Recommended default: B.** A thin reaction-config layer (named defaults + owner override) is the
right home for the cross-cutting tunables (B4c threshold, A5 offsets, gift lead, reconciler window).
It's the forcing function the deferred architecture question was waiting for; the reaction layer's
tunable density justifies it now rather than transcribing dozens of constants.

**UI implication: Y** (later) — owner-editable reaction settings imply a settings surface. Flag to UI
agent as a future need, not v1-blocking.

---

## D10 — GATE posture for auto-created items: do internal auto-creations get an undo/notice?

**Context.** ADR-021 records that the dispatcher routes external-effect reactions through
`ActionStagingService` (GATE), but the current accepted set is "almost entirely internal/reversible"
— so GATE is wired but rarely hit. The open question is the **posture for the internal auto-creations
that DON'T hit GATE**: an auto-created focus block, an auto-recorded settlement, an auto-marked-paid
bill. They're internal/reversible by the autonomy boundary, but the owner may still want a lightweight
notice + undo rather than silent action.

**Options**
- **A. Silent for internal/reversible (autonomy boundary as written); only external-effect → GATE.**
  — Trade-off: cleanest, matches the locked internal-reversible boundary; but a silently-created block
  or silently-marked-paid bill can surprise.
- **B. Silent action + passive notice (appears in Review/digest log, undoable), GATE only for
  external.** — Trade-off: keeps internal actions automatic (no approval friction) but observable +
  reversible; small addition to the activity log already planned.
- **C. First-N occurrences of each new auto-reaction prompt, then go silent** (trust-building ramp). —
  Trade-off: gentle onboarding per reaction; but overlaps the Tier-B suggest→graduate ramp that already
  does exactly this for judgment reactions.

**Recommended default: B.** Internal/reversible reactions act automatically (per the locked boundary)
but every auto-creation lands a passive, undoable entry in the activity/Review log — observability
without approval friction. GATE stays reserved for genuine external effects. (Tier-B's graduation ramp
already covers the "earn trust before auto" need for judgment reactions, so C is redundant.)

**UI implication: Y** — an "Artemis did this (undo)" activity lane covering auto-created internal items,
separate from GATE pending-actions and from new-reaction suggestions. Flag to UI agent — this is a
distinct third surface alongside Review-suggestions and GATE-pending.

---

## D11 — De-park / sequence the gift-signal capture + share-clip channel (A8/E4/E6b)

**Context.** The A8 Ashley playbook's gift-suggestion feature needs (1) a **gift-signal memory
category** (extends M4 extraction with a "gift signal" flag, accumulating a per-person wishlist) and
(2) a universal **"share/clip to Artemis" inbound channel** — cleanest as an iOS Share Extension on
the CLIENT, with an email-to-self fallback that already works via the M8-b Gmail mirror. This is an
explicit open thread; it gates A8, E4 (key-date nudge), and E6b (gift-signal→wishlist).

**Options**
- **A. Ship both now (M4 extraction amendment + CLIENT Share Extension spec).** — Trade-off: full A8
  partner-CRM experience at launch; adds an M4 amendment + a new CLIENT (iOS) surface — and iOS is
  Mac-Mini/hardware-gated.
- **B. Ship gift-signal memory category now; use the email-to-self fallback for clipping; defer the
  Share Extension.** — Trade-off: wishlist accumulation + date-approach nudge work via the
  zero-new-code Gmail fallback; the polished iOS clip path lands when the client is built.
- **C. Defer all of A8-gift to a later wave.** — Trade-off: leanest v1; the owner's most personal
  feature (gift nudges for Ashley) is absent.

**Recommended default: B.** The gift-signal memory category is a small M4-extraction amendment that
unblocks the wishlist + the ~1-month date-approach nudge (E4); the email-to-self fallback covers
clipping with zero new code, so the iOS Share Extension can follow when the CLIENT/iOS surface is
built (it's hardware-gated anyway). This delivers the owner-valued nudge early without blocking on iOS.

**UI implication: Y** (later) — a per-person wishlist view + the gift/dinner nudge surfacing; iOS
Share Extension is a CLIENT-side surface. Flag to UI agent as client-gated.

---

## D12 — Migrate the legacy polled ✅ pushes onto the layer now, or leave them?

**Context.** ADR-021 notes the existing ✅ reactions (B1 bill→task, B2 renewal→marker, B4
unusual-spend→notify, C-side Task↔Calendar) are **time-polled heartbeat pushes** today — they poll,
they don't subscribe, and aren't observable/learnable on the new layer. The ADR says they "should
migrate onto this layer for uniformity," but doesn't sequence it. Open: migrate as part of building
the layer, or leave them as legacy and only build new reactions on the layer.

**Options**
- **A. Migrate all legacy polled pushes onto emit→dispatch as part of the layer build.** — Trade-off:
  one uniform, observable model; touches working code (re-wiring B1/B2/B4 + Task↔Calendar) for no new
  user-facing feature.
- **B. Leave legacy pushes as-is; build only new reactions on the layer; migrate opportunistically.**
  — Trade-off: less churn, faster to new value; two coexisting models (polled + dispatched) until
  migrated — the non-uniformity the layer was meant to remove.
- **C. Migrate only the reactions that need to become learnable/observable; leave pure-notify polls.**
  — Trade-off: migrates where the layer adds value (links, graduation), leaves dumb notifiers alone;
  needs a per-reaction call.

**Recommended default: C.** Migrate the reactions that gain from observability/graduation/link-integrity
(B1's task link, Task↔Calendar, anything feeding the reconciler) onto the layer; leave pure
fire-and-forget notifiers (B4 unusual-spend notify) on their existing polled hook until there's a
reason to move them. Avoids churning working code that gains nothing from the layer.

**UI implication: N** (internal uniformity; surfaces unchanged).

---

## Summary table

| # | Decision | Recommended default | UI? |
|---|----------|---------------------|-----|
| D1 | Email→Task trigger wiring | Dispatcher-mediated; A4 = first dispatcher consumer | Y |
| D2 | Email→Calendar event path | New `calendar.create_from_extract` seam | Y |
| D3 | B4c fraud threshold/window | Ship S$500/±7d as a runtime knob, re-tune on Mini | Y |
| D4 | v1 reaction cut line | ACCOUNTED + instrument + module→Memory push | N |
| D5 | De-park Trip + Maps | Trip now (buffer timings); Maps fast-follow | Y |
| D6 | Per-reaction tiering | Extend Tier-A to all gate-passing reactions; ratify list | N |
| D7 | Link-integrity reconciler posture | Auto-repair deterministic, flag fuzzy; nightly | Y |
| D8 | Stateful reaction state home | Spoke owns domain state; dispatcher keeps idempotency ledger | N |
| D9 | Tunables: config layer vs constants | Thin reaction-config layer (forces the deferred OQ) | Y |
| D10 | GATE posture for auto-creations | Auto + passive undoable notice; GATE for external only | Y |
| D11 | Gift-signal + share-clip channel | Memory category now + email fallback; defer iOS extension | Y |
| D12 | Migrate legacy polled pushes | Migrate where observability/links add value only | N |
