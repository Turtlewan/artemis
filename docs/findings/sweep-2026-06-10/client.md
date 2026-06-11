# CLIENT suite review — sweep 2026-06-10

Scope: CLIENT-a-app-auth-core, CLIENT-b-app-endpoints, CLIENT-broker-pair-ipc, CLIENT-c-artemiskit, CLIENT-d-app-shell, CLIENT-e-screens. Context: ADR-010, app-flow.md, GATE-b (Review-screen extension check).

Counts: **BLOCK 7 · UPGRADE 6 · FLAG 16 · RESEARCH 4**

What checks out (verified, no finding): endpoint paths and DTO field names match exactly between CLIENT-b (server), CLIENT-c (SDK), and CLIENT-e (screens); the pairing flow (key encoding, counter-reset-on-re-pair, two-store registration + rollback) is consistent across CLIENT-a ↔ CLIENT-b ↔ CLIENT-broker ↔ CLIENT-c; the API-session vs vault-unlock domain separation is carried coherently end-to-end; GATE-b's "Pending actions" extension slots cleanly into CLIENT-e's `List`-with-sections Review structure (GATE-b's title says "tab" but it implements a Section — compatible; `ReviewModel.error`, `onLocked`, and the `BrainApi` seam all line up).

---

## BLOCK

### B1 — CLIENT-b Task 2: `require_unlocked` / `require_session` wiring is unbuildable as written
`def require_unlocked(principal: Principal = Depends(require_session(...)), request: Request) -> Principal` is a Python **SyntaxError** (non-default parameter after a default). Worse, `require_session` is a CLIENT-a **factory** that needs an `AppAuth` instance — but `api_app.py` routes are decorated at module import time, while `AppAuth` is only constructed in `main.py`'s lifespan and parked on `app.state`. The `...` placeholder is unresolvable by a literal executor; every authed route depends on this. Fix: spec a module-level dependency that reads `request.app.state.app_auth` (drop the factory-closure usage in api_app.py), and give the exact corrected signature with `request: Request` ordered first.

### B2 — CLIENT-b Tasks 2/5: the pairing-code mint path is operationally unreachable
`PairingCodeStore` is in-memory on `app.state`, constructed in the lifespan. The spec's owner mint path is "a documented one-liner over `mint_pairing_code(app)` … mints via the running app's state". A CLI one-liner runs in a **separate process** and cannot touch the running server's `app.state`. As specced, no pairing code can ever be minted into the live brain → pairing can never start. Fix: add a loopback-only admin route (e.g. `POST /admin/pairing-code`, bound to 127.0.0.1 semantics — not exposed via tailscale serve) or persist the hashed code to a file the CLI can write and the app reads.

### B3 — CLIENT-c Task 6 contradicts Task 5 on the pairing signed message
Task 5 (matching CLIENT-b Task 3) mandates the length-prefixed message `uint16BE(len(code)) ‖ code ‖ deviceId`. Task 6's test description says the test verifies the code-signature "over `pairingCode|deviceId`" — the `|`-separator form both specs explicitly rejected. A literal executor writing the test from Task 6 produces a failing (or worse, wrongly-passing-against-the-wrong-bytes) test. Fix Task 6's wording to the length-prefixed bytes.

### B4 — CLIENT-c Tasks 2/4: four response DTOs are missing
CLIENT-b returns `{"paired": true}` (pair), `{"unlocked": true}` (unlock/complete), `{"locked": true}` (lock), `{"ok": true}` (logout). CLIENT-c Task 4 says every ApiClient method "decodes the typed response", but Task 2's WireModels list defines no DTO for any of these four. A literal executor has no type to decode into. Fix: add `PairResponse/UnlockCompleteResponse/LockResponse/OkResponse` (or specify these methods discard the body and return `Void` on 2xx).

### B5 — CLIENT-d Task 2 vs Task 5: AppModel's concrete `Authenticator` makes the required tests impossible
Task 2 specifies `private let auth: Authenticator` (the concrete CLIENT-c **actor** — actors cannot be subclassed or mocked). Task 5 then requires a `FakeAuthenticator` injected via an `Authenticating` protocol. As written, Task 2 must be reworked mid-build. Fix: Task 2 should declare `private let auth: any Authenticating` and the spec should define the `Authenticating` protocol's exact members (pair/connect/unlock/connectAndUnlock/logout/currentToken + whatever bootstrap needs — see F7) up front.

### B6 — CLIENT-d Task 2: `AppModel.lock()` calls an interface that doesn't exist
"`func lock() async` (`api.lock` via auth → `state = .connectedLocked`)" — CLIENT-c's `Authenticator` has **no lock method**, and AppModel holds no `ApiClient`. Missing interface between CLIENT-c and CLIENT-d. Fix: add `func lock() async throws` to `Authenticator` (it holds the api + token) in CLIENT-c, or give AppModel the ApiClient + token (which B7 needs anyway).

### B7 — CLIENT-d/CLIENT-e: the screens' token provider is concurrency-impossible and the ApiClient accessor is missing
CLIENT-e view-models take a **synchronous** `token: @Sendable () -> String?` closure and Task 5 constructs them "from the `AppModel`'s `ApiClient` + token provider". But (a) CLIENT-d's AppModel exposes neither an `ApiClient` property nor a token; (b) the only token source, `Authenticator.currentToken()`, is actor-isolated — calling it from a synchronous closure requires `await`, which Swift 6 strict concurrency rejects at compile time. A literal executor cannot bridge this. Fix: have AppModel cache the current token as `@MainActor` state (updated on connect/logout) and expose `var api: ApiClient` + `func currentToken() -> String?` on AppModel; spec the exact properties in CLIENT-d.

---

## UPGRADE

### U1 — CLIENT-b Task 2: RateLimiter keyed on `request.client.host` is a single global bucket behind `tailscale serve`
`tailscale serve` proxies to 127.0.0.1, so **every** remote peer arrives as the same `request.client.host`. The 5/15-min limit becomes one shared bucket: a single misbehaving tailnet peer locks out the owner's phone, and per-peer attribution is lost. Key on the peer identity `tailscale serve` forwards (its injected forwarded/identity headers — see R3), falling back to `client.host` for loopback.

### U2 — CLIENT-d Task 3 / Task 4, CLIENT-e Task 3: replace `UIAccessibility.post(.announcement, …)` with the SwiftUI-native API
On iOS 17+ (the deployment target) the idiomatic, strict-concurrency-clean call is `AccessibilityNotification.Announcement("…").post()` — no UIKit import in shared SwiftUI files, and it composes with `accessibilityAnnouncementPriority` where needed. Same fix in all three places the specs say `UIAccessibility.post`.

### U3 — CLIENT-c Task 4: `askStream` should own the mid-stream error frame
CLIENT-b emits a terminal `data: {"error":"vault_locked"}` frame; CLIENT-c's `askStream` as specced yields every `data:` payload verbatim, so CLIENT-e's ChatModel would append raw JSON to the transcript before detecting it (see F2). Better: `askStream` parses the frame and finishes the `AsyncThrowingStream` by throwing `ApiError.vaultLocked` — one detection point, ChatModel's existing `.vaultLocked` catch handles both pre-flight and mid-stream lock identically.

### U4 — CLIENT-e Task 4: `StatusModel.lockNow` duplicates the lock path
It calls `api.lock` then manually writes `appModel.state = .connectedLocked`, duplicating `AppModel.lock()` (CLIENT-d Task 2). Call `await appModel.lock()` instead — one lock path, one state writer.

### U5 — CLIENT-c Task 3: put `KeychainStore` behind a `KeychainStoring` protocol with an in-memory fake
The Authenticator tests (Task 6c) as written construct the real `KeychainStore`, hitting the actual macOS keychain from unit tests (prompting/flaky in headless runs — see F11). A 5-line protocol + dictionary-backed fake mirrors the existing `Signer` seam and keeps `swift test` hermetic.

### U6 — CLIENT-b Task 2 / CLIENT-c Task 2: standardise wire timestamps to ISO-8601
`SessionCompleteResponse.expires_at` comes from CLIENT-a's `Session.expires_at: float` (epoch seconds), while GATE-b's DTOs assume "a `JSONDecoder` with `.iso8601` … consistent with existing DTOs". Emit ISO-8601 from CLIENT-b so one decoder config serves all current and GATE-b DTOs; otherwise CLIENT-c must special-case a `Double` field (see F3).

---

## FLAG

### F1 — CLIENT-b Task 2: `/app/logout` needs the raw bearer token but the dependency yields a `Principal`
`auth.logout(token)` — `require_session` returns the principal, not the token. The route must re-read the `Authorization` header (or the dependency must return both); spec neither. Literal executor trips.

### F2 — CLIENT-b Task 4 / CLIENT-c Task 4 / CLIENT-e Task 3: ownership of the SSE `vault_locked` frame is split across three specs
CLIENT-e says ChatModel reacts to "`.vaultLocked` (or a terminal `{"error":"vault_locked"}` SSE frame)" — implying the raw frame reaches the view-model, while CLIENT-c's askStream contract says yield chunks until `[DONE]` with no error-frame handling. Exactly one layer must detect it (recommend CLIENT-c, see U3); say so in both specs.

### F3 — CLIENT-c Task 2: Swift DTO field **types** are never given
The DTO list names fields only. Most are inferable, but `expiresAt` (epoch `Double` vs `Date`/ISO — clashes with GATE-b's `.iso8601` decoder assumption), `path`/`toolUsed` optionality in `AskResponse`, and `counter` width (`Int` vs `UInt64`) are genuine executor decision points. Pin the types (and resolve with U6).

### F4 — CLIENT-b Task 6: the shared RateLimiter will 429 the spec's own test flow
One limiter instance keyed only on peer IP, shared across `/app/pair` + `/app/session/begin` + `/app/session/complete` + `/app/unlock/begin`, persists on `app.state` across tests; TestClient requests all share one host key. The pairing+session+unlock happy-path flow alone spends 4+ of the 5 attempts; subsequent tests get spurious 429s. Spec must state: fresh app/limiter per test fixture, and whether the production bucket is per-route or global.

### F5 — CLIENT-e Tasks 2/3 (and Assumption 3): "retry after unlock" has no mechanism
The view-models call `onLocked()` (presents the sheet) "and retry after unlock" — but nothing signals unlock completion back to the waiting view-model (AppModel has `needsUnlock: Bool` only; no continuation, callback, or observation contract is specced). Define it (e.g. the view-model observes `appModel.state == .unlocked` then re-invokes, or `requireUnlock()` returns an awaited result) or downgrade to "user retries manually".

### F6 — CLIENT-d Env table: `ARTEMIS_BRAIN_URL` cannot reach an iOS app at runtime
iOS apps don't read environment variables outside an Xcode scheme. Where the base URL actually lives on device (Info.plist key, Settings bundle, hardcoded dev constant, or entered at onboarding) is unspecified — and onboarding-entered would change the Onboarding flow. Decide and spec it.

### F7 — CLIENT-d Task 2: `bootstrap()` reads keychain state AppModel cannot reach
"decide `unpaired` vs `disconnected` from keychain device/key presence + token" — AppModel is constructed with an Authenticator only; no keychain accessor or `isPaired`-style query exists on any specced interface. Add it to the `Authenticating` protocol (fold into B5's fix).

### F8 — CLIENT-c Task 5: the repair-required predicate is vague
"On `ApiError.unauthenticated` whose counter was freshly loaded/zero" — "freshly loaded/zero" is not a checkable condition. Define it exactly (e.g. `if priorPersistedCounter == 0` at entry to `connect()`), else the executor invents semantics for an identity-wiping branch.

### F9 — CLIENT-b Tasks 1/2: the `UnlockProof` dict shape is by-reference only
"`{device_id: principal.device_id, signature, counter}` per M2-a `UnlockProof`" — exact JSON key names and whether `signature` is base64 string or bytes are unstated (the length-prefixed-JSON IPC implies b64 string; `BrokerClient.get_dek(scope, proof: dict)` then needs no decode). One wrong guess fails only on-hardware. Inline the exact key/value types.

### F10 — All Swift specs: acceptance criteria assume a configured Mac toolchain
`swift build/test` (CLIENT-broker, CLIENT-c), `brew install xcodegen`, `xcodegen generate`, and `xcodebuild … -destination 'platform=iOS Simulator,name=iPhone 16'` (CLIENT-d/e) all require Xcode CLT/Xcode + a downloaded iOS simulator runtime with that exact device name. CLIENT-d Acceptance #1 (`xcodegen generate`) is **not** marked GATED though it needs the Mac too. Also CLIENT-d Task 5's "(or `swift test` on the testable target)" is misleading — an iOS *app* target cannot run under `swift test`; only `xcodebuild test` with a simulator works (unless AppModel moves to a SPM-testable target). Mark every Swift criterion gated-on-Mac and name the simulator-runtime prerequisite in bring-up prep.

### F11 — CLIENT-c Task 6: Authenticator unit tests hit the real macOS keychain
Task 6c constructs the Authenticator with the concrete `KeychainStore`; `SecItemAdd` in `swift test` can prompt or fail headless. Resolve via U5.

### F12 — CLIENT-e Task 4 vs §Accessibility: `.alert` vs "Confirmation dialog on Sign out"
Task 4 explicitly mandates `.alert` *not* `.confirmationDialog`; the spec's own Accessibility section says "Confirmation dialog on Sign out". Task 4 is correct — fix the a11y section so a literal executor doesn't see two instructions.

### F13 — CLIENT-e Task 4: idle-lock countdown has no data source
The a11y text exposes "any idle-lock countdown … as the row's `accessibilityValue`", and app-flow promises Status shows "time-to-idle-lock" — but CLIENT-b's `StatusResponse {connected, vault_unlocked, device_id}` carries no such field. Either add it in CLIENT-b (broker `status()` likely has it) or strike the countdown from CLIENT-e and app-flow.

### F14 — CLIENT-c Task 5: `unlock(scope: String = "owner-private")` is an unpinned cross-language magic constant
It matches M1-c's `OWNER_SCOPE = "owner-private"` today (verified in M1-c-gateway-surfaces.md), but no spec asserts the equality; a drift makes the phone sign one scope while the brain relays another — unlock fails only on-hardware with a generic 401. Add an explicit cross-ref ("MUST equal M1-c `OWNER_SCOPE`") and an on-hardware acceptance line.

### F15 — CLIENT-b Assumption vs ADR-010 §5: transport contradiction
ADR-010 says "the same app additionally **binds the Tailscale interface**"; CLIENT-b mandates loopback-only + `tailscale serve`. CLIENT-b's design is better (TLS termination, no extra listener), but the accepted ADR now contradicts the ready spec — amend ADR-010 §5 so future readers/specs follow one story.

### F16 — CLIENT-c Task 3: `.userPresence` vs `.biometryCurrentSet` left as an unresolved either/or
The two have different semantics (`biometryCurrentSet` invalidates the key when Face ID is re-enrolled — i.e. forced re-pair on biometric change; `userPresence` allows passcode fallback). This is an owner-visible security/UX decision; pick one in the spec.

---

## RESEARCH

### R1 — Secure Enclave in the iOS simulator (CLIENT-c Task 7)
Task 7 gates on "Apple-silicon simulator/device". Historically the simulator has **no** Secure Enclave (`SecureEnclave.isAvailable == false`); recent Xcode releases changed parts of this. Verify on the actual Xcode version before relying on a simulator for the SE round-trip — otherwise Task 7 is physical-device-only (and needs a provisioned iPhone, not just the Mini).

### R2 — One-gesture / two-handshake `LAContext` reuse (CLIENT-c Tasks 3/5, ADR-010 §4)
The whole UX rests on one evaluated `LAContext` authorising **two** SE sign operations separated by network round-trips. The reuse window (`touchIDAuthenticationAllowableReuseDuration`, despite the name covering Face ID) is ≤ 5 s and interacts with the chosen `SecAccessControl` flags. Validate on-device early that the second sign doesn't re-prompt (or worse, fail) under realistic tailnet latency; CLIENT-c's `biometricRequired` fallback exists, but if re-prompting is the common case the ADR-010 §4 promise needs revisiting.

### R3 — `tailscale serve` CLI syntax + forwarded identity headers (CLIENT-b Task 5, U1)
`tailscale serve --bg --https=443 http://127.0.0.1:${BRAIN_PORT}` — the serve CLI syntax changed several times (2023–2025); verify against the version that will be installed on the Mini. Also confirm exactly which headers serve injects for peer identity (needed to fix U1's rate-limiter keying).

### R4 — XcodeGen currency (CLIENT-d Task 1)
Confirm the installed XcodeGen supports `supportedDestinations` and Swift-6 settings (`SWIFT_VERSION: 6.0`, `SWIFT_STRICT_CONCURRENCY: complete`) cleanly with the mid-2026 Xcode; XcodeGen lags new Xcode project-format changes. A 10-minute check on the build Mac before CLIENT-d starts.

---

## Cross-spec consistency matrix (checked)

| Contract | Server (CLIENT-b) | Client (CLIENT-c) | Screens (CLIENT-e) | Verdict |
|---|---|---|---|---|
| `/app/pair`, `/app/session/*`, `/app/unlock/*`, `/app/status`, `/app/lock`, `/app/logout`, `/app/review/*`, `/app/ask`, `/app/ask/stream` | defined | matching methods | via `BrainApi` | OK |
| Request DTO fields (snake_case) | defined | mirrored w/ CodingKeys | n/a | OK |
| 4 trivial response bodies | defined | **no DTOs** | n/a | B4 |
| Pairing signed message | length-prefixed | Task 5 matches; Task 6 contradicts | n/a | B3 |
| API-session message `nonce‖"artemis-api-session"‖counter8BE` | CLIENT-a verifies | CLIENT-c signs identically | n/a | OK |
| Vault proof scope string | brain relays `resolve_scope()` | hardcodes `"owner-private"` | n/a | F14 |
| Counter reset on re-pair | CLIENT-a registry + CLIENT-broker store | CLIENT-c keychain reset | n/a | OK |
| Mid-stream lock frame | emits | not handled | expects to see | F2/U3 |
| GATE-b Pending-actions section | additive routes | additive DTO/methods | Section into existing List | OK |
