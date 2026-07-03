---
spec: oauth-4-client-ui
status: draft
token_profile: lean
autonomy_level: L5
coder_effort: medium
---

# Spec: Google OAuth broker — client Connect/disconnect UI

**Identity:** Desktop client "Connect Google account" action + connected-accounts/granted-scopes view with disconnect, over the oauth connect routes.
→ why: docs/technical/adr/ADR-044-google-oauth-broker-byo-client.md (decision 6)

## Assumptions
- The oauth routes (`oauth-2-connect-routes`) exist: connect (returns consent URL), status (accounts+scopes), disconnect → impact: Stop
- The session token stays in Rust (Tauri command pattern), mirroring the existing `app_invoke_confirm` / keys-panel gateway commands → impact: Stop
- Opening the consent URL uses the OS browser (Tauri shell/opener) — the loopback listener (brain, spec 1) catches the redirect; the client does not embed a webview for Google consent → impact: Caution

Simplicity check: reuse the existing keys-panel / gateway-command pattern; the OAuth UI is a sibling panel (Connect + list), not a new surface.

## Prerequisites
- `oauth-2-connect-routes` (routes) — required.
- Shares no brain files with the other oauth specs; client-only. Independent of `verify-auth-unverified-mark` and R4.

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| client/src-tauri/src/... (commands) | modify | `app_oauth_connect` / `app_oauth_status` / `app_oauth_disconnect` Tauri commands (session token in Rust) |
| client/src/gateway/oauth.ts | create | TS wrappers over the commands |
| client/src/.../<keys-or-settings panel>.tsx | modify | "Connect Google account" button (opens consent URL) + connected-accounts/scopes list + Disconnect |
| client/src/.../*.test.ts(x) | modify/create | wrapper + component tests (vitest) |

## Tasks
- [ ] Task 1: Add the three Tauri commands + `oauth.ts` TS wrappers (session token injected in Rust, not the webview), mirroring the existing gateway-command pattern. — files: client/src-tauri commands, client/src/gateway/oauth.ts + test — done when: the wrappers call the routes and the session token never appears in the webview; vitest wrapper tests pass.
- [ ] Task 2: Add the OAuth panel UI: "Connect Google account" (scope pick → connect → open the returned consent URL in the OS browser), a connected-accounts + granted-scopes list, and Disconnect. Reflect a `reconnect_google` state surfaced from an invoke (deep-link/prompt to reconnect). — files: client panel component + test — done when: connect opens the consent URL, the list renders accounts+scopes from status, disconnect calls through; component tests pass; `tsc`/`eslint`/vitest clean.

## Wave plan
Wave 1: [Task 1] | Wave 2: [Task 2]

## Permissions
### File Operations
| Action | Paths |
|--------|-------|
| Create | client/src/gateway/oauth.ts (+ tests) |
| Modify | client Tauri commands, the keys/settings panel component |

### Commands
| Command | Purpose |
|---------|---------|
| `npm run -w client tsc && npm run -w client lint` | type/lint (adjust to the repo's client scripts) |
| `npm run -w client test` | vitest |
| `cargo test` (client/src-tauri) | Rust command tests |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | client files + CHANGELOG.md |
| `git commit` | "feat(client): Connect Google account UI (OAuth broker)" |

## Specialist Context
### Security
Session token stays in Rust (never the webview), per the established gateway pattern. The UI shows account ids + granted scope names only (never tokens). Opening the OS browser for consent (not an embedded webview) avoids the client handling Google credentials at all. No BLOCKER; a light review that no token/secret crosses into the webview.

### Accessibility
The Connect panel follows the existing keys-panel a11y (labels, focus, keyboard) — match the sibling panel.

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | client/src/gateway/oauth.ts | wrapper docs |
| Changelog | CHANGELOG.md | Unreleased/Added — Connect Google UI |

## Acceptance Criteria
- [ ] Connect → verify the returned consent URL opens in the OS browser and the session token is not exposed to the webview.
- [ ] Status → verify the panel lists connected accounts + granted scopes (no token values).
- [ ] Disconnect → verify it calls through and the account drops from the list.
- [ ] A `reconnect_google` invoke outcome surfaces a reconnect prompt/deep-link.
- [ ] client `tsc`/`eslint`/vitest clean; `cargo test` green.

## Progress
_(Coding mode writes here — do not edit manually)_
