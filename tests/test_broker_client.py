from __future__ import annotations

import base64
import json
import socket
import threading
from pathlib import Path
from typing import Protocol, cast

import pytest

from artemis.identity.broker_client import BrokerClient, BrokerError, BrokerKeyProvider
from artemis.identity.key_provider import ScopeLockedError, SecretKey
from artemis.ports.types import Scope

DEK = b"d" * 32
AF_UNIX = cast(socket.AddressFamily | None, getattr(socket, "AF_UNIX", None))


class BrokerLike(Protocol):
    def request_nonce(self, scope: Scope) -> bytes: ...
    def get_dek(self, scope: Scope, proof: dict[str, object]) -> bytes: ...
    def lock(self, scope: Scope) -> None: ...
    def status(self) -> dict[str, object]: ...


class FakeBroker:
    def __init__(self, *, locked: bool = False) -> None:
        self.locked = locked
        self.locked_scopes: list[Scope] = []

    def request_nonce(self, scope: Scope) -> bytes:
        if self.locked:
            raise BrokerError("locked", "scope is locked")
        return f"nonce:{scope}".encode()

    def get_dek(self, scope: Scope, proof: dict[str, object]) -> bytes:
        if self.locked or proof.get("counter") != 1:
            raise BrokerError("no-proof", "proof is required")
        return DEK

    def lock(self, scope: Scope) -> None:
        self.locked_scopes.append(scope)
        self.locked = True

    def status(self) -> dict[str, object]:
        return {"owner_unlocked": not self.locked}


class ErrorBroker:
    def request_nonce(self, scope: Scope) -> bytes:
        raise BrokerError("no-proof", "proof required")

    def get_dek(self, scope: Scope, proof: dict[str, object]) -> bytes:
        raise AssertionError("get_dek should not be called")

    def lock(self, scope: Scope) -> None:
        return None

    def status(self) -> dict[str, object]:
        return {"owner_unlocked": False}


def prover(scope: str, nonce: bytes, counter: int) -> dict[str, object]:
    return {
        "scope": scope,
        "nonce": base64.b64encode(nonce).decode(),
        "counter": counter,
        "deviceId": "mock-device",
        "signature": "mock-signature",
    }


def test_broker_key_provider_zeroizes_secret_key_after_lock_all() -> None:
    broker = FakeBroker()
    provider = BrokerKeyProvider(_as_client(broker), prover)

    secret = provider.dek_for_scope("owner-private")

    assert isinstance(secret, SecretKey)
    assert secret.as_hex() == DEK.hex()
    provider.lock_all()
    assert secret.as_hex() == ("00" * 32)
    assert broker.locked_scopes == ["owner-private"]


def test_broker_key_provider_maps_locked_broker_to_scope_locked_error() -> None:
    provider = BrokerKeyProvider(_as_client(ErrorBroker()), prover)

    with pytest.raises(ScopeLockedError):
        provider.dek_for_scope("owner-private")


def test_broker_key_provider_status_uses_broker_status() -> None:
    broker = FakeBroker()
    provider = BrokerKeyProvider(_as_client(broker), prover)

    assert provider.is_owner_unlocked() is True
    broker.locked = True
    assert provider.is_owner_unlocked() is False


@pytest.mark.skipif(AF_UNIX is None, reason="AF_UNIX sockets are unavailable")
def test_broker_client_request_nonce_then_get_dek(tmp_path: Path) -> None:
    server = FakeUnixBrokerServer(tmp_path / "broker.sock")
    server.start()
    try:
        client = BrokerClient(server.socket_path)
        nonce = client.request_nonce("owner-private")
        dek = client.get_dek("owner-private", prover("owner-private", nonce, 1))
    finally:
        server.stop()

    assert nonce == b"nonce-1"
    assert dek == DEK


@pytest.mark.skipif(AF_UNIX is None, reason="AF_UNIX sockets are unavailable")
def test_broker_client_raises_broker_error_reply(tmp_path: Path) -> None:
    server = FakeUnixBrokerServer(tmp_path / "broker.sock")
    server.start()
    try:
        client = BrokerClient(server.socket_path)
        with pytest.raises(BrokerError) as raised:
            client.get_dek("owner-private", {"counter": 1})
    finally:
        server.stop()

    assert raised.value.code == "no-nonce"


class FakeUnixBrokerServer:
    def __init__(self, socket_path: Path) -> None:
        self.socket_path = socket_path
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._nonce_used = False
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def start(self) -> None:
        self._thread.start()
        assert self._ready.wait(timeout=5)

    def stop(self) -> None:
        self._stop.set()
        try:
            assert AF_UNIX is not None
            with socket.socket(AF_UNIX, socket.SOCK_STREAM) as client:
                client.connect(str(self.socket_path))
                _send_frame(client, {"op": "status"})
        except OSError:
            pass
        self._thread.join(timeout=5)

    def _serve(self) -> None:
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.socket_path.unlink()
        except FileNotFoundError:
            pass
        assert AF_UNIX is not None
        with socket.socket(AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(str(self.socket_path))
            server.listen()
            self._ready.set()
            while not self._stop.is_set():
                connection, _ = server.accept()
                with connection:
                    request = _recv_frame(connection)
                    _send_frame(connection, self._handle(request))

    def _handle(self, request: dict[str, object]) -> dict[str, object]:
        op = request.get("op")
        if op == "requestNonce":
            self._nonce_used = False
            return {"nonce": base64.b64encode(b"nonce-1").decode()}
        if op == "getDEK":
            proof = request.get("proof")
            if self._nonce_used:
                return {"error": {"code": "replay", "message": "nonce was already used"}}
            if not isinstance(proof, dict):
                return {"error": {"code": "no-nonce", "message": "request nonce first"}}
            if proof.get("counter") != 1:
                return {"error": {"code": "bad-proof", "message": "invalid proof"}}
            self._nonce_used = True
            return {"dek": base64.b64encode(DEK).decode()}
        if op == "lock":
            return {"ok": True}
        if op == "status":
            return {"owner_unlocked": True}
        return {"error": {"code": "unknown-op", "message": "unknown operation"}}


def _recv_frame(sock: socket.socket) -> dict[str, object]:
    length = int.from_bytes(_recv_exact(sock, 4), "big")
    decoded = json.loads(_recv_exact(sock, length).decode())
    assert isinstance(decoded, dict)
    return decoded


def _send_frame(sock: socket.socket, payload: dict[str, object]) -> None:
    encoded = json.dumps(payload).encode()
    sock.sendall(len(encoded).to_bytes(4, "big") + encoded)


def _recv_exact(sock: socket.socket, length: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < length:
        chunk = sock.recv(length - len(chunks))
        if not chunk:
            raise OSError("socket closed")
        chunks.extend(chunk)
    return bytes(chunks)


def _as_client(client: BrokerLike) -> BrokerClient:
    return client  # type: ignore[return-value]
