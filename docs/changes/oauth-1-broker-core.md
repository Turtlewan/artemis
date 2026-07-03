---
spec: oauth-1-broker-core
status: ready
token_profile: lean
autonomy_level: L5
coder_effort: high
cross_model_review: true
---

# Spec: Google OAuth broker — core (loopback auth-code flow + token store/refresh)

**Identity:** A brain-side `OAuthBroker` that runs the bring-your-own-client loopback authorization-code flow (PKCE), stores the refresh token in the keychain, and mints fresh access tokens on demand.
→ why: docs/technical/adr/ADR-044-google-oauth-broker-byo-client.md

## Assumptions
- The keychain `SecretStorePort` (`src/artemis/secrets_store.py` `KeyringSecretStore`) already exists and stores string values by name; the OAuth `client_id`/`client_secret` and per-account refresh token live there as named secrets → impact: Stop
- `httpx` is already a project dependency (used by the web tool) — the broker uses it for the token endpoint; no new dependency → impact: Caution
- The owner registers their own Google Cloud OAuth client (Desktop app) and provides `client_id`+`client_secret` out-of-band per the runbook — the broker does not create the Google-side client → impact: Stop
- **Single-account MVP.** The broker keys stored credentials by a caller-supplied `account` id, but for now the client always passes a fixed id (`"default"`) — one connected Google account. `account` is NEVER derived from an email address (Google identity hard-block); multi-account + `sub`-based keying + connected-email display are deferred → impact: Stop
- The OS keychain (Windows Credential Manager / macOS Keychain via `keyring`) is treated as the encrypted server-side credential store the security model requires — the broker runs brain-side (local service), not in a browser client → impact: Caution
- This spec is brain-only and has NO routes/UI/invoke-wiring — those are separate specs (oauth-2, oauth-3, oauth-4). The broker is a pure, unit-testable module (HTTP + browser + listener are injected/mockable) → impact: Stop

Simplicity check: considered a third-party OAuth library (Authlib is the stack's designated OAuth swap). Rejected for now — a single fixed provider (Google) desktop loopback+PKCE+refresh flow against fixed endpoints is small and explicit, and a hand-rolled broker avoids adding a new dependency to the credential path. The reviews below pin the exact correctness points a library would otherwise own (CSPRNG `state`, constant-time compare, `redirect_uri` exactness, PKCE S256, refresh-token rotation), so hand-rolling is safe here. **Revisit (adopt Authlib) if a second OAuth provider is added.**

## Prerequisites
- Specs that must be complete first: none (this is the base of the OAuth stack).
- Environment: none for unit tests (the token endpoint + browser + loopback listener are mocked). A live connect requires the owner's Google Cloud client (runbook).

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| src/artemis/oauth/__init__.py | create | package marker |
| src/artemis/oauth/broker.py | create | `OAuthBroker`: `begin_connect(scopes)`, `complete_connect(code,...)`, `mint_access_token(account, scope)`, `disconnect(account)`; PKCE helpers; loopback listener; refresh-grant + expiry-skew cache |
| docs/technical/setup/google-oauth-setup.md | create | screen-by-screen Google Cloud Console runbook (create project → OAuth consent screen (External) → **publish to Production** → add owner as test user if kept in Testing → Desktop OAuth client → copy client_id/secret → paste into Artemis keys panel); mirrors js-fetcher-provisioning.md style |
| tests/oauth/test_broker.py | create | unit tests with mocked httpx token endpoint + injected listener/browser |

## Tasks
- [ ] Task 1: Create `src/artemis/oauth/broker.py` with PKCE + auth-URL construction. `generate_pkce()` → (verifier, S256 challenge). `build_consent_url(client_id, redirect_uri, scopes, challenge, state)` → Google auth endpoint URL with `access_type=offline`, `prompt=consent`, `code_challenge_method=S256`. `state` is generated with `secrets.token_urlsafe(32)` (CSPRNG). Pure functions, no I/O. — files: src/artemis/oauth/broker.py, tests/oauth/test_broker.py — done when: PKCE verifier/challenge round-trip verifies against RFC 7636 S256; the consent URL contains the required params; two `state` generations never collide (asserted in tests).
- [ ] Task 2: Loopback listener + `begin_connect`/`complete_connect`. `begin_connect(scopes)` binds an ephemeral `127.0.0.1` port (never `0.0.0.0`/all-interfaces), builds `redirect_uri = http://127.0.0.1:<port>/callback`, stores a pending-state (CSPRNG `state` + PKCE verifier + port + the exact `redirect_uri`, short TTL), opens the browser via an injected `open_browser` callable (default `webbrowser.open`; the connect route injects a no-op so the desktop client opens the URL — see oauth-2/oauth-4), and returns the consent URL. A minimal one-shot HTTP handler catches `GET /callback?code=&state=`: any non-`/callback` path or malformed/extra params get a generic closed 200/404 response and do NOT touch pending state; the `state` is compared with `hmac.compare_digest` (constant-time); on match it hands the code to `complete_connect`. `complete_connect` exchanges `code`+`client_secret`+`verifier` at Google's token endpoint (injected `httpx.AsyncClient`) using the SAME `redirect_uri` string byte-for-byte, then stores the refresh token in the keychain keyed by account (`google_refresh:<account>`, fixed `"default"` for now) and records the granted scopes. It returns only the account id + granted scopes — never tokens or the client secret. The listener has a bounded timeout (e.g. 120s) after which it closes and the pending state expires (fail closed). State mismatch / missing code / timeout → fail closed (no token stored). — files: src/artemis/oauth/broker.py, tests/oauth/test_broker.py — done when: a mocked end-to-end connect (fake token endpoint) stores a refresh token + granted scopes and returns no secret; a bad `state` is rejected and stores nothing; a replayed valid `code`/`state` succeeds at most once; the listener socket is bound to `127.0.0.1` (asserted via socket introspection); the token-exchange `redirect_uri` equals the consent-URL `redirect_uri` byte-for-byte.
- [ ] Task 3: `mint_access_token(account, scope)` + expiry cache + rotation + `disconnect`. Reads the account's refresh token from the keychain, runs the refresh-token grant (injected httpx) to mint an access token, caches it in-memory (never keychain/disk) with its `expires_in` minus a skew (e.g. 60s) and returns cached tokens until near expiry. **If the refresh-grant response includes a `refresh_token`, overwrite the keychain entry with the rotated value.** Raises a typed `OAuthUnavailable` / returns a sentinel when the refresh token is missing/revoked, and on any httpx/token-endpoint failure — all raised errors are sanitized (no `client_secret`, code, token, request/response body in the message; fail closed → caller signals "re-connect Google"). Checks the requested `scope` was granted for the account; if not, raises typed `ScopeNotGranted`. `disconnect(account)` calls Google's revoke endpoint (best-effort, sanitized error on failure) and deletes the refresh token + granted-scopes record from the keychain. — files: src/artemis/oauth/broker.py, tests/oauth/test_broker.py — done when: mint returns a cached token within skew (one HTTP call for two mints); a rotated `refresh_token` in the grant response overwrites the keychain entry; a revoked/missing refresh token fails closed; an ungranted scope raises `ScopeNotGranted`; disconnect deletes the stored token; no access token is ever written to the keychain/disk.

## Wave plan
Wave 1: [Task 1] | Wave 2: [Task 2] | Wave 3: [Task 3]
<!-- Sequential: all three build up the same broker.py + test_broker.py. -->

## Permissions
### File Operations
| Action | Paths |
|--------|-------|
| Create | src/artemis/oauth/__init__.py, src/artemis/oauth/broker.py, docs/technical/setup/google-oauth-setup.md, tests/oauth/test_broker.py |
| Modify | CHANGELOG.md |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/` | lint/format |
| `uv run mypy` | type gate |
| `uv run pytest -q` | test gate (all mocked; no live Google) |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | the created files + CHANGELOG.md |
| `git commit` | "feat(oauth): Google OAuth broker core (loopback PKCE flow + token refresh)" |

### Network
| Action | Purpose |
|--------|---------|
| (none) | no new packages; httpx already present; no network in tests (mocked) |

## Specialist Context
### Security / Auth / Google (reviews DONE 2026-07-03 — apex-security, apex-auth, apex-google; findings folded above)
This module acquires and stores a long-lived Google **refresh token** and handles the OAuth **client secret**. Invariants now pinned in tasks/ACs: (1) refresh token + client secret only ever in the keychain, never logged / never in any raised error / never returned to callers (all error paths sanitized); (2) `state` is CSPRNG (`secrets.token_urlsafe(32)`), compared constant-time (`hmac.compare_digest`), single-use; PKCE verifier + `redirect_uri` exactness validated before/at token exchange; (3) loopback binds `127.0.0.1` only; the one-shot listener rejects non-`/callback` requests and has a bounded fail-closed timeout; (4) minted access tokens are in-memory only (never keychain/disk); (5) fail-closed on revoked/expired/errored refresh grant; (6) refresh-token **rotation** re-persisted; (7) account keyed by a fixed id, never by email. `cross_model_review: true` (independent second-model review fires at build).

**Owner action (Google-side, required before first live use):** publish the OAuth consent screen to **Production** in Cloud Console. Apps left in "Testing" status issue refresh tokens that expire after **7 days**, which would force a weekly reconnect. Publishing to Production is a status flip (not the multi-week verification review) — it adds only an "unverified app" warning screen for the owner-as-sole-user. The runbook must document this step and the 7-day caveat.

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | src/artemis/oauth/broker.py | module + method docstrings (never-log-secrets contract) |
| Setup | docs/technical/setup/google-oauth-setup.md | Cloud Console runbook incl. the publish-to-Production step |
| Changelog | CHANGELOG.md | Unreleased/Added — OAuth broker core |

## Acceptance Criteria
- [ ] `generate_pkce()` + `build_consent_url(...)` → verify the S256 challenge matches the verifier and the URL carries `access_type=offline`, `code_challenge_method=S256`, the scopes, and the state; two `state` values from consecutive calls differ.
- [ ] Mocked connect (fake token endpoint) → verify a refresh token + granted scopes are stored in the keychain keyed by account, `complete_connect` returns no token/secret; a `state` mismatch stores nothing; a replayed valid `code`/`state` succeeds at most once.
- [ ] Listener socket is bound to `127.0.0.1` (asserted via socket introspection); a non-`/callback` request gets a generic closed response and leaves pending state untouched; the connect times out and fails closed (pending state expires) if no callback arrives.
- [ ] The `redirect_uri` used at token exchange equals the one in the consent URL byte-for-byte (asserted).
- [ ] `mint_access_token` twice within skew → one token-endpoint call (cache hit); after skew → a second call.
- [ ] A refresh-grant response containing a rotated `refresh_token` → verify the keychain entry is overwritten with the new value.
- [ ] Missing/revoked refresh token → `mint_access_token` fails closed (typed error/sentinel), no crash.
- [ ] No secret material (client_secret / code / access or refresh token / httpx request-response body) appears in ANY raised error's message/`repr` across all error paths — state mismatch, `complete_connect` token-exchange failure, `mint_access_token` httpx failure, and `disconnect` revoke failure (parametrized test).
- [ ] Ungranted scope → verify `ScopeNotGranted`. No access token is ever written to the keychain/disk (only the refresh token is).
- [ ] `disconnect(account)` → verify revoke called + refresh token deleted from keychain.
- [ ] Runbook exists with the Cloud Console steps, the **publish-to-Production** step + 7-day-refresh-token-expiry warning, and the "you are your own test user" note.
- [ ] `uv run mypy` / `ruff` clean; `uv run pytest -q` green (no live Google calls).

## Progress
_(Coding mode writes here — do not edit manually)_
