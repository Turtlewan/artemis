---
spec: secret-capture-ui
status: ready
token_profile: balanced
autonomy_level: L2
coder_model: codex
coder_effort: high
cross_model_review: true
---

# Spec: 4b — secret-capture client UI (keys panel + capture, over the 4a routes)

**Identity:** Client half of secret-capture: Tauri commands (`app_secret_set/list/delete`, session
token stays in Rust) + TS wrappers + a Keys popup (list names / add / delete) summoned from a
provisional corner gear, with a programmatic `open()` the step-5 gate will deep-link into.
→ why: ADR-035 enabler #2 (secret-capture); consumes the 4a `/app/secrets` routes.

**STYLING NOTE (owner directive 2026-07-02):** the whole Artemis UI is being overhauled later, so
build FUNCTIONAL structure with BASELINE styling only — keep styling cleanly separable (a small CSS
module / inline tokens), do NOT invest in polishing the liquid-glass aesthetic. Reference mock:
`docs/design/keys-panel-mock.html`.

## Assumptions
- 4a shipped `/app/secrets` (POST set / GET names / DELETE) session-gated → the Rust gateway calls
  them with the stored session token (mirror the existing capability commands in
  `client/src-tauri/src/gateway.rs` + TS wrappers in `client/src/api/gateway.ts`) → impact: Caution
  (follow the EXACT existing command+session pattern; don't invent a new transport)
- The client is React + TS (Vite/Tauri); commands go webview → `invoke()` → Rust `#[tauri::command]`
  → brain HTTP with the session token held in Rust (out of the webview) → impact: Low
- A persistent corner control can be mounted in `App.tsx` alongside the map without disturbing the
  travel-zoom map → impact: Caution (mount as an overlay layer, not inside the map transform)

Simplicity check: one shared `<KeysPanel>` component with an `open`/`onClose` prop + a small store
for open-state, reused by the gear trigger AND (later) the step-5 gate — not two separate UIs.

## Prerequisites
- Specs complete first: secret-routes (4a, done)
- Environment: `npm install` (client); the client Verification Recipe (tsc/eslint/vitest + cargo/clippy)

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| client/src-tauri/src/gateway.rs | modify | add `app_secret_set(name,value)` / `app_secret_list() -> names` / `app_secret_delete(name)` `#[tauri::command]`s calling the brain `/app/secrets` with the session token |
| client/src-tauri/src/lib.rs | modify | register the 3 new secret commands in the `tauri::generate_handler![...]` invoke_handler list (registration only) |
| client/src/api/gateway.ts | modify | add `secretSet(name,value)` / `secretList(): Promise<string[]>` / `secretDelete(name)` wrappers over `invoke` |
| client/src/api/dto.ts | modify | add the secret-names response type if the file centralises DTOs (else inline) |
| client/src/secrets/KeysPanel.tsx | create | the popup: list names + delete, add-key form (masked value input + reveal), `open`/`onClose`; baseline styling |
| client/src/secrets/keysStore.ts | create | tiny open-state store + `openKeys()` (so a hotkey / the step-5 gate can summon it) |
| client/src/App.tsx | modify | mount `<KeysPanel>` overlay + a provisional corner gear button that calls `openKeys()` |
| client/src/secrets/KeysPanel.test.tsx | create | vitest: list renders names (not values), add calls `secretSet`, delete calls `secretDelete`, masked input default type=password |

## Tasks
- [ ] Task 1: Rust commands — files: client/src-tauri/src/gateway.rs, client/src-tauri/src/lib.rs — done when: three `#[tauri::command]`s (`app_secret_set`, `app_secret_list`, `app_secret_delete`) in gateway.rs call the brain `/app/secrets` endpoints with the session token (exactly like the existing `app_capability_*` commands), AND are added to the `tauri::generate_handler![...]` list in lib.rs (alongside `gateway::app_capability_*`); `cargo build` + `cargo clippy` clean. The secret VALUE flows webview→Rust→brain only; never returned to the webview.
- [ ] Task 2: TS wrappers + types — files: client/src/api/gateway.ts, client/src/api/dto.ts — done when: `secretSet(name,value): Promise<void>`, `secretList(): Promise<string[]>`, `secretDelete(name): Promise<void>` wrap `invoke`; `tsc` clean.
- [ ] Task 3: KeysPanel + store — files: client/src/secrets/KeysPanel.tsx, client/src/secrets/keysStore.ts — done when: `<KeysPanel open onClose>` lists names (from `secretList`, refreshed after mutations), shows a delete (calls `secretDelete`), and an add form with a `type="password"` value input + a reveal toggle that calls `secretSet` then refreshes; NEVER renders a secret value (list is names only). `keysStore` exposes `openKeys()`/`closeKeys()` + open-state. Baseline styling (separable). Accepts an optional `pendingKey?: string` prop to preselect a required key (for the step-5 gate deep-link) — wiring the gate itself is step 5.
- [ ] Task 4: mount + summon — files: client/src/App.tsx — done when: `<KeysPanel>` is mounted as an overlay (bound to keysStore open-state) and a provisional corner gear button calls `openKeys()`; the map is undisturbed; `tsc`/eslint clean.
- [ ] Task 5: tests — files: client/src/secrets/KeysPanel.test.tsx — done when: the client test command passes: list shows names not values, add invokes `secretSet` + refreshes, delete invokes `secretDelete`, the value input is `type="password"` by default.

## Wave plan
Wave 1: [Task 1, Task 2] | Wave 2: [Task 3] | Wave 3: [Task 4, Task 5]

## Permissions
### File Operations
| Action | Paths |
|--------|-------|
| Create | client/src/secrets/** |
| Modify | client/src-tauri/src/gateway.rs, client/src/api/gateway.ts, client/src/api/dto.ts, client/src/App.tsx |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| (client Verification Recipe — tsc / eslint / vitest / cargo build / clippy) | per the bound apex-tauri recipe |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | client/src/secrets/** client/src-tauri/src/gateway.rs client/src/api/gateway.ts client/src/api/dto.ts client/src/App.tsx |
| `git commit` | "feat: secret-capture client UI (keys panel + Tauri commands)" |

## Specialist Context
### Security
- The session token MUST stay in Rust (never passed into or returned to the webview) — mirror the
  existing capability commands. Secret VALUES flow webview→Rust→brain on set only; `secretList`
  returns names only; nothing renders a value. apex-security reviews the command layer.

### Performance
(none)

### Accessibility
- Baseline: the value input is a real `<input type="password">`; the reveal toggle is a button with
  an accessible label; the panel is dismissible via a close control. (Full a11y + visual polish is
  the owner's later overhaul.)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | client/src/secrets/KeysPanel.tsx, keysStore.ts | brief docstrings/comments |

## Acceptance Criteria
- [ ] Keys popup opens from the corner gear + `openKeys()` → verify: Task 4 mount; manual open
- [ ] List shows names only, never values → verify: Task 5 test
- [ ] Add persists via secretSet, delete via secretDelete, list refreshes → verify: Task 5 test
- [ ] Session token stays in Rust → verify: Task 1 mirrors the capability-command pattern (review)
- [ ] Client gate green → verify: the client Verification Recipe (tsc/eslint/vitest/cargo/clippy) passes

## Progress
_(Coding mode writes here — do not edit manually)_
