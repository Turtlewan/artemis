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
- `oauth-1-broker-core` (broker) — required.
- `capability-metadata` — **SHIPPED** (`164e420`); defines `oauth_scopes` on `Skill`/`SkillDraft` + its SKILL.md round-trip + store plumbing. This spec only ADDS invoke-time resolution.
- `verify-auth-unverified-mark` — **SHIPPED** (`4fa2b71`); it added the `mark_auth_verified` write-back to `invoke.py`. This spec adds the OAuth-token mint/inject branch to the same `confirm_invoke`. Additive + compatible; rebase onto current `invoke.py`.

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| src/artemis/capabilities/invoke.py | modify | when `skill.oauth_scopes` non-empty: mint token(s) via the broker, merge into the injected `secrets` dict; any mint failure / missing / revoked / broker error → `InvokeConfirmResult(status="reconnect_google")` (fail closed, no partial injection, no crash, no leaked internals) |
| tests/capabilities/test_invoke.py | modify | oauth-scope capability → token injected; broker fail-closed → reconnect status; multi-scope partial failure → reconnect + no injection; egress unchanged |

## Tasks
- [ ] Task 1: Extend `confirm_invoke` (and the `InvokeConfirmResult` status enum with a new `reconnect_google` value) so that when `skill.oauth_scopes` is non-empty, the broker mints a fresh access token per declared scope and it is merged into the `resolved` secrets dict (env name e.g. `GOOGLE_ACCESS_TOKEN`) passed to `sandbox.run(secrets=...)`. Fail-closed semantics: a missing/revoked refresh token, ANY broker exception (network timeout, 5xx, malformed response), OR a partial multi-scope failure (some scopes mint, at least one does not) → return `InvokeConfirmResult(status="reconnect_google")`, inject NO token (not even the ones that succeeded), do NOT run the sandbox, never crash, and never surface internal exception detail (sanitized). Static-secret resolution is unchanged and composes with this. Injecting an OAuth token does NOT modify `egress_domains` resolution — network reach stays whatever the capability's declared allowlist grants. The broker is injected into `confirm_invoke` (add a param / read from `app.state` at the call site). — files: src/artemis/capabilities/invoke.py, tests/capabilities/test_invoke.py — done when: an oauth-scope capability gets the minted token injected (asserted via a stub broker + stub sandbox capturing `secrets`); a fail-closed broker AND a partial multi-scope failure each yield `reconnect_google` with no token injected and the sandbox not run; a broker exception maps to `reconnect_google` with no internal detail in the result; the token never appears in logs/result/quarantine prompts; egress config is unchanged by the token-injection path.

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
