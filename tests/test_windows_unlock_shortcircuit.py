from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import FastAPI
from fastapi.testclient import TestClient

from artemis.api_app import DefaultDomainReadSource, PairingCodeStore, RateLimiter, app_router
from artemis.config import Settings
from artemis.identity.app_auth import AppAuth, ChallengeStore, DeviceRegistry, SessionStore
from artemis.identity.scope import OWNER_PRIVATE
from artemis.identity.windows_key_provider import WindowsKeyProvider

SESSION_CONTEXT = b"session"


class Phone:
    def __init__(self) -> None:
        self.private_key = ec.generate_private_key(ec.SECP256R1())

    @property
    def public_key_b64(self) -> str:
        public_bytes = self.private_key.public_key().public_bytes(
            serialization.Encoding.X962,
            serialization.PublicFormat.UncompressedPoint,
        )
        return base64.b64encode(public_bytes).decode("ascii")

    def sign_pairing(self, code: str, device_id: str) -> str:
        code_bytes = code.encode("utf-8")
        message = len(code_bytes).to_bytes(2, "big") + code_bytes + device_id.encode("utf-8")
        return _b64(self.private_key.sign(message, ec.ECDSA(hashes.SHA256())))

    def sign_session(self, nonce: bytes, counter: int) -> str:
        message = (
            len(nonce).to_bytes(2, "big")
            + nonce
            + len(SESSION_CONTEXT).to_bytes(2, "big")
            + SESSION_CONTEXT
            + counter.to_bytes(8, "big")
        )
        return _b64(self.private_key.sign(message, ec.ECDSA(hashes.SHA256())))


@dataclass
class Fixture:
    app: FastAPI
    client: TestClient
    key_provider: WindowsKeyProvider
    pairing_codes: PairingCodeStore


class _JsonResponse(Protocol):
    status_code: int

    def json(self) -> object: ...


def _settings(tmp_path: Path) -> Settings:
    return Settings(data_root=tmp_path / "profile" / "Roaming" / "Artemis")


@pytest.fixture(autouse=True)
def _owner_profile_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path / "profile" / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "profile" / "Local"))


def test_windows_unlock_shortcircuit_unit(tmp_path: Path) -> None:
    provider = WindowsKeyProvider(_settings(tmp_path))
    provider.provision()
    provider._unseal_all()

    nonce = provider.begin_unlock(OWNER_PRIVATE)
    assert len(nonce) == 32

    provider.complete_unlock(OWNER_PRIVATE, nonce, b"garbage-proof")
    assert provider.is_owner_unlocked()

    provider.lock_all()
    assert not provider.is_owner_unlocked()


def test_calendar_route_passes_after_startup_hello_unsealed_windows_provider(
    tmp_path: Path,
) -> None:
    """DefaultDomainReadSource remains a typed fake until real owner-DEK readers land."""
    provider = WindowsKeyProvider(_settings(tmp_path))
    provider.provision()
    provider._unseal_all()
    fixture = _fixture(tmp_path, provider)
    headers = _paired_session_headers(fixture, Phone())

    calendar = fixture.client.get("/app/calendar", headers=headers)

    assert calendar.status_code == 200


def test_sealed_windows_provider_unlock_complete_stays_fail_closed(
    tmp_path: Path,
) -> None:
    provider = WindowsKeyProvider(_settings(tmp_path))
    provider.provision()
    nonce = provider.begin_unlock(OWNER_PRIVATE)

    provider.complete_unlock(OWNER_PRIVATE, nonce, b"garbage-proof")
    assert not provider.is_owner_unlocked()

    fixture = _fixture(tmp_path, provider)
    headers = _paired_session_headers(fixture, Phone())
    unlock_begin = fixture.client.post("/app/unlock/begin", json={}, headers=headers)
    assert unlock_begin.status_code == 200
    unlock_nonce_b64 = cast(str, cast(dict[str, object], unlock_begin.json())["nonce_b64"])
    unlock_complete = fixture.client.post(
        "/app/unlock/complete",
        json={
            "nonce_b64": unlock_nonce_b64,
            "counter": 10,
            "signature_b64": _b64(b"garbage-proof"),
        },
        headers=headers,
    )

    assert unlock_complete.status_code == 200
    assert not provider.is_owner_unlocked()
    assert fixture.client.get("/app/calendar", headers=headers).status_code == 423


def _fixture(tmp_path: Path, key_provider: WindowsKeyProvider) -> Fixture:
    app = FastAPI()
    app.include_router(app_router)
    registry = DeviceRegistry(tmp_path / "identity" / "devices.json")
    pairing_codes = PairingCodeStore()
    app.state.app_auth = AppAuth(registry, ChallengeStore(), SessionStore())
    app.state.broker_client = None
    app.state.key_provider = key_provider
    app.state.pairing_codes = pairing_codes
    app.state.rate_limiter = RateLimiter()
    app.state.domain_read_source = DefaultDomainReadSource()
    client = TestClient(app, client=("127.0.0.1", 5000))
    return Fixture(app, client, key_provider, pairing_codes)


def _paired_session_headers(fixture: Fixture, phone: Phone) -> dict[str, str]:
    assert _pair(fixture, phone, "phone").status_code == 200
    return {"Authorization": f"Bearer {_session_token(fixture, phone, 'phone', 1)}"}


def _pair(fixture: Fixture, phone: Phone, device_id: str) -> _JsonResponse:
    code = fixture.pairing_codes.mint()
    return fixture.client.post(
        "/app/pair",
        json={
            "device_id": device_id,
            "public_key_b64": phone.public_key_b64,
            "pairing_code": code,
            "code_signature_b64": phone.sign_pairing(code, device_id),
        },
    )


def _session_token(fixture: Fixture, phone: Phone, device_id: str, counter: int) -> str:
    begin = fixture.client.post("/app/session/begin", json={"device_id": device_id})
    assert begin.status_code == 200
    nonce = base64.b64decode(cast(str, cast(dict[str, object], begin.json())["nonce_b64"]))
    complete = fixture.client.post(
        "/app/session/complete",
        json={
            "device_id": device_id,
            "nonce_b64": _b64(nonce),
            "counter": counter,
            "signature_b64": phone.sign_session(nonce, counter),
        },
    )
    assert complete.status_code == 200
    return cast(str, cast(dict[str, object], complete.json())["session_token"])


def _b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")
