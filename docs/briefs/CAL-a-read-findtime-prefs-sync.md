# Brief: CAL-a — read/awareness tools + find_time engine + preferences + read-cache + sync

- **For:** AFK Deep Details drafting · **autonomy_level:** L2 · **token_profile:** balanced
- **review_domains:** security, data  _(security: encrypted read-cache + the `externally_authored` provenance tag + scope wall; data: the read-cache + preferences schema, sync idempotency, bounded-window)_
- **Read first:** `docs/briefs/CAL-shared.md` · `docs/technical/modules/calendar.md` §A,§E,§Data · M1-a · M8-a · M2-b/c · M0-a/d
- **Build order:** first CAL spec; creates the shared `calendar` manifest. CAL-b/c modify it; CAL-c's projected-hold marker is recognized by this sync (decision 3).

## Intent
The read/awareness foundation of the Calendar module: the full read tool surface (§A), a deterministic
`find_time` / `find_time_with_attendees` engine, the owned **preferences** store, and the **read-cache**
with a full **incremental-sync mirror** engine. No writes, no gating, no hooks (those are CAL-b/c/d).

## Scope / files (proposed — drafter finalises)
- `src/artemis/modules/calendar/__init__.py`, `manifest.py` (create the `calendar` ModuleManifest, data_scope OWNER_PRIVATE, read tools registered; empty hooks for now)
- `client.py` — the `CalendarClient` port + `GoogleCalendarClient` (over googleapiclient) + `FakeCalendarClient` (tests)
- `cache.py` — read-cache SQLCipher store + the incremental `sync()` engine (syncToken, bounded window, adds/updates/deletes, recognizes the `artemis_overlay` marker as own-projection per shared decision 3)
- `preferences.py` — preferences SQLCipher store + defaults + get/set
- `read_tools.py` — the §A tools (typed `ToolSpec`s, all `action_risk = READ`) + `find_time` logic
- `tests/test_calendar_read.py`
- register calendar scopes via M8-a (`calendar.readonly` + `calendar.events`)

## Resolved decisions (from CAL-shared — bind)
- Read-cache = full incremental-sync mirror; bounded rolling window default −12mo/+12mo (a preference), expandable.
- `externally_authored` flag set per event (organizer/creator email ≠ owner email). CAL-a only **tags**; quarantine is CAL-d.
- Sync recognizes `extendedProperties.private.artemis_overlay` → own-projection (render as hold, not external, not double-counted).
- find_time deterministic over declared prefs; find_time_with_attendees via Google FreeBusy API; learning deferred.
- Multi-calendar: read all; tools accept optional `calendar_ids`.

## Tasks (concern layers — drafter expands to full step→verify tasks)
1. `CalendarClient` port + Google impl + fake.
2. Preferences store (schema: working_hours, timezone(s), default_write_calendar, buffer_minutes, no_meeting_before/after, default_reminders, focus_block_prefs, sync_window_months, owner_email cache; autonomy=self-auto default) + defaults + get/set.
3. Read-cache store + `sync()` engine (initial full + incremental syncToken; idempotent; marker-aware; `externally_authored` tagging).
4. §A read tools as typed `ToolSpec`s (READ) reading the cache; `find_time` + `find_time_with_attendees`.
5. Manifest assembly (calendar ModuleManifest with the read tools) + scope registration.
6. Tests (fakes): sync idempotency + add/update/delete + marker-skip; `externally_authored` correctness; find_time honors working hours/buffers/no-meeting windows; FreeBusy intersection; bounded-window; locked-store → `ScopeLockedError`.
7. (GATED on-hardware) real Google sync + real SQLCipher cache + a real FreeBusy query.

## Acceptance shape
mypy --strict + ruff clean; pytest covers sync idempotency, provenance tagging, marker recognition, find_time correctness, locked-store; gated on-hardware = real sync + FreeBusy + SQLCipher.

## Out of scope / deferred
Writes, gating, activity log (CAL-b); overlay/proposals, hooks (CAL-c); knowledge/memory/untrusted-quarantine (CAL-d); travel-time (Maps connector); learned preferred-times.
