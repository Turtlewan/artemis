---
spec: oauth-2-connect-routes
status: draft
token_profile: lean
autonomy_level: L5
coder_effort: high
---

# Spec: Google OAuth broker — connect routes + app wiring

**Identity:** Session-gated brain HTTP routes to start an OAuth connect, report connected-account status, and disconnect; plus `create_app` wiring of the broker onto `app.state`.
→ why: docs/technical/adr/ADR-044-google-oauth-broker-byo-client.md

## Assumptions
- The `OAuthBroker` from `oauth-1-broker-core` exists with `begin_connect`, `complete_connect`, `mint_access_token`, `disconnect`, and a granted-scopes/status read → impact: Stop
- Routes are session-gated exactly like the existing `/app/*` routes (same session dependency used by capability/invoke routes) → impact: Stop
- The client `client_id`/`client_secret` are already in the keychain (owner pasted them via the existing keys panel) before a connect is started; the connect route surfaces a typed "client not configured" status if absent → impact: Caution

Simplicity check: the loopback listener + browser open live in the broker (spec 1); these routes are thin — start returns the consent URL/launches the flow, status reads granted scopes, disconnect delegates. No flow logic duplicated here.

## Prerequisites
- `oauth-1-broker-core` (the broker) — must be built first.
- **Shared-file note (ADR-029):** this spec edits `src/artemis/api/app.py`, also edited by `R4a-telegram-ingress-router` and `R4c-desktop-bless-ui` (both in docs/drafts/). Whichever builds first owns the `create_app` additions; the others rebase their `app.state` line. Sequence these on `app.py`, do not build them concurrently.

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| src/artemis/api/oauth_routes.py | create | `APIRouter`: `POST /app/oauth/google/connect` (start flow → returns consent URL/launches), `GET /app/oauth/google/status` (connected accounts + granted scopes), `POST /app/oauth/google/disconnect` |
| src/artemis/api/app.py | modify | `app.state.oauth_broker = OAuthBroker(app.state.secrets)`; include the oauth router |
| tests/api/test_oauth_routes.py | create | session-gate + happy-path (mocked broker) + client-not-configured + disconnect |

## Tasks
- [ ] Task 1: Create `oauth_routes.py` with the three session-gated endpoints backed by an injected/`app.state` broker. `connect` accepts the requested scopes, calls `broker.begin_connect`, returns the consent URL (client opens it) or a `client_not_configured` status; `status` returns connected accounts + granted scopes (values never included); `disconnect` calls `broker.disconnect`. — files: src/artemis/api/oauth_routes.py, tests/api/test_oauth_routes.py — done when: the three endpoints return their typed payloads and reject unauthenticated calls (session gate).
- [ ] Task 2: Wire the broker in `create_app` (`app.state.oauth_broker`, built from `app.state.secrets`) and include the router. — files: src/artemis/api/app.py, tests/api/test_oauth_routes.py — done when: a `TestClient` reaches the routes and `app.state.oauth_broker` is present.

## Wave plan
Wave 1: [Task 1] | Wave 2: [Task 2]

## Permissions
### File Operations
| Action | Paths |
|--------|-------|
| Create | src/artemis/api/oauth_routes.py, tests/api/test_oauth_routes.py |
| Modify | src/artemis/api/app.py |

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
The routes are session-gated and never return secret/token values (only account ids + granted scope names). `status`/`disconnect` operate on account identifiers, not tokens. No new credential handling beyond delegating to the broker (spec 1 carries the credential review). A light apex-security check that no token/secret leaks into a response payload is warranted; not a full BLOCKER.

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | src/artemis/api/oauth_routes.py | route docstrings |
| Changelog | CHANGELOG.md | Unreleased/Added — OAuth connect routes |

## Acceptance Criteria
- [ ] Unauthenticated calls to all three routes → verify rejected by the session gate.
- [ ] `POST /connect` with scopes (mocked broker) → verify returns the consent URL; with no client creds → verify `client_not_configured`.
- [ ] `GET /status` → verify returns accounts + granted scopes, no token values present in the payload.
- [ ] `POST /disconnect` → verify `broker.disconnect` called and a success payload returned.
- [ ] `app.state.oauth_broker` present; `uv run mypy`/`ruff` clean; `pytest -q` green.

## Progress
_(Coding mode writes here — do not edit manually)_
