---
spec: oauth-4-client-ui
status: ready
token_profile: lean
autonomy_level: L5
coder_effort: medium
---

# Spec: Google OAuth broker — client Connect/disconnect UI

**Identity:** Desktop client "Connect Google account" action + connected-account/granted-scopes view with disconnect, over the oauth connect routes.
→ why: docs/technical/adr/ADR-044-google-oauth-broker-byo-client.md (decision 6)

## Assumptions
- The oauth routes (`oauth-2-connect-routes`) exist: connect (returns consent URL), status (accounts+scopes), disconnect → impact: Stop
- The session token stays in Rust (Tauri command pattern), mirroring the existing `app_invoke_confirm` / keys-panel gateway commands in `client/src-tauri/src/gateway.rs` → impact: Stop
- TS wrappers live under `client/src/api/` (the gateway dir is `src/api`, not `src/gateway`); a sibling module `client/src/api/oauth.ts` matches the existing `bless.ts` pattern → impact: Stop
- Opening the consent URL uses the OS browser (Tauri shell/opener) — the loopback listener (brain, spec 1) catches the redirect; the client does not embed a webview for Google consent, and the brain does not open a browser server-side (oauth-2 injects a no-op opener) → impact: Stop
- **Single connected account for the MVP** — the panel shows the one connected Google account as "Connected" + its granted scopes; the specific email is not displayed (account identity is a fixed label brain-side, not email-derived) → impact: Caution

Simplicity check: reuse the existing keys-panel / gateway-command pattern; the OAuth UI is a section in the existing `KeysPanel`, not a new surface.

## Prerequisites
- `oauth-2-connect-routes` (routes) — required.
- Shares no brain files with the other oauth specs; client-only. Independent of `verify-auth-unverified-mark` and R4.

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| client/src-tauri/src/gateway.rs | modify | `app_oauth_connect` / `app_oauth_status` / `app_oauth_disconnect` Tauri commands (session token injected in Rust) |
| client/src-tauri/src/lib.rs | modify | register the three commands in the `generate_handler!` list |
| client/src/api/oauth.ts | create | TS wrappers over the commands (sibling to `bless.ts`) |
| client/src/api/oauth.test.ts | create | wrapper tests (vitest) |
| client/src/settings/KeysPanel.tsx | modify | "Connect Google account" section (opens consent URL) + connected-account/scopes list + Disconnect + `reconnect_google` prompt |
| client/src/settings/KeysPanel.test.tsx | modify | component tests |

## Tasks
- [ ] Task 1: Add the three Tauri commands in `client/src-tauri/src/gateway.rs`, register them in the `generate_handler!` macro in `client/src-tauri/src/lib.rs`, and add `client/src/api/oauth.ts` TS wrappers (session token injected in Rust, not the webview), mirroring the existing gateway-command pattern. — files: client/src-tauri/src/gateway.rs, client/src-tauri/src/lib.rs, client/src/api/oauth.ts, client/src/api/oauth.test.ts — done when: the wrappers call the routes, the commands are registered, the session token never appears in the webview; vitest wrapper tests pass and `cargo test` is green.
- [ ] Task 2: Add the OAuth section to `KeysPanel.tsx`: "Connect Google account" (scope pick → connect → open the returned consent URL in the OS browser via Tauri opener), a connected-account + granted-scopes list, and Disconnect. Reflect a `reconnect_google` state surfaced from an invoke (prompt to reconnect). — files: client/src/settings/KeysPanel.tsx, client/src/settings/KeysPanel.test.tsx — done when: connect opens the consent URL, the list renders the account+scopes from status, disconnect calls through; component tests pass; `tsc`/`eslint`/vitest clean.

## Wave plan
Wave 1: [Task 1] | Wave 2: [Task 2]
<!-- 6 files but one cohesive feature across two sequential layers (gateway → UI); Task 2 depends on Task 1's wrappers. Kept as one spec (no parallelism to gain from a split). -->

## Permissions
### File Operations
| Action | Paths |
|--------|-------|
| Create | client/src/api/oauth.ts, client/src/api/oauth.test.ts |
| Modify | client/src-tauri/src/gateway.rs, client/src-tauri/src/lib.rs, client/src/settings/KeysPanel.tsx, client/src/settings/KeysPanel.test.tsx, CHANGELOG.md |

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
Session token stays in Rust (never the webview), per the established gateway pattern. The UI shows the connected account label + granted scope names only (never tokens). Opening the OS browser for consent (not an embedded webview) avoids the client handling Google credentials at all. No BLOCKER; a light review that no token/secret crosses into the webview.

### Accessibility
The Connect section follows the existing `KeysPanel` a11y (labels, focus, keyboard) — match the sibling panel.

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | client/src/api/oauth.ts | wrapper docs |
| Changelog | CHANGELOG.md | Unreleased/Added — Connect Google UI |

## Acceptance Criteria
- [ ] Connect → verify the returned consent URL opens in the OS browser and the session token is not exposed to the webview.
- [ ] Status → verify the panel lists the connected account + granted scopes (no token values).
- [ ] Disconnect → verify it calls through and the account drops from the list.
- [ ] A `reconnect_google` invoke outcome surfaces a reconnect prompt.
- [ ] The three commands are registered in `lib.rs`; client `tsc`/`eslint`/vitest clean; `cargo test` green.

## Progress
_(Coding mode writes here — do not edit manually)_
