import importlib.util
import io
from contextlib import redirect_stdout
from pathlib import Path

from artemis.data.ingest import FetcherOutput

_TOOL = Path("capabilities/builtin/calendar-sync/tool.py")


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
            {
                "id": "a",
                "summary": "Standup",
                "start": {"dateTime": "2026-08-22T09:00:00+00:00"},
                "end": {"dateTime": "2026-08-22T09:30:00+00:00"},
            },
            {
                "id": "b",
                "summary": "Holiday",
                "start": {"date": "2026-08-23"},
                "end": {"date": "2026-08-24"},
            },
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
