<!-- amended 2026-06-11 per contracts.md (Seam 3) + client.md BLOCKs B1, B2 -->
---
spec: client-b-app-endpoints
status: ready
token_profile: balanced
autonomy_level: L2
---

# Spec: CLIENT-b — Brain app HTTP surface (pairing bootstrap + session + unlock-relay + Review/Chat/Status endpoints + tailnet exposure)

**Identity:** Implements the authenticated HTTP surface the client app talks to over the tailnet: a pairing-bootstrap route (registers the phone key in the brain registry + relays to the broker), session begin/complete routes over CLIENT-a's `AppAuth`, vault unlock-relay routes (broker nonce → phone proof → broker unlock), the Review/Chat/Status app endpoints, the `tailscale serve` exposure, and the `main.py` wiring (mount + app.state + lock lifecycle).
→ why: see docs/technical/adr/ADR-010-client-app-auth.md (pairing/session/unlock handshakes; session ≠ data access) · docs/technical/architecture/app-flow.md (the 3 screens + lock states).

<!-- Split rule: flagged atomic exception (precedent: M1-c bundled gateway+CLI+API+main across 5 files). This is ONE cohesive surface — the app's HTTP face — across 5 files: api_app.py (all routes + the small pairing-code store), broker_client.py (additive: pair + unlock-relay methods), main.py (mount + state + lock lifecycle), setup_tailscale_serve.sh (gated exposure), test_api_app.py. Splitting the routes across two specs would fork main.py (merge risk) + duplicate the TestClient scaffold. Phases are separated in ## Tasks. Consumes CLIENT-a (AppAuth/require_session/resolve_scope), M7-b (ReviewSurface), M1-c (Gateway scoped entrypoints), M2-c (BrokerKeyProvider), CLIENT-broker (the broker `pair` IPC verb the relay calls). -->

## Assumptions
- CLIENT-a complete: `AppAuth` (`begin_session`/`complete_session`/`logout`/`lock`), `DeviceRegistry`, `ChallengeStore`, `SessionStore`, `Principal`, `require_session`, `resolve_scope`, `InvalidDeviceKeyError`/`AuthError`, `paths.identity_dir`/`devices_file`, and the Gateway scoped entrypoints (`handle_text_scoped`/`handle_text_stream_scoped`). → impact: Stop (CLIENT-b composes these; signatures must match).
- M7-b complete: `ReviewSurface` (`auto_enabled()`, `pending_for_review()`, `approve(name)`, `reject(name)` → `RecipeReview`), `RecipeReview` (frozen dataclass: `name`, `description`, `status`, `action_class`, `safety`, `explanation`). → impact: Stop (the Review endpoints serialise `RecipeReview` and call these exactly).
- M2-c complete: `BrokerKeyProvider` (`dek_for_scope`, `is_owner_unlocked()`, `lock_all()`) over a `BrokerClient` (`request_nonce(scope) -> bytes`, `get_dek(scope, proof: dict) -> bytes`, `lock(scope)`, `status() -> dict`); the broker IPC frame is length-prefixed JSON. CLIENT-b adds the `pair` + unlock-relay methods. → impact: Stop (the relay reuses the existing IPC client + DEK cache).
- CLIENT-broker complete (or its off-hardware fake): the broker answers a `{"op":"pair","device_id","public_key"}` IPC frame. Off-hardware, CLIENT-b tests use a **fake broker provider** (no socket), so CLIENT-b is testable standalone; the real round-trip is gated on-hardware. → impact: Caution (live pairing relay needs CLIENT-broker; off-hardware uses fakes — mirrors M2-c's fake-broker test pattern).
- The brain app (M0-b `main.py`) binds `127.0.0.1` and is **unchanged in its host** — the app surface is exposed on the tailnet via **`tailscale serve`** (Tailscale terminates TLS for the MagicDNS name; the only remote ingress; ADR-002 "no public listener"). → impact: Stop (do NOT change the uvicorn `--host`; the exposure is a Tailscale config, gated on-hardware).
- **The session is a reachability token, not a data gate** (ADR-010 §6): data endpoints (Review, Chat) additionally require the **vault unlocked** (`is_owner_unlocked()`), failing **423 Locked** otherwise; Status + unlock + logout need only the session. → impact: Stop (the two-tier guard is the security model).
- The pairing **code** is a short-lived single-use secret the owner mints out-of-band (CLI one-liner) and enters/scans on the phone; the phone proves it by signing `pairing_code ‖ device_id` with the new key. → impact: Caution (binds the new key to an owner-authorised pairing; without it, anyone on the tailnet could register a device).

Simplicity check: considered a websocket for chat — rejected; M1-c already fixed SSE for server→client token streams (apex-realtime default); the app endpoints reuse it. Considered putting pairing/session/unlock in separate specs — rejected; they share `main.py` wiring + the TestClient scaffold (forking them adds merge risk + duplication for thin routes). Considered minting pairing codes via a new CLI file — rejected; the loopback-only `POST /admin/pair-code` route (calling `PairingCodeStore.mint()`) driven by a documented `curl` one-liner avoids a 6th file.

## Prerequisites
- Specs that must be complete first: CLIENT-a, M7-b, M1-c, M2-c. Sequenced-with CLIENT-broker (the broker `pair` IPC verb — off-hardware fakes decouple CLIENT-b's tests; the live pairing relay needs it).
- Environment setup required: none beyond CLIENT-a's `cryptography`. Off-hardware testable via FastAPI `TestClient` + fakes (fake broker provider, in-test phone keypair, fake ReviewSurface/Gateway). The `tailscale serve` exposure + the live broker pairing round-trip are **gated on-hardware**.

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| /Users/artemis-build/artemis/src/artemis/api_app.py | create | `APIRouter` (prefix `/app`): pairing bootstrap, session begin/complete, unlock begin/complete, review (pending/auto-enabled/approve/reject), chat (ask + ask/stream), status, lock, logout; **loopback-only `POST /admin/pair-code`** (pairing-code mint; B2 fix); `PairingCodeStore`; `require_unlocked` dependency (corrected signature: `request: Request` first; B1/Seam 3 fix); pydantic request/response models |
| /Users/artemis-build/artemis/src/artemis/identity/broker_client.py | modify | additive: `BrokerClient.pair(device_id, public_key_b64)`; `BrokerKeyProvider.begin_unlock(scope)`/`complete_unlock(scope, nonce, proof)`; extract a shared `_cache_dek` |
| /Users/artemis-build/artemis/src/artemis/main.py | modify | build `AppAuth` + `BrokerKeyProvider` + `ReviewSurface` at startup → `app.state`; `include_router(app_router)`; wire idle-lock → DEK zeroize (session NOT revoked per ADR-010 §6) |
| /Users/artemis-build/artemis/scripts/setup_tailscale_serve.sh | create | gated on-hardware: `tailscale serve` config exposing `127.0.0.1:{BRAIN_PORT}` on the tailnet (HTTPS, MagicDNS) |
| /Users/artemis-build/artemis/tests/test_api_app.py | create | TestClient: full pair→session→unlock→review/chat/status flow against fakes; lock → 423; auth failures → 401/423 |

## Tasks
- [ ] Task 1: Add the broker pair + unlock-relay methods — files: `/Users/artemis-build/artemis/src/artemis/identity/broker_client.py` (modify, additive) —
  - `def pair(self, device_id: str, public_key_b64: str) -> None` on `BrokerClient`: send a `{"op":"pair","device_id":device_id,"public_key":public_key_b64}` length-prefixed-JSON frame; parse `ok`/`error` (raise `BrokerError` on error). (Calls the CLIENT-broker IPC verb.)
  - On `BrokerKeyProvider`: extract the existing DEK-caching logic from `dek_for_scope` into a private `def _cache_dek(self, scope: Scope, dek: bytes) -> SecretKey` (copy into the mlock'd buffer, cache under the session window, zeroize the transient `dek`) — `dek_for_scope` now calls it; behaviour unchanged.
  - `def begin_unlock(self, scope: Scope) -> bytes`: `nonce = self._client.request_nonce(scope)`; stash `self._pending_nonce[scope] = nonce`; return `nonce`.
  - `def complete_unlock(self, scope: Scope, nonce: bytes, proof: dict[str, object]) -> None`: if NOT `hmac.compare_digest(self._pending_nonce.get(scope, b""), nonce)` (constant-time — apex-security timing rule) raise `BrokerError("stale or unknown unlock nonce")`; `dek = self._client.get_dek(scope, proof)`; `self._cache_dek(scope, dek)`; clear the pending nonce. The phone's `proof` dict is the M2-a `UnlockProof` shape (signature over `nonce ‖ scope ‖ counter`); CLIENT-b does not re-verify it — the broker is the verifier (the brain only relays). NEVER log the proof or DEK.
  — done when: `uv run mypy --strict src` passes; against the M2-c fake broker server, `begin_unlock` returns a nonce and `complete_unlock` with a MockProver-shaped proof results in `is_owner_unlocked()` true; a `complete_unlock` with a mismatched nonce raises `BrokerError`.

- [ ] Task 2: Implement the pairing-code store + rate limiter + the app router models + the unlock/lock/logout/status routes — files: `/Users/artemis-build/artemis/src/artemis/api_app.py` —
  - `app_router = APIRouter(prefix="/app")`.
  - `class PairingCodeStore` (`ttl_seconds: int = 600`): stores ONLY `sha256(code)` (never the raw code — apex-auth invite-token rule), **at most ONE outstanding code** (a new `mint` invalidates any prior unexpired one). `mint() -> str` (a `secrets.token_urlsafe(9)` code; persist its `sha256`, return the raw code to the caller exactly once), `consume(code: str) -> bool` (`hmac.compare_digest(sha256(code), stored_hash)`, unexpired, single-use). The raw code is NEVER logged. **NOT a module-level singleton** — `main.py` constructs it in the lifespan and attaches it to `app.state.pairing_codes`. Concurrency: the app runs a single uvicorn worker (asyncio single-threaded) → no lock needed; state this explicitly.
  - **Pairing-code mint endpoint (B2 fix — the CLI one-liner in a separate process cannot reach `app.state`):** add `POST /admin/pair-code` to the `app_router`. This route is **loopback-restricted** (middleware guard: `if request.client.host not in ("127.0.0.1", "::1"): raise HTTPException(403)`; it is deliberately NOT exposed through `tailscale serve` — it binds to the brain's loopback-only listener). It calls `app.state.pairing_codes.mint()` and returns `{"code": <raw_code>}` over localhost only, so the owner one-liner is `curl -s http://127.0.0.1:${BRAIN_PORT}/app/admin/pair-code -X POST | jq -r .code`. The raw code is printed to stdout on the owner-controlled machine — never logged by the brain. Add the test: `POST /admin/pair-code` from TestClient (loopback) returns a code; the same request with a simulated non-loopback IP (override `request.client.host`) returns 403.
  - `class RateLimiter` (in-memory sliding window, keyed on the Tailscale peer IP from `request.client.host`): `check(key: str) -> bool` allowing **5 attempts / 15-minute window** (apex-auth/apex-security minimum); a dependency `rate_limited(request)` raises `HTTPException(429, "too many attempts")` when exceeded. Applied to the **unauthenticated** routes (`/app/pair`, `/app/session/begin`, `/app/session/complete`) and to `/app/unlock/begin`.
  - pydantic models: `PairRequest {device_id, public_key_b64, pairing_code, code_signature_b64}`; `SessionBeginRequest {device_id}` → `SessionBeginResponse {nonce_b64}`; `SessionCompleteRequest {device_id, nonce_b64, counter, signature_b64}` → `SessionCompleteResponse {session_token, expires_at}`; `UnlockBeginRequest {}` (**no `scope` — derived from the session**) → `UnlockBeginResponse {nonce_b64}`; `UnlockCompleteRequest {nonce_b64, counter, signature_b64}` (**no `scope`**); `StatusResponse {connected: bool, vault_unlocked: bool, device_id: str}`; `AskRequest {text}` / `AskResponse {text, path, tool_used, escalated}`; `ReviewItem` (mirrors `RecipeReview`).
  - `def require_unlocked(request: Request, principal: Principal = Depends(require_session(...))) -> Principal`: **`request: Request` is declared first** (non-default before default — Python requires this; swapping the order was a SyntaxError, Seam 3 B3/B1 fix); declared to **depend on `require_session` via `Depends`** (so FastAPI enforces the session check first — a route annotated with `require_unlocked` alone can NEVER bypass the session gate, apex-security A01); then assert `request.app.state.key_provider.is_owner_unlocked()` is True else `HTTPException(423, "vault locked")`; return the principal. Note: `require_session` is **imported from CLIENT-a** (`from artemis.identity.app_auth import require_session`) — CLIENT-a ships it as a zero-arg dependency `async def require_session(request: Request) -> Principal` that reads `request.app.state.app_auth` internally. CLIENT-b does NOT redefine it; it is used as a plain `Depends(require_session)`.
  - `POST /app/unlock/begin` (require_session, rate_limited): `scope = resolve_scope(principal)` (**from the session — never the client**, apex-auth hard-block #4); `nonce = key_provider.begin_unlock(scope)`; return base64 nonce.
  - `POST /app/unlock/complete` (require_session): `scope = resolve_scope(principal)`; build the `proof` dict from the request (`{device_id: principal.device_id, signature, counter}` per M2-a `UnlockProof`), `key_provider.complete_unlock(scope, b64decode(nonce), proof)`; return `{"unlocked": True}`. Map `BrokerError`→`HTTPException(401, "unlock failed")` (generic).
  - `GET /app/status` (require_session): return `StatusResponse(connected=True, vault_unlocked=key_provider.is_owner_unlocked(), device_id=principal.device_id)`.
  - `POST /app/lock` (require_session): `key_provider.lock_all()` (zeroize DEK; session stays — ADR-010 §6). Return `{"locked": True}`.
  - `POST /app/logout` (require_session): `auth.logout(token)` (revoke this session). Return `{"ok": True}`.
  — done when: `uv run mypy --strict src` passes.

- [ ] Task 3: Implement the pairing-bootstrap + session routes — files: `/Users/artemis-build/artemis/src/artemis/api_app.py` (same file) —
  - `POST /app/pair` (UNAUTHENTICATED bootstrap, rate_limited): **verify key-possession FIRST, consume the code LAST** (so a bad signature never burns a valid code — apex-security DoS fix). Build the signed message with a **length-prefixed** encoding (no `|`-separator ambiguity — apex-security signature-confusion fix): `msg = len(code).to_bytes(2,"big") + code.encode() + req.device_id.encode()`; load the P-256 pubkey from `req.public_key_b64`, `verify(b64decode(req.code_signature_b64), msg, ECDSA(SHA256()))` (fail → `HTTPException(401, "invalid pairing")`). THEN `if not pairing_codes.consume(req.pairing_code): HTTPException(401, "invalid pairing")`. THEN register with **rollback** (apex-security two-store atomicity): `registry.register(req.device_id, req.public_key_b64)`; `try: broker_client.pair(req.device_id, req.public_key_b64) except BrokerError: registry.remove(req.device_id); raise HTTPException(503, "pairing unavailable")` (a failed pair leaves BOTH stores empty → cleanly re-runnable; `pair` is idempotent on success). Return `{"paired": True}`. Generic 401 on any auth failure (no enumeration). NEVER log the code, signature, or pubkey.
  - `POST /app/session/begin` (UNAUTHENTICATED, rate_limited): `nonce = auth.begin_session(req.device_id)` (AuthError → `HTTPException(401)`); return base64 nonce.
  - `POST /app/session/complete` (UNAUTHENTICATED, rate_limited): `session = auth.complete_session(req.device_id, b64decode(req.nonce_b64), req.counter, b64decode(req.signature_b64))` (AuthError → `HTTPException(401, "authentication failed")`); return `{session_token, expires_at}`. **Exclude this response body from any access/response logging** (apex-auth hard-block #2 — the token must never reach a log).
  — done when: `uv run mypy --strict src` passes.

- [ ] Task 4: Implement the Review + Chat routes — files: `/Users/artemis-build/artemis/src/artemis/api_app.py` (same file) —
  - `GET /app/review/pending` (require_unlocked): `[ReviewItem.from_recipe_review(r) for r in review_surface.pending_for_review()]`.
  - `GET /app/review/auto-enabled` (require_unlocked): `review_surface.auto_enabled()` → `[ReviewItem]`.
  - `POST /app/review/approve` (require_unlocked): body `{name}` → `review_surface.approve(name)` → `ReviewItem`. Map `KeyError`/`RecipeAlreadyRetiredError`/`RecipeSignatureError`→`HTTPException(409, "<reason>")`.
  - `POST /app/review/reject` (require_unlocked): body `{name}` → `review_surface.reject(name)` → `ReviewItem`.
  - `POST /app/ask` (require_unlocked): `r = await gateway.handle_text_scoped(req.text, resolve_scope(principal))`; return `AskResponse(text=r.text, path=r.path, tool_used=r.tool_used, escalated=r.escalated)`.
  - `POST /app/ask/stream` (require_unlocked): SSE `StreamingResponse(media_type="text/event-stream")` iterating `gateway.handle_text_stream_scoped(req.text, resolve_scope(principal))` → `data: <chunk>\n\n` frames + terminal `data: [DONE]\n\n` (mirrors M1-c). **Mid-stream lock:** the generator checks `key_provider.is_owner_unlocked()` at each chunk boundary; if the vault locks mid-stream (idle DEK zeroize) it emits a terminal `data: {"error":"vault_locked"}\n\n` frame and closes (fail-closed, client-observable — CLIENT-c/d handle it by re-unlocking) — never a silent truncation.
  — done when: `uv run mypy --strict src` passes.

<!-- LINT-DEFER 2026-06-11: WARN CLIENT-b:78 — ReviewSurface composition ("reuse the existing brain composition where possible") is exploratory; the exact M7-a/M7-b/M1-b factory symbol to call is not known from the CLIENT specs alone. Naming the wrong factory would be a guess; needs the M7-a/M7-b author or a codebase check to pin the constructor. -->
- [ ] Task 5: Wire app.state + mount + the tailscale-serve script — files: `/Users/artemis-build/artemis/src/artemis/main.py` (modify), `/Users/artemis-build/artemis/scripts/setup_tailscale_serve.sh` (create) —
  - main.py (additive only, do NOT touch `/healthz`/`/readyz` or the M1-c loopback router): in the startup/lifespan, build `s = get_settings()`; `registry = DeviceRegistry(devices_file(s))`; `auth = AppAuth(registry, ChallengeStore(), SessionStore())`; the `ReviewSurface` (compose its `RecipeStore`+`Promoter` from M7-a/M7-b using the M1-b embedder + `recipes_dir(s)` — reuse the existing brain composition where possible); a `PairingCodeStore`; a `RateLimiter`. **Key-provider injection (safe by default — apex-auth/apex-security):** the `app` factory takes the `BrokerKeyProvider` as a **constructor/factory argument defaulting to the real M2-c provider**; a fake is injected ONLY by the test fixture overriding `app.state` — there is **NO production env flag** that can swap in a fake. Add a startup assertion: if the active provider is not the real `BrokerKeyProvider` AND `s.slot == "prod"` (`Settings.slot` is a `str` from M0-a whose production value is exactly the literal `"prod"`), raise at startup (fail-loud — a fake auth provider can never run in prod). Store all on `app.state` (`app_auth`, `key_provider`, `review_surface`, `pairing_codes`, `rate_limiter`, and the existing `gateway`). `app.include_router(app_router)`.
  - setup_tailscale_serve.sh: create the `scripts/` dir if absent. bash `set -euo pipefail`; **validate the port before use**: `[[ "${BRAIN_PORT}" =~ ^[0-9]{1,5}$ ]] || { echo "Invalid BRAIN_PORT"; exit 1; }` (no empty-var/injection — apex-security); run `tailscale serve --bg --https=443 "http://127.0.0.1:${BRAIN_PORT}"`; print the resulting MagicDNS `https://<host>.<tailnet>.ts.net` URL; comment that this is the ONLY remote ingress and that Tailscale terminates TLS + restricts to the tailnet. Authored deterministically; only takes effect on the Mini (gated). — done when: `uv run mypy --strict src` passes; `TestClient(app)` exposes `/app/status` (401 without a session) alongside the unchanged `/healthz`; `bash -n scripts/setup_tailscale_serve.sh` passes.

- [ ] Task 6: Write the app-surface tests — files: `/Users/artemis-build/artemis/tests/test_api_app.py` — typed pytest + FastAPI `TestClient`. Fakes: an in-test phone (P-256 key, reused from the CLIENT-a test helper pattern — sign API-session + a fake unlock proof); a `FakeKeyProvider` implementing `begin_unlock`/`complete_unlock`/`is_owner_unlocked`/`lock_all` (an in-memory `unlocked` flag + a pending nonce); a `FakeReviewSurface` returning fixed `RecipeReview`s; a `Gateway(FakeBrain())`. Override `app.state` with these. Flow tests:
  - pairing: mint a code via the store; `POST /app/pair` with a valid code + length-prefixed code-signature → 200 and the registry now has the device + the fake broker recorded the relay; a wrong code → 401; a bad code-signature → 401 **AND the code is NOT consumed** (a subsequent valid attempt with the same code still succeeds — verify-before-consume); the stored code form is a `sha256` hash, not the raw code.
  - partial-pairing rollback: a fake broker whose `pair` raises → `POST /app/pair` returns 5xx AND `registry.get(device_id)` is None (rolled back).
  - session: `POST /app/session/begin` → nonce; sign it; `POST /app/session/complete` → a `session_token`; replay → 401.
  - rate limit: 6 rapid `POST /app/session/begin` from the same client → the 6th returns 429.
  - guard: `GET /app/review/pending` without a bearer → 401; **a route annotated `require_unlocked` with NO bearer still → 401** (the composition enforces the session gate first); with a session but vault **locked** → 423; after `POST /app/unlock/begin`+`/complete` (fake proof, **no client scope** — derived from the session) → 200 with the fixed review items.
  - chat: `POST /app/ask` (unlocked) → the FakeBrain's `AskResponse`; `POST /app/ask/stream` → `text/event-stream` containing the answer + `[DONE]`.
  - approve/reject: `POST /app/review/approve {name}` → the fake surface flipped it; reject likewise.
  - status/lock/logout: `GET /app/status` → `vault_unlocked` reflects the fake; `POST /app/lock` → fake `unlocked` false, session still valid (`/app/status` still 200); `POST /app/logout` → the session token now 401s.
  - regression: `/healthz` still 200.
  — done when: `uv run pytest -q tests/test_api_app.py` passes AND `uv run mypy --strict src tests/test_api_app.py` passes.

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | /Users/artemis-build/artemis/src/artemis/api_app.py, /Users/artemis-build/artemis/scripts/setup_tailscale_serve.sh, /Users/artemis-build/artemis/tests/test_api_app.py |
| Modify | /Users/artemis-build/artemis/src/artemis/identity/broker_client.py, /Users/artemis-build/artemis/src/artemis/main.py |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict src tests/test_api_app.py` | Type gate |
| `uv run ruff check . ; uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q tests/test_api_app.py` | Test gate (TestClient app surface) |
| `bash -n scripts/setup_tailscale_serve.sh` | Syntax-check the gated exposure script |
| `tailscale serve --bg --https=443 http://127.0.0.1:8030` (GATED, on-Mini) | Expose the app surface on the tailnet |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | src/artemis/api_app.py, src/artemis/identity/broker_client.py, src/artemis/main.py, scripts/setup_tailscale_serve.sh, tests/test_api_app.py |
| `git commit` | "feat: CLIENT-b brain app surface (pairing + session + unlock-relay + review/chat/status + tailscale serve)" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_ENV_FILE` | Slot Settings (ports, identity dir, recipes dir) |
| `ARTEMIS_DATA_ROOT` | Broker socket + identity registry resolution |
| `BRAIN_PORT` | tailscale-serve target port |

### Network
| Action | Purpose |
|--------|---------|
| (no PyPI add) | reuses CLIENT-a's `cryptography` |
| `tailscale serve` (GATED, on-Mini) | Tailnet exposure (Tailscale-managed TLS; only remote ingress) |
| App surface binds nothing new | brain stays `127.0.0.1`; broker IPC is a local Unix socket |

## Specialist Context
### Security
The two-tier guard is load-bearing (ADR-010): `require_session` (reachability) vs `require_unlocked` (session AND vault DEK present). Data endpoints (Review, Chat) are `require_unlocked` → 423 when the DEK is zeroized; only Status/unlock/lock/logout are session-only. Division of verification: the brain verifies the **API-session** signature itself (CLIENT-a, against its own registry copy of the pubkey) but **relays the vault proof without verifying it** — the broker is the sole vault-proof verifier. Pairing requires an owner-minted single-use code + a key-possession signature, then registers in BOTH stores (brain registry + broker). All failures return generic 401/423 (no enumeration). The pairing code, vault proof, API signature, session token, and DEK are NEVER logged. The surface is reachable only over the tailnet (`tailscale serve`); the process still binds loopback.

Review resolutions baked in (security + auth, 2026-06-08): **rate-limiting** (5/15min per peer IP) on every unauthenticated route + `/app/unlock/begin`; pairing code stored **hashed** (`sha256`), single-outstanding, **verify-key-possession-before-consume**, **length-prefixed** signed message (no `|` ambiguity), **two-store rollback** on a failed broker relay; `require_unlocked` **composes `require_session` via `Depends`** (no bypass); **scope derived from the session**, never the client body (unlock routes); **constant-time** nonce compare in `complete_unlock`; **SSE mid-stream lock** emits a terminal error frame (fail-closed); the broker key-provider fake is a **test-only constructor override** with a **prod startup assertion** (no env-flag bypass); the `/app/session/complete` response is **excluded from response logging**. [FLAG apex-security + apex-auth: re-confirm these at the wave review — esp. the `require_unlocked` composition + scope-from-session + no token/DEK in logs.]

### Performance
SSE streams chat (TTFT masked, brain.md). Review/Status are O(recipes) rule-based reads (M7-b is token-free). Unlock relay is two short IPC round-trips; the DEK is then mlock-cached for the broker session window (no re-proof until idle/lock).

### Accessibility
(none — HTTP surface; the rendered UI + a11y are CLIENT-d. The Review payload carries M7-b's plain-language `explanation` for the screen to render verbatim.)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | src/artemis/api_app.py, src/artemis/identity/broker_client.py | Type + docstring all exports; document the `/app/*` route contract (auth tier per route, request/response shapes, SSE frames) + the unlock-relay flow |
| API | docs/product/api/client-app-api.md | Add the `/app/*` endpoint reference (routes, auth tier, payloads) for the CLIENT-c/d Swift client |

## Acceptance Criteria
- [ ] Run `uv run mypy --strict src tests/test_api_app.py` → verify: exit 0.
- [ ] Run `uv run pytest -q tests/test_api_app.py` → verify: full pair→session→unlock→review/chat flow passes; no-bearer→401; session-but-locked→423; replay-nonce→401; wrong-pairing-code→401; `/app/lock` keeps the session; `/app/logout` invalidates it; `/healthz` still 200.
- [ ] Run `uv run python -c "import artemis.main; from artemis.api_app import app_router, PairingCodeStore, require_unlocked"` → verify: exit 0.
- [ ] Run `bash -n scripts/setup_tailscale_serve.sh` → verify: exit 0.
- [ ] Run `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.
- [ ] (GATED, on Mini) `tailscale serve` exposes `https://<host>.ts.net/app/status` returning 401 without a bearer, 200 with a valid session → verify recorded in handoff.

## Amendment 2026-06-24 — `/app/layout` + per-domain read endpoints (Tauri client surface)

The Tauri client (ADR-028 carve) consumes the existing `/app/*` surface **plus** these additions. All additive to `api_app.py`; the two-tier auth pattern + main.py wiring are unchanged. The stale `/Users/artemis-build/` paths are adapted to the live tree at build time (standing pre-flight pattern).

### Added files
| File | Operation | Notes |
|------|-----------|-------|
| src/artemis/app_layout_store.py | create | `LayoutStore` — the owner's map-layout persistence. **Plain JSON `0600` under `identity_dir(s)/layout.json` — NOT a SQLCipher vault store.** Rationale: layout is **session-gated** (ADR-030) and must be readable while the vault is **locked**, when no DEK is available — so it lives beside the device registry (readable with a session, no unlock), not inside an unlock-gated encrypted scope. Atomic write (temp + `os.replace`). LWW: a PUT persists only if its `updated_at` > stored. |

### Added routes (api_app.py)
- **`GET /app/layout`** (`Depends(require_session)` — **NOT** `require_unlocked`; ADR-030 § Layout endpoint gate): return the stored `LayoutDTO`, or a server **default seed** (the 4-cluster / 11-domain default per `domains.ts`) if none. Session-gated so the map arranges while Vault-locked; card positions are low-sensitivity UX state.
- **`PUT /app/layout`** (`require_session`): body = `LayoutDTO`; **last-writer-wins** on `updated_at` (reject/ignore a PUT whose `updated_at` ≤ stored); return the effective `LayoutDTO`. Server stamps `updated_at` on accept.
- **Per-domain reads** (`Depends(require_unlocked)` — owner data; **423 when locked**). Each composes its module's READ tools only (never a write; untrusted external content stays behind the DR-a chokepoint where applicable) and returns the CLIENT-screens DTO as a pydantic model (snake_case wire):

  | Route | Response model (mirrors CLIENT-screens TS) | Composes | Build |
  |---|---|---|---|
  | `GET /app/calendar` | `CalendarRead {events:[{id,title,start,end,kind,attendees?,rsvp?}], tasks_due_by_day}` | CAL-a/b/c reads + M8-d tasks-due | **real** |
  | `GET /app/tasks` | `TasksRead {overdue,today,upcoming,suggestions}` | M8-d-a/a2 reads | **real** |
  | `GET /app/projects` | `ProjectsRead {projects:[{id,name,status,target?,open_tasks}]}` | M8-d projects manifest | **real** |
  | `GET /app/email` | `GmailRead {needs_you:[{id,sender,subject,why}], signal:[{id,sender,subject,ts}]}` | M8-b1 reads | **fake-gated** (M8-b1 blocked on docling) |
  | `GET /app/finance` | `FinanceRead {week_total, mtd_total, daily:[{date,amount}], categories:[{name,amount,color}], transactions[], bills[], unusual?, duplicate?, ambiguous?}` | FIN-* | **fake-gated** (FIN unbuilt) |

  **Fake-gated** = ship the route + a typed fake payload behind a flag so the client builds/tests now; swap to the real module read when M8-b1 / FIN land. (FinanceRead matches the now-settled finance detail design — `finance-page.html` — even though the CLIENT-screens Finance *view* is still the generic placeholder; see GAP below.)

### Added tasks
- [ ] Task 7 (amendment): `LayoutStore` + `GET/PUT /app/layout` — files: `src/artemis/app_layout_store.py` (create), `src/artemis/api_app.py` (modify), `src/artemis/main.py` (modify — construct `LayoutStore(identity_dir(s)/...)` → `app.state.layout_store`), `tests/test_api_app.py` (modify). Pydantic `LayoutDTO`/`CardPlacement`; GET (session) returns stored-or-default-seed; PUT (session) LWW. — done when: `mypy --strict src` passes; TestClient: GET without a session → 401; with a session (vault **locked**) → a `LayoutDTO` (proves session-not-unlock gating); a PUT with an older `updated_at` leaves the store unchanged; a newer PUT persists + round-trips.
- [ ] Task 8 (amendment): the 5 per-domain read endpoints — files: `src/artemis/api_app.py` (modify), `tests/test_api_app.py` (modify). Add the 5 `require_unlocked` routes above + their pydantic models; calendar/tasks/projects compose the real module read tools, email/finance return a typed FAKE behind a feature flag. — done when: `mypy --strict src` passes; TestClient (against fake modules): each route → **423 when vault-locked**, **200 + the typed DTO when unlocked**; `/app/calendar` includes `tasks_due_by_day`; the fake-gated email/finance return their typed shapes.

### Permissions / AC delta
- File ops: **+ create** `src/artemis/app_layout_store.py`; **+ modify** `src/artemis/api_app.py`, `src/artemis/main.py`, `tests/test_api_app.py`.
- AC: **+** `GET/PUT /app/layout` session-gated (works while locked) + LWW; **+** the 5 per-domain reads = 423-when-locked / typed-DTO-when-unlocked (calendar/tasks/projects real; email/finance fake-gated).

### GAP (for planning)
The **Finance detail design is now settled** (`docs/research/mockups/finance-page.html` — compact daily-spend list + leader-line category pie), but `CLIENT-screens` still carries Finance as the **generic placeholder**. A near-term `CLIENT-screens` Finance amendment should graduate Finance from `GenericDomainDetail` to a bespoke `FinanceDetail` consuming the rich `FinanceRead` above (mirrors the mockup). The `/app/finance` endpoint already returns the rich shape, so no brain re-work is needed when that lands.

## Progress
_(Coding mode writes here — do not edit manually)_
