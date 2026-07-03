---
spec: oauth-2-connect-routes
status: ready
token_profile: lean
autonomy_level: L5
coder_effort: high
---

# Spec: Google OAuth broker — connect routes + app wiring

**Identity:** Session-gated brain HTTP routes to start an OAuth connect, report connected-account status, and disconnect; plus `create_app` wiring of the broker onto `app.state`.
→ why: docs/technical/adr/ADR-044-google-oauth-broker-byo-client.md

## Assumptions
- The `OAuthBroker` from `oauth-1-broker-core` (SHIPPED, `c01e747`) exists with `begin_connect(scopes,*,account)`, `listen_for_callback()`, `complete_connect(*,code,state)`, `mint_access_token(account,scope)`, `disconnect(account)`. It has **no public status read** — this spec ADDS a small public `account_status(account)` read to the broker (reads the store: connected bool + granted scopes, NO token values) → impact: Stop
- Routes are session-gated exactly like the existing `/app/*` routes (same session dependency used by capability/invoke routes) → impact: Stop
- The client `client_id`/`client_secret` are already in the keychain (owner pasted them via the existing keys panel) before a connect is started; `begin_connect` raises a typed error when absent, which the connect route maps to a `client_not_configured` status → impact: Caution
- **The route does NOT open a browser server-side.** `begin_connect` accepts an injected `open_browser`; the route passes a no-op so the desktop client (oauth-4) opens the returned consent URL in the OS browser (single opener, no double-tab). The brain-side loopback listener still catches the redirect → impact: Stop
- **`listen_for_callback()` must be scheduled immediately after `begin_connect`** (as an `asyncio` background task on `app.state`), so the bound loopback socket is served and never leaked (Opus review finding, oauth-1). The connect route returns the consent URL right away; the background task completes when the owner consents (or times out fail-closed) → impact: Stop

Simplicity check: the loopback listener + browser open live in the broker (spec 1); these routes are thin — start returns the consent URL, status reads granted scopes, disconnect delegates. No flow logic duplicated here.

## Prerequisites
- `oauth-1-broker-core` (the broker) — must be built first.
- **Shared-file note (ADR-029):** this spec edits `src/artemis/api/app.py`, also edited by `R4a-telegram-ingress-router` and `R4c-desktop-bless-ui` (both in docs/drafts/). Whichever builds first owns the `create_app` additions; the others rebase their `app.state` line. Sequence these on `app.py`, do not build them concurrently.

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| src/artemis/oauth/broker.py | modify | add a public `account_status(account=DEFAULT_ACCOUNT)` read: returns `{connected: bool, granted_scopes: tuple[str,...]}` from the store, NO token values; no network |
| tests/oauth/test_broker.py | modify | test `account_status` (connected vs not; no token in the result) |
| src/artemis/api/oauth_routes.py | create | `APIRouter`: `POST /app/oauth/google/connect` (start flow → schedule `listen_for_callback` background task → returns consent URL), `GET /app/oauth/google/status` (connected account + granted scopes), `POST /app/oauth/google/disconnect` |
| src/artemis/api/app.py | modify | `app.state.oauth_broker = OAuthBroker(secrets_store=app.state.secrets, open_browser=<no-op>)`; include the oauth router; hold the connect background task on `app.state` |
| tests/api/test_oauth_routes.py | create | session-gate + happy-path (mocked broker) + client-not-configured + status + disconnect |

## Tasks
- [ ] Task 1: Add a public `account_status(self, account: str = DEFAULT_ACCOUNT)` method to `OAuthBroker` returning whether the account is connected (refresh token present in the store) and its granted scopes — reading the store only, no network, no token values in the result. — files: src/artemis/oauth/broker.py, tests/oauth/test_broker.py — done when: `account_status` returns connected+scopes for a stored account and connected=False/empty scopes for an unknown one, with no token value present; full recipe green.
- [ ] Task 2: Create `oauth_routes.py` with the three session-gated endpoints backed by the `app.state` broker. `connect` accepts the requested scopes, calls `broker.begin_connect`, **schedules `broker.listen_for_callback()` as an `asyncio` background task held on `app.state`**, and returns the consent URL (client opens it) or a typed `client_not_configured` status when `begin_connect` raises the not-configured error — it never opens a browser server-side; `status` calls `broker.account_status` and returns the connected account + granted scopes (token values never included); `disconnect` calls `broker.disconnect`. — files: src/artemis/api/oauth_routes.py, tests/api/test_oauth_routes.py — done when: the three endpoints return their typed payloads, reject unauthenticated calls (session gate), `connect` returns the consent URL without opening a browser in-process and schedules the listener task.
- [ ] Task 3: Wire the broker in `create_app` (`app.state.oauth_broker = OAuthBroker(secrets_store=app.state.secrets, open_browser=<no-op lambda>)`), include the router, and hold the connect background task on `app.state`. — files: src/artemis/api/app.py, tests/api/test_oauth_routes.py — done when: a `TestClient` reaches the routes and `app.state.oauth_broker` is present.

## Wave plan
Wave 1: [Task 1] | Wave 2: [Task 2] | Wave 3: [Task 3]
<!-- Sequential: Task 2 uses account_status from Task 1; Task 3 wires the router from Task 2. -->

## Prerequisites (updated)
- `oauth-1-broker-core` — SHIPPED (`c01e747`).

## Permissions
### File Operations
| Action | Paths |
|--------|-------|
| Create | src/artemis/api/oauth_routes.py, tests/api/test_oauth_routes.py |
| Modify | src/artemis/oauth/broker.py, tests/oauth/test_broker.py, src/artemis/api/app.py, CHANGELOG.md |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy` | type gate |
| `uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/` | lint/format |
| `uv run pytest -q` | test gate (mocked broker) |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | created/modified files + CHANGELOG.md |
| `git commit` | "feat(oauth): connect/status/disconnect routes + broker wiring" |

## Specialist Context
### Security
The routes are session-gated and never return secret/token values (only account ids + granted scope names). `status`/`disconnect` operate on account identifiers, not tokens. No browser is opened server-side (no-op opener; client opens the consent URL). No new credential handling beyond delegating to the broker (spec 1 carries the credential review). A light apex-security check that no token/secret leaks into a response payload is warranted; not a full BLOCKER.

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | src/artemis/api/oauth_routes.py | route docstrings |
| Changelog | CHANGELOG.md | Unreleased/Added — OAuth connect routes |

## Acceptance Criteria
- [ ] Unauthenticated calls to all three routes → verify rejected by the session gate.
- [ ] `POST /connect` with scopes (mocked broker) → verify returns the consent URL and does NOT open a browser in-process; with no client creds → verify `client_not_configured`.
- [ ] `GET /status` → verify returns accounts + granted scopes, no token values present in the payload.
- [ ] `POST /disconnect` → verify `broker.disconnect` called and a success payload returned.
- [ ] `app.state.oauth_broker` present; `uv run mypy`/`ruff` clean; `pytest -q` green.

## Progress
_(Coding mode writes here — do not edit manually)_
