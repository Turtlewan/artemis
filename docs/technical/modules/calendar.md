# Module design — Calendar (full / final)

_Per-module design doc (first of the spoke-module design docs). The complete, intended-final function
surface for the Calendar spoke. Source-of-truth for the CAL-* specs. Created 2026-06-08._

> Posture (ADR-011): **mirror + write-through + Artemis-native proposal overlay.** Google Calendar is the
> source of truth for real events; Artemis reads (incremental sync) and writes through (no divergent copy,
> no bidirectional sync); Artemis owns a thin native overlay (proposals/holds) + a preferences engine that
> Google has no concept of. Autonomy (decided 2026-06-08): **self-only changes are autonomous**; only
> external-effect actions (invites/cancels/RSVPs) route through the CLIENT Review screen.

## Plugs into the contract
- **Module** = a `ModuleManifest` (M1-a): typed `tools` (below) + `proactive_hooks` (§D) + `data_scope`.
  The calendar module's `data_scope = OWNER_PRIVATE` (real events are owner data) → its hooks are **Tier-1**
  (queued while the vault is locked, ADR-006).
- **Knowledge push** (M3-a `Connector` → `IngestPipeline`): past-meeting summaries → searchable knowledge.
- **Memory** (M4-b `MemoryWritePath`): standing facts ("1:1 with X on Tuesdays") via A.U.D.N.
- **Heartbeat** (M6): the proactive hooks.
- **Auth**: the shared M8-a Google-auth foundation (OAuth2 user-flow, refresh token in the owner-private
  encrypted scope, `calendar.events` + read scope).
- **Brain composes**: the module ships typed primitives; conversational scheduling ("lunch with mom next
  week") is the brain composing `find_time` + `create_event`. The module's job is that every primitive
  exists, typed, and correctly gated.

## A. Read / awareness — `action_risk: read` (never gated)
| Tool | Purpose |
|---|---|
| `calendar.list_calendars()` | the user's calendars (work/personal/family) + metadata |
| `calendar.list_events(window, calendar_ids?, query?)` | events across calendars in a window |
| `calendar.get_event(event_id)` | full detail of one event |
| `calendar.agenda(day\|range)` | rendered "what's my day/week" |
| `calendar.next_event()` | the next upcoming event |
| `calendar.search(query, range?)` | find events by text ("when did I last see X") |
| `calendar.free_busy(window, calendar_ids?)` | busy blocks across **your** calendars |
| `calendar.find_time(duration, window, constraints)` | free slots respecting working hours + buffers + all your calendars |
| `calendar.find_time_with_attendees(duration, window, attendee_emails)` | FreeBusy across invitees **+** you (Google FreeBusy API) |
| `calendar.conflicts(range?)` | detect double-bookings / overlaps |

## B. Write / management — write-through; gating per ADR-011 (auto = self-only; gated = external effect)
| Tool | `action_risk` / gating |
|---|---|
| `calendar.block_focus_time(range, title?)` | `write` · **auto** (self) — the "protect my afternoon" action |
| `calendar.create_event(...)` | **auto** if private/self · **high-stakes/gated** if attendees (sends invites) |
| `calendar.update_event(event_id, changes)` | **auto** if private · **gated** if it notifies attendees |
| `calendar.move_event(event_id, new_time)` | **auto** if private · **gated** if attendees |
| `calendar.cancel_event(event_id)` | **auto** if private · **gated** if attendees (sends cancellation) |
| `calendar.respond_to_invite(event_id, accepted\|declined\|tentative)` | **gated** (acts toward others) |
| `calendar.add_attendees` / `remove_attendees` | **gated** |
| `calendar.create_recurring_event(rrule, ...)` | by attendee presence |
| `calendar.set_reminders(event_id, reminders)` | `write` · **auto** (personal notification only) |
| `calendar.quick_add(text)` | Google natural-language add; gating by attendee presence |

**Gating mechanism:** the `ActionRisk` on each `ToolSpec` + a runtime check of `event.attendees` decides
auto-vs-gated. A gated action does not execute immediately — it becomes a **`TAKES_ACTION` recipe staged
for the Review screen** (CLIENT-b / M7-b). Auto actions execute write-through and are recorded in an
**activity log** (so the owner can see what Artemis did unattended).

## C. Proposal overlay — Artemis-native (ADR-011), promoted via Review
`calendar.propose_reschedule(event_id, suggested_time, reason)` · `calendar.propose_event(draft)` ·
`calendar.hold_tentative(range, label)` (optionally projected to Google as a *tentative* event) ·
`calendar.list_proposals()` · `calendar.approve_proposal(id)` (→ write-through) · `calendar.reject_proposal(id)`.
**Intentions projection:** render Habits/Goals (from the Productivity module) onto open slots as soft
suggestions. Proposals are Artemis-native rows (NOT copies of Google events) → they can never conflict.

## D. Proactive hooks — M6 Heartbeat (`check_ref → HookResult`), all **Tier-1**
- **Daily briefing** (cron, e.g. 07:00) — "here's your day."
- **Upcoming-event reminder** (interval) — "your 3pm starts in 15 min" + location/travel awareness.
- **Change detection** (interval poll via `syncToken`) — "your 3pm moved" / "X cancelled" / "new invite from Y."
- **Conflict / double-booking alert.**
- **Free-gap → focus-protect suggestion** (emits a proposal).
- **Unanswered-invite nudge** — "3 invites awaiting your response."
- **Prep nudge** — "meeting with X tomorrow — last time you noted Y" (pulls from memory/knowledge).

## E. Preferences engine — owned, Artemis-native (owner-private scope; Google has no equivalent)
Working hours · timezone(s) · default write-calendar · inter-meeting buffer · "no meetings before/after X"
· default reminders · focus-block prefs · **per-no-one autonomy is on by default** (self-changes auto).
`find_time` + auto-scheduling honour these. Stored in the owned SQLCipher store (M0-a `relational/`, M2 wall).

## F. Knowledge + memory integration
Push past-meeting summaries to the **knowledge layer** (searchable: "when did I last meet X") · extract
standing facts to **memory** via A.U.D.N. (recurring 1:1s, key contacts) · feed learned preferences back
into `find_time` (preferred meeting times, typical buffers).

## Security — external event content is UNTRUSTED
Event fields that originate from **other people** (invite title/description/location/attendee display
names) are attacker-controllable → an injection vector when fed to the LLM (briefings, prep nudges).
**Externally-sourced event text passes through the `artemis.untrusted` / spotlighting layer (DR-a)** before
it reaches the brain, exactly like Gmail. Self-created event text is trusted. Refresh token never logged;
lives only in the owner-private encrypted scope. Auto actions are logged; gated actions need owner approval.

## Data
- **Read-cache** (mirror): a per-scope cache of Google events keyed by Google event id + `syncToken`, in the
  encrypted vault — invalidated by incremental sync; never authoritative.
- **Overlay store** (owned): proposals / tentative holds — Artemis-native rows.
- **Preferences store** (owned): the §E settings.
- **Activity log** (owned): auto-actions Artemis took unattended.
All owned stores are SQLCipher under the owner-private scope (M2 wall). Schema detail → the CAL specs +
`data-model.md` update.

## Decisions (2026-06-08)
- **Full/final surface** incl. attendee availability (FreeBusy), recurrence, RSVP, multi-calendar.
- **Self-only changes autonomous**; external-effect gated through Review (ADR-011).
- **Location-aware now; true travel-time deferred** to a future **Maps connector** (Google Distance Matrix)
  — out of this milestone.
- **Polling, not push** (no public webhook) — incremental `syncToken`; Heartbeat drives cadence.
- **Published-unverified single-owner OAuth** (refresh tokens persist; one-time unverified-app warning).

## Spec decomposition (on the shared M8-a Google-auth foundation)
- **CAL-a** — read + `find_time`/`find_time_with_attendees` engine + the preferences engine + the read-cache + sync.
- **CAL-b** — write/management tools (create/update/move/cancel/RSVP/recurrence) + the auto-vs-gated classifier + activity log + Review-staging integration.
- **CAL-c** — the proposal overlay + the proactive hooks + knowledge/memory integration + the untrusted-content handling.
(Likely 3 specs + M8-a; CAL-b may split if the write surface + gating exceeds the file budget.)

## Deferred / future
- **Maps connector** → true travel-time + "leave by" alerts.
- **Auto-escalation** of recurring proposals; learning preferred times from accept/reject history.
- **Other-people scheduling assistant** (negotiating times via email) — needs Gmail send (deferred).
