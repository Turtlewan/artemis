"""Tests for the version-scoped bless store."""

from __future__ import annotations

from pathlib import Path

import pytest

from artemis.capabilities.bless import BlessStore


def test_bless_is_version_scoped_and_unbless_removes(tmp_path: Path) -> None:
    store = BlessStore(tmp_path)

    store.bless("gmail-reader", 2)

    assert store.is_blessed("gmail-reader", 2) is True
    assert store.is_blessed("gmail-reader", 3) is False
    assert store.list_blessed() == [("gmail-reader", 2)]

    store.unbless("gmail-reader")

    assert store.is_blessed("gmail-reader", 2) is False
    assert store.list_blessed() == []


def test_list_reflects_multiple_blessed_capabilities(tmp_path: Path) -> None:
    store = BlessStore(tmp_path)

    store.bless("zeta", 1)
    store.bless("alpha", 4)

    assert store.list_blessed() == [("alpha", 4), ("zeta", 1)]


def test_reads_fail_closed_for_missing_corrupt_and_unreadable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "bless.json"
    store = BlessStore(path)

    assert store.is_blessed("gmail-reader", 1) is False
    assert store.list_blessed() == []

    path.write_text("{not json", encoding="utf-8")
    assert store.is_blessed("gmail-reader", 1) is False
    assert store.list_blessed() == []

    def raise_permission_error(self: Path, encoding: str = "utf-8") -> str:
        del self, encoding
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "read_text", raise_permission_error)

    assert store.is_blessed("gmail-reader", 1) is False
    assert store.list_blessed() == []


def test_reads_are_fresh_after_another_store_revokes(tmp_path: Path) -> None:
    first = BlessStore(tmp_path)
    second = BlessStore(tmp_path)
    first.bless("gmail-reader", 2)

    assert first.is_blessed("gmail-reader", 2) is True

    second.unbless("gmail-reader")

    assert first.is_blessed("gmail-reader", 2) is False
