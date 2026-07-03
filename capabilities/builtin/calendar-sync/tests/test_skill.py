import sys
from datetime import timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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
        {
            "id": "d1",
            "summary": "Holiday",
            "start": {"date": "2026-08-22"},
            "end": {"date": "2026-08-23"},
        },
        timezone.utc,
    )
    assert row["payload"]["all_day"] is True
    assert "All day" in row["text"] and "22 Aug 2026" in row["text"]


def test_build_rows_multiple():
    rows = build_rows(
        [
            {
                "id": "a",
                "summary": "A",
                "start": {"dateTime": "2026-08-22T09:00:00+00:00"},
                "end": {"dateTime": "2026-08-22T10:00:00+00:00"},
            },
            {
                "id": "b",
                "summary": "B",
                "start": {"date": "2026-08-23"},
                "end": {"date": "2026-08-24"},
            },
        ],
        "UTC",
    )
    assert [r["key"] for r in rows] == ["a", "b"]
