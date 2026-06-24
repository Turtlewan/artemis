"""Broker-backed key provider for owner-scope data encryption keys."""

from __future__ import annotations

import atexit
import base64
import ctypes
import ctypes.util
import json
import logging
import socket
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from artemis.identity.key_provider import ScopeLockedError, SecretKey
from artemis.ports.types import Scope

LOGGER = logging.getLogger(__name__)
FRAME_LENGTH_BYTES = 4
DEK_LENGTH_BYTES = 32
AF_UNIX = cast(socket.AddressFamily | None, getattr(socket, "AF_UNIX", None))


class BrokerError(Exception):
    """Typed error returned by the broker IPC endpoint."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


class _SecureBuffer:
    """Zeroizable byte buffer with best-effort page locking."""

    def __init__(self, data: bytes) -> None:
        self._buffer = bytearray(data)
        self._locked = _try_lock(self._buffer)

    @property
    def bytes(self) -> bytes:
        return bytes(self._buffer)

    def wipe(self) -> None:
        for index in range(len(self._buffer)):
            self._buffer[index] = 0

    def release(self) -> None:
        if self._locked:
            try:
                _try_unlock(self._buffer)
            finally:
                self._locked = False


@dataclass
class _CachedKey:
    secret: SecretKey
    secure_buffer: _SecureBuffer
    expires_at: float

    def wipe(self) -> None:
        self.secret.wipe()
        self.secure_buffer.wipe()
        self.secure_buffer.release()


def _buffer_address(buffer: bytearray) -> tuple[ctypes.c_void_p, int]:
    view = (ctypes.c_char * len(buffer)).from_buffer(buffer)
    return ctypes.c_void_p(ctypes.addressof(view)), len(buffer)


def _try_lock(buffer: bytearray) -> bool:
    if not buffer:
        return True
    address, length = _buffer_address(buffer)
    try:
        if sys.platform == "win32":
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.VirtualLock.argtypes = (ctypes.c_void_p, ctypes.c_size_t)
            kernel32.VirtualLock.restype = ctypes.c_int
            locked = kernel32.VirtualLock(address, ctypes.c_size_t(length)) != 0
        else:
            libc_name = ctypes.util.find_library("c")
            if libc_name is None:
                LOGGER.debug("secure buffer page locking unavailable: libc not found")
                return False
            libc = ctypes.CDLL(libc_name, use_errno=True)
            libc.mlock.argtypes = (ctypes.c_void_p, ctypes.c_size_t)
            libc.mlock.restype = ctypes.c_int
            locked = libc.mlock(address, ctypes.c_size_t(length)) == 0
    except OSError as exc:
        LOGGER.debug("secure buffer page locking unavailable: %s", exc.__class__.__name__)
        return False
    if not locked:
        LOGGER.debug("secure buffer page locking unavailable for this process")
    return bool(locked)


def _try_unlock(buffer: bytearray) -> None:
    if not buffer:
        return
    address, length = _buffer_address(buffer)
    try:
        if sys.platform == "win32":
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.VirtualUnlock.argtypes = (ctypes.c_void_p, ctypes.c_size_t)
            kernel32.VirtualUnlock.restype = ctypes.c_int
            kernel32.VirtualUnlock(address, ctypes.c_size_t(length))
        else:
            libc_name = ctypes.util.find_library("c")
            if libc_name is None:
                return
            libc = ctypes.CDLL(libc_name, use_errno=True)
            libc.munlock.argtypes = (ctypes.c_void_p, ctypes.c_size_t)
            libc.munlock.restype = ctypes.c_int
            libc.munlock(address, ctypes.c_size_t(length))
    except OSError as exc:
        LOGGER.debug("secure buffer page unlock failed: %s", exc.__class__.__name__)


class BrokerClient:
    """Synchronous length-prefixed-JSON client for the local key broker."""

    def __init__(self, socket_path: Path) -> None:
        self._socket_path = socket_path

    def request_nonce(self, scope: Scope) -> bytes:
        """Request a single-use broker nonce for ``scope``."""
        reply = self._request({"op": "requestNonce", "scope": scope})
        nonce_b64 = _string_field(reply, "nonce")
        return base64.b64decode(nonce_b64)

    def get_dek(self, scope: Scope, proof: dict[str, object]) -> bytes:
        """Exchange a proof for the raw 32-byte data encryption key."""
        reply = self._request({"op": "getDEK", "scope": scope, "proof": proof})
        dek = base64.b64decode(_string_field(reply, "dek"))
        if len(dek) != DEK_LENGTH_BYTES:
            raise BrokerError("invalid-dek", "broker returned an invalid DEK length")
        return dek

    def lock(self, scope: Scope) -> None:
        """Ask the broker to lock ``scope``."""
        self._request({"op": "lock", "scope": scope})

    def status(self) -> dict[str, object]:
        """Return broker status as a JSON object."""
        return self._request({"op": "status"})

    def _request(self, payload: dict[str, object]) -> dict[str, object]:
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        frame = len(encoded).to_bytes(FRAME_LENGTH_BYTES, "big") + encoded
        if AF_UNIX is None:
            raise BrokerError("unsupported-platform", "AF_UNIX sockets are unavailable")
        with socket.socket(AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.connect(str(self._socket_path))
            sock.sendall(frame)
            length_bytes = _recv_exact(sock, FRAME_LENGTH_BYTES)
            length = int.from_bytes(length_bytes, "big")
            body = _recv_exact(sock, length)
        decoded = json.loads(body.decode("utf-8"))
        if not isinstance(decoded, dict):
            raise BrokerError("invalid-response", "broker returned a non-object response")
        reply: dict[str, object] = decoded
        error = reply.get("error")
        if isinstance(error, dict):
            code = error.get("code")
            message = error.get("message")
            raise BrokerError(
                code if isinstance(code, str) else "broker-error",
                message if isinstance(message, str) else "broker request failed",
            )
        return reply


class BrokerKeyProvider:
    """KeyProvider implementation backed by the local owner key broker."""

    def __init__(
        self,
        client: BrokerClient,
        prover: Callable[[str, bytes, int], dict[str, object]],
        *,
        session_seconds: float = 600.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client
        self._prover = prover
        self._session_seconds = session_seconds
        self._clock = clock
        self._cache: dict[Scope, _CachedKey] = {}
        self._counter = 0
        atexit.register(self.lock_all)

    def dek_for_scope(self, scope: Scope) -> SecretKey:
        """Return an unlocked SecretKey for ``scope`` or raise ScopeLockedError."""
        now = self._clock()
        cached = self._cache.get(scope)
        if cached is not None and cached.expires_at > now:
            return cached.secret
        if cached is not None:
            cached.wipe()
            del self._cache[scope]

        try:
            nonce = self._client.request_nonce(scope)
            self._counter += 1
            proof = self._prover(scope, nonce, self._counter)
            dek = self._client.get_dek(scope, proof)
        except BrokerError as exc:
            if _is_locked_error(exc):
                raise ScopeLockedError(f"Scope is locked: {scope}") from exc
            raise

        secure_buffer = _SecureBuffer(dek)
        try:
            secret = SecretKey(secure_buffer.bytes)
        finally:
            dek_shadow = bytearray(dek)
            for index in range(len(dek_shadow)):
                dek_shadow[index] = 0
            del dek
        self._cache[scope] = _CachedKey(
            secret=secret,
            secure_buffer=secure_buffer,
            expires_at=now + self._session_seconds,
        )
        return secret

    def is_owner_unlocked(self) -> bool:
        """Return true only when broker status reports an unlocked owner session."""
        try:
            status = self._client.status()
        except BrokerError:
            return False
        owner_unlocked = status.get("owner_unlocked", status.get("unlocked"))
        if isinstance(owner_unlocked, bool):
            return owner_unlocked
        state = status.get("status")
        return isinstance(state, str) and state.lower() == "unlocked"

    def lock_all(self) -> None:
        """Zeroize local cached keys and ask the broker to lock each cached scope."""
        cached_scopes = list(self._cache)
        for scope in cached_scopes:
            cached = self._cache.pop(scope)
            cached.wipe()
            try:
                self._client.lock(scope)
            except BrokerError as exc:
                LOGGER.debug("broker lock failed for scope %s: %s", scope, exc.code)


def _is_locked_error(error: BrokerError) -> bool:
    normalized = error.code.replace("_", "-").lower()
    return normalized in {"locked", "scope-locked", "no-proof", "proof-required", "unauthorized"}


def _recv_exact(sock: socket.socket, length: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < length:
        chunk = sock.recv(length - len(chunks))
        if not chunk:
            raise BrokerError("truncated-frame", "broker closed the connection mid-frame")
        chunks.extend(chunk)
    return bytes(chunks)


def _string_field(reply: dict[str, object], name: str) -> str:
    value = reply.get(name)
    if not isinstance(value, str):
        raise BrokerError("invalid-response", f"broker response missing {name}")
    return value
