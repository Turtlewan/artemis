# Open UI/UX decisions — Gmail · Calendar · Tasks · Finance cluster (client map)

_Decision-resolution inventory for the Tauri client. Scope: the genuinely-OPEN per-domain
content/actions + layout choices the owner must settle before the CLIENT-* (Tauri) specs are written.
**Already LOCKED, not re-litigated here:** spatial travel-zoom navigation (ADR-028) · Tauri platform
(ADR-023) · auth/lock model (ADR-025) · Holo Tactical theme + 16-cell ambient theming + tokens
(design-brief) · Ask-Artemis pop-up *shape* (design-brief) · the 7-spec CLIENT carve._

Sources: ADR-028 (+ Refinement), design-brief.md, app-flow.md, overview.md, ADR-012 (gated-action
staging), ADR-029 (sensitivity ingestion gate), modules/{gmail,calendar,productivity,finance}.md, and
the `travel-zoom-workspace.html` reference mockup.

**Key prior locks that bound these decisions:**
- Glance cards: ONE line, number + label, baseline-aligned, **never content-scroll** (hard rule).
  List domains → a count; fixed-metric domains → fixed stat tiles.
- Detail overlays MAY scroll internally (app-flow cross-screen rules).
- The mockup is the **feel** source of truth but its card *contents* are illustrative, not final.
- Finance v1 is **awareness-only, no ActionStagingService/GATE** (finance.md §Permissions) — so "finance
  confirms" in the UI are local-ledger edits, not the gated-external-action path.
- Gmail v1 is **read-only** (no send/modify) — so no gated email actions exist in v1.
- The two gated surfaces that DO exist in v1: Calendar external-effect writes (PendingActions, ADR-012)
  and recipe approvals (M7-b) — both on the **Review** domain, which is a *separate* card from these four.

---

## 1. Where the four domains sit in the functional-cluster map (default seed positions)

**Context.** ADR-028 Refinement locked the four-cluster model (Comms · Planning · Knowledge · Self) as a
*default seed* the user can rearrange + persist. The cluster assignment of these four is implied but the
exact default seed coordinates / adjacency for THIS cluster aren't frozen, and the owner should ratify
the seed because spatial memory anchors off it.

Per the locked clusters: **Email → Comms** · **Calendar(Schedule) + Tasks → Planning** · **Finance →
Self**. So this "cluster" is actually split across three poles — a thing to confirm, not assume.

**Options**
- **(A) Keep the locked seed split** — Email@Comms, Schedule+Tasks@Planning, Finance@Self.
  Trade-off: matches ADR-028 lock + real semantics; but the four "cluster" domains aren't visually
  co-located, so a user thinking "my daily-life ops" pans across three poles.
- **(B) Co-locate the four as a tight "daily ops" neighbourhood** within/between poles.
  Trade-off: faster glance-sweep across the four most-used domains; diverges from the clean four-pole
  semantic grouping and crowds one quadrant.
- **(C) Seed split (A) but ensure the four sit on the inner ring** (closest to brain core).
  Trade-off: high-frequency domains nearest the core = shortest travel; keeps semantic poles intact.

**Recommended default:** **(A)+(C)** — honour the locked four-pole seed, but place these four on the
inner ring (short travel, brain-centred resting view shows them first). Cheapest, lock-consistent, and
the user can still drag to co-locate.

**Affects:** all four (Gmail, Calendar, Tasks, Finance) · CLIENT-world.

---

## 2. Calendar glance card — what the at-a-glance line shows

**Context.** List-type domain. Mockup shows `3 · events today`. But Calendar carries several count-worthy
signals (today's events, conflicts, unanswered invites, next-event countdown). One line only.

**Options**
- **(A) "N events today"** (mockup default). Trade-off: simplest, matches the lock; but hides
  conflicts/invites that may be the actually-urgent signal.
- **(B) Next-event countdown** ("3pm in 25m"). Trade-off: most actionable at a glance; loses the
  day-shape overview; empty/odd when no next event.
- **(C) "N today · M need RSVP"** (count + an accent badge when invites/conflicts pending). Trade-off:
  surfaces the gated/actionable signal; risks breaking the "one number + label" baseline rule if done as
  two numbers — must render the secondary as an accent dot/badge, not a second metric.

**Recommended default:** **(A) "N events today"** as the number+label, **plus an accent dot** when there
are unanswered invites or a conflict (badge, not a second metric — preserves the one-line rule). Lock-safe
and surfaces the one thing that needs the owner.

**Affects:** Calendar · CLIENT-card.

---

## 3. Tasks glance card — count basis (open vs due-today)

**Context.** List-type domain. Mockup shows `5 · open · 2 due today`. The label packs two numbers, which
flirts with the "one number + label" rule. Tasks has open/overdue/due-today/scheduled cuts.

**Options**
- **(A) "N open"** single count. Trade-off: cleanest; "open" can be a large, low-urgency number that
  doesn't tell you what to do today.
- **(B) "N due today"** (overdue rolled in, accent if any overdue). Trade-off: most action-relevant for a
  daily-driver; hides total backlog.
- **(C) "N open" number + "M due today" as label suffix** (mockup style). Trade-off: richest; technically
  a number-in-the-label, borderline against the baseline rule.

**Recommended default:** **(B) "N due today"** as the number+label, rendered **accent when any are
overdue**. The glance should answer "what do I owe today", not "how big is my list". Single number =
clean lock compliance.

**Affects:** Tasks · CLIENT-card.

---

## 4. Finance glance card — list-count vs fixed-metric tile

**Context.** Finance is borderline between the two glance archetypes. Mockup shows `2 · bills due this
week` (accent) — a list count. But Finance also has a natural fixed metric (month-to-date spend) that
behaves like the Diet&Fitness stat-tile pattern.

**Options**
- **(A) "N bills due this week"** (mockup; accent). Trade-off: reminder-forward, matches the awareness-
  first scope; doesn't show the headline "how am I doing this month" number.
- **(B) Fixed-metric tile: "S$X spent this month"**. Trade-off: the single most-asked finance question
  at a glance; not actionable (no due-date urgency); needs a sensible period anchor.
- **(C) "S$X this month" number + accent badge when bills are due**. Trade-off: best of both; the badge
  (not a second number) keeps the one-line rule.

**Recommended default:** **(C)** — month-to-date spend as the headline number, **accent dot when bills
are due this week**. Spend is the recurring question; the badge preserves the bill-reminder signal without
a second metric. (Note: spend total must exclude transfers/settlements per finance.md.)

**Affects:** Finance · CLIENT-card.

---

## 5. Gmail glance card — unread count vs "needs you" signal

**Context.** List-type domain. Mockup shows `4 · unread · 1 needs you`. Gmail's real product value is the
3-stage urgency funnel (gmail.md §E) → "important unread / needs a reply today", NOT raw unread (the
promo firehose is deliberately pointed away). Raw unread count is noisy and arguably the wrong signal.

**Options**
- **(A) "N unread"** raw. Trade-off: trivial; but contradicts the whole signal/awareness split — unread
  is dominated by Updates/Promos the system intentionally de-emphasises.
- **(B) "N need you"** (urgency-funnel output only; accent). Trade-off: matches the module's actual value
  prop; can be 0 most of the day (good — empty state is meaningful), so the card often shows a calm "0".
- **(C) "N unread · M need you"** (mockup). Trade-off: richest; two numbers again brushes the one-line rule.

**Recommended default:** **(B) "N need you"** as the number+label (accent when >0). The whole Gmail design
is "aware of everything, surface only what needs a reply today" — the glance card should reflect that, not
raw unread. Single number, lock-clean.

**Affects:** Gmail · CLIENT-card.

---

## 6. Calendar detail overlay — content + which actions it offers (and where gated invites surface)

**Context.** Calendar is the one domain in this cluster with **gated external actions** in v1 (invites /
RSVP / cancel-with-attendees → PendingAction, ADR-012). Open question: does the Calendar detail overlay
expose write actions inline, or is everything that's gated punted to the Review card? The detail shows an
agenda (mockup). The actions surface is undecided.

**Options**
- **(A) Read-only agenda; ALL actions go to Review.** Trade-off: clean separation (Review = the one
  approval surface, per IG1); but the owner can't even *initiate* a reschedule/RSVP from the calendar they're
  looking at — feels inert.
- **(B) Agenda + inline self-only actions (block focus time, accept-own-edits), gated actions still
  route to Review.** Trade-off: matches ADR-011's auto-vs-gated split exactly — self-only acts inline,
  external-effect stages to Review. Most coherent with the backend gate model.
- **(C) Agenda + full inline action set, with gated ones showing a "needs approval → staged" inline
  confirmation** (PendingAction created from the overlay, then visible on Review). Trade-off: most fluid;
  but duplicates approval affordance across two cards and risks the owner approving in two places.

**Recommended default:** **(B)** — detail overlay renders the agenda + **self-only inline actions**
(focus-block, personal reminder, view event); **any external-effect action stages a PendingAction and
the owner is told "staged for your review →"** with the actual approve/reject living on the **Review
card**. One approval surface (lock-consistent), but initiation is where you're looking.

**Affects:** Calendar · CLIENT-card · CLIENT-screens (Review). Cross-ref decision 9 (gated surfacing).

---

## 7. Tasks detail overlay — content + inline actions (all auto, no gating)

**Context.** Tasks is fully owned/owner-private; every write is auto (no gating). The detail can be a
genuinely interactive list (check off, reschedule, capture-inbox confirm) with no approval friction. Open:
how much editing lives in the overlay vs deferring to the Ask pop-up / a dedicated view.

**Options**
- **(A) Read-only list + check-off only.** Trade-off: minimal build; but wastes the no-gating advantage
  and forces the owner to the Ask pop-up for everything else.
- **(B) Interactive list: check-off, time-block ("schedule this"), confirm capture-suggestions inline.**
  Trade-off: matches the module's flagship (Morning-plan → time-block) and the suggestion-inbox; more
  client build. The suggestion-inbox confirm is a natural inline tray.
- **(C) (B) + create/edit task inline.** Trade-off: fullest; create-task overlaps with the Ask pop-up's
  NL capture ("remind me to…") — possible redundancy.

**Recommended default:** **(B)** — interactive check-off + "schedule into calendar" + the **capture-
suggestion confirm tray** inline (one-tap approve, per productivity.md §G). Defer free-form task *creation*
to the Ask pop-up (NL is the better entry). High value, no gating cost, avoids duplicating capture.

**Affects:** Tasks · CLIENT-card. Cross-ref decision 10 (where the capture/suggestion inbox lives).

---

## 8. Finance detail overlay — content + the "~S$500 confirm" question

**Context.** The brief flags "~S$500 finance confirms" as a gated-action concern — but finance.md v1 is
**awareness-only, explicitly NO ActionStagingService** (Artemis never moves money; edits are local-ledger
writes). So there is **no external finance action to gate in v1**. The genuine open decisions are: (a) what
the detail shows, (b) whether *local* edits (recategorize, mark-bill-paid, confirm-duplicate) need any
in-UI confirmation, and (c) whether to reserve a confirm-threshold affordance for an end-state where
Finance might take actions.

**Options for (a) content**
- **(A) Recent transactions + bills due + subscriptions list** (mockup ≈ this). Trade-off: covers the
  awareness scope; no spend-trend visual.
- **(B) (A) + a month-to-date spend summary header** (matches glance metric in decision 4). Trade-off:
  consistent with the card's headline; slightly more to render.

**Options for (b) local-edit confirmation**
- **(B1) No confirmation — local edits apply instantly** (they're reversible owner-private writes).
  Trade-off: frictionless; an accidental recategorize is silent.
- **(B2) Lightweight inline confirm only for destructive/merge edits** (the L3 "possible duplicate?"
  suggestions, per finance.md, are *already* inert-until-confirmed). Trade-off: matches the existing
  suggestion-inbox pattern; near-zero extra UI.

**Recommended default:** content **(B)**; local edits **(B2)** — instant for recategorize/edit, inline
confirm only for the L3 duplicate-merge suggestions (which finance.md already models as owner-confirmed).
**Do NOT build a S$500 confirm gate in v1** — there's no external finance action; **reserve** the
threshold-confirm affordance for the end-state (note it in the spec as deferred, don't wire it).

**Affects:** Finance · CLIENT-card. ⚠️ Flags a brief/scope mismatch — confirm with owner that the
"~S$500 confirm" is end-state-only, not v1.

---

## 9. How gated actions (Calendar invites / PendingActions) surface in the map UI

**Context.** ADR-012 puts pending actions on the **Review** card's pending-actions tab; ADR-012 also
*rejected* ntfy action buttons (IG1: the client Review screen is the only approval surface). Open: how does
the map signal that something is *waiting* (so the owner knows to go to Review), and does a domain card
(e.g. Calendar) advertise its own pending count?

**Options**
- **(A) Review card only** — pending count lives solely on the Review glance card; other cards say
  nothing. Trade-off: single source; but the owner standing on the Calendar card doesn't see that a calendar
  invite is staged.
- **(B) Originating domain card shows an accent badge** ("1 staged") that deep-links to Review. Trade-off:
  contextual awareness where the action originated; must not become a second approve surface (badge → jumps
  to Review, never approves in place).
- **(C) A persistent top-bar / minimap pending indicator** (global "N awaiting you"). Trade-off: always
  visible regardless of where you've panned; matches the "some cards off-screen" reality of the map.

**Recommended default:** **(A)+(C)** — Review card carries the authoritative pending count **and** a
small global top-bar indicator (since Review may be off-screen on the map). Optionally add (B)'s accent
dot on the originating card later. Approval ALWAYS happens on Review (lock-consistent); the indicators are
wayfinding only.

**Affects:** Calendar (+ Review) · CLIENT-world (top-bar/minimap) · CLIENT-screens. Cross-ref decision 6.

---

## 10. How the sensitivity gate's "held-back items + inline release" surfaces

**Context.** ADR-029 mandates: when a general (cloud-eligible) query is answered, sensitive items pulled
into context are **filtered from the cloud prompt, surfaced per-item, and offered for one-time inline
release** (NOT via GATE staging — inline, conversational, audited). This is fundamentally an **Ask-Artemis
pop-up** concern (it happens during a Q&A turn), but the owner must decide its presentation. Finance/Gmail
content is exactly the sensitive material this gate holds back.

**Options**
- **(A) Inline chip row under the answer**: "Held back: medical email, finance summary — [include &
  redo]". Trade-off: matches ADR-029's "say 'include the medical email'" + conversational flow; per-item
  chips give one-tap release. Best fit for the locked Ask pop-up result-row pattern.
- **(B) A single "answer may be incomplete — N items held back" line** that expands on click. Trade-off:
  less visual noise; one more click to see/release; weaker per-item transparency (ADR-029 wants per-item).
- **(C) Engine-tag-style inline marker** reusing the `review`/accent tag already in the pop-up footer.
  Trade-off: visually consistent with the locked engine-tag system; may be too subtle for a privacy action.

**Recommended default:** **(A)** — a per-item held-back chip row beneath the answer with one-tap
"include & redo", rendered in the **accent** colour (reusing the locked `review`/accent role). It's
per-item (ADR-029 requirement), conversational, and lives in the Ask pop-up where the gate fires. The
release is logged (audit) per ADR-029 — no extra UI.

**Affects:** Gmail, Finance (primary sensitive sources) · CLIENT-ask. (Tasks/Calendar are owner-authored/
mirror — less often held back, but the mechanism is domain-agnostic.)

---

## 11. Where the capture / suggestion inboxes live (Tasks captures, Finance duplicate-suggestions)

**Context.** Two modules drop **inert owner-confirm suggestions**: Tasks' capture-inbox ("I'll send the
report Friday" → suggested task) and Finance's L3 "possible duplicate?" suggestions. These are NOT the
gated-action path and NOT recipe-Review. Open: do they surface on their own domain card detail, on a
shared "inbox", or somewhere else?

**Options**
- **(A) Each on its own domain detail overlay** (Tasks card shows task-suggestions; Finance card shows
  dup-suggestions). Trade-off: contextual (you confirm where it belongs); but suggestions are easy to miss
  if you don't open that card.
- **(B) A shared "Suggestions/Inbox" surface** (own card or a section of Review). Trade-off: one place to
  triage all pending confirmations; but mixes semantically different confirm types and competes with Review.
- **(C) (A) + a glance-card accent badge** when a domain has pending suggestions. Trade-off: contextual +
  discoverable; consistent with the badge pattern used elsewhere (decisions 2–5, 9).

**Recommended default:** **(C)** — suggestions live on their **originating domain's detail overlay**, with
an **accent badge on that card's glance** when any are pending. Keeps confirmation in-context, makes it
discoverable on the map, and avoids a competing inbox surface. (Distinct from Review, which is gated
actions + recipes only.)

**Affects:** Tasks, Finance · CLIENT-card. Cross-ref decision 7.

---

## 12. Notification / ntfy ↔ client relationship

**Context.** gmail.md §E says the urgency briefing is "delivered to **ntfy / the CLIENT Review-Status
surface**". ADR-012 rejected ntfy *action buttons* (no approving from the push). So ntfy is a **read-only
alert channel**; the client is where you act. Open: what's the division of labour, and does tapping an ntfy
push deep-link into a specific map card?

**Options**
- **(A) ntfy = alerts only; tapping opens the client to Home** (map resting view). Trade-off: simplest;
  the owner then navigates to the relevant card manually.
- **(B) ntfy deep-links to the relevant domain card** (tap "important email" → opens client → flies to
  Gmail card / Review). Trade-off: best UX continuity; needs a deep-link scheme (Tauri URL handler) +
  per-notification target — more build.
- **(C) ntfy mirrors what's already on the map** (every push corresponds to a card badge/Review item; the
  push is just the off-device echo). Trade-off: clean mental model (ntfy = remote echo of map state); makes
  the client the single source of truth, ntfy purely a remote tap-on-shoulder.

**Recommended default:** **(C) as the model + (A) for v1 behaviour** — ntfy is the **remote echo** of
state that already lives on the map (never an independent action surface; never carries the gated approve,
per ADR-012). For v1, tapping opens the client to Home; **reserve (B) deep-linking** as a fast-follow once
the map deep-link scheme exists. Keeps the client authoritative and ntfy thin.

**Affects:** Gmail (urgency briefing is the main ntfy producer), Calendar/Tasks/Finance proactive hooks ·
CLIENT-world / app shell. (Some of this may sit outside the four CLIENT specs — flag for routing.)

---

## 13. The Ask-Artemis pop-up scope vs the per-domain detail overlays

**Context.** The Ask pop-up *shape* is locked (design-brief). Open is its **scope boundary** against the
four domains: a cross-domain question like "what's due this week?" is answered by the brain pulling
Finance bills + Tasks + Calendar (overview.md hub-synthesis). Does that answer render in the pop-up, or
deep-link into cards? And can the pop-up *act* (create task, stage an invite) or only answer?

**Options**
- **(A) Pop-up = answer + read-only; all actions happen on cards.** Trade-off: clean separation; but
  "remind me to call mom" is the canonical NL capture — forcing it to a card is worse UX.
- **(B) Pop-up answers AND performs the same auto/gated actions the cards do** (NL create task = auto;
  NL "RSVP yes" = stages a PendingAction → Review). Trade-off: most Jarvis-like; the gating rules are
  identical to the cards (server-side), so no new trust surface — just a new entry point.
- **(C) Pop-up answers + offers deep-link chips** ("→ open Tasks", "→ 3 bills in Finance") rather than
  inlining domain content. Trade-off: keeps the pop-up light, drives navigation to the rich cards.

**Recommended default:** **(B)+(C)** — the pop-up **answers and acts** (NL capture/auto-writes inline;
gated actions stage to Review exactly as the cards do — same server gate, no new approval surface), **and**
offers deep-link chips for "go see the full view". This is the locked "Ask anywhere" promise; gating is
unchanged because it's enforced server-side regardless of entry point.

**Affects:** all four (cross-domain "what's due this week" spans Finance/Tasks/Calendar; NL capture →
Tasks) · CLIENT-ask. Cross-ref decisions 6, 9, 10.

---

## 14. Lock-state behaviour per card (Vault-locked glance vs detail)

**Context.** ADR-025/app-flow: in **Connected·Vault-locked**, only Map + Status work; opening any
owner-private domain raises a re-unlock prompt. All four domains are owner-private (Finance explicitly
owner-only). Open: what does a domain **glance card** show while the vault is locked — the real count
(leaks data) or a masked state?

**Options**
- **(A) Cards show real glance counts even when locked.** Trade-off: most informative; but the glance
  number ("S$4,200 spent", "1 email needs you") is itself owner-private — leaks behind the lock.
- **(B) Cards show a masked/locked glance ("🔒 locked") until unlocked; opening prompts unlock.**
  Trade-off: privacy-correct (no owner data pre-unlock); the resting map is less informative when locked.
- **(C) Tier-0 derived-safe domains show counts; owner-private (these four) mask.** Trade-off: nuanced,
  consistent with the two-tier proactivity model (ADR-006); these four all fall on the mask side anyway.

**Recommended default:** **(B)/(C)** — all four glance cards **mask their count while Vault-locked**
(showing a lock affordance), since every one is owner-private; opening raises the standard re-unlock
prompt. Privacy-wall-correct and consistent with ADR-006/ADR-025. The map shape/positions stay visible
(not sensitive); only the *numbers* mask.

**Affects:** all four · CLIENT-card · CLIENT-core (state machine). Strongly recommended (privacy
requirement) — likely a near-lock, but worth owner ratification since it shapes the resting-map feel.

---

## 15. Fonts pass — defer or settle now?

**Context.** ADR-028 § Parked explicitly defers a "dedicated fonts pass". design-brief already names
**Space Grotesk** (display/UI/numerals) + **Inter** (body) and the mockups use them. So a usable default
exists; the open question is only whether to do a *dedicated* pass now or build on the named defaults.

**Options**
- **(A) Defer (keep ADR-028's park)** — build CLIENT-theme on Space Grotesk + Inter as named; revisit
  fonts as a polish pass. Trade-off: unblocks the build now; risks a later restyle.
- **(B) Settle the full type scale now** (sizes/weights/numerals/letter-spacing tokens). Trade-off:
  one-and-done type system; but it's polish that doesn't change *what gets built* and the mockups already
  encode workable values.

**Recommended default:** **(A) Defer** — the named pairing is locked and the mockups encode working
sizes; CLIENT-theme tokenises those as-is. A dedicated fonts pass stays parked (per ADR-028). No owner
decision needed unless they want to override the park.

**Affects:** all four (theme is global) · CLIENT-theme. Lowest priority — listed for completeness.
