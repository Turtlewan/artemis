---
slice: client-revival
status: ready
coder_effort: high
---

# CR-2 — Auth handshake (pair → session), no-lock vault

**Identity:** Second client-revival slice — port the v1 P-256 device-pairing + API-session auth so the Tauri client actually connects. Per owner decision (2026-06-30) the **vault/unlock layer is dropped** ("no lock concept"): `/app/status` reports `vault_unlocked: true`, and `/app/unlock/*` + `/app/lock` are no-op 200s. The crypto must match the prebuilt client byte-for-byte, so the implementation is a faithful port of `archive/v1` per the precise reference in **`docs/findings/cr-2-auth-port-reference.md`** — read that doc; it has the exact signing schemes, the verbatim classes, the dep replacements, the wire-model table, and a ported real-signing pytest.

## Files to change

1. `pyproject.toml` — **modify**: add `cryptography>=42`.
2. `src/artemis/file_lock.py` — **create**: port verbatim from `archive/v1:src/artemis/file_lock.py` (msvcrt/fcntl cross-platform lock; the Windows branch matters on the dev box).
3. `src/artemis/api/auth.py` — **create**: the auth core ported from `archive/v1:src/artemis/identity/app_auth.py` (`DeviceRegistry`, `ChallengeStore`, `SessionStore`, `AppAuth`, `Principal`, `RegisteredDevice`, `Session`, `require_session`, `_load_public_key`, `_verify_pairing_signature`, b64/sha256/bearer helpers) **with the no-lock adaptations** below.
4. `src/artemis/api/auth_routes.py` — **create**: the pydantic wire models + an `APIRouter` with the auth routes, ported from the auth portion of `archive/v1:src/artemis/api_app.py` (`PairingCodeStore`, `RateLimiter`, the `/app/*` auth handlers).
5. `src/artemis/api/app.py` — **modify**: instantiate the auth components in `create_app(data_dir=...)`, store on `app.state`, include the auth router, and make `/app/status` reflect real auth (require session; `connected=True`, `vault_unlocked=True`).
6. `tests/test_api.py` — **modify**: the CR-1 `/app/status` test now expects **401 without a session** (status requires auth, matching v1).
7. `tests/test_api_auth.py` — **create**: the ported real-signing test (P-256 keygen → pair → session begin/complete → authenticated `/app/status` → 200; plus replay + counter-regression rejection).

This is a port slice (6 cohesive files + a 1-line test tweak); larger than the 3-file heuristic but one logical phase. Flagged, not split — the crypto core, its routes, the lock util, and the test are one unit.

## Exact changes

> The authoritative implementation detail is in `docs/findings/cr-2-auth-port-reference.md`. Reproduce the v1 code faithfully (it is what the client signs against). Below are the **adaptations** that differ from a verbatim copy.

### Signing schemes (must match exactly — from the reference)
- **Pairing sig** (`/app/pair`): verify `code_signature_b64` over `len(code)u16be || code_utf8 || device_id_utf8` (code length-prefixed; trailing `device_id` is **not**).
- **Session sig** (`/app/session/complete`): verify `signature_b64` over `len(nonce)u16be || nonce || len(b"session")u16be || b"session" || counter_u64be`, `API_SESSION_CONTEXT = b"session"`.
- Both: `ec.SECP256R1()`, `ec.ECDSA(hashes.SHA256())`, DER signature, pubkey loaded via `ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), raw65)` where `raw65` = base64-decoded **X9.63 uncompressed point** (NOT SPKI/DER).
- `device_id` is a free-form client string (the registry key), **not** derived from the pubkey.
- Counter strictly increases per device; nonces are single-use (120s TTL); session tokens are opaque `secrets.token_urlsafe(32)`.

### No-lock adaptations (the deltas from v1)
- **Drop everything vault/unlock/Scope/broker/DPAPI/Hello.** `AppAuth.lock()` is removed; `SessionStore.revoke_all` may stay but is **not** wired to any lock path. No `UnlockProvider`, `require_unlocked`, or `Scope` anywhere.
- **`/app/unlock/begin` + `/app/unlock/complete`** → return `200` with an empty/echo body (no-op); they do **not** verify anything.
- **`/app/lock`** → no-op `200` (does not revoke the session — there is no lock concept).
- **`/app/status`** → `Depends(require_session)`; returns `StatusResponse(connected=True, vault_unlocked=True, device_id=<principal.device_id>)`. Without a valid bearer → `401` (via `require_session`).
- **`/app/logout`** → real (revoke the current session token).

### Dependency replacements (v1-only modules that don't exist in v2)
1. `artemis.gateway.OWNER_PERSON_ID/OWNER_SCOPE` → inline `OWNER_PERSON_ID = "owner"` in `auth.py`; **drop** `OWNER_SCOPE`. Any `resolve_person()` → `return "owner"`.
2. `artemis.ports.types.PersonId/Scope` → use plain `str` for person id; **drop** `Scope` entirely.
3. `artemis.file_lock` → the new `src/artemis/file_lock.py` (ported verbatim, step 2).

### `create_app` wiring (`api/app.py`)
- Signature becomes `create_app(*, data_dir: str | Path | None = None) -> FastAPI`. Resolve `data_dir` from the arg, else `os.environ.get("ARTEMIS_DATA_DIR", ".")`. Device registry file lives at `<data_dir>/devices.json`.
- Instantiate `DeviceRegistry`, `ChallengeStore`, `SessionStore`, `PairingCodeStore`, `RateLimiter`, `AppAuth`; store the auth bundle on `app.state` so `require_session` and the routes can reach it (follow the v1 `app.state` pattern).
- `include_router` the auth router from `auth_routes.py`. Keep `/healthz` as-is.
- The admin pair-code mint route (`POST /app/admin/pair-code`, **loopback-only** guard) is ported so the owner can mint a code to type into the client's PairingScreen.

### Tests
- Port the real-signing test from the reference doc into `tests/test_api_auth.py` (it generates a P-256 key, X9.63-encodes the pubkey, pairs, runs the session handshake, and calls an authenticated route). Use `TestClient` bound to a loopback client host so the `RateLimiter` is exempt, exactly as the reference shows.
- Update the `/app/status` test in `tests/test_api.py`: unauthenticated `GET /app/status` now returns **401** (was 200 in the CR-1 skeleton).

## Acceptance criteria

1. **Full handshake works end-to-end** — pair → session/begin → session/complete (real P-256 DER sig over the exact framing) → authenticated `GET /app/status` returns `200 {"connected":true,"vault_unlocked":true,"device_id":"..."}`. (`test_api_auth.py`)
2. **Replay/counter protection** — reusing a nonce, or a counter ≤ the device's last, is rejected (`401`/`400`). (`test_api_auth.py`)
3. **Unauthenticated status → 401** (`tests/test_api.py` updated).
4. **No-lock behavior** — `/app/unlock/begin`, `/app/unlock/complete`, `/app/lock` return `200` no-ops; status always reports `vault_unlocked: true`.
5. **Pairing-code mint** — `POST /app/admin/pair-code` from loopback returns a code; a wrong/forged pairing signature is rejected at `/app/pair`.
6. Full-project verify green: `uv run mypy` (strict) + `uv run pytest -q` + `uv run ruff check` + `uv run ruff format --check`.

## Commands to run

```bash
uv sync
uv run ruff format src/artemis/file_lock.py src/artemis/api tests/test_api.py tests/test_api_auth.py
uv run ruff check src/artemis/file_lock.py src/artemis/api tests/test_api.py tests/test_api_auth.py
uv run mypy
uv run pytest -q
```
