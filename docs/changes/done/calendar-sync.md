# calendar-sync — windowed calendar fetcher capability (Wave 2c)

**Identity:** A spec-built fetcher capability that syncs the next 7 days of Google Calendar events
into the local store, emitting `{domain:"calendar", rows:[...]}` on stdout. Adapts
`today-calendar`'s Google-calling logic (reused, not rewritten); leaves `today-calendar` intact as
the on-demand invoke fallback. ADR-046 #1 · owner decision 2026-07-03 (adapt, spec-built).

Differences from `today-calendar`: (1) a **7-day window** not today-only (fixes live-smoke Finding D
— date-specific asks get real data); (2) **rows output** (`{domain, rows}` JSON) not formatted text;
(3) each row keyed by the **Google event id** so re-syncs upsert (not duplicate), with `text`
carrying the **date + time** so the read-path phraser can answer date-specific asks. The row
`payload` holds structured fields (never fed to an LLM); `text` is the untrusted display string the
ingest quarantine sanitizes.

## Files to change
| Op | Path |
|----|------|
| create | `capabilities/library/calendar-sync/SKILL.md` |
| create | `capabilities/library/calendar-sync/tool.py` |
| create | `capabilities/library/calendar-sync/sandbox_policy.json` |
| create | `capabilities/library/calendar-sync/tests/test_skill.py` |
| create | `tests/data/test_calendar_sync.py` |

(A self-contained capability bundle = 4 files + 1 host contract test; inherent to a new capability.)

## Exact changes

### Task 1 — `capabilities/library/calendar-sync/SKILL.md` (create)
```markdown
---
name: calendar-sync
description: Syncs upcoming Google Calendar events into the local store.
version: 1
tags: []
uses: []
secrets: []
inputs:
- name: calendar_id
  type: string
  description: Google Calendar ID to read; use primary for the main calendar.
  required: false
- name: timezone_name
  type: string
  description: Optional IANA timezone such as America/New_York; defaults to the runtime local timezone.
  required: false
- name: days_ahead
  type: integer
  description: How many days ahead to sync (default 7).
  required: false
goal: 'Keep the local calendar domain synced with upcoming Google Calendar events.'
built_at: '2026-07-03T00:00:00+00:00'
auth_status: not-required
oauth_scopes:
- https://www.googleapis.com/auth/calendar.readonly
---

Fetches the next N days (default 7) of events from Google Calendar using Artemis-provided Google
OAuth and emits them as a JSON row set ({"domain":"calendar","rows":[...]}) for the local data
spine to ingest. Read-only; one-way sync (never writes back to Google).
```

### Task 2 — `capabilities/library/calendar-sync/tool.py` (create)
Self-contained stdlib module. Reuse `today-calendar/tool.py`'s HTTP + timezone helpers
(`_request_json`, `_display_timezone`, platform-safe time formatting) and adapt to a window + rows.
Full module:

```python
"""Sync upcoming Google Calendar events as JSON rows for the local data spine.

Self-contained (stdlib only). Artemis injects a Google Calendar OAuth access token in
GOOGLE_ACCESS_TOKEN at runtime. Emits {"domain":"calendar","rows":[...]} on stdout.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

GOOGLE_CALENDAR_EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events"


def _display_timezone(timezone_name: str | None) -> timezone | ZoneInfo:
    if timezone_name is None or timezone_name.strip() == "":
        return datetime.now().astimezone().tzinfo or timezone.utc
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown IANA timezone: {timezone_name}") from exc


def window_bounds(days_ahead: int, timezone_name: str | None = None) -> tuple[datetime, datetime]:
    """Start of today through the end of the day `days_ahead` days out, in the display tz."""
    tz = _display_timezone(timezone_name)
    today = datetime.now(tz).date()
    start = datetime.combine(today, time.min, tzinfo=tz)
    end = datetime.combine(today + timedelta(days=max(0, days_ahead)), time.max, tzinfo=tz)
    return start, end


def _fmt_time(dt: datetime) -> str:
    return dt.strftime("%#I:%M %p") if os.name == "nt" else dt.strftime("%-I:%M %p")


def _labels(start: dict[str, str], end: dict[str, str], display_tz: timezone | ZoneInfo) -> tuple[str, str, bool]:
    """Return (date_label, time_label, all_day)."""
    if "date" in start:
        d = date.fromisoformat(start["date"])
        return d.strftime("%a %d %b %Y"), "All day", True
    raw = start.get("dateTime")
    if not raw:
        return "Unknown date", "Unknown time", False
    sdt = datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(display_tz)
    date_label = sdt.strftime("%a %d %b %Y")
    end_raw = end.get("dateTime")
    if end_raw:
        edt = datetime.fromisoformat(end_raw.replace("Z", "+00:00")).astimezone(display_tz)
        return date_label, f"{_fmt_time(sdt)}–{_fmt_time(edt)}", False
    return date_label, _fmt_time(sdt), False


def event_to_row(item: dict[str, Any], display_tz: timezone | ZoneInfo) -> dict[str, Any]:
    summary = str(item.get("summary") or "Untitled event")
    start = item.get("start", {}) or {}
    end = item.get("end", {}) or {}
    location_value = item.get("location")
    location = str(location_value) if location_value else None
    date_label, time_label, all_day = _labels(start, end, display_tz)
    text = f"{date_label}, {time_label}: {summary}" + (f" ({location})" if location else "")
    key = str(item.get("id") or f"{date_label}-{summary}")
    return {
        "kind": "event",
        "key": key,
        "payload": {
            "summary": summary,
            "start": start,
            "end": end,
            "location": location,
            "all_day": all_day,
        },
        "text": text,
    }


def build_rows(items: list[dict[str, Any]], timezone_name: str | None = None) -> list[dict[str, Any]]:
    display_tz = _display_timezone(timezone_name)
    return [event_to_row(item, display_tz) for item in items]


def _request_json(url: str, token: str, timeout_seconds: float = 20.0) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Google Calendar API error {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach Google Calendar API: {exc.reason}") from exc
    decoded = json.loads(body)
    if not isinstance(decoded, dict):
        raise RuntimeError("Google Calendar API returned an unexpected response.")
    return decoded


def fetch_window_events(
    calendar_id: str = "primary", timezone_name: str | None = None, days_ahead: int = 7
) -> list[dict[str, Any]]:
    token = os.environ.get("GOOGLE_ACCESS_TOKEN")
    if not token:
        raise RuntimeError("GOOGLE_ACCESS_TOKEN is required at runtime.")
    start, end = window_bounds(days_ahead, timezone_name)
    encoded_calendar_id = urllib.parse.quote(calendar_id, safe="")
    params = {
        "timeMin": start.isoformat(),
        "timeMax": end.isoformat(),
        "singleEvents": "true",
        "orderBy": "startTime",
    }
    if timezone_name:
        params["timeZone"] = timezone_name
    query = urllib.parse.urlencode(params)
    url = GOOGLE_CALENDAR_EVENTS_URL.format(calendar_id=encoded_calendar_id) + "?" + query
    payload = _request_json(url, token)
    items = payload.get("items", [])
    if not isinstance(items, list):
        raise RuntimeError("Google Calendar API returned invalid event data.")
    return items


def main(argv: list[str] | None = None) -> int:
    # Artemis delivers all declared inputs as a single JSON object string in argv[1].
    raw = list(sys.argv[1:] if argv is None else argv)
    data: dict[str, Any] = {}
    if raw:
        try:
            loaded = json.loads(raw[0])
            if isinstance(loaded, dict):
                data = loaded
        except (ValueError, TypeError):
            data = {}
    calendar_id = str(data.get("calendar_id") or "primary")
    timezone_name = data.get("timezone_name") or None
    try:
        days_ahead = int(data.get("days_ahead") or 7)
    except (ValueError, TypeError):
        days_ahead = 7
    items = fetch_window_events(
        calendar_id=calendar_id, timezone_name=timezone_name, days_ahead=days_ahead
    )
    rows = build_rows(items, timezone_name=timezone_name)
    print(json.dumps({"domain": "calendar", "rows": rows}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

### Task 3 — `capabilities/library/calendar-sync/sandbox_policy.json` (create)
Identical to `today-calendar`'s:
```json
{
  "egress_domains": [
    "www.googleapis.com"
  ],
  "memory_mb": 512,
  "cpu_pct": 100,
  "pids_max": 128,
  "timeout_s": 60
}
```

### Task 4 — `capabilities/library/calendar-sync/tests/test_skill.py` (create)
Hermetic (no network), `from tool import ...` (mirrors `today-calendar/tests/test_skill.py`):
```python
from datetime import timezone

from tool import build_rows, event_to_row


def test_event_to_row_timed_carries_date_and_time():
    row = event_to_row(
        {
            "id": "abc123",
            "summary": "Standup",
            "start": {"dateTime": "2026-08-22T09:00:00+00:00"},
            "end": {"dateTime": "2026-08-22T09:30:00+00:00"},
            "location": "Zoom",
        },
        timezone.utc,
    )
    assert row["kind"] == "event"
    assert row["key"] == "abc123"
    assert "22 Aug 2026" in row["text"]
    assert "Standup" in row["text"] and "(Zoom)" in row["text"]
    assert row["payload"]["all_day"] is False


def test_event_to_row_all_day():
    row = event_to_row(
        {"id": "d1", "summary": "Holiday", "start": {"date": "2026-08-22"}, "end": {"date": "2026-08-23"}},
        timezone.utc,
    )
    assert row["payload"]["all_day"] is True
    assert "All day" in row["text"] and "22 Aug 2026" in row["text"]


def test_build_rows_multiple():
    rows = build_rows(
        [
            {"id": "a", "summary": "A", "start": {"dateTime": "2026-08-22T09:00:00+00:00"}, "end": {"dateTime": "2026-08-22T10:00:00+00:00"}},
            {"id": "b", "summary": "B", "start": {"date": "2026-08-23"}, "end": {"date": "2026-08-24"}},
        ],
        "UTC",
    )
    assert [r["key"] for r in rows] == ["a", "b"]
```

### Task 5 — `tests/data/test_calendar_sync.py` (create) — HOST CONTRACT TEST
Loads the capability's `tool.py` by path (it is not a package) and asserts its output parses as the
ingest contract `FetcherOutput`. This runs in the main suite (regression protection):
```python
import importlib.util
import io
import json
from contextlib import redirect_stdout
from pathlib import Path

from artemis.data.ingest import FetcherOutput

_TOOL = Path("capabilities/library/calendar-sync/tool.py")


def _load_tool():
    spec = importlib.util.spec_from_file_location("calendar_sync_tool", _TOOL)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_main_output_conforms_to_fetcher_contract(monkeypatch):
    mod = _load_tool()
    # Avoid network + token: stub the fetch to return two raw Google items.
    monkeypatch.setattr(
        mod,
        "fetch_window_events",
        lambda **_: [
            {"id": "a", "summary": "Standup", "start": {"dateTime": "2026-08-22T09:00:00+00:00"}, "end": {"dateTime": "2026-08-22T09:30:00+00:00"}},
            {"id": "b", "summary": "Holiday", "start": {"date": "2026-08-23"}, "end": {"date": "2026-08-24"}},
        ],
    )
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = mod.main(["{}"])
    assert rc == 0
    parsed = FetcherOutput.model_validate_json(buf.getvalue())  # must satisfy the ingest contract
    assert parsed.domain == "calendar"
    assert [r.key for r in parsed.rows] == ["a", "b"]
    assert "22 Aug 2026" in parsed.rows[0].text
```

## Acceptance criteria
1. `event_to_row` produces `{kind,key,payload,text}` with the Google event id as key and the date+time in `text`, for timed and all-day events. → capability `test_skill.py`
2. `main` prints `{"domain":"calendar","rows":[...]}` that validates as `artemis.data.ingest.FetcherOutput`, with rows keyed by event id and `text` carrying the date. → `tests/data/test_calendar_sync.py`
3. Whole-project `uv run mypy src/` clean, `uv run ruff check` + `ruff format --check` clean on new files, full host suite green.
4. The capability's own hermetic tests pass.

## Commands to run
```
uv run ruff check src/ tests/ capabilities/library/calendar-sync/
uv run ruff format --check capabilities/library/calendar-sync/ tests/data/test_calendar_sync.py
uv run mypy src/
uv run pytest -q tests/data/test_calendar_sync.py
(cd capabilities/library/calendar-sync && uv run pytest tests/ -q)
uv run pytest -q
```
