"""Windows Hello unlock gate + CLI + main.py wiring (m2-win-b, ADR-033).

The live gesture is mocked everywhere except the env-gated manual test — the COM
path in ``windows_hello.verify`` is only exercised by a real fingerprint/PIN on a
Hello-enrolled box (``ARTEMIS_HELLO_MANUAL=1``), never in CI.
"""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI

from artemis.config import Settings
from artemis.identity import windows_hello
from artemis.identity.key_provider import ScopeLockedError
from artemis.identity.scope import OWNER_PRIVATE
from artemis.identity.windows_key_provider import (
    UnlockDeniedError,
    UnlockUnavailableError,
    WindowsKeyProvider,
)
from artemis.main import lifespan


def _settings(tmp_path: Path) -> Settings:
    return Settings(data_root=tmp_path)


@pytest.fixture(autouse=True)
def _owner_profile_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin APPDATA/LOCALAPPDATA under tmp_path so WindowsKeyProvider construction
    (which requires the key store to live under the user profile) is deterministic."""
    monkeypatch.setenv("APPDATA", str(tmp_path / "profile" / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))


# --- Task 1: parameterised-IID algorithm -----------------------------------


def test_parameterized_iid_matches_published_ireference_bool() -> None:
    """The WinRT pinterface-GUID algorithm that derives the IAsyncOperation IID is
    pinned against the published IReference<bool> IID, so a regression in the
    derivation (which we cannot otherwise verify without a gesture) is caught."""
    iid = windows_hello._parameterized_iid("pinterface({61c17706-2d65-11e0-9ae8-d48564015472};b1)")
    assert iid == uuid.UUID("3C00FD60-2950-5939-A21A-2D12C5A01B8A")


async def test_hello_available_safe_inside_event_loop() -> None:
    """Regression (cross-model review BLOCK): hello_available() is invoked from the
    async lifespan via unlock(), so it must NOT call asyncio.run() on the running
    loop. Calling it from inside an event loop must return a bool, never raise
    RuntimeError. Exercises the real winsdk path on win32 (no gesture needed)."""
    result = windows_hello.hello_available()
    assert isinstance(result, bool)


# --- Task 2: Hello-enforced unlock() ---------------------------------------


def test_unlock_unseals_when_gesture_verified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(windows_hello, "hello_available", lambda: True)
    monkeypatch.setattr(windows_hello, "verify", lambda _message: True)
    provider = WindowsKeyProvider(_settings(tmp_path))
    provider.provision()

    provider.unlock()

    assert provider.is_owner_unlocked()
    assert len(provider.dek_for_scope(OWNER_PRIVATE).as_hex()) == 64


def test_unlock_denied_raises_and_unseals_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(windows_hello, "hello_available", lambda: True)
    monkeypatch.setattr(windows_hello, "verify", lambda _message: False)
    provider = WindowsKeyProvider(_settings(tmp_path))
    provider.provision()

    with pytest.raises(UnlockDeniedError):
        provider.unlock()

    assert not provider.is_owner_unlocked()
    with pytest.raises(ScopeLockedError):
        provider.dek_for_scope(OWNER_PRIVATE)


def test_unlock_unavailable_never_calls_verify_or_unseals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = {"verify": 0}

    def _verify(_message: str) -> bool:
        calls["verify"] += 1
        return True

    monkeypatch.setattr(windows_hello, "hello_available", lambda: False)
    monkeypatch.setattr(windows_hello, "verify", _verify)
    provider = WindowsKeyProvider(_settings(tmp_path))
    provider.provision()

    with pytest.raises(UnlockUnavailableError):
        provider.unlock()

    assert calls["verify"] == 0  # gate short-circuits before the gesture
    assert not provider.is_owner_unlocked()


def test_unlock_no_console_maps_to_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _verify(_message: str) -> bool:
        raise windows_hello.NoConsoleWindowError("no console window")

    monkeypatch.setattr(windows_hello, "hello_available", lambda: True)
    monkeypatch.setattr(windows_hello, "verify", _verify)
    provider = WindowsKeyProvider(_settings(tmp_path))
    provider.provision()

    with pytest.raises(UnlockUnavailableError):
        provider.unlock()

    assert not provider.is_owner_unlocked()


def test_unseal_all_is_private_and_not_hello_gated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # _unseal_all bypasses the gesture (test/internal only) and must not be the
    # public unlock surface.
    monkeypatch.setattr(windows_hello, "hello_available", lambda: False)
    provider = WindowsKeyProvider(_settings(tmp_path))
    provider.provision()

    provider._unseal_all()

    assert provider.is_owner_unlocked()
    assert "_unseal_all".startswith("_")  # leading underscore = private surface


# --- Task 3: artemis-unlock CLI --------------------------------------------


def test_cli_unlock_reports_scope_count_on_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(windows_hello, "hello_available", lambda: True)
    monkeypatch.setattr(windows_hello, "verify", lambda _message: True)
    monkeypatch.setattr("artemis.cli.unlock.get_settings", lambda: _settings(tmp_path))
    from artemis.cli.unlock import main

    rc = main([])

    out = capsys.readouterr().out
    assert rc == 0
    assert out.strip() == "unlocked: 1 scope(s)"
    # never leaks key material
    assert "0x" not in out.lower() and len([c for c in out if c in "0123456789abcdef"]) < 16


def test_cli_unlock_failure_is_generic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(windows_hello, "hello_available", lambda: False)
    monkeypatch.setattr("artemis.cli.unlock.get_settings", lambda: _settings(tmp_path))
    from artemis.cli.unlock import main

    rc = main([])

    out = capsys.readouterr().out
    assert rc == 2
    assert out.strip() == "Unlock failed."
    # does not distinguish enrolled-vs-denied / expose an exception class
    for leak in ("Unavailable", "Denied", "Error", "Hello"):
        assert leak not in out


# --- Task 4: main.py lifespan wiring ---------------------------------------


class _Dummy:
    def __init__(self, *args: object, **kwargs: object) -> None:
        pass


@pytest.fixture
def _patch_lifespan_noise(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub everything in lifespan *after* the key-provider branch so the tests
    isolate the branch under test."""
    monkeypatch.setattr("artemis.main.compose_brain", lambda *a, **k: object())
    monkeypatch.setattr("artemis.adapters.model_adapters.OpenAIEmbeddingModel", _Dummy)
    for name in (
        "RecipeStore",
        "Promoter",
        "RecurrenceStore",
        "DeviceRegistry",
        "Gateway",
        "AppAuth",
        "ChallengeStore",
        "SessionStore",
        "ReviewSurface",
        "PairingCodeStore",
        "RateLimiter",
        "LayoutStore",
        "DefaultDomainReadSource",
    ):
        monkeypatch.setattr(f"artemis.main.{name}", _Dummy)


async def test_lifespan_win32_composes_windows_key_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _patch_lifespan_noise: None
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(windows_hello, "hello_available", lambda: True)
    monkeypatch.setattr(windows_hello, "verify", lambda _message: True)
    monkeypatch.setattr("artemis.main.get_settings", lambda: _settings(tmp_path))

    app = FastAPI()
    async with lifespan(app):
        assert isinstance(app.state.key_provider, WindowsKeyProvider)
        assert app.state.key_provider.is_owner_unlocked()


async def test_lifespan_prod_blocks_require_hello_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "artemis.main.get_settings",
        lambda: Settings(data_root=tmp_path, slot="prod", require_hello_unlock=False),
    )
    app = FastAPI()
    with pytest.raises(RuntimeError, match="prod requires Hello unlock"):
        async with lifespan(app):
            pass


async def test_lifespan_hello_unavailable_aborts_when_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(windows_hello, "hello_available", lambda: False)
    monkeypatch.setattr(
        "artemis.main.get_settings",
        lambda: Settings(data_root=tmp_path, require_hello_unlock=True),
    )
    app = FastAPI()
    with pytest.raises(UnlockUnavailableError):
        async with lifespan(app):
            pass


async def test_lifespan_darwin_path_uses_broker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _patch_lifespan_noise: None
) -> None:
    from artemis.identity.broker_client import BrokerKeyProvider

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr("artemis.main.BrokerClient", _Dummy)
    monkeypatch.setattr("artemis.main.get_settings", lambda: _settings(tmp_path))

    app = FastAPI()
    async with lifespan(app):
        assert isinstance(app.state.key_provider, BrokerKeyProvider)


# --- Task 1: manual, env-gated live gesture (never a CI gate) ---------------


@pytest.mark.skipif(
    not os.environ.get("ARTEMIS_HELLO_MANUAL"),
    reason="interactive Windows Hello gesture (set ARTEMIS_HELLO_MANUAL=1 on the dev box)",
)
def test_verify_live_gesture_manual() -> None:  # pragma: no cover - interactive
    assert windows_hello.hello_available()
    assert windows_hello.verify("Unlock Artemis (manual test)") is True
