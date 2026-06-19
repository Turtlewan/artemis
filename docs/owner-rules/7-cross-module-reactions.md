# Owner Rules — 7. Cross-Module Reactions ("when X → then Y")

_The connective tissue: one module reacting to another. CANDIDATES below are seeded from
`docs/findings/cross-module-io-map.md` for owner triage — keep / drop / add. Legend:
**✅** already in specs · **◑** partially in specs · **🆕** new (needs the reaction layer)._

Status: 🟡 triage in progress — **Cluster A (email) DONE** 2026-06-19; clusters B–E pending.

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

## B. Triggered by FINANCE
| # | When (X) | Then (Y) | In specs? | Keep? |
|---|----------|----------|-----------|-------|
| B1 | **bill due** | Tasks: create "pay X" task | ✅ | |
| B2 | **subscription renewal** soon | Calendar marker / notify | ✅ | |
| B3 | **new recurring charge** detected | Memory: "owner subscribes to X" | ✅ | |
| B4 | **unusual spend** flagged | notify owner | ✅ | |

## C. Triggered by TASKS / PRODUCTIVITY
| # | When (X) | Then (Y) | In specs? | Keep? |
|---|----------|----------|-----------|-------|
| C1 | task **scheduled** | Calendar: focus block | ✅ | |
| C2 | "**pay bill**" task **completed** | Finance: mark the bill paid | 🆕 | |
| C3 | **project completed** | Knowledge summary + Memory fact | ✅ | |

## D. Triggered by CALENDAR
| # | When (X) | Then (Y) | In specs? | Keep? |
|---|----------|----------|-----------|-------|
| D1 | meeting created w/ **external attendee** | Tasks: prep task | 🆕 | |
| D2 | meeting **cancelled** | cancel linked focus block / re-plan tasks | ◑ | |
| D3 | **free gap** found | schedule a pending task into it | ◑ | |
| D4 | meeting **with a person** | surface Memory facts (person briefing) | 🆕 | |

## E. Cross-cutting (entity / enrichment)
| # | When (X) | Then (Y) | In specs? | Keep? |
|---|----------|----------|-----------|-------|
| E1 | email/event mentions a **known person** | link to that person's entity (auto-tag) | 🆕 | |
| E2 | booking / receipt email | add to Knowledge corpus | ✅ | |

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
