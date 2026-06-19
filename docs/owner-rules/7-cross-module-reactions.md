# Owner Rules — 7. Cross-Module Reactions ("when X → then Y")

_The connective tissue: one module reacting to another. CANDIDATES below are seeded from
`docs/findings/cross-module-io-map.md` for owner triage — keep / drop / add. Legend:
**✅** already in specs · **◑** partially in specs · **🆕** new (needs the reaction layer)._

Status: 🟡 triage in progress (2026-06-19).
- **Cluster A (email) DONE** — triaged; A5/A7/A8 expanded into playbooks.
- **Clusters B / C / E — all permutations enumerated; owner triage of the ⭐ items PENDING.**
- **Cluster D (calendar) — NOT yet triaged** (simple menu only).
- **Approach** (learned-first vs declared vs built-in) — discussed, **not yet locked**.

**▶ RESUME HERE:** (1) owner triages B/C/E ⭐ rows (keep/drop) + flagged deep-dives **B4c** (charge↔receipt
+ fraud signal) and **E8** ("what's due this week" hub view); (2) triage cluster D; (3) lock the reaction
approach → write the cross-module-reaction **ADR** (the 3 missing pieces: emit events · rule store ·
reaction dispatcher — see `docs/findings/cross-module-io-map.md`). Then specs at Mini-build time.

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
| B2b | renewal / **price increase** | Tasks: "decide keep/cancel before renewal" | ⭐ | |
| B3 | new recurring charge | Memory: "subscribes to X" + price history | ✅ | |
| B4 | unusual spend | notify | ✅ | |
| B4b | unusual spend | Tasks: "review / dispute this charge?" | ⭐ | |
| B4c | **any charge** | Gmail: find the source receipt email (charge↔email link); **no matching email → higher fraud suspicion** | ⭐ | |
| B5 | **purchase matches a "buy X" task** | Tasks: complete it (**Buy-it loop**) | ⭐ | |
| B6 | **purchase = a travel booking** (flight/hotel paid) | → trigger the A5 travel playbook | ⭐ | |
| B7 | category spend over a threshold | budget awareness / notify | ⚠️ end-state (budget envelopes) | |
| B8 | finance facts / patterns | Memory + Knowledge | ✅ | |

## C. Triggered by TASKS / PRODUCTIVITY — all permutations (deep dive 2026-06-19)
| # | When Tasks emits… | Then (reaction) | Class | Keep? |
|---|----|----|----|----|
| C1 | task scheduled | Calendar: focus block | ✅ | |
| C2 | "pay bill" task completed | Finance: mark bill paid (**reverse of A9**) | ✅ | |
| C3 | project completed | Knowledge summary + Memory fact | ✅ | |
| C3b | project completed | Tasks: archive child tasks | ◽ | |
| C3c | task/project completed **linked to a Goal** | Goal: update progress (**Goal-progress loop**) | ⭐ | |
| C4 | task completed | Calendar: clear linked focus block | ✅ | |
| C4b | task completed | Memory: note completion / accomplishment pattern | ◽ | |
| C5 | task overdue | notify nudge | ✅ | |
| C5b | task overdue | Calendar: auto-find time / propose reschedule | ⭐ | |
| C5c | task overdue **repeatedly** | escalate priority / flag "stuck" | ◽ | |
| C6 | commitment/suggestion captured | Recipe graduation (M7) | ✅ | |
| C6b | commitment captured | Memory: commitment as a fact | ◽ | |
| C7 | GOAL entity created | surface in week-ahead review; entity link | ◽ | |

## D. Triggered by CALENDAR
| # | When (X) | Then (Y) | In specs? | Keep? |
|---|----------|----------|-----------|-------|
| D1 | meeting created w/ **external attendee** | Tasks: prep task | 🆕 | |
| D2 | meeting **cancelled** | cancel linked focus block / re-plan tasks | ◑ | |
| D3 | **free gap** found | schedule a pending task into it | ◑ | |
| D4 | meeting **with a person** | surface Memory facts (person briefing) | 🆕 | |

## E. Cross-cutting (entity / knowledge / enrichment) — all permutations (deep dive 2026-06-19)
| # | When… | Then (reaction) | Class | Keep? |
|---|----|----|----|----|
| E1 | **any** module mentions a known person/place/goal | resolve + link to entity (auto-tag); unsure → ask | ⭐ universal | |
| E2 | booking / receipt email | add to Knowledge | ✅ | |
| E3 | entity gains/changes info (new email/phone) | propagate via entity refs (live, no copies); name→email merge = lifecycle-sync | ✅ | |
| E4 | a **key date** learned about a person (birthday) | Calendar + advance gift/plan nudge (A8 pattern) | ⭐ | |
| E5 | document ingested (Knowledge) | Memory: extract facts | ⭐ | |
| E5b | document = **statement / receipt** (OCR) | Finance: transaction extract | ⭐ | |
| E5c | document ingested | link to relevant entities (person/project) | ◽ | |
| E6 | fact added to Memory that **is a date** | Calendar marker | ⭐ | |
| E6b | fact added = **gift-signal** | wishlist (A8) | ✅ | |
| E7 | (hub) **before meeting a person** | person briefing — entity facts + recent interactions (= D4) | ⭐ | |
| E8 | (hub) "**what's due this week**" | synthesize Finance bills + Tasks + Calendar | ⭐ | |

## Emergent loops & patterns (across A–E)
1. **Bill lifecycle loop** — A6 (email→bill) → B1 (bill→task) → A9 (payment→mark paid+complete) ↔ C2 (manual task-done→mark paid). ✅
2. **Buy-it loop** — "buy X" task → B5 purchase detected → complete the task. ⭐
3. **Charge↔receipt linking** — B4c: every charge ties to its source email; a charge with **no** email = fraud signal (feeds the legal/fraud notify rule). ⭐
4. **Goal-progress loop** — C3c: completing tasks/projects advances a linked Goal. ⭐
5. **Entity enrichment → person briefing** — E1/E3/E4 build the person graph; E7/D4 spend it (know who you're meeting). ⭐
6. **Document → facts + ledger** — E5/E5b: ingested docs feed Memory facts and (if statements/receipts) the Finance ledger. ⭐

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

## Notes
- ✅/◑ items mostly exist as one-directional pushes already; the reaction LAYER makes them uniform,
  observable, and **learnable** (suggest→confirm→graduate).
- Each kept reaction → defines a required **emit event** + the **entity join** + whether it needs the
  **GATE** (external effect) or is internal/auto. That's the ADR requirements list.
