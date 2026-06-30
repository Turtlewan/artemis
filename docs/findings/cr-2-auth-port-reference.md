# CR-2 Auth Port Reference — Artemis v1 → v2 brain (device pairing + API session)

Port target: re-implement the v1 app-auth (device pairing + API-session challenge/response)
in the v2 brain so it verifies EXACTLY what the prebuilt Tauri client signs with its per-device
P-256 key. **NO-LOCK decision:** the vault/unlock/Scope layer is dropped — `vault_unlocked`
is always `true`, unlock endpoints become no-op `200`s.

Source (read via `git show archive/v1:<path>`, v1 is deleted from disk):
- `src/artemis/identity/app_auth.py` — crypto core (DeviceRegistry, ChallengeStore, SessionStore, AppAuth)
- `src/artemis/api_app.py` — wire models, stores, dependencies, route handlers
- `src/artemis/file_lock.py` — cross-platform advisory file lock
- `tests/test_api_app.py` — the `Phone` signing helper + flow tests (gold reference)

---

## 1. Exact signing schemes (THE load-bearing contract)

Both signatures: curve **SECP256R1 (P-256 / prime256v1)**, hash **SHA-256**, signature
encoding **DER** (`cryptography`'s `private_key.sign()` default), verified with
`public_key.verify(signature, message, ec.ECDSA(hashes.SHA256()))`.

All length prefixes are **u16 big-endian** (`len(x).to_bytes(2, "big")`); the counter is
**u64 big-endian** (`counter.to_bytes(8, "big")`).

### 1a. Pairing-code signature (`/app/pair`, field `code_signature_b64`)
Verified by `_verify_pairing_signature` in `api_app.py`. Message framing:

```
message = len(code)u16be || code_utf8 || device_id_utf8
```

- `code` = the pairing code string, UTF-8 encoded (`body.pairing_code.encode("utf-8")`).
- `device_id` = the device id string, UTF-8 encoded, **appended raw with NO length prefix**
  (it is the trailing field).
- NOTE the asymmetry: the code IS length-prefixed, the device_id is NOT.

### 1b. Session-nonce signature (`/app/session/complete`, field `signature_b64`)
Verified by `AppAuth.complete_session` in `app_auth.py`. Context constant
`API_SESSION_CONTEXT = b"session"`. Message framing:

```
message = len(nonce)u16be || nonce || len(b"session")u16be || b"session" || counter_u64be
```

- `nonce` = the raw 32 bytes issued by `/app/session/begin` (base64-decoded from `nonce_b64`).
- counter is u64be, 8 bytes, MUST strictly increase per device (`counter <= device.counter` → reject).

### Public-key encoding & device_id derivation
- **Public key wire format = X9.63 / SEC1 uncompressed point, base64-encoded.** The client
  produces it via `public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)`
  then base64. That is the 65-byte `0x04 || X(32) || Y(32)` form, base64 → `public_key_b64`.
- Brain loads it with `ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), raw_bytes)`
  (NOT SPKI/DER — do not use `load_der_public_key`).
- **`device_id` is NOT derived from the pubkey.** It is a free-form client-supplied string
  (the v1 tests use the literal `"phone"`). The registry is keyed by this string; the pubkey
  is stored as a value. There is no fingerprint/hash derivation step to port.

---

## 2. What to port verbatim vs what to drop

### Port verbatim (the crypto core, `app_auth.py`)
- **`DeviceRegistry`** — port ALL methods: `register`, `get`, `list`, `remove`, `bump_counter`,
  `_read_all`, `_write_all`. Atomic JSON store keyed by device_id, fields
  `{public_key_b64, counter, paired_at}`. `register` validates the key by loading it and resets
  counter to 0. Keep the `file_lock` + temp-file `os.replace` atomic write.
- **`ChallengeStore`** — port ALL: `issue` (32-byte `secrets.token_bytes`, single slot per device,
  120s TTL), `consume` (constant-time `hmac.compare_digest`, single-use, expiry-drop), `_sweep`.
- **`SessionStore`** — port `create` (opaque `secrets.token_urlsafe(32)` token, 3600s TTL), `get`
  (expiry-drop on read), `revoke`. **`revoke_all`** survives only as the `logout`-adjacent
  reset; its v1 caller was vault-lock — under no-lock there is no lock trigger, so it becomes
  dead unless wired to `/app/logout`-all. Keep it (cheap), just don't call it from a lock path.
- **`AppAuth`** — port `__init__`, `begin_session` (constant-work: issue nonce, then check device
  exists, consume-and-raise if not — preserves anti-enumeration timing), `complete_session`
  (the full verify: device exists → consume nonce → counter strictly-increasing → rebuild frame
  → `verify()` → `bump_counter` → mint session), `logout`. **DROP `lock()`** (vault-lock revoke-all).
- **`Principal`** — keep, but simplify: under no-lock, `person_id` is a constant (see §3).
  Fields `person_id`, `device_id`.
- **`RegisteredDevice`, `Session`** dataclasses — port verbatim.
- **`require_session`** dependency — port verbatim (bearer parse → `app_auth.sessions.get`).
- **`_load_public_key`** — port verbatim (base64 validate → `from_encoded_point`).
- Exceptions `AuthError`, `InvalidDeviceKeyError` — port.

### Drop entirely
- `resolve_scope` / `Scope` everywhere (no-lock = no scopes).
- `AppAuth.lock()`, `SessionStore.revoke_all` as a lock hook.
- All broker/DPAPI/Secure-Enclave/`UnlockProvider`/`begin_unlock`/`complete_unlock`/`dek_for_scope`
  /`is_owner_unlocked`/`lock_all` machinery.
- `require_unlocked` dependency → collapses to `require_session` (vault always unlocked).
- `Hello`/Identity/`Scope` resolution.

---

## 3. v1-only dependencies to replace

| v1 import | Replacement | Reason |
|---|---|---|
| `from artemis.gateway import OWNER_PERSON_ID, OWNER_SCOPE` | **Inline a constant.** `OWNER_PERSON_ID` traces to `artemis.identity.scope.OWNER_PERSON_ID = PersonId("owner")`. Inline `OWNER_PERSON_ID = "owner"` (or drop `Principal.person_id` to the literal `"owner"`). **Drop `OWNER_SCOPE`** (`= "owner-private"`) — no Scope under no-lock. | Single-owner box; person is always `"owner"`. |
| `from artemis.ports.types import PersonId, Scope` | **`PersonId` → inline a plain `str` (or `PersonId = str` NewType in v2 `types.py`).** **`Scope` → drop.** | v2 `types.py` has neither; no-lock removes Scope. |
| `from artemis.file_lock import file_lock` | **Port the util verbatim** to `src/artemis/identity/file_lock.py` (or reuse if a v2 copy exists — none currently). It is self-contained: `msvcrt.locking` on Windows, `fcntl.flock` on POSIX, locks a sidecar `<target>.lock`. | DeviceRegistry's atomic write needs it; dev box is Windows so the `msvcrt` branch matters. |

`resolve_person(device_id)` collapses to `return "owner"` (constant). `_sha256_hex` (pairing-code
hashing) uses `cryptography.hazmat.primitives.hashes` — port verbatim or swap to stdlib `hashlib`.

---

## 4. Exact wire models (request/response JSON), with no-lock behavior

All routes under prefix `/app`. Rate-limited routes carry `Depends(rate_limited)` (5 attempts /
900s sliding window per peer IP; loopback `127.0.0.1`/`::1`/`localhost` exempt).

| Route | Method / auth | Request JSON | Response JSON | No-lock note |
|---|---|---|---|---|
| `/app/admin/pair-code` | POST, **loopback-only** (403 otherwise) | `{}` | `{"code": "<urlsafe>"}` | mints a 600s pairing code (hashed single-slot store) |
| `/app/pair` | POST, unauth, rate-limited | `{device_id, public_key_b64, pairing_code, code_signature_b64}` | `{"paired": true}` | drop broker relay; just `registry.register`. 401 on bad sig/code |
| `/app/session/begin` | POST, unauth, rate-limited | `{device_id}` | `{nonce_b64}` | unchanged. 401 if device unknown (constant-work) |
| `/app/session/complete` | POST, unauth, rate-limited | `{device_id, nonce_b64, counter, signature_b64}` | `{session_token, expires_at}` | unchanged. 401 on bad sig / replay / non-increasing counter |
| `/app/status` | GET, `require_session` | — | `{connected: true, vault_unlocked: true, device_id}` | **`vault_unlocked` HARD-CODED `true`** |
| `/app/lock` | POST, `require_session` | — | `{"locked": true}` | **no-op 200** (no key_provider.lock_all) |
| `/app/logout` | POST, `require_session` | — | `{"ok": true}` | `auth.logout(bearer_token)` — keep (revokes this session) |
| `/app/unlock/begin` | POST, `require_session` | `{}` | `{nonce_b64}` | **no-op**: return a throwaway nonce (e.g. `secrets.token_bytes(32)`), 200 |
| `/app/unlock/complete` | POST, `require_session` | `{nonce_b64, counter, signature_b64}` | `{"unlocked": true}` | **no-op 200**; ignore body / don't relay to a broker |

Bearer scheme: `Authorization: Bearer <session_token>`. Missing/malformed → 401 `unauthenticated`.

Wire-model classes to recreate (pydantic `BaseModel`): `PairRequest`, `SessionBeginRequest`,
`SessionBeginResponse`, `SessionCompleteRequest`, `SessionCompleteResponse`, `StatusResponse`,
plus `UnlockBeginRequest`/`UnlockBeginResponse`/`UnlockCompleteRequest` reduced to no-op shapes.
Helpers to port: `_b64encode`, `_b64decode` (base64 `validate=True`), `_sha256_hex`, `_bearer_token`,
`_verify_pairing_signature`, `PairingCodeStore`, `RateLimiter`.

---

## 5. Ported pytest (real P-256 flow)

Adapted from v1 `tests/test_api_app.py` (`Phone` + `_pair`/`_session_token`). Drops broker/vault.
Place at e.g. `tests/test_app_auth.py`. Assumes the ported module exposes `app_router`,
`AppAuth`, `DeviceRegistry`, `ChallengeStore`, `SessionStore`, `PairingCodeStore`, `RateLimiter`,
`require_session`, `API_SESSION_CONTEXT`.

```python
"""Real-P256 device-pairing + API-session flow for the no-lock v2 brain."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import cast

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from artemis.identity.app_auth import (
    API_SESSION_CONTEXT,
    AppAuth,
    ChallengeStore,
    DeviceRegistry,
    Principal,
    SessionStore,
    require_session,
)
from artemis.api.app_auth_routes import (  # wherever the router lands
    PairingCodeStore,
    RateLimiter,
    app_router,
)


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


def _b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _app(tmp_path: Path) -> FastAPI:
    app = FastAPI()
    app.include_router(app_router)

    @app.post("/guarded")
    async def guarded(_principal: Principal = Depends(require_session)) -> dict[str, bool]:
        return {"ok": True}

    registry = DeviceRegistry(tmp_path / "identity" / "devices.json")
    app.state.app_auth = AppAuth(registry, ChallengeStore(), SessionStore())
    app.state.pairing_codes = PairingCodeStore()
    app.state.rate_limiter = RateLimiter()
    return app


def _client(tmp_path: Path) -> TestClient:
    return TestClient(_app(tmp_path), client=("127.0.0.1", 5000))


def test_pair_session_and_authenticated_call(tmp_path: Path) -> None:
    client = _client(tmp_path)
    phone = Phone()
    device_id = "phone"

    # 1. mint a pairing code (loopback admin route) and pair the device.
    code = cast(dict[str, str], client.post("/app/admin/pair-code").json())["code"]
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

    # 2. begin -> sign nonce -> complete -> bearer token.
    begin = client.post("/app/session/begin", json={"device_id": device_id})
    assert begin.status_code == 200
    nonce = base64.b64decode(cast(dict[str, str], begin.json())["nonce_b64"])
    complete = client.post(
        "/app/session/complete",
        json={
            "device_id": device_id,
            "nonce_b64": _b64(nonce),
            "counter": 1,
            "signature_b64": phone.sign_session(nonce, 1),
        },
    )
    assert complete.status_code == 200
    token = cast(dict[str, object], complete.json())["session_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 3. authenticated endpoint succeeds with the bearer token; bare call 401s.
    assert client.post("/guarded").status_code == 401
    assert client.post("/guarded", headers=headers).status_code == 200

    # 4. no-lock: status reports vault_unlocked True; unlock routes are no-op 200.
    status = client.get("/app/status", headers=headers)
    assert status.status_code == 200
    assert status.json()["vault_unlocked"] is True
    assert client.post("/app/lock", headers=headers).json() == {"locked": True}


def test_replay_and_counter_rejected(tmp_path: Path) -> None:
    client = _client(tmp_path)
    phone = Phone()
    code = cast(dict[str, str], client.post("/app/admin/pair-code").json())["code"]
    client.post(
        "/app/pair",
        json={
            "device_id": "phone",
            "public_key_b64": phone.public_key_b64,
            "pairing_code": code,
            "code_signature_b64": phone.sign_pairing(code, "phone"),
        },
    )
    # A stale/unknown nonce never matches the single-slot challenge -> 401.
    replay = client.post(
        "/app/session/complete",
        json={
            "device_id": "phone",
            "nonce_b64": _b64(b"missing-nonce-bytes-not-issued"),
            "counter": 2,
            "signature_b64": phone.sign_session(b"missing-nonce-bytes-not-issued", 2),
        },
    )
    assert replay.status_code == 401
```

> Loopback `TestClient(client=("127.0.0.1", 5000))` keeps the rate limiter exempt so the
> pair→begin→complete handshake doesn't 429 (v1 ADR-033 loopback exemption — port it).

---

## 6. `cryptography` primitives used (add the dep)

`cryptography` is **NOT** in v2 `pyproject.toml` (`dependencies = [...]`) — **add `cryptography>=42`**
(or current). `fastapi`/`uvicorn`/`pydantic` are already present.

Primitives:
- `from cryptography.hazmat.primitives.asymmetric import ec`
  - `ec.SECP256R1()` — the curve.
  - `ec.generate_private_key(ec.SECP256R1())` — test-side key gen (client side only).
  - `ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), raw)` — load X9.63 uncompressed point.
  - `ec.ECDSA(hashes.SHA256())` — the signature algorithm passed to `verify`.
- `from cryptography.hazmat.primitives import hashes`
  - `hashes.SHA256()` — digest for ECDSA and for `_sha256_hex` (`hashes.Hash(...).update(...).finalize().hex()`).
- `from cryptography.hazmat.primitives import serialization` (test/client side only)
  - `serialization.Encoding.X962`, `serialization.PublicFormat.UncompressedPoint` — produce the
    65-byte pubkey the brain expects.
- `from cryptography.exceptions import InvalidSignature` — caught → `AuthError` / 401.
- `public_key.verify(signature_der, message, ec.ECDSA(hashes.SHA256()))` — DER ECDSA verify.
- stdlib: `hmac.compare_digest` (constant-time nonce/code compare), `secrets.token_bytes(32)` /
  `secrets.token_urlsafe(32)` / `secrets.token_urlsafe(9)` (nonce / session token / pairing code).

---

_Findings doc: `docs/findings/cr-2-auth-port-reference.md`_
