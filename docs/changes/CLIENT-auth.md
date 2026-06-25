---
spec: client-auth
status: ready
token_profile: balanced
autonomy_level: L2
cross_model_review: true
---

# Spec: CLIENT-auth — device-key signer plugin + pairing/connect/unlock orchestration (ADR-025)

**Identity:** Builds the Tauri client's authentication layer — a `tauri-plugin-keystore` housing a hardware-backed, biometric-gated **P-256 device signing key** (Windows TPM/NCrypt now; macOS Secure Enclave gated) and the Rust-side **pairing → connect → unlock** orchestration that composes CLIENT-core's transport fns to authenticate the client to the brain. Implements ADR-025.
→ why: see docs/technical/adr/ADR-025-tauri-client-auth-wall-reroot.md (the auth design) · ADR-030 (auth runs entirely in Rust) · ADR-005 (recovery passphrase) · docs/technical/architecture/app-flow.md (pairing journey + lock states).

<!-- Split rule: flagged atomic exception (precedent: M2-a/CLIENT-c whole-package specs). CLIENT-auth is ONE cohesive security boundary — a signer plugin + the orchestration that drives it — that must compile + verify as a unit; the device key, the counter, the handshake, and the state-machine wiring are mutually dependent. The brain-side routes are CLIENT-a/b (Python); the visual lock chrome is CLIENT-world/screens. -->

## Assumptions
- **CLIENT-core is built first (ADR-030 + ADR-029 file overlap):** CLIENT-auth composes CLIENT-core's internal Rust transport fns (`pair`/`session_*`/`unlock_*`), stores the session token in CLIENT-core's `AppState`, and drives the `connection.ts` state machine. CLIENT-auth **modifies** `client/src-tauri/src/lib.rs`, `Cargo.toml`, `capabilities/default.json` (shared with CLIENT-core) → the two are NOT file-disjoint and MUST serialize (core first). → impact: Stop (build order; signatures must match CLIENT-core's transport fns).
- **The brain `SignedKeypairVerifier` (M2-a) + CLIENT-a/b verify DER-encoded P-256 ECDSA signatures** (Python `cryptography` default). The plugin normalizes every signature to **DER** at its boundary; the public key is exported as **X9.63 uncompressed point, base64** (`p256::PublicKey::to_encoded_point(false)`) — **NOT SPKI-DER** (the brain registry uses `from_encoded_point` and the M2-a broker `pair --pubkey` expects X9.63; SPKI-DER would break both — confirmed by the CLIENT-a/b amendment review). → impact: Stop (a signature/pubkey encoding mismatch fails every handshake — the ADR-025 conformance spike covers it).
- **Windows Hello `KeyCredentialManager` is RSA-only** (confirmed, agent-D) — the P-256 key uses **NCrypt + `MS_PLATFORM_CRYPTO_PROVIDER`** with `NCRYPT_UI_POLICY` for the biometric gate. → impact: Stop (do not use KeyCredentialManager).
- **The macOS Secure Enclave path is GATED** (no Apple hardware on the dev box) — it is written behind `#[cfg(target_os = "macos")]` as the ADR-025 SE design but compiled/verified only on a Mac. Dev builds + tests run the Windows path + a fake. → impact: Caution (mac tasks gated; Windows is the dev wall).
- **The live broker pairing/unlock relay is Mac-gated** — dev uses a fake broker (per CLIENT-b/broker, M2-c shim). The unlock orchestration is tested against the fake. → impact: Caution.
- **Windows MSVC toolchain** (`rustup default stable-msvc` + VS C++ Build Tools) is required — `windows-sys` will not link on GNU. → impact: Stop (the `dlltool` failure; `npm run tauri info` verifies — apex-tauri impl.md).

Simplicity check: considered an inline `#[tauri::command]` module instead of a plugin — rejected; the signer is a distinct security boundary that earns its own ACL namespace (apex-tauri plugin-vs-command rule) and a desktop/mobile split point later. Considered putting the orchestration in the plugin — rejected; pair/connect/unlock compose CLIENT-core's transport (the network owner per ADR-030), so the orchestration lives in `src-tauri/src/auth.rs` beside the gateway, and the plugin owns ONLY key custody + signing.

## Prerequisites
- Specs complete first: **CLIENT-core** (transport fns, `AppState`, `connection.ts`, capabilities/lib.rs scaffold). Sequenced-with: **CLIENT-a/b** (brain pairing-bootstrap + session + unlock-relay routes — dev tests use fakes; live handshake needs them) and **CLIENT-broker** (Mac-gated; dev fake).
- Environment: Rust **MSVC** toolchain, WebView2; `cargo` fetches `windows-sys`/`ecdsa`/`p256`/`spki`/`zeroize`/`argon2` on first build.
- **Supply-chain pre-step (before the first Cargo.toml edit):** verify each new crate (`windows-sys`, `ecdsa`, `p256`, `spki`, `zeroize`, `argon2`) against canonical crates.io — correct author org, active maintenance, not a typosquat — then commit `Cargo.lock` (`cargo audit` alone does not catch typosquats).

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| client/src-tauri/tauri-plugin-keystore/Cargo.toml | create | local plugin crate; deps: `tauri`, `serde`, `thiserror`, `zeroize`, `ecdsa`+`p256`(features `ecdsa`,`pem`)`, `spki`; **`[build-dependencies] tauri-plugin = { version = "2", features = ["build"] }`**; `[target.'cfg(windows)'.dependencies] windows-sys` (Win32_Security_Cryptography, Win32_Foundation); `[target.'cfg(target_os="macos")'.dependencies] security-framework`/`objc2-security`. **Pre-verify every new crate vs canonical crates.io (author org, maintenance, no typosquat) BEFORE adding; commit `Cargo.lock`.** |
| client/src-tauri/tauri-plugin-keystore/build.rs | create | `const COMMANDS: &[&str] = &["create_key","sign","get_public_key","destroy_key","has_key"]; tauri_plugin::Builder::new(COMMANDS).build();` |
| client/src-tauri/tauri-plugin-keystore/permissions/default.toml | create | `[default] permissions = ["allow-sign","allow-get-public-key","allow-has-key"]` (create/destroy require explicit grant) |
| client/src-tauri/tauri-plugin-keystore/src/lib.rs | create | `init()` → `tauri::plugin::Builder::new("keystore").invoke_handler(generate_handler![...]).setup(\|app, _api\| { app.manage(Mutex::new(platform_keystore())); Ok(()) }).build()`; `Keystore` trait; platform dispatch via `State<'_, Mutex<dyn Keystore>>` (NOT a hand-rolled `Arc` — Tauri wraps managed state). Module gating: `#[cfg(windows)] mod windows;` / `#[cfg(target_os="macos")] mod macos;` |
| client/src-tauri/tauri-plugin-keystore/src/commands.rs | create | `#[tauri::command]` create_key/sign/get_public_key/destroy_key/has_key; all `async`, return `Result<_, KeystoreError>` (serializable); NEVER return or log the private key |
| client/src-tauri/tauri-plugin-keystore/src/error.rs | create | `KeystoreError` (`thiserror` + `impl Serialize`) — the **IPC-facing** variants are a closed user enum `BiometricCancelled`/`HardwareUnavailable`/`KeyNotFound`/`Encoding`; the **raw NCrypt/SE numeric code is mapped here and kept INTERNAL** (tracing only, never serialized to the webview — anti-fingerprinting) |
| client/src-tauri/tauri-plugin-keystore/src/windows.rs | create | `#[cfg(windows)]` NCrypt/TPM impl: `NCryptOpenStorageProvider(MS_PLATFORM_CRYPTO_PROVIDER)` → `NCryptCreatePersistedKey(NCRYPT_ECDSA_P256_ALGORITHM)` → set `NCRYPT_UI_POLICY{ NCRYPT_UI_FORCE_HIGH_PROTECTION_FLAG }` **before** `NCryptFinalizeKey` → `NCryptSignHash(hKey, pPaddingInfo=NULL, pbHashValue=externally-computed SHA-256 digest, cbHashValue=32, dwFlags=0)` → exactly **64 bytes = two 32-byte big-endian scalars** `r‖s`; export pubkey `BCRYPT_ECCPUBLIC_BLOB`. Provider + key handles wrapped in a **RAII Drop guard calling `NCryptFreeObject`** (no handle leak). `unsafe` FFI isolated here |
| client/src-tauri/tauri-plugin-keystore/src/macos.rs | create (GATED) | `#[cfg(target_os="macos")]` SE: `SecKeyGeneratePair`(`kSecAttrTokenIDSecureEnclave`, EC 256, `SecAccessControl(privateKeyUsage|biometryAny)`) + `SecKeyCreateSignature(...X962SHA256)` (DER) via pre-evaluated `LAContext`. Compiled/verified on Mac only |
| client/src-tauri/tauri-plugin-keystore/src/sig.rs | create | `to_der(raw_rs: &[u8;64]) -> Vec<u8>` (Win) + identity (mac); `pubkey_to_x963(blob) -> Vec<u8>` (uncompressed point, `p256::PublicKey::to_encoded_point(false)` — NOT SPKI-DER); signature via `ecdsa::Signature::<NistP256>::from_bytes(..).to_der()` + `p256` (drop the `spki` crate) |
| client/src-tauri/tauri-plugin-keystore/src/counter.rs | create | monotonic per-device counter persisted to app-local data (`app_data_dir/keystore/counter`); `next() -> Result<u64,_>` = load→+1→**atomic persist (write temp → `fsync` → rename)**→return. **Crash-safe + FAIL-CLOSED:** a missing/corrupt counter file at startup → **abort the handshake (error), NEVER silent-reset to 0** (a 0-reset is a full replay hole). The only path that may reset is a fresh `create_key` that invalidates all prior proofs. Not secret |
| client/src-tauri/src/auth.rs | create | orchestration commands composing CLIENT-core transport + the keystore plugin: `auth_pair(pairing_code)`, `auth_connect()`, `auth_unlock()`, `auth_logout()`, **`auth_recover(passphrase: Zeroizing<String>)`**; **all signed messages use a fixed length-prefixed layout**: pair = `u16-len(code)‖code‖device_id`; connect/unlock proof = `u16-len(nonce)‖nonce‖u16-len(context)‖context‖counter(8-byte big-endian)` (exactly what the brain `SignedKeypairVerifier` reconstructs); store token in `AppState`; advance the counter per proof; map results to `connection.ts` transitions. `create_key`/`destroy_key` are invoked ONLY from here (Rust-internal), never from the webview |
| client/src-tauri/src/lib.rs | modify | `.plugin(tauri_plugin_keystore::init())`; register **all five** `auth_*` app commands (`auth_pair`/`auth_connect`/`auth_unlock`/`auth_logout`/`auth_recover`) in `invoke_handler!` |
| client/src-tauri/Cargo.toml | modify | add `tauri-plugin-keystore = { path = "tauri-plugin-keystore" }` + `argon2` (recovery KDF, client-entry) |
| client/src-tauri/capabilities/default.json | modify | `"windows": ["main"]` (NEVER `"*"`); add `"keystore:allow-sign"`, `"keystore:allow-get-public-key"`, `"keystore:allow-has-key"` + the **five** `auth_*` app command permissions (incl. `auth_recover`). **Do NOT add `keystore:allow-create-key` / `keystore:allow-destroy-key`** — those are Rust-internal only and must never be webview-reachable |
| client/src/auth/pairing.ts | create | TS flow: pairing-code entry → `invoke("auth_pair")` → `auth_connect` → drive `connection.ts`; idempotent/re-runnable; surfaces wrong/expired-code + off-tunnel errors (app-flow) |
| client/src/auth/recovery.ts | create | recovery-passphrase entry (ADR-005): collect passphrase → `invoke("auth_recover", {passphrase})` (relays to the broker escrow path); **clear the local passphrase ref immediately after `invoke` returns** (no lingering JS copy); client role = surfacing/entry only, never holds the DEK. Rust receives it as `Zeroizing<String>`, zeroized on drop |
| client/src-tauri/tauri-plugin-keystore/src/sig.rs (tests) · client/src-tauri/src/auth.rs (`#[cfg(test)]`) · client/src/auth/pairing.test.ts | create | sig DER round-trip vs a known P-256 vector; auth orchestration against a fake signer + fake transport (pair→connect→unlock→counter advance); TS pairing flow against mocked `invoke` |

## Tasks
- [ ] Task 1: Keystore plugin scaffold + ACL + error type — files: `client/src-tauri/tauri-plugin-keystore/{Cargo.toml,build.rs,permissions/default.toml,src/lib.rs,src/commands.rs,src/error.rs}` — generate the plugin crate (`Builder::new("keystore")`, COMMANDS const → autogen permissions, default.toml grants sign/get_public_key/has_key only); `commands.rs` declares the async command surface delegating to a `Keystore` trait (impl in Task 2/3); `KeystoreError` serializable, leaks no FFI text. — done when: `cargo fmt --check` exit 0 in the plugin crate; the crate compiles standalone with a stub backend (MSVC-gated → record); `build.rs` emits `permissions/autogenerated/`.
- [ ] Task 2: Windows NCrypt/TPM signer — files: `client/src-tauri/tauri-plugin-keystore/src/windows.rs` — implement the `Keystore` trait for Windows: create persisted P-256 key on `MS_PLATFORM_CRYPTO_PROVIDER` with `NCRYPT_UI_POLICY` (`NCRYPT_UI_FORCE_HIGH_PROTECTION_FLAG`) set **before** `NCryptFinalizeKey`; `sign(digest: &[u8;32])` signs the **externally-computed SHA-256 digest** with `NCryptSignHash(pPaddingInfo=NULL, dwFlags=0)` → exactly **64B** `r‖s` (two 32-byte BE scalars); export public key (`BCRYPT_ECCPUBLIC_BLOB`); `destroy_key`/`has_key`; provider/key handles freed via a **RAII Drop guard** (`NCryptFreeObject`); raw backend codes mapped to the closed `KeystoreError` enum (internal-log only); all `unsafe` confined here; the private key handle never leaves Rust. — done when: (MSVC-gated) `cargo clippy -- -D warnings` exit 0; a `#[cfg(windows)]` test creates→signs→verifies a key with the `p256` verifier (records the live-Hello-prompt path as the GATED spike, Task 7).
- [ ] Task 3: Signature/pubkey normalization + macOS SE (gated) — files: `client/src-tauri/tauri-plugin-keystore/src/sig.rs`, `client/src-tauri/tauri-plugin-keystore/src/macos.rs` — `sig.rs`: `to_der(raw r‖s)` via `ecdsa::Signature::<NistP256>` + `pubkey_to_spki_der` via `p256`/`spki`; the plugin returns **DER signatures + SPKI-DER pubkey** (the brain's pinned form). `macos.rs`: the SE `Keystore` impl behind `#[cfg(target_os="macos")]` (returns DER natively) — **compiled on Mac only**. — done when: `sig.rs` DER round-trip test passes against a known P-256 vector (a Windows-raw input → DER verifies); `macos.rs` is `#[cfg]`-gated and does not block the Windows build.
- [ ] Task 4: Auth orchestration + counter + wiring — files: `client/src-tauri/src/auth.rs`, `client/src-tauri/tauri-plugin-keystore/src/counter.rs`, `client/src-tauri/src/lib.rs` (modify), `client/src-tauri/Cargo.toml` (modify), `client/src-tauri/capabilities/default.json` (modify) — `counter.rs`: the crash-safe fail-closed monotonic counter (atomic temp→fsync→rename; corrupt/missing → abort, never reset to 0). `auth.rs`: `auth_pair` (gen key if absent → biometric sign of `u16-len(code)‖code‖device_id` → CLIENT-core `pair` transport fn → register), `auth_connect` (`session_begin` → sign the **fixed length-prefixed** `nonce‖context‖counter(8-byte BE)` → `session_complete` → store token in `AppState` → `connection.onConnected`), `auth_unlock` (begin → sign → complete via the broker relay → `onUnlocked`), `auth_logout`, **`auth_recover(passphrase: Zeroizing<String>)`** (relay to the escrow path; never holds the DEK). `create_key`/`destroy_key` invoked ONLY here (Rust-internal). Register the plugin + ALL FIVE `auth_*` commands in `invoke_handler!`; grant their capabilities (window `"main"`); do NOT grant `keystore:allow-create-key`/`allow-destroy-key`. — done when: (MSVC-gated) `cargo clippy`/`cargo test` exit 0; `cargo test` runs pair→connect→unlock against a fake transport + fake signer and asserts the counter strictly increases, **a corrupt counter file aborts (no 0-reset)**, and the token lands in `AppState`.
- [ ] Task 5: TS auth flow — files: `client/src/auth/pairing.ts`, `client/src/auth/recovery.ts` — `pairing.ts`: pairing-code entry → `invoke("auth_pair")` → `auth_connect` → `connection.ts` transitions; re-runnable; maps `auth_*` errors to the app-flow error states (wrong/expired code, off-tunnel, user-cancelled biometric). `recovery.ts`: passphrase entry → `invoke("auth_recover", {passphrase})` → **clear the local ref immediately after invoke returns**; never holds key material. — done when: `tsc --noEmit` exit 0; vitest drives the pairing flow over mocked `invoke` and asserts the connection store reaches `unlocked` on success and surfaces the error states on failure.
- [ ] Task 6: Tests — files: `client/src-tauri/tauri-plugin-keystore/src/sig.rs` (tests), `client/src-tauri/src/auth.rs` (`#[cfg(test)]`), `client/src/auth/pairing.test.ts` — the sig DER vector test, the orchestration fake test, the TS pairing test (above). The no-exfil guard is **structural** — `sign` returns `Vec<u8>` (a DER signature) by type; there is no key-export command in the surface. — done when: `npx vitest run` passes; (MSVC-gated) `cargo test` passes; an assertion confirms **no raw signature bytes, no `nonce` value, and no recovery passphrase** appear in any captured log/tracing/test output (esp. the `auth_recover` relay path).
- [ ] Task 7 (GATED — ADR-025 build-time spikes, real hardware): files: (verification only) — (a) confirm `NCRYPT_UI_POLICY` surfaces a Windows **Hello biometric** prompt (not PIN-only) from the Tauri process incl. the parent-window-handle path; (b) signature-encoding **conformance**: a client DER signature verifies against the live brain `SignedKeypairVerifier` (CLIENT-a); (c) macOS SE entitlements/code-signing for Touch ID from a Tauri/Rust process. — done when: each recorded in the handoff with pass/fail; failures route to planning (e.g. PIN-only fallback = the accepted ADR-025 dev-wall downgrade).

## Wave plan
Wave 1: [Task 1] | Wave 2: [Task 2, Task 3] | Wave 3: [Task 4] | Wave 4: [Task 5] | Wave 5: [Task 6] | Gated (after, real hardware): [Task 7]

## Permissions
The following actions will run autonomously during build. Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | client/src-tauri/tauri-plugin-keystore/** (Cargo.toml, build.rs, permissions/default.toml, src/{lib,commands,error,windows,macos,sig,counter}.rs), client/src-tauri/src/auth.rs, client/src/auth/{pairing,recovery,pairing.test}.ts |
| Modify | client/src-tauri/src/lib.rs, client/src-tauri/Cargo.toml, client/src-tauri/capabilities/default.json |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `cd client && npm install` | (no-op if CLIENT-core ran) |
| `cd client && npx tsc --noEmit && npx vitest run` | TS typecheck + auth-flow tests |
| `cd client/src-tauri && cargo fmt --check` | Rust format gate |
| `cd client/src-tauri && cargo clippy -- -D warnings` | Rust lint (MSVC-gated) |
| `cd client/src-tauri && cargo test` | Rust signer + orchestration tests (MSVC-gated) |
| `cd client/src-tauri && cargo audit` | supply-chain audit (windows-sys, ecdsa, argon2) |
| `cd client && npm run tauri info` | verify MSVC toolchain |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | client/src-tauri/tauri-plugin-keystore/**, client/src-tauri/src/auth.rs, client/src-tauri/{src/lib.rs,Cargo.toml,Cargo.lock,capabilities/default.json}, client/src/auth/**, client/package-lock.json |
| `git commit` | "feat: CLIENT-auth device-key signer plugin + pairing/connect/unlock (ADR-025)" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| (none new) | the device key lives in the TPM/SE; the counter is app-local data; no secrets in env |

### Network
| Action | Purpose |
|--------|---------|
| `cargo` crate fetch | windows-sys/ecdsa/p256/spki/argon2 (first build) |
| (runtime) the handshake reaches the brain only via CLIENT-core's Rust transport | no direct network here |

## Specialist Context
### Security
- **The private key NEVER leaves the TPM/Secure Enclave** — the plugin holds only an opaque handle; `sign` returns a signature, never key bytes; no command exports the private key; `KeystoreError` leaks no FFI text. Biometric-gated per use (`NCRYPT_UI_FORCE_HIGH_PROTECTION_FLAG` / `kSecAccessControlBiometryAny`).
- **Monotonic counter** (apex-auth replay discipline): strictly-increasing per-device, persisted, advanced on every proof; the brain rejects a stale/equal counter.
- **No turnkey crate** — the FFI is hand-written `unsafe` (windows-sys / objc2). Isolated to `windows.rs`/`macos.rs`; reviewed as the security boundary. [FLAG apex-security + apex-auth at wave review: confirm key-never-exported, counter monotonicity, DER conformance, and that biometric-cancel fails closed.]
- **Recovery passphrase** (ADR-005): client collects + relays only; the Argon2id-wrapped DEK escrow lives host-side (M2/broker) — the client never holds the DEK.
- **GATED spikes (Task 7)** carry the residual hardware risk: the Windows Hello-vs-PIN modality and the SE entitlements path. **PIN-only is the accepted *dev-wall* downgrade only** (ADR-025 §Windows-dev-wall caveat — Windows is the dev host); the **production root of trust is the Mac Secure Enclave with a biometric gate**, not a PIN.
- **IPC error hygiene** (anti-fingerprinting): backend NCrypt/SE numeric codes are mapped to a closed user enum (`BiometricCancelled`/`HardwareUnavailable`/`KeyNotFound`/`Encoding`) before crossing IPC; the raw code stays in internal tracing only. Biometric-cancel fails closed.
- **No-leak (broadened):** beyond key custody — raw signature bytes, nonce values, and the recovery passphrase (`Zeroizing<String>`, TS clears its ref) never reach a log/tracing/webview surface.

### Performance
(none — signing is a single TPM/SE operation per handshake; not hot.)

### Accessibility
(none — the visual pairing/unlock chrome is CLIENT-world/screens; this spec is the logic + the biometric OS prompt.)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | client/src-tauri/tauri-plugin-keystore/src/*.rs, client/src-tauri/src/auth.rs | rustdoc all exports; document the key-custody invariant (private key never leaves the hardware), the DER/SPKI pinned form, and the counter discipline |
| API | docs/product/api/client-app-api.md | note the `keystore:*` + `auth_*` command contract |
| ADR | (none new) | implements ADR-025/005/030 — no new ADR |

## Acceptance Criteria
- [ ] Run `cd client && npx tsc --noEmit && npx vitest run` → verify: the pairing flow reaches `unlocked` over mocked `invoke`; error states surface (wrong code, off-tunnel, biometric-cancel).
- [ ] Run `cd client/src-tauri && cargo fmt --check` → verify: exit 0.
- [ ] Run the `sig.rs` DER round-trip test → verify: a Windows-raw `r‖s` input normalizes to DER and verifies against the `p256` verifier for a known vector.
- [ ] (MSVC-gated) Run `cd client/src-tauri && cargo clippy -- -D warnings && cargo test` → verify: signer create→sign→verify passes; orchestration pair→connect→unlock advances the counter strictly; **a corrupt/missing counter file aborts the handshake (no silent 0-reset)**; the token lands in `AppState`; **no raw signature bytes / nonce / passphrase in any captured output**. Record gated status if MSVC absent.
- [ ] Run `cd client/src-tauri && cargo audit` → verify: no advisories for the new crates (typosquat pre-check done at Cargo.toml edit; `Cargo.lock` committed).
- [ ] Inspect `build.rs` output → verify: `permissions/autogenerated/` contains `allow-`/`deny-` pairs for all 5 COMMANDS (`create_key`/`sign`/`get_public_key`/`destroy_key`/`has_key`).
- [ ] Inspect `capabilities/default.json` → verify: `"windows"` is `["main"]` (never `"*"`); only `keystore:allow-sign|get-public-key|has-key` + the five `auth_*` commands are granted; `keystore:allow-create-key`/`allow-destroy-key` are NOT present.
- [ ] (GATED, real hardware — Task 7) → verify recorded in handoff: Hello biometric prompt (not PIN-only) from Tauri; client DER signature verifies against the live brain verifier; macOS SE Touch-ID path (Mac).

## Progress
_(Coding mode writes here — do not edit manually)_
