---
spec: oauth-3-invoke-integration
status: ready
token_profile: lean
autonomy_level: L5
coder_effort: high
cross_model_review: true
---

# Spec: Google OAuth broker — dynamic-token invoke integration

**Identity:** Let a capability declare an OAuth `scope` and have the invoke path mint a fresh Google access token via the broker and inject it into the isolate — the "dynamic secret" path alongside static secrets.
→ why: docs/technical/adr/ADR-044-google-oauth-broker-byo-client.md (decision 4)

## Assumptions
- The `OAuthBroker` (`oauth-1-broker-core`) exposes `mint_access_token(account, scope)` that fails closed on a missing/revoked refresh token → impact: Stop
- The invoke path (`src/artemis/capabilities/invoke.py` `confirm_invoke`) resolves static secrets via `resolve_secret_values(skill.secrets, ...)` and injects them into `FetchSandbox.run(secrets=...)`; the OAuth token is injected the SAME way, as an extra env secret (e.g. `GOOGLE_ACCESS_TOKEN`) → impact: Stop
- Tokens are minted/injected ONLY at real invoke, never at build/verify (consistent with `verify-auth-unverified-mark` Option 1) → impact: Stop
- A capability declares at most one Google account/scope-set for now (single-account, fixed `"default"` account); multi-account is out of scope → impact: Caution
- The `oauth_scopes` field on `Skill`/`SkillDraft` already ships (from `capability-metadata`, verified present in `src/artemis/types.py` + store round-trip); this spec does NOT define or persist that field → impact: Stop

Simplicity check: reuse the existing `secrets=` injection channel rather than a new sandbox parameter — the access token is just another env secret to the capability; only its *resolution* is dynamic.

## Prerequisites
- `oauth-1-broker-core` (broker) — **SHIPPED** (`c01e747`). Broker exposes `mint_access_token(account, scope) -> str` (fails closed with a typed error on missing/revoked/errored).
- `oauth-2-connect-routes` — required (sets `app.state.oauth_broker`, which `ask_routes.py` reads). Build oauth-2 first.
- `capability-metadata` — **SHIPPED** (`164e420`); defines `oauth_scopes` on `Skill`/`SkillDraft` + round-trip + store plumbing. This spec only ADDS invoke-time resolution.
- `verify-auth-unverified-mark` — **SHIPPED** (`4fa2b71`); added `mark_auth_verified` write-back to `invoke.py`. This spec adds the OAuth-token mint/inject branch to the same `confirm_invoke`. Additive; rebase onto current `invoke.py`.

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| src/artemis/capabilities/invoke.py | modify | add optional `oauth_broker` kwarg (a local Protocol, default None); when `skill.oauth_scopes` non-empty: mint via the broker, merge one `GOOGLE_ACCESS_TOKEN` into the injected `secrets` dict; broker None / any mint failure / missing / revoked / partial → `InvokeConfirmResult(status="reconnect_google")` (fail closed, no partial injection, no crash, no leaked internals) |
| tests/capabilities/test_invoke.py | modify | oauth-scope capability → token injected; broker None or fail-closed → reconnect status; multi-scope partial failure → reconnect + no injection; egress unchanged |
| src/artemis/api/ask_routes.py | modify | pass `oauth_broker=request.app.state.oauth_broker` into `confirm_invoke` (the desktop Ask confirm route) |
| tests/api/test_ask_routes.py | modify | confirm-route test still green with the new kwarg (broker present/absent) |
<!-- ingress.py (Telegram confirm path) is DELIBERATELY not touched: it calls confirm_invoke without a broker → oauth-scope capabilities fail closed to reconnect_google there until Telegram invoke lands (R4). Non-oauth capabilities are unaffected (broker kwarg defaults None). -->
<!-- The oauth_scopes field lives in capability-metadata (SHIPPED); this spec does NOT touch types.py/skill_md.py/store.py. -->
<!-- app.state.oauth_broker is set by oauth-2 (Task 3) — build oauth-2 first. -->

## Tasks
- [ ] Task 1: Extend `confirm_invoke` in `invoke.py`. Add `reconnect_google` to the `InvokeConfirmResult.status` Literal. Add a local `Protocol` (e.g. `_OAuthMinter` with `async def mint_access_token(self, account: str, scope: str) -> str`) and an optional kwarg `oauth_broker: _OAuthMinter | None = None` — do NOT import the concrete `OAuthBroker` (keep layering: capabilities/ must not import oauth/). When `skill.oauth_scopes` is non-empty: if `oauth_broker is None` → return `InvokeConfirmResult(status="reconnect_google")` (path not wired). Else, in a `try` that catches broad `Exception`, mint for EACH declared scope via `oauth_broker.mint_access_token("default", scope)` (this both validates the scope was granted and mints); on any exception → return `reconnect_google`, inject NO token, do NOT run the sandbox, never crash, never surface internal exception detail. On all-success, merge ONE `GOOGLE_ACCESS_TOKEN` (the minted account token) into the `resolved` secrets dict passed to `sandbox.run(secrets=...)`. Static-secret resolution is unchanged and composes. Injecting the token does NOT touch `egress_domains` (passed through unchanged from `skill.egress_domains`). — files: src/artemis/capabilities/invoke.py, tests/capabilities/test_invoke.py — done when: an oauth-scope capability with a stub broker gets `GOOGLE_ACCESS_TOKEN` in the captured `sandbox.run` secrets alongside static secrets; `oauth_broker=None`, a raising broker, and a partial multi-scope failure each yield `reconnect_google` with NO token injected and the sandbox NOT run; the token never appears in logs/result/quarantine prompts; `egress_domains` passed to `sandbox.run` is unchanged by the token path.
- [ ] Task 2: In `ask_routes.py`, pass `oauth_broker=request.app.state.oauth_broker` into the `confirm_invoke(...)` call in the desktop Ask confirm route. Keep `tests/api/test_ask_routes.py` green (the confirm route now supplies the broker kwarg). — files: src/artemis/api/ask_routes.py, tests/api/test_ask_routes.py — done when: the confirm route passes the broker; existing ask-route tests pass; mypy/ruff/pytest green.

## Wave plan
Wave 1: [Task 1]
<!-- Single task. Whole spec sequences AFTER capability-metadata (shipped) and verify-auth-unverified-mark (shipped, shared invoke.py) — rebase onto current invoke.py. -->

## Permissions
### File Operations
| Action | Paths |
|--------|-------|
| Modify | src/artemis/capabilities/invoke.py, tests/capabilities/test_invoke.py, CHANGELOG.md |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy` | type gate |
| `uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/` | lint/format |
| `uv run pytest -q` | test gate |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | modified files + CHANGELOG.md |
| `git commit` | "feat(oauth): dynamic access-token injection at invoke for oauth-scope capabilities" |

## Specialist Context
### Security (review DONE 2026-07-03 — apex-security; findings folded above)
This wires a live, minted Google **access token** into the untrusted-capability isolate. `cross_model_review: true`. Invariants pinned in the task/ACs: (1) the minted token reaches ONLY the isolate env (same channel as static secrets), never logs / never `FetchResult.output` / never quarantine prompts (mirror the existing secret invariants in `invoke.py`); (2) mint happens only after the confirm gate and only at real invoke (never build/verify); (3) fail-closed on broker unavailability, ANY broker exception, and partial multi-scope failure (`reconnect_google`) with no partial/blank-token injection and no leaked internals; (4) a capability can only obtain a token for a scope it declared AND the owner granted (broker-enforced); (5) declaring a scope does NOT auto-open egress — egress stays the explicit `egress_domains` allowlist, unchanged by this path.

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | src/artemis/capabilities/invoke.py | document the dynamic-secret path + reconnect_google status |
| Changelog | CHANGELOG.md | Unreleased/Added — OAuth token injection at invoke |

## Acceptance Criteria
- [ ] `confirm_invoke` on an oauth-scope capability (stub broker returns a token, stub sandbox captures `secrets`) → verify the minted token is present in the injected `secrets` under the expected env name, alongside any static secrets.
- [ ] Broker fail-closed (missing/revoked refresh token) → verify `InvokeConfirmResult(status="reconnect_google")` and the sandbox is NOT run.
- [ ] Broker raises an exception (timeout/5xx/malformed) → verify `reconnect_google`, no crash, and no internal exception detail in the result.
- [ ] Multi-scope capability where one scope mints and another fails → verify `reconnect_google`, NO token (partial set) injected, sandbox not run.
- [ ] Injecting an OAuth token leaves `egress_domains` resolution unchanged — an oauth-scope capability with no matching egress entry still cannot reach the network (assert egress config is untouched by the token-injection code path).
- [ ] The minted token never appears in logs, the returned result, or quarantine prompts (assert against captured log records + result text).
- [ ] `uv run mypy`/`ruff` clean; `pytest -q` green.
<!-- The `oauth_scopes` field persistence/round-trip is verified by capability-metadata's own acceptance criteria (shipped) — not re-tested here. -->

## Progress
_(Coding mode writes here — do not edit manually)_
