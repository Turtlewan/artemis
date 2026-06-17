"""Tests for path-resolution functions (artemis.paths)."""

from __future__ import annotations

from pathlib import Path

import pytest

from artemis.config import Settings
from artemis.paths import (
    backups_dir,
    env_file,
    logs_dir,
    scope_dir,
    slot_root,
    vault_dir,
)


def _dev_settings() -> Settings:
    """Factory for a minimal dev Settings with a tmp-style data root."""
    return Settings(
        slot="dev",
        data_root=Path("/tmp/artemis-test"),
        roles_file=Path("config/roles.toml"),
    )


def test_slot_root() -> None:
    s = _dev_settings()
    assert slot_root(s) == Path("/tmp/artemis-test/dev")


def test_scope_dir_owner_private() -> None:
    s = _dev_settings()
    assert scope_dir(s, "owner-private") == Path("/tmp/artemis-test/dev/owner-private")


def test_scope_dir_general() -> None:
    s = _dev_settings()
    assert scope_dir(s, "general") == Path("/tmp/artemis-test/dev/general")


def test_scope_dir_guest() -> None:
    s = _dev_settings()
    assert scope_dir(s, "guest-alice") == Path("/tmp/artemis-test/dev/guest-alice")


def test_scope_dir_unknown_raises() -> None:
    s = _dev_settings()
    with pytest.raises(ValueError, match="Unknown scope"):
        scope_dir(s, "invalid-scope")


def test_vault_dir() -> None:
    s = _dev_settings()
    assert vault_dir(s, "owner-private") == scope_dir(s, "owner-private") / "vault"


def test_backups_dir() -> None:
    s = _dev_settings()
    assert backups_dir(s) == Path("/tmp/artemis-test/dev/backups")


def test_logs_dir() -> None:
    s = _dev_settings()
    assert logs_dir(s) == Path("/tmp/artemis-test/dev/logs")


def test_env_file_dev() -> None:
    s = _dev_settings()
    assert env_file(s) == Path("config/.env.dev")


def test_env_file_uat() -> None:
    from artemis.config import Settings

    s = Settings(
        slot="uat",
        data_root=Path("/tmp/artemis-test"),
        roles_file=Path("config/roles.toml"),
    )
    assert env_file(s) == Path("config/.env.uat")
