---
spec: m2-a-key-broker
status: ready
token_profile: balanced
autonomy_level: L2
---

<!-- amended 2026-06-11 per Decision D4/D5 (contracts.md Seam 10) -->

# Spec: M2-a — Key-broker LaunchAgent (Secure-Enclave key gen/wrap/unwrap, per-scope DEK store, UnlockProof + mock prover, session lifecycle + zeroization, local IPC server, per-scope encrypted-volume mount-on-unlock)

**Identity:** Builds the hardened Swift `ArtemisBroker` LaunchAgent — the ONLY process that touches the Secure Enclave: generates per-scope SE wrapping keys (`.userPresence`), ECIES-wraps/unwraps each per-scope SQLCipher DEK, stores ciphertext on disk, verifies a fresh phone `UnlockProof` (behind one swappable interface + a mock prover test harness), enforces session lifetime + zeroization, MOUNTS the per-scope encrypted volume on a verified unlock (ADR-007 — the volume holds the scope's SQLCipher memory DB + LanceDB doc index; one unlock opens the whole per-scope vault), and exposes a local Unix-socket IPC (peer-credential + code-signing checked) to the brain.
→ why: see docs/technical/adr/ADR-005-owner-key-broker.md (the broker architecture) · docs/research/owner-key-brain-architecture.md (Apple SE mechanics + threat model) · docs/technical/adr/ADR-007-knowledge-layer.md (the broker mounts the per-scope encrypted volume on unlock — refines ADR-005).

<!-- Split rule: this spec creates ONE atomic component (the broker) in ONE logical phase. It exceeds 3 files because the broker is a new SwiftPM package that must compile as a unit: SE crypto + DEK store + UnlockProof interface + mock prover + session manager + IPC server are mutually dependent and cannot be sub-split without leaving a non-building package or an unguarded IPC. Justified atomic exception, flagged per rules. The phone APP that produces real proofs is a later client milestone; M2 ships ONLY the verification side + a mock prover. -->

## Assumptions
- The broker is a **Swift** component (Secure Enclave / `SecKeyCreateRandomKey` + `kSecAttrTokenIDSecureEnclave` + `SecKeyCreateEncryptedData`/`SecKeyCreateDecryptedData` are Apple-only APIs; Python cannot reach the SE). It is built as a SwiftPM executable package at `/Users/artemis-build/artemis/swift/ArtemisBroker/`. → impact: Stop (language + SE API access is non-negotiable per ADR-005; a Python broker cannot satisfy the wall).
- The broker runs as a **LaunchAgent in the owner-runtime user's login session** (SE data-protection-keychain items only work in a user login context, NOT a LaunchDaemon — ADR-005 decisive constraint). The launchd plist + owner auto-login are added in **M2-c**, not here. → impact: Stop (if run as a daemon, SE unwrap fails at runtime).
- The brain (Python) is the IPC **client**, built in **M2-c**. M2-a ships only the broker **server** + a Swift test harness that exercises the IPC + a mock prover. → impact: Caution (the wire protocol defined here is the contract M2-c consumes; both must match).
- `.userPresence` is the chosen `SecAccessControl` flag on the Mini-side SE key (no local biometric exists; the real biometric is enforced on the phone). → impact: Stop. This is a documented build-time spike (ADR-005): on a Mini with no Touch ID, `.userPresence` MUST NOT silently degrade to "unlocked at login". Verified only on-hardware (gated Task 9). Fallback if `.userPresence` degrades on-hardware: gate unwrap SOLELY on a verified phone proof with the SE key created WITHOUT a presence requirement (phone assertion = sole human factor); code shape identical (the proof gate already wraps every unwrap) — only the `SecAccessControl` flags change. Whether degradation occurs is the GATED on-hardware check (Task 9); must NOT silently degrade to login-unlock.
- The DEK is a 32-byte random key per scope; the broker holds it only transiently during wrap/unwrap and zeroizes its own buffer immediately after handing ciphertext (wrap) or after delivering it to the brain over IPC (unwrap). The brain's long-lived mlock'd hold is M2-c's concern. → impact: Stop (broker must never persist or log a plaintext DEK).
- On a verified unlock the broker also MOUNTS the per-scope APFS encrypted volume (ADR-007) at `scope_dir(scope)/vault/` = `/opt/artemis/<slot>/<scope>/vault/` (Decision D4: this volume holds **LanceDB ONLY** — NOT the SQLCipher stores; SQLCipher DBs live directly at `scope_dir(scope)/` and are encrypted by SQLCipher with the owner-gated DEK; no double-encryption layer on SQLite). Mount attempted only after a fresh proof verifies and before the DEK is returned; on session lock/idle/process-exit the broker UNMOUNTS the volume (close any open LanceDB handles before unmounting to avoid in-use errors). The volume key is a separate SE-wrapped key (same `.userPresence` policy as the DEK). M3 consumes the mounted path. → impact: Stop (M3 cannot open the LanceDB index unless the broker mounts here; the mount-point path `scope_dir/vault/` is a frozen contract for M3-a — Seam 10).
- "Fresh phone assertion" = a server(broker)-issued nonce + the phone's signature over (nonce ‖ context) + a strictly-increasing per-device counter. The concrete signer is swappable (App Attest OR an SE-backed signing keypair registered at pairing) behind ONE `UnlockProofVerifier` protocol; M2 ships the **SE-backed-signing-keypair** verifier as the concrete default (no Apple-server dependency) plus the protocol seam for App Attest. → impact: Caution. M2 ships the SE-backed-signing-keypair verifier as the concrete `UnlockProofVerifier`; App Attest is the documented alternative behind the same protocol (a separate gated spike). Fully testable, no Apple-server dependency.
- Pairing (registering the phone's public key + initial counter with the broker) is represented in M2 by a `pair` IPC/CLI command that stores a provided public key; the real pairing UX (QR/handshake from the phone app) is a later client milestone. → impact: Low (the registration store + verification are real; only the human pairing flow is deferred).

Simplicity check: considered writing the broker in Python via PyObjC to reach `Security.framework` — rejected: the SE keychain access-control + ECIES path is fragile through PyObjC and ADR-005 wants the SMALLEST auditable trusted base; a tiny Swift executable is the minimal, idiomatic, audit-friendly form. Considered XPC instead of a Unix domain socket for IPC — XPC is the macOS-idiomatic choice but couples the Python client to a harder-to-call transport; a Unix domain socket with `SO_PEERCRED`/`LOCAL_PEERPID` peer-credential + code-signing checks is simpler to consume from Python while still satisfying ADR-005's "peer-credential + code-signing checked". Documented as the M2 choice; XPC remains a swappable transport behind the same message contract.

## Prerequisites
- Specs that must be complete first: **M0-a** (the `/Users/artemis-build/artemis` repo root + the per-scope data-dir layout, esp. `<slot>/<scope>/keys/` where wrapped-DEK ciphertext lands), **M0-d** (`Scope`/`PersonId` domain vocabulary — mirrored, not imported, into Swift). Soft: **M0-b** (the launchd render mechanism M2-c extends for the broker plist).
- Environment setup required: Swift 6 toolchain (Xcode CLT) on the Mac Mini. The crypto/IPC LOGIC is unit-testable on any Apple Silicon mac with the toolchain, BUT real Secure-Enclave key generation + `.userPresence` semantics are **GATED on-hardware** (see Task 9).

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| /Users/artemis-build/artemis/swift/ArtemisBroker/Package.swift | create | SwiftPM executable package `artemis-broker` + a test target |
| /Users/artemis-build/artemis/swift/ArtemisBroker/Sources/ArtemisBroker/SecureEnclaveKeyStore.swift | create | SE key gen (`.userPresence`), ECIES wrap/unwrap of a 32-byte DEK + the per-scope volume-mount key |
| /Users/artemis-build/artemis/swift/ArtemisBroker/Sources/ArtemisBroker/DEKStore.swift | create | per-scope wrapped-DEK ciphertext on disk under `<slot>/<scope>/keys/` |
| /Users/artemis-build/artemis/swift/ArtemisBroker/Sources/ArtemisBroker/UnlockProof.swift | create | `UnlockProofVerifier` protocol + nonce issue + counter store + SE-signed-keypair verifier + `MockProver` |
| /Users/artemis-build/artemis/swift/ArtemisBroker/Sources/ArtemisBroker/Session.swift | create | session lifetime, idle timer, explicit lock, zeroization of held key material |
| /Users/artemis-build/artemis/swift/ArtemisBroker/Sources/ArtemisBroker/IPCServer.swift | create | Unix-domain-socket server; peer-cred + code-signing check; message dispatch |
| /Users/artemis-build/artemis/swift/ArtemisBroker/Sources/ArtemisBroker/VolumeMount.swift | create | mount/unmount the per-scope encrypted volume at /opt/artemis/<slot>/<scope>/vault/ on verified unlock / lock |
| /Users/artemis-build/artemis/swift/ArtemisBroker/Sources/ArtemisBroker/Protocol.swift | create | the wire message types (Codable) shared as the brain↔broker contract |
| /Users/artemis-build/artemis/swift/ArtemisBroker/Sources/ArtemisBroker/main.swift | create | entry point: parse args (`serve` / `provision-scope` / `pair`), wire the components |
| /Users/artemis-build/artemis/swift/ArtemisBroker/Tests/ArtemisBrokerTests/BrokerTests.swift | create | unit + integration tests using `MockProver` over an in-process socket pair |
| /Users/artemis-build/artemis/docs/technical/protocol/broker-ipc.md | create | the frozen IPC message contract (consumed by M2-c's Python client) |

## Tasks
- [ ] Task 1: Scaffold the SwiftPM package — files: `/Users/artemis-build/artemis/swift/ArtemisBroker/Package.swift` — `swift-tools-version: 6.0`; one executable target `artemis-broker` (path `Sources/ArtemisBroker`) and one test target `ArtemisBrokerTests`; macOS platform `.macOS(.v26)` (or the highest the toolchain accepts — document if `.v15`/`.v14` is the SDK ceiling); enable strict concurrency. No external dependencies (use only `Security`, `CryptoKit`, `Foundation`). — done when: `swift build` (run in `swift/ArtemisBroker/`) succeeds with an empty `main.swift` stub.

- [ ] Task 2: Implement the Secure-Enclave key store — files: `/Users/artemis-build/artemis/swift/ArtemisBroker/Sources/ArtemisBroker/SecureEnclaveKeyStore.swift` — `struct SecureEnclaveKeyStore`:
  - `func wrappingKey(forScope scope: String, create: Bool, proofRequired: Bool = true) throws -> SecKey` — looks up (or, if `create`, generates) a per-scope SE key via `SecKeyCreateRandomKey` with `kSecAttrTokenIDSecureEnclave`, `kSecAttrKeyTypeECSECPrimeRandom`, a `SecAccessControl` built with `SecAccessControlCreateWithFlags(...)`: when `proofRequired == true` (the default) include `.privateKeyUsage + .userPresence`; when `proofRequired == false` build the access-control WITHOUT `.userPresence` (boot-unwrappable — scoped to the `proactive` corpus ONLY, per ADR-006). `kSecUseDataProtectionKeychain = true`, and an application tag `com.artemis.broker.scope.<scope>`. Non-exportable; stored in the data-protection keychain.
  - `func wrap(dek: Data, forScope scope: String) throws -> Data` — `SecKeyCreateEncryptedData(pubKey, .eciesEncryptionStandardX963SHA256AESGCM, dek)`; returns ciphertext. Zeroize no plaintext here (caller owns the `dek` buffer; document that the caller zeroizes).
  - `func unwrap(ciphertext: Data, forScope scope: String) throws -> Data` — `SecKeyCreateDecryptedData(privKey, .eciesEncryptionStandardX963SHA256AESGCM, ciphertext)`; the SE access-control prompt fires here (gated on `.userPresence`). Returns the 32-byte DEK.
  - Wrap every Security.framework call's `CFError` out-param into a thrown typed `BrokerError`. — done when: `swift build` passes; a unit test that runs ONLY when an env flag `ARTEMIS_SE_AVAILABLE=1` is set exercises gen/wrap/unwrap round-trip (skipped in CI/off-hardware — the real SE path is Task 9).

- [ ] Task 3: Implement the per-scope DEK ciphertext store — files: `/Users/artemis-build/artemis/swift/ArtemisBroker/Sources/ArtemisBroker/DEKStore.swift` — `struct DEKStore` constructed with a data-root + slot. `func storedCiphertextPath(scope: String) -> URL` = `<dataRoot>/<slot>/<scope>/keys/dek.wrapped` (mirrors M0-a `paths.scope_dir(...)/keys`). `func hasWrappedDEK(scope:) -> Bool`. `func saveWrapped(_ ciphertext: Data, scope:)` writes atomically with file perms `0600`. `func loadWrapped(scope:) throws -> Data`. NEVER stores a plaintext DEK; the file holds ONLY ECIES ciphertext. `func provisionScope(scope:, keyStore: SecureEnclaveKeyStore) throws` — generate a fresh 32-byte DEK (`SecRandomCopyBytes`), wrap it via `keyStore.wrap`, persist ciphertext, then zeroize the plaintext DEK buffer (`withUnsafeMutableBytes { memset_s(...) }`). — done when: `swift build` passes; an off-hardware test (mock keyStore returning identity-ciphertext) confirms `provisionScope` writes a `0600` `dek.wrapped` and that no plaintext is written.

- [ ] Task 4: Implement the UnlockProof verification interface + nonce/counter + SE-signed-keypair verifier + mock prover — files: `/Users/artemis-build/artemis/swift/ArtemisBroker/Sources/ArtemisBroker/UnlockProof.swift` —
  - `protocol UnlockProofVerifier { func issueNonce(forScope: String) -> Data; func verify(_ proof: UnlockProof, expectedScope: String) throws -> Bool }` (the ONE swappable mechanism seam).
  - `struct UnlockProof: Codable { let scope: String; let nonce: Data; let counter: UInt64; let signature: Data; let deviceId: String }`.
  - A `NonceStore` that issues random 32-byte nonces with a short TTL and consumes-on-verify (single use; replay block #1).
  - A `CounterStore` persisting the last-seen counter per `deviceId`; `verify` REQUIRES `proof.counter > lastSeen` then advances it (strictly-increasing; replay/rollback block #2).
  - A `RegisteredDeviceStore` mapping `deviceId → publicKey` (set by `pair`).
  - `struct SignedKeypairVerifier: UnlockProofVerifier` — verifies `proof.signature` over `nonce ‖ scope ‖ counter` against the registered device public key (P-256, `SecKeyVerifySignature` / CryptoKit `P256.Signing`); enforces nonce-was-issued-and-unconsumed + counter strictly increasing.
  - `struct MockProver` (TEST HARNESS) — holds a P-256 private key; `func prove(scope:, nonce:, counter:) -> UnlockProof` producing a VALID signed assertion the `SignedKeypairVerifier` accepts; expose its public key for registration. Mark the type with a doc comment: "TEST HARNESS — stands in for the iPhone app (built at the client milestone); never ships in a release build path."
  — done when: `swift build` passes; tests show (a) a `MockProver` proof verifies true, (b) a replayed nonce fails, (c) a non-increasing counter fails, (d) a tampered signature fails.

- [ ] Task 5: Implement the session manager + zeroization — files: `/Users/artemis-build/artemis/swift/ArtemisBroker/Sources/ArtemisBroker/Session.swift` — `actor SessionManager`: tracks per-scope unlocked state with an `idleTimeout` (default 600s, config) + a `lastActivity` timestamp; `func isUnlocked(scope:) -> Bool` (false once idle-expired); `func markUnlocked(scope:)`; `func touch(scope:)` (resets idle on activity); `func lock(scope:)` and `func lockAll()` (explicit lock). The broker holds NO plaintext DEK across the IPC boundary — it unwraps on demand per `getDEK` request only after a fresh proof; the session state gates whether a *new* proof is required vs the current window is still valid. On `lockAll` / process exit, zeroize any transient buffers. Document: "session-only; the brain restart / idle / explicit lock all force a re-proof; the brain holds the mlock'd copy (M2-c) and is responsible for zeroizing on its side." — done when: `swift build` passes; a test advancing a fake clock past `idleTimeout` flips `isUnlocked` to false and forces the next `getDEK` to demand a fresh proof.

- [ ] Task 6: Define the wire protocol + the IPC server — files: `/Users/artemis-build/artemis/swift/ArtemisBroker/Sources/ArtemisBroker/Protocol.swift`, `/Users/artemis-build/artemis/swift/ArtemisBroker/Sources/ArtemisBroker/IPCServer.swift` —
  - Protocol.swift: `Codable` request/response enums framed as length-prefixed JSON (4-byte big-endian length + UTF-8 JSON body). Requests: `requestNonce(scope)`, `getDEK(scope, proof: UnlockProof)`, `lock(scope)`, `status`. Responses: `nonce(Data)`, `dek(Data)` (the 32-byte DEK, delivered ONCE per call), `ok`, `error(code, message)`. Document that `dek` is returned only after a valid fresh proof AND that the brain must mlock + zeroize it.
  - IPCServer.swift: a Unix-domain-socket server bound to `<dataRoot>/<slot>/run/broker.sock` (dir `0700`, socket `0600`); on each connection, BEFORE dispatch, enforce: (1) peer-credential check via `getsockopt(LOCAL_PEERPID)` / `getpeereid` — the connecting uid MUST equal the broker's own uid (same owner-runtime user; rejects the build-agent user and any other account); (2) code-signing identity check on the peer PID via `SecCodeCreateWithPID` + `SecCodeCheckValidity` against the brain's expected requirement (Team ID / designated requirement) — reject mismatches. Dispatch verified requests to the SE/DEK/Session components. Never write a DEK to a log; log only request types + decisions. — done when: `swift build` passes; a test connects over an in-process socket pair, completes `requestNonce`→`getDEK(MockProver proof)` and receives a 32-byte `dek`, and a request from a simulated wrong-uid peer is rejected. Code-signing requirement: the build-agent user runs an unsigned `uv run python` during dev. For dev/UAT, gate the code-signing check behind a config flag (peer-uid check still enforced); for PROD require a signed brain launcher. The PROD signing identity is confirmed at the client/packaging milestone; M2 ships the check with a documented dev bypass flag `ARTEMIS_BROKER_SKIP_CODESIGN=1`.

- [ ] Task 7: Wire the entry point + sub-commands — files: `/Users/artemis-build/artemis/swift/ArtemisBroker/Sources/ArtemisBroker/main.swift` — parse argv: `serve` (start the IPC server loop, reading data-root/slot from env `ARTEMIS_DATA_ROOT`/`ARTEMIS_SLOT`), `provision-scope --scope <s> [--no-proof]` (generate SE key + wrapped DEK for a scope — used by M2-b/M2-c provisioning; `--no-proof` sets `proof_required=false` → the boot-unwrappable SE key policy, for the `proactive` scope ONLY per ADR-006), `pair --device-id <id> --pubkey <base64>` (register a phone public key + reset its counter). All commands resolve paths the same way M0-a does. — done when: `swift build` passes; `swift run artemis-broker provision-scope --scope owner-private` runs against a temp data-root and writes a `dek.wrapped` (using a mock/off-hardware SE shim when `ARTEMIS_SE_AVAILABLE` is unset, so it is verifiable off-hardware), and `swift run artemis-broker pair --device-id test --pubkey <b64>` records the device.

- [ ] Task 8: Write the broker test suite — files: `/Users/artemis-build/artemis/swift/ArtemisBroker/Tests/ArtemisBrokerTests/BrokerTests.swift` — XCTest (or swift-testing) covering: DEKStore round-trip + `0600` perms + no-plaintext; UnlockProof happy path + the 3 replay/tamper failures (Task 4); Session idle expiry forces re-proof (Task 5); end-to-end over an in-process socket pair: `requestNonce → MockProver.prove → getDEK → 32-byte dek`; peer-uid rejection. SE round-trip test guarded by `ARTEMIS_SE_AVAILABLE=1` (skipped off-hardware). — done when: `swift test` passes off-hardware (SE-guarded test skipped).

- [ ] Task 9 (GATED — on-hardware, build-time spike): Verify Secure-Enclave `.userPresence` semantics on the Mini — files: (no new files; runs Task 2/Task 8 SE-guarded paths) — on the Mac Mini only, with `ARTEMIS_SE_AVAILABLE=1`: generate a real per-scope SE key with `.userPresence`, wrap a DEK, then **power-relevant check**: confirm that `unwrap` does NOT succeed merely because the owner is logged in (i.e. `.userPresence` does not silently degrade to "unlocked at login" on the no-Touch-ID Mini). If it DOES degrade, switch to the proof-gated fallback described in the Assumptions (`.userPresence` degradation). Mark build-time empirical (ADR-005 spike). — done when: on the Mini, the SE round-trip works AND the degradation question is answered + recorded in `docs/handoff/`; the real encrypted-volume attach/detach at /opt/artemis/<slot>/<scope>/vault/ succeeds and survives a lock/unlock cycle (ADR-007 mount-lifecycle spike).

- [ ] Task 10: Implement the per-scope encrypted-volume mount/unmount — files: `/Users/artemis-build/artemis/swift/ArtemisBroker/Sources/ArtemisBroker/VolumeMount.swift` — `struct VolumeMount`: `mountPoint(scope:) -> URL` = `scope_dir(scope)/vault/` = `/opt/artemis/<slot>/<scope>/vault/` (Decision D4: this volume holds **LanceDB ONLY** — SQLCipher DBs are NOT on this volume; they live directly at `scope_dir(scope)/`); `mount(scope:) throws` attaches the scope's APFS encrypted volume/sparsebundle (key SE-unwrapped, same `.userPresence` policy) at that mount point; `unmount(scope:) throws` — MUST close any LanceDB handles for this scope before unmounting (enforce this by calling a registered `onBeforeUnmount(scope:)` callback, wired to the LanceDB handle manager at the composition root); `isMounted(scope:) -> Bool`. Wire into the broker: `getDEK` mounts on a successful proof BEFORE returning the DEK; `lock`/idle/`lockAll`/process-exit call `unmount` (LanceDB-handle-close callback fires first). The concrete attach mechanism (hdiutil sparsebundle vs `diskutil apfs` encrypted volume) is the ADR-007 mount-lifecycle build-time spike → the real attach is GATED on-hardware (folded into the gated Task 9). Off-hardware the mount is a verifiable no-op shim recording mount/unmount calls. — done when: `swift build` passes; an off-hardware test asserts `getDEK` triggers `mount(scope)` before returning the DEK and `lock` triggers `unmount(scope)` after the pre-unmount callback; real attach gated on-hardware (Task 9).

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | /Users/artemis-build/artemis/swift/ArtemisBroker/Package.swift, /Users/artemis-build/artemis/swift/ArtemisBroker/Sources/ArtemisBroker/*.swift, /Users/artemis-build/artemis/swift/ArtemisBroker/Tests/ArtemisBrokerTests/BrokerTests.swift, /Users/artemis-build/artemis/docs/technical/protocol/broker-ipc.md |
| Modify | (none) |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `swift build` (in swift/ArtemisBroker) | Compile the broker |
| `swift test` (in swift/ArtemisBroker) | Run the broker test suite (SE-guarded tests skipped off-hardware) |
| `swift run artemis-broker provision-scope --scope owner-private` | Provision a scope's wrapped DEK (off-hardware via SE shim) |
| `swift run artemis-broker pair --device-id <id> --pubkey <b64>` | Register a phone public key |
| `ARTEMIS_SE_AVAILABLE=1 swift test` (GATED, on-Mini) | Real Secure-Enclave round-trip |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | swift/ArtemisBroker/**, docs/technical/protocol/broker-ipc.md |
| `git commit` | "feat: M2-a key-broker LaunchAgent — SE wrap/unwrap, per-scope DEK store, UnlockProof + mock prover, session, IPC" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_DATA_ROOT` | Root of the per-slot/per-scope data tree (keys/, run/) |
| `ARTEMIS_SLOT` | Which slot the broker serves |
| `ARTEMIS_SE_AVAILABLE` | Gate the real-Secure-Enclave path (set only on the Mini) |
| `ARTEMIS_BROKER_SKIP_CODESIGN` | Dev-only bypass of the peer code-signing check (peer-uid still enforced) |

### Network
| Action | Purpose |
|--------|---------|
| (none) | No outbound; IPC is a local Unix domain socket only |

## Specialist Context
### Security
This spec is the heart of the crypto wall (ADR-005). Hard invariants the build MUST honour: the broker is the ONLY process touching the SE key; the plaintext DEK is never written to disk, never logged, and is zeroized in the broker immediately after use; every `getDEK` requires a fresh, single-use nonce + strictly-increasing counter + valid signature (replay/rollback blocked); the IPC socket enforces peer-uid (rejects the build-agent user) + code-signing (PROD). The `MockProver` is a TEST HARNESS only and must be excluded from any release/serve path. [HARD FLAG for the apex-security gate (M2-d): this spec is the primary subject of ADR-005's "prompt-injected tool exfiltrating the DEK" core risk and the `.userPresence` residual risk — both reviewed before M3/M4.]

### Performance
SE unwrap fires a per-`getDEK` enclave op; the session window (idle timeout) means one proof covers a session, so steady-state brain reads do NOT re-hit the enclave (the brain caches the mlock'd DEK — M2-c). Keep the IPC server single-purpose and non-blocking.

### Accessibility
(none — headless agent, no UI)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | all Sources/ArtemisBroker/*.swift | Doc-comment every public type/func; flag `MockProver` as test-only |
| Protocol | docs/technical/protocol/broker-ipc.md | Write the frozen length-prefixed-JSON message contract (the M2-c client implements it) |

## Acceptance Criteria
- [ ] Run `swift build` in `swift/ArtemisBroker` → verify: exit 0.
- [ ] Run `swift test` in `swift/ArtemisBroker` → verify: all off-hardware tests pass (SE-guarded test reported skipped).
- [ ] Run `swift run artemis-broker provision-scope --scope owner-private` against a temp `ARTEMIS_DATA_ROOT` → verify: a `dek.wrapped` file exists under `<root>/<slot>/owner-private/keys/` with perms `0600` and contains no ASCII-readable 32-byte plaintext.
- [ ] Run the end-to-end IPC test → verify: `requestNonce` → `MockProver.prove` → `getDEK` returns a 32-byte `dek`; a replayed nonce and a non-increasing counter both yield `error`.
- [ ] Run the peer-uid rejection test → verify: a connection from a simulated non-broker uid is refused before dispatch.
- [ ] Run the volume-mount test → verify: a verified `getDEK` invokes `mount(scope)` before returning the DEK; `lock` invokes `unmount(scope)` (real attach gated on-hardware).
- [ ] (GATED, on Mini) `ARTEMIS_SE_AVAILABLE=1 swift test` → verify: real SE gen/wrap/unwrap round-trips AND the `.userPresence`-does-not-degrade question is answered + recorded in handoff; the real encrypted-volume attach/detach survives a lock/unlock cycle.

## Progress
_(Coding mode writes here — do not edit manually)_
