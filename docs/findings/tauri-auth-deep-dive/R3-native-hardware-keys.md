# R3 — Native hardware-backed, biometric-gated signing keys from Tauri 2 / Rust

**Question:** Can a Tauri 2 / Rust desktop app create and use a hardware-backed, biometric-gated
signing key on Windows and macOS, to implement a custom challenge-response prover that signs a
server nonce behind a biometric prompt — feeding our existing brain-side P-256 ECDSA verifier (over
`nonce || context || counter`)? This is **direct native key access**, not WebAuthn.

_Research date: 2026-06-22. Tags: [VERIFIED] = confirmed in primary/official source; [LIKELY] =
strong secondary evidence; [UNCERTAIN] = needs hands-on confirmation._

---

## Headline verdict

**Viable on both Windows and macOS, but it is a custom-FFI build, not a turn-key crate — and on
Windows you must use the CNG/NCrypt path, NOT the obvious Windows Hello `KeyCredentialManager` API.**

The single most important finding: **`KeyCredentialManager` (the WinRT "Windows Hello for apps" API)
produces RSA-2048 keys signed with PKCS#1 RSA-PSS-SHA256 — it cannot produce a P-256 ECDSA
signature.** [VERIFIED] That is a direct algorithm mismatch with our existing P-256 verifier. To get
TPM-backed **P-256 ECDSA** with a per-use biometric/PIN prompt on Windows, you go one level down to
**CNG/NCrypt** with the **Microsoft Platform Crypto Provider** + `NCRYPT_UI_POLICY`.

On macOS the path is clean and matches ADR-005 exactly: Secure Enclave P-256 key via
`SecKeyCreateRandomKey` with a `SecAccessControl` carrying `.privateKeyUsage` +
`.biometryCurrentSet`/`.userPresence`, signed via `SecKeyCreateSignature`. All callable from Rust.

No existing Tauri plugin does this — the existing biometric plugins do auth-gate (yes/no) or
encrypted storage, not challenge-response signing with a registered public key. A small custom Tauri
command / plugin wrapping platform FFI is required.

---

## 1. Windows

### 1a. The wrong path: `KeyCredentialManager` (WinRT) — RSA only

- The WinRT `Windows.Security.Credentials.KeyCredentialManager` class is the documented
  "Windows Hello for apps" API. `RequestCreateAsync` creates a key, `OpenAsync` retrieves it, and
  `KeyCredential.RequestSignAsync(challenge)` triggers the "Making sure it's you" Hello prompt and
  signs the challenge. The key is hardware/TPM-backed where available and gated by Hello on each use.
- **BUT** the official class remarks state: **Key Type = RSA 2048-bit; Signature Format = PKCS #1
  RSA PSS with SHA256.** There is no parameter to select an EC curve. [VERIFIED]
  - https://learn.microsoft.com/en-us/uwp/api/windows.security.credentials.keycredentialmanager (updated 2026-03-30)
- The Rust binding exists (`windows` crate,
  `windows::Security::Credentials::KeyCredentialManager`) so it is callable from Rust, but the RSA-only
  constraint makes it unusable against our P-256 verifier unless we add an RSA-PSS verification path
  on the brain side. [VERIFIED — binding exists]
  - https://microsoft.github.io/windows-docs-rs/doc/windows/Security/Credentials/struct.KeyCredentialManager.html

> Decision lever: if we were willing to register an RSA-2048 public key for Windows clients and add
> an RSA-PSS-SHA256 verify branch in the brain verifier, `KeyCredentialManager` is by far the *easiest*
> Windows path (high-level WinRT, Hello prompt handled for us, no provider plumbing). Our stated
> verifier is P-256-only, so as specified this path is out.

### 1b. The right path for P-256: CNG / NCrypt + Platform Crypto Provider

- **Provider:** open the **Microsoft Platform Crypto Provider** (`MS_PLATFORM_CRYPTO_PROVIDER`) — this
  is the TPM-backed KSP. Keys live in the TPM and are non-exportable by hardware nature. [VERIFIED]
  - TPM-backed ECDSA via Platform Crypto Provider documented in Microsoft's TPM/PCP guidance and
    `cng-cryptographic-algorithm-providers`.
- **Algorithm:** `NCRYPT_ECDSA_P256_ALGORITHM` is a supported CNG algorithm identifier; Microsoft's
  own `Windows-classic-samples/.../SignHashWithPersistedKeys` demonstrates
  `NCryptCreatePersistedKey(... NCRYPT_ECDSA_P256_ALGORITHM ...)` → `NCryptFinalizeKey` →
  `NCryptSignHash`. [VERIFIED]
  - https://github.com/microsoft/Windows-classic-samples/blob/main/Samples/Security/SignHashWithPersistedKeys/cpp/SignHashWithPersistedKeys.cpp
- **Per-use biometric/PIN prompt:** set `NCRYPT_UI_POLICY_PROPERTY` with an `NCRYPT_UI_POLICY`
  struct before finalizing the key. `dwFlags = NCRYPT_UI_PROTECT_KEY_FLAG (0x1)` shows the strong-key
  UI as needed; `NCRYPT_UI_FORCE_HIGH_PROTECTION_FLAG (0x2)` forces it. This property is set-once at
  key generation and becomes read-only after `NCryptFinalizeKey`. The prompt fires on each private-key
  use (the "strong key" dialog → PIN/fingerprint/face via the credential provider). [VERIFIED for the
  property semantics; [LIKELY] that it surfaces Hello biometric specifically rather than only a PIN —
  the doc says "PIN or fingerprint protected" but the exact modality depends on enrolled Hello
  factors and is worth a hands-on check.]
  - https://learn.microsoft.com/en-us/windows/win32/api/ncrypt/ns-ncrypt-ncrypt_ui_policy (updated 2024-02-22)
  - https://learn.microsoft.com/en-us/windows/win32/seccng/key-storage-property-identifiers (updated 2025-05-19)
- **Non-exportable:** set `NCRYPT_EXPORT_POLICY_PROPERTY` to `0` (no `NCRYPT_ALLOW_EXPORT_FLAG`).
  With the Platform Crypto (TPM) provider the private key never leaves the TPM regardless. [VERIFIED]
- **Counter:** the brain protocol's `counter` must be maintained by us (in the signed payload). CNG's
  `NCRYPT_USE_COUNT_PROPERTY` is *not* supported by the Microsoft KSPs, so do not rely on a
  hardware-maintained counter — track it app-side. [VERIFIED — doc states MS KSP does not support it.]

**Rust crates for this path:** the official `windows` / `windows-sys` crates (windows-rs) expose the
full `windows::Win32::Security::Cryptography` module: `NCryptOpenStorageProvider`,
`NCryptCreatePersistedKey`, `NCryptSetProperty`, `NCryptFinalizeKey`, `NCryptSignHash`, plus the
`NCRYPT_*` constants including `NCRYPT_ECDSA_P256_ALGORITHM`. [VERIFIED]
- https://docs.rs/windows-sys/latest/windows_sys/Win32/Security/Cryptography/index.html
- https://microsoft.github.io/windows-docs-rs/doc/windows/Win32/Security/Cryptography/
There is a worked Rust+TPM example (RSA key wrapping) using `windows-sys` NCrypt that confirms the
binding ergonomics, though it does RSA not ECDSA:
- https://dev.to/tsuruko12/how-i-used-tpm-for-key-encryption-in-rust-using-windows-apis-33n0

No dedicated high-level "ncrypt" or "tpm" Rust crate wraps this nicely for ECDSA + UI policy — you
call the raw `unsafe` NCrypt FFI through windows-rs yourself. [LIKELY — no maintained higher-level
crate surfaced in search.]

**Signature format note:** `NCryptSignHash` for ECDSA returns the raw `r || s` (64-byte) fixed-width
signature, not DER. Our verifier must accept (or we convert to) that encoding — trivial but a
known integration seam. [LIKELY]

### Windows summary
P-256 ECDSA, TPM-backed, non-exportable, per-use Hello/PIN prompt is achievable via CNG/NCrypt +
Platform Crypto Provider, fully from Rust through windows-rs. Effort is **medium-high**: raw unsafe
FFI, manual `NCRYPT_UI_POLICY` plumbing, and a hands-on check that the prompt presents the biometric
factor (not just PIN) and that a windowless Tauri process can parent the dialog
(`NCRYPT_WINDOW_HANDLE_PROPERTY` must be set or the UI may misbehave).

---

## 2. macOS

This reproduces ADR-005's Swift `SignedKeypairVerifier`/SE approach directly from Rust.

- **Key creation:** `SecKeyCreateRandomKey` with attributes:
  `kSecAttrKeyType = kSecAttrKeyTypeECSECPrimeRandom`, `kSecAttrKeySizeInBits = 256` (→ P-256),
  `kSecAttrTokenID = kSecAttrTokenIDSecureEnclave`, and a `kSecAttrAccessControl` built by
  `SecAccessControlCreateWithFlags(..., kSecAttrAccessibleWhenUnlockedThisDeviceOnly,
  flags = .privateKeyUsage | .biometryCurrentSet (or .userPresence), ...)`. [VERIFIED — standard
  documented SE pattern]
  - https://developer.apple.com/documentation/security/secaccesscontrolcreatewithflags(_:_:_:_:)
  - https://developer.apple.com/documentation/security/secaccesscontrolcreateflags
- **Signing:** `SecKeyCreateSignature(privateKey, .ecdsaSignatureMessageX962SHA256, data, &err)`.
  With `.biometryCurrentSet`/`.userPresence` in the access control, this call **blocks and triggers
  Touch ID / Face ID (or watch/password fallback) on every signature** — call it off the main
  thread. Returns a **DER-encoded** ECDSA-SHA256 signature; convert to `r||s` if the verifier wants
  raw. [VERIFIED]
  - https://developer.apple.com/documentation/security/secaccesscontrolcreateflags
  - credctl SE deep-dive (Go, but identical Security.framework calls): http://credctl.com/blog/secure-enclave-deep-dive/
- **Non-exportable:** SE keys are non-exportable by hardware design; only the public key and an opaque
  key reference are accessible. [VERIFIED]
- **`LocalAuthentication` (LAContext)** can supply a pre-authenticated context / custom prompt via
  `kSecUseAuthenticationContext`, but is optional — the access-control flag alone drives the prompt.
  [LIKELY]

**Rust path / crates:**
- **`objc2-security`** (v0.3.2, last release ~late 2025, actively maintained as part of madsmtm's
  `objc2` framework-bindings family) — raw bindings to Security.framework: exposes `SecKey*`,
  `SecAccessControl*`, and the `kSec*` constants. This is the recommended, current foundation; you
  write the SE create/sign sequence yourself over these bindings. [VERIFIED — crate exists, maintained,
  objc2 family]
  - https://crates.io/crates/objc2-security · https://docs.rs/objc2-security/latest/objc2_security/
  - objc2 umbrella: https://github.com/madsmtm/objc2
- **`security-framework`** (the kornelski/rust crate; updated as recently as Feb 2026) — safe
  higher-level bindings (keychain, SecKey, etc.). Good for parts but historically thinner on the
  SE-access-control + biometry creation flow; check current version for `SecAccessControl` coverage.
  [LIKELY]
  - https://crates.io/crates/security-framework
- **`keychain-services.rs`** (iqlusioninc) — purpose-built for "TouchID-guarded access to keys in the
  SEP," i.e. exactly this use case, BUT explicitly marked **experimental, "may have bugs / memory
  safety issues, USE AT YOUR OWN RISK," last meaningful activity ~2018–2019.** Useful as a reference
  implementation, not for production. [VERIFIED]
  - https://github.com/iqlusioninc/keychain-services.rs/

### macOS summary
Clean, well-trodden conceptually (the Swift/Go pattern is everywhere). From Rust it's **medium
effort**: drive `objc2-security` FFI for the create/sign sequence (~150–250 lines unsafe-ish glue),
DER↔raw conversion, off-main-thread signing. No maintained Rust crate gives it to you turn-key;
`keychain-services.rs` shows it's been done but is stale.

> Hard requirement: SE code only works on real Apple hardware — the iOS Simulator (and to a degree CI)
> does not emulate the Secure Enclave. On macOS you need a Mac with SE (T2 / Apple Silicon) + a code
> signature with the right entitlements for Touch ID. This matters for the Mac Mini bring-up plan.

---

## 3. Linux (lower priority)

- **TPM2 via `tss-esapi`** (parallaxsecond/rust-tss-esapi) — mature, maintained Rust wrapper over
  TSS2 ESAPI; supports `TPM2_ALG_ECDSA`, works against hardware TPM and swtpm/vTPM. Can create a
  TPM-resident P-256 key and sign. [VERIFIED]
  - https://docs.rs/tss-esapi/ · https://github.com/parallaxsecond/rust-tss-esapi
- **But there is no standard biometric layer on Linux.** TPM gives you hardware non-exportable keys;
  gating them behind a *biometric* is not a uniform OS service (fprintd exists but isn't wired to TPM
  key use the way Hello/SE are). Practical Linux story: hardware-backed key = yes (TPM2 via
  `tss-esapi`); biometric-gated = effectively no without bespoke fprintd/PAM glue. A pragmatic
  fallback is the OS keyring (`secret-service`/`keyutils`) for at-rest protection without hardware
  binding. [LIKELY]
- `tss-esapi`'s high-level abstraction is RSA-centric; ECDSA likely needs lower-level ESAPI calls.
  [LIKELY]

### Linux summary
Hardware key + ECDSA: feasible via `tss-esapi`. Biometric gating: not a solved native path — treat
as "TPM-backed, presence-gated at best" or defer Linux to keyring-only.

---

## 4. Practical maturity & effort

- **Is biometric-gated *signing* from Rust well-trodden?** Partly. The platform APIs are stable and
  well-documented; the *Rust* layer is raw FFI with **no maintained turn-key crate** for "create a
  biometric-gated hardware signing key and sign a nonce." You assemble it from `windows-rs` (Win) and
  `objc2-security` (mac). The Tauri biometric plugins that exist do **not** cover this:
  - `tauri-apps/plugins-workspace` biometric plugin: **mobile only** (iOS/Android), and it's
    auth-gate, not signing. [VERIFIED] — https://v2.tauri.app/plugin/biometric/
  - `Choochmeque/tauri-plugin-biometry`: covers Win/mac/iOS/Android but is **auth + encrypted data
    storage**, and on **Windows it uses the WebAuthn API (`webauthn.dll`, hmac-secret/PRF)** — i.e.
    not the direct-native-key path requested, and not P-256 challenge-response signing against a
    registered key. [VERIFIED] — https://github.com/Choochmeque/tauri-plugin-biometry
  → **A custom Tauri command/plugin is required either way.**

- **Effort estimate:**
  - macOS: **medium.** Clean pattern, good `objc2-security` bindings, stale-but-real reference in
    `keychain-services.rs`. Sharp edges: entitlements/code-signing for Touch ID, off-main-thread
    blocking signature, DER→raw conversion, SE only on real hardware.
  - Windows: **medium-high.** Must consciously reject `KeyCredentialManager` (RSA) and hand-roll
    CNG/NCrypt; `NCRYPT_UI_POLICY` is set-once and lightly documented; confirm the prompt shows
    biometric not just PIN; set the parent window handle from a Tauri webview process; raw `r||s`
    output. Microsoft's C++ sample is the template, ported to windows-rs `unsafe`.
  - Linux: **medium** for TPM-only signing (`tss-esapi`), **high/blocked** for true biometric gating.

- **Example projects doing native hardware-key signing from Rust:**
  - `sekey/sekey` — SSH agent using Secure Enclave + Touch ID, **written in Rust**, P-256 keys.
    Proves the macOS path end-to-end, but **stale (v0.1, Dec 2017).** [VERIFIED]
    - https://github.com/sekey/sekey
  - `iqlusioninc/keychain-services.rs` — Rust SEP/TouchID key access, experimental/stale. [VERIFIED]
  - `credctl` — SE P-256 (→ES256) credential signer, **Go not Rust**, but a clean modern reference for
    the exact create+sign+convert flow. [VERIFIED] — http://credctl.com/blog/secure-enclave-deep-dive/
  - Windows: no public Rust project found doing CNG-ECDSA + UI-policy biometric signing; closest is
    the Rust+windows-sys TPM key-wrap article (RSA). [LIKELY — none surfaced]

---

## Confidence & biggest unknowns

- **Overall confidence: high** that the path is viable on both target platforms; **medium** on the
  exact Windows biometric-prompt modality and the precise Rust glue volume.
- **Biggest unknown #1:** Whether `NCRYPT_UI_POLICY` on the Platform Crypto Provider reliably surfaces
  a **Windows Hello biometric** prompt (face/fingerprint) rather than only a PIN dialog, and whether it
  behaves correctly when invoked from a Tauri (non-classic-window) process. Needs a hands-on spike on
  real Windows-Hello hardware.
- **Biggest unknown #2:** macOS code-signing/entitlement requirements to make SE + Touch ID work for a
  Tauri-bundled binary (Developer ID, hardened runtime, `com.apple.security` entitlements) — mechanical
  but must be validated during Mac Mini bring-up.
- **Cross-cutting:** both platforms emit non-`r||s` defaults (Win = raw r||s; mac = DER) — pin the
  signature encoding the brain verifier expects early.

## Key sources
1. KeyCredentialManager (RSA-2048 / RSA-PSS — the disqualifier) — https://learn.microsoft.com/en-us/uwp/api/windows.security.credentials.keycredentialmanager (2026-03-30)
2. NCRYPT_UI_POLICY (per-use strong-key prompt) — https://learn.microsoft.com/en-us/windows/win32/api/ncrypt/ns-ncrypt-ncrypt_ui_policy (2024-02-22)
3. CNG key-storage properties (export policy, UI policy, use-count not supported) — https://learn.microsoft.com/en-us/windows/win32/seccng/key-storage-property-identifiers (2025-05-19)
4. windows-sys CNG/NCrypt Rust bindings — https://docs.rs/windows-sys/latest/windows_sys/Win32/Security/Cryptography/index.html
5. objc2-security (current maintained macOS FFI) — https://crates.io/crates/objc2-security
6. SecAccessControlCreateWithFlags / biometry flags — https://developer.apple.com/documentation/security/secaccesscontrolcreatewithflags(_:_:_:_:)
7. sekey (Rust SE + Touch ID signing, stale) — https://github.com/sekey/sekey
