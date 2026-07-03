---
spec: oauth-3-invoke-integration
status: draft
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
- A capability declares at most one Google account/scope-set for now (single-account); multi-account is out of scope → impact: Caution

Simplicity check: reuse the existing `secrets=` injection channel rather than a new sandbox parameter — the access token is just another env secret to the capability; only its *resolution* is dynamic.

## Prerequisites
- `oauth-1-broker-core` (broker) — required.
- **`capability-metadata` (build FIRST)** — defines the `oauth_scopes` field on `Skill` + `SkillDraft`, its SKILL.md frontmatter round-trip, and the store stage/promote/read plumbing. This spec no longer defines that field; it only ADDS the invoke-time resolution logic (consolidation, 2026-07-03).
- **`verify-auth-unverified-mark` (build BEFORE this):** both specs edit `src/artemis/capabilities/invoke.py` (verify-auth adds the `mark_auth_verified` write-back call; this adds the OAuth-token mint/inject branch). Additive + compatible, but the SAME file — sequence after verify-auth and rebase onto it; do not build concurrently.

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| src/artemis/capabilities/invoke.py | modify | when `skill.oauth_scopes` non-empty: mint token(s) via the broker, merge into the injected `secrets` dict; missing/revoked → `InvokeConfirmResult(status="reconnect_google")` (fail closed, no crash) |
| tests/capabilities/test_invoke.py | modify | oauth-scope capability → token injected; broker fail-closed → reconnect status |
<!-- types.py / skill_md.py / store.py are NO LONGER touched here — the oauth_scopes field lives in capability-metadata. -->

## Tasks
- [ ] Task 1: Extend `confirm_invoke` (and the `InvokeConfirmResult` status enum) so that when `skill.oauth_scopes` is non-empty (the field exists from `capability-metadata`), the broker mints a fresh access token per scope and it is merged into the `resolved` secrets dict (env name e.g. `GOOGLE_ACCESS_TOKEN`) passed to `sandbox.run(secrets=...)`. A missing/revoked refresh token (broker fail-closed) → return `InvokeConfirmResult(status="reconnect_google")` (new status), never crash, never leak the token. Static-secret resolution is unchanged and composes with this. The broker is injected into `confirm_invoke` (add a param / read from app.state at the call site). — files: src/artemis/capabilities/invoke.py, tests/capabilities/test_invoke.py — done when: an oauth-scope capability gets the minted token injected (asserted via a stub broker + stub sandbox capturing `secrets`); a fail-closed broker yields `reconnect_google` and does not run the sandbox.

## Wave plan
Wave 1: [Task 1]
<!-- Single task. Whole spec sequences AFTER capability-metadata (field) and verify-auth-unverified-mark (shared invoke.py). -->

## Permissions
### File Operations
| Action | Paths |
|--------|-------|
| Modify | src/artemis/types.py, src/artemis/capabilities/skill_md.py, src/artemis/capabilities/store.py, src/artemis/capabilities/invoke.py, tests/capabilities/test_invoke.py + types/skill_md/store tests |

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
### Security
**BLOCKER: apex-security review pending — do not mark `ready` until run.** `cross_model_review: true`. This wires a live, minted Google **access token** into the untrusted-capability isolate. Review focus: (1) the minted token reaches ONLY the isolate env (same channel as static secrets), never logs / never `FetchResult.output` / never quarantine prompts (mirror the existing secret invariants in `invoke.py`); (2) mint happens only after the confirm gate and only at real invoke (never build/verify); (3) fail-closed on broker unavailability (`reconnect_google`) with no partial/blank-token injection; (4) a capability can only obtain a token for a scope it declared AND that the owner granted (broker-enforced). Egress for a Google capability must still be an explicit allowlist (e.g. `googleapis.com`) via the existing `egress_domains` — declaring a scope does NOT auto-open egress.

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | src/artemis/capabilities/invoke.py | document the dynamic-secret path + reconnect_google status |
| Changelog | CHANGELOG.md | Unreleased/Added — OAuth token injection at invoke |

## Acceptance Criteria
- [ ] A capability with `oauth_scopes=["...gmail.readonly"]` persists + reads back; capabilities without it read `[]`.
- [ ] `confirm_invoke` on an oauth-scope capability (stub broker returns a token, stub sandbox captures `secrets`) → verify the minted token is present in the injected `secrets` under the expected env name, alongside any static secrets.
- [ ] Broker fail-closed (missing/revoked refresh token) → verify `InvokeConfirmResult(status="reconnect_google")` and the sandbox is NOT run.
- [ ] The minted token never appears in logs, the returned result, or quarantine prompts (assert against captured log records + result text).
- [ ] `uv run mypy`/`ruff` clean; `pytest -q` green.

## Progress
_(Coding mode writes here — do not edit manually)_
