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
- The oauth routes (`oauth-2-connect-routes`) exist (SHIPPED `64a0a9f`): connect (returns consent URL), status (account+scopes), disconnect → impact: Stop
- The session token stays in Rust (Tauri command pattern), mirroring the existing gateway commands in `client/src-tauri/src/gateway.rs`: a thin `#[tauri::command] pub(crate) async fn app_X(state: State<AppState>, ...)` delegates to a private helper using `request_json`/`request_empty(..., authed=true)` (bearer token injected in Rust from `AppState`). Register each command in the `generate_handler!` list in `client/src-tauri/src/lib.rs` → impact: Stop
- TS wrappers live under `client/src/api/` (the gateway dir is `src/api`, not `src/gateway`); a sibling module `client/src/api/oauth.ts` matches the existing `bless.ts` pattern (`export const x = (...) => call("app_x", {...})` using the `invoke`-based `call` helper) → impact: Stop
- **The BRAIN opens the consent browser** (`webbrowser.open` on the local desktop host — see the prerequisite app.py opener flip), NOT the client. The client has no opener/shell plugin; adding one is out of scope. The client's connect command just triggers the flow; the brain opens the OS browser and its loopback listener (spec 1) catches the redirect. The client may show the returned `consent_url` as selectable fallback text but does not open it → impact: Stop
- **Single connected account for the MVP** — the panel shows the one connected Google account as "Connected" + its granted scopes; the specific email is not displayed (account identity is a fixed label brain-side, not email-derived) → impact: Caution

Simplicity check: reuse the existing keys-panel / gateway-command pattern; the OAuth UI is a section in the existing `KeysPanel`, not a new surface. Brain-opens avoids adding a Tauri opener plugin (Cargo + npm + capability + permission) for identical UX on this single-machine desktop deployment.

## Prerequisites
- `oauth-2-connect-routes` (routes) — SHIPPED (`64a0a9f`).
- **Brain opener flip** — a 1-line change so `create_app` constructs `OAuthBroker` with its default `webbrowser.open` opener (not the no-op), landed as a small fix before this spec. Client-only otherwise.
- Client-only; shares no brain files. Independent of `verify-auth-unverified-mark` and R4.

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| client/src-tauri/src/gateway.rs | modify | `app_oauth_connect` / `app_oauth_status` / `app_oauth_disconnect` Tauri commands (session token injected in Rust) |
| client/src-tauri/src/lib.rs | modify | register the three commands in the `generate_handler!` list |
| client/src/api/oauth.ts | create | TS wrappers over the commands (sibling to `bless.ts`) |
| client/src/api/oauth.test.ts | create | wrapper tests (vitest) |
| client/src/settings/KeysPanel.tsx | modify | "Connect Google account" section (triggers connect; brain opens browser) + connected-account/scopes list + Refresh + Disconnect + `reconnect_google` prompt |
| client/src/settings/KeysPanel.test.tsx | modify | component tests |

## Tasks
- [ ] Task 1: Add the three Tauri commands in `client/src-tauri/src/gateway.rs`, register them in the `generate_handler!` macro in `client/src-tauri/src/lib.rs`, and add `client/src/api/oauth.ts` TS wrappers (session token injected in Rust, not the webview), mirroring the existing gateway-command pattern. — files: client/src-tauri/src/gateway.rs, client/src-tauri/src/lib.rs, client/src/api/oauth.ts, client/src/api/oauth.test.ts — done when: the wrappers call the routes, the commands are registered, the session token never appears in the webview; vitest wrapper tests pass and `cargo test` is green.
- [ ] Task 2: Add the OAuth section to `KeysPanel.tsx`: "Connect Google account" (scope pick → call the connect command; the BRAIN opens the OS browser — show a "A browser window opened — approve access, then Refresh" hint, optionally the returned `consent_url` as selectable fallback text), a connected-account + granted-scopes list (from status, with a Refresh control), and Disconnect. Reflect a `reconnect_google` state surfaced from an invoke (prompt to reconnect). The client does NOT open a URL itself. — files: client/src/settings/KeysPanel.tsx, client/src/settings/KeysPanel.test.tsx — done when: connect calls the connect command (no client-side URL open), the list renders the account+scopes from status, disconnect calls through; component tests pass; `tsc`/`eslint`/vitest clean.

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
- [ ] Connect → verify the connect command is called and the session token is not exposed to the webview (the client does not open a URL; the brain opens the browser).
- [ ] Status → verify the panel lists the connected account + granted scopes (no token values).
- [ ] Disconnect → verify it calls through and the account drops from the list.
- [ ] A `reconnect_google` invoke outcome surfaces a reconnect prompt.
- [ ] The three commands are registered in `lib.rs`; client `tsc`/`eslint`/vitest clean; `cargo test` green.

## Progress
_(Coding mode writes here — do not edit manually)_
