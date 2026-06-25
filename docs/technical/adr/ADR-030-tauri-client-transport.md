# ADR-030 — Tauri client transport: Rust-core gateway (token-in-Rust, webview-via-invoke)

- **Status:** Accepted
- **Date:** 2026-06-24
- **Deciders:** owner + planning
- **Relates:** ADR-023 (Tauri client) · ADR-025 (client auth — the signer is already Rust-side) · ADR-028 (the CLIENT spec carve; this is a CLIENT-core decision) · `apex-tauri` skill (secrets-in-Rust NEVER rule) · `docs/research/2026-06-24-tauri2-stack.md` (IPC primitives; CSP).

## Context
The Tauri client talks to the brain's `/app/*` HTTP/SSE surface (CLIENT-b) behind a short-lived session bearer token. Two places can own that token + the network calls: the **webview** (TS `fetch` — standard web style) or the **Rust core** (every brain call marshalled through a typed `invoke` command). The choice is load-bearing — it shapes CLIENT-auth and every future per-domain data spec, and it sets the CSP posture.

## Decision
**The Rust core owns the session token and all brain transport. The webview holds no token and makes no direct network requests** — every brain call is a typed `#[tauri::command]` `invoke`; the Rust core injects `Authorization: Bearer <token-from-managed-state>` and performs the HTTP via `reqwest`. SSE (`/app/ask/stream`) streams from Rust to the webview over a Tauri **`Channel`** (honoring the `vault_locked` terminal frame). CSP stays locked: `default-src 'self'`; `connect-src 'self' ipc: http://ipc.localhost` (the webview has no network grant). Capabilities are default-deny, window-scoped, with no `http`/`fs`/`shell` plugin grants.

## Consequences
- **Positive:** the session token never enters the untrusted webview surface — an XSS/injected-content compromise in the frontend cannot exfiltrate the token or reach the brain directly (apex-tauri secrets-in-Rust NEVER rule + apex-security). The auth handshakes (pair/connect/unlock) and the CLIENT-auth signer plugin live together in Rust, composing the same internal transport fns. The token is never serialized to the webview or logged.
- **Negative (accepted):** more plumbing — every route needs a Rust transport fn + (for non-auth routes) a webview-facing command + its ACL permission; SSE goes through `Channel` rather than a native `EventSource`. The webview becomes a pure view that marshals all I/O through Rust.
- **Shapes downstream:** CLIENT-auth exposes the device-key signer + drives pair/connect/unlock by composing CLIENT-core's internal auth-route transport fns. Every future per-domain data spec adds its read endpoint as a Rust command, not a webview fetch.

## Alternatives considered
- **Webview holds the token + `fetch`** — *rejected.* Simpler (no Rust marshaling, native SSE), but the token lives in JS (XSS-reachable), CSP must open `connect-src` to the brain origin, and it violates the `apex-tauri` NEVER rule + the project's secrets-discipline posture (ADR-025 already keeps the signer in Rust). Weaker for a privacy-first personal assistant.

## Layout endpoint gate
`GET/PUT /app/layout` (the brain-synced map layout — ADR-028 decision 2) is gated at **`require_session`, not `require_unlocked`**. Rationale: app-flow.md requires the **map to function in `Connected·Vault-locked`** (Map + Status are the two surfaces that work while locked), so the layout that positions the map MUST be readable/writable while the vault is locked — gating it on unlock would brick map arrangement in the one state where the map is mostly what works. The exposure is low-sensitivity: card *positions* are generic domain names + coordinates (UX state), never vault data. **Accepted exposure.** (apex-security review 2026-06-24.)

## Sources
- `apex-tauri` skill (NEVER: secrets stay in Rust core) · `docs/research/2026-06-24-tauri2-stack.md` (Tauri `Channel` for streaming; strict CSP for a no-remote-content client).
