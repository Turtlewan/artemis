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


def _labels(
    start: dict[str, str], end: dict[str, str], display_tz: timezone | ZoneInfo
) -> tuple[str, str, bool]:
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
        return date_label, f"{_fmt_time(sdt)}-{_fmt_time(edt)}", False
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


def build_rows(
    items: list[dict[str, Any]], timezone_name: str | None = None
) -> list[dict[str, Any]]:
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
