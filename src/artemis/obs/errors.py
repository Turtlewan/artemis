"""Local append-only error capture for observability sinks."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from artemis.obs.logging import get_logger, redact


@dataclass(frozen=True)
class ErrorRecord:
    """A redacted error record with no traceback or raw content."""

    component: str
    error_type: str
    message: str
    at: datetime


class ErrorStore:
    """Append-only JSONL store for redacted error records."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def append(self, rec: ErrorRecord) -> None:
        """Append one JSON line, flush it, and fsync the file."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(rec)
        payload["at"] = rec.at.isoformat()
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def list(self) -> list[ErrorRecord]:
        """Read all complete records, tolerating a trailing partial line."""
        if not self._path.exists():
            return []
        records: list[ErrorRecord] = []
        with self._path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    payload = json.loads(line)
                    records.append(
                        ErrorRecord(
                            component=str(payload["component"]),
                            error_type=str(payload["error_type"]),
                            message=str(payload["message"]),
                            at=datetime.fromisoformat(str(payload["at"])),
                        )
                    )
                except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                    continue
        return records


class ErrorCaptureSink:
    """Observability sink that records local redacted errors only."""

    def __init__(self, store: ErrorStore) -> None:
        self._store = store

    def on_route_decision(
        self,
        task_class_key: str,
        confidence: float,
        path: str,
        *,
        now: datetime,
    ) -> None:
        pass

    def on_escalation(
        self,
        task_class_key: str,
        *,
        is_cloud_safe: bool,
        now: datetime,
    ) -> None:
        pass

    def on_error(self, component: str, exc: BaseException, *, now: datetime) -> None:
        msg = str(redact(str(exc)))[:500]
        self._store.append(
            ErrorRecord(
                component=component,
                error_type=type(exc).__name__,
                message=msg,
                at=now,
            )
        )
        get_logger(component).error("captured", extra={"error_type": type(exc).__name__})
