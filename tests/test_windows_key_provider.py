from __future__ import annotations

import os
from pathlib import Path

import pytest

from artemis.config import Settings
from artemis.data.sqlcipher import SqlCipherError, sqlcipher_open
from artemis.identity.dpapi import DpapiError, dpapi_seal, dpapi_unseal
from artemis.identity.key_provider import ScopeLockedError, SecretKey
from artemis.identity.scope import GENERAL, OWNER_PRIVATE
from artemis.identity.windows_key_provider import InsecureKeyStoreError, WindowsKeyProvider


def _settings(tmp_path: Path) -> Settings:
    return Settings(data_root=tmp_path)


def _owner_entropy() -> bytes:
    return b"artemis-v1-owner-private"


def _general_entropy() -> bytes:
    return b"artemis-v1-general"


@pytest.fixture(autouse=True)
def _owner_profile_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin APPDATA/LOCALAPPDATA under tmp_path so the owner-private-dir assertion is
    deterministic regardless of the CI %TEMP% location (otherwise a non-profile %TEMP%
    makes every provider test fail at construction = silent false-green)."""
    monkeypatch.setenv("APPDATA", str(tmp_path / "profile" / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))


@pytest.fixture(autouse=True)
def _verified_hello(monkeypatch: pytest.MonkeyPatch) -> None:
    """m2-win-b gates unlock() behind a Windows Hello gesture. These m2-win-a tests
    exercise the DPAPI unseal/persist/lock behaviour, so stub the gesture to
    verified (the gate itself is covered in test_windows_hello_unlock.py)."""
    monkeypatch.setattr("artemis.identity.windows_hello.hello_available", lambda: True)
    monkeypatch.setattr("artemis.identity.windows_hello.verify", lambda _message: True)


def test_dpapi_round_trip_and_returns_bytearray() -> None:
    plaintext = bytes(range(32))
    entropy = b"artemis-test-entropy"

    unsealed = dpapi_unseal(dpapi_seal(plaintext, entropy=entropy), entropy=entropy)

    assert isinstance(unsealed, bytearray)
    assert bytes(unsealed) == plaintext


def test_dpapi_entropy_isolation() -> None:
    blob = dpapi_seal(bytes(range(32)), entropy=b"artemis-test-entropy-1")

    with pytest.raises(DpapiError):
        dpapi_unseal(blob, entropy=b"artemis-test-entropy-2")


def test_provider_provision_unlock_persists_and_locks(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    provider = WindowsKeyProvider(settings)
    provider.provision()
    provider.unlock()

    key_hex = provider.dek_for_scope(OWNER_PRIVATE).as_hex()
    assert provider.is_owner_unlocked()
    assert len(key_hex) == 64

    second_provider = WindowsKeyProvider(settings)
    second_provider.unlock()
    assert second_provider.dek_for_scope(OWNER_PRIVATE).as_hex() == key_hex

    provider.lock()
    assert not provider.is_owner_unlocked()
    with pytest.raises(ScopeLockedError):
        provider.dek_for_scope(OWNER_PRIVATE)


def test_provider_per_scope_entropy_isolation() -> None:
    blob = dpapi_seal(bytes(range(32)), entropy=_owner_entropy())

    with pytest.raises(DpapiError):
        dpapi_unseal(blob, entropy=_general_entropy())


def test_interrupted_provision_never_creates_final_dek(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    provider = WindowsKeyProvider(settings)

    def fail_replace(
        src: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        dst: str | bytes | os.PathLike[str] | os.PathLike[bytes],
    ) -> None:
        raise OSError("simulated interrupted provision")

    with monkeypatch.context() as patch:
        patch.setattr("artemis.identity.windows_key_provider.os.replace", fail_replace)
        with pytest.raises(OSError):
            provider.provision()

    assert not (tmp_path / "keys" / f"{OWNER_PRIVATE}.dek").exists()

    provider.provision()
    provider.unlock()
    assert len(provider.dek_for_scope(OWNER_PRIVATE).as_hex()) == 64


def test_unlock_zeroes_intermediate_bytearray(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    provider = WindowsKeyProvider(settings)
    provider.provision()
    returned = bytearray(b"x" * 32)

    def fake_unseal(blob: bytes, *, entropy: bytes) -> bytearray:
        assert blob
        assert entropy == _owner_entropy()
        return returned

    monkeypatch.setattr("artemis.identity.windows_key_provider.dpapi_unseal", fake_unseal)

    provider.unlock()

    assert provider.dek_for_scope(OWNER_PRIVATE).as_hex() == (b"x" * 32).hex()
    assert returned == bytearray(32)


def test_construction_outside_owner_private_root_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner_root = tmp_path / "profile"
    outside_root = tmp_path / "outside"
    monkeypatch.setenv("APPDATA", str(owner_root / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(owner_root / "Local"))

    with pytest.raises(InsecureKeyStoreError):
        WindowsKeyProvider(Settings(data_root=outside_root))


def test_sqlcipher_round_trip_with_provider_key(tmp_path: Path) -> None:
    provider = WindowsKeyProvider(_settings(tmp_path))
    provider.provision()
    provider.unlock()
    key_hex = provider.dek_for_scope(OWNER_PRIVATE).as_hex()
    db_path = tmp_path / "enc.db"
    marker = "sqlcipher-marker-value"

    conn = sqlcipher_open(db_path, key_hex)
    conn.execute("CREATE TABLE markers (value TEXT NOT NULL)")
    conn.execute("INSERT INTO markers (value) VALUES (?)", (marker,))
    conn.commit()
    conn.close()

    conn = sqlcipher_open(db_path, key_hex)
    try:
        assert conn.execute("SELECT value FROM markers").fetchone() == (marker,)
    finally:
        conn.close()

    wrong_key_hex = "00" * 32 if key_hex != "00" * 32 else "11" * 32
    with pytest.raises(SqlCipherError) as exc_info:
        sqlcipher_open(db_path, wrong_key_hex)
    # Criterion 1: neither the right nor wrong key leaks via the exception text or chain.
    chain_text = str(exc_info.value)
    for linked in (exc_info.value.__cause__, exc_info.value.__context__):
        if linked is not None:
            chain_text += str(linked)
    assert key_hex not in chain_text
    assert wrong_key_hex not in chain_text
    assert exc_info.value.__cause__ is None  # `from None` drops the cause chain

    raw_bytes = db_path.read_bytes()
    assert marker.encode() not in raw_bytes
    assert b"SQLite format 3" not in raw_bytes


def test_provider_accepts_multiple_scopes(tmp_path: Path) -> None:
    provider = WindowsKeyProvider(_settings(tmp_path), scopes=(OWNER_PRIVATE, GENERAL))

    provider.provision()
    provider.unlock()

    owner_key = provider.dek_for_scope(OWNER_PRIVATE)
    general_key = provider.dek_for_scope(GENERAL)
    assert isinstance(owner_key, SecretKey)
    assert isinstance(general_key, SecretKey)
    assert owner_key.as_hex() != general_key.as_hex()
