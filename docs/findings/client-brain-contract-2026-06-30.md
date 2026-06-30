# Artemis Client → Brain API Contract

_Mapped 2026-06-30 from `client/src-tauri/src/` (Rust Tauri layer). The Rust commands are the definitive list of brain endpoints the desktop client depends on._

## Transport

- **Base URL:** `http://127.0.0.1:8030` — hardcoded default in `lib.rs` (`DEFAULT_BRAIN_BASE_URL`), set into `AppState.brain_base_url` at app setup if unset. Loopback, plain HTTP (local brain on the same host). No env/config override path in current code (only tests set it via `set_base_url`).
- **HTTP client:** `reqwest::Client` (fresh per call — `gateway::client()`). JSON request/response via serde.
- **Two request paths:**
  - `request_json(...)` — standard JSON request/response. Non-2xx → `GatewayError::from_status` (401 → Unauthenticated, 423 → VaultLocked, else `Http{status}`). Reqwest transport errors → `Network`.
  - **Streaming (`/app/ask/stream`, `/app/ask/voice`)** — POST, but the client does **not** consume a live SSE stream. It awaits the full `response.text()` then splits on lines, takes lines prefixed `data:`, and parses each frame. So the brain returns SSE-framed text (`data: <payload>\n\n`), but the client buffers the whole body before parsing (no incremental streaming today). Frames are forwarded to the webview over a Tauri `Channel<StreamEvent>` (`tauri::ipc::Channel`), not a brain WebSocket.
- **SSE frame grammar** (`parse_stream_frame`): each `data:` payload is one of:
  - `[DONE]` → `StreamEvent::Done { path: None, tool_used: None, escalated: false }` (the DONE frame carries no metadata today).
  - JSON `{"error":"vault_locked"}` → `StreamEvent::VaultLocked`.
  - Any other JSON `{"error":"..."}` → hard `GatewayError::Network`.
  - Anything else (plain text) → `StreamEvent::Text { text }`.

## Auth / Session Model

Device-bound, signature-based handshake using a hardware keystore (`tauri_plugin_keystore`). Aligns with ADR-025 (P-256 signatures) and ADR-030 (session token never reaches the webview).

**Key material & identity**
- Keystore holds a per-device ECDSA P-256 key (test signatures begin `0x30 0x44` = DER ECDSA; public key is X9.63 uncompressed, `0x04`-prefixed). Created on first pair (`create_key`), counter reset alongside (`reset_for_new_key`).
- **`device_id`** = `"artemis-" + hex(sha256(public_key)[..16])`. Derived client-side; sent in pair + session/begin + session/complete.
- **Public key** sent base64 (STANDARD) only at pairing.
- **Monotonic counter** (`CounterStore` under `app_data_dir/keystore/counter`) — incremented per signed proof, sent in session/complete and unlock/complete to defeat replay. Corrupt/missing counter aborts (no silent reset).

**Signed message layouts** (SHA-256 digest of the message is what's signed):
- Pairing proof: `len16(pairing_code) ‖ code ‖ device_id` (device_id NOT length-prefixed, trails).
- Session/unlock proof: `len16(nonce) ‖ nonce ‖ len16(context) ‖ context ‖ counter_be64`. Context = `b"session"` for connect, `b"unlock"` for unlock. Domain separation prevents cross-use of a connect proof as an unlock proof.

**Flow**
1. **Pair** (`auth_pair`, code from user) → create/reuse key, sign pairing proof → `POST /app/pair` (unauthenticated). Brain returns `{paired: bool}`.
2. **Connect** (`auth_connect`) → `POST /app/session/begin {device_id}` → `{nonce_b64}`; sign nonce w/ `session` context + next counter → `POST /app/session/complete {device_id, nonce_b64, counter, signature_b64}` → `{session_token, expires_at: float}`. Token stored in **`AppState` (Rust memory only, `Zeroizing<String>`)** — deliberately never serialized back to the webview (ADR-030). `auth_connect` returns `()`.
3. **Unlock vault** (`auth_unlock`) → `POST /app/unlock/begin {}` (bearer-authed) → `{nonce_b64}`; sign w/ `unlock` context + counter → `POST /app/unlock/complete {nonce_b64, counter, signature_b64}` → `{unlocked: bool}`.
4. **Authenticated requests** carry `Authorization: Bearer <session_token>` (reqwest `.bearer_auth`). Missing token → `GatewayError::Unauthenticated` before any network call.
5. **Lock** (`app_lock`) → `POST /app/lock` → `{locked}`, then clears in-memory token regardless. **Logout** (`app_logout`/`auth_logout`) → `POST /app/logout` → `{ok}`, then clears token.

**Recovery** (`auth_recover`) — DEV-WALL: accepts a passphrase `String`, wraps in `Zeroizing`, and **discards it** (returns `Ok(())`). The Argon2id DEK-escrow broker relay is Mac-gated (ADR-005) and absent on the Windows dev box. No brain call today.

## Endpoint Table

Auth column: **none** = no bearer; **bearer** = `Authorization: Bearer <session_token>`; **sig** = body carries a keystore signature proof.

| Method | Path | Auth | Request body | Response body | Triggering `invoke()` command(s) |
|---|---|---|---|---|---|
| POST | `/app/pair` | none + sig | `{device_id, public_key_b64, pairing_code, code_signature_b64}` | `{paired: bool}` | `auth_pair` |
| POST | `/app/session/begin` | none | `{device_id}` | `{nonce_b64}` | `auth_connect` |
| POST | `/app/session/complete` | none + sig | `{device_id, nonce_b64, counter, signature_b64}` | `{session_token, expires_at: float}` | `auth_connect` |
| POST | `/app/unlock/begin` | bearer | `{}` | `{nonce_b64}` | `auth_unlock` |
| POST | `/app/unlock/complete` | bearer + sig | `{nonce_b64, counter, signature_b64}` | `{unlocked: bool}` | `auth_unlock` |
| GET | `/app/status` | none | — | `{connected, vault_unlocked, device_id}` | `app_status` |
| GET | `/app/review/pending` | bearer | — | `ReviewItem[]` | `app_review_pending` |
| GET | `/app/review/auto-enabled` | bearer | — | `ReviewItem[]` | `app_review_auto_enabled` |
| POST | `/app/review/approve` | bearer | `{name}` | `{ok}` | `app_review_approve` |
| POST | `/app/review/reject` | bearer | `{name}` | `{ok}` | `app_review_reject` |
| GET | `/app/actions/pending` | bearer | — | `PendingAction[]` | `app_actions_pending` |
| POST | `/app/actions/approve` | bearer | `{id}` | `{ok}` | `app_actions_approve` |
| POST | `/app/actions/reject` | bearer | `{id}` | `{ok}` | `app_actions_reject` |
| POST | `/app/tasks/suggestion/accept` | bearer | `{suggestion_id, due_at?, project_id?}` (client always sends `project_id: null`) | `{task: <json>}` | `task_suggestion_accept` |
| POST | `/app/tasks/suggestion/reject` | bearer | `{suggestion_id}` | `{ok}` | `task_suggestion_reject` |
| POST | `/app/ask` | bearer | `{text}` | `{text, path, tool_used?, escalated}` | `app_ask` |
| POST | `/app/ask/stream` | bearer | `{text}` | SSE text body (`data: ...` lines; `[DONE]` terminator) | `app_ask_stream` |
| POST | `/app/ask/voice` | bearer | `{speak}` | SSE text body (`data: ...` lines; `[DONE]` terminator) | `app_ask_voice` |
| POST | `/app/lock` | bearer | — | `{locked}` | `app_lock` |
| POST | `/app/logout` | bearer | — | `{ok}` | `app_logout`, `auth_logout` |
| GET | `/app/layout` | bearer | — | `LayoutDto` | `app_layout_get` |
| PUT | `/app/layout` | bearer | `LayoutDto` | `LayoutDto` | `app_layout_put` |

### Response shape details

- **ReviewItem**: `{name, description, status, action_class, safety, explanation}` (all strings).
- **PendingAction**: `{id, module, tool, summary, action_class, status, created_at, expires_at, result?}` — `created_at`/`expires_at` are strings (ISO); `result` is arbitrary JSON or null. (Note: no `args` field — a test asserts its absence.)
- **LayoutDto**: `{version: u64, updated_at: string, cards: CardPlacement[]}`; **CardPlacement**: `{id, domain, cluster, x, y, w, h}` (x/y/w/h are floats).
- **TaskSuggestionAcceptResponse**: `{task: <arbitrary json>}`.
- **AskResponse**: `{text, path, tool_used?: string, escalated: bool}`.
- **expires_at** in session/complete is a **float** Unix timestamp (deserialized as `f64`; a `u64` would break on fractional values).

## Local-only Tauri commands (no brain call)

- **`auth_recover`** — accepts passphrase, zeroizes and discards it; no HTTP (Mac-gated broker relay, ADR-005). Returns `()`.
- **Global shortcut** `Alt+Space` (registered in `lib.rs`, not an `invoke` command) — shows/focuses the `ask` window and emits the `ask:summon` webview event. Purely local UI summon.
- **Window event** `ask:summon` — emitted to the webview, no brain involvement.
- Token lifecycle side effects (`app_lock`, `app_logout`, `auth_connect`, `auth_logout`) mutate Rust-side `AppState` token in addition to (or instead of) their brain calls — the token clearing itself is local.

## Notes / observations

- The client never exposes the session token to JS (ADR-030) — all bearer auth happens in Rust.
- All endpoints are under the `/app/*` namespace (brain's app-facing gateway).
- Errors surfaced to the webview are typed/redacted: `GatewayError` → `{kind, status?}`; `AuthError` → `{kind}` with kinds like `biometricCancelled`, `hardwareUnavailable`, `keyNotFound`, `pairingRejected` (maps brain 400/401/403/404/410), `unauthenticated`, `vaultLocked`, `network`, `encoding`. No signature bytes, nonces, or tokens leak.
- 423 LOCKED (status) and `{"error":"vault_locked"}` (SSE) both signal a locked vault and should drive a re-unlock flow.
