"""Brain-side app authentication for Artemis client sessions."""

from __future__ import annotations

import base64
import binascii
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, cast

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException, Request

from artemis.file_lock import file_lock

API_SESSION_CONTEXT: Final[bytes] = b"session"
OWNER_PERSON_ID: Final[str] = "owner"


class AuthError(Exception):
    """Generic authentication failure that avoids device enumeration."""


class InvalidDeviceKeyError(AuthError):
    """Raised when a registered public key is not a valid P-256 point."""


@dataclass(frozen=True)
class Principal:
    """Authenticated client principal resolved from a device."""

    person_id: str
    device_id: str


@dataclass(frozen=True)
class RegisteredDevice:
    """Public-key device record for API-session challenge response."""

    device_id: str
    public_key_b64: str
    counter: int
    paired_at: str


@dataclass(frozen=True)
class Session:
    """Opaque revocable API session."""

    token: str
    principal: Principal
    expires_at: float


class DeviceRegistry:
    """Atomic JSON store for public device records outside encrypted scopes."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def register(self, device_id: str, public_key_b64: str) -> RegisteredDevice:
        """Upsert a device with a fresh pairing timestamp and counter reset."""
        _load_public_key(public_key_b64)
        with file_lock(self._path):
            device = RegisteredDevice(
                device_id=device_id,
                public_key_b64=public_key_b64,
                counter=0,
                paired_at=datetime.now(UTC).isoformat(),
            )
            devices = self._read_all()
            devices[device_id] = device
            self._write_all(devices)
            return device

    def get(self, device_id: str) -> RegisteredDevice | None:
        """Return a registered device, or None if absent."""
        return self._read_all().get(device_id)

    def list(self) -> list[RegisteredDevice]:
        """Return all registered devices sorted by device id."""
        devices = self._read_all()
        return [devices[device_id] for device_id in sorted(devices)]

    def remove(self, device_id: str) -> None:
        """Remove a device if present."""
        with file_lock(self._path):
            devices = self._read_all()
            if device_id in devices:
                del devices[device_id]
                self._write_all(devices)

    def bump_counter(self, device_id: str, new_counter: int) -> None:
        """Persist a caller-validated strictly greater counter."""
        with file_lock(self._path):
            devices = self._read_all()
            device = devices.get(device_id)
            if device is None:
                raise AuthError
            devices[device_id] = RegisteredDevice(
                device_id=device.device_id,
                public_key_b64=device.public_key_b64,
                counter=new_counter,
                paired_at=device.paired_at,
            )
            self._write_all(devices)

    def _read_all(self) -> dict[str, RegisteredDevice]:
        if not self._path.exists():
            return {}
        try:
            raw: object = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return {}
        if not isinstance(raw, dict):
            return {}
        devices: dict[str, RegisteredDevice] = {}
        for device_id, record in raw.items():
            if not isinstance(device_id, str) or not isinstance(record, dict):
                continue
            raw_record = cast(dict[object, object], record)
            public_key_b64 = raw_record.get("public_key_b64")
            counter = raw_record.get("counter")
            paired_at = raw_record.get("paired_at")
            if (
                isinstance(public_key_b64, str)
                and isinstance(counter, int)
                and isinstance(paired_at, str)
            ):
                devices[device_id] = RegisteredDevice(
                    device_id=device_id,
                    public_key_b64=public_key_b64,
                    counter=counter,
                    paired_at=paired_at,
                )
        return devices

    def _write_all(self, devices: dict[str, RegisteredDevice]) -> None:
        self._path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        payload = {
            device_id: {
                "public_key_b64": device.public_key_b64,
                "counter": device.counter,
                "paired_at": device.paired_at,
            }
            for device_id, device in sorted(devices.items())
        }
        temp_path = self._path.with_name(f".{self._path.name}.{secrets.token_hex(8)}.tmp")
        temp_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, self._path)


class ChallengeStore:
    """Single-slot per-device challenge store with constant-time nonce compare."""

    def __init__(self, ttl_seconds: int = 120) -> None:
        self._ttl_seconds = ttl_seconds
        self._challenges: dict[str, tuple[bytes, float]] = {}

    def issue(self, device_id: str) -> bytes:
        """Issue a fresh 32-byte nonce, replacing any live nonce for the device."""
        self._sweep()
        nonce = secrets.token_bytes(32)
        self._challenges[device_id] = (nonce, time.time() + self._ttl_seconds)
        return nonce

    def consume(self, device_id: str, nonce: bytes) -> bool:
        """Consume an unexpired matching nonce exactly once."""
        self._sweep()
        entry = self._challenges.get(device_id)
        if entry is None:
            return False
        stored_nonce, expiry = entry
        if expiry <= time.time():
            del self._challenges[device_id]
            return False
        if not hmac.compare_digest(stored_nonce, nonce):
            return False
        del self._challenges[device_id]
        return True

    def _sweep(self) -> None:
        now = time.time()
        expired = [
            device_id for device_id, (_, expiry) in self._challenges.items() if expiry <= now
        ]
        for device_id in expired:
            del self._challenges[device_id]


class SessionStore:
    """In-memory opaque API-session store."""

    def __init__(self, ttl_seconds: int = 3600) -> None:
        self._ttl_seconds = ttl_seconds
        self._sessions: dict[str, Session] = {}

    def create(self, principal: Principal) -> Session:
        """Create and store a revocable opaque session token."""
        token = secrets.token_urlsafe(32)
        session = Session(
            token=token,
            principal=principal,
            expires_at=time.time() + self._ttl_seconds,
        )
        self._sessions[token] = session
        return session

    def get(self, token: str) -> Session | None:
        """Return a live session, dropping expired entries on read."""
        session = self._sessions.get(token)
        if session is None:
            return None
        if session.expires_at <= time.time():
            del self._sessions[token]
            return None
        return session

    def revoke(self, token: str) -> None:
        """Revoke a session if present."""
        self._sessions.pop(token, None)

    def revoke_all(self) -> None:
        """Revoke every API session."""
        self._sessions.clear()


class AppAuth:
    """Challenge-response API-session authenticator."""

    def __init__(
        self,
        registry: DeviceRegistry,
        challenges: ChallengeStore,
        sessions: SessionStore,
    ) -> None:
        self.registry = registry
        self.challenges = challenges
        self.sessions = sessions

    def begin_session(self, device_id: str) -> bytes:
        """Issue a challenge for a known device using constant work."""
        nonce = self.challenges.issue(device_id)
        if self.registry.get(device_id) is None:
            self.challenges.consume(device_id, nonce)
            raise AuthError
        return nonce

    def complete_session(
        self,
        device_id: str,
        nonce: bytes,
        counter: int,
        signature: bytes,
    ) -> Session:
        """Verify a DER ECDSA signature and mint an opaque API session."""
        device = self.registry.get(device_id)
        if device is None:
            raise AuthError
        if not self.challenges.consume(device_id, nonce):
            raise AuthError
        if counter <= device.counter:
            raise AuthError
        try:
            counter_bytes = counter.to_bytes(8, "big")
        except OverflowError as exc:
            raise AuthError from exc
        public_key = _load_public_key(device.public_key_b64)
        ctx = API_SESSION_CONTEXT
        message = (
            len(nonce).to_bytes(2, "big")
            + nonce
            + len(ctx).to_bytes(2, "big")
            + ctx
            + counter_bytes
        )
        try:
            public_key.verify(signature, message, ec.ECDSA(hashes.SHA256()))
        except InvalidSignature as exc:
            raise AuthError from exc
        self.registry.bump_counter(device_id, counter)
        return self.sessions.create(
            Principal(person_id=resolve_person(device_id), device_id=device_id)
        )

    def logout(self, token: str) -> None:
        """Revoke one API session."""
        self.sessions.revoke(token)


def resolve_person(device_id: str) -> str:
    """Resolve a registered device to its person for the single-owner client."""
    _ = device_id
    return OWNER_PERSON_ID


async def require_session(request: Request) -> Principal:
    """FastAPI dependency returning the authenticated API-session principal."""
    authorization = request.headers.get("authorization")
    if authorization is None:
        raise HTTPException(status_code=401, detail="unauthenticated")
    scheme, separator, token = authorization.partition(" ")
    if separator == "" or scheme.lower() != "bearer" or token == "":
        raise HTTPException(status_code=401, detail="unauthenticated")
    auth = cast(AppAuth, request.app.state.app_auth)
    session = auth.sessions.get(token)
    if session is None:
        raise HTTPException(status_code=401, detail="unauthenticated")
    return session.principal


def _load_public_key(public_key_b64: str) -> ec.EllipticCurvePublicKey:
    try:
        encoded = base64.b64decode(public_key_b64, validate=True)
        return ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), encoded)
    except (ValueError, binascii.Error) as exc:
        raise InvalidDeviceKeyError from exc
