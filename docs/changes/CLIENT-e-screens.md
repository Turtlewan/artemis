<!-- amended 2026-06-11 per contracts.md (Seam 3) + client.md BLOCKs B7 (token provider), FLAG F12 (alert vs confirmationDialog) -->
---
spec: client-e-screens
status: ready
token_profile: balanced
autonomy_level: L2
---

# Spec: CLIENT-e — Swift screens (Review / Chat / Status) + their view-models

**Identity:** Implements the three concrete screens that fill the CLIENT-d shell: Review (list pending + auto-enabled recipes with plain-language explanations, approve/reject), Chat (streaming SSE answers), Status (connection/lock state, device info, Lock-now + Sign-out), each with an `@Observable` view-model over the ArtemisKit `ApiClient`, polished to iPhone + iPad parity.
→ why: see docs/technical/architecture/app-flow.md (the three screens + per-screen lock behaviour) · CLIENT-b (the `/app/*` endpoints) · M7-b (`ReviewSurface` semantics the Review screen renders).

<!-- Split rule: ONE logical phase (the three sibling screens + their view-models), 3 screen files + 1 protocol/conformance file + 1 shell modify + 1 test. Cohesive (they share the BrainApi seam + the lock-handling pattern) and all slot into the same shell destination switch. Consumes CLIENT-c (ApiClient/DTOs/ApiError), CLIENT-d (AppModel, RootShell destination switch, lock chrome). -->

## Assumptions
- CLIENT-d complete: the `AppModel` (with `requireUnlock()`, the current token via the Authenticator, `state`), `RootShell` with a `@ViewBuilder destinationView(_:)` switch returning placeholders, and the re-unlock sheet/lock banner. → impact: Stop (CLIENT-e replaces the placeholders + reuses the lock chrome).
- CLIENT-c `ApiClient` exposes `reviewPending/reviewAutoEnabled/approve/reject/ask/askStream/status/lock/logout` returning the DTOs + throwing `ApiError` (`.unauthenticated`/`.vaultLocked`). → impact: Stop (the view-models call these exactly).
- Review + Chat require the vault **unlocked** → on `ApiError.vaultLocked` the view-model calls back to `AppModel.requireUnlock()` (presents the re-unlock sheet) and retries after unlock; Status works session-only. → impact: Stop (matches ADR-010 §6 + app-flow lock table).
- The view-models depend on an **app-local `BrainApi` protocol** (the methods the screens use), with `ApiClient` conforming via an extension — consumer-defined dependency inversion so the screens unit-test against a fake without a live brain (same pattern as CLIENT-d's `Authenticating`). → impact: Low (idiomatic; keeps ArtemisKit unchanged).
- **Universal, equal polish**: each screen adapts to compact + regular width (Review/Status use `List`/`Form` that become multi-column-friendly on iPad; Chat uses a readable max-width column on regular); keyboard shortcuts where natural. → impact: Caution (every screen is laid out for both idioms).

Simplicity check: considered a shared generic "list screen" — rejected; Review and Status differ enough (actions vs read-only) that a shared abstraction would be forced. Considered polling Status — rejected; a manual refresh + on-appear load is enough (no live push in v1). Considered rendering the recipe explanation with client-side formatting — rejected; M7-b already ships a deterministic plain-language `explanation`; the screen renders it verbatim.

## Prerequisites
- Specs that must be complete first: CLIENT-c, CLIENT-d. (CLIENT-b provides the live endpoints; full screen behaviour against a real brain is gated with CLIENT-d's Task 6 integration.)
- Environment setup required: none beyond CLIENT-c/d. Off-device: view-models unit-test against a fake `BrainApi`; the rendered UI is gated on simulator/device.

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| /Users/artemis-build/artemis/swift/ArtemisApp/Sources/Screens/BrainApi.swift | create | app-local `BrainApi` protocol + `extension ApiClient: BrainApi`; a small `tokenedApi` helper binding the current token |
| /Users/artemis-build/artemis/swift/ArtemisApp/Sources/Screens/ReviewScreen.swift | create | `ReviewModel` (@Observable) + `ReviewScreen` view (pending + auto-enabled, approve/reject) |
| /Users/artemis-build/artemis/swift/ArtemisApp/Sources/Screens/ChatScreen.swift | create | `ChatModel` (@Observable) + `ChatScreen` view (streaming SSE answers) |
| /Users/artemis-build/artemis/swift/ArtemisApp/Sources/Screens/StatusScreen.swift | create | `StatusModel` (@Observable) + `StatusScreen` view (state, device, Lock now, Sign out) |
| /Users/artemis-build/artemis/swift/ArtemisApp/Sources/RootShell.swift | modify | replace the three placeholder destinations with the real screens |
| /Users/artemis-build/artemis/swift/ArtemisApp/Tests/ArtemisAppTests/ScreenModelsTests.swift | create | the three view-models against a fake `BrainApi` |

## Tasks
- [ ] Task 1: BrainApi seam — files: `/Users/artemis-build/artemis/swift/ArtemisApp/Sources/Screens/BrainApi.swift` — create the `Sources/Screens/` subdir if absent (CLIENT-d's `project.yml` globs the `Sources` source dir recursively, so the new subdir is picked up automatically — no `project.yml` change needed). `protocol BrainApi: Sendable` declaring the methods the screens use (`reviewPending(token:)`, `reviewAutoEnabled(token:)`, `approve(name:token:)`, `reject(name:token:)`, `ask(_:token:)`, `askStream(_:token:)`, `status(token:)`, `lock(token:)`, `logout(token:)`) with the CLIENT-c DTO signatures. `extension ApiClient: BrainApi {}` (retroactive conformance in the app module). Document: consumer-defined protocol for testability; ArtemisKit stays unchanged. — done when: the target compiles; `ApiClient` satisfies `BrainApi`.

- [ ] Task 2: Review screen — files: `/Users/artemis-build/artemis/swift/ArtemisApp/Sources/Screens/ReviewScreen.swift` —
  - `@MainActor @Observable final class ReviewModel` constructed with `(api: BrainApi, token: @Sendable () -> String?, onLocked: @MainActor () -> Void)`. State: `pending: [ReviewItem]`, `autoEnabled: [ReviewItem]`, `loading: Bool`, `error: String?`. `func load() async` (fetch both lists; on `.vaultLocked` → `onLocked()`); `func approve(_ name: String) async` / `func reject(_ name: String) async` (call the API, optimistic-remove the row from `pending`, reconcile on response/restore on error). Never render a raw error token.
  - `struct ReviewScreen: View`: a `List` with a **Pending** section (each row: recipe name + the M7-b `explanation` verbatim + a safety chip + **Approve**/**Reject** buttons) and an **Auto-enabled** section (read-only, explained). Empty state `ContentUnavailableView("Nothing waiting for your review", systemImage: "checkmark.seal")` (the system image is decorative — confirm it produces no VoiceOver announcement). `.task { await model.load() }` + `.refreshable` **plus a toolbar "Refresh" button** (`.accessibilityLabel("Refresh review list")`) as a non-gesture alternative (WCAG 2.5.7). iPad: the list is the sidebar-detail content; rows use the available width. **A11y:** the safety chip is its own element with `.accessibilityLabel("Safety: <level>")` (text, not colour alone — WCAG 1.4.1); **Approve/Reject carry the recipe name** (`.accessibilityLabel("Approve <name>")`/`"Reject <name>"`) so VoiceOver disambiguates rows; the explanation is each row's `.accessibilityValue`; ≥44pt targets. — done when: the target compiles; the model + view build; behaviour verified in Task 6.

- [ ] Task 3: Chat screen — files: `/Users/artemis-build/artemis/swift/ArtemisApp/Sources/Screens/ChatScreen.swift` —
  - `struct ChatMessage: Identifiable, Sendable { id, role: enum {user, assistant}, text, footer: String? }`.
  - `@MainActor @Observable final class ChatModel` constructed with `(api: BrainApi, token:, onLocked:)`. State: `messages: [ChatMessage]`, `input: String`, `sending: Bool`. `func send() async`: append the user message + an empty assistant message; consume `api.askStream(AskRequest(text), token)` appending each chunk to the assistant message's `text` as it streams; on `.vaultLocked` (or a terminal `{"error":"vault_locked"}` SSE frame from CLIENT-b's mid-stream lock) → `onLocked()` then retry after unlock, and **do NOT clear `input`** (preserve the composed text — WCAG 3.3.7); clear `input` only on a successful send. Set a dim footer (path/tool/escalated) when the stream completes (omit in v1 if it needs a second call — document). Degrade-don't-crash on stream error (inline error bubble). <!-- LINT-DEFER 2026-06-11: WARN CLIENT-e:48 — the v1 footer keep-vs-omit branch is a product/SSE-protocol decision (does the stream carry a trailing metadata frame?). Resolving it requires confirming the CLIENT-b SSE contract / a product call; not a mechanical lint fix. -->
  - `struct ChatScreen: View`: a scrolling transcript (user right / assistant left bubbles) auto-scrolling to the newest; a bottom input bar (`TextField` + Send, ⌘↩ to send on iPad). On regular width, constrain the transcript to a readable max width. **A11y (BLOCK fix — SwiftUI live region):** the streaming assistant bubble carries `.accessibilityAddTraits(.updatesFrequently)` (mutating `.accessibilityLabel` alone does NOT announce — WCAG 4.1.3); on stream completion post `UIAccessibility.post(.announcement, "Response complete")`. Each turn is `.accessibilityElement(children: .combine)` so VoiceOver reads "You: …" / "Artemis: …" as one element. The `TextField` has `.accessibilityLabel("Message")` (not just a placeholder); Send has `.accessibilityLabel("Send message")` and is `.disabled(input.isEmpty)`. **Auto-scroll honours `@Environment(\.accessibilityReduceMotion)`** (no animation when reduced); the typing indicator is non-animated under Reduce Motion. — done when: the target compiles; the model + view build; streaming verified in Task 6.

- [ ] Task 4: Status screen — files: `/Users/artemis-build/artemis/swift/ArtemisApp/Sources/Screens/StatusScreen.swift` —
  - `@MainActor @Observable final class StatusModel` constructed with `(api: BrainApi, token:, appModel: AppModel)`. State: `status: StatusResponse?`, `loading`, `error`. `func refresh() async` (`api.status(token:)`); `func lockNow() async` (`await appModel.lock()` — single lock path via AppModel, B6/U4 fix; do NOT call `api.lock` directly and then write `appModel.state` manually); `func signOut() async` (`await appModel.logout()`).
  - `struct StatusScreen: View`: a `Form`/`List` showing **Connection** (connected ✓), **Vault** (Unlocked / Locked — text + icon, not colour alone), **This device** (the `deviceId`), and actions **Lock now** + **Sign out**. `.task { await model.refresh() }`. Works while `connectedLocked` (session-only). **A11y:** the Vault row carries `.accessibilityAddTraits(.updatesFrequently)` so a lock-state change is announced while the screen is visible (WCAG 4.1.3), with any idle-lock countdown exposed as the row's `.accessibilityValue` (announce only at meaningful thresholds, not every tick); Sign out uses **`.alert`** (not `.confirmationDialog`) so VoiceOver focus moves to it automatically — title "Sign out of Artemis?", a destructive "Sign out" + "Cancel". Fully labelled; Dynamic Type throughout; ≥44pt targets. — done when: the target compiles; the model + view build.

- [ ] Task 5: Wire the screens into the shell — files: `/Users/artemis-build/artemis/swift/ArtemisApp/Sources/RootShell.swift` (modify) — replace the three `ContentUnavailableView` placeholders in `destinationView(_:)` with `ReviewScreen`, `ChatScreen`, `StatusScreen`. Construct each view-model from **`model.api`** (the `ApiClient` exposed as a `let` on `AppModel`, per CLIENT-d Task 2 B7 fix) and the token provider **`{ model.currentToken }`** (the `@MainActor` cached `String?` on `AppModel`, synchronously readable — no actor-isolation violation) plus `onLocked: { model.requireUnlock() }`. <!-- LINT-DEFER 2026-06-11: WARN CLIENT-e:55 — whether the token-provider closure type is @Sendable vs @MainActor () -> String? is a Swift 6 strict-concurrency design decision spanning CLIENT-e Task 2's view-model constructors; changing it would ripple the protocol signature and needs a deliberate concurrency call, not a one-line lint edit. --> Status additionally receives `appModel: model`. Keep the adaptive container + lock chrome unchanged. — done when: the target compiles; selecting each destination renders the real screen (Task 6).

- [ ] Task 6 (GATED — on simulator/device): the three screens against a live brain — files: (uses Tasks 2–5) — on a Mac, against a running brain (CLIENT-b) with at least one pending recipe staged: Review lists the pending recipe with its explanation → Approve flips it (re-fetch shows it gone); Chat sends a prompt and streams an answer; locking the vault then opening Review/Chat raises the re-unlock sheet, and after unlock the data loads; Status shows connected + the lock state and Lock-now/Sign-out work. Both iPhone + iPad idioms. **Manual VoiceOver pass (mandatory, apex-accessibility):** navigate Review (approve/reject announce the recipe name; safety chip read as text), Chat (send a prompt → the streamed response is announced via the live region + "Response complete"; each turn read as one element), and Status (lock-state change announced; Sign-out alert takes focus); record any gaps in the handoff. — done when: all three screens behave per app-flow against a live brain on both idioms AND the VoiceOver pass is clean — recorded in handoff.

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | /Users/artemis-build/artemis/swift/ArtemisApp/Sources/Screens/BrainApi.swift, /Users/artemis-build/artemis/swift/ArtemisApp/Sources/Screens/ReviewScreen.swift, /Users/artemis-build/artemis/swift/ArtemisApp/Sources/Screens/ChatScreen.swift, /Users/artemis-build/artemis/swift/ArtemisApp/Sources/Screens/StatusScreen.swift, /Users/artemis-build/artemis/swift/ArtemisApp/Tests/ArtemisAppTests/ScreenModelsTests.swift |
| Modify | /Users/artemis-build/artemis/swift/ArtemisApp/Sources/RootShell.swift |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `xcodegen generate --spec swift/ArtemisApp/project.yml` | Regenerate after adding sources |
| `xcodebuild test -project swift/ArtemisApp/Artemis.xcodeproj -scheme Artemis -destination 'platform=iOS Simulator,name=iPhone 16'` (GATED, Mac) | Build + view-model test gate |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | swift/ArtemisApp/Sources/Screens/**, swift/ArtemisApp/Sources/RootShell.swift, swift/ArtemisApp/Tests/ArtemisAppTests/ScreenModelsTests.swift |
| `git commit` | "feat: CLIENT-e Review/Chat/Status screens + view-models" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| (none) | Brain base URL comes from Keychain via AppModel.api — no env var (Decision D6) |

### Network
| Action | Purpose |
|--------|---------|
| (none at build/test) | view-models test against a fake `BrainApi`; live traffic is gated |

## Specialist Context
### Security
The screens render only what the brain returns; the Review `explanation` is M7-b's deterministic text (no client LLM). No token/nonce is ever rendered or logged; errors surface as generic user strings. Approve/Reject hit the owner-gated commit path (CLIENT-b → M7-b) — the screen is the only owner-approval surface (IG1=B). [FLAG apex-security + apex-auth: confirm approve/reject require the unlocked session, optimistic UI reconciles correctly on failure, and no sensitive payload is logged.]

### Performance
SSE streaming renders incrementally (TTFT masked). Review/Status are small rule-based reads. Optimistic row updates keep approve/reject responsive.

### Accessibility
apex-accessibility (auto-fires at the gate — first-UI). Per-screen: Review rows expose the explanation as the accessibility value + labelled Approve/Reject; the safety chip carries text not colour alone; Chat bubbles are role-labelled with polite streaming announcements; Status uses text+icon for lock state (never colour alone); all hit 44pt targets, respect Dynamic Type, and honour Reduce Motion (typing indicator, auto-scroll). Sign out uses **`.alert`** (not `.confirmationDialog`) so VoiceOver focus moves to it automatically — F12 fix; this matches Task 4's explicit `.alert` requirement.

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | Screens sources | DocC-comment the view-models; document the lock-retry pattern + the BrainApi seam |
| App-flow | docs/technical/architecture/app-flow.md | (already written this session — these screens implement it; no further edit) |

## Acceptance Criteria
- [ ] Run `xcodegen generate` + the screen-model tests (gated on a Mac) → verify: `ReviewModel.load` populates both lists; `approve` optimistically removes + reconciles; a `.vaultLocked` error triggers `onLocked`; `ChatModel.send` appends user + streamed assistant text from a fake stream; `StatusModel.lockNow`/`signOut` drive the AppModel.
- [ ] Inspect sources → verify: `@Observable` view-models, no `ObservableObject`, no token/nonce rendered or logged; Review renders the explanation verbatim.
- [ ] (GATED, simulator/device) the three screens against a live brain on iPhone + iPad → verify recorded in handoff.

## Progress
_(Coding mode writes here — do not edit manually)_
