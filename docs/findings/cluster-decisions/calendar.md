# Cluster Decision Inventory — Google Calendar

_Decision-resolution pass before build specs. Surfaces ONLY genuinely-open design decisions in the
Calendar area. Sources read: `docs/technical/modules/calendar.md`; `docs/changes/CAL-a/b/c/d`;
`docs/owner-rules/2-scheduling.md` + `1-proactivity.md` + `00-INDEX.md`; `ADR-011`; `docs/status.md`._

**Context note.** CAL-a/b/c/d are all `status: ready` and very detailed — the function surface, the
auto-vs-gated security classifier, the untrusted-text chokepoint, the overlay/projection lifecycle, the
sync engine, and the 7 hooks are all LOCKED. Most "calendar decisions" are already resolved. What
remains open is a small set of **owner-policy values and small spec amendments** (the owner-rules
capture explicitly flags these as "spec gaps" not yet written into the ready specs), plus a few
genuinely-undecided behaviour questions. Ordered by importance.

---

## 1. `working_days` field — weekends-off enforcement

**Context.** Owner confirmed work rhythm = Mon–Fri, weekends off. But `CalPrefs` (CAL-a) has **no
`working_days` field** — `find_time` and the free-gap focus-protect hook key off working *hours* only,
so today they would happily offer Saturday/Sunday slots. Flagged as the #1 spec gap in
`owner-rules/00-INDEX.md` and `2-scheduling.md`.

**Options**
- **A. Add `working_days: tuple[int,...]` to `CalPrefs`** (default Mon–Fri), have `FindTimeEngine` and
  the free-gap hook skip non-working days — clean, one knob, matches owner intent. Small CAL-a amend.
- **B. Leave hours-only, rely on the owner to not book weekends** — zero work, but `find_time` keeps
  suggesting weekend slots → wrong output, owner re-tunes manually forever.
- **C. Hardcode Mon–Fri in the engine** — simplest code, but not owner-tunable (owner may want
  Saturday for personal scheduling later).

**Recommended default: A** — a single `working_days` knob is the minimal correct fix; the owner already
asked for weekends-off and the gap is explicitly logged. Touches `FindTimeEngine.find_slots` + the
free-gap hook day-band loop.

**UI implication: N** (a preferences value; surfaces in a settings panel eventually, not a new screen).

---

## 2. `preferred_focus_window` — morning deep-work bias

**Context.** Owner resolved (2026-06-19): bias focus/deep-work blocks to mornings (~09:00–12:00), fall
back to earliest free slot if no morning slot. `CalPrefs` / `FindTimeEngine` model **no time-of-day
block preference** today (earliest-slot only). Spec gap #8 in the index. Also feeds the free-gap
focus-protect hook ("defend morning gaps first").

**Options**
- **A. Add `preferred_focus_window: tuple[str,str]` to `CalPrefs`** and bias slot ranking: prefer slots
  inside the window for focus/deep-work blocks, fall back to earliest — matches owner intent exactly.
- **B. Bias only the free-gap hook (defend morning gaps), leave `find_time` earliest-first** — smaller,
  but `block_focus_time` / time-block picks would still grab afternoons.
- **C. Make focus-window a per-call arg, not a stored pref** — flexible but the owner has a standing
  preference, so a stored default is simpler and matches the captured rule.

**Recommended default: A** — stored pref + bias both the time-block pick and the free-gap hook; it is
the captured owner rule. Note this is a *ranking* change, not the frozen find_time *algorithm* (the
available-band logic stays frozen per `2-scheduling.md` invariants).

**UI implication: N** (preferences value).

---

## 3. Travel-time / Maps connector — and how leave-buffers behave without it

**Context.** True travel-time + "leave by" alerts are **deferred to a future Maps connector** (Google
Distance Matrix), parked in `status.md` and out of this milestone (calendar.md §Deferred). The
upcoming-reminder hook is "location-aware now; true travel-time deferred." Open question: what does the
owner get *in the meantime*, and is the connector wanted at all soon.

**Options**
- **A. Ship location-only reminders now; defer Maps entirely** (current plan) — the 15-min reminder
  shows the event location string but computes no travel time / leave-by. Zero new work; matches the
  parked decision.
- **B. Add a flat configurable "leave buffer" pref** (e.g. always warn N minutes early for events with
  a location) — cheap approximation, no Maps API, no API key/cost; not real travel time but better than
  nothing for the owner's local context.
- **C. Build the Maps connector now** (Distance Matrix, API key, quota, cost) — accurate leave-by, but
  pulls a deferred milestone forward; adds an external paid dependency + a new connector surface.

**Recommended default: A, with B as a cheap follow-up if the owner wants leave-by before Maps** —
keeps the milestone scope intact; a flat leave-buffer (B) is a small `CalPrefs` knob the owner can opt
into without the Maps build. Confirm: does the owner want *any* leave-by signal pre-Maps, or is
location-string-only acceptable for now?

**UI implication: N** (reminder content + optional pref; no new screen).

---

## 4. Other-people scheduling / negotiation via email (needs Gmail send)

**Context.** An "other-people scheduling assistant" (negotiating meeting times via email) is listed as
**deferred — needs Gmail send** (calendar.md §Deferred; ADR-011 §5 — Gmail sending is deferred in
wave-1). Today the calendar can find mutual free slots (`find_time_with_attendees` via FreeBusy) and
stage an invite for owner approval, but cannot *negotiate by email*.

**Options**
- **A. Keep deferred — calendar finds slots + stages the invite; owner sends/negotiates manually**
  (current posture) — no Gmail-send dependency, no new gated-send surface; owner does the back-and-forth.
- **B. Build a thin "propose times by email" once Gmail-send lands** — Artemis drafts a slot-proposal
  email, gated through Review; still owner-approved per send. Real assistant value, but blocked on the
  deferred Gmail write capability + a negotiation state machine.
- **C. Full autonomous negotiation loop** (parse replies, counter-propose, book) — high value, high
  risk; multi-party state, untrusted inbound parsing, many gated sends. Far out of scope.

**Recommended default: A (confirm defer)** — it depends on Gmail-send which is itself deferred; the
FreeBusy + staged-invite path already covers the 80%. Flag B as the natural unlock once Gmail-send
exists. Decision needed: confirm the owner is happy deferring, or wants B prioritised when send lands.

**UI implication: N now** (would be a Review-screen flow if built — defer to UI/Integration then).

**Cross-spoke note:** the email-described-event → calendar-event seam (an email saying "let's meet
Tuesday 3pm" auto-becoming a staged event) is real but is **cross-spoke wiring → defer to the
Integration agent.** Note only.

---

## 5. Tentative/overlay projection rules — project holds to Google or keep Artemis-only?

**Context.** CAL-c's overlay can optionally project proposals/holds to Google as a *tentative* event
(carrying the `artemis_overlay` private marker). CAL-c currently projects holds **immediately** to
Google (self-only auto write-through) and the free-gap hook emits a hold each day. Open: how aggressive
should auto-projection be, given each projected hold writes a (cleanable) tentative event to the real
calendar.

**Options**
- **A. Project holds to Google immediately** (current CAL-c behaviour) — the owner sees holds in their
  real Google Calendar app (cross-device visibility); cleaned on approve/reject. But Artemis writes
  tentative events the owner didn't explicitly ask for (free-gap hook fires daily).
- **B. Keep proposals Artemis-native only; project to Google only on owner approval** — no unsolicited
  tentative events on Google; but holds are invisible outside the Artemis client until approved.
- **C. Make projection a pref** (`project_holds_to_google: bool`) — owner chooses; small `CalPrefs` knob.

**Recommended default: C, defaulting to A** — keep the current cross-device-visible behaviour as
default but let the owner turn off auto-projection if daily tentative holds feel like clutter. Confirm
the owner is comfortable with the free-gap hook writing a tentative Google event each day.

**UI implication: Y (flag)** — whether holds render in the Artemis client *and/or* Google changes what
the calendar surface shows; the function choice (project-or-not) forces a client display decision.
Flag to the UI agent.

---

## 6. Free-gap focus-protect hook — auto-create vs propose-only, and daily cadence

**Context.** The free-gap hook (CAL-c) finds a free gap ≥30 min in working hours and **auto-emits a
hold proposal** once/day (dedup per day). Owner proactivity posture is "gentle nudges." Open: should
this hook proactively create a focus block at all, and is once/day the right cadence.

**Options**
- **A. Propose-only, once/day** (current) — emits a hold the owner can approve/reject; gentle, dedup'd.
- **B. Auto-block the morning gap** (no approval, self-only is already auto) — more proactive; but the
  owner may not want Artemis silently filling their calendar daily even with self-only blocks.
- **C. Off by default; owner opts in** — most conservative; matches "gentle" but loses the protect-time
  value the owner seemed to want (morning-defense was explicitly requested).

**Recommended default: A** — proposal (not silent auto-block), once/day, biased to the morning window
(ties to decision #2). Matches "gentle nudges" + the owner's morning-defense intent without
auto-filling the calendar. Confirm cadence (once/day vs only-when-no-existing-focus-block).

**UI implication: N** (hook behaviour; surfaces as a Review proposal).

---

## 7. Recurring-event edit-scope default (THIS_EVENT vs series)

**Context.** CAL-b threads Google's three recurrence scopes (`THIS_EVENT`, `THIS_AND_FOLLOWING`,
`ALL_EVENTS`) and **defaults every edit/move/cancel to `THIS_EVENT`**. This is a sensible safe default,
but it is a real behaviour choice the owner hasn't explicitly confirmed (conversational "move my
standup" is ambiguous about scope).

**Options**
- **A. Default `THIS_EVENT`, let the brain ask when ambiguous** (current) — safest (never edits a whole
  series unintentionally); the brain elicits scope for recurring events.
- **B. Default `THIS_AND_FOLLOWING`** — matches the common "from now on" intent for standing meetings;
  riskier (touches future instances).
- **C. Always require the owner to specify scope for recurring edits** — zero surprise, but more
  friction on every recurring-event change.

**Recommended default: A** — `THIS_EVENT` default + brain elicits scope when the target is recurring.
Safe and already specced; just confirm the brain-side elicitation is the intended UX.

**UI implication: N** (brain elicitation, not a screen).

---

## 8. Multi-timezone / DST handling depth

**Context.** Timezone is RESOLVED to `Asia/Singapore` (SGT, UTC+8) and standardized across specs.
Singapore has **no DST**, so day-to-day this is simple. Open only at the edges: events created by
others in other timezones, and the owner travelling. `CalPrefs` has a single `timezone` field; §E
mentions "timezone(s)" plural but the model is single-tz.

**Options**
- **A. Single owner timezone (SGT), render everything in it** (current) — simplest; correct for a
  SG-resident owner who rarely travels; external events' own tz is normalized to SGT for display.
- **B. Add a travel/secondary-timezone mode** (`CalPrefs.timezone` becomes overridable per session) —
  handles the owner travelling; more code, find_time band math must follow the active tz.
- **C. Full multi-tz find_time** (schedule across attendee timezones) — FreeBusy already returns
  absolute instants so cross-tz mutual-free works; the only gap is *display* + working-hours band in
  the owner's current tz.

**Recommended default: A** — single SGT, no DST, normalize external events for display. Defer travel-tz
(B) until the owner actually needs it (no current requirement). Confirm: does the owner travel enough to
want a quick "I'm in tz X this week" override? If not, A is done.

**UI implication: N** (display formatting; a travel-tz toggle would be a small UI control if B is ever built).

---

## 9. `calendar.readonly` scope sufficiency for FreeBusy (hardware-gated verify, not a design fork)

**Context.** CAL-a registers only `calendar.readonly` and *assumes* it covers the FreeBusy API; the
spec flags `calendar.freebusy` as a narrower alternative and says "expand if on-hardware testing shows
readonly is insufficient." This is a **verify-on-Mini** item, not really an open design decision —
listing it so it isn't mistaken for one.

**Recommended default:** keep `calendar.readonly`; verify FreeBusy works against it in CAL-a Task 8
(on-hardware). No owner decision required.

**UI implication: N.**

---

# Appendix — Already resolved / locked (excluded from the open list)

- **Source-of-truth posture** — mirror + write-through + Artemis-native overlay. LOCKED (ADR-011).
- **Autonomy boundary** — self-only changes autonomous; external-effect (invites/cancels/RSVP/attendee
  changes) gated through Review. LOCKED (ADR-011, calendar.md §B, CAL-b STRICT classifier).
- **Auto-vs-gated classifier rules** — `respond_to_invite` always gated; `block_focus_time` /
  `set_reminders` / `quick_add` always auto; any non-owner attendee → gated; empty-owner failsafe →
  gated. FROZEN security boundary (CAL-b `gating.py`).
- **Untrusted external event text** — single `quarantine_event_text` chokepoint over DR-a; trusted
  passthrough for self-created. LOCKED (CAL-d, ADR-009).
- **`find_time` algorithm** — available band `max(working_start, no_meeting_before) → min(working_end,
  no_meeting_after)`, ≤10 slots earliest-first. FROZEN invariant (`2-scheduling.md`). (Decisions #1/#2
  add day-filtering + ranking *inputs*, not the band logic.)
- **Polling not push** — incremental `syncToken`, Heartbeat-driven; no public webhook. LOCKED
  (calendar.md, ADR-011).
- **Tentative-projection mechanics** — `extendedProperties.private.artemis_overlay` marker, own-projection
  recognition, no double-count in agenda/free_busy. LOCKED (CAL-a/CAL-c). (#5 is only the *aggressiveness*
  of projection, not the mechanism.)
- **The 7 Tier-1 hooks** — daily briefing (wake-triggered, merged into Morning digest), upcoming
  reminder, change detection, conflict alert, free-gap protect, unanswered-invite nudge, prep nudge.
  Set + schedules captured in `1-proactivity.md`. (#6 is the only one with a residual tuning question.)
- **Hook schedules / wake-trigger / Morning-digest merge** — RESOLVED (`1-proactivity.md` §Hook schedule,
  2026-06-19). Wake-trigger + day-gating is a cross-module M6 design gap, not a calendar decision.
- **Timezone value** — `Asia/Singapore`, standardized across specs. RESOLVED (`2-scheduling.md`).
  (#8 is only the multi-tz/travel edge.)
- **Working hours / no-meeting windows / buffer / focus-block duration / reminder lead / sync window** —
  09:00–18:00, 15m buffer, 90m focus, 10m reminder, ±12mo sync. Captured defaults (`2-scheduling.md`).
- **OAuth posture** — published-unverified single-owner; refresh token in owner-private encrypted scope.
  LOCKED (calendar.md, M8-a).
- **Knowledge push boundary** — structured trusted-metadata summary only (no raw external text at rest).
  LOCKED (CAL-d Task 2).
- **Memory extraction (A.U.D.N.)** — recurring/key-contact events only, sanitized extract only, keep-both
  bitemporal. LOCKED (CAL-d + `4-memory.md`).
- **Storage** — read-cache + overlay + preferences + activity log, all SQLCipher under owner-private M2
  wall. LOCKED (calendar.md §Data).
</content>
</invoke>
