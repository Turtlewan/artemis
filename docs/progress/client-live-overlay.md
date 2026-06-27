# client-live-overlay — PARKED at Task 2 (UI-architecture fork)

**Parked 2026-06-27** during the Tauri client runway build (Wave 2). Tasks 1, 3, 4, 5 are
unblocked-but-deferred behind the Task-2 decision; Task 5 is an owner-manual demo regardless.

## The fork (Task 2 — always-on-top Ask overlay)
The spec says: configure the **Ask window** in `client/src-tauri/tauri.conf.json` with
`alwaysOnTop/skipTaskbar/decorations:false` so the global-shortcut summons it over a foreground game,
framing it as "just window config; the summon mechanism is already built."

**Reality (pre-flight against the live client):** there is **no separate Ask window**. `tauri.conf.json`
defines only the `"main"` window. The ⌥Space global-shortcut handler in `client/src-tauri/src/lib.rs`
summons the **main** window (`get_webview_window("main")` → `unminimize` + `set_focus` + emit
`ask:summon`); CLIENT-ask renders the Ask UI inside the main command-map window on that event.

So Task 2 cannot be done as written, and the two valid implementations diverge on the **locked client
UI direction** (ADR-028 / memory `client-ui-travel-zoom-direction`, which calls for a "distinct floating
Ask-Artemis pop-up (⌥Space)"):
- **Option A — separate floating Ask window** (design-aligned with "distinct floating pop-up"): add a
  small dedicated always-on-top / undecorated / skip-taskbar Ask window (new window + webview entry; the
  Ask UI moves/duplicates into it). More work; matches the locked UX.
- **Option B — main window always-on-top during Ask** (minimal config): but the main window is the
  full pannable command-map — making it always-on-top / undecorated / skip-taskbar is wrong for the
  primary surface and contradicts the map-as-main concept.

This is a UI-architecture decision touching the LOCKED design → owner call, not a coding guess.

## Independent-but-deferred tasks
- **Task 1** (brain_base_url default at startup → fixes the permanent "connection-gating"; add a
  `set_base_url` setter to `state.rs` — it currently has only a getter — and default to
  `http://127.0.0.1:8030` in `lib.rs`). Orthogonal to the window choice; clean to build once greenlit.
- **Task 4** (contract reconciliation — diff client `gateway.rs` structs vs brain `/app/*` pydantic;
  CLIENT-auth wiremock tests already pin pair/session/unlock shapes, so likely confirms ask/status).
- **Task 3 / Task 5** need the window (Task 2) + a live brain + CLIENT-auth signer; Task 5 is a manual
  game-overlay acceptance (owner-run, like CLIENT-auth Task 7 / m2-win-b Hello).

## Confirmed facts (so the resume build is fast)
- `/app/ask` is `require_session` (not `require_unlocked`) — `api_app.py:822-823` → the demo path needs
  connect (session) only, NOT a vault unlock. Good.
- Ask summon = ⌥Space (`Modifiers::ALT + Code::Space`) on the `"main"` window today.
- No drift blockers found in the transport layer; `gateway.rs` ask/status structs:
  `AskRequest{text}` / `AskResponse{text,path,tool_used,escalated}` / `StatusResponse{connected,vault_unlocked,device_id}`.

**Resume:** owner picks A or B → build Tasks 1–4 in one Codex pass (apex-tauri recipe verify) → owner
runs the Task-5 game-overlay demo.
