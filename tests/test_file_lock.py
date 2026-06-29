from __future__ import annotations

from pathlib import Path

from artemis.file_lock import file_lock


def test_file_lock_releases_for_subsequent_acquire(tmp_path: Path) -> None:
    target = tmp_path / "x.json"

    with file_lock(target):
        pass

    with file_lock(target):
        pass

    assert target.with_name("x.json.lock").exists()
