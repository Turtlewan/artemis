"""Tests for the artemis schedule-management CLI."""

from __future__ import annotations

from pathlib import Path

import pytest

from artemis.app import main


def test_add_list_cancel_roundtrip(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db = str(tmp_path / "s.db")
    main(
        [
            "--db",
            db,
            "add",
            "--id",
            "j1",
            "--goal",
            "digest",
            "--cron",
            "0 7 * * *",
            "--title",
            "Morning",
        ]
    )
    assert "scheduled j1" in capsys.readouterr().out

    main(["--db", db, "list"])
    listed = capsys.readouterr().out
    assert "j1" in listed and "Morning" in listed

    main(["--db", db, "cancel", "j1"])
    assert "cancelled j1" in capsys.readouterr().out

    main(["--db", db, "list"])
    assert "j1" not in capsys.readouterr().out


def test_add_oneshot(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db = str(tmp_path / "s.db")
    main(["--db", db, "add", "--id", "once", "--goal", "g", "--at", "2030-01-01T07:00:00"])
    main(["--db", db, "list"])
    assert "once" in capsys.readouterr().out


def test_add_requires_cron_or_at(tmp_path: Path) -> None:
    db = str(tmp_path / "s.db")
    with pytest.raises(SystemExit):
        main(["--db", db, "add", "--goal", "no schedule"])


def test_list_empty(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["--db", str(tmp_path / "s.db"), "list"])
    assert "no active jobs" in capsys.readouterr().out
