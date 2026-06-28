from __future__ import annotations

import base64
from collections.abc import AsyncIterator
from pathlib import Path
from typing import cast

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from artemis.brain import Brain, BrainResponse
from artemis.gateway import OWNER_PERSON_ID, OWNER_SCOPE, Gateway
from artemis.identity.app_auth import (
    API_SESSION_CONTEXT,
    AppAuth,
    AuthError,
    ChallengeStore,
    DeviceRegistry,
    InvalidDeviceKeyError,
    Principal,
    SessionStore,
    resolve_scope,
)


def _private_key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


def _public_key_b64(private_key: ec.EllipticCurvePrivateKey) -> str:
    public_bytes = private_key.public_key().public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )
    return base64.b64encode(public_bytes).decode("ascii")


def _sign(private_key: ec.EllipticCurvePrivateKey, nonce: bytes, counter: int) -> bytes:
    ctx = API_SESSION_CONTEXT
    return private_key.sign(
        len(nonce).to_bytes(2, "big")
        + nonce
        + len(ctx).to_bytes(2, "big")
        + ctx
        + counter.to_bytes(8, "big"),
        ec.ECDSA(hashes.SHA256()),
    )


def _auth(tmp_path: Path, device_id: str = "dev") -> tuple[AppAuth, ec.EllipticCurvePrivateKey]:
    private_key = _private_key()
    registry = DeviceRegistry(tmp_path / "identity" / "devices.json")
    registry.register(device_id, _public_key_b64(private_key))
    auth = AppAuth(registry, ChallengeStore(), SessionStore())
    return auth, private_key


def test_registry_round_trips_and_rejects_invalid_key(tmp_path: Path) -> None:
    private_key = _private_key()
    registry_path = tmp_path / "identity" / "devices.json"
    registry = DeviceRegistry(registry_path)

    registered = registry.register("dev", _public_key_b64(private_key))
    loaded = DeviceRegistry(registry_path).get("dev")

    assert loaded == registered
    assert loaded is not None
    assert loaded.counter == 0
    assert DeviceRegistry(registry_path).list() == [registered]
    with pytest.raises(InvalidDeviceKeyError):
        registry.register("bad", "not-a-key")
    registry.remove("dev")
    registry.remove("dev")
    assert registry.get("dev") is None


def test_challenge_response_happy_path_updates_counter(tmp_path: Path) -> None:
    auth, private_key = _auth(tmp_path)

    nonce = auth.begin_session("dev")
    session = auth.complete_session("dev", nonce, 1, _sign(private_key, nonce, 1))
    stored_session = auth.sessions.get(session.token)
    stored_device = auth.registry.get("dev")

    assert stored_session is not None
    assert stored_session.principal.device_id == "dev"
    assert stored_device is not None
    assert stored_device.counter == 1


def test_replayed_nonce_is_rejected(tmp_path: Path) -> None:
    auth, private_key = _auth(tmp_path)
    nonce = auth.begin_session("dev")
    auth.complete_session("dev", nonce, 1, _sign(private_key, nonce, 1))

    with pytest.raises(AuthError):
        auth.complete_session("dev", nonce, 2, _sign(private_key, nonce, 2))


def test_counter_must_strictly_increase(tmp_path: Path) -> None:
    auth, private_key = _auth(tmp_path)

    nonce_zero = auth.begin_session("dev")
    with pytest.raises(AuthError):
        auth.complete_session("dev", nonce_zero, 0, _sign(private_key, nonce_zero, 0))

    nonce_one = auth.begin_session("dev")
    auth.complete_session("dev", nonce_one, 1, _sign(private_key, nonce_one, 1))

    nonce_replay_counter = auth.begin_session("dev")
    with pytest.raises(AuthError):
        auth.complete_session(
            "dev",
            nonce_replay_counter,
            1,
            _sign(private_key, nonce_replay_counter, 1),
        )

    nonce_two = auth.begin_session("dev")
    session = auth.complete_session("dev", nonce_two, 2, _sign(private_key, nonce_two, 2))
    assert auth.sessions.get(session.token) is not None


def test_unknown_begin_session_clears_challenge_slot(tmp_path: Path) -> None:
    challenges = ChallengeStore()
    auth = AppAuth(DeviceRegistry(tmp_path / "devices.json"), challenges, SessionStore())

    with pytest.raises(AuthError):
        auth.begin_session("unknown")

    assert not challenges.consume("unknown", b"wrong")


def test_bad_signature_and_unknown_device_are_rejected(tmp_path: Path) -> None:
    auth, _ = _auth(tmp_path)
    wrong_private_key = _private_key()
    nonce = auth.begin_session("dev")

    with pytest.raises(AuthError):
        auth.complete_session("dev", nonce, 1, _sign(wrong_private_key, nonce, 1))
    with pytest.raises(AuthError):
        auth.begin_session("nope")


def test_session_lifetime_and_revocation() -> None:
    principal = Principal(OWNER_PERSON_ID, "dev")
    expired_store = SessionStore(ttl_seconds=0)
    expired = expired_store.create(principal)
    assert expired_store.get(expired.token) is None

    store = SessionStore()
    first = store.create(principal)
    second = store.create(principal)
    assert store.get(first.token) is not None
    store.revoke(first.token)
    assert store.get(first.token) is None
    assert store.get(second.token) is not None
    store.revoke_all()
    assert store.get(second.token) is None


def test_scope_resolution() -> None:
    assert resolve_scope(Principal(OWNER_PERSON_ID, "dev")) == OWNER_SCOPE


@pytest.mark.asyncio
async def test_gateway_delegates_owner_and_explicit_scopes() -> None:
    class FakeBrain:
        def __init__(self) -> None:
            self.scopes: list[str] = []

        async def respond(self, request_text: str, scope: str) -> BrainResponse:
            self.scopes.append(scope)
            return BrainResponse(text=request_text, path="local")

        async def respond_stream(self, request_text: str, scope: str) -> AsyncIterator[str]:
            self.scopes.append(scope)
            yield request_text

    fake = FakeBrain()
    gateway = Gateway(cast(Brain, fake))

    response = await gateway.handle_text("hi")
    scoped_response = await gateway.handle_text_scoped("hi", "general")
    stream = [chunk async for chunk in gateway.handle_text_stream_scoped("stream", "general")]

    assert response.text == "hi"
    assert scoped_response.text == "hi"
    assert stream == ["stream"]
    assert fake.scopes == [OWNER_SCOPE, "general", "general"]


def test_x963_public_key_and_der_signature_conformance(tmp_path: Path) -> None:
    private_key = _private_key()
    public_key_bytes = private_key.public_key().public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )
    assert public_key_bytes[0] == 0x04
    assert len(public_key_bytes) == 65
    public_key_b64 = base64.b64encode(public_key_bytes).decode("ascii")

    registry = DeviceRegistry(tmp_path / "identity" / "devices.json")
    registry.register("client-auth", public_key_b64)
    auth = AppAuth(registry, ChallengeStore(), SessionStore())
    nonce = auth.begin_session("client-auth")
    signature_der = _sign(private_key, nonce, 1)

    session = auth.complete_session("client-auth", nonce, 1, signature_der)

    assert auth.sessions.get(session.token) is not None
    assert session.principal.device_id == "client-auth"
