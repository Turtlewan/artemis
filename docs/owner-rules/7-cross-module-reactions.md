# Owner Rules — 7. Cross-Module Reactions ("when X → then Y")

_The connective tissue: one module reacting to another. CANDIDATES below are seeded from
`docs/findings/cross-module-io-map.md` for owner triage — keep / drop / add. Legend:
**✅** already in specs · **◑** partially in specs · **🆕** new (needs the reaction layer)._

Status: 🟡 triage in progress (2026-06-20).
- **Cluster A (email) DONE** — triaged; A5/A7/A8 expanded into playbooks.
- **Clusters B / C / E — DONE (owner-triaged 2026-06-20).** B: B2b/B4b/B4c/B5/B6 keep (B6 extended
  +task-complete), B7 deferred. C: all kept (C3c/C7 Goal-gated, C5b propose-not-auto). E: all kept
  (E7 merges w/ D4, E8 flagged deep-dive). Cross-cutting rules added: **task⇄Calendar always linked**
  + **link-integrity** (declared wiring contract + reconciler).
- **Cluster D (calendar) — DONE (owner-triaged 2026-06-20).** D1/D2/D3 keep (D3 propose-not-auto),
  D4 merged into E7 (person briefing).
- **ALL CLUSTERS TRIAGED (A–E + D).** D3 **dropped** (gap-fill opt-out conflict, owner 2026-06-20).
- **Deep-dives DONE:** B4c (amount-gated confirm @ ~S$500; shared reconciler) · E8 (reclassified = hub view).
- **WIRING AUDIT DONE 2026-06-20** → `docs/findings/2026-06-20-reaction-wiring-audit.md` (46 reactions:
  27 ACCOUNTED · 17 PARTIAL · 2 GAP). PARTIALs cluster on **5 missing capabilities** (module→Memory push ·
  transaction.instrument · Memory emit point · Trip entity + Maps · gift-signal + share-channel) → ADR
  dependency list / amendments. GAPs resolved: D3 dropped · E8 reclassified.
- **Approach** — ✅ **LOCKED 2026-06-21 → ADR-021** (hybrid learned-first).

**✅ SURFACE 7 COMPLETE 2026-06-21.** Approach locked (hybrid learned-first) and the cross-module-reaction
**ADR-021** written (`docs/technical/adr/ADR-021-cross-module-reactions.md`). It specifies: the **3 pieces**
(emit events · rule store · reaction dispatcher), the **shared fuzzy-match reconciler** (audit X-cut #1), the
**link-integrity contract + reconciler**, **stateful/windowed reactions** as first-class, **hub views carved
out** (E8/E7/D4), the **GATE posture**, and the **5-capability dependency list** + amendments (M4-b module
add_fact · M4 emit point · finance.instrument · Trip/Maps · gift-signal/share-channel). **Next:** build specs
(3 infra pieces + reconciler + 5 amendments + per-cluster recipes) at Mini-build time, against ADR-021.

## A. Triggered by EMAIL (Gmail) — the richest source
| # | When (X) | Then (Y) | In specs? | Keep? |
|---|----------|----------|-----------|-------|
| A1 | email = credit-card **bill payment** | Finance: record as **settlement** (not spend) | ✅ | ✅ keep |
| A2 | email = credit-card **bill payment** | Tasks: **complete** the "pay CC bill" task | 🆕 | ↪ **folded into A9** |
| A3a | email = **card payment** notification (UOB / SC / DBS card) | Finance: record transaction — track **which card/account** + dedup vs merchant receipt | ◑ (instrument field 🆕) | ✅ owner |
| A3b | email = **PayLah! / PayNow** (DBS) payment | Finance: record transaction — **classify**: purchase / bill-payment (spend or settlement) vs **P2P transfer (not spend)** | 🆕 | ✅ owner |
| A4 | email contains a **commitment** ("I'll send X Fri") | Tasks: capture a suggestion | ✅ | ✅ keep |
| A5 | email = **flight / travel itinerary** | **branching travel playbook** (whose flight? me / Ashley+co-travel / others) → see **A5 detail** below | 🆕 | ✅ owner (expanded) |
| A6 | email = **bill** (has due date) | Finance: record bill + remind | ✅ | ✅ owner |
| A7 | email = **interview** invite | **interview-prep playbook** → see A7 detail | 🆕 | ✅ owner (expanded) |
| A8 | email from/about **Ashley** | **Ashley playbook** (partner CRM) → see A8 detail | 🆕 | 🟡 diving in |
| **A9** | a **payment** notification (A3) **matches an open bill** (A6) | Finance: **mark bill paid** + complete the linked "pay-bill" task | 🆕 | ✅ owner |

### A5 detail — Flight / travel playbook (branching reaction, owner 2026-06-19)
Trigger: a flight / travel itinerary email — owner's **or anyone who sends theirs**.

**Step 0 — Parse + identify travelers** (quarantined extract): passenger name(s), flight times,
departure/arrival airports, airline, confirmation #. Resolve each traveler via the **entity backbone**
(owner / Ashley / other known person / unknown).

**Step 1 — Co-travel check:** if the **owner appears in the passenger list** (even on someone else's
itinerary, e.g. Ashley's) → owner is travelling → use the **OWNER-TRAVEL plan**, regardless of who sent it.

**Step 1b — ⚠️ TRIP ASSEMBLY (owner refinement 2026-06-19).** Itinerary pieces for one trip often
arrive as **separate emails in different formats** (owner's flight, Ashley's flight, hotel, car —
different airlines/booking systems). A5 **cannot** decide co-travel from a single email. So A5 needs a
**Trip-assembly layer:**
- Extract structured itinerary from each email **regardless of format** (LLM-robust).
- **Correlate** pieces into one **Trip** by overlapping dates + destination + travelers + booking refs.
- **Resolve co-travel across emails:** owner's separate flight on the same route/dates as Ashley →
  travelling together → flip to OWNER-TRAVEL.
- **Stateful + revisable:** accumulate over a window; **re-plan as new pieces arrive** (idempotent —
  update the playbook, don't duplicate it).
- **Precision-first:** unsure whether two itineraries are the same trip / co-travel → **ask**, don't assume.
- **NEW concept — a "Trip" aggregation entity** (TripIt-style) linking flights/hotels/people. Not in
  the corpus today; relates to the parked Maps/Travel area. Likely a small **Travel** capability.
- **⭐ Reaction-layer requirement (extends A5):** reactions can be **stateful, multi-email, revisable** —
  accumulating evidence over a window, not fire-once-per-email.

**OWNER-TRAVEL plan** (my flight, or I'm going too):
- Add flight to Calendar.
- 🧳 **Packing task** — ~T-2 days (tunable).
- ✈️ **Online check-in reminder/task** — when check-in opens (~T-48h) if the airline supports it.
  *(Reminder only — actually checking in is an external action with no stored credentials → never auto.)*
- 🚗 **"Leave for airport" calendar block** — computed: departure − airport buffer (intl ~3h /
  domestic ~1.5h) − travel-time-to-airport.
- ⊕ intl extras: passport/visa check.

**SUPPORT plan** (someone else's flight — Ashley / other — and owner is NOT travelling):
- 🚗 **Drop-off** block — "leave home" = departure − airport buffer − travel time.
- 🚗 **Pick-up** block — "leave to collect" = arrival + deplane/baggage buffer (~45m) − travel time.
- 🧠 **Memory** — note their travel (e.g. "Ashley flies to X on date").

**Applies to:** owner · Ashley · any known person who sends their itinerary.

**Deltas surfaced:**
- ⚠️ **Maps / travel-time connector** (currently **PARKED** in the corpus) is a hard dependency for
  the airport-timing blocks — without it, timings fall back to a fixed buffer guess.
- **Itinerary parsing** = structured extraction (travelers, times, airports, airline) via local model + quarantine.
- **Co-travel detection** = match owner against the passenger list (entity resolution).
- **Online check-in = reminder, NOT auto** (external effect, no credentials).
- **Tunable offsets:** packing T-2d · check-in T-48h · airport buffer intl 3h / domestic 1.5h · pickup baggage 45m.
- **⭐ Reaction-layer requirement:** reactions can be **multi-step PLAYBOOKS** (computed timing +
  conditional branching + entity routing), not just single "X→Y." A5 is the proof case.

### A7 detail — Interview-prep playbook (owner 2026-06-19: "basic interview prep handout")
Trigger: an interview invite email.
**Role: CANDIDATE (confirmed 2026-06-19)** — handout researches the company/role/interviewer.
**CANDIDATE plan (basic):**
0. Extract — company, role, interviewer(s), date/time, location or video link, stage/round.
1. Calendar — add the interview event (+ video link).
2. **Prep handout** (one basic briefing doc → Knowledge): company (what they do + recent news), the
   role, the interviewer(s) if named, likely questions + smart questions to ask back.
3. Prep task — block prep time (day before).
4. Logistics — in-person → travel block (Maps dep, like A5); video → test-link + join reminder.
5. Surface the handout — evening before + morning of.
_"basic" = a lightweight briefing, not exhaustive research._

### A8 detail — Ashley playbook (owner 2026-06-19: "slightly linked to A5, dive in") — 🟡 shaping
Ashley = primary person (partner). Emails **from/about** Ashley get classified + routed. Proposed facets
(owner to shape):
- **Travel / flights** → A5 (support: pickup/dropoff, or co-travel if owner is on the itinerary).
- **⭐ Key dates** (birthday; anniversary = shared) — **~1 month advance** proactive nudge (tunable) to
  **buy a gift / plan an important dinner**, WITH **suggestions sourced from past conversations**
  (owner 2026-06-19). At trigger: surface gift/dinner ideas mined from what Ashley mentioned
  wanting/liking + recent conversation topics + a task to act.
- **Events / plans she shares** → Calendar / shared awareness.
- **Requests** ("can you pick up X?") → Task.
- **Preferences / facts** (gift ideas, likes, plans) → Memory.
This is an instance of the **Person Briefing / personal-CRM** concept (see
`docs/findings/person-briefing-discussion.md`), focused on the most important person.

**Deltas surfaced by the gift-suggestion feature:**
- ⭐ **Gift-signal capture (new memory category):** Memory must continuously capture **gift-relevant
  mentions** about a person from conversations ("Ashley wants X / likes Y / has been eyeing Z") —
  tagged to her entity, accumulating a running **gift-idea list / wishlist**. Extends the M4 extraction
  rule (a "gift signal" flag).
- ⭐ **Shared-reel capture (owner 2026-06-19):** Ashley also sends gift-signal **Instagram reels** via DM.
  **No IG DM API exists** (Meta messaging API = business accounts only; scraping = ToS violation, DECLINED).
  Realistic capture = **owner-mediated share**:
  - **Clean path:** a **"Share to Artemis" iOS Share Extension** on the iPhone CLIENT — a *general*
    clip-capture channel (any reel/link/article/product), owner shares → clippings inbox → wishlist.
  - **Zero-new-code fallback:** copy reel link → email to self / a dedicated label → existing Gmail
    mirror (M8-b) catches it → wishlist.
  - Processing: local model summarizes the reel (caption/link → product/place/experience); tag to
    Ashley's wishlist w/ provenance; **owner confirms "gift idea?"** (precision-first — can't be sure a
    reel is a gift signal vs entertainment).
  - **NEW capability:** a universal **"share/clip to Artemis" inbound channel** beyond email — feeds
    wishlist / Knowledge / Memory. Broadly useful; a CLIENT (iPhone app) addition.
- **Date-approach trigger:** ~1 month before a key date (from Memory/Calendar), fire the nudge +
  synthesize suggestions from the gift-signal list + recent conversation topics.
- **Dinner planning = suggestion + reminder/task, NOT auto-booking** (booking a restaurant is an
  external effect → owner does it, or future GATE-staged).
- **Generalizable** to other key people's dates, but Ashley is the primary case.
- All local (Memory facts + conversations) — never cloud, per the privacy line.

## B. Triggered by FINANCE — all permutations (deep dive 2026-06-19)
_Legend: ✅ already in specs/menu · ⭐ new high-value · ◽ plausible (owner judge) · ⚠️ end-state/careful._
| # | When Finance emits… | Then (reaction) | Class | Keep? |
|---|----|----|----|----|
| B1 | bill due | Tasks: "pay X" task | ✅ | |
| B1b | bill due | Calendar: due-date marker | ◽ | |
| B2 | subscription renewal soon | Calendar marker + notify | ✅ | |
| B2b | renewal / **price increase** | Tasks: "decide keep/cancel before renewal" **+ Calendar** due-date marker / focus block (deadline = renewal date) | ⭐ | ✅ owner (+ calendar) |
| B3 | new recurring charge | Memory: "subscribes to X" + price history | ✅ | |
| B4 | unusual spend | notify | ✅ | |
| B4b | unusual spend | Tasks: "review / dispute this charge?" **+ Calendar** marker (deadline = dispute window) | ⭐ | ✅ owner (+ calendar) |
| B4c | **any charge** | Gmail: find the source receipt email (charge↔email link); **no matching email → higher fraud suspicion** | ⭐ | |
| B5 | **purchase matches a "buy X" task** | Tasks: complete it (**Buy-it loop**) | ⭐ | |
| B6 | **purchase = a travel booking** (flight/hotel paid) | (1) trigger the A5 travel playbook **and** (2) complete any **linked "book the trip / buy flight" task** (Buy-it loop, B5) — both reactions off one purchase | ⭐ | ✅ owner (extended: + task-complete) |
| B7 | category spend over a threshold | budget awareness / notify | ⚠️ end-state (budget envelopes) | |
| B8 | finance facts / patterns | Memory + Knowledge | ✅ | |

### B4c detail — charge↔receipt matcher + fraud signal (owner deep-dive 2026-06-20)
A **stateful, windowed reconciliation** (same shape as A9), not a one-shot — receipt emails lag or
precede the bank charge. Two email types: (a) the bank/card notification that *creates* the txn (A3);
(b) the merchant receipt B4c *links* to it as corroboration.
- **Matcher:** `amount + fuzzy merchant token + date window (±7d, tunable)`. Confident → silent internal
  link; uncertain → needs-review. **Shared reconciler** with A9 + B5/B6 + E5b + dedup (audit X-cut #1 —
  build once).
- **Fraud signal = AMOUNT-GATED confirmation, not an alarm (owner):** everyday/retail spend **below
  ~S$500 → no fraud check** (silent link only, never ping). A charge **≥ ~S$500 with no matching receipt
  → ping owner to CONFIRM** ("Did you make this S$X at Y?"). Precision-first; fits *notify = payment*.
- **Bidirectional:** a receipt arriving also back-fills its charge.
- **New wiring (audit PARTIAL):** the reverse direction (charge w/o email → flag) + Finance→Gmail
  cross-module read are new. Threshold + window tunable.

## C. Triggered by TASKS / PRODUCTIVITY — all permutations (deep dive 2026-06-19)
| # | When Tasks emits… | Then (reaction) | Class | Keep? |
|---|----|----|----|----|
| C1 | task scheduled | Calendar: focus block | ✅ | |
| C2 | "pay bill" task completed | Finance: mark bill paid (**reverse of A9**) | ✅ | |
| C3 | project completed | Knowledge summary + Memory fact | ✅ | |
| C3b | project completed | Tasks: archive child tasks | ◽ | ✅ owner keep |
| C3c | task/project completed **linked to a Goal** | Goal: update progress (**Goal-progress loop**) | ⭐ | ✅ owner keep (Goal-gated) |
| C4 | task completed | Calendar: clear linked focus block | ✅ | |
| C4b | task completed | Memory: note completion / accomplishment pattern | ◽ | ✅ owner keep |
| C5 | task overdue | notify nudge | ✅ | |
| C5b | task overdue | Calendar: auto-find time / **propose** reschedule (suggest, not silent-move) — task⇄calendar linked | ⭐ | ✅ owner keep (propose-not-auto) |
| C5c | task overdue **repeatedly** | escalate priority / flag "stuck" | ◽ | ✅ owner keep |
| C6 | commitment/suggestion captured | Recipe graduation (M7) | ✅ | |
| C6b | commitment captured | Memory: commitment as a fact | ◽ | ✅ owner keep |
| C7 | GOAL entity created | surface in week-ahead review; entity link | ◽ | ✅ owner keep (Goal-gated) |

## D. Triggered by CALENDAR
| # | When (X) | Then (Y) | In specs? | Keep? |
|---|----------|----------|-----------|-------|
| D1 | meeting created w/ **external attendee** | Tasks: prep task (+ Calendar focus block before meeting, per task⇄Calendar rule) | 🆕 | ✅ owner keep |
| D2 | meeting **cancelled** | cancel linked focus block / re-plan tasks (lifecycle-sync) | ◑ | ✅ owner keep |
| D3 | **free gap** found | ~~propose scheduling a pending task~~ | ◑ | ❌ **DROPPED** (owner 2026-06-20) — conflicts w/ the 2026-06-09 gap-fill opt-out; free gaps stay focus-protect only; C5b covers the overdue case |
| D4 | meeting **with a person** | person briefing — surface Memory facts (**merged into E7**) | 🆕 | ✅ owner keep (= E7) |

## E. Cross-cutting (entity / knowledge / enrichment) — all permutations (deep dive 2026-06-19)
| # | When… | Then (reaction) | Class | Keep? |
|---|----|----|----|----|
| E1 | **any** module mentions a known person/place/goal | resolve + link to entity (auto-tag); unsure → ask | ⭐ universal | ✅ owner keep (foundational join) |
| E2 | booking / receipt email | add to Knowledge | ✅ | |
| E3 | entity gains/changes info (new email/phone) | propagate via entity refs (live, no copies); name→email merge = lifecycle-sync | ✅ | |
| E4 | a **key date** learned about a person (birthday) | Calendar + advance gift/plan nudge (A8 pattern) | ⭐ | ✅ owner keep |
| E5 | document ingested (Knowledge) | Memory: extract facts | ⭐ | ✅ owner keep |
| E5b | document = **statement / receipt** (OCR) | Finance: transaction extract | ⭐ | ✅ owner keep (pairs w/ B4c) |
| E5c | document ingested | link to relevant entities (person/project) | ◽ | ✅ owner keep |
| E6 | fact added to Memory that **is a date** | Calendar marker | ⭐ | ✅ owner keep |
| E6b | fact added = **gift-signal** | wishlist (A8) | ✅ | |
| E7 | (hub) **before meeting a person** | person briefing — entity facts + recent interactions (= D4) | ⭐ | ✅ owner keep (merge w/ D4) |
| E8 | (hub) "**what's due this week**" | synthesize Finance bills + Tasks + Calendar | ⭐ | ✅ owner keep — deep-dive |

### E8 detail — "what's due this week" hub (owner deep-dive 2026-06-20)
**Reclassified: a HUB VIEW, not a reaction** (audit GAP #2 + finance.md §Cross-module). It's *pulled*,
not event-triggered → **Brain query-time synthesis** (ADR-013 #4); needs **none** of the 3 reaction-layer
pieces (no emit / rule / dispatcher). Spec it in the brain/hub layer, not the rule store. E7/D4 (person
briefing) are the same kind.
- **Surfacing:** on-demand ("what's due this week?") **+** auto-included in the Sunday-evening week-ahead
  review (optionally the morning digest).
- **Live by construction:** recomputes from current module state on every read → completed/paid items
  drop off automatically, no staleness. Can show **progress** ("4 of 9 done") — pairs with C4b.
- **Aggregates:** Finance (bills due + renewals) · Tasks (due + overdue) · Calendar (events +
  reaction-created markers/blocks). It's the **payoff surface** where the task⇄Calendar + reconciliation
  wiring becomes visible in one place.

## Emergent loops & patterns (across A–E)
1. **Bill lifecycle loop** — A6 (email→bill) → B1 (bill→task) → A9 (payment→mark paid+complete) ↔ C2 (manual task-done→mark paid). ✅
2. **Buy-it loop** — "buy X" task → B5 purchase detected → complete the task. ⭐ Also covers
   **B6** (a travel-booking purchase completes its "book the trip" task) — and B6 shows one event
   **fanning out** to two reactions (A5 playbook + task-complete): fan-out, not chaining, so still one hop each. ⭐
3. **Charge↔receipt linking** — B4c: every charge ties to its source email; a charge with **no** email = fraud signal (feeds the legal/fraud notify rule). ⭐
4. **Goal-progress loop** — C3c: completing tasks/projects advances a linked Goal. ⭐
5. **Entity enrichment → person briefing** — E1/E3/E4 build the person graph; E7/D4 spend it (know who you're meeting). ⭐
6. **Document → facts + ledger** — E5/E5b: ingested docs feed Memory facts and (if statements/receipts) the Finance ledger. ⭐

## Approach decision — ✅ LOCKED 2026-06-21 → ADR-021
How a reaction comes to exist + becomes active. **Triage already settled WHICH reaction types owner
wants; this decides the RUNTIME model** (auto vs suggest-then-graduate vs switch-on).

| Model | How a rule activates | Pros | Cons |
|---|---|---|---|
| Built-in / hardcoded | ships as code, enabled | instant value; predictable | rigid; not personalized; can act unbidden |
| Owner-declared | owner switches each on | full control | high upfront friction; slow value |
| Learned-first (suggest→confirm→graduate) | suggest per pattern → confirm → graduate to auto (M7 recipe loop) | low friction; adapts; builds trust; observable | slower to mature; needs suggestion machinery |

**✅ CHOSEN = Hybrid, learned-first (owner 2026-06-21):** (a) a few **safe built-ins auto from day one** — only
universally-correct, internal/reversible, zero-judgment reactions (E1 entity-link · C1/C4 task↔block ·
D2 lifecycle-sync · A6 bill→task); (b) **everything with judgment → suggest→confirm→graduate** via the
M7 recipe loop (precedent: M8-d-c2 capture-recipe graduation); (c) **owner-declare always available** as
manual force-enable/disable/hand-write. Fits precision-first + gentle-nudge + internal-reversible boundary;
reuses M7 (no new machinery). Rejected built-in-first (acts unbidden), declared-first (high friction),
pure-learned (taxes zero-judgment reactions). **Locked into ADR-021** with the 3 pieces · shared reconciler ·
link-integrity contract · stateful-reactions-first-class · hub-view carve-out · 5-capability dependency list.

## Owner-added reactions
_(to be filled during triage)_

## Finance design deltas surfaced by A3/A6/A9 (→ carry to finance.md)
- **Payment channels (owner, 2026-06-19):** UOB card · Standard Chartered card · DBS card · DBS
  **PayLah!** · **PayNow**. Each notification = a transaction via a known instrument.
- **`transaction` needs an `instrument`/`account` field** (which card / PayLah / PayNow) — beyond the
  `type` field already added. Drives "which account did this come from" + dedup.
- **PayNow is ambiguous** — can be P2P **transfer** (not spend) or a **payment** (spend/settlement);
  must run through the purchase/transfer/settlement classifier (the no-double-count logic).
- **Bill reconciliation (A9) = stateful loop:** bill recorded (open) → later payment notification
  matched (payee + ~amount + due-window) → bill marked **paid** → linked "pay-bill" task auto-completes.
  The bill-side twin of dedup. Needs bill state (open→paid) + a payment↔bill matcher + lifecycle-sync
  to Tasks. Ambiguous match → owner-review (precision-first).

## Cross-cutting rule — task ⇄ Calendar always linked (owner 2026-06-20)
Any reaction that **creates OR links to a task** must also wire that task into the **Calendar** via the
existing Task→Calendar integration — a **due-date marker** and/or a **focus block** — so the task
surfaces in time rather than sitting orphaned in the task list. This is **bidirectional**: a task touched
by a reaction always has its calendar reflection, and completing the task clears the linked block (C4).
Applies wherever a reaction spawns or references a dated/deadlined task: B2b, B4b, B5/B6 (booking task),
the A5/A7 playbook tasks (already do this), and across C (C3c, C5b, C5c) and E. Deadline source = the
triggering event (renewal date, dispute window, due date, etc.).

## Link-integrity — how "properly wired" is guaranteed (owner 2026-06-20)
Concern: half-wired links (task with no calendar block · charge with no receipt · bill paid but task
still open). Five mechanisms — four already exist, one is a new ADR requirement:
1. **One join, no copies (✅ ADR-013)** — links are logical `EntityRef{module,entity_id}` /
   `person_fact_key` resolved live via ToolRegistry; nothing copied → nothing drifts.
2. **Bidirectional + lifecycle-synced (✅ ADR-013 #3)** — both ends store the ref; change/delete one →
   the other updates/clears (generalizes M8-d-b auto-cancel). No orphans.
3. **Idempotent reconciliation (✅ invariant)** — match on stable keys (booking ref · payee+amount+window ·
   task id); re-fire updates the existing link, never duplicates (A9 / A5 trip-assembly pattern).
4. **Precision-first linking (✅ owner rule)** — uncertain match → needs-review, never a silent wrong link.
5. **⚠️ NEW ADR REQUIREMENT — declared wiring contract + link-integrity reconciler.** Each reaction
   declares: *emit event · entity join · reverse link · GATE? · idempotency key*. A periodic **reconciler**
   (generalized A9 matcher) sweeps for half-wired links and repairs or flags them. This is the actual
   guarantee — a verifier + contract, not trust. (Closes the I/O-map gap: "memory facts from other
   modules — structurally possible, not yet wired.")

## Notes
- ✅/◑ items mostly exist as one-directional pushes already; the reaction LAYER makes them uniform,
  observable, and **learnable** (suggest→confirm→graduate).
- Each kept reaction → defines a required **emit event** + the **entity join** + whether it needs the
  **GATE** (external effect) or is internal/auto. That's the ADR requirements list.
