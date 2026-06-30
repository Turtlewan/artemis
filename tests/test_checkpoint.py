from __future__ import annotations

from pathlib import Path

from artemis.spine.checkpoint import Checkpoint, InMemoryCheckpoint, JsonFileCheckpoint


def test_in_memory_checkpoint_round_trip_and_protocol() -> None:
    checkpoint = InMemoryCheckpoint()

    assert isinstance(checkpoint, Checkpoint)
    assert checkpoint.load("missing") is None

    checkpoint.save("task-1", "acting", {"attempt": 1})

    assert checkpoint.load("task-1") == {"state": "acting", "data": {"attempt": 1}}


def test_json_file_checkpoint_round_trip_and_persistence(tmp_path: Path) -> None:
    checkpoint = JsonFileCheckpoint(tmp_path)

    assert isinstance(checkpoint, Checkpoint)
    assert checkpoint.load("missing") is None

    checkpoint.save("task-1", "verifying", {"output": "draft"})

    assert checkpoint.load("task-1") == {"state": "verifying", "data": {"output": "draft"}}
    assert JsonFileCheckpoint(tmp_path).load("task-1") == {
        "state": "verifying",
        "data": {"output": "draft"},
    }
