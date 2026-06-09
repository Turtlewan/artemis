# Brief: CAL-b — write/management tools + strict auto-vs-gated classifier + activity log + Review-staging

- **For:** AFK Deep Details drafting · **autonomy_level:** L2 · **token_profile:** balanced
- **review_domains:** security, auth  _(security: the gating classifier is the safety-critical boundary — a mis-classified attendee event = an unapproved external action; write-through auth; auth: acting-on-behalf-of-owner, the gated boundary, no scope/identity from a tool arg)_
- **Read first:** `docs/briefs/CAL-shared.md` · `docs/technical/modules/calendar.md` §B · M1-a · M7-b + CLIENT-b (Review staging) · M8-a · M2
- **Build order:** after CAL-a (modifies `modules/calendar/manifest.py`; uses CAL-a's `CalendarClient` + cache).

## Intent
The write/management surface (§B): create/update/move/cancel events, RSVP, attendees, recurrence,
reminders, quick-add — all **write-through** to Google. The **STRICT** runtime auto-vs-gated classifier
(shared decision 2), the **activity log** of auto-actions, and the integration that stages gated actions
as `TAKES_ACTION` recipes on the **CLIENT Review screen**.

## Scope / files (proposed — drafter finalises)
- `src/artemis/modules/calendar/write_tools.py` — §B tools (typed `ToolSpec`s, `action_risk` baselines)
- `gating.py` — the runtime classifier `classify(action, event) -> AUTO | GATED` (attendees-minus-owner) + the stage-vs-execute dispatch
- `activity_log.py` — owned SQLCipher append-only log of auto-actions
- `manifest.py` (**modify** — add write tools)
- `tests/test_calendar_write.py`

## Resolved decisions (from CAL-shared — bind)
- STRICT gating: any attendee other than owner → GATED (stage, don't execute). Self-only → AUTO (write-through + log). RSVP always gated. focus-block + reminders always auto.
- Runtime classifier (event.attendees) is the real gate; `ToolSpec.action_risk` is a baseline hint only.
- Write-through hits Google directly via CAL-a's `CalendarClient`; on success update/invalidate the read-cache; on failure surface a typed error (never silently drop).
- Recurrence: full three-scope edits (this / this-and-following / all); attendee recurring → gated.
- Gated path stages via the M7-b/CLIENT-b Review seam — **bind to the real staging API; this is the highest-risk seam → park `[NEEDS CLARIFICATION]` if its shape is absent/unclear.**

## Tasks (concern layers)
1. The runtime classifier (`classify`) + owner-resolution (attendees minus owner email) + unit-tested truth table (self-only→auto; +attendee→gated; RSVP→gated; focus/reminders→auto).
2. Activity-log store (append-only: ts, tool, event_id, summary, result).
3. §B write tools as `ToolSpec`s → each routes through `classify`: AUTO → write-through (CalendarClient) + activity-log; GATED → build + stage a `TAKES_ACTION` recipe (Review seam), return a "staged for approval" result, do NOT execute.
4. Recurrence (three-scope) + `sendUpdates` handling on write-through.
5. Manifest modify (add write tools).
6. Tests (fakes): the classifier truth table; AUTO executes + logs; GATED stages + does NOT call the write API; recurrence scopes; write-failure surfaces; locked-store → `ScopeLockedError`.
7. (GATED on-hardware) real write-through (create a self event), real gated-staging round-trip, real recurrence edit.

## Acceptance shape
mypy --strict + ruff clean; pytest proves the classifier truth table + the AUTO-executes / GATED-stages-only invariant (the safety-critical assertion) + recurrence + locked-store; gated on-hardware = real write-through + staging.

## Out of scope / deferred
Read tools / find_time (CAL-a); proposal overlay + hooks (CAL-c); knowledge/memory/untrusted (CAL-d). Sending email to negotiate times (needs Gmail send — deferred).
