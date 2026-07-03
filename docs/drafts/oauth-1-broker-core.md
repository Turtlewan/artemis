---
spec: oauth-1-broker-core
status: draft
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
- This spec is brain-only and has NO routes/UI/invoke-wiring — those are separate specs (oauth-2, oauth-3, oauth-4). The broker is a pure, unit-testable module (HTTP + browser + listener are injected/mockable) → impact: Stop

Simplicity check: considered a third-party OAuth library — rejected for now; the desktop loopback+PKCE+refresh flow against Google's fixed endpoints is small and explicit, and a hand-rolled broker avoids a new security-sensitive dependency in the credential path. Revisit if scope grows beyond Google.

## Prerequisites
- Specs that must be complete first: none (this is the base of the OAuth stack).
- Environment: none for unit tests (the token endpoint + browser + loopback listener are mocked). A live connect requires the owner's Google Cloud client (runbook).

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| src/artemis/oauth/__init__.py | create | package marker |
| src/artemis/oauth/broker.py | create | `OAuthBroker`: `begin_connect(scopes)`, `complete_connect(code,...)`, `mint_access_token(account, scope)`, `disconnect(account)`; PKCE helpers; loopback listener; refresh-grant + expiry-skew cache |
| docs/technical/setup/google-oauth-setup.md | create | screen-by-screen Google Cloud Console runbook (create project → OAuth consent screen (External, test user = owner) → Desktop OAuth client → copy client_id/secret → paste into Artemis keys panel); mirrors js-fetcher-provisioning.md style |
| tests/oauth/test_broker.py | create | unit tests with mocked httpx token endpoint + injected listener/browser |

## Tasks
- [ ] Task 1: Create `src/artemis/oauth/broker.py` with PKCE + auth-URL construction. `generate_pkce()` → (verifier, S256 challenge). `build_consent_url(client_id, redirect_uri, scopes, challenge, state)` → Google auth endpoint URL with `access_type=offline`, `prompt=consent`, `code_challenge_method=S256`. Pure functions, no I/O. — files: src/artemis/oauth/broker.py, tests/oauth/test_broker.py — done when: PKCE verifier/challenge round-trip verifies against RFC 7636 S256, and the consent URL contains the required params (asserted in tests).
- [ ] Task 2: Loopback listener + `begin_connect`/`complete_connect`. `begin_connect(scopes)` binds an ephemeral `127.0.0.1` port, stores a pending-state (state token + PKCE verifier + port, short TTL), opens the browser (via an injected `open_browser` callable, default `webbrowser.open`), and returns the consent URL. A minimal one-shot HTTP handler catches `GET /callback?code=&state=`, validates `state`, and hands the code to `complete_connect`, which exchanges `code`+`client_secret`+`verifier` at Google's token endpoint (injected `httpx.AsyncClient`) for access+refresh tokens, then stores the refresh token in the keychain keyed by account (e.g. `google_refresh:<account>`) and records the granted scopes. State mismatch / missing code → fail closed (no token stored). — files: src/artemis/oauth/broker.py, tests/oauth/test_broker.py — done when: a mocked end-to-end connect (fake token endpoint) stores a refresh token + granted scopes; a bad `state` is rejected and stores nothing.
- [ ] Task 3: `mint_access_token(account, scope)` + expiry cache + `disconnect`. Reads the account's refresh token from the keychain, runs the refresh-token grant (injected httpx) to mint an access token, caches it in-memory with its `expires_in` minus a skew (e.g. 60s) and returns cached tokens until near expiry. Raises a typed `OAuthUnavailable`/returns a sentinel when the refresh token is missing/revoked (fail closed → caller signals "re-connect Google"). Checks the requested `scope` was granted for the account; if not, raises a typed `ScopeNotGranted`. `disconnect(account)` calls Google's revoke endpoint (best-effort) and deletes the refresh token + granted-scopes record from the keychain. — files: src/artemis/oauth/broker.py, tests/oauth/test_broker.py — done when: mint returns a cached token within skew (one HTTP call for two mints), a revoked/missing refresh token fails closed, an ungranted scope raises `ScopeNotGranted`, and disconnect deletes the stored token.

## Wave plan
Wave 1: [Task 1] | Wave 2: [Task 2] | Wave 3: [Task 3]
<!-- Sequential: all three build up the same broker.py + test_broker.py. -->

## Permissions
### File Operations
| Action | Paths |
|--------|-------|
| Create | src/artemis/oauth/__init__.py, src/artemis/oauth/broker.py, docs/technical/setup/google-oauth-setup.md, tests/oauth/test_broker.py |
| Modify | (none) |

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
### Security
**BLOCKER: apex-security review pending — do not mark this spec `ready` until run.** This module acquires and stores a long-lived Google **refresh token** and handles the OAuth **client secret**. Review focus: (1) refresh token + client secret only ever in the keychain, never logged / never in errors / never returned to callers; (2) `state` (CSRF) + PKCE verifier validated before token exchange; loopback binds `127.0.0.1` only (never `0.0.0.0`); (3) the one-shot callback listener closes promptly and rejects unexpected paths/params (fail closed); (4) minted access tokens are not persisted to disk (in-memory cache only); (5) fail-closed on revoked/expired refresh token. `cross_model_review: true`.

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | src/artemis/oauth/broker.py | module + method docstrings (never-log-secrets contract) |
| Setup | docs/technical/setup/google-oauth-setup.md | Cloud Console runbook |
| Changelog | CHANGELOG.md | Unreleased/Added — OAuth broker core |

## Acceptance Criteria
- [ ] `generate_pkce()` + `build_consent_url(...)` → verify S256 challenge matches the verifier and the URL carries `access_type=offline`, `code_challenge_method=S256`, the scopes, and the state.
- [ ] Mocked connect (fake token endpoint) → verify a refresh token + granted scopes are stored in the keychain keyed by account; a `state` mismatch stores nothing.
- [ ] `mint_access_token` twice within skew → verify one token-endpoint call (cache hit); after skew → a second call.
- [ ] Missing/revoked refresh token → verify `mint_access_token` fails closed (typed error/sentinel), no crash, no secret leak in the message.
- [ ] Ungranted scope → verify `ScopeNotGranted`.
- [ ] `disconnect(account)` → verify revoke called + refresh token deleted from keychain.
- [ ] Runbook exists with the Cloud Console steps + the "you are your own test user (no verification needed)" note.
- [ ] `uv run mypy` / `ruff` clean; `uv run pytest -q` green (no live Google calls).

## Progress
_(Coding mode writes here — do not edit manually)_
