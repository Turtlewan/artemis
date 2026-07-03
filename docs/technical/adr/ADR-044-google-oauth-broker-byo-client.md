# ADR-044 — Google OAuth broker (bring-your-own client)

- **Status:** **Accepted** — owner + planning, 2026-07-03. Broker greenlit; specs `oauth-1..4` reviewed (apex-security ×2, apex-auth, apex-google) + promoted to `docs/changes/` ready. See § Refinements.
- **Date:** 2026-07-03
- **Deciders:** owner + planning
- **Refines:** ADR-039 (capability invoke/reuse — the broker plugs a *dynamic* credential into the existing secret-injection path) and the credential-kernel work (keychain `SecretStorePort`). Complements ADR-035 (network capabilities). Keeps ADR-009/037 quarantine unchanged.
- **Design basis:** owner discussion 2026-07-03 (the "is OAuth a spoke or builder-territory?" thread); live read of `invoke.py`, `fetch_sandbox.py`, `ports/secrets.py`, `types.py`, `api/app.py`.

## Context

A build-by-chat capability runs headless in the WSL2 isolate and gets secrets injected at invoke. That
fits *using* a Google token (call Gmail/Calendar with a bearer token = a normal network+secret
capability). It does **not** fit *acquiring* one: the OAuth authorization-code flow needs an
interactive browser consent + a redirect-catching listener + a stateful refresh lifecycle, none of
which a headless, run-to-completion sandbox capability can do — and you would not want model-authored
code holding the OAuth client secret or minting refresh tokens. So OAuth splits: **token acquisition +
refresh = infrastructure (this ADR); token use = builder-territory (a normal capability).**

## Decision

| # | Decision | Statement |
|---|----------|-----------|
| 1 | **Bring-your-own OAuth client** | The owner registers their own Google Cloud OAuth client (Desktop-app type) once and stores `client_id`+`client_secret` in the keychain via the existing `SecretStorePort`. No shipped/shared client. Rationale: Artemis is single-owner + self-hosted; the owner is their own test user, which sidesteps Google's app-verification review and the unverified-app warnings/100-user cap that a shared client hits for sensitive Gmail scopes. A screen-by-screen Cloud Console runbook ships with the broker. |
| 2 | **Loopback authorization-code flow with PKCE** | Standard OAuth desktop flow: the broker starts a temporary local HTTP listener on an ephemeral `127.0.0.1:<port>`, builds the consent URL (PKCE `code_challenge`, requested scopes, `access_type=offline`, `prompt=consent`), opens the owner's browser, catches the redirect + `code` on loopback, and exchanges `code`+`client_secret`+PKCE `verifier` for access + refresh tokens. No public redirect URI. |
| 3 | **Refresh token stored; access token minted on demand (the "dynamic secret")** | The long-lived **refresh token** goes in the keychain (per Google account). Access tokens (~1h) are **not** stored statically — the broker mints a fresh one via the refresh-token grant at each use, with an expiry-skew check and a short in-memory cache. This is the core reason the broker is more than a keychain entry. |
| 4 | **Invoke integration = a new "dynamic credential" resolution path** | A capability that needs Google declares an OAuth **scope** (`oauth_scopes` on the Skill), NOT a static secret. At invoke, alongside the existing static-secret resolution, the broker mints a fresh access token for the declared scope and it is injected into the isolate as an env secret (e.g. `GOOGLE_ACCESS_TOKEN`) via the existing `FetchSandbox.run(secrets=...)` channel. Tokens are minted/injected ONLY at real invoke — never at build/verify (consistent with the owner's Option-1 verify-credential-less choice, ADR-pending `verify-auth-unverified-mark`). |
| 5 | **Connect-time scope selection; per-capability scope declaration; incremental re-consent** | The owner picks which Google services to authorize when connecting (the granted scope set is recorded per account). A capability declares the scope it needs; the broker checks it was granted and, if not, triggers incremental re-consent rather than failing opaquely. |
| 6 | **Client "Connect Google" UI + revoke** | The desktop client gets a "Connect Google account" action (opens the flow) and a connected-accounts / granted-scopes view with disconnect. Disconnect revokes the refresh token (Google revoke endpoint) and deletes it from the keychain. |

## Consequences

**Positive:** one infra investment opens *all* of Google to build-by-chat — Gmail, Calendar, Drive,
etc. become normal capabilities that declare a scope. Credential acquisition stays vetted
infrastructure; the owner's real tokens never touch model-authored code at build time.

**Costs / trade-offs:**
- A one-time ~10-minute Google Cloud Console setup by the owner (the runbook covers it). This is the
  price of dodging Google's app-verification review.
- The broker is security-sensitive: it acquires + stores long-lived refresh tokens and holds the
  client secret. Every credential-handling spec here carries `cross_model_review: true` and a
  mandatory dispatched apex-security review before build-ready.
- Refresh-token revocation/expiry (owner revokes access, or Google expires it) must degrade cleanly —
  a capability invoke that can't mint a token fails closed with a "re-connect Google" signal, not a crash.
- Opening a browser + binding a loopback port is an interactive, desktop-bound action; it can't run in
  a headless/cron context (acceptable — connecting an account is a deliberate owner action).

## Refinements (2026-07-03 draft→ready review pass)

The dispatched domain reviews surfaced three decisions that refine the decisions above:

- **R1 — Consent-screen must be published to Production (refines decision 1).** An OAuth client left in Google's "Testing" publishing status issues refresh tokens that **expire after 7 days**, which would break the broker's durable-refresh design weekly. The runbook (`google-oauth-setup.md`) must instruct the owner to **publish the consent screen to Production** — a status flip distinct from Google's multi-week verification review; for the owner as sole user it only adds an "unverified app" warning screen. This is a required owner action in Cloud Console before first live use.
- **R2 — The client opens the consent browser, not the brain (refines decision 2).** Decision 2 said the broker "opens the owner's browser." Resolved: `begin_connect` takes an injected `open_browser` (default `webbrowser.open` for standalone/CLI use), but the connect route (oauth-2) injects a **no-op** so the desktop client (oauth-4) opens the returned consent URL via the OS browser — single opener, no double-tab, and keeps the brain headless-capable. The brain-side loopback listener still catches the redirect.
- **R3 — Account keyed by a fixed label, not email (refines decision 5).** Google's identity rules forbid using `email` as a primary key. For the single-account MVP the broker keys stored credentials by a caller-supplied `account` id that is a fixed constant (`"default"`), never email-derived. The UI shows "Connected to Google" + granted scopes without the specific email. Multi-account support + `sub`-based keying (via `openid` + id-token) + connected-email display are **deferred** — a future revision reopens decision 5.

## Alternatives considered
- **Shipped/shared Artemis OAuth client** — rejected (decision 1): the "secret" isn't secret in a
  self-hosted app, and sensitive Gmail scopes force app-verification or test-mode warnings; all cost,
  no benefit for a single-owner system.
- **App-password + IMAP for Gmail (no OAuth)** — a real escape hatch for Gmail specifically (a static
  secret, buildable-by-chat today), but Gmail-only and unscoped; Calendar and other Google APIs have no
  legacy-password path. Kept as the "value now" option; the broker is the general answer. Not mutually
  exclusive.
- **Service account / domain-wide delegation** — for Workspace-admin scenarios, not a personal account. Out of scope.
