from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

from artemis.config import Settings
from artemis.identity import windows_hello
from artemis.identity.owner_provider import build_owner_key_provider
from artemis.identity.windows_key_provider import UnlockUnavailableError, WindowsKeyProvider
from artemis.integrations.google.tokens import InMemoryTokenStore


@pytest.fixture(autouse=True)
def _owner_profile_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    profile = tmp_path / "profile"
    monkeypatch.setenv("APPDATA", str(profile / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(profile / "Local"))


def _settings(tmp_path: Path) -> Settings:
    return Settings(data_root=tmp_path / "profile" / "Local" / "artemis")


def _mock_hello(monkeypatch: pytest.MonkeyPatch, *, available: bool, verified: bool = True) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(windows_hello, "hello_available", lambda: available)
    monkeypatch.setattr(windows_hello, "verify", lambda _message: verified)


def test_owner_provider_win32_unlocks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_hello(monkeypatch, available=True)

    provider = build_owner_key_provider(_settings(tmp_path))

    assert isinstance(provider, WindowsKeyProvider)
    assert provider.is_owner_unlocked()


def test_owner_provider_hello_unavailable_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_hello(monkeypatch, available=False)

    with pytest.raises(UnlockUnavailableError):
        build_owner_key_provider(_settings(tmp_path))


def test_google_auth_status_constructs_windows_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from artemis.integrations.google import cli

    seen: dict[str, WindowsKeyProvider] = {}
    _mock_hello(monkeypatch, available=True)
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(tmp_path))

    def _store(provider: WindowsKeyProvider) -> InMemoryTokenStore:
        seen["provider"] = provider
        return InMemoryTokenStore()

    monkeypatch.setattr(cli, "build_token_store", _store)

    rc = cli.main(["status"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "no Google account paired" in out
    assert seen["provider"].is_owner_unlocked()


def test_google_auth_hello_unavailable_clean_fail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    from artemis.integrations.google import cli

    _mock_hello(monkeypatch, available=False)
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(tmp_path))

    with caplog.at_level(logging.WARNING, logger=cli.logger.name):
        rc = cli.main(["status"])

    out = capsys.readouterr().out
    assert rc == 2
    assert out.strip() == "Unlock failed."
    for leak in ("Unavailable", "Denied", "Error", "Hello"):
        assert leak not in out
    assert "UnlockUnavailableError" in caplog.text


def test_google_auth_hello_denied_clean_fail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    from artemis.integrations.google import cli

    # Hello is present but the gesture is denied -> UnlockDeniedError.
    _mock_hello(monkeypatch, available=True, verified=False)
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(tmp_path))

    with caplog.at_level(logging.WARNING, logger=cli.logger.name):
        rc = cli.main(["status"])

    out = capsys.readouterr().out
    assert rc == 2
    assert out.strip() == "Unlock failed."
    for leak in ("Unavailable", "Denied", "Error", "Hello"):
        assert leak not in out
    assert "UnlockDeniedError" in caplog.text


async def test_email_rules_hello_denied_clean_fail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    from artemis.dev import email_rules

    _mock_hello(monkeypatch, available=True, verified=False)
    monkeypatch.setattr(email_rules, "get_settings", lambda: _settings(tmp_path))

    with caplog.at_level(logging.WARNING, logger=email_rules.logger.name):
        with pytest.raises(SystemExit) as exc_info:
            await email_rules.run(once=True)

    out = capsys.readouterr().out
    assert exc_info.value.code == 2
    assert out.strip() == "Unlock failed."
    for leak in ("Unavailable", "Denied", "Error", "Hello"):
        assert leak not in out
    assert "UnlockDeniedError" in caplog.text


async def test_email_rules_run_constructs_windows_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from artemis.dev import email_rules

    seen: dict[str, WindowsKeyProvider] = {}
    _mock_hello(monkeypatch, available=True)
    monkeypatch.setattr(email_rules, "get_settings", lambda: _settings(tmp_path))

    def _runtime(*, settings: Settings, key_provider: WindowsKeyProvider) -> object:
        del settings
        seen["provider"] = key_provider
        return object()

    async def _poll_once(runtime: object) -> int:
        del runtime
        return 0

    monkeypatch.setattr(email_rules, "build_dev_rules_runtime", _runtime)
    monkeypatch.setattr(email_rules, "poll_once", _poll_once)

    await email_rules.run(once=True)

    assert seen["provider"].is_owner_unlocked()


async def test_email_rules_hello_unavailable_clean_fail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    from artemis.dev import email_rules

    _mock_hello(monkeypatch, available=False)
    monkeypatch.setattr(email_rules, "get_settings", lambda: _settings(tmp_path))

    with caplog.at_level(logging.WARNING, logger=email_rules.logger.name):
        with pytest.raises(SystemExit) as exc_info:
            await email_rules.run(once=True)

    out = capsys.readouterr().out
    assert exc_info.value.code == 2
    assert out.strip() == "Unlock failed."
    for leak in ("Unavailable", "Denied", "Error", "Hello"):
        assert leak not in out
    assert "UnlockUnavailableError" in caplog.text
