---
spec: client-broker-pair-ipc
status: ready
token_profile: balanced
autonomy_level: L2
---

# Spec: CLIENT-broker — Broker `pair` IPC verb (network-driven device registration over the peer-cred-checked socket)

**Identity:** Adds a `pair` operation to the ArtemisBroker's Unix-socket IPC so the brain can register a phone's public key over the existing peer-credential + code-signing-checked channel (today pairing is CLI-only). The verb reuses M2-a's `RegisteredDeviceStore`; no new crypto, no new trust surface.
→ why: see docs/technical/adr/ADR-010-client-app-auth.md §1 (pairing registers the key in BOTH the broker and the brain app-auth registry; the brain relays over the broker IPC) · docs/technical/adr/ADR-005-owner-key-broker.md (the broker is the SE/registration authority).

<!-- Split rule: ONE logical phase (expose the existing RegisteredDeviceStore.register over the IPC dispatch), additive, 3 Swift edits + 1 protocol-doc edit, all small. Isolated cleanly from the Python specs (CLIENT-a/b) and the new ArtemisApp package (CLIENT-c/d) because it touches ONLY the M2-a ArtemisBroker package. Consumes M2-a (IPCServer, RegisteredDeviceStore, main.swift wiring, BrokerTests). -->

## Assumptions
- M2-a is complete: the `ArtemisBroker` SwiftPM package builds; `IPCServer.swift` runs the length-prefixed-JSON Unix-socket server with the **peer-uid + code-signing** checks before dispatch; `RegisteredDeviceStore` maps `deviceId → publicKey (+ counter)` with a `register(deviceId:publicKey:)`-style method (set today by the CLI `pair` sub-command in `main.swift`); `UnlockProof.swift` holds the store + `SignedKeypairVerifier`; `BrokerTests.swift` covers the IPC round-trip over an in-process socket pair with `MockProver`. → impact: Stop (this spec extends those exact symbols; if the register signature differs, match it).
- The IPC wire contract is length-prefixed (4-byte big-endian) UTF-8 JSON, one `op` per request, frozen in `docs/technical/protocol/broker-ipc.md` (created by M2-a). → impact: Stop (the new `pair` op follows the same frame + error shape).
- The phone public key is an **X9.63 uncompressed point, base64** — exactly what the CLI `pair --pubkey <base64>` already accepts and what the brain registry stores (CLIENT-a). The IPC `pair` verb accepts the same base64 and calls the same store path the CLI uses. → impact: Stop (one key encoding across CLI pair, IPC pair, brain registry, and the Swift app export).
- The verb needs no extra authorization beyond the existing IPC guards: the **same-uid peer-credential check** already restricts callers to the brain (same owner-runtime user); a build-agent or other account is rejected before dispatch. The owner-authorisation of a pairing is enforced one layer up by the brain's pairing **code** (CLIENT-b), not in the broker. → impact: Caution (documented: the broker trusts its same-uid IPC peer; pairing-intent authorisation is the brain's pairing-code job).

Simplicity check: considered a separate "pairing service" — rejected; registration is a one-line reuse of the existing `RegisteredDeviceStore` over the channel that already exists. Considered having the brain shell out to `artemis-broker pair` — rejected (ADR-005: the broker is reached only via the guarded IPC, never by spawning its CLI from the brain daemon). Considered re-verifying owner intent in the broker — rejected; the brain's single-use pairing code is the intent gate, and the broker's same-uid check is its trust boundary.

## Prerequisites
- Specs that must be complete first: M2-a (the broker package + IPC + RegisteredDeviceStore + tests).
- Environment setup required: Swift 6 toolchain (Xcode CLT) — already required by M2-a. Fully off-hardware testable (in-process socket pair, no Secure Enclave needed for the pair path — it only writes the public-key store).

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| /Users/artemis-build/artemis/swift/ArtemisBroker/Sources/ArtemisBroker/IPCServer.swift | modify | add a `pair` case to the request dispatch (calls an injected pairing handler) |
| /Users/artemis-build/artemis/swift/ArtemisBroker/Sources/ArtemisBroker/main.swift | modify | inject a `pair` handler into the `IPCServer` that calls `RegisteredDeviceStore.register(...)` |
| /Users/artemis-build/artemis/swift/ArtemisBroker/Tests/ArtemisBrokerTests/BrokerTests.swift | modify | add an IPC `pair` round-trip test over the in-process socket pair |
| /Users/artemis-build/artemis/docs/technical/protocol/broker-ipc.md | modify | document the `pair` op (request/response/error) in the frozen contract |

## Tasks
- [ ] Task 1: Add the `pair` dispatch to the IPC server — files: `/Users/artemis-build/artemis/swift/ArtemisBroker/Sources/ArtemisBroker/IPCServer.swift` — the `IPCServer` gains a stored closure `pairHandler: (_ deviceId: String, _ publicKeyB64: String) throws -> Void` (injected at construction). In the request dispatch (after the existing peer-uid + code-signing guards, alongside `requestNonce`/`getDEK`/`lock`/`status`), add a case for `op == "pair"`: decode JSON `device_id` into a local `deviceId: String` and JSON `public_key` into a local `publicKeyB64: String`; call `try pairHandler(deviceId, publicKeyB64)`; respond `{"ok": true}`; on a thrown error respond the standard `{"error": {"code": "...", "message": "..."}}` frame (same error shape as the other ops). Never log the public key bytes beyond a redacted device-id + decision (consistent with M2-a's "log only request types + decisions"). — done when: `swift build` passes; the dispatch handles a `pair` frame and returns `{"ok": true}` (Task 3 test).

- [ ] Task 2: Inject the pairing handler in main — files: `/Users/artemis-build/artemis/swift/ArtemisBroker/Sources/ArtemisBroker/main.swift` — where the `serve` command constructs the `IPCServer` (M2-a Task 7), pass a `pairHandler` closure that calls the SAME `RegisteredDeviceStore.register(deviceId:publicKey:)` path the CLI `pair` sub-command uses (decode the base64 X9.63 point → register + reset that device's counter). Reuse the existing store instance the verifier holds (one source of truth — do NOT create a second store). The CLI `pair` sub-command is unchanged. — done when: `swift build` passes; `serve` wires a non-nil `pairHandler` into the `IPCServer`.

- [ ] Task 3: Test the `pair` IPC round-trip — files: `/Users/artemis-build/artemis/swift/ArtemisBroker/Tests/ArtemisBrokerTests/BrokerTests.swift` — add a test: over the in-process socket pair (the existing M2-a test harness), send a `{"op":"pair","device_id":"phone-1","public_key":"<MockProver pubkey b64>"}` frame; assert the response is `{"ok": true}` and that the `RegisteredDeviceStore` now resolves `phone-1` to that public key; then assert a subsequent `requestNonce`→`getDEK` using a `MockProver` bound to that same key succeeds (proves the IPC-paired key is usable for a real unlock, end-to-end). Also assert a malformed `pair` frame (missing `public_key`) returns an `error` frame, not a crash. — done when: `swift test` passes off-hardware (no SE needed for the pair path; the SE-guarded unlock test stays `ARTEMIS_SE_AVAILABLE`-gated as in M2-a).

- [ ] Task 4: Document the `pair` op in the IPC contract — files: `/Users/artemis-build/artemis/docs/technical/protocol/broker-ipc.md` — append a `pair` section: request `{"op":"pair","device_id":<string>,"public_key":<base64 X9.63 point>}`; success `{"ok":true}`; error `{"error":{"code","message"}}`; note it is same-uid-peer-guarded and that owner-intent authorisation is enforced by the brain's pairing code (CLIENT-b), not the broker. — done when: the `pair` op is present in `broker-ipc.md` with request/response/error shapes.

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | (none) |
| Modify | /Users/artemis-build/artemis/swift/ArtemisBroker/Sources/ArtemisBroker/IPCServer.swift, /Users/artemis-build/artemis/swift/ArtemisBroker/Sources/ArtemisBroker/main.swift, /Users/artemis-build/artemis/swift/ArtemisBroker/Tests/ArtemisBrokerTests/BrokerTests.swift, /Users/artemis-build/artemis/docs/technical/protocol/broker-ipc.md |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `swift build --package-path swift/ArtemisBroker` | Build gate |
| `swift test --package-path swift/ArtemisBroker` | Test gate (pair IPC round-trip; SE-guarded test skipped off-hardware) |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | swift/ArtemisBroker/Sources/ArtemisBroker/IPCServer.swift, swift/ArtemisBroker/Sources/ArtemisBroker/main.swift, swift/ArtemisBroker/Tests/ArtemisBrokerTests/BrokerTests.swift, docs/technical/protocol/broker-ipc.md |
| `git commit` | "feat: CLIENT-broker pair IPC verb (network-driven device registration over the broker socket)" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_DATA_ROOT` | Broker socket + RegisteredDeviceStore path (as M2-a) |
| `ARTEMIS_SLOT` | Slot selection (as M2-a) |

### Network
| Action | Purpose |
|--------|---------|
| (none) | Broker IPC is a local Unix socket; the `pair` verb adds no network |

## Specialist Context
### Security
The `pair` verb adds **no new trust surface**: it is dispatched only AFTER the existing same-uid peer-credential + code-signing checks, so only the brain (same owner-runtime user) can call it; it writes ONLY a public key into the existing `RegisteredDeviceStore`; it touches no SE key, no DEK, no volume. Owner-intent for a pairing is gated one layer up by the brain's single-use pairing code (CLIENT-b) — the broker deliberately trusts its same-uid IPC peer (its established trust boundary, ADR-005). The handler logs a redacted device-id + decision only, never raw key bytes. [FLAG apex-security: confirm the `pair` dispatch sits AFTER the peer-cred/code-sign guards and writes only to the one existing store; confirm a re-pair resets the counter (prevents a stale-counter replay against a re-registered device).]

### Performance
(none — a single store write per pairing, a rare owner-initiated event.)

### Accessibility
(none — broker IPC; no UI.)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | swift/ArtemisBroker/Sources/ArtemisBroker/IPCServer.swift, main.swift | Document the `pair` op handler + the same-uid trust note |
| Protocol | docs/technical/protocol/broker-ipc.md | Add the `pair` op to the frozen IPC contract |

## Acceptance Criteria
- [ ] Run `swift build --package-path swift/ArtemisBroker` → verify: exit 0.
- [ ] Run `swift test --package-path swift/ArtemisBroker` → verify: the `pair` IPC round-trip registers the key and a subsequent `MockProver` unlock with that key succeeds; a malformed `pair` frame returns an `error` (no crash); the SE-guarded test is skipped off-hardware.
- [ ] Inspect `docs/technical/protocol/broker-ipc.md` → verify: a `pair` op section exists with request/response/error shapes.

## Progress
_(Coding mode writes here — do not edit manually)_
