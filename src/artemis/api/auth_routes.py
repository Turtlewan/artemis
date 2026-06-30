"""Authenticated `/app/*` HTTP surface for the Artemis client."""

from __future__ import annotations

import base64
import binascii
import hmac
import secrets
import time
from typing import cast

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from artemis.api.auth import AppAuth, AuthError, DeviceRegistry, Principal, require_session

PAIRING_CODE_TTL_SECONDS = 600
RATE_LIMIT_ATTEMPTS = 5
RATE_LIMIT_WINDOW_SECONDS = 900.0
_RATE_LIMIT_EXEMPT_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})

app_router = APIRouter(prefix="/app")


class PairingCodeStore:
    """Single-slot hashed pairing-code store."""

    def __init__(self, ttl_seconds: int = PAIRING_CODE_TTL_SECONDS) -> None:
        self._ttl_seconds = ttl_seconds
        self._code_hash: str | None = None
        self._expires_at = 0.0

    @property
    def stored_hash(self) -> str | None:
        """Return the stored SHA-256 hex digest for tests and diagnostics."""
        return self._code_hash

    def mint(self) -> str:
        """Mint one short-lived code, invalidating any previous code."""
        code = secrets.token_urlsafe(9)
        self._code_hash = _sha256_hex(code)
        self._expires_at = time.time() + self._ttl_seconds
        return code

    def consume(self, code: str) -> bool:
        """Consume the code exactly once when it matches and is unexpired."""
        code_hash = self._code_hash
        if code_hash is None or self._expires_at <= time.time():
            self._clear()
            return False
        if not hmac.compare_digest(_sha256_hex(code), code_hash):
            return False
        self._clear()
        return True

    def _clear(self) -> None:
        self._code_hash = None
        self._expires_at = 0.0


class RateLimiter:
    """In-memory sliding-window limiter keyed by client peer IP."""

    def __init__(
        self,
        attempts: int = RATE_LIMIT_ATTEMPTS,
        window_seconds: float = RATE_LIMIT_WINDOW_SECONDS,
    ) -> None:
        self._attempts = attempts
        self._window_seconds = window_seconds
        self._hits: dict[str, list[float]] = {}

    def check(self, key: str) -> bool:
        """Return True when ``key`` is still inside its allowed attempt budget."""
        now = time.monotonic()
        live = [hit for hit in self._hits.get(key, []) if now - hit < self._window_seconds]
        if len(live) >= self._attempts:
            self._hits[key] = live
            return False
        live.append(now)
        self._hits[key] = live
        return True


class PairRequest(BaseModel):
    """Unauthenticated pairing bootstrap request."""

    device_id: str
    public_key_b64: str
    pairing_code: str
    code_signature_b64: str


class SessionBeginRequest(BaseModel):
    """Begin an API-session challenge for a known device."""

    device_id: str


class SessionBeginResponse(BaseModel):
    """Base64 session nonce response."""

    nonce_b64: str


class SessionCompleteRequest(BaseModel):
    """Complete API-session challenge response."""

    device_id: str
    nonce_b64: str
    counter: int
    signature_b64: str


class SessionCompleteResponse(BaseModel):
    """Opaque bearer token returned after API-session authentication."""

    session_token: str
    expires_at: float


class UnlockBeginRequest(BaseModel):
    """No-op unlock-begin body."""


class UnlockBeginResponse(BaseModel):
    """Base64 no-op unlock nonce response."""

    nonce_b64: str


class UnlockCompleteRequest(BaseModel):
    """No-op unlock-complete body."""

    nonce_b64: str
    counter: int
    signature_b64: str


class StatusResponse(BaseModel):
    """Authenticated app status."""

    connected: bool
    vault_unlocked: bool
    device_id: str


async def rate_limited(request: Request) -> None:
    """FastAPI dependency enforcing the peer-IP sliding-window budget."""
    host = request.client.host if request.client is not None else "unknown"
    if host in _RATE_LIMIT_EXEMPT_HOSTS:
        return
    limiter = cast(RateLimiter, request.app.state.rate_limiter)
    if not limiter.check(host):
        raise HTTPException(status_code=429, detail="too many attempts")


@app_router.post("/admin/pair-code")
async def admin_pair_code(request: Request) -> dict[str, str]:
    """Mint a raw pairing code for localhost callers only."""
    host = request.client.host if request.client is not None else ""
    if host not in {"127.0.0.1", "::1"}:
        raise HTTPException(status_code=403, detail="loopback only")
    store = cast(PairingCodeStore, request.app.state.pairing_codes)
    return {"code": store.mint()}


@app_router.post("/pair", dependencies=[Depends(rate_limited)])
async def pair(request: Request, body: PairRequest) -> dict[str, bool]:
    """Pair a new app device after code and key-possession verification."""
    _verify_pairing_signature(body)
    codes = cast(PairingCodeStore, request.app.state.pairing_codes)
    if not codes.consume(body.pairing_code):
        raise HTTPException(status_code=401, detail="invalid pairing")

    auth = cast(AppAuth, request.app.state.app_auth)
    registry: DeviceRegistry = auth.registry
    try:
        registry.register(body.device_id, body.public_key_b64)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail="invalid pairing") from exc
    return {"paired": True}


@app_router.post(
    "/session/begin",
    response_model=SessionBeginResponse,
    dependencies=[Depends(rate_limited)],
)
async def session_begin(request: Request, body: SessionBeginRequest) -> SessionBeginResponse:
    """Begin an unauthenticated API-session challenge."""
    auth = cast(AppAuth, request.app.state.app_auth)
    try:
        nonce = auth.begin_session(body.device_id)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail="authentication failed") from exc
    return SessionBeginResponse(nonce_b64=_b64encode(nonce))


@app_router.post(
    "/session/complete",
    response_model=SessionCompleteResponse,
    dependencies=[Depends(rate_limited)],
)
async def session_complete(
    request: Request, body: SessionCompleteRequest
) -> SessionCompleteResponse:
    """Complete API-session authentication and return a bearer token."""
    auth = cast(AppAuth, request.app.state.app_auth)
    try:
        session = auth.complete_session(
            body.device_id,
            _b64decode(body.nonce_b64),
            body.counter,
            _b64decode(body.signature_b64),
        )
    except (AuthError, binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=401, detail="authentication failed") from exc
    return SessionCompleteResponse(session_token=session.token, expires_at=session.expires_at)


@app_router.post(
    "/unlock/begin",
    response_model=UnlockBeginResponse,
    dependencies=[Depends(rate_limited)],
)
async def unlock_begin(
    _body: UnlockBeginRequest,
    _principal: Principal = Depends(require_session),
) -> UnlockBeginResponse:
    """Return a no-op unlock nonce; v2 has no vault lock concept."""
    return UnlockBeginResponse(nonce_b64=_b64encode(secrets.token_bytes(32)))


@app_router.post("/unlock/complete", dependencies=[Depends(rate_limited)])
async def unlock_complete(
    _body: UnlockCompleteRequest,
    _principal: Principal = Depends(require_session),
) -> dict[str, bool]:
    """Complete no-op unlock; v2 has no vault lock concept."""
    return {"unlocked": True}


@app_router.get("/status", response_model=StatusResponse)
async def status(
    principal: Principal = Depends(require_session),
) -> StatusResponse:
    """Return authenticated session and no-lock vault status."""
    return StatusResponse(connected=True, vault_unlocked=True, device_id=principal.device_id)


@app_router.post("/lock")
async def lock(
    _principal: Principal = Depends(require_session),
) -> dict[str, bool]:
    """No-op lock endpoint; v2 has no vault lock concept."""
    return {"locked": True}


@app_router.post("/logout")
async def logout(
    request: Request,
    _principal: Principal = Depends(require_session),
) -> dict[str, bool]:
    """Revoke the current API-session token."""
    auth = cast(AppAuth, request.app.state.app_auth)
    auth.logout(_bearer_token(request))
    return {"ok": True}


def _verify_pairing_signature(body: PairRequest) -> None:
    try:
        public_key_bytes = _b64decode(body.public_key_b64)
        signature = _b64decode(body.code_signature_b64)
        public_key = ec.EllipticCurvePublicKey.from_encoded_point(
            ec.SECP256R1(),
            public_key_bytes,
        )
        code_bytes = body.pairing_code.encode("utf-8")
        message = len(code_bytes).to_bytes(2, "big") + code_bytes + body.device_id.encode("utf-8")
        public_key.verify(signature, message, ec.ECDSA(hashes.SHA256()))
    except (ValueError, binascii.Error, InvalidSignature) as exc:
        raise HTTPException(status_code=401, detail="invalid pairing") from exc


def _b64encode(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.b64decode(value, validate=True)


def _sha256_hex(value: str) -> str:
    digest = hashes.Hash(hashes.SHA256())
    digest.update(value.encode("utf-8"))
    return digest.finalize().hex()


def _bearer_token(request: Request) -> str:
    authorization = request.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or token == "":
        raise HTTPException(status_code=401, detail="unauthenticated")
    return token
