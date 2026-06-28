from __future__ import annotations

import base64
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from artemis.identity.app_auth import (
    AppAuth,
    AuthError,
    ChallengeStore,
    DeviceRegistry,
    SessionStore,
)

SESSION_CONTEXT = b"session"
UNLOCK_CONTEXT = b"unlock"


def _public_key_b64(private_key: ec.EllipticCurvePrivateKey) -> str:
    public_bytes = private_key.public_key().public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )
    return base64.b64encode(public_bytes).decode("ascii")


def _client_session_message(nonce: bytes, counter: int) -> bytes:
    return (
        len(nonce).to_bytes(2, "big")
        + nonce
        + len(SESSION_CONTEXT).to_bytes(2, "big")
        + SESSION_CONTEXT
        + counter.to_bytes(8, "big")
    )


def _raw_concat_session_message(nonce: bytes, counter: int) -> bytes:
    return nonce + SESSION_CONTEXT + counter.to_bytes(8, "big")


def _unlock_message(nonce: bytes, counter: int) -> bytes:
    return (
        len(nonce).to_bytes(2, "big")
        + nonce
        + len(UNLOCK_CONTEXT).to_bytes(2, "big")
        + UNLOCK_CONTEXT
        + counter.to_bytes(8, "big")
    )


def _sign(private_key: ec.EllipticCurvePrivateKey, message: bytes) -> bytes:
    return private_key.sign(message, ec.ECDSA(hashes.SHA256()))


def test_client_framed_session_proof_and_replay_invariants(tmp_path: Path) -> None:
    # Safe in failures: cryptography private-key reprs redact private scalar bytes.
    private_key = ec.generate_private_key(ec.SECP256R1())
    registry = DeviceRegistry(tmp_path / "identity" / "devices.json")
    registry.register("phone", _public_key_b64(private_key))
    auth = AppAuth(registry, ChallengeStore(), SessionStore())

    raw_nonce = auth.begin_session("phone")
    with pytest.raises(AuthError):
        auth.complete_session(
            "phone",
            raw_nonce,
            1,
            _sign(private_key, _raw_concat_session_message(raw_nonce, 1)),
        )

    nonce = auth.begin_session("phone")
    session = auth.complete_session(
        "phone",
        nonce,
        1,
        _sign(private_key, _client_session_message(nonce, 1)),
    )
    assert auth.sessions.get(session.token) is not None

    with pytest.raises(AuthError):
        auth.complete_session(
            "phone",
            nonce,
            2,
            _sign(private_key, _client_session_message(nonce, 2)),
        )

    stale_counter_nonce = auth.begin_session("phone")
    with pytest.raises(AuthError):
        auth.complete_session(
            "phone",
            stale_counter_nonce,
            1,
            _sign(private_key, _client_session_message(stale_counter_nonce, 1)),
        )


def test_unlock_context_signature_rejected_by_session_verify(tmp_path: Path) -> None:
    # Domain separation: a proof signed over the b"unlock" context must NOT
    # authenticate a connect (session) proof, which the verifier builds with
    # b"session". Pins the Seam 11 "contexts are non-interchangeable" invariant.
    private_key = ec.generate_private_key(ec.SECP256R1())
    registry = DeviceRegistry(tmp_path / "identity" / "devices.json")
    registry.register("phone", _public_key_b64(private_key))
    auth = AppAuth(registry, ChallengeStore(), SessionStore())

    nonce = auth.begin_session("phone")
    with pytest.raises(AuthError):
        auth.complete_session(
            "phone",
            nonce,
            1,
            _sign(private_key, _unlock_message(nonce, 1)),
        )


def test_reserved_unlock_framing_golden_vector() -> None:
    nonce = bytes(range(32))
    message = _unlock_message(nonce, 0x0102030405060708)

    assert message.hex() == (
        "0020"
        "000102030405060708090a0b0c0d0e0f"
        "101112131415161718191a1b1c1d1e1f"
        "0006"
        "756e6c6f636b"
        "0102030405060708"
    )
