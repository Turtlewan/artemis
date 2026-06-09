---
spec: client-a-app-auth-core
status: ready
token_profile: balanced
autonomy_level: L2
---

# Spec: CLIENT-a — Brain app-auth core (device registry + challenge-response API sessions + `require_session` dependency + gateway scope-from-session)

**Identity:** Implements the brain-side authentication for the client app over the Tailscale tunnel: a public-key device registry (readable pre-unlock), a P-256 challenge-response that mints short-lived revocable API sessions reusing M2-a's SE-signed-keypair + strictly-increasing-counter primitive, the FastAPI `require_session` dependency, and the Gateway scope-from-session seam that replaces M1-c's hard-coded owner constant.
→ why: see docs/technical/adr/ADR-010-client-app-auth.md (one key/two authorities; session ≠ vault-unlock; scope-from-session) · docs/technical/architecture/app-flow.md (connection/lock states).

<!-- Split rule: ONE logical phase (the app-auth core + its two integration points). 1 create + 1 test + 2 small modifies (paths.py = a single new function; gateway.py = a scoped entrypoint that the M1-c constant path now delegates to). The gateway touch is in-scope because brain.md mandates scope is attached AT the Gateway before the Brain — the resolution seam belongs there, not in the endpoint layer (CLIENT-b). Justified atomic unit; flagged per rules. Pairing-bootstrap, unlock-relay, and the HTTP app routes are CLIENT-b; this spec is pure auth logic + the FastAPI dependency. -->

## Assumptions
- M0-a (`Settings`, `paths.slot_root(s)`, `get_settings()`), M0-d (`PersonId = NewType("PersonId", str)`, `Scope`), M1-b (`Brain.respond(text, scope) -> BrainResponse`, `Brain.respond_stream`), M1-c (`Gateway` with `OWNER_PERSON_ID`, `OWNER_SCOPE`, `handle_text`, `handle_text_stream`, `compose_brain`) are complete. → impact: Stop (signatures must match exactly; this spec extends them).
- The phone holds a **non-exportable P-256 Secure-Enclave keypair** (CLIENT-c) and exports its **public key as an X9.63 uncompressed point** (65 bytes, `0x04 ‖ X ‖ Y`), base64-encoded — exactly the form `SecKeyCopyExternalRepresentation` yields and the form M2-a's `pair --pubkey <base64>` already accepts. The brain loads it via `ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), b64decode(...))`. → impact: Stop (key encoding must match the Swift export + M2-a's pairing format).
- The API-session assertion signs `nonce ‖ b"artemis-api-session" ‖ counter(8-byte big-endian)` with **ECDSA-P256-SHA256** (`.ecdsaSignatureMessageX962SHA256` on the phone → a DER signature; `public_key.verify(sig_der, msg, ec.ECDSA(SHA256()))` on the brain). The domain-separation context `b"artemis-api-session"` makes an API nonce un-replayable as a vault nonce (which signs `nonce ‖ scope ‖ counter`, M2-a). → impact: Stop (signature shape is the wire contract CLIENT-c implements).
- The **API-session counter is a separate namespace** from the broker's vault-unlock counter (ADR-010 — two counters, one key). The DeviceRegistry tracks the API-session counter; the broker tracks its own. → impact: Caution (do not share counter state between the brain registry and the broker).
- Sessions are **server-side and in-memory** (a process-local store); a brain restart drops all sessions → the app re-authenticates (a fast Face-ID handshake). No session persistence is required (revocation-on-lock is the security property; durability is not). → impact: Low (acceptable per ADR-010 §6; documented).
- The device registry holds **public keys only** (not secret) and must be readable **before any vault unlock** (it authenticates the unlock itself) → it lives in `slot_root(s)/identity/devices.json`, NOT in a per-scope encrypted vault. → impact: Stop (placing it in an encrypted scope would make it unreadable when needed).
- `cryptography` (pyca) is the P-256 verification library. → impact: Low (well-known, actively maintained; not a typosquat).

Simplicity check: considered JWTs for sessions — rejected; ADR-010 requires instant revocation on vault lock, which opaque server-side sessions give for free (delete the row) and JWTs do not (blocklist needed). Considered storing the registry in SQLite — rejected; a single-owner handful of devices is a small atomic JSON file (same pattern as M7-b `RecurrenceStore`, M2-a `DEKStore`). Considered putting scope resolution in the endpoint layer — rejected; brain.md mandates scope is attached at the Gateway before the Brain, so the seam belongs on the Gateway.

## Prerequisites
- Specs that must be complete first: M0-a, M0-d, M1-b, M1-c. (CLIENT-a is pure logic + a FastAPI dependency; it does NOT itself mount routes or bind a host — that is CLIENT-b.)
- Environment setup required: `uv add cryptography` (P-256 verification). Fully off-hardware testable (an in-test `cryptography` P-256 keypair stands in for the phone — no SE, no broker, no network).

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| /Users/artemis-build/artemis/src/artemis/identity/app_auth.py | create | `Principal`, `RegisteredDevice`, `DeviceRegistry`, `ChallengeStore`, `Session`, `SessionStore`, `AppAuth`, `resolve_scope`, `require_session` dependency factory, typed errors |
| /Users/artemis-build/artemis/src/artemis/paths.py | modify | add `identity_dir(s: Settings) -> Path` (= `slot_root(s) / "identity"`) + `devices_file(s) -> Path` |
| /Users/artemis-build/artemis/src/artemis/gateway.py | modify | add `handle_text_scoped(text, scope)` + `handle_text_stream_scoped(text, scope)`; refactor `handle_text`/`handle_text_stream` to delegate with `OWNER_SCOPE` (M1-c callers unchanged) |
| /Users/artemis-build/artemis/tests/test_app_auth.py | create | registry round-trip, challenge-response happy path + the 4 failure modes, session create/get/expire/revoke/revoke_all, scope resolution, gateway scoped delegation |

## Tasks
- [ ] Task 1: Add the identity-dir path helpers — files: `/Users/artemis-build/artemis/src/artemis/paths.py` — add pure typed functions `def identity_dir(s: Settings) -> Path` = `slot_root(s) / "identity"` and `def devices_file(s: Settings) -> Path` = `identity_dir(s) / "devices.json"`. Return paths only; do NOT create dirs (mirrors the existing M0-a path functions). Document in the docstring: the identity dir holds public-key device records ONLY (not secret) and is readable before any vault unlock. — done when: `uv run mypy --strict src` passes; `identity_dir(get_settings())` returns `<data_root>/<slot>/identity`.

- [ ] Task 2: Implement the device registry + challenge + session stores — files: `/Users/artemis-build/artemis/src/artemis/identity/app_auth.py` —
  - `PersonId` imported from `artemis.ports.types`; `Scope` likewise.
  - `@dataclass(frozen=True) class Principal { person_id: PersonId, device_id: str }`.
  - `@dataclass(frozen=True) class RegisteredDevice { device_id: str, public_key_b64: str, counter: int, paired_at: str }` (`paired_at` ISO-8601 UTC; `public_key_b64` = base64 X9.63 point; `counter` = last-accepted API-session counter, starts at 0).
  - `class DeviceRegistry` constructed with `(path: Path)`:
    - `def register(self, device_id: str, public_key_b64: str) -> RegisteredDevice`: **idempotent upsert** — write/overwrite the record for `device_id` with `counter=0` and a fresh `paired_at`; validate the key decodes to a valid P-256 point (`ec.EllipticCurvePublicKey.from_encoded_point` — raise `InvalidDeviceKeyError` on failure) before persisting. Atomic write (same-dir temp + `os.replace`; create `identity_dir` if absent with mode `0700`). Re-registering an existing `device_id` resets its counter to 0 (a re-pair is a fresh key). **Cross-spec invariant:** a re-pair resets the API-session counter to 0 on BOTH sides — here (brain registry) AND in CLIENT-c's `Authenticator.pair` (the phone's keychain `apiCounter`/`unlockCounter`) — so the two never diverge after a re-pair.
    - `def get(self, device_id: str) -> RegisteredDevice | None`; `def list(self) -> list[RegisteredDevice]`; `def remove(self, device_id: str) -> None` (idempotent).
    - `def bump_counter(self, device_id: str, new_counter: int) -> None`: persist `new_counter` for the device (caller has already checked it is strictly greater). Corrupt/missing file → treated as empty.
  - `class ChallengeStore` constructed with `(ttl_seconds: int = 120)`: **at most ONE live challenge per device** (single-slot, not a multi-entry dict) — store `device_id -> (nonce, expiry)`. `def issue(self, device_id: str) -> bytes` — generate a 32-byte nonce (`secrets.token_bytes(32)`), **overwrite** the device's slot unconditionally (a new challenge invalidates any prior outstanding one for that device — closes the offline-enumeration/unbounded-growth window, apex-auth BLOCK), return the nonce; `def consume(self, device_id: str, nonce: bytes) -> bool` — return True iff the device's slot holds an unexpired nonce equal (via `hmac.compare_digest` — constant-time) to the supplied one, then clear the slot (single-use). Run a full sweep of expired slots on each `issue`/`consume` (bounded by device count, not request count).
  - `@dataclass(frozen=True) class Session { token: str, principal: Principal, expires_at: float }`.
  - `class SessionStore` constructed with `(ttl_seconds: int = 3600)`: `def create(self, principal: Principal) -> Session` — opaque `secrets.token_urlsafe(32)` token, store `token -> Session`; `def get(self, token: str) -> Session | None` — None if absent OR expired (drop on read); `def revoke(self, token: str) -> None`; `def revoke_all(self) -> None` (called on vault lock — clears every session).
  - Errors: `class AuthError(Exception)` (generic — never distinguishes "unknown device" vs "bad signature" to a caller, to avoid enumeration), `class InvalidDeviceKeyError(AuthError)`.
  — done when: `uv run mypy --strict src` passes; `DeviceRegistry.register` then `get` round-trips across two instances over the same path; `register` on a non-P256 key raises `InvalidDeviceKeyError`; `ChallengeStore.consume` returns True once then False on replay; `SessionStore.get` returns None after `revoke`/`revoke_all` and after TTL expiry.

- [ ] Task 3: Implement the challenge-response AppAuth + scope resolution — files: `/Users/artemis-build/artemis/src/artemis/identity/app_auth.py` (same file) —
  - `API_SESSION_CONTEXT: Final[bytes] = b"artemis-api-session"`.
  - `class AppAuth` constructed with `(registry: DeviceRegistry, challenges: ChallengeStore, sessions: SessionStore)`:
    - `def begin_session(self, device_id: str) -> bytes`: **constant-work to avoid a device-enumeration timing oracle** (apex-security BLOCK) — ALWAYS `nonce = challenges.issue(device_id)` first; then if `registry.get(device_id) is None`, discard the slot (`challenges.consume(device_id, nonce)` to clear) and `raise AuthError` (generic); else return the nonce. Both the known- and unknown-device paths do the same issue work, so response latency does not reveal device existence. (The per-device single-slot store means an unknown-device probe cannot accrete nonces.)
    - `def complete_session(self, device_id: str, nonce: bytes, counter: int, signature: bytes) -> Session`: load the device (None → `AuthError`); `if not challenges.consume(device_id, nonce): raise AuthError`; `if counter <= device.counter: raise AuthError` (strictly-increasing, the passkey-clone check); reconstruct `msg = nonce + API_SESSION_CONTEXT + counter.to_bytes(8, "big")`; load the public key (`from_encoded_point(SECP256R1(), b64decode(device.public_key_b64))`) and `public_key.verify(signature, msg, ec.ECDSA(hashes.SHA256()))` — any `InvalidSignature`/exception → `raise AuthError`; on success `registry.bump_counter(device_id, counter)` and return `sessions.create(Principal(person_id=resolve_person(device_id), device_id=device_id))`. NEVER log the nonce, signature, or token.
    - `def logout(self, token: str) -> None`: `sessions.revoke(token)`.
    - `def lock(self) -> None`: `sessions.revoke_all()` (invoked when the vault locks — CLIENT-b wires this to the lock path).
  - `def resolve_person(device_id: str) -> PersonId`: M-client single-owner → return `OWNER_PERSON_ID` (imported from `artemis.gateway`) for any registered device. (The seam: future multi-person resolution keys off the device → person mapping here.)
  - `def resolve_scope(principal: Principal) -> Scope`: M-client single-owner → return `OWNER_SCOPE` (imported from `artemis.gateway`). The future guest/multi-person wall replaces this body; callers are unchanged.
  - `def require_session(auth: AppAuth) -> Callable[..., Awaitable[Principal]]`: returns an async FastAPI dependency `dep(request: Request) -> Principal` that reads the `Authorization: Bearer <token>` header (missing/malformed → `HTTPException(status_code=401, detail="unauthenticated")`), looks up `auth.sessions.get(token)` (None → `HTTPException(401)`), and returns `session.principal`. Constant 401 detail (no enumeration). — done when: `uv run mypy --strict src` passes; a full begin→sign(test key)→complete returns a `Session`; a replayed nonce, a non-increasing counter, a wrong-key signature, and an unknown device each raise `AuthError`; `resolve_scope(any_principal)` returns `OWNER_SCOPE`.

- [ ] Task 4: Add the Gateway scope-from-session seam — files: `/Users/artemis-build/artemis/src/artemis/gateway.py` — add `async def handle_text_scoped(self, request_text: str, scope: Scope) -> BrainResponse` (calls `await self.brain.respond(request_text, scope)`) and `async def handle_text_stream_scoped(self, request_text: str, scope: Scope) -> AsyncIterator[str]` (the streamed variant, mirroring `handle_text_stream`). Refactor the existing `handle_text`/`handle_text_stream` to **delegate**: `return await self.handle_text_scoped(request_text, OWNER_SCOPE)` (and the stream equivalent) — so the M1-c CLI/loopback path is unchanged in behaviour but the scoped seam now exists for CLIENT-b's authenticated endpoints. Do NOT change `pre_route` or `compose_brain`. — done when: `uv run mypy --strict src` passes; `handle_text("hi")` still returns the same `BrainResponse` as before (delegation is behaviour-preserving — asserted against a FakeBrain that records the scope it received = `OWNER_SCOPE`).

- [ ] Task 5: Write the app-auth tests — files: `/Users/artemis-build/artemis/tests/test_app_auth.py` — typed pytest. Build an in-test phone: generate an `ec.generate_private_key(ec.SECP256R1())`, export its public key as an X9.63 point (`public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)`) → base64 (this is the exact CLIENT-c export contract). A helper `sign(priv, nonce, counter) -> bytes` returns `priv.sign(nonce + b"artemis-api-session" + counter.to_bytes(8,"big"), ec.ECDSA(hashes.SHA256()))`. Tests:
  - registry: `register(dev, pub)` then `get(dev)` round-trips over a fresh `DeviceRegistry(tmp_path/...)`; `register` of a garbage key raises `InvalidDeviceKeyError`; `remove` is idempotent.
  - happy path: `begin_session` → `sign(priv, nonce, 1)` → `complete_session(dev, nonce, 1, sig)` returns a `Session`; `sessions.get(session.token).principal.device_id == dev`; the registry counter is now 1.
  - replay nonce: a second `complete_session` with the same nonce raises `AuthError`.
  - counter monotonicity: after counter 1 accepted, `complete_session(..., counter=1, ...)` (fresh nonce) raises `AuthError`; counter=2 succeeds. **Boundary: a fresh device (stored counter 0) presenting `counter=0` raises `AuthError`** (the strictly-greater check rejects `0 <= 0`).
  - timing/enumeration: `begin_session("unknown")` raises `AuthError` AND leaves the ChallengeStore empty (the discarded slot was cleared) — no nonce accretes for an unknown device.
  - bad signature: a signature from a DIFFERENT private key raises `AuthError`.
  - unknown device: `begin_session("nope")` raises `AuthError`.
  - session lifetime: `SessionStore(ttl_seconds=0)` → `get` returns None immediately; `revoke`/`revoke_all` drop sessions.
  - scope: `resolve_scope(Principal(OWNER_PERSON_ID, dev)) == OWNER_SCOPE`.
  - gateway delegation: a `FakeBrain` recording its received scope → `Gateway(FakeBrain()).handle_text("hi")` passed `OWNER_SCOPE`; `handle_text_scoped("hi", "general")` passed `"general"`.
  — done when: `uv run pytest -q tests/test_app_auth.py` passes AND `uv run mypy --strict src tests/test_app_auth.py` passes.

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | /Users/artemis-build/artemis/src/artemis/identity/app_auth.py, /Users/artemis-build/artemis/tests/test_app_auth.py |
| Modify | /Users/artemis-build/artemis/src/artemis/paths.py, /Users/artemis-build/artemis/src/artemis/gateway.py |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv add cryptography` | P-256 signature verification |
| `uv run mypy --strict src tests/test_app_auth.py` | Type gate |
| `uv run ruff check . ; uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q tests/test_app_auth.py` | Test gate (challenge-response + sessions + scope) |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | src/artemis/identity/app_auth.py, src/artemis/paths.py, src/artemis/gateway.py, tests/test_app_auth.py, pyproject.toml, uv.lock |
| `git commit` | "feat: CLIENT-a brain app-auth core (device registry + P-256 challenge-response sessions + gateway scope-from-session)" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_ENV_FILE` | Slot Settings → `identity_dir`/`devices_file` resolution |

### Network
| Action | Purpose |
|--------|---------|
| `uv add cryptography` | Package install (PyPI) |
| (no outbound at runtime) | Verification is local CPU; no network |

## Specialist Context
### Security
This is the brain-side auth wall (ADR-010). Invariants the build MUST honour: (1) the device registry holds **public keys only** and lives outside any encrypted scope (readable pre-unlock) — it must never hold a secret; (2) the **counter is strictly-increasing per device** (the passkey-clone check — reject `counter <= stored`); (3) **single-use nonces** with a short TTL (replay = reject); (4) sessions are **opaque, server-side, revocable** — `lock()`/`revoke_all` drops every session when the vault locks; (5) **scope is resolved from the authenticated principal, never from a request parameter** (apex-auth hard block #4 — the tenant-from-session invariant); (6) the nonce, signature, and session token are **never logged** (apex-auth hard block #2); (7) auth failures raise a **generic** error / constant 401 (no device/user enumeration, apex-auth hard block #3). The API-session signature is **domain-separated** from the vault `UnlockProof` (`b"artemis-api-session"` vs the scope string) so the two assertion types can never be cross-replayed.

Review resolutions baked in: (8) **constant-time** for all secret comparisons (`hmac.compare_digest` for the challenge nonce — apex-security/Trail-of-Bits timing-side-channel rule); (9) `begin_session` does **constant-work** regardless of device existence (no enumeration timing oracle); (10) the ChallengeStore is **single-slot-per-device** (bounded, no offline-enumeration accretion). **No circular import:** `app_auth` imports `OWNER_SCOPE`/`OWNER_PERSON_ID` from `gateway`, and `gateway` (Task 4) does NOT import `app_auth` (it only adds scoped methods); `require_session` is consumed by CLIENT-b's routes, not by `gateway`. [FLAG apex-security + apex-auth: verify the counter check (incl. the `0<=0` boundary), single-slot single-use nonce, constant-work begin_session, domain-separation, and no-secret-in-registry at review.]

### Performance
P-256 verify is sub-millisecond; in-memory challenge/session dicts are O(1). The challenge TTL (120 s) and session TTL (3600 s) are config-shaped constants — tune at integration, not load-bearing.

### Accessibility
(none — brain-side; the lock/unlock/onboarding UX is CLIENT-c/d.)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | src/artemis/identity/app_auth.py | Type + docstring all exports; document the challenge-response wire contract (`nonce ‖ context ‖ counter`, X9.63 key, DER sig), the counter/nonce/session invariants, and the scope-from-session seam |
| ADR | docs/technical/adr/ADR-010-client-app-auth.md | (already written this session — no code touch) |

## Acceptance Criteria
- [ ] Run `uv run mypy --strict src tests/test_app_auth.py` → verify: exit 0.
- [ ] Run `uv run pytest -q tests/test_app_auth.py` → verify: happy-path challenge-response mints a session; replay-nonce, non-increasing-counter, wrong-key-signature, and unknown-device each raise `AuthError`; `revoke_all` drops sessions; `resolve_scope` returns `OWNER_SCOPE`; gateway delegation passes `OWNER_SCOPE`.
- [ ] Run `uv run python -c "from artemis.identity.app_auth import AppAuth, DeviceRegistry, SessionStore, ChallengeStore, require_session, resolve_scope; from artemis.paths import identity_dir, devices_file"` → verify: exit 0.
- [ ] Run `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.

## Progress
_(Coding mode writes here — do not edit manually)_
