---
status: ready
weight: light
cross_model_review: false
coder_effort: medium
---

# client-live-overlay — live client↔brain connection + game-overlay Ask demo (⑤b)

## Intent
Connect the live Tauri client to the running brain and prove the headline demo: **press a global
hotkey while a game is in front → an always-on-top Ask pop-up → a real answer from the brain.**
The transport (`gateway.rs` reqwest), the global-shortcut summon (`lib.rs`), and the brain's
`/app/*` endpoints all already exist; the gaps are (a) `brain_base_url` is never set (the permanent
"connection-gating"), (b) the Ask window isn't always-on-top, and (c) the live pair→connect→ask
path has never run against a real brain. Client-side half of ⑤; pairs with `win-brain-runtime` (⑤a).

## Prerequisites
- **`win-brain-runtime` (⑤a)** — a brain to connect to (`uv run artemis-brain` on :8030).
- **`CLIENT-auth` (Phase A)** — the real device-key signer for the live pair/connect handshake.
  Until it lands, the automated tests use the existing fake signer/transport; the **live demo**
  (Task 5) needs CLIENT-auth built.

## Key decisions
- **`brain_base_url` defaults to `http://127.0.0.1:{brain_port}`** at app startup (dev) — the client
  auto-targets the local brain with no manual config; a `configure`-style command can override
  later. This turns the connection-gate from "blocked forever" into "connect to localhost."
- **The Ask window is always-on-top + skip-taskbar + undecorated**, so the existing global-shortcut
  summons it *over* a foreground game. The summon mechanism is already built — this is window config.
- **The game-overlay run is a MANUAL gated acceptance** (like m2-win-b's Hello gesture / CLIENT-auth
  Task 7) — recorded in the build handoff, not a CI gate. Automated coverage uses a fake/live brain.

## Gotchas / edge cases
- **Exclusive-fullscreen games may not show the overlay** (a Windows limitation, not ours) — the
  demo targets **borderless / windowed-fullscreen**; record the exclusive-fullscreen behaviour as a
  finding rather than treating it as a failure.
- **Summoning steals focus** — a game that pauses on focus-loss will pause while the pop-up is up.
  Acceptable for the demo; note it.
- **Confirm whether `/app/ask` requires a full vault unlock or only a session** (connect). A basic
  general-knowledge ask should need only a session token; if `/app/ask` is `require_unlocked`, the
  demo path must include unlock. Resolve against `api_app.py` at build, don't assume.
- **Contract drift:** the client reqwest structs (field names like `public_key_b64`, `nonce_b64`,
  `session_token`; paths `/app/pair`, `/app/session/*`, `/app/ask`) must match the brain pydantic
  models exactly — a mismatch fails silently as a deserialize/404. Reconcile field-by-field.
- Keep the webview network-free (ADR-030): the base_url default is set in **Rust** state, not the
  webview; the Ask still calls the brain only via the Rust `ask` command.

## Tasks
1. Default `brain_base_url` at startup — `client/src-tauri/src/lib.rs` (+ `state.rs` setter if none
   exists): initialise `AppState.brain_base_url` to `http://127.0.0.1:8030` (brain_port; overridable
   via a `TAURI`/env or a future configure command). — done when: a fresh client's `status` call
   reaches the live brain's `GET /app/status` (a real response, not `GatewayError::Network`).
2. Always-on-top Ask window — `client/src-tauri/tauri.conf.json` (Ask window: `alwaysOnTop: true`,
   `skipTaskbar: true`, `decorations: false`, `focus: true` on show) + confirm the global-shortcut
   handler shows + focuses it. — done when: pressing the Ask hotkey raises the pop-up above other
   windows (incl. a borderless foreground window).
3. Live ask round-trip — confirm the Ask flow `invoke("ask"|…)` → Rust `ask` command →
   `gateway` `POST /app/ask` returns the brain's `AskResponse`; reconcile any path/field drift. —
   done when: with the brain running + a session, a question typed in the Ask pop-up returns the
   brain's real answer (integration test against a live/test brain; manual against the live brain).
4. Contract reconciliation — diff the client `gateway.rs` request/response structs against the
   brain `/app/*` pydantic models (pair / session begin+complete / unlock / ask / status); fix any
   field/path mismatch. — done when: a transport round-trip test (client ↔ a test brain) passes for
   pair→connect→ask.
5. **(GATED — manual, real hardware/interaction)** Game-overlay demo — brain running (⑤a) +
   CLIENT-auth signer (Phase A) + paired/connected; launch a **borderless** game, press the Ask
   hotkey, ask a question, get the live brain answer over the game. — done when: recorded in the
   build handoff with pass/fail + the exclusive-fullscreen behaviour noted.

## Files to touch
- `client/src-tauri/src/lib.rs` — modify (set `brain_base_url` default at startup)
- `client/src-tauri/src/state.rs` — modify (base_url setter, if not already present)
- `client/src-tauri/tauri.conf.json` — modify (Ask window always-on-top / skip-taskbar / undecorated)
- `client/src-tauri/src/gateway.rs` — modify only if Task 4 finds contract drift
- `client/src/ask/*` (askStore / ResultRow) — modify only if Task 3 finds the ask invoke isn't wired to the live command
- `client/src-tauri/src/gateway.rs` (tests) / `client/src/ask/*.test.ts` — round-trip + ask integration coverage
