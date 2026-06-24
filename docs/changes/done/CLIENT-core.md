---
spec: client-core
status: ready
token_profile: balanced
autonomy_level: L2
cross_model_review: true
---

# Spec: CLIENT-core — Tauri 2 client foundation (scaffold + Rust gateway transport + connection/lock state machine + DTOs + layout sync)

**Identity:** Scaffolds the Tauri 2 desktop client (`client/`: React/TS/Vite webview + Rust `src-tauri/` core) and builds its non-visual foundation — the Rust-core HTTP/SSE gateway to the brain's `/app/*` surface (session token held in Rust, never the webview), the typed TS DTO + facade layer over `invoke`, the 4-state connection/lock machine the UI reads, and the brain-synced layout client.
→ why: see docs/technical/adr/ADR-023 (Tauri platform) · ADR-025 (auth/lock states) · ADR-028 (the map shell these foundations serve) · docs/drafts/tauri-client-spec-rewrite.md (the carve + the 4 settled decisions).

<!-- Split rule: flagged atomic exception (precedent: CLIENT-c shipped the whole ArtemisKit package as one spec, "must compile as a unit"; M1-c bundled gateway+CLI+API+main). CLIENT-core is ONE cohesive foundation — a Tauri project that must build as a unit (Rust core + TS webview + their IPC contract are mutually dependent). The auth crypto/FFI is CLIENT-auth; all visual layers are theme/world/card/screens; the Ask popup is CLIENT-ask. -->

## Assumptions
- **The brain `/app/*` HTTP surface (old CLIENT-a/b, Python) is the contract this client targets — it survives the Tauri rewrite (ADR-025).** Route paths + wire DTO field names are taken verbatim from `docs/changes/CLIENT-b-app-endpoints.md` (snake_case wire). → impact: Stop (the DTOs + request shapes are a cross-language wire contract; a field-name drift breaks every call).
- **The CLIENT-b amendment adds `GET/PUT /app/layout`** (session-gated, owner-private layout store, last-writer-wins on `updated_at`) — decision 2 of the rewrite. CLIENT-core *consumes* it; the brain endpoint itself is the separate CLIENT-b amendment. → impact: Stop (layout sync calls a route that the amendment must ship; off-box tests mock it).
- **The device-key signer + the pair/connect/unlock *orchestration* are CLIENT-auth.** CLIENT-core provides the raw transport (HTTP request builders for the auth routes as internal Rust fns) + the state machine; CLIENT-auth's plugin signs and drives the handshakes by composing these. → impact: Stop (the auth-route invoke commands live in CLIENT-auth; core exposes the transport fns it calls).
- **Secrets stay in the Rust core (apex-tauri NEVER).** The session token + brain base URL live in Rust managed state; the webview never holds the token and makes **no** direct network requests — every brain call is a typed `invoke` command, so CSP stays locked to `ipc:`. → impact: Stop (this is the security model; a webview-side fetch + token would break it).
- **Windows build prereq:** the **MSVC** toolchain (`rustup default stable-msvc` + VS C++ Build Tools) is required — the box default is GNU (`dlltool not found`); see apex-tauri impl.md. → impact: Stop (no Tauri build compiles without it; `npm run tauri info` verifies).
- Tauri 2.11.x / `@tauri-apps/* ^2` per `docs/research/2026-06-24-tauri2-stack.md`; React 19 + Vite 5 + TS 5. → impact: Caution (pin minors; lockfiles committed).

Simplicity check: considered the webview `fetch`-ing the brain directly (token in JS, CSP opened to the tailnet origin) — rejected; it violates the apex-tauri secrets-in-core rule for a privacy-first client and would scatter the token across the untrusted webview. The Rust-core gateway is marginally more code but is the load-bearing security posture (ratified — ADR-030). Considered splitting scaffold/transport/state into 3 specs — rejected; a non-building partial Tauri project is useless (same atomic-package rationale as CLIENT-c).

## Prerequisites
- Specs that must be complete first: **none** to draft/build the scaffold + transport + state against fakes. **Sequenced-with:** the CLIENT-b `/app/layout` amendment (off-box tests mock it; live layout sync needs it) and CLIENT-auth (provides the signer + drives the auth-route transport fns — core compiles + tests standalone with a fake signer/no-auth).
- Repo root = the Artemis repo (`client/` is a new top-level dir alongside `src/` and `swift/`). Node ≥20, Rust **MSVC** toolchain, WebView2 (present on Win 11).
- Environment setup required: `npm install` in `client/`; `cargo` fetches crates on first build.

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| client/package.json | create | `@tauri-apps/cli ^2`, `@tauri-apps/api ^2`, react 19, vite, typescript, vitest, eslint; scripts: dev/build/preview/tauri + typecheck/lint/test (the recipe add-ons per apex-tauri) |
| client/index.html · client/vite.config.ts · client/tsconfig.json · client/tsconfig.node.json | create | Vite+React+TS; `vite.config.ts` per research (port 5173 strictPort, `watch.ignored: ["**/src-tauri/**"]`, `envPrefix` incl. `TAURI_ENV_*`) |
| client/src/main.tsx · client/src/App.tsx | create | minimal entry + a placeholder shell (theme/world fill it later); reads `useConnection()` to show a bare connection banner only |
| client/src/api/dto.ts | create | TS interfaces mirroring CLIENT-b wire DTOs (snake_case) + `ConnectionState` type + `LayoutDTO`/`CardPlacement` + the `StreamEvent` union (`text`/`vault_locked`/`done` — **`done` carries `{path?, tool_used?, escalated}`** so the Ask engine tag renders on a streamed answer) |
| client/src/domains.ts | create | **canonical domain registry (single source — imported by theme/world/card/screens):** `type DomainId` (the 11 locked ids per DECISIONS-LOG 2026-06-23: `email·people·schedule·tasks·projects·travel·memory·knowledge·review·health·finance` — **`projects` is a separate card from `tasks`**, both in Planning, per the Tasks/Projects module split) + `domainLabel(id)` + `domainCluster(id)` (Comms/Planning/Knowledge/Self: Email→Comms · Schedule/Tasks/Projects/Travel→Planning · Memory/Knowledge/Review→Knowledge · Health/Finance→Self). Eliminates the three-places-define-domains drift. |
| client/src/api/errors.ts | create | `ApiError` discriminated union (`unauthenticated`/`vaultLocked`/`http`/`network`); maps 401→unauthenticated, 423→vaultLocked |
| client/src/api/gateway.ts | create | typed TS facade over `invoke(...)` for every `/app/*` route + `askStream` over a Tauri `Channel<StreamEvent>` (typed events, never raw `data:`); no `fetch`, no token in JS |
| client/src/state/connection.ts | create | the 4-state connection/lock machine (a typed store + transition fns the UI reads); `ConnectionState` = unpaired·disconnected·connectedLocked·unlocked |
| client/src/state/layout.ts | create | layout store: load via `gateway.layoutGet()`, debounced `layoutPut()` on drag-end (LWW on `updated_at`), `resetToDefault()` |
| client/src-tauri/Cargo.toml · build.rs | create | `tauri = {version="2", features=["test"]}`, `tauri-build`, `serde`, `serde_json`, `reqwest` (rustls), `tokio`, **`zeroize`** (session token = `Zeroizing<String>`), `thiserror`; `[lib] crate-type=["staticlib","cdylib","rlib"]`. **Commit `Cargo.lock`** (reproducible builds + supply-chain pinning). |
| client/src-tauri/tauri.conf.json | create | v2 schema: `app` key, `frontendDist:"../dist"`, `devUrl:"http://localhost:5173"`, top-level `identifier:"com.artemis.client"`, strict explicit CSP — `default-src 'self'`; `script-src 'self'` (NO `'unsafe-inline'`/`'unsafe-eval'`); `style-src 'self'`; `connect-src 'self' ipc: http://ipc.localhost`; `object-src/frame-src 'none'`. `http://ipc.localhost` is the **Tauri-internal IPC bridge only** — no other `http://` origin is permitted. If Vite needs inline styles, use Tauri's nonce injection (keep CSP-modification ON), NEVER `'unsafe-inline'`. |
| client/src-tauri/capabilities/default.json | create | default-deny; `windows:["main"]`; only `core:default` + the app's own command permissions (autogenerated) — no fs/shell/http plugin grants |
| client/src-tauri/src/main.rs · lib.rs | create | thin `main.rs` → `client_lib::run()`; `lib.rs` = `tauri::Builder` + managed `AppState` + `invoke_handler![...]` |
| client/src-tauri/src/state.rs | create | `AppState { session_token: Mutex<Option<Zeroizing<String>>>, brain_base_url: Mutex<Option<String>> }` (managed; token never crosses to the webview; **manual `Debug` impl redacts `session_token`** — no derive that prints it) |
| client/src-tauri/src/gateway.rs | create | `reqwest` client to the brain `/app/*`; serde DTO structs; **`pub(crate)`** internal request fns (incl. the auth routes for CLIENT-auth's plugin to compose — narrowest visibility) + `#[tauri::command]`s for the non-auth routes + a typed-event `Channel<StreamEvent>` `app_ask_stream` (`enum StreamEvent { Text(String), VaultLocked, Done }` — parsed in Rust; the raw `data:` string is NEVER forwarded to the webview); `GatewayError` (serializable; maps 401/423; never serializes the token). `reqwest` built WITHOUT debug/trace logging in release. |
| client/src-tauri/src/error.rs | create | `GatewayError` (`thiserror` + `impl Serialize`) — 401→`Unauthenticated`, 423→`VaultLocked`, else `Http{status}`/`Network` |
| client/src/api/gateway.test.ts · client/src/state/connection.test.ts | create | vitest: facade wrappers mock `@tauri-apps/api/core` `invoke`; state-machine transition table |
| client/src-tauri/src/gateway.rs (`#[cfg(test)]` block) | modify | cargo test: request shape + bearer injection + 401/423 mapping + token-never-leaks + zeroize + `StreamEvent` parsing, against a mock HTTP server (`wiremock`, a dev-dependency) |

## Tasks
- [ ] Task 1: Tauri 2 scaffold + config + capabilities — files: `client/package.json`, `client/index.html`, `client/vite.config.ts`, `client/tsconfig.json`, `client/tsconfig.node.json`, `client/src/main.tsx`, `client/src/App.tsx`, `client/src-tauri/Cargo.toml`, `client/src-tauri/build.rs`, `client/src-tauri/tauri.conf.json`, `client/src-tauri/capabilities/default.json`, `client/src-tauri/src/main.rs`, `client/src-tauri/src/lib.rs` — scaffold a Tauri 2 React/TS/Vite app (v2 config shapes ONLY — `app` not `tauri`, `frontendDist`/`devUrl`, top-level `identifier`, `lib.rs`+thin `main.rs`); strict CSP + default-deny capability per apex-tauri; `App.tsx` is a placeholder that renders the connection banner from `useConnection()` and nothing else. — done when: `cd client && npx tsc --noEmit` exit 0; `npm run build` produces `dist/`; `npm run tauri info` shows v2 config parsed; `cargo fmt --check` (in `src-tauri/`) exit 0. (Full `cargo check`/`tauri build` is MSVC-gated — record status.)
- [ ] Task 2: TS DTO + error + domain layer — files: `client/src/api/dto.ts`, `client/src/api/errors.ts`, `client/src/domains.ts` — TS interfaces mirroring CLIENT-b exactly (snake_case fields): `PairRequest/Response`, `SessionBegin/Complete Request/Response` (`session_token`, `expires_at` ISO string, `counter` number), `UnlockBegin/Complete Request/Response`, `StatusResponse {connected, vault_unlocked, device_id}`, `AskRequest`/`AskResponse {text, path?, tool_used?, escalated}`, `ReviewItem {name, description, status, action_class, safety, explanation}`, `LockResponse`, `OkResponse`; **new** `CardPlacement {domain_id, cluster, x, y}` + `LayoutDTO {placements: CardPlacement[], updated_at: string}`; `type ConnectionState = "unpaired"|"disconnected"|"connectedLocked"|"unlocked"`; `ApiError` discriminated union; `type StreamEvent = {type:"text",text:string}|{type:"vault_locked"}|{type:"done", path?:string, tool_used?:string, escalated?:boolean}` (the `done` event carries the answer metadata for the Ask engine tag). **`domains.ts`:** the canonical `type DomainId` (the 11 locked ids per DECISIONS-LOG 2026-06-23, incl. `projects` as a separate Planning card) + `domainLabel(id): string` + `domainCluster(id)` — the single source theme/world/card/screens import (no per-spec domain lists). — done when: `tsc --noEmit` exit 0; types exported.
- [ ] Task 3: Rust gateway transport + state + error — files: `client/src-tauri/src/state.rs`, `client/src-tauri/src/gateway.rs`, `client/src-tauri/src/error.rs`, wire into `client/src-tauri/src/lib.rs` — managed `AppState { session_token: Mutex<Option<Zeroizing<String>>>, brain_base_url: Mutex<Option<String>> }` with a **manual `Debug` impl that redacts `session_token`** (no token-printing derive anywhere); a `reqwest` client built WITHOUT debug/trace logging in release; serde structs mirroring the DTOs. **`pub(crate)` async fns** for every `/app/*` route (incl. `pair`/`session_*`/`unlock_*` — `pub(crate)` so CLIENT-auth's plugin module composes them, NOT webview commands here) that inject `Authorization: Bearer <token-from-state>` on authed routes; `#[tauri::command]`s for the **non-auth** routes only: `app_status`, `app_review_pending`, `app_review_auto_enabled`, `app_review_approve`, `app_review_reject`, `app_ask`, `app_lock`, `app_logout`; `app_ask_stream(channel: Channel<StreamEvent>)` — **parse each SSE frame in Rust** into `enum StreamEvent { Text(String), VaultLocked, Done { path: Option<String>, tool_used: Option<String>, escalated: bool } }` (emit `VaultLocked` on the `{"error":"vault_locked"}` terminal frame; `Done{..}` on `[DONE]`, carrying the answer metadata for the Ask engine tag); the raw `data:` string is NEVER forwarded. `GatewayError` (`thiserror` + `impl Serialize`) maps 401→`Unauthenticated`/423→`VaultLocked`/else `Http{status}`/`Network` and **never includes the raw token**. No-log invariant: no token/proof/bearer/nonce reaches any log, `Debug`, or serialized output. — done when: `cargo fmt --check` exit 0; (MSVC-gated) `cargo clippy -- -D warnings`/`cargo test` converge — record gated status if MSVC absent.
- [ ] Task 4: TS gateway facade + connection/lock state machine — files: `client/src/api/gateway.ts`, `client/src/state/connection.ts` — `gateway.ts`: typed async wrappers over `invoke("app_status")` etc. returning the Task-2 DTOs, throwing `ApiError`; plus `askStream` consuming the `Channel<StreamEvent>` and yielding the **typed** `StreamEvent` union (`{type:"text",text}` / `{type:"vault_locked"}` / `{type:"done", path?, tool_used?, escalated?}` — never a raw string); NO `fetch`, NO token in JS. `connection.ts`: a typed store holding `ConnectionState` + connection/lock info, with transition fns (`onPaired`, `onConnected`, `onLocked`, `onUnlocked`, `onDisconnected`, `onRevoked`) implementing app-flow.md's transition table; the UI subscribes. — done when: `tsc --noEmit` exit 0; the store's transitions match the app-flow.md table (Task 6 test).
- [ ] Task 5: Brain-synced layout client — files: `client/src-tauri/src/gateway.rs` (add `app_layout_get`/`app_layout_put` commands + internal fns; modify), `client/src/api/gateway.ts` (add `layoutGet`/`layoutPut`; modify), `client/src/state/layout.ts` (create) — `app_layout_get`→`GET /app/layout`, `app_layout_put(layout)`→`PUT /app/layout` (session-gated; both go through the Rust bearer path); `layout.ts` store loads on connect, debounces `layoutPut` on drag-end, applies LWW on `updated_at` (drop a stale PUT response), exposes `resetToDefault()`. — done when: `tsc --noEmit` exit 0; the store round-trips a `LayoutDTO` through a mocked `invoke` and discards an older `updated_at` (Task 6 test).
- [ ] Task 6: Tests — files: `client/src/api/gateway.test.ts`, `client/src/state/connection.test.ts`, `client/src-tauri/src/gateway.rs` (`#[cfg(test)]` block; modify) — vitest: facade calls mock `@tauri-apps/api/core` `invoke` and assert the right command + args + DTO mapping + `ApiError` on a thrown invoke; the connection store transition table; the layout LWW discard. cargo test: gateway request shape + bearer header on authed routes + 401→Unauthenticated / 423→VaultLocked against a mock HTTP server; **the token-never-leaks assertion** (`Debug`/`Serialize` of `AppState`/`GatewayError` omit the token + `"bearer"`); **the zeroize assertion** (token allocation zeroed after `app_logout`/`app_lock`); the `StreamEvent` frame parser (`text`/`vault_locked`/`done`). — done when: `npx vitest run` passes; (MSVC-gated) `cargo test` + `cargo audit` pass — record gated status if MSVC absent.

## Wave plan
Wave 1: [Task 1] | Wave 2: [Task 2, Task 3] | Wave 3: [Task 4, Task 5] | Wave 4: [Task 6]

## Permissions

The following actions will run autonomously during build. Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | client/** (package.json, index.html, vite/ts configs, src/main.tsx, src/App.tsx, src/api/{dto,errors,gateway}.ts, src/state/{connection,layout}.ts, src-tauri/{Cargo.toml,build.rs,tauri.conf.json}, src-tauri/capabilities/default.json, src-tauri/src/{main,lib,state,gateway,error}.rs, and the test files) |
| Modify | (none — all new) |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `cd client && npm install` | Install frontend + Tauri CLI deps |
| `cd client && npx tsc --noEmit` | Frontend typecheck gate |
| `cd client && npm run build` | Vite build → dist/ |
| `cd client && npx vitest run` | Frontend unit tests |
| `cd client && npx eslint . --max-warnings 0` | Frontend lint |
| `cd client/src-tauri && cargo fmt --check` | Rust format gate |
| `cd client/src-tauri && cargo clippy -- -D warnings` | Rust lint (MSVC-gated) |
| `cd client/src-tauri && cargo test` | Rust tests (MSVC-gated) |
| `cd client/src-tauri && cargo audit` | Supply-chain advisory scan (RustSec) on `Cargo.lock` |
| `cd client && npm run tauri info` | Env doctor (verify MSVC toolchain + v2 config) |
| `cd client && npm run tauri build -- --no-bundle` | Compile gate (MSVC-gated) |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | client/** |
| `git commit` | "feat: CLIENT-core Tauri 2 client foundation (scaffold + Rust gateway + connection state + DTOs + layout sync)" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `TAURI_ENV_*` | set by the Tauri CLI during build (platform target) — read-only |
| (brain base URL) | captured at pairing / Settings (CLIENT-auth), held in Rust `AppState` — NOT an env var |

### Network
| Action | Purpose |
|--------|---------|
| `npm install` | package install |
| `cargo` crate fetch | first build only |
| (runtime) Rust → brain `/app/*` over Tailscale/loopback | the gateway transport; the webview makes no network calls |

## Specialist Context
### Security
Load-bearing decision (RATIFIED — ADR-030; shapes CLIENT-auth + every data spec): **the HTTP client + session token live in the Rust core; the webview holds no token and makes no network requests — every brain call is a typed `invoke` command.** This honors apex-tauri's secrets-in-core rule and keeps CSP locked to `ipc:`. Consequences: the auth handshakes (pair/connect/unlock) run entirely in Rust (core transport + the CLIENT-auth signer plugin); the bearer is injected in Rust; the token is never serialized to the webview or logged. CSP is strict + explicit (`default-src`/`script-src`/`style-src`/`connect-src` all `'self'`-rooted; no `'unsafe-inline'`/`'unsafe-eval'`; `object-src`/`frame-src 'none'`; `http://ipc.localhost` = the Tauri IPC bridge only); capabilities are default-deny, window-scoped, no fs/shell/http plugin grants.

Review resolutions baked in (apex-security 2026-06-24): **(1) Token never logged/serialized** — `session_token` is `Zeroizing<String>`; `AppState` + any token-touching struct use a **manual `Debug` that redacts** it (no token-printing derive); `reqwest` carries no debug/trace logging in release; `GatewayError::Serialize` never includes the raw token; an AC test asserts the token is absent from any serialized/logged output. **(2) SSE is typed** — `app_ask_stream` parses frames in Rust to `StreamEvent { Text, VaultLocked, Done }`; the raw `data:` string never reaches the webview. **(4) Layout gate ACCEPTED** — `require_session` (not `require_unlocked`) for `GET/PUT /app/layout`: the map must function in `Connected·Vault-locked`, so the layout positioning it must be readable while locked; positions are low-sensitivity UX state (→ ADR-030 § Layout endpoint gate). **(5) Zeroize** — `Zeroizing<String>` zeroes the prior token allocation on `app_logout`/`app_lock` (AC-tested). **(6) Supply chain** — `cargo audit` gate + committed `Cargo.lock`. **(7)** internal auth-route transport fns are `pub(crate)` (narrowest for CLIENT-auth to compose).

### Performance
SSE chat streams via a Tauri `Channel` (ordered, efficient — research-preferred over repeated `emit`). Status/review are O(recipes) rule-based reads. Layout PUT is debounced on drag-end (no per-frame writes).

### Accessibility
(none — CLIENT-core is non-visual foundation; the bare connection banner in `App.tsx` is a placeholder. A11y lands in world/card/screens/theme.)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | client/src/api/*.ts, client/src-tauri/src/*.rs | TSDoc/rustdoc all exports; document the IPC command contract (command name, args, DTO, error mapping), the token-in-Rust invariant, AND the **no-log invariant** (no token/proof/bearer/nonce in any log, `Debug`, or serialized output) |
| API | docs/product/api/client-app-api.md | note the Tauri client consumes the existing `/app/*` surface + the new `/app/layout` route |
| ADR | docs/technical/adr/ADR-030-tauri-client-transport.md | ✅ Written this session — the "Rust-core gateway, token-in-Rust, webview-via-invoke" decision |

## Acceptance Criteria
- [ ] Run `cd client && npx tsc --noEmit` → verify: exit 0 (DTOs, facade, state machine all typed).
- [ ] Run `cd client && npm run build` → verify: `dist/` produced; exit 0.
- [ ] Run `cd client && npx vitest run` → verify: facade maps each `/app/*` command + DTO; throws `ApiError` (401→unauthenticated, 423→vaultLocked); connection store transitions match app-flow.md; layout LWW discards a stale `updated_at`.
- [ ] Run `cd client && npx eslint . --max-warnings 0` → verify: exit 0.
- [ ] Run `cd client/src-tauri && cargo fmt --check` → verify: exit 0.
- [ ] (MSVC-gated) Token never leaks → verify: a `#[cfg(test)]` assertion that `format!("{:?}", app_state)` and `serde_json::to_string(&gateway_error)` contain neither the token value nor `"bearer"`; the redacted `Debug` shows e.g. `session_token: <redacted>`.
- [ ] (MSVC-gated) Zeroize on lock/logout → verify: a `#[cfg(test)]` assertion that after `app_logout`/`app_lock` the prior token allocation is zeroed (the `Zeroizing<String>` drop path).
- [ ] Run `cd client/src-tauri && cargo audit` → verify: exit 0 (no unresolved RustSec advisory); `Cargo.lock` committed.
- [ ] Run `cd client && npm run tauri info` → verify: v2 config parsed; reports the active Rust toolchain (MSVC expected).
- [ ] (MSVC-gated) Run `cd client/src-tauri && cargo clippy -- -D warnings && cargo test` AND `cd client && npm run tauri build -- --no-bundle` → verify: converge; record gated status in handoff if the MSVC toolchain is not yet installed.

## Progress
_(Coding mode writes here — do not edit manually)_
