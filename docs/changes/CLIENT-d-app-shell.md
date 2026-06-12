<!-- amended 2026-06-11 per contracts.md (Seam 3) + client.md BLOCKs B5, B6, B7; Decision D6 (brain URL captured at pairing, Settings-editable) -->
---
spec: client-d-app-shell
status: ready
token_profile: balanced
autonomy_level: L2
---

# Spec: CLIENT-d — ArtemisApp shell (XcodeGen target + adaptive nav + onboarding/pairing flow + lock chrome + AppModel coordinator)

**Identity:** Implements the universal (iPhone + iPad) SwiftUI app target on top of ArtemisKit: the XcodeGen project, the `@main App`, an `@Observable` `AppModel` that drives the connection/lock state machine, the adaptive root shell (bottom tabs on compact width → `NavigationSplitView` sidebar on regular width), the onboarding/pairing flow (one Face-ID connect+unlock), and the global lock banner + re-unlock sheet.
→ why: see docs/technical/architecture/app-flow.md (states, adaptive nav, onboarding journey) · docs/technical/adr/ADR-010-client-app-auth.md (one-gesture connect+unlock).

<!-- Split rule: flagged atomic exception (precedent: M2-a/CLIENT-c whole-package specs). ONE app target (XcodeGen project + 4 sources + tests) that must build as a unit; the screens (Review/Chat/Status) are CLIENT-e and slot into this shell's destination switch. Consumes CLIENT-c (ArtemisKit: Authenticator, ApiClient, DeviceIdentity, DTOs, ConnectionState). -->

## Assumptions
- CLIENT-c (ArtemisKit) complete: `Authenticator` (pair/connect/unlock/connectAndUnlock/logout), `ApiClient`, `DeviceIdentity`/`Signer`, `KeychainStore`, the DTOs, `ConnectionState`, `ApiError` (`.unauthenticated`/`.vaultLocked`). → impact: Stop (the app imports + drives these exactly).
- **ADR-017 multiplatform amendment:** `Authenticating` is **imported from ArtemisKit** (promoted there in CLIENT-c), NOT defined app-locally — `AppModel` drives `any Authenticating`. `AppModel` also **conforms to `AppCoordinating`** (the `Sources/Screens/` protocol from CLIENT-e: `lock()`/`logout()`) so the shared Status screen binds the protocol, not the concrete type, and the macOS `MacAppModel` (CLIENT-f) reuses the screens identically. → impact: Caution (one import swap + a trivial conformance; resolves the CLIENT-f reuse seam).
- **Swift 6 language mode ON**; view-models are `@MainActor @Observable final class`; routing is size-class-adaptive SwiftUI (`NavigationSplitView` regular / `TabView` compact); no `ObservableObject` (apex-swift hard blocks). → impact: Stop.
- **Universal, equal polish** (chosen 2026-06-08): one iOS target, iPhone + iPad both primary; adaptivity is driven by `horizontalSizeClass`, not `#if`. iPad gets the sidebar + keyboard shortcuts. → impact: Caution (every shell view adapts to both size classes).
- The packaging is **XcodeGen** (`project.yml` → generated `.xcodeproj`) so DeepSeek can hand-edit + regenerate (a binary `.xcodeproj` is not hand-editable). → impact: Low (default chosen 2026-06-08; overridable).
- Pairing input: **manual code entry is the always-available baseline**; a QR scan (`DataScannerViewController`, iOS 16+) is an additive convenience. The code is shown out-of-band by the brain (CLIENT-b `mint_pairing_code` one-liner). → impact: Caution (manual entry must work even if the camera path is unavailable).
- The three screens (Review/Chat/Status) are CLIENT-e; this spec ships the shell with **placeholder destinations** (`ContentUnavailableView`) that CLIENT-e replaces by editing the shell's destination switch. → impact: Low (clean build seam; CLIENT-d builds + runs standalone).
- apex-swift Verification Recipe is v0.1.0 unvalidated → UI build/run validated on the first Mac/simulator build (gated). → impact: Caution (recorded).

Simplicity check: considered a single NavigationStack for both size classes — rejected; equal-polish iPad wants a sidebar (`NavigationSplitView`), which is the idiomatic regular-width container. Considered QR-only pairing — rejected; manual entry is the robust, testable baseline (camera is an enhancement). Considered a redux-style store — rejected; one `@Observable AppModel` is the apex-swift default and is directly testable.

## Prerequisites
- Specs that must be complete first: CLIENT-c (ArtemisKit). CLIENT-b provides the live endpoints the app talks to (integration is gated on a running brain + tailnet).
- Environment setup required: Xcode (Swift 6) + XcodeGen (`brew install xcodegen` on the build Mac). Off-device: `AppModel` unit-tests with a fake Authenticator; the full UI run + live pairing are gated on simulator/device.

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| /Users/artemis-build/artemis/swift/ArtemisApp/project.yml | create | XcodeGen manifest: universal iOS app target, ArtemisKit local-package dep, Info.plist keys (Face ID, camera), iOS 17 |
| /Users/artemis-build/artemis/swift/ArtemisApp/Sources/ArtemisApp.swift | create | `@main struct ArtemisApp: App`; injects `AppModel`; roots Onboarding-or-Shell |
| /Users/artemis-build/artemis/swift/ArtemisApp/Sources/AppModel.swift | create | `@MainActor @Observable final class AppModel`: state machine + connect/unlock/lock/logout + `requireUnlock()` |
| /Users/artemis-build/artemis/swift/ArtemisApp/Sources/RootShell.swift | create | adaptive shell (tabs ↔ split-view) + lock banner + re-unlock sheet + placeholder destinations |
| /Users/artemis-build/artemis/swift/ArtemisApp/Sources/OnboardingView.swift | create | pairing flow (manual code + optional QR) → one-gesture connect+unlock |
| /Users/artemis-build/artemis/swift/ArtemisApp/Tests/ArtemisAppTests/AppModelTests.swift | create | AppModel state transitions against a fake Authenticator |

## Tasks
<!-- LINT-DEFER 2026-06-11: WARN CLIENT-d:42 — adding an off-Mac validity check (xcodegen dry-run / YAML lint) depends on whether xcodegen or a YAML linter is present in the build env; the report itself qualifies it "if available". Choosing a specific tool would be a guess about the environment. -->
- [ ] Task 1: XcodeGen project — files: `/Users/artemis-build/artemis/swift/ArtemisApp/project.yml` — define an app `name: Artemis`, `options.deploymentTarget.iOS: "17.0"`; one target `Artemis` (`type: application`, `platform: iOS`, `supportedDestinations` iPhone + iPad), sources `Sources`, a test target `ArtemisAppTests` (sources `Tests/ArtemisAppTests`); a local SPM package dependency on `../ArtemisKit`; `settings`: `SWIFT_VERSION: 6.0`, `SWIFT_STRICT_CONCURRENCY: complete`, a dev bundle id `com.artemis.app`; `info.properties`: `NSFaceIDUsageDescription` ("Unlock Artemis and authorise actions"), `NSCameraUsageDescription` ("Scan the pairing code"), `UISupportedInterfaceOrientations` for both idioms. — done when: `xcodegen generate --spec swift/ArtemisApp/project.yml` produces `Artemis.xcodeproj` and `xcodebuild -project swift/ArtemisApp/Artemis.xcodeproj -scheme Artemis -destination 'generic/platform=iOS Simulator' build` compiles (gated to a Mac — see Task 6).

- [ ] Task 2: AppModel state machine — files: `/Users/artemis-build/artemis/swift/ArtemisApp/Sources/AppModel.swift` — **B5/B6/B7 fixes applied here.**
  - **Define `Authenticating` protocol** (app-local, in `AppModel.swift` or a small companion file `Authenticating.swift` in Sources): `@MainActor protocol Authenticating: AnyObject { func pair(pairingCode: String, brainBaseURL: URL) async throws; func connect() async throws -> SessionCompleteResponse; func unlock(scope: String) async throws; func connectAndUnlock(biometric: LAContext) async throws; func logout() async throws; func lock() async throws; func currentToken() -> String?; var isPaired: Bool { get } }` — `isPaired` (B7/F7 fix: `bootstrap()` can query keychain state through this protocol without a separate accessor). **CLIENT-c Task 5 already ships every method of this protocol — including `func lock() async throws` and `var isPaired: Bool { get }`** (added there as the Authenticator's home). CLIENT-d therefore only writes the conformance declaration `extension Authenticator: Authenticating {}` — it does NOT add or re-implement any `Authenticator` method here.
  - `@MainActor @Observable final class AppModel`. Holds `private let auth: any Authenticating` (B5 fix — protocol existential, not the concrete `Authenticator` actor; enables `FakeAuthenticator` injection in tests without subclassing), `private let api: ApiClient`, `var state: ConnectionState`, `var currentToken: String?` (B7 fix — `@MainActor` cached token, updated on connect/logout so screen view-models can read it synchronously without calling the actor-isolated `currentToken()`), `var needsUnlock: Bool`, `var lastError: String?`. Constructed with `(auth: any Authenticating, api: ApiClient)` (production: built from `ApiClient(baseURL:)` + a real `Authenticator`; tests inject fakes). `var api: ApiClient` exposed as a `let` so CLIENT-e screens can access it (B7 fix — AppModel is the sole `ApiClient` holder). Methods (all `@MainActor`): `func bootstrap() async` (use `auth.isPaired` to decide `unpaired` vs `disconnected`; load cached token from keychain if present); `func pair(code: String, brainURL: URL) async` (passes `brainURL` to `auth.pair(pairingCode:brainBaseURL:)` which persists it to the keychain, then calls `connectAndUnlock`; Decision D6 — no env var); `func connectAndUnlock() async` (one Face-ID `LAContext` → `try await auth.connectAndUnlock(biometric: context)`; on success `currentToken = auth.currentToken()`, `state = .unlocked`; map `ApiError.vaultLocked` → `state = .connectedLocked`, `.unauthenticated` → `state = .disconnected`); `func reUnlock() async` (Face-ID `LAContext` → `auth.unlock()`; `currentToken = auth.currentToken()`; clears `needsUnlock`); `func lock() async` (B6 fix — `try await auth.lock()` which calls `api.lock`; `state = .connectedLocked`; `currentToken` stays set — session survives lock, ADR-010 §6); `func logout() async` (`try await auth.logout()`; `currentToken = nil`; `state = .unpaired`-or-`.disconnected`); `func requireUnlock()` (sets `needsUnlock = true`). Errors set `lastError` (a user-facing string; never the raw token/nonce). — done when: `xcodebuild`/`swift build` of the target compiles; the transitions are covered in Task 5.

- [ ] Task 3: Adaptive root shell + lock chrome — files: `/Users/artemis-build/artemis/swift/ArtemisApp/Sources/RootShell.swift` — `enum Destination: Hashable, CaseIterable { case review, chat, status }` (Review first). `struct RootShell: View` reading `@Environment(AppModel.self)` + `@Environment(\.horizontalSizeClass)`: when `.regular` → `NavigationSplitView` (sidebar lists the destinations, detail = the selected screen); else → `TabView` (Review/Chat/Status tabs, Review default). A `@ViewBuilder func destinationView(_:)` that currently returns `ContentUnavailableView("<name>", systemImage: ...)` placeholders (CLIENT-e replaces these). A `LockBanner` subview shown when `state == .connectedLocked` ("Vault locked — tap to unlock" → `model.reUnlock()`), `.accessibilityAddTraits(.isButton)`, foreground/background contrast ≥ 4.5:1 in light + dark (semantic colours); **on appear post `UIAccessibility.post(.announcement, "Vault locked. Tap the banner to unlock.")`** so VoiceOver users learn of the lock without navigating to it (WCAG 4.1.3). A `.sheet(isPresented: needsUnlock)` presenting a `ReUnlockSheet` (Face-ID prompt → `model.reUnlock()`): **declare an `@AccessibilityFocusState` and on `.onAppear` move VoiceOver focus to the unlock button; on dismiss return focus to the element that triggered `requireUnlock()`** (WCAG 2.4.3 — BLOCK fix). Keyboard shortcuts on iPad (⌘1/⌘2/⌘3 select destinations); the sidebar list items are keyboard-navigable (arrow/Tab — add `.focusable()` if `NavigationSplitView` does not provide it natively; verify in Task 6). **Every tappable control is ≥ 44×44pt** (`.frame(minWidth:44,minHeight:44)` / `.contentShape` + padding for icon-only buttons). All controls carry VoiceOver labels. — done when: the target compiles; `RootShell` renders tabs on compact + a split view on regular (verified in the gated UI run, Task 6).

- [ ] Task 4: Onboarding / pairing flow — files: `/Users/artemis-build/artemis/swift/ArtemisApp/Sources/OnboardingView.swift` — `struct OnboardingView: View`: an explanatory step → a **brain URL field** (plain text, pre-filled with the last stored URL if available; label "Brain address", e.g. `https://artemis.tailnet-name.ts.net`) + a **code entry field** (the always-available path) + an optional **"Scan code"** button presenting a `DataScannerViewController`-backed scanner (guarded so the absence of camera permission degrades to manual entry, not a dead end) → on submit, `await model.pair(code:, brainURL:)` which persists the URL to the keychain, generates the SE key (first run), registers, then runs the one-Face-ID `connectAndUnlock`. **Decision D6 (2026-06-11): the brain URL is entered here, stored in keychain — not from `ARTEMIS_BRAIN_URL` env var (env vars are not accessible at iOS runtime).** Progress + error states (`model.lastError`) are shown inline; success dismisses to the shell. The brain URL field also appears in a Settings screen (CLIENT-e or a simple `Form` accessible from the root shell) so it can be edited after initial pairing without re-pairing. **Pairing-code field a11y:** `.textContentType(.oneTimeCode)`, `.font(.system(.body, design: .monospaced))` (named text style → scales with Dynamic Type — NOT a fixed size), an explicit `.accessibilityLabel("Pairing code")`, and **paste must NOT be suppressed** (WCAG 3.3.8 — no delegate/modifier blocking paste). **QR scanner a11y (BLOCK fix):** the camera overlay carries a visible VoiceOver-labelled instruction ("Point the camera at the pairing code; it scans automatically"), the raw viewfinder wrapper sets `isAccessibilityElement = false`, and a successful scan posts `UIAccessibility.post(.announcement, "Pairing code scanned")` before dismissing. Dynamic Type + VoiceOver labels throughout. — done when: the target compiles; the manual-entry path drives `model.pair` (verified in Task 5 via the AppModel; full UI in Task 6).

- [ ] Task 5: AppModel unit tests — files: `/Users/artemis-build/artemis/swift/ArtemisApp/Tests/ArtemisAppTests/AppModelTests.swift` — swift-testing with a `FakeAuthenticator: Authenticating` (the `Authenticating` protocol defined in Task 2 — B5 fix; the SE/network are out of the test because `AppModel` holds `any Authenticating`). `FakeAuthenticator` stubs **all 8 `Authenticating` members** (`pair`, `connect`, `unlock`, `connectAndUnlock`, `logout`, `lock`, `currentToken`, `isPaired`) returning canned values: `bootstrap` with `isPaired == false` → `state == .unpaired`; with `isPaired == true` → `.disconnected`; `pair` happy path → `connectAndUnlock` → `.unlocked` + `currentToken` set; `connectAndUnlock` mapping `ApiError.vaultLocked` → `.connectedLocked`; `.unauthenticated` → `.disconnected`; `reUnlock` clears `needsUnlock`; `lock` → `.connectedLocked` (session survives — `currentToken` non-nil); `logout` → `currentToken == nil` + `.unpaired`/`.disconnected`; an error sets `lastError` without leaking a token. — done when: `xcodebuild test` (or `swift test` on the testable target if AppModel is in a testable SPM target) passes off-device for the AppModel transitions.

- [ ] Task 6 (GATED — on simulator/device): UI build + run + live pairing — files: (uses Tasks 1–4) — on a Mac: `xcodegen generate` + `xcodebuild ... build` the app for the iOS simulator; launch; confirm the adaptive shell shows tabs on an iPhone sim and a split view on an iPad sim; against a running brain (CLIENT-b on the tailnet) complete a real pairing (minted code) → one Face-ID connect+unlock → land on the (placeholder) Review destination; lock → banner appears → re-unlock works. ADR-010 end-to-end. **Manual VoiceOver pass (mandatory, apex-accessibility):** with VoiceOver on, navigate the pairing flow (incl. the QR overlay), the lock banner, and the re-unlock sheet — confirm focus moves to the sheet on present + returns on dismiss, the lock announcement fires, and no control is unlabelled; record gaps in the handoff. Optionally run Xcode's Accessibility Inspector audit on the sim. — done when: the app pairs, connects, unlocks, locks, and re-unlocks against a live brain on both idioms AND the VoiceOver pass is clean — recorded in handoff.

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | /Users/artemis-build/artemis/swift/ArtemisApp/project.yml, /Users/artemis-build/artemis/swift/ArtemisApp/Sources/ArtemisApp.swift, /Users/artemis-build/artemis/swift/ArtemisApp/Sources/AppModel.swift, /Users/artemis-build/artemis/swift/ArtemisApp/Sources/RootShell.swift, /Users/artemis-build/artemis/swift/ArtemisApp/Sources/OnboardingView.swift, /Users/artemis-build/artemis/swift/ArtemisApp/Tests/ArtemisAppTests/AppModelTests.swift |
| Modify | (none) |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `brew install xcodegen` (on the build Mac, once) | Project generator |
| `xcodegen generate --spec swift/ArtemisApp/project.yml` | Generate the Xcode project |
| `xcodebuild -project swift/ArtemisApp/Artemis.xcodeproj -scheme Artemis -destination 'generic/platform=iOS Simulator' build` (GATED, Mac) | Build gate |
| `xcodebuild test -project swift/ArtemisApp/Artemis.xcodeproj -scheme Artemis -destination 'platform=iOS Simulator,name=iPhone 16'` (GATED, Mac) | Test gate (AppModel) |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | swift/ArtemisApp/project.yml, swift/ArtemisApp/Sources/**, swift/ArtemisApp/Tests/** (NOT the generated `Artemis.xcodeproj` — add it to `.gitignore`) |
| `git commit` | "feat: CLIENT-d ArtemisApp shell (adaptive nav + onboarding/pairing + lock chrome + AppModel)" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| (none) | Brain base URL is captured at pairing, stored in the Keychain via `KeychainStore.brainBaseURL`, and editable in Settings. No `ARTEMIS_BRAIN_URL` env var — env vars are not accessible at iOS runtime (Decision D6). |

### Network
| Action | Purpose |
|--------|---------|
| `brew install xcodegen` | Tool install (build Mac) |
| (runtime) app → brain `/app/*` over the tailnet | the live client traffic (gated integration) |

## Specialist Context
### Security
The app never persists a secret outside the keychain (ArtemisKit owns that); `AppModel` holds only transient UI state + a redacted `lastError`. The pairing code is entered, used once, never stored or logged. Face ID gates the one connect+unlock gesture. [FLAG apex-security + apex-auth: confirm no token/code/nonce is rendered or logged; confirm the camera/QR path degrades safely to manual entry; confirm `ATS` is not globally disabled (tailnet HTTPS is valid TLS via Tailscale).]

### Performance
`@Observable` re-renders only the views reading changed properties. Connect+unlock is two IPC-backed round-trips behind one Face-ID. No blocking work on `@MainActor` — `Authenticator` is an actor.

### Accessibility
First-UI surface → apex-accessibility applies (the gate auto-fires an accessibility review). Requirements baked in: every control has a VoiceOver label; Dynamic Type respected (no fixed font sizes); 44×44pt minimum touch targets; the lock banner is a labelled button with the `.isButton` trait; focus moves to the re-unlock sheet on present; colour is never the sole state signal (lock state also carries text/icon); `Reduce Motion` honoured for any transition. Detailed per-screen criteria continue in CLIENT-e.

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | ArtemisApp sources | DocC-comment public types; document the `AppModel` state machine + the adaptive-nav rule + the placeholder-destination seam CLIENT-e fills |
| App-flow | docs/technical/architecture/app-flow.md | (already written this session — implements the Onboarding + shell journeys; no further edit needed) |

## Acceptance Criteria
- [ ] Run `xcodegen generate --spec swift/ArtemisApp/project.yml` → verify: `Artemis.xcodeproj` is produced with the iPhone+iPad app target + the ArtemisKit dependency.
- [ ] Run the AppModel tests (gated on a Mac) → verify: every documented state transition holds; an error never leaks a token into `lastError`.
- [ ] (GATED, simulator/device) Build + run → verify: tabs on iPhone, split-view on iPad; a live pairing → one Face-ID connect+unlock → Review destination; lock → banner → re-unlock — recorded in handoff.
- [ ] Inspect sources → verify: Swift 6 language mode, `@Observable` (no `ObservableObject`), no secret in `UserDefaults`/logs.

## Progress
_(Coding mode writes here — do not edit manually)_
