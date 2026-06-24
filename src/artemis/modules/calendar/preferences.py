"""Owner-private Calendar preferences store.

The store persists one small JSON record under the owner-private SQLCipher
scope. ``key.as_hex()`` is kept local to ``_connect`` and
``ScopeLockedError`` propagates when the owner scope is locked.
"""

from __future__ import annotations

import dataclasses
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from artemis import paths
from artemis.config import Settings
from artemis.data.sqlcipher import sqlcipher_open
from artemis.identity.key_provider import KeyProvider
from artemis.identity.scope import OWNER_PRIVATE


@dataclass(frozen=True)
class CalPrefs:
    """Calendar preferences used by sync, read tools, and scheduling.

    ``working_days`` and ``preferred_focus_window`` mirror X3 runtime-config
    defaults so ``CalPrefs()`` is valid off-hardware. The real composition root
    should overlay ``get_runtime_config().calendar`` values with
    ``dataclasses.replace`` after loading. Validation of those fields belongs to
    X3; this dataclass trusts owner-authored runtime config.
    """

    working_hours_start: str = "09:00"
    working_hours_end: str = "18:00"
    timezone: str = "UTC"
    default_write_calendar: str = "primary"
    buffer_minutes: int = 15
    no_meeting_before: str = "09:00"
    no_meeting_after: str = "18:00"
    default_reminder_minutes: int = 10
    focus_block_duration_minutes: int = 90
    sync_window_months_past: int = 12
    sync_window_months_future: int = 12
    owner_email: str | None = None
    working_days: tuple[int, ...] = (0, 1, 2, 3, 4)
    preferred_focus_window: tuple[str, str] = ("09:00", "12:00")


class PreferencesStore:
    """SQLCipher-backed owner-private single-row preferences store."""

    def __init__(self, settings: Settings, key_provider: KeyProvider) -> None:
        self._settings = settings
        self._key_provider = key_provider

    def _db_path(self) -> Path:
        """Return the dev path; Mini vault-path reconciliation is deferred."""
        return paths.scope_dir(self._settings, OWNER_PRIVATE) / "calendar" / "preferences.db"

    def _connect(self) -> sqlite3.Connection:
        key = self._key_provider.dek_for_scope(OWNER_PRIVATE)
        db_path = self._db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        key_hex = key.as_hex()
        conn = sqlcipher_open(db_path, key_hex)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS prefs ("
            "id INTEGER PRIMARY KEY CHECK (id=1), "
            "data TEXT NOT NULL)"
        )
        return conn

    def load(self) -> CalPrefs:
        """Load preferences, filtering unknown future JSON keys."""
        with self._connect() as conn:
            row = conn.execute("SELECT data FROM prefs WHERE id=1").fetchone()
        if row is None:
            return CalPrefs()
        raw = json.loads(str(row[0]))
        if not isinstance(raw, dict):
            return CalPrefs()
        known = {field.name for field in dataclasses.fields(CalPrefs)}
        filtered = {key: value for key, value in raw.items() if key in known}
        if "working_days" in filtered:
            filtered["working_days"] = tuple(filtered["working_days"])
        if "preferred_focus_window" in filtered:
            filtered["preferred_focus_window"] = tuple(filtered["preferred_focus_window"])
        return CalPrefs(**filtered)

    def save(self, prefs: CalPrefs) -> None:
        """Persist all preferences as one JSON blob."""
        data = json.dumps(dataclasses.asdict(prefs))
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO prefs (id, data) VALUES (1, ?) "
                "ON CONFLICT(id) DO UPDATE SET data=excluded.data",
                (data,),
            )

    def update(self, **kwargs: object) -> CalPrefs:
        """Replace known fields and reject unknown preference names."""
        known = {field.name for field in dataclasses.fields(CalPrefs)}
        for key in kwargs:
            if key not in known:
                raise ValueError(f"unknown pref field: {key}")
        updated = dataclasses.replace(self.load(), **kwargs)  # type: ignore[arg-type]
        self.save(updated)
        return updated
