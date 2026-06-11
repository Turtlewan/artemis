# Spec-Lint Report — CLIENT specs

Final pre-handoff lint pass. Executor: DeepSeek V4-Flash (literal). Date: 2026-06-11.
Scope: CLIENT-a, CLIENT-b, CLIENT-broker, CLIENT-c, CLIENT-d, CLIENT-e.

---

## CLIENT-a-app-auth-core.md

**Verdict: PASS** (WARN-only)

File explicitness, atomicity, code detail, and acceptance criteria are strong. All types and method signatures are given exactly; every task has a runnable `done when` check. Tasks 2 and 3 share one file but are cleanly separated logical phases (stores vs. orchestration) and each is independently verifiable — acceptable.

| spec:line | BLOCK/WARN | check | what's wrong | minimal fix |
|-----------|-----------|-------|--------------|-------------|
| CLIENT-a:62 | WARN | cross-ref | `resolve_person` and `resolve_scope` import `OWNER_PERSON_ID`/`OWNER_SCOPE` from `artemis.gateway`; the exact value/type of these constants is assumed-from-M1-c, not inlined. Flash can build the import but cannot self-check the type if M1-c diverged. The Assumptions block (line 16) does name them, so this is borderline — soft flag only. | Inline the expected type in Task 3, e.g. `# OWNER_SCOPE: Scope (str alias from M1-c)`. |
| CLIENT-a:33 | WARN | new-file parent dir | `src/artemis/identity/app_auth.py` is created; whether the `identity/` package dir + `__init__.py` exist is not stated. Task 2 line 46 creates the *runtime* `identity_dir` on disk but not the *source* package. | Add to Task 2: "create `src/artemis/identity/__init__.py` if absent." |

---

## CLIENT-b-app-endpoints.md

**Verdict: BLOCK**

The previously-flagged non-default-after-default trap is correctly fixed (Task 2, line 54: `request: Request` declared first — explicitly called out). However two defects remain that will make Flash build the wrong symbol surface, plus a cross-spec contract contradiction.

| spec:line | BLOCK/WARN | check | what's wrong | minimal fix |
|-----------|-----------|-------|--------------|-------------|
| CLIENT-b:155 | BLOCK | acceptance / code detail | Acceptance criterion imports `mint_pairing_code` from `artemis.api_app`, but **no task defines a `mint_pairing_code` symbol**. Task 2 (line 50–51) implements `PairingCodeStore.mint()` (a method) and a `POST /admin/pair-code` route — there is no module-level `mint_pairing_code`. Flash will either invent a stray function to satisfy the import check or the check fails. The Simplicity note (line 25) also says "a documented one-liner over a `mint_pairing_code()` helper," reinforcing a symbol the tasks never build. | Either add a task to define `def mint_pairing_code(...)` explicitly, or change line 155 import to `from artemis.api_app import app_router, PairingCodeStore, require_unlocked` and drop `mint_pairing_code` from line 25. |
| CLIENT-b:54 vs CLIENT-a:33,64 | BLOCK | cross-ref / contract mismatch | CLIENT-a builds `require_session` as a **factory** `require_session(auth) -> Callable` (line 64) and a "dependency factory" (Files table line 33). CLIENT-b Task 2 line 54 says the factory-closure pattern "is replaced with a zero-arg dependency that reads `request.app.state.app_auth`" and uses `Depends(require_session)`. These are two incompatible signatures for the same symbol. Flash builds CLIENT-a first to the factory contract, then CLIENT-b consumes it as zero-arg → `Depends(require_session)` will pass the FastAPI `Request`-less factory and break, or Flash silently rewrites CLIENT-a's symbol. | Make CLIENT-b Task 2 explicit: "redefine `require_session` in `api_app.py` as `async def require_session(request: Request) -> Principal` reading `request.app.state.app_auth`; do NOT call CLIENT-a's factory." OR change CLIENT-a to ship the zero-arg form. The two specs must agree on ONE signature. |
| CLIENT-b:78 | WARN | atomicity (>3 sub-steps) | Task 5 main.py wiring bundles: build registry, auth, ReviewSurface (compose RecipeStore+Promoter+embedder), PairingCodeStore, RateLimiter, prod-vs-fake startup assertion, app.state attach, include_router — 8 sub-steps in one task. The ReviewSurface composition ("reuse the existing brain composition where possible") is the weakest: it is exploratory, not a named call. | Split the ReviewSurface composition into its own sub-bullet with the exact constructor signature, or name the existing M1-b/M7-b factory function to call. |
| CLIENT-b:78 | WARN | env precondition | "if the active provider is not the real `BrokerKeyProvider` AND `s.slot == "prod"`" — the value space of `s.slot` (is `"prod"` the exact literal?) is assumed from M0-a, not inlined. | Inline: confirm `Settings.slot` is a `str` whose prod value is exactly `"prod"`. |
| CLIENT-b:34 | WARN | new-file parent dir | `scripts/setup_tailscale_serve.sh` created — `scripts/` dir existence not confirmed. | Add "create `scripts/` if absent" to Task 5. |

---

## CLIENT-broker-pair-ipc.md

**Verdict: PASS** (WARN-only)

Tight, single-phase, additive Swift spec. Files all named, every task has a `swift build`/`swift test` check, error-frame shape inlined. The re-pair-resets-counter invariant is stated (Task 2 line 38).

| spec:line | BLOCK/WARN | check | what's wrong | minimal fix |
|-----------|-----------|-------|--------------|-------------|
| CLIENT-broker:36 | WARN | code detail | The closure type is `pairHandler: (_ deviceId: String, _ publicKeyB64: String) throws -> Void`, but the dispatch body decodes JSON key `public_key` into a local then "call `try pairHandler(deviceId, publicKeyB64)`". The local variable name `publicKeyB64` vs JSON key `public_key` is implied, not spelled. Minor; a literal executor may name the decoded var `public_key`. Harmless to compile. | One line: "decode JSON `public_key` into `publicKeyB64`". |
| CLIENT-broker:16,38 | WARN | cross-ref | `RegisteredDeviceStore.register(deviceId:publicKey:)` exact signature is "match it if it differs" (line 16) — Flash cannot verify against M2-a from the spec alone, but the spec explicitly instructs to match the existing symbol, which is acceptable for an additive reuse. | None required; acceptable per checklist (consumed shape is reuse-existing, not new). |

---

## CLIENT-c-artemiskit.md

**Verdict: BLOCK**

Excellent signature-level detail and byte-exact assertion contracts. But a keychain service-id contradiction will produce two different keychain partitions, and a missing concrete `lock()`/`isPaired` surface (relied on by CLIENT-d) is not built here.

| spec:line | BLOCK/WARN | check | what's wrong | minimal fix |
|-----------|-----------|-------|--------------|-------------|
| CLIENT-c:21 vs CLIENT-c:47 | BLOCK | code detail / internal contradiction | Assumption (line 21) states the URL is persisted "in the **Keychain** (under the `ArtemisKit` service, key `brainBaseURL`)". Task 3 (line 47) states `KeychainStore` uses "a service id `com.artemis.app`". Two different service identifiers for the same store. Flash will pick one literally; if it picks `ArtemisKit` for the URL and `com.artemis.app` for everything else, the URL writes/reads to a different keychain partition and `fromKeychain` throws `.noBaseURL` at runtime. | Pick one. Change line 21 to "under the `com.artemis.app` service" to match Task 3 (the implementable one). |
| CLIENT-c (whole) vs CLIENT-d:45 | BLOCK | cross-ref / missing symbol | CLIENT-d Task 2 requires `Authenticator.lock()` and `Authenticator.isPaired` and says they "must be applied before CLIENT-d builds (add to CLIENT-c Task 5 ... or implement them here)." CLIENT-c Task 5 (lines 52–58) does **not** define `lock()` or `isPaired`. So per CLIENT-c as-written, these symbols do not exist; the cross-spec dependency is dangling. A literal executor building CLIENT-c will not add them. | Add to CLIENT-c Task 5: `func lock() async throws` (calls `api.lock(token: currentToken() ?? "")` then clears the cached token) and `var isPaired: Bool { get }` (true iff `deviceId` + `seKeyBlob` exist in keychain), with the exact signatures CLIENT-d's protocol expects. |
| CLIENT-c:55 | WARN | cross-ref / value source | `unlock(scope: String = "owner-private")` builds the signed message `nonce ‖ scope ‖ counter`; the broker (M2-a) is the verifier and must agree on the scope string `"owner-private"`. The exact M2-a scope literal is not inlined — if the broker expects a different owner-scope string, the signature verifies over the wrong bytes and unlock silently fails on hardware (gated, so not caught off-device). | Inline a one-line note confirming `"owner-private"` is the exact M2-a owner scope string, or cite the M2-a constant. |
| CLIENT-c:62 | WARN | acceptance (human judgment) | Task 7 `done when: a real SE key signs + verifies + persists on-device, recorded in handoff` — gated + narrative; acceptable as a gated task but not machine-checkable. | None (correctly gated). |

---

## CLIENT-d-app-shell.md

**Verdict: BLOCK**

The ambiguous either/or placement of the `Authenticator.lock()`/`isPaired` additions is the core defect — a literal executor cannot resolve "add to CLIENT-c OR implement here." Combined with the CLIENT-c gap above, the protocol conformance can fail to build.

| spec:line | BLOCK/WARN | check | what's wrong | minimal fix |
|-----------|-----------|-------|--------------|-------------|
| CLIENT-d:45 | BLOCK | atomicity / ambiguous instruction | "add to CLIENT-c Task 5 as a conformance addendum, **or** implement them here in a retroactive extension in the app module if CLIENT-c is already built." A literal executor cannot decide between two mutually-exclusive code locations and will likely do neither or both (duplicate symbol). The `extension Authenticator: Authenticating {}` (same line) then fails to compile if `lock()`/`isPaired` are absent. | Resolve to ONE location. Given the CLIENT-c BLOCK above, add `lock()`/`isPaired` to CLIENT-c Task 5 and change CLIENT-d line 45 to: "CLIENT-c now ships `lock()` + `isPaired`; CLIENT-d only writes `extension Authenticator: Authenticating {}`." Delete the either/or. |
| CLIENT-d:45 | WARN | code detail / signature | Protocol declares `func connectAndUnlock(biometric: LAContext)` and `func lock() async throws`; CLIENT-c's actor method is `connectAndUnlock(biometric context: LAContext)`. External label `biometric` matches, so conformance holds — but verify `lock()` signature added to CLIENT-c is exactly `func lock() async throws` (no args) to satisfy this protocol. | Ensure the CLIENT-c addition matches `func lock() async throws` verbatim. |
| CLIENT-d:52 | WARN | atomicity (>3 sub-steps) | Task 5 (AppModel unit tests) asserts ~9 distinct transitions in one task; acceptable for a test task but the `FakeAuthenticator` conforming to `Authenticating` must implement all 8 protocol methods — not enumerated. | Add: "`FakeAuthenticator` stubs all 8 `Authenticating` methods returning canned values." |
| CLIENT-d:42 | WARN | acceptance | Task 1 `done when` is the gated `xcodebuild` (Task 6) — off-Mac there is no runnable check that `project.yml` is valid YAML. | Add an off-Mac check: `xcodegen generate --spec ...` dry-run or a YAML lint, if available in the build env. |

---

## CLIENT-e-screens.md

**Verdict: BLOCK**

Screen specs are well-detailed with exact view-model constructors and a11y criteria. One hard contradiction: the Environment Access table reintroduces `ARTEMIS_BRAIN_URL`, directly contradicting Decision D6 (no env var; URL from keychain) enforced across CLIENT-c/d.

| spec:line | BLOCK/WARN | check | what's wrong | minimal fix |
|-----------|-----------|-------|--------------|-------------|
| CLIENT-e:86 | BLOCK | env precondition / cross-spec contradiction | Environment Access table lists `ARTEMIS_BRAIN_URL` "base URL (via AppModel)". This contradicts Decision D6 (banner line 1) and CLIENT-c:21/91 + CLIENT-d:85, which all state explicitly there is NO `ARTEMIS_BRAIN_URL` env var (env vars are inaccessible at iOS runtime; URL comes from keychain). A literal executor reading this table may wire an env-var lookup that cannot work on iOS, or contradict the AppModel's keychain-sourced `ApiClient`. | Replace the row with: `| (none) | Brain base URL comes from Keychain via AppModel.api — no env var (Decision D6) |`. |
| CLIENT-e:55 | WARN | code detail / token provider | Task 5 passes token provider `{ model.currentToken }`. The closure type expected by the view-models is `token: @Sendable () -> String?` (Task 2 line 43). `model.currentToken` is `@MainActor`-isolated state on `AppModel`; capturing it in a `@Sendable` closure may trip Swift 6 strict-concurrency. The spec asserts it's "synchronously readable — no actor-isolation violation" but does not show the closure satisfies `@Sendable`. | Specify the provider closure is constructed `@MainActor` and the protocol uses `@MainActor () -> String?` (not `@Sendable`), or confirm the capture is isolation-safe with a one-line note. |
| CLIENT-e:48 | WARN | code detail / deferred decision | Task 3 Chat footer: "Set a dim footer (path/tool/escalated) when the stream completes (omit in v1 if it needs a second call — document)." Leaves a build-time branch to the executor's judgment. | State the v1 decision explicitly: "omit the footer in v1; the SSE stream carries no trailing metadata frame" (or define the frame). |
| CLIENT-e:32 | WARN | new-file parent dir | `Sources/Screens/` is a new subdir (BrainApi/Review/Chat/Status all under it); CLIENT-d created `Sources/` flat. Dir creation implicit. | Note "create `Sources/Screens/`"; ensure `project.yml` source globbing includes the subdir (it globs `Sources` recursively — confirm). |

---

## Area verdict

**BLOCK** — 4 of 6 specs carry BLOCK findings (CLIENT-b, -c, -d, -e); CLIENT-a and CLIENT-broker are PASS. The dominant theme is **cross-spec contract drift** introduced by the 2026-06-11 amendments: the `require_session` factory-vs-zero-arg split (CLIENT-a↔b), the dangling `Authenticator.lock()`/`isPaired` addition with an unresolved either/or location (CLIENT-c↔d), the keychain service-id contradiction (CLIENT-c internal), the undefined `mint_pairing_code` symbol (CLIENT-b), and the re-introduced `ARTEMIS_BRAIN_URL` env var contradicting Decision D6 (CLIENT-e). All are small, surgical fixes but each would make Flash build a mismatched or non-compiling surface. Resolve the five BLOCKs before handoff.
