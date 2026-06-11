---
spec: cal-a-read-findtime-prefs-sync
status: ready
token_profile: balanced
autonomy_level: L2
---
<!-- amended 2026-06-11 per contracts.md (Seam 4) + cal-gate.md BLOCKs B4, B5, B11, U4 -->

# Spec: CAL-a — Calendar read/awareness tools + find_time engine + preferences store + incremental-sync read-cache

**Identity:** The read-only foundation of the Calendar module: a `CalendarClient` port over googleapiclient, an owner-private SQLCipher preferences store (working hours/timezone/buffers), an owner-private SQLCipher read-cache with a full incremental-sync engine (syncToken, bounded rolling window, `artemis_overlay` marker recognition, `externally_authored` provenance tag), and the §A read tools + `find_time` / `find_time_with_attendees` as typed `ToolSpec`s.
→ why: see docs/technical/modules/calendar.md §A,§E,§Data · docs/technical/adr/ADR-011-spoke-source-of-truth.md

<!-- Split rule: ONE logical phase (the read/awareness/prefs/sync foundation). Creates >3 files; justified atomic exception — the CalendarClient port, two SQLCipher stores, the sync engine, and the §A tools share a single vocabulary (CachedEvent, CalPrefs, syncToken); splitting would leave a sync engine with no store to write into, or tools with no cache to query. Flagged per rules. No writes, no gating, no hooks — those are CAL-b/c/d. -->

## Assumptions
- **M0-a** (`Settings`, `get_settings`, `paths.scope_dir`) complete. → impact: Stop (stores use `paths.scope_dir`).
- **M0-d** (`ports/` package, frozen-dataclass + `Protocol` conventions) complete. → impact: Stop.
- **M2-b** (`KeyProvider` Protocol at `artemis.identity.key_provider`, `SecretKey.as_hex()`, `ScopeLockedError`, `OWNER_PRIVATE` from `artemis.identity.scope`) complete. → impact: Stop (both stores open under the owner DEK via this API).
- **M2-c** (`sqlcipher_open(path, key_hex)` at `artemis.data.sqlcipher`) complete. → impact: Stop (both stores call `sqlcipher_open` exactly; wrong symbol name = build break).
- **M8-a** (`register_google_scopes` at `artemis.integrations.google.scopes`, `GoogleCredentialsFactory`, `ReauthRequiredError` at `artemis.integrations.google`) complete. → impact: Stop (scope registration + authorized client depend on these exact exports).
- **M1-a** (`ModuleManifest`, `ToolSpec`, `ActionRisk`, `DataScope` at `artemis.manifest`) complete. → impact: Stop (the manifest + all read ToolSpecs are constructed using these models).
- Google `calendar.readonly` scope covers `calendarList.list`, `events.list`, `events.get`, and the FreeBusy API. CAL-a registers **only `calendar.readonly`** (U4 / Seam 4: `calendar.events` write scope belongs to CAL-b which owns all write operations; registering it here would grant write access to an owner who pauses at CAL-a). The `calendar.freebusy` scope is a narrower alternative; `calendar.readonly` is used for simplicity. If on-hardware testing shows `calendar.readonly` is insufficient for FreeBusy (R1), expand in CAL-a's `register_google_scopes` call. → impact: Caution.
- Off-hardware: all tests run against `FakeCalendarClient` + `FakeKeyProvider` + in-memory/temp stores (no real Google calls, no real SQLCipher). Real Google round-trips + real SQLCipher + real FreeBusy = **GATED on-hardware** (Task 8), mirroring the M8-a Task 7 pattern. → impact: Stop (CI must pass without credentials or a mounted vault).
- The vault-path reconciliation for the two stores (pointing paths under the broker-mounted `/opt/artemis/<slot>/<scope>/vault/`) is a one-line path adapter deferred to on-hardware integration, identical to the M3-a/M8-a deferral. Off-hardware, paths derive from `paths.scope_dir(settings, OWNER_PRIVATE) / "calendar" / <store>.db`. → impact: Low.
- CAL-b/c will **modify** `manifest.py`; CAL-a creates it with read tools only. → impact: Caution (do not pre-populate write/proposal tools here).

**Module path confirmed:** `src/artemis/modules/<name>/` is the LOCKED convention for all domain modules; the shared Google auth foundation stays in `src/artemis/integrations/google/`. DeepSeek must create `src/artemis/modules/__init__.py` (listed in Files to Change) as the first action if it does not already exist.

Simplicity check: considered using the Google API directly in tool functions (no client port) — rejected: the `CalendarClient` port is required so off-hardware tests inject a fake (no network). Considered one unified SQLCipher store for prefs + cache — rejected: different schemas, different invalidation lifecycles; two narrow stores are simpler and each stays under 200 lines. Considered a lazy/live (no-cache) read mode — rejected by CAL-shared resolved decision 1: full incremental-sync mirror is required.

## Prerequisites
- Specs complete: **M0-a**, **M0-d**, **M2-b**, **M2-c**, **M8-a**, **M1-a**.
- Build order: CAL-a is the first CAL spec; CAL-b/c must NOT start before this spec is committed.
- Environment: `google-api-python-client` already in pyproject (added by M8-a). No new runtime deps; all Google calls go through `CalendarClient` (testable without PyPI install changes off-hardware). On-hardware only: real `sqlcipher3`/APSW binding (M2-c), real OAuth credentials (M8-a), network to `googleapis.com`.

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| /Users/artemis-build/artemis/src/artemis/modules/__init__.py | create | modules package marker (create if not already present) |
| /Users/artemis-build/artemis/src/artemis/modules/calendar/__init__.py | create | calendar package marker + re-exports |
| /Users/artemis-build/artemis/src/artemis/modules/calendar/manifest.py | create | `calendar` `ModuleManifest` (read tools, `data_scope=OWNER_PRIVATE`, empty hooks); CAL-b/c will modify |
| /Users/artemis-build/artemis/src/artemis/modules/calendar/client.py | create | `CalendarClient` port Protocol + `GoogleCalendarClient` + `FakeCalendarClient` |
| /Users/artemis-build/artemis/src/artemis/modules/calendar/preferences.py | create | `CalPrefs` dataclass + `PreferencesStore` (SQLCipher, OWNER_PRIVATE) with defaults + get/set |
| /Users/artemis-build/artemis/src/artemis/modules/calendar/cache.py | create | `CachedEvent` dataclass + `EventCacheStore` (SQLCipher, OWNER_PRIVATE) + `CalendarSyncEngine` (`sync()`) |
| /Users/artemis-build/artemis/src/artemis/modules/calendar/read_tools.py | create | §A typed `ToolSpec`-callable functions + `FindTimeEngine` |
| /Users/artemis-build/artemis/tests/test_calendar_read.py | create | off-hardware tests (fakes); all Task 7 test cases |

## Tasks

- [ ] Task 1: `CalendarClient` port + `GoogleCalendarClient` + `FakeCalendarClient` — files: `/Users/artemis-build/artemis/src/artemis/modules/calendar/client.py` —

  Define `class CalendarClient(Protocol)` (structural port; `# satisfies CalendarClient` comment + static assertion in tests). All methods return plain dicts matching the raw Google Calendar v3 JSON shapes (calendar list items, event resources, freeBusy response) — the cache and tools parse into typed dataclasses above this layer. Methods:
  ```python
  # --- Read methods (CAL-a) ---
  def list_calendars(self) -> list[dict[str, object]]: ...
  def list_events(
      self,
      calendar_id: str,
      *,
      time_min: str | None = None,
      time_max: str | None = None,
      sync_token: str | None = None,
      page_token: str | None = None,
      max_results: int = 250,
      show_deleted: bool = False,
  ) -> dict[str, object]: ...  # {items, nextPageToken?, nextSyncToken?}
  def get_event(self, calendar_id: str, event_id: str) -> dict[str, object]: ...
  def query_free_busy(
      self,
      time_min: str,
      time_max: str,
      items: list[dict[str, str]],  # [{"id": email_or_calendar_id}, ...]
  ) -> dict[str, object]: ...  # standard FreeBusy response

  # --- Write methods (B5 / Seam 4 — canonical set; implemented in CAL-b via GoogleCalendarClient + FakeCalendarClient) ---
  # These are declared here so the Protocol is complete; GoogleCalendarClient and FakeCalendarClient
  # MUST implement all of them (CAL-b adds the bodies in its Files to Change for client.py).
  # ToolSpec.name is bare; "module.tool" is the registry id used by stage()/get_tool().
  def create_event(self, *, summary: str, start: str, end: str, description: str | None = None,
                   location: str | None = None, attendees: tuple[str, ...] = (),
                   calendar_id: str, recurrence: tuple[str, ...] = (),
                   reminders: dict | None = None, send_updates: str = "all") -> dict[str, object]: ...
  def update_event(self, event_id: str, changes: dict[str, object], *,
                   recurrence_scope: str, send_updates: str = "all") -> dict[str, object]: ...
  def move_event(self, event_id: str, *, new_start: str, new_end: str,
                 recurrence_scope: str, send_updates: str = "all") -> dict[str, object]: ...
  def cancel_event(self, event_id: str, *, recurrence_scope: str,
                   send_updates: str = "all") -> None: ...
  def respond_to_invite(self, event_id: str, response: str) -> dict[str, object]: ...
  def add_attendees(self, event_id: str, attendee_emails: list[str], *,
                    send_updates: str = "all") -> dict[str, object]: ...
  def remove_attendees(self, event_id: str, attendee_emails: list[str], *,
                       send_updates: str = "all") -> dict[str, object]: ...
  def quick_add(self, text: str, calendar_id: str) -> dict[str, object]: ...  # always-AUTO (B10 / Seam 4)
  def set_reminders(self, event_id: str, reminders: list[dict[str, object]]) -> dict[str, object]: ...
  # NOTE: there is NO delete_event method — use cancel_event (Seam 4). Any spec referencing
  # delete_event must be amended to cancel_event.
  ```

  `class GoogleCalendarClient` constructed with `(credentials_factory: GoogleCredentialsFactory, *, settings: Settings)`. The `_service` property lazily calls `credentials_factory.authorized_credentials()` then `googleapiclient.discovery.build("calendar", "v3", credentials=creds)` — only built once per instance; call `authorized_credentials()` once per `GoogleCalendarClient` construction cycle. On `ReauthRequiredError` propagate it — do NOT crash a hook or swallow it. Each method delegates to the matching `service.calendarList().list()` / `service.events().list()` / `service.events().get()` / `service.freebusy().query()` googleapiclient call (`.execute()`). Document: no method retries — retry policy is the caller's concern.

  `class FakeCalendarClient` (TEST). Constructor accepts `calendar_list: list[dict]`, `events_by_calendar: dict[str, list[dict]]`, `free_busy_response: dict`. `list_calendars()` returns `calendar_list`. `list_events(calendar_id, *, sync_token=None, page_token=None, **kwargs)`: if `sync_token` is non-None returns `{"items": [], "nextSyncToken": "fake-token-2"}` (simulates no-change incremental sync, configurable via `set_incremental_events`); else returns `{"items": events_by_calendar.get(calendar_id, []), "nextSyncToken": "fake-token-1"}`. `get_event(calendar_id, event_id)` returns the matching item from `events_by_calendar` or raises `KeyError`. `query_free_busy(...)` returns `free_busy_response`.

  — done when: `uv run mypy --strict src` passes; a static `_c: CalendarClient = FakeCalendarClient([], {}, {})` type-checks.

- [ ] Task 2: Preferences store — files: `/Users/artemis-build/artemis/src/artemis/modules/calendar/preferences.py` —

  `@dataclass(frozen=True) class CalPrefs`:
  ```python
  working_hours_start: str = "09:00"   # HH:MM local
  working_hours_end: str   = "18:00"   # HH:MM local
  timezone: str            = "UTC"     # IANA timezone name
  default_write_calendar: str = "primary"
  buffer_minutes: int      = 15        # minimum gap between meetings
  no_meeting_before: str   = "09:00"   # HH:MM; find_time respects this
  no_meeting_after: str    = "18:00"   # HH:MM; find_time respects this
  default_reminder_minutes: int = 10
  focus_block_duration_minutes: int = 90
  sync_window_months_past: int  = 12   # rolling window: how far back to sync
  sync_window_months_future: int = 12  # rolling window: how far forward to sync
  owner_email: str | None  = None      # cached once from the 'primary' calendar id
  ```
  All fields have defaults so `CalPrefs()` is a valid object with sensible defaults.

  `class PreferencesStore` constructed with `(settings: Settings, key_provider: KeyProvider)`.

  `def _db_path(self) -> Path`: `paths.scope_dir(settings, OWNER_PRIVATE) / "calendar" / "preferences.db"` (document vault-path reconciliation deferral — same pattern as M8-a `SqlCipherTokenStore`).

  `def _connect(self) -> Connection`: `key = key_provider.dek_for_scope(OWNER_PRIVATE)` (propagates `ScopeLockedError` if locked — no unlock, no data); `mkdir(parents=True, exist_ok=True)` the db dir; `conn = sqlcipher_open(self._db_path(), key.as_hex())`; execute `CREATE TABLE IF NOT EXISTS prefs (id INTEGER PRIMARY KEY CHECK (id=1), data TEXT NOT NULL)` (stores the whole `CalPrefs` as JSON in one row — preferences is a small, single-record store). **`key.as_hex()` assigned only to a local variable inside `_connect()`, never to `self`** (same scoping rule as M8-a tokens.py).

  `def load(self) -> CalPrefs`: `_connect()`, select `data` where `id=1`; if no row return `CalPrefs()` (defaults); else `CalPrefs(**json.loads(data))` — unknown keys in the JSON are ignored (forward-compat: CalPrefs fields expand over time; `**` with frozen dataclass raises `TypeError` on unknown fields, so use `dataclasses.fields` filter: only pass known field names).

  `def save(self, prefs: CalPrefs) -> None`: `_connect()`, upsert the `id=1` row with `json.dumps(dataclasses.asdict(prefs))`.

  `def update(self, **kwargs: object) -> CalPrefs`: `load()`, build a new `CalPrefs` replacing only the given fields (using `dataclasses.replace`), `save()`, return the new prefs. Reject unknown field names with `ValueError(f"unknown pref field: {k}")`.

  — done when: `uv run mypy --strict src` passes; `FakeKeyProvider(owner_unlocked=False)` → `load()` raises `ScopeLockedError`; `PreferencesStore(settings, FakeKeyProvider(...))` + `save(CalPrefs(timezone="Asia/Singapore"))` + `load()` round-trips the field (on-hardware SQLCipher only; off-hardware this test is marked `pytest.mark.skip(reason="requires SQLCipher")` — see Task 7).

  **Off-hardware test approach:** use a `FakePreferencesStore` in-memory shim (a simple `dict`-backed get/set, defined in `tests/test_calendar_read.py`) for all Task 7 functional tests; the real SQLCipher round-trip is gated (Task 8).

- [ ] Task 3: Read-cache store + incremental-sync engine — files: `/Users/artemis-build/artemis/src/artemis/modules/calendar/cache.py` —

  **`CachedEvent` dataclass** (frozen):
  ```python
  @dataclass(frozen=True)
  class CachedEvent:
      event_id: str           # Google event id
      calendar_id: str        # which calendar this came from
      summary: str            # title (untrusted if externally_authored)
      description: str | None
      location: str | None
      start_dt: str           # ISO-8601 (Google "dateTime" or "date")
      end_dt: str
      status: str             # "confirmed" | "tentative" | "cancelled"
      attendees: list[str]    # email addresses (may include owner)
      organizer_email: str | None
      creator_email: str | None
      externally_authored: bool  # organizer_email OR creator_email != owner_email
      is_overlay_projection: bool  # True if extendedProperties.private.artemis_overlay is set
      overlay_proposal_id: str | None  # value of artemis_overlay marker, or None
      raw_json: str           # the full Google event JSON, stored as text
  ```

  **`EventCacheStore`** constructed with `(settings: Settings, key_provider: KeyProvider)`.

  `def _db_path(self) -> Path`: `paths.scope_dir(settings, OWNER_PRIVATE) / "calendar" / "event_cache.db"`.

  `def _connect(self) -> Connection`: same pattern as `PreferencesStore._connect`: `dek_for_scope(OWNER_PRIVATE)` → `ScopeLockedError` propagates; `sqlcipher_open(..., key.as_hex())`; `CREATE TABLE IF NOT EXISTS events (event_id TEXT NOT NULL, calendar_id TEXT NOT NULL, summary TEXT NOT NULL, description TEXT, location TEXT, start_dt TEXT NOT NULL, end_dt TEXT NOT NULL, status TEXT NOT NULL, attendees TEXT NOT NULL, organizer_email TEXT, creator_email TEXT, externally_authored INTEGER NOT NULL, is_overlay_projection INTEGER NOT NULL, overlay_proposal_id TEXT, raw_json TEXT NOT NULL, PRIMARY KEY (event_id, calendar_id))` and `CREATE TABLE IF NOT EXISTS sync_tokens (calendar_id TEXT PRIMARY KEY, sync_token TEXT NOT NULL)`.

  `def upsert(self, event: CachedEvent) -> None`: insert or replace the row (keyed by `(event_id, calendar_id)`); `attendees` stored as JSON-serialised `list[str]`.

  `def delete(self, event_id: str, calendar_id: str) -> None`: `DELETE FROM events WHERE event_id=? AND calendar_id=?`.

  `def get_sync_token(self, calendar_id: str) -> str | None`: returns stored token or `None` (initial sync).

  `def set_sync_token(self, calendar_id: str, token: str) -> None`: upsert the sync_tokens row.

  `def query_events(self, *, calendar_ids: list[str] | None = None, time_min: str | None = None, time_max: str | None = None, status_filter: list[str] | None = None) -> list[CachedEvent]`: SELECT + filter by the given params; exclude `status="cancelled"` by default unless `status_filter` explicitly includes it; ORDER BY `start_dt ASC`. Returns `CachedEvent` objects reconstructed from rows.

  `def clear_calendar(self, calendar_id: str) -> None`: `DELETE FROM events WHERE calendar_id=?`; `DELETE FROM sync_tokens WHERE calendar_id=?` (used before a full re-sync if `syncToken` is invalidated).

  `def invalidate(self, event_id: str, calendar_id: str) -> None`: `DELETE FROM events WHERE event_id=? AND calendar_id=?` (B4 / Seam 4: PK is `(event_id, calendar_id)` so both args are required; used by CAL-b's write-through path to evict a stale cached event after a Google write succeeds).

  ---

  **`CalendarSyncEngine`** constructed with `(client: CalendarClient, store: EventCacheStore, prefs: CalPrefs)`.

  `def _tag_externally_authored(self, event_raw: dict, owner_email: str) -> bool`: return `True` if `event_raw.get("organizer", {}).get("email")` or `event_raw.get("creator", {}).get("email")` differs from `owner_email` (case-insensitive). Events with no organizer/creator are treated as owner-authored (`False`).

  `def _parse_overlay_marker(self, event_raw: dict) -> tuple[bool, str | None]`: check `event_raw.get("extendedProperties", {}).get("private", {}).get("artemis_overlay")`; if present return `(True, value)` else `(False, None)`. Document: **events carrying this marker are own-projections from CAL-c (tentative holds); they must NOT be tagged as externally_authored even if the organizer email happens to match another account. The `is_overlay_projection` flag takes precedence — render as a hold, not as a real external event. Do not double-count in agenda or free_busy calculations.**

  `def _to_cached_event(self, event_raw: dict, calendar_id: str, owner_email: str) -> CachedEvent`: parse an event dict into `CachedEvent`. Pull `attendees` from `event_raw.get("attendees", [])` as a list of `item["email"]` values. `status` from `event_raw.get("status", "confirmed")`. `is_overlay_projection, overlay_proposal_id = _parse_overlay_marker(event_raw)`. `externally_authored = False if is_overlay_projection else _tag_externally_authored(event_raw, owner_email)`. Store full `raw_json = json.dumps(event_raw)`.

  `def sync(self, calendar_id: str, owner_email: str) -> SyncResult` where `SyncResult = dataclass { calendar_id: str, events_added: int, events_updated: int, events_deleted: int, full_sync: bool }`:

  1. `sync_token = store.get_sync_token(calendar_id)`.
  2. Determine the bounded window from `prefs`: `time_min` = `now - prefs.sync_window_months_past` months (ISO-8601 datetime), `time_max` = `now + prefs.sync_window_months_future` months.
  3. **If `sync_token` is `None` (initial sync):** paginate `client.list_events(calendar_id, time_min=time_min, time_max=time_max, show_deleted=False)` collecting all pages (follow `nextPageToken`); `store.clear_calendar(calendar_id)` before writing (idempotent full re-seed); upsert every event; record `full_sync=True`.
  4. **If `sync_token` is set (incremental sync):** call `client.list_events(calendar_id, sync_token=sync_token, show_deleted=True)` (B11 / Seam 4: `show_deleted=True` is REQUIRED so cancellations propagate — without it, cancelled events are never returned and stay in the cache forever; Google requires consistent params across the syncToken sequence); paginate; for each event: if `status == "cancelled"` → `store.delete(event_id, calendar_id)`; else → `store.upsert(event)`. If the client raises an HTTP `410 Gone` (invalidated syncToken — simulate via `InvalidSyncTokenError` from the client) → clear `sync_token`, retry as a full sync from step 3. Record `full_sync=False`.
  5. After all pages: `store.set_sync_token(calendar_id, nextSyncToken)`.
  6. Return `SyncResult`.

  `def sync_all(self, calendar_ids: list[str], owner_email: str) -> list[SyncResult]`: call `sync(cid, owner_email)` for each `calendar_id` in order; collect results.

  Define `InvalidSyncTokenError(Exception)` — raised by `FakeCalendarClient` when the injected sync token scenario calls for it; `GoogleCalendarClient` maps HTTP 410 to it.

  — done when: `uv run mypy --strict src` passes; Task 7 tests cover sync idempotency, add/update/delete, marker-skip, `externally_authored` correctness, `InvalidSyncTokenError` → full-re-sync, bounded-window on initial sync, locked-store → `ScopeLockedError`.

- [ ] Task 4: §A read tools + `FindTimeEngine` — files: `/Users/artemis-build/artemis/src/artemis/modules/calendar/read_tools.py` —

  All callables in this file read only from `EventCacheStore` (via an injected store instance) and `PreferencesStore` (via injected prefs, pre-loaded as `CalPrefs`). No direct Google API calls. Each callable is the `callable_ref` on its `ToolSpec`.

  **ADR-016 (uniform async tool-dispatch):** every tool `callable_ref` is `async def` returning a Pydantic model. So EVERY callable below (and every `CalendarTools` method in Task 5 that becomes a `callable_ref`) is declared `async def`. These read-only tools do only local cache/prefs reads (or a sync `CalendarClient` call for `list_calendars` / `find_time_with_attendees`), so their bodies contain **no `await`** — the `async def` is for signature uniformity at the single dispatch site (Brain `await spec.callable_ref(args)`). `FindTimeEngine.find_slots` is a pure helper, NOT a `callable_ref`, so it stays a plain `def`.

  **Pydantic args/return models** (define all in this file):
  ```python
  class Window(BaseModel):
      start: str  # ISO-8601 datetime or date
      end: str

  class CalendarIdsFilter(BaseModel):
      calendar_ids: list[str] | None = None  # None = all calendars

  # --- list_calendars ---
  class ListCalendarsArgs(BaseModel): pass
  class CalendarInfo(BaseModel):
      calendar_id: str; summary: str; primary: bool; access_role: str
  class ListCalendarsResult(BaseModel):
      calendars: list[CalendarInfo]

  # --- list_events ---
  class ListEventsArgs(BaseModel):
      window: Window
      calendar_ids: list[str] | None = None
      query: str | None = None  # substring filter on summary (client-side)
  class EventSummary(BaseModel):
      event_id: str; calendar_id: str; summary: str; start_dt: str; end_dt: str
      status: str; externally_authored: bool; is_overlay_projection: bool
  class ListEventsResult(BaseModel):
      events: list[EventSummary]

  # --- get_event ---
  class GetEventArgs(BaseModel):
      event_id: str; calendar_id: str
  class EventDetail(BaseModel):
      event_id: str; calendar_id: str; summary: str; description: str | None
      location: str | None; start_dt: str; end_dt: str; status: str
      attendees: list[str]; organizer_email: str | None
      externally_authored: bool; is_overlay_projection: bool; overlay_proposal_id: str | None
  class GetEventResult(BaseModel):
      event: EventDetail | None  # None if not in cache

  # --- agenda ---
  class AgendaArgs(BaseModel):
      day: str | None = None    # ISO date "YYYY-MM-DD"; None = today
      range: Window | None = None  # alternative: explicit range
  class AgendaResult(BaseModel):
      events: list[EventSummary]  # sorted by start_dt; overlays rendered as holds

  # --- next_event ---
  class NextEventArgs(BaseModel):
      calendar_ids: list[str] | None = None
  class NextEventResult(BaseModel):
      event: EventSummary | None  # None if nothing upcoming in window

  # --- search ---
  class SearchArgs(BaseModel):
      query: str
      range: Window | None = None  # None = full cache window
      calendar_ids: list[str] | None = None
  class SearchResult(BaseModel):
      events: list[EventSummary]

  # --- free_busy ---
  class FreeBusyArgs(BaseModel):
      window: Window
      calendar_ids: list[str] | None = None
  class BusyBlock(BaseModel):
      calendar_id: str; start_dt: str; end_dt: str
  class FreeBusyResult(BaseModel):
      busy_blocks: list[BusyBlock]  # sorted by start_dt; overlays EXCLUDED

  # --- find_time ---
  class FindTimeArgs(BaseModel):
      duration_minutes: int
      window: Window
      calendar_ids: list[str] | None = None
      # Optional overrides (None = use prefs)
      buffer_minutes: int | None = None
  class FreeSlot(BaseModel):
      start_dt: str; end_dt: str; duration_minutes: int
  class FindTimeResult(BaseModel):
      slots: list[FreeSlot]  # up to 10, ranked by start_dt within working hours

  # --- find_time_with_attendees ---
  class FindTimeWithAttendeesArgs(BaseModel):
      duration_minutes: int
      window: Window
      attendee_emails: list[str]  # owner is implicitly included
  class FindTimeWithAttendeesResult(BaseModel):
      slots: list[FreeSlot]

  # --- conflicts ---
  class ConflictsArgs(BaseModel):
      range: Window | None = None  # None = today + 7 days
      calendar_ids: list[str] | None = None
  class ConflictGroup(BaseModel):
      events: list[EventSummary]  # 2+ overlapping events
  class ConflictsResult(BaseModel):
      conflicts: list[ConflictGroup]
  ```

  **Callable functions** — all take `(args, *, store: EventCacheStore, prefs: CalPrefs, client: CalendarClient | None = None)` as injected dependencies (NOT as `ToolSpec.args_schema` fields — the brain passes `args`; the module wires the store/prefs at dispatch time via `functools.partial` or a `CalendarTools` class constructed with the dependencies; document this dispatch pattern clearly):

  - `async def list_calendars(args: ListCalendarsArgs, *, client: CalendarClient) -> ListCalendarsResult`: calls `client.list_calendars()` (the live calendar list is not cached, as it rarely changes and is lightweight; `CalendarClient.list_calendars` is sync per Seam 4 — body has no `await`, the `async def` is signature-uniformity per ADR-016). Parse each item to `CalendarInfo`.

  - `async def list_events(args: ListEventsArgs, *, store: EventCacheStore) -> ListEventsResult`: `store.query_events(calendar_ids=args.calendar_ids, time_min=args.window.start, time_max=args.window.end)`; if `args.query` apply a case-insensitive substring filter on `summary`. Map to `EventSummary` list.

  - `async def get_event(args: GetEventArgs, *, store: EventCacheStore) -> GetEventResult`: `store.query_events(...)` filtered by `event_id` and `calendar_id`; return the first match as `EventDetail` or `event=None`.

  - `async def agenda(args: AgendaArgs, *, store: EventCacheStore, prefs: CalPrefs) -> AgendaResult`: resolve the window (if `args.day` parse to that day's 00:00–23:59 in `prefs.timezone`; if `args.range` use it; default today in `prefs.timezone`); query cache; include overlay projections (`is_overlay_projection=True`) rendered as holds (not double-counted as real events — status="tentative" overlays are holds, not meetings).

  - `async def next_event(args: NextEventArgs, *, store: EventCacheStore, prefs: CalPrefs) -> NextEventResult`: query from now → `now + sync_window_months_future`; exclude overlays and cancelled; return the earliest upcoming event.

  - `async def search(args: SearchArgs, *, store: EventCacheStore) -> SearchResult`: query cache within range; case-insensitive substring match on `summary`, `description`, `location` (searching `description`/`location` is a client-side filter over `raw_json` fields — parse from `CachedEvent.raw_json`). **Note: `description` and `location` are attacker-controlled fields from external events; CAL-a searches them but does NOT pass them to the LLM directly. Any consumer that renders search results into an LLM prompt MUST pass `externally_authored` fields through DR-a `artemis.untrusted` (CAL-d's responsibility). Document this boundary on `SearchResult`.**

  - `async def free_busy(args: FreeBusyArgs, *, store: EventCacheStore) -> FreeBusyResult`: query cache for the window; build busy blocks from non-cancelled, non-overlay events (overlay projections are own-holds, not real meetings — exclude them from free/busy calculation to avoid self-blocking). Sort by `start_dt`.

  - **`FindTimeEngine`** — a class constructed with `(prefs: CalPrefs)`, holding the deterministic slot-finding logic (pure, no I/O). Used by both `find_time` and `find_time_with_attendees`.

    `def find_slots(self, busy_blocks: list[tuple[datetime, datetime]], window_start: datetime, window_end: datetime, duration_minutes: int, *, buffer_minutes: int | None = None) -> list[FreeSlot]`: pure algorithm — stays a plain `def` (it is NOT a `callable_ref`, just a helper the two find_time tools call internally).
    1. Use `buffer_minutes or prefs.buffer_minutes` as the padding to add before/after each busy block.
    2. Expand each busy block by buffer on both sides (clip to window bounds).
    3. Parse `prefs.working_hours_start` / `prefs.working_hours_end` and `prefs.no_meeting_before` / `prefs.no_meeting_after` in `prefs.timezone`; for each calendar day in the window, the available band is `max(working_hours_start, no_meeting_before)` to `min(working_hours_end, no_meeting_after)`.
    4. Enumerate free gaps within each day's available band that are ≥ `duration_minutes`; split at midnight boundaries.
    5. Return up to 10 slots (earliest first) as `FreeSlot` objects with `start_dt`, `end_dt` in ISO-8601.

    `async def find_time_tool(args: FindTimeArgs, *, store: EventCacheStore, prefs: CalPrefs) -> FindTimeResult` (callable_ref → `async def` per ADR-016; body has no `await` — `find_slots` is pure): query free_busy (step in this file); build `FindTimeEngine(prefs).find_slots(busy, window, args.duration_minutes, buffer_minutes=args.buffer_minutes)`.

    `async def find_time_with_attendees_tool(args: FindTimeWithAttendeesArgs, *, store: EventCacheStore, prefs: CalPrefs, client: CalendarClient) -> FindTimeWithAttendeesResult` (callable_ref → `async def` per ADR-016; calls sync `client.query_free_busy` per Seam 4, so no `await` in the body):
    1. Parse `args.window.start` / `args.window.end` as ISO-8601 datetimes.
    2. Build `items = [{"id": email} for email in [prefs.owner_email, *args.attendee_emails] if email]` (owner always included; skip `None` owner_email).
    3. `raw = client.query_free_busy(time_min, time_max, items)`.
    4. Collect all busy intervals from `raw["calendars"]` values → flatten into a `list[tuple[datetime, datetime]]`.
    5. `FindTimeEngine(prefs).find_slots(busy, window_start, window_end, args.duration_minutes)`.
    6. Return `FindTimeWithAttendeesResult(slots=slots)`.

  - `async def conflicts(args: ConflictsArgs, *, store: EventCacheStore, prefs: CalPrefs) -> ConflictsResult`: default range = today + 7 days in `prefs.timezone`; query events; find overlapping pairs (O(n²) for small n); group overlapping clusters; return `ConflictGroup` per cluster of ≥2 overlapping events.

  — done when: `uv run mypy --strict src` passes; all callables have complete type annotations; `FindTimeEngine.find_slots` with synthetic busy blocks returns expected free slots (Task 7 tests).

- [ ] Task 5: Module manifest + scope registration — files: `/Users/artemis-build/artemis/src/artemis/modules/calendar/manifest.py`, `/Users/artemis-build/artemis/src/artemis/modules/calendar/__init__.py` —

  In `manifest.py`, define a `CalendarTools` class that holds injected dependencies (`store: EventCacheStore`, `prefs_store: PreferencesStore`, `client: CalendarClient`) and exposes each read callable as a bound method (so `ToolSpec.callable_ref` captures dependencies cleanly without global state):
  ```python
  class CalendarTools:
      def __init__(self, store: EventCacheStore, prefs_store: PreferencesStore, client: CalendarClient) -> None: ...
      async def list_calendars(self, args: ListCalendarsArgs) -> ListCalendarsResult: ...
      async def list_events(self, args: ListEventsArgs) -> ListEventsResult: ...
      # ... all §A callables — EVERY bound method is `async def` (it is a ToolSpec.callable_ref; ADR-016 uniform async)
  ```
  Each method is `async def` and `await`s the corresponding (now-async) function from `read_tools.py` with the injected deps. (Bodies do no extra I/O; the `await` is just forwarding to the async callable.)

  `def make_calendar_manifest(tools: CalendarTools) -> ModuleManifest`: return a fully constructed `ModuleManifest`:
  ```python
  ModuleManifest(
      name="calendar",
      version="0.1.0",
      description="Google Calendar read/awareness, scheduling, and find_time engine.",
      data_scope=DataScope.OWNER_PRIVATE,
      tools=[
          ToolSpec(name="list_calendars", description="List all of the owner's Google calendars.",
                   args_schema=ListCalendarsArgs, return_schema=ListCalendarsResult,
                   callable_ref=tools.list_calendars, action_risk=ActionRisk.READ),
          ToolSpec(name="list_events", description="List calendar events within a time window.",
                   args_schema=ListEventsArgs, return_schema=ListEventsResult,
                   callable_ref=tools.list_events, action_risk=ActionRisk.READ),
          ToolSpec(name="get_event", description="Get full details of a single calendar event.",
                   args_schema=GetEventArgs, return_schema=GetEventResult,
                   callable_ref=tools.get_event, action_risk=ActionRisk.READ),
          ToolSpec(name="agenda", description="Render the owner's schedule for a day or date range.",
                   args_schema=AgendaArgs, return_schema=AgendaResult,
                   callable_ref=tools.agenda, action_risk=ActionRisk.READ),
          ToolSpec(name="next_event", description="Get the next upcoming calendar event.",
                   args_schema=NextEventArgs, return_schema=NextEventResult,
                   callable_ref=tools.next_event, action_risk=ActionRisk.READ),
          ToolSpec(name="search", description="Search calendar events by text query.",
                   args_schema=SearchArgs, return_schema=SearchResult,
                   callable_ref=tools.search, action_risk=ActionRisk.READ),
          ToolSpec(name="free_busy", description="Get the owner's busy blocks across calendars in a window.",
                   args_schema=FreeBusyArgs, return_schema=FreeBusyResult,
                   callable_ref=tools.free_busy, action_risk=ActionRisk.READ),
          ToolSpec(name="find_time", description="Find free time slots respecting working hours and buffers.",
                   args_schema=FindTimeArgs, return_schema=FindTimeResult,
                   callable_ref=tools.find_time, action_risk=ActionRisk.READ),
          ToolSpec(name="find_time_with_attendees",
                   description="Find mutually free slots across the owner and attendees via FreeBusy.",
                   args_schema=FindTimeWithAttendeesArgs, return_schema=FindTimeWithAttendeesResult,
                   callable_ref=tools.find_time_with_attendees, action_risk=ActionRisk.READ),
          ToolSpec(name="conflicts", description="Detect double-bookings and overlapping events.",
                   args_schema=ConflictsArgs, return_schema=ConflictsResult,
                   callable_ref=tools.conflicts, action_risk=ActionRisk.READ),
      ],
      proactive_hooks=[],   # CAL-c adds hooks; empty here
  )
  ```

  In `__init__.py`: register scopes at module import time (U4: `calendar.events` write scope removed — belongs to CAL-b):
  ```python
  from artemis.integrations.google.scopes import register_google_scopes
  register_google_scopes("calendar", {
      "https://www.googleapis.com/auth/calendar.readonly",
  })
  ```
  Re-export `make_calendar_manifest`, `CalendarTools`, `CalendarSyncEngine`, `EventCacheStore`, `PreferencesStore`, `CalPrefs`, `CalendarClient`, `GoogleCalendarClient`, `FakeCalendarClient`.

  — done when: `uv run mypy --strict src` passes; `from artemis.modules.calendar import make_calendar_manifest` succeeds; `register_google_scopes` is called with the two calendar scopes on import.

- [ ] Task 6: (Optional Module registration) — files: (none new) — document in `__init__.py` that the caller (e.g. the composition root `compose_brain` in M1-c) must construct a `CalendarTools` instance and call `make_calendar_manifest(tools)` then `registry.register(manifest)` to activate the calendar module. CAL-a does NOT auto-register (no global singleton with live credentials); the composition root owns wiring. Leave a `# TODO(CAL-b): compose_brain wiring` comment in `__init__.py`. This task has no new files; it is a documentation-only task — done when the `__init__.py` comment exists.

- [ ] Task 7: Off-hardware tests (fakes only) — files: `/Users/artemis-build/artemis/tests/test_calendar_read.py` —

  Typed pytest. Any test that invokes a `CalendarTools` method / read-tool `callable_ref` directly must `await` it (they are `async def` per ADR-016) and the test is an `async def` under `pytest.mark.asyncio`. `FindTimeEngine.find_slots` stays a plain sync call (it is not a callable_ref). Use `FakeCalendarClient`, `FakeKeyProvider` (from M2-b), in-memory shims for stores (define `FakePreferencesStore` and `FakeCacheStore` as simple dict-backed implementations of the same interface, NOT using SQLCipher — used for all functional tests; the real SQLCipher round-trips are gated in Task 8).

  **`FakePreferencesStore`**: holds a `CalPrefs` attr, `load()` returns it, `save(p)` updates it, `update(**kw)` applies `dataclasses.replace`.

  **`FakeCacheStore`**: holds `events: dict[tuple[str,str], CachedEvent]` + `sync_tokens: dict[str, str]`. Implements `upsert`, `delete`, `get_sync_token`, `set_sync_token`, `query_events`, `clear_calendar` with correct semantics.

  Test cases:

  **Port conformance:**
  - Static assertion: `_c: CalendarClient = FakeCalendarClient([], {}, {})` type-checks.

  **Sync idempotency:**
  - `sync(calendar_id, owner_email)` twice with the same events: second call uses the stored syncToken and returns an incremental result with 0 adds/updates/deletes.

  **Sync add/update/delete:**
  - Initial sync seeds 3 events; incremental sync adds 1, updates 1 (same event_id, changed summary), deletes 1 (status="cancelled"): final cache has 3 events (original 3 - 1 deleted + 1 new, 1 updated in-place).

  **`InvalidSyncTokenError` → full re-sync:**
  - Configure `FakeCalendarClient` to raise `InvalidSyncTokenError` on the first incremental call; assert `CalendarSyncEngine.sync` clears the token and re-seeds from scratch (`full_sync=True`).

  **`artemis_overlay` marker recognition:**
  - An event with `extendedProperties.private.artemis_overlay="prop-123"` syncs into the cache with `is_overlay_projection=True`, `externally_authored=False` (even if organizer_email ≠ owner_email), `overlay_proposal_id="prop-123"`.
  - An overlay event does NOT appear in `free_busy` results.
  - An overlay event DOES appear in `agenda` results as a hold (is_overlay_projection=True).

  **`externally_authored` correctness:**
  - An event with `organizer.email == owner_email` → `externally_authored=False`.
  - An event with `organizer.email != owner_email` → `externally_authored=True`.
  - An event that is an overlay projection → `externally_authored=False` regardless of organizer.

  **Bounded window on initial sync:**
  - Verify `list_events` is called with `time_min` and `time_max` derived from `prefs.sync_window_months_past` and `prefs.sync_window_months_future` (assert the FakeCalendarClient received those params).

  **Locked store → `ScopeLockedError`:**
  - `EventCacheStore(settings, FakeKeyProvider(owner_unlocked=False)).query_events()` raises `ScopeLockedError`.
  - (Note: this test requires a real-enough `EventCacheStore._connect` path reachable with a fake key provider; if SQLCipher isn't importable off-hardware, mock `sqlcipher_open` to raise `ScopeLockedError` when `dek_for_scope` would, and test at the `_connect` level.)

  **`find_time` honors working hours/buffers/no-meeting windows:**
  - `FindTimeEngine(prefs)` with `working_hours_start="09:00"`, `working_hours_end="17:00"`, `buffer_minutes=15`, `no_meeting_before="10:00"`: a busy block 10:00–11:00 → no slot starting before 11:15 and no slot before 10:00; verify at least one slot returned ≥ 60 min in the 11:15–17:00 band.
  - Edge: duration > available band → `slots == []`.
  - `no_meeting_after` clips end of day.

  **FreeBusy intersection (find_time_with_attendees):**
  - `FakeCalendarClient.query_free_busy` returns two attendees each busy in non-overlapping windows; verify the returned slots are only in the gaps outside BOTH busy sets.
  - Owner's own busy blocks (from the FreeBusy response) are included in the intersection.

  **Multi-calendar:**
  - `list_events` with `calendar_ids=["cal1","cal2"]` returns events from both; with `calendar_ids=["cal1"]` returns only cal1 events.

  **`search` text filter:**
  - A case-insensitive substring search on `summary` returns matching events; non-matching events are excluded.

  — done when: `uv run pytest -q tests/test_calendar_read.py` passes AND `uv run mypy --strict src tests/test_calendar_read.py` passes AND `uv run ruff check . && uv run ruff format --check .` both exit 0.

- [ ] Task 8 (GATED — on-hardware / owner-present): Real Google sync + real SQLCipher stores + real FreeBusy — files: (uses Tasks 1–5) — on the Mini, with the M8-a refresh token stored, the vault unlocked, `GOOGLE_OAUTH_CLIENT_ID`/`SECRET` from Keychain:

  (a) Construct `GoogleCalendarClient(credentials_factory)` and call `list_calendars()` — verify it returns at least the `primary` calendar. Record the primary calendar's `id` (it is the owner email address for the Google API).

  (b) Set `owner_email` in preferences from step (a).

  (c) Run `CalendarSyncEngine.sync(primary_calendar_id, owner_email)` with real `PreferencesStore` + real `EventCacheStore` (both opened under the broker-mounted vault via real SQLCipher). Confirm rows land in the real `event_cache.db`. Confirm the db is SQLCipher-encrypted (a wrong key fails to open; the file is not plaintext-readable).

  (d) Run `PreferencesStore.save(CalPrefs(timezone="Asia/Singapore"))` + `load()` — confirm round-trip under real SQLCipher.

  (e) Run an incremental sync (second call): confirm it uses the stored `syncToken` and returns `full_sync=False`.

  (f) Run `find_time_with_attendees_tool` with the owner's own email as an attendee against the real FreeBusy API; confirm a non-empty (or empty if fully booked) `slots` list is returned without error.

  (g) Confirm `externally_authored` is set correctly on events with external organizers in the real event feed.

  — done when: (a)–(g) verified on the Mini and recorded in handoff.

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | /Users/artemis-build/artemis/src/artemis/modules/__init__.py (if absent), /Users/artemis-build/artemis/src/artemis/modules/calendar/__init__.py, /Users/artemis-build/artemis/src/artemis/modules/calendar/manifest.py, /Users/artemis-build/artemis/src/artemis/modules/calendar/client.py, /Users/artemis-build/artemis/src/artemis/modules/calendar/preferences.py, /Users/artemis-build/artemis/src/artemis/modules/calendar/cache.py, /Users/artemis-build/artemis/src/artemis/modules/calendar/read_tools.py, /Users/artemis-build/artemis/tests/test_calendar_read.py |
| Modify | (none — pyproject.toml unchanged; all deps already present from M8-a) |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict src tests/test_calendar_read.py` | Type gate |
| `uv run ruff check . && uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q tests/test_calendar_read.py` | Test gate (fakes only; no network; no real SQLCipher) |
| `uv run python -c "from artemis.modules.calendar import make_calendar_manifest; print('ok')"` | Import smoke |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | src/artemis/modules/**, tests/test_calendar_read.py |
| `git commit` | "feat: CAL-a calendar read/awareness tools, find_time engine, preferences store, incremental-sync read-cache" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_ENV_FILE` / `ARTEMIS_DATA_ROOT` / `ARTEMIS_SLOT` | Settings + per-scope store path resolution (M0-a) |
| `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` | GATED on-hardware only (real Google round-trips); never used off-hardware |

### Network
| Action | Purpose |
|--------|---------|
| HTTPS to `www.googleapis.com` (GATED, on-Mini only) | Real Google Calendar API + FreeBusy. Off-hardware: `FakeCalendarClient` used; no outbound calls. |

## Specialist Context
### Security
CAL-a stores and returns content that is **attacker-controllable at the data-source level** (event titles, descriptions, locations, attendee display names written by external parties). The module's security boundary is:

1. **`externally_authored` provenance tag** is the chokepoint. Every event with `organizer_email` or `creator_email` ≠ `owner_email` is tagged `externally_authored=True` at ingest. The tag is cached with the event and returned in every result type. **CAL-a only stores and tags; it does NOT quarantine.** Any consumer passing externally-authored event text to the LLM MUST route through DR-a `artemis.untrusted` (spotlight + dual-LLM quarantine) — this is CAL-d's responsibility. **Security-review focus: confirm every code path that could render event text (title/description/location) into an LLM prompt goes through DR-a, including the brain's direct rendering of a `list_events` result. If a direct rendering path bypasses DR-a, flag it.**

2. **`is_overlay_projection` takes precedence** over `externally_authored`. A CAL-c projected hold carries `extendedProperties.private.artemis_overlay`; CAL-a recognises this and sets `externally_authored=False` to prevent own-projections from being quarantined as if they were foreign. The marker is a string the owner's own Artemis writes; it is trusted.

3. **Both SQLCipher stores open only under the broker-delivered owner DEK** via `KeyProvider.dek_for_scope(OWNER_PRIVATE)` → `ScopeLockedError` propagates on locked vault (no data access). The `key.as_hex()` value is used only within `_connect()` local scope, never assigned to `self`. The raw event text and preferences are stored encrypted at rest.

4. **Refresh token / credentials**: CAL-a never touches the refresh token. It calls `GoogleCredentialsFactory.authorized_credentials()` once per `GoogleCalendarClient` instance and does not log the returned `Credentials` object. On `ReauthRequiredError` it propagates without crashing hooks.

5. **FreeBusy is a read-only operation** (no data written to Google); the attendee emails passed to `query_free_busy` are owner-controlled inputs (typed args). No event text from attendees reaches the LLM via CAL-a's tools.

6. **`raw_json` stored in cache**: the full event JSON (including untrusted fields) is stored in the encrypted cache. It is not passed to the LLM directly by CAL-a; consumers of `CachedEvent.raw_json` must treat it as untrusted.

[Specialist security review should confirm: (a) the `externally_authored` tag covers every externally-sourced field path; (b) no CAL-a tool returns a direct LLM-consumable string of untrusted event text (all results are structured Pydantic models, not free-form strings); (c) the `is_overlay_projection` bypass does not create a spoofing vector (an external event falsely carrying the `artemis_overlay` marker would be treated as trusted — this is acceptable because writing arbitrary `extendedProperties.private` to a Google Calendar event requires write access to that calendar, which means the attacker already has owner-level Google access).]

### Performance
- **Cache is the hot path**: all §A tools except `list_calendars` and `find_time_with_attendees` read only the local SQLCipher cache — no network per tool call. The SQLCipher open is per-call (inside `_connect()`); the broker DEK cache in M2-c ensures `dek_for_scope` does not re-hit the enclave per call.
- **Sync is the write path**: `sync()` paginates Google events and does a batched upsert to SQLCipher. Pagination with `max_results=250` per page. On-hardware sizing and throughput are a build-time spike (Task 8).
- **`FindTimeEngine.find_slots`** is O(n × days) over busy blocks for a bounded window. For the default ±12-month window the day count is ≤730 and busy blocks ≤ a few thousand — negligible.
- **`find_time_with_attendees`** makes one FreeBusy API call per invocation; no pagination (FreeBusy is a single query). Keep `attendee_emails` to a reasonable size (document: max 50 items per FreeBusy request per Google API limits).

### Accessibility
(none — no frontend; all tools are headless data providers)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | src/artemis/modules/calendar/*.py | Type + docstring all exports; document `externally_authored` tag boundary (CAL-a tags, CAL-d quarantines); `is_overlay_projection` semantics; `ScopeLockedError` propagation; vault-path reconciliation deferral; `raw_json` untrusted note |
| Inline | src/artemis/modules/calendar/read_tools.py | Document on `SearchResult` that `description`/`location` fields are untrusted when `externally_authored=True` and must not be passed to the LLM without DR-a |
| Inline | src/artemis/modules/calendar/cache.py | Document `_parse_overlay_marker` semantics + the spoofing-boundary note (attacker with write access to the calendar = already owner-level) |

## Acceptance Criteria
- [ ] Run `uv run mypy --strict src tests/test_calendar_read.py` → verify: exit 0, no errors.
- [ ] Run `uv run pytest -q tests/test_calendar_read.py` → verify: sync idempotency passes; add/update/delete semantics pass; `InvalidSyncTokenError` → full-re-sync passes; overlay marker recognition + `externally_authored=False` on overlays passes; `externally_authored=True` on external organizers passes; `free_busy` excludes overlays; `find_time` honors working hours + buffers + `no_meeting_before`/`after`; FreeBusy intersection (multi-attendee) returns only mutual free gaps; multi-calendar list_events filter passes; locked store raises `ScopeLockedError`.
- [ ] Run `uv run python -c "from artemis.modules.calendar import make_calendar_manifest; m = make_calendar_manifest.__doc__ or 'ok'; print('ok')"` → verify: exit 0 (module is importable; scopes are registered on import).
- [ ] Run `uv run python -c "from artemis.integrations.google.scopes import required_scopes; scopes = ' '.join(required_scopes()); print('calendar.readonly' in scopes, 'calendar.events' not in scopes)"` → verify: prints `True True` (readonly scope present; write scope NOT registered by CAL-a — U4).
- [ ] Run `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.
- [ ] (GATED, on Mini, owner-present) Real `calendarList.list` succeeds; real incremental sync stores encrypted rows in owner-private SQLCipher vault; wrong key fails to open; `find_time_with_attendees` executes a real FreeBusy call and returns results; `externally_authored` correctly tagged on real event feed → verify recorded in handoff.

## Progress
_(Coding mode writes here — do not edit manually)_
