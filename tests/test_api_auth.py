"""Real-P256 device-pairing + API-session flow for the no-lock v2 brain."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import cast

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from artemis.api.app import create_app
from artemis.api.auth import API_SESSION_CONTEXT


class Phone:
    """Client-side P-256 signer mirroring the Tauri device key."""

    def __init__(self) -> None:
        self.private_key = ec.generate_private_key(ec.SECP256R1())

    @property
    def public_key_b64(self) -> str:
        raw = self.private_key.public_key().public_bytes(
            serialization.Encoding.X962,
            serialization.PublicFormat.UncompressedPoint,
        )
        return base64.b64encode(raw).decode("ascii")

    def sign_pairing(self, code: str, device_id: str) -> str:
        code_bytes = code.encode("utf-8")
        message = len(code_bytes).to_bytes(2, "big") + code_bytes + device_id.encode("utf-8")
        return _b64(self.private_key.sign(message, ec.ECDSA(hashes.SHA256())))

    def sign_session(self, nonce: bytes, counter: int) -> str:
        ctx = API_SESSION_CONTEXT
        message = (
            len(nonce).to_bytes(2, "big")
            + nonce
            + len(ctx).to_bytes(2, "big")
            + ctx
            + counter.to_bytes(8, "big")
        )
        return _b64(self.private_key.sign(message, ec.ECDSA(hashes.SHA256())))


def test_pair_session_and_authenticated_status(tmp_path: Path) -> None:
    client = _client(tmp_path)
    phone = Phone()
    device_id = "phone"

    code = cast(dict[str, str], client.post("/app/admin/pair-code").json())["code"]
    bad_pair = client.post(
        "/app/pair",
        json={
            "device_id": device_id,
            "public_key_b64": phone.public_key_b64,
            "pairing_code": code,
            "code_signature_b64": phone.sign_pairing("wrong", device_id),
        },
    )
    assert bad_pair.status_code == 401

    pair = client.post(
        "/app/pair",
        json={
            "device_id": device_id,
            "public_key_b64": phone.public_key_b64,
            "pairing_code": code,
            "code_signature_b64": phone.sign_pairing(code, device_id),
        },
    )
    assert pair.status_code == 200
    assert pair.json() == {"paired": True}

    token = _session_token(client, phone, device_id, 1)
    headers = {"Authorization": f"Bearer {token}"}

    assert client.get("/app/status").status_code == 401
    status = client.get("/app/status", headers=headers)
    assert status.status_code == 200
    assert status.json() == {
        "connected": True,
        "vault_unlocked": True,
        "device_id": device_id,
    }
    assert client.post("/app/unlock/begin", json={}, headers=headers).status_code == 200
    assert client.post(
        "/app/unlock/complete",
        json={"nonce_b64": _b64(b"nonce"), "counter": 1, "signature_b64": _b64(b"sig")},
        headers=headers,
    ).json() == {"unlocked": True}
    assert client.post("/app/lock", headers=headers).json() == {"locked": True}

    assert client.post("/app/logout", headers=headers).status_code == 200
    assert client.get("/app/status", headers=headers).status_code == 401


def test_replay_and_counter_rejected(tmp_path: Path) -> None:
    client = _client(tmp_path)
    phone = Phone()
    _pair(client, phone, "phone")

    begin = client.post("/app/session/begin", json={"device_id": "phone"})
    assert begin.status_code == 200
    nonce = base64.b64decode(cast(dict[str, str], begin.json())["nonce_b64"])

    complete = client.post(
        "/app/session/complete",
        json={
            "device_id": "phone",
            "nonce_b64": _b64(nonce),
            "counter": 1,
            "signature_b64": phone.sign_session(nonce, 1),
        },
    )
    assert complete.status_code == 200

    replay = client.post(
        "/app/session/complete",
        json={
            "device_id": "phone",
            "nonce_b64": _b64(nonce),
            "counter": 2,
            "signature_b64": phone.sign_session(nonce, 2),
        },
    )
    assert replay.status_code == 401

    begin_again = client.post("/app/session/begin", json={"device_id": "phone"})
    assert begin_again.status_code == 200
    next_nonce = base64.b64decode(cast(dict[str, str], begin_again.json())["nonce_b64"])
    counter_regression = client.post(
        "/app/session/complete",
        json={
            "device_id": "phone",
            "nonce_b64": _b64(next_nonce),
            "counter": 1,
            "signature_b64": phone.sign_session(next_nonce, 1),
        },
    )
    assert counter_regression.status_code == 401


def test_admin_pair_code_is_loopback_only_and_rate_limit_remote(tmp_path: Path) -> None:
    loopback = _client(tmp_path / "loopback")
    assert loopback.post("/app/admin/pair-code").status_code == 200

    remote = TestClient(create_app(data_dir=tmp_path / "remote"), client=("100.64.0.1", 1234))
    assert remote.post("/app/admin/pair-code").status_code == 403
    statuses = [
        remote.post("/app/session/begin", json={"device_id": "unknown"}).status_code
        for _ in range(6)
    ]
    assert statuses == [401, 401, 401, 401, 401, 429]


def _client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(data_dir=tmp_path), client=("127.0.0.1", 5000))


def _pair(client: TestClient, phone: Phone, device_id: str) -> None:
    code = cast(dict[str, str], client.post("/app/admin/pair-code").json())["code"]
    response = client.post(
        "/app/pair",
        json={
            "device_id": device_id,
            "public_key_b64": phone.public_key_b64,
            "pairing_code": code,
            "code_signature_b64": phone.sign_pairing(code, device_id),
        },
    )
    assert response.status_code == 200


def _session_token(client: TestClient, phone: Phone, device_id: str, counter: int) -> str:
    begin = client.post("/app/session/begin", json={"device_id": device_id})
    assert begin.status_code == 200
    nonce = base64.b64decode(cast(dict[str, str], begin.json())["nonce_b64"])
    complete = client.post(
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
