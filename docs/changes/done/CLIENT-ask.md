---
spec: client-ask
status: ready
token_profile: balanced
autonomy_level: L2
---

# Spec: CLIENT-ask — the floating "Ask Artemis" pop-up + streaming chat

**Identity:** Implements the branded, top-most **Ask-Artemis pop-up** (⌥Space global hotkey + top-bar button), summonable over any in-app view; streams a chat answer through CLIENT-core's `askStream` Rust `Channel`, renders the design-brief-locked structure (brand mark · input · mode-hint chip · results list with load-bearing engine tags · footer engine-status chips), and gates sending on the vault-unlocked state.
→ why: see docs/technical/adr/ADR-028-client-spatial-navigation.md §5 (chat = a distinct floating pop-up, NOT a card/tab) · docs/technical/architecture/design-brief.md (the locked pop-up shape) · docs/technical/architecture/app-flow.md (Ask lock rules).

<!-- Split rule: flagged atomic exception (precedent: the other CLIENT-* specs ship a cohesive surface as one unit). CLIENT-ask is ONE feature — the pop-up + its global-hotkey wiring + its stream consumption are mutually dependent; splitting the Rust hotkey from the TS pop-up leaves a non-functional half. Touches client/src/ask/ (TS) + 3 shared src-tauri/ files (the global-shortcut plugin registration) — the latter is the serialization edge with CLIENT-core/auth (see Prerequisites). -->

## Assumptions
- **CLIENT-core ships `gateway.askStream(text, onEvent)` over a Tauri `Channel<StreamEvent>`** with `StreamEvent = {Text(string) | VaultLocked | Done}` (ADR-030: the brain call + token live in Rust; the webview only consumes typed events). CLIENT-ask consumes it; it never calls the brain or holds the token. → impact: Stop (the streaming contract is CLIENT-core's; a field/variant drift breaks rendering).
- **The connection/lock store (CLIENT-core `state/connection.ts`) exposes the current `ConnectionState`.** Sending requires `unlocked`; in `connectedLocked` the pop-up raises the re-unlock prompt seam (owned by CLIENT-auth) instead of sending. → impact: Stop (the lock gate is the security model — app-flow: Ask touches memory/knowledge → requires Unlocked).
- **The engine tag derives from the `Done` event metadata.** CLIENT-core (amended) ships `StreamEvent::Done { path?, tool_used?, escalated }`; CLIENT-ask consumes it directly — `escalated` → `review`, cloud `path` → `codex`, else `local`. → impact: Low (the typed event provides it; no fallback path).
- **⌥Space must summon the pop-up even when the app is not focused** (Athena-style global summon, ADR-028 §5) → an OS-level global shortcut is required, which in Tauri 2 needs `tauri-plugin-global-shortcut` (a Rust plugin) — a webview `keydown` only fires when the webview is focused. → impact: Stop (drives the Rust touch + the serialization edge with CLIENT-core's `lib.rs`/`capabilities`).
- Tokens + the `.glass`/engine-tag colour roles come from CLIENT-theme; no hardcoded hex (design-brief forbidden pattern). → impact: Caution.

Simplicity check: considered a **webview-only `keydown` hotkey** (no Rust plugin, frontend-only, file-disjoint from core) — rejected as the primary because it only fires while the app/webview is focused, defeating the ⌥Space "summon from anywhere" intent (ADR-028 §5). Considered a **separate Tauri `WebviewWindow`** (a true Spotlight-style OS window) — rejected for v1: the stream/auth/ambient state all live in the main window, and a second window forks that state + the theme provider; an in-DOM top-most modal over the main window (raised to front by the global shortcut) achieves "over any view" with far less machinery. The separate-window variant is a clean future enhancement, non-breaking.

## Prerequisites
- Specs that must be complete first: **CLIENT-core** (the `askStream` Channel contract + the connection store + the `client/` scaffold) · **CLIENT-theme** (tokens, glass, engine-tag colour roles). Sequenced-with **CLIENT-auth** (the re-unlock prompt seam) and **CLIENT-world** (both modify `App.tsx` + the shared `src-tauri/` files). **NOT file-disjoint** from CLIENT-core/auth/world — it modifies `client/src-tauri/{lib.rs, Cargo.toml, capabilities/default.json}` and `client/src/App.tsx`; serialize after them (ADR-029 file-overlap edge).
- Environment setup required: `@tauri-apps/plugin-global-shortcut` (npm) + `tauri-plugin-global-shortcut` (crate). MSVC toolchain for any Rust compile (per apex-tauri / CLIENT-core).

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| client/src/ask/askStore.ts | create | chat state: `messages[]`, streaming buffer, `mode hint`, `engineStatus`; `send(text)` → consumes CLIENT-core `gateway.askStream` (Text→append, VaultLocked→raise re-unlock, Done→finalize + attach engine metadata); gated on `ConnectionState==="unlocked"` |
| client/src/ask/AskPopup.tsx | create | the floating dialog — `role="dialog" aria-modal="true"` with a visible `<h2>Ask Artemis</h2>` (`aria-labelledby`); brand mark (arc-reactor ring) · labelled input line (Space Grotesk + caret) + mode-hint chip · results list · footer engine-status chips; an `aria-live="polite"` region for the streamed answer (debounced — flush on sentence boundary / `Done`) + a separate `role="alert"`/`aria-live="assertive"` region for the vault-locked message; manual focus-trap (input focused on open, Tab wraps last→first / Shift+Tab first→last); Esc/click-away/✕ all close + restore focus to the pre-open element; open/close + caret via `transform`/`opacity` (WebKit-safe), reduced-motion → instant open/close + stop/native caret; **no `mix-blend-mode` on the `.glass`/backdrop-filter element** (WebKit #176830) |
| client/src/ask/ResultRow.tsx | create | one result row: rounded icon tile (`aria-hidden="true"` — decorative) · title + subtitle · right-aligned `<EngineTag>`; footer chips never obscure a focused row (footer outside the scroll container or `scroll-padding-bottom`) |
| client/src/ask/EngineTag.tsx | create | the load-bearing engine tag: `local` / `codex` / `review` (review in `--a` accent) rendered as a **DOM text node** (not colour/CSS-only); never omitted |
| client/src/ask/useAskHotkey.ts | create | `listen<null>("ask:summon", …)` (zero-payload contract compiler-enforced) → open; binds the top-bar button + Esc/click-away/✕ close (all restore focus); no token, no brain call |
| client/src/App.tsx | modify | mount `<AskPopup>` at the top level (above the map) + add the top-bar "Ask" button affordance (discoverability for the hotkey) — additive to CLIENT-world's shell mount |
| client/src-tauri/src/lib.rs | modify | add `.plugin(tauri_plugin_global_shortcut::init())` as a NEW plugin in the builder chain (do **NOT** add a second `.invoke_handler()` — it discards CLIENT-core's handler); register `Alt+Space` → raise/focus `main` + `emit("ask:summon", ())`; unregister on `RunEvent::ExitRequested` |
| client/src-tauri/Cargo.toml | modify | add `tauri-plugin-global-shortcut = "2"` |
| client/src-tauri/capabilities/default.json | modify | grant `global-shortcut:allow-register` / `allow-unregister` + `core:event:allow-listen` (for the webview to `listen("ask:summon")`) to the `main` window only |
| client/package.json | modify | add `@tauri-apps/plugin-global-shortcut` (^2) |
| client/src/ask/askStore.test.ts · client/src/ask/AskPopup.test.tsx | create | vitest + RTL: stream consumption + lock-gate; focus-trap + Esc + engine-tag presence |

## Tasks
- [ ] Task 1: Global-shortcut wiring (Rust + deps) — files: `client/src-tauri/Cargo.toml`, `client/package.json`, `client/src-tauri/src/lib.rs`, `client/src-tauri/capabilities/default.json` — add `tauri-plugin-global-shortcut` (crate + npm); in `lib.rs` add `.plugin(tauri_plugin_global_shortcut::init())` as a NEW plugin in the existing builder chain (do **NOT** add a second `.invoke_handler()` — it silently discards CLIENT-core's command handler); register the `Alt+Space` global shortcut; on trigger, `get_webview_window("main")` → `.unminimize()`/`.set_focus()` then `emit("ask:summon", ())`; **unregister the shortcut on `RunEvent::ExitRequested`** (the granted `allow-unregister` must have a code path). Grant `global-shortcut:allow-register`/`allow-unregister` + `core:event:allow-listen` in `capabilities/default.json` scoped to `"windows":["main"]` (NOT `"*"`). Verify each new dep against canonical crates.io/npm (no typosquat); commit lockfiles. — done when: `cd client && npx tsc --noEmit` exit 0; `cargo fmt --check` exit 0; `capabilities/default.json` names `main`, has no `"*"`, grants only register/unregister + `core:event:allow-listen`; `app.windows[main].transparent` is false/absent (in-content glass); `cargo audit` clean; (MSVC-gated) `cargo check` converges, ALL pre-existing CLIENT-core commands still resolve, pressing ⌥Space unfocused raises the app + the webview receives `ask:summon`, and a second launch re-registers `Alt+Space` without an OS conflict — record gated status.
- [ ] Task 2: Ask state store — files: `client/src/ask/askStore.ts` — a typed store: `messages: AskMessage[]` (`{role, text, engine?, path?, tool?}`), a live `streaming` buffer, `modeHint` (TASK/DIGEST/WIND-DOWN…), `engineStatus`; `send(text)`: if `connection.state !== "unlocked"` → call the CLIENT-auth re-unlock seam and DO NOT send; else instant-ack (append the user message + an empty assistant message), then `gateway.askStream(text, onEvent)` — `Text`→append to the streaming buffer (+ the `aria-live="polite"` region, debounced to sentence boundary / `Done`), `VaultLocked`→stop + raise re-unlock + mark the message failed-locked + push "Vault locked — re-authentication required" to the `assertive` region, `Done`→finalize the assistant message + map `StreamEvent::Done {path?, tool_used?, escalated}` (`escalated`→`review`, cloud `path`→`codex`, else `local`) to its `engine` tag. No `fetch`, no token. — done when: `tsc --noEmit` exit 0; unit test: a Text/Text/Done sequence builds one assistant message with the right engine tag from the Done payload; a VaultLocked event marks failed-locked + invokes the re-unlock seam + sets the assertive region; `send` while `connectedLocked` never calls `askStream`.
- [ ] Task 3: The pop-up UI — files: `client/src/ask/AskPopup.tsx`, `client/src/ask/ResultRow.tsx`, `client/src/ask/EngineTag.tsx` — render the design-brief-locked structure over a `.glass` panel: brand mark · a **labelled** input line (`aria-label="Ask Artemis"`, Space Grotesk, caret) + mode-hint chip · results list of `<ResultRow>` (decorative icon tile `aria-hidden="true"` · title+subtitle · right-aligned `<EngineTag>`) · footer engine-status chips (the `●` bullet wrapped in `<span aria-hidden="true">`). `AskPopup` is `role="dialog" aria-modal="true"` named by a visible `<h2 id>Ask Artemis</h2>` via `aria-labelledby`; a **manual focus trap** (focus the input on open; a keydown handler wraps Tab last→first and Shift+Tab first→last); Esc/click-away/✕ all close and restore focus to the pre-open element. Two SR regions: `aria-live="polite"` for the streamed answer (debounced) + `role="alert"` (`aria-live="assertive"`) for the vault-locked message. `<EngineTag>` renders `local`/`codex`/`review` (review in `--a`) as a DOM text node; never omit it. The footer renders outside the results scroll container so it never obscures a focused row (2.4.11). Open/close + caret animate `transform`/`opacity` only; `@media (prefers-reduced-motion)` → instant open/close + stopped/native caret. **No `mix-blend-mode` on the `.glass` element** (WebKit #176830). No hardcoded hex (tokens only); no light theme. — done when: `tsc --noEmit` exit 0; RTL: `getByRole('dialog',{name:/ask artemis/i})` resolves; `getByRole('textbox',{name:/ask/i})` resolves; Tab wraps last→first and Shift+Tab first→last; Esc closes + restores focus; `getByText(/local|codex|review/)` on each row; `grep -E "#[0-9a-fA-F]{3,6}" client/src/ask/` finds no literal hex.
- [ ] Task 4: Hotkey listener + shell mount — files: `client/src/ask/useAskHotkey.ts`, `client/src/App.tsx` — `useAskHotkey`: `listen<null>("ask:summon", …)` (zero-payload contract compiler-enforced) → open the pop-up; bind the top-bar "Ask" button; Esc/click-away/✕ close — **every** close path restores focus to the pre-open element. `App.tsx`: mount `<AskPopup>` at the top level above the map (additive to CLIENT-world's shell) + render the top-bar Ask button. — done when: `tsc --noEmit` exit 0; RTL: the Ask button opens the pop-up and focus moves into the input; a simulated `ask:summon` event opens it; **click-away closes it AND restores focus to the previously-focused element** (explicit click-away test); Esc likewise.
- [ ] Task 5: Tests — files: `client/src/ask/askStore.test.ts`, `client/src/ask/AskPopup.test.tsx` — vitest + RTL covering Tasks 2–4 (mock `@tauri-apps/api/core` `invoke` + the `Channel`/`listen` events; mock the connection store). — done when: `cd client && npx vitest run` passes; (MSVC-gated) the integrated `cargo` gates still pass — record status.

## Wave plan
Wave 1: [Task 1, Task 2] | Wave 2: [Task 3] | Wave 3: [Task 4] | Wave 4: [Task 5]

## Permissions

The following actions will run autonomously during build. Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | client/src/ask/{askStore.ts, AskPopup.tsx, ResultRow.tsx, EngineTag.tsx, useAskHotkey.ts, askStore.test.ts, AskPopup.test.tsx} |
| Modify | client/src/App.tsx, client/src-tauri/src/lib.rs, client/src-tauri/Cargo.toml, client/src-tauri/capabilities/default.json, client/package.json |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `cd client && npm install` | add the global-shortcut plugin |
| `cd client && npx tsc --noEmit` | frontend typecheck gate |
| `cd client && npx vitest run` | frontend unit/RTL tests |
| `cd client && npx eslint . --max-warnings 0` | lint gate |
| `cd client/src-tauri && cargo fmt --check` | Rust format gate |
| `cd client/src-tauri && cargo check && cargo clippy -- -D warnings` | Rust compile + lint (MSVC-gated) |
| `cargo audit` (in src-tauri) | supply-chain check for the new crate |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | client/src/ask/**, client/src/App.tsx, client/src-tauri/src/lib.rs, client/src-tauri/Cargo.toml, client/src-tauri/Cargo.lock, client/src-tauri/capabilities/default.json, client/package.json, client/package-lock.json |
| `git commit` | "feat: CLIENT-ask floating Ask-Artemis pop-up + streaming chat" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| (none new) | reuses CLIENT-core's gateway + token-in-Rust transport |

### Network
| Action | Purpose |
|--------|---------|
| `npm install` / `cargo` fetch | the global-shortcut plugin (verify name; not a typosquat) |
| (runtime) | none direct — streaming goes through CLIENT-core's Rust `Channel`; the webview makes no network calls |

## Specialist Context
### Security
No token in the webview (streaming consumes CLIENT-core's Rust `Channel`; ADR-030). The global-shortcut capability is scoped to `"windows":["main"]` (never `"*"`) and grants only register/unregister + the one `ask:summon` event. Sending is gated on `unlocked` — a locked vault raises the re-unlock prompt and never reaches the brain (fail-closed, app-flow). The new crate is name-verified + audited; lockfiles committed. [FLAG apex-security at wave review: confirm the `ask:summon` event carries no payload + the capability is minimal.]

### Performance
Streaming uses CLIENT-core's `Channel` (ordered, efficient). Open/close + caret animate `transform`/`opacity` only (WebKit-safe). The results list is short (a session's turns); no virtualization needed at this scale.

### Accessibility
The pop-up is a focus-trapped modal dialog (`role="dialog" aria-modal="true"`, named by a visible `<h2>Ask Artemis</h2>` via `aria-labelledby`); the input is labelled; a manual focus trap wraps Tab/Shift+Tab; focus enters the input on open and is restored to the pre-open element on **every** close path (Esc/click-away/✕). The streamed answer is announced via an `aria-live="polite"` region (debounced to sentence boundary), the vault-locked transition via a separate `role="alert"`/`assertive` region. The top-bar Ask button is the discoverable affordance for the ⌥Space hotkey (not the sole path). Engine tags carry text (`local`/`codex`/`review`), never colour-only. Decorative bits (`●` bullet, icon tile) are `aria-hidden`. Reduced-motion → instant open/close + stopped/native caret. [Reviewed: apex-accessibility (3 BLOCKs + 5 FLAGs) + apex-tauri (4 FLAGs) — all applied 2026-06-24.]

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | client/src/ask/*.ts(x), client/src-tauri/src/lib.rs | TSDoc/rustdoc all exports; document the `ask:summon` event contract + the askStream consumption |
| API | docs/product/api/client-app-api.md | note the Ask pop-up consumes CLIENT-core `askStream` (no new brain route) |

## Acceptance Criteria
- [ ] Run `cd client && npx tsc --noEmit` → verify: exit 0 (store, pop-up, hotkey, tags all typed).
- [ ] Run `cd client && npx vitest run` → verify: stream Text/Done builds one assistant message with the correct engine tag (from the `Done` payload); VaultLocked raises re-unlock + sets the assertive region + does not finalize; `send` while `connectedLocked` never calls `askStream`; `getByRole('dialog',{name:/ask artemis/i})` + `getByRole('textbox',{name:/ask/i})` resolve; Tab/Shift+Tab wrap within the trap; Esc AND click-away both close + restore focus to the pre-open element; the `aria-live` region updates with the streamed answer; `getByText(/local|codex|review/)` on each row.
- [ ] Run `cd client && npx eslint . --max-warnings 0` → verify: exit 0.
- [ ] Run `grep -E "#[0-9a-fA-F]{3,6}" client/src/ask/` → verify: no literal hex (tokens only).
- [ ] Run `cd client/src-tauri && cargo fmt --check && cargo audit` → verify: both exit 0.
- [ ] Inspect `client/src-tauri/capabilities/default.json` + `tauri.conf.json` → verify: the grant names `"main"`, has no `"*"`, grants only register/unregister + `core:event:allow-listen`; `app.windows[main].transparent` is false/absent.
- [ ] (MSVC-gated) Run `cd client/src-tauri && cargo check && cargo clippy -- -D warnings` → verify: converge; ALL pre-existing CLIENT-core commands still resolve; press ⌥Space unfocused → app raises + pop-up opens; second launch re-registers `Alt+Space` without conflict; record gated status if MSVC absent.

## Progress
_(Coding mode writes here — do not edit manually)_
