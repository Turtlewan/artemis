"""Checkpoint implementations for spine run state."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol, runtime_checkable

from artemis.spine.types import RunState


@runtime_checkable
class Checkpoint(Protocol):
    def save(self, task_id: str, state: RunState, data: dict) -> None:  # type: ignore[type-arg]
        """Save the latest task snapshot."""
        ...

    def load(self, task_id: str) -> dict | None:  # type: ignore[type-arg]
        """Load the latest task snapshot, if any."""
        ...


class InMemoryCheckpoint:
    def __init__(self) -> None:
        self._snapshots: dict[str, dict] = {}  # type: ignore[type-arg]

    def save(self, task_id: str, state: RunState, data: dict) -> None:  # type: ignore[type-arg]
        self._snapshots[task_id] = {"state": state, "data": data}

    def load(self, task_id: str) -> dict | None:  # type: ignore[type-arg]
        return self._snapshots.get(task_id)


class JsonFileCheckpoint:
    def __init__(self, dir: Path) -> None:
        self._dir = dir
        self._dir.mkdir(parents=True, exist_ok=True)

    def save(self, task_id: str, state: RunState, data: dict) -> None:  # type: ignore[type-arg]
        path = self._path(task_id)
        path.write_text(json.dumps({"state": state, "data": data}), encoding="utf-8")

    def load(self, task_id: str) -> dict | None:  # type: ignore[type-arg]
        path = self._path(task_id)
        if not path.exists():
            return None
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            return loaded
        return None

    def _path(self, task_id: str) -> Path:
        return self._dir / f"{task_id}.json"
