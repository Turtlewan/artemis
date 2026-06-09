# CAL — shared context (read before drafting any CAL-* spec)

_Cross-cutting decisions + seams for the Calendar module specs (CAL-a/b/c/d). Each CAL brief references
this file. Source-of-truth design: `docs/technical/modules/calendar.md`; posture: ADR-011. These
decisions are **resolved at planning** — do not re-litigate; bind to them. Drafted 2026-06-08 in a
present-session CAL elicitation sprint (forks F1 gating + F2 holds answered by the owner)._

## Module identity
- One `calendar` module = a `ModuleManifest` (M1-a) with `data_scope = DataScope.OWNER_PRIVATE`
  (real events are owner data → its hooks are **Tier-1**, queued while the vault is locked, ADR-006).
- **Proposed package:** `src/artemis/modules/calendar/`. ⚠️ Verify against where **M1-d** placed its
  `get_current_time` module/tool; match that convention. Park `[NEEDS CLARIFICATION]` if M1-d's module
  layout differs.
- The manifest is **shared + grown across specs**: CAL-a creates it with the read tools; CAL-b adds the
  write tools; CAL-c adds the proposal tools + proactive hooks. So CAL-b/c **modify** CAL-a's
  `modules/calendar/manifest.py`. Build order is strictly **CAL-a → b → c → d**.

## Auth seam (M8-a — already ready in docs/changes/)
- Get an authorized client via `GoogleCredentialsFactory.authorized_credentials()` →
  `googleapiclient.discovery.build("calendar", "v3", credentials=creds)`.
- Register scopes at import/registration via M8-a `register_google_scopes("calendar", {...})`.
  **Least-privilege scope set:** `https://www.googleapis.com/auth/calendar.readonly` (read all subscribed
  calendars + FreeBusy) + `https://www.googleapis.com/auth/calendar.events` (create/edit/delete events).
  Do NOT request the broad `…/auth/calendar`.
- On `ReauthRequiredError` from the factory, surface it (owner re-runs `artemis-google-auth login`) — do
  not crash a hook.
- **Owner email/identity** = the authenticated Google account (the `primary` calendar id). Resolve once,
  cache in the preferences store; it is the key for the "organizer ≠ owner" untrusted check.

## Google-API access behind a testable port
- Wrap the googleapiclient calendar service behind a thin typed **`CalendarClient` port** (introduced in
  CAL-a, `modules/calendar/client.py`) so tests inject a fake and no CAL logic calls googleapiclient
  directly. All real Google calls go through it.
- **Off-hardware:** everything tests against a `FakeCalendarClient` + `FakeKeyProvider` + fake stores.
  **On-hardware gated** (mirror the M8-a Task-7 pattern): real Google round-trips (sync, write-through,
  FreeBusy), real SQLCipher keyed stores, real authorized API pings.

## Storage (owned stores — M2 wall)
- All owned calendar stores are **SQLCipher under the owner-private scope**, opened via the M2 primitive
  `sqlcipher_open(path, key.as_hex())` with `key = KeyProvider.dek_for_scope(OWNER_PRIVATE)` — reuse the
  **exact pattern of M8-a's `SqlCipherTokenStore`** (keyed `_connect`, `ScopeLockedError` propagates =
  no unlock → no data, `as_hex()` local-only). Paths under
  `paths.scope_dir(settings, OWNER_PRIVATE) / "calendar" / <store>.db` (read-cache reconciles under the
  broker-mounted `vault/` at on-hardware integration — same one-line deferral as M3-a/M8-a).
- Stores: **read-cache** (mirror of Google events; never authoritative) · **overlay** (proposals/holds) ·
  **preferences** · **activity log**. Which spec builds which: CAL-a = read-cache + preferences; CAL-b =
  activity log; CAL-c = overlay.

## RESOLVED DECISIONS (bind to these)
1. **Read-cache = full incremental-sync mirror** (not lazy/live). Initial full sync over a **bounded
   rolling window** (default −12 months / +12 months, stored in preferences, expandable) per calendar;
   incremental sync via per-calendar Google **`syncToken`** applies adds/updates/deletes; queries read
   the cache. The change-detection hook (CAL-c) drives sync cadence; CAL-a ships the sync *engine* + a
   manual/triggered `sync()`.
2. **Gating = STRICT (owner fork F1).** For ANY mutation: if the target event has **attendees other than
   the owner**, the action is **gated** — it does NOT execute; it is staged as a `TAKES_ACTION` recipe for
   the **CLIENT Review screen** (M7-b / CLIENT-b seam). If the event is **self-only** (no other
   attendees), it is **auto**: write-through executes and is recorded in the activity log. `respond_to_invite`
   (RSVP) is **always gated** (acts toward others). `block_focus_time` + `set_reminders` are **always auto**
   (self-only). The static `ToolSpec.action_risk` (M1-a enum) is a baseline hint; the **runtime classifier
   in CAL-b** (`event.attendees` minus owner) is the actual gate. Document: this is more conservative than
   `sendUpdates=none` cleverness — chosen deliberately.
3. **Holds projected to Google (owner fork F2).** `hold_tentative` / proposals are written to Google as
   **`status: "tentative"`** events **and** stored as native overlay rows. Each projected Google event
   carries an Artemis marker **`extendedProperties.private.artemis_overlay = <proposal_id>`**. The CAL-a
   sync MUST recognize that marker → treat the event as an **own-projection** (not an external event; do
   not re-ingest it as untrusted, do not double-count it in the agenda as a real meeting — render it as a
   hold). The overlay store maps `proposal_id ↔ google_event_id`. **approve_proposal** → promote
   (tentative→confirmed `update`, or create the real event) + clear the hold. **reject_proposal** → delete
   the projected Google event + mark the overlay row rejected. Projected holds are self-only → **auto**
   write-through (consistent with the strict gate).
4. **Untrusted chokepoint = at the LLM-prompt boundary, not the tool-return boundary.** An event is
   externally-authored when its **organizer/creator email ≠ owner email** → CAL-a tags each cached/returned
   event `externally_authored: bool`. Any code path that puts event text (title/description/location/
   attendee display-names) **into an LLM prompt** (CAL-c briefings, prep nudges) MUST pass the
   externally-authored fields through **DR-a `artemis.untrusted`** (spotlight + quarantine) first. CAL-d
   provides the `quarantine_event_text` helper (over DR-a) and wires the proactive consumers. Self-created
   event text is trusted. ⚠️ Security-review focus: confirm this single chokepoint covers every path event
   text reaches the model (incl. the brain's direct rendering of a read-tool result — flag if that path
   bypasses the helper).
5. **find_time** = deterministic slot-finder over the cache's busy blocks within working hours, honoring
   buffers + no-meeting-before/after windows from preferences; returns ranked free slots ≥ duration.
   `find_time_with_attendees` = Google **FreeBusy API** across attendee emails + owner, intersect free.
   **Learning** preferred times from accept/reject history is **deferred** (calendar.md Deferred).
6. **Recurrence = full three-scope editing** (Google semantics: this-event / this-and-following /
   all-events). A recurring event with attendees → gated like any attendee event.
7. **Multi-calendar:** read across ALL the owner's calendars; write to the **default-write-calendar**
   (a preference); tools accept optional `calendar_ids` to target. 
8. **Polling, not push** (no public webhook) — incremental `syncToken`; the Heartbeat drives cadence (CAL-c).
9. **Travel-time deferred** to a future Maps connector — location-aware only (store/show location; no
   "leave by"). Out of scope for all CAL specs.

## Seams to bind (verify against the named ready spec; park `[NEEDS CLARIFICATION]` on mismatch)
| Seam | Spec | Use |
|------|------|-----|
| `ModuleManifest` / `ToolSpec(action_risk: ActionRisk)` / `HookSpec(check_ref)` | M1-a | manifest + tools + hooks |
| `Connector` → `IngestPipeline.ingest` | M3-a | push past-meeting summaries (CAL-d) |
| `MemoryWritePath` / `build_write_path` | M4-b | extract standing facts (CAL-d) |
| Heartbeat + `HookSpec` (⚠️ `check_ref` returns `bool` per M1-a vs `HookResult` per calendar.md — bind to M6-a) | M6-a | proactive hooks (CAL-c) |
| Review staging / `TAKES_ACTION` recipe (the owner-approval surface) | M7-b + CLIENT-b | gated-action staging (CAL-b) — **highest-risk binding; verify or park** |
| `artemis.untrusted` (spotlight + dual-LLM quarantine) | DR-a | untrusted event text (CAL-d) |
| `GoogleCredentialsFactory` / `register_google_scopes` | M8-a | auth (all) |
| `sqlcipher_open` / `KeyProvider` / `OWNER_PRIVATE` / `paths.scope_dir` | M2-b/c, M0-a | owned stores (all) |

## Per-brief drafting pipeline (AFK)
Each CAL-* drafter: read this file + its brief + `calendar.md` + the named seam specs → write the full
Deep Details spec (apex-orchestrate spec-template) to `docs/drafts/<spec>.md` → dispatch the brief's
`review_domains` as parallel `apex-spec-reviewer` agents → resolve BLOCK/FLAG → run the readiness gate →
move to `docs/changes/` + `status: ready`. **Park** `[NEEDS CLARIFICATION]` (don't guess) on any seam
mismatch or unresolved fork; a parked spec stays in `docs/drafts/` for the owner's next present session.
Specs may exceed 3 files as justified-atomic units (precedent: M0-a/M1-a/M8-a) but must stay ≤2 logical
phases — split-flag in a parked note if a brief's scope exceeds that.
