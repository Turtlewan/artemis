# R2 — WebAuthn PRF-derived DEK: production viability (late 2025 / 2026)

**Question:** Is the WebAuthn PRF extension (CTAP2 `hmac-secret`) a viable production mechanism for deriving a stable symmetric secret from a passkey / platform authenticator to wrap a local data-encryption key (DEK) — for a Windows Hello / Touch ID biometric ceremony that releases a 32-byte DEK decrypting a local SQLCipher DB?

**Research date:** 2026-06-22. WebFetch was denied in this environment; all findings are from WebSearch result extractions of primary/maintainer sources. Where a claim rests on a single search-summarised source it is tagged accordingly.

---

## TL;DR verdict

PRF-derived DEK wrapping is **technically real and shipping in production** (Bitwarden, 1Password, age/typage), but for the **Artemis use case specifically — a local SQLCipher DB inside a Tauri webview — it is NOT a clean fit**, for two independent reasons:

1. **Tauri webview gap [VERIFIED/LIKELY]:** WebAuthn (and therefore the `prf` extension) is generally **not available inside the system webviews Tauri uses** (WebView2, WKWebView, webkit2gtk). PRF lives in the browser's WebAuthn implementation; a webview that doesn't expose `navigator.credentials` with platform-authenticator support can't produce PRF at all. You would need a native plugin path, not the JS WebAuthn API.

2. **Sync-stability landmine [VERIFIED]:** with **synced passkeys (iCloud Keychain)**, the PRF output has been repeatedly reported to **differ across devices** — same credential, same salt, different 32-byte output per physical device. If the DEK is wrapped by a PRF output produced on device A, the user's device B (or a restored device) reproduces a *different* PRF and **cannot unwrap the DEK → data permanently lost**.

The pattern works best with **device-bound (non-synced) authenticators** (a YubiKey, or a platform authenticator explicitly used as device-bound), which contradicts the convenience goal of "biometric on any of my devices."

---

## 1. PRF / `hmac-secret` support matrix (2026)

`prf` is the WebAuthn-level extension; on security keys it is backed by the CTAP2.1 `hmac-secret` extension. Mechanically the authenticator computes `HMAC-SHA-256(perCredentialSecret, SHA256("WebAuthn PRF\0" || salt))` → 32 bytes. [VERIFIED — Trail of Bits, https://blog.trailofbits.com/2025/05/14/the-cryptography-behind-passkeys/ , 2025-05-14; Yubico PRF guide, https://developers.yubico.com/WebAuthn/Concepts/PRF_Extension/ ]

| Platform / authenticator | PRF status (2026) | Tag |
|---|---|---|
| **Windows Hello (platform auth)** | Historically the big gap. `hmac-secret` was only patched into Windows Hello via the **Feb 2026 cumulative update (KB5077181, Win 25H2 build 26200.7840+)**; earlier 25H2 builds have no PRF. Chrome **147** ships PRF-on-create on Windows enabled by default; Chrome/Edge ≤146 don't surface it. So Windows Hello PRF is *brand-new and version-gated* — assume most of the installed base lacks it through 2026. | VERIFIED (search-summarised) |
| **macOS Touch ID / iCloud passkeys** | PRF available for platform authenticators since **macOS 15 / iOS 18**; Safari 18+ and Chrome both support PRF via iCloud Keychain. Get-assertion and (for synced providers) PRF-on-create both work. | VERIFIED |
| **iOS 18+ passkeys** | PRF supported; synced providers can return first PRF output during `create()`. | VERIFIED |
| **Chrome / Edge (Chromium)** | Best desktop support. PRF on get for a while; PRF-on-create on Windows in Chrome 147. Chromium browsers are the primary supported target for Bitwarden/1Password PRF. | VERIFIED |
| **Safari** | Supports PRF via iCloud Keychain (macOS 15+/iOS 18+). But Safari 26.4 has **two open WebKit bugs for CTAP2 security keys**: WebKit 311099 (returns AES-256-CBC-encrypted hmac-secret undecrypted on USB/NFC keys → breaks cross-browser interop) and WebKit 314934 (null PRF for YubiKey Bio / intervalUV keys that skip PIN). Platform-authenticator PRF is fine; *security-key* PRF in Safari is flaky. | VERIFIED (search-summarised) |
| **Firefox** | Lagging. `hmac-secret` desktop support tracked in Bugzilla 1593571; treat as not reliably available. Android passkeys "work across most browsers except Firefox." | LIKELY |
| **Android (Google Password Manager)** | Described as the most robust/widespread PRF support; GPM passkeys include PRF by default across most browsers. | LIKELY |
| **Security keys (YubiKey etc.)** | `hmac-secret` widely implemented in hardware; this is the *original* and most deterministic path (device-bound, no sync). Safari security-key bugs above are the caveat. | VERIFIED |
| **Chrome Profile / password-manager-in-Chrome as authenticator** | **Does NOT support PRF.** | LIKELY (1Password community) |
| **Embedded webviews (WebView2 / WKWebView / webkit2gtk — i.e. Tauri)** | WebAuthn generally **not supported in webviews**; PRF therefore unavailable. WebView2 can surface passkey/WebAuthn flows in *specific Microsoft Entra sign-in configurations* (KB5072033, builds 26200.7462+), but this is not a general `navigator.credentials.create({prf})` capability for arbitrary apps. Tauri's own guidance/issues confirm WebAuthn in the webview is unreliable cross-platform; the workaround is native plugins (`tauri-plugin-webauthn`, `tauri-plugin-authenticator`) which themselves aren't on every platform. | VERIFIED/LIKELY (search-summarised) |

---

## 2. Stability across time and across sync/backup — THE critical risk

- **Same device, over time:** stable. Re-running the ceremony on the same physical device with the same salt reproduces the same 32 bytes. [VERIFIED]
- **Across iCloud-synced devices:** **NOT stable.** Multiple developer reports (Apple Developer Forums; corbado; lilting.ch) state that after a passkey syncs via iCloud Keychain, authenticating on a *different* device with the *same constant salt* yields a **different PRF output**. Output is identical *per device*, implying a **device-specific component in the derivation**. Whether this is an intentional Apple design or a bug is **UNCERTAIN** and **not confirmed fixed** as of early/mid-2026. Some reports tie the divergence specifically to **cross-device (QR-code/hybrid) flows** vs same-iCloud-account direct login — i.e. it may be *worse* over QR than over genuine sync — but the safe assumption stands. [VERIFIED that divergence is reported; UNCERTAIN on root cause/fix]
- **Google Password Manager / Android:** the *expectation* for a properly synced provider is that the per-credential secret syncs and PRF is therefore stable across that user's devices; community testing reports synced providers (Apple Passwords, GPM) hit ~100% PRF-on-create success. But the iCloud counter-example shows "synced" does not guarantee "deterministic PRF across devices." Treat GPM cross-device determinism as **LIKELY but verify empirically** before trusting it with non-recoverable keys.
- **Credential loss / deletion:** even on one device, if the passkey is deleted or the authenticator is lost/reset, the PRF is gone forever → the wrapped DEK is unrecoverable. Tim Cappalli (W3C WebAuthn L3 co-editor) and the lilting.ch article explicitly warn against PRF-for-encryption for exactly this reason: you turn a *replaceable* credential into a *non-replaceable* one and massively widen the blast radius. [VERIFIED — https://lilting.ch/en/articles/passkeys-prf-extension-encryption-risk ]

**Implication for Artemis:** wrapping a SQLCipher DEK directly with a PRF output is only safe if (a) the authenticator is device-bound and (b) there is an **independent recovery path** for the DEK (a second wrap under a recovery key / password / second credential). Never let PRF be the *sole* wrap.

---

## 3. Production precedents and lessons

- **Bitwarden** [VERIFIED — https://bitwarden.com/blog/prf-webauthn-and-its-role-in-passkeys/ , contributing.bitwarden.com PRF deep-dive]: passkey can decrypt the vault. They do **not** wrap the symmetric key directly with the raw PRF output. Architecture: PRF symmetric key → decrypts a **PRF-encrypted private key** → which decrypts the **account encryption key** → which decrypts vault data. The indirection (PRF wraps an asymmetric keypair, keypair wraps the real key) lets them rotate and avoid binding data directly to one device's PRF. Supported primarily on **Chromium** browsers. Lesson: **add a layer of indirection; don't bind data to the PRF output directly.**
- **1Password** [VERIFIED — https://blog.1password.com/encrypt-data-saved-passkeys/ ]: "encrypt data using saved passkeys" — PRF creates an additional key combined with a service salt to produce a shared secret used as an encryption key. Rolled out across Android (beta 8.10.38), iOS 18, browser ext (beta 2.26.1). Gotcha they hit: **Chrome-profile-as-authenticator doesn't support PRF**; behaviour differs per provider.
- **age / typage (Filippo Valsorda)** [VERIFIED — https://words.filippo.io/passkey-encryption/ ]: typage passkey support is <300 lines incl. a minimal CTAP2 CBOR impl. Each file gets its own PRF input(s); the file key is ChaCha20Poly1305-encrypted under a wrapping key derived by **HKDF-Extract-SHA256 over the concatenated PRF outputs with salt `age-encryption.org/fido2prf`**. Privacy property: you can't link a file to a credential without decrypting it. This is the clean reference design for *file* encryption with **device-bound security keys**.
- **age-plugin-fido2-hmac (olastor)** [VERIFIED — https://github.com/olastor/age-plugin-fido2-hmac ]: uses CTAP2 `hmac-secret` directly with **non-discoverable credentials** on FIDO2 tokens. Confirms the security-key path is mature; spec-v2 documents salt handling.
- **Oblique Security PRF guide** [VERIFIED — https://oblique.security/blog/passkey-prf/ ]: best-practice notes (see §4).

**Common lesson across all four:** they target **device-bound security keys or Chromium browsers**, wrap **a key-encryption-key (not the data key) and keep a recovery path**, and treat the raw PRF output as a *KEK seed run through HKDF*, never as the final key.

---

## 4. Caveats: salt, eval input, credential ID, webviews

- **Salt / eval input:** WebAuthn mandates the website-provided salt(s) (`eval.first`, optional `eval.second`) are prefixed/hashed with the context string `"WebAuthn PRF\0"` before hitting `hmac-secret`, partitioning PRF input space so a site can't coerce HMACs for non-web uses. [VERIFIED — Oblique, Trail of Bits]
- **Static salt is fine:** PRF is unique per-credential, so a fixed/static salt is acceptable — two users (or same user on different sites) always get different outputs. A static salt can be issued at the login challenge before you know who's authenticating. [VERIFIED — Oblique]
- **`eval.second` as rotation primitive:** pass current key as `first`, next key as `second`; server flips which is "current" over time → seamless KEK rotation without re-enrolment. [VERIFIED — Oblique]
- **Credential ID must be stored:** to PRF on a *get* assertion you must supply `allowCredentials` with the credential ID (non-discoverable creds). age/age-plugin-fido2-hmac store the credential ID in the stanza/header. For discoverable (resident) passkeys it's optional but you still typically persist it. [VERIFIED — age spec, Yubico]
- **PRF is not a full KDF:** the extension gives one HMAC-SHA-256 per salt; not flexible enough to *be* HKDF, but you can use it as HKDF-Extract input (concatenate `first`+`second`, run HKDF). Always HKDF the output before use. [VERIFIED — Trail of Bits]
- **Webview:** as in §1 — `prf` is unavailable in plain Tauri webviews; needs native authenticator API. [VERIFIED/LIKELY]

---

## 5. Non-PRF alternatives for the same goal (brief)

For a **local-only DEK wrapped by a biometric/presence ceremony**, the platform-native sealing APIs are a better fit than WebAuthn-PRF for a desktop app, because they're built for exactly "hardware-bind a secret to this device, gate release on user presence/biometric," they don't depend on a browser/webview, and the device-bound nature is explicit (no sync surprise).

- **Windows — TPM-sealed key + Hello-for-presence (CNG/NCrypt / DPAPI-NG):** generate/seal a key in the TPM via `NCryptOpenStorageProvider(MS_PLATFORM_CRYPTO_PROVIDER)` / `NCryptImportKey`/`NCryptSignHash`; or use **DPAPI-NG (CNG DPAPI)** to protect the DEK to a principal. TPM 2.0 anti-hammering locks after 32 PIN failures (forgets one per 10 min). Hello provides the user-presence/biometric gate; the TPM provides the hardware binding. Device-bound by nature → **not portable across machines** (you need an explicit recovery/escrow path), which is the same constraint as PRF but without the sync ambiguity. [VERIFIED — Microsoft CNG DPAPI docs; Unit42]
- **macOS — Secure Enclave key wrapping + LocalAuthentication:** generate a non-exportable EC key in the Secure Enclave; wrap the DEK with it; gate use with an `LAContext` (Touch ID / password) and a SecAccessControl flag (`.biometryCurrentSet`/`.userPresence`). Standard pattern (e.g. agens EllipticCurveKeyPair). Also device-bound. [VERIFIED — Apple/agens]
- **Trade-off vs PRF:** native sealing avoids the webview gap and the sync-determinism landmine entirely, at the cost of writing two platform-specific Rust/FFI paths instead of one WebAuthn JS path. For a Tauri SQLCipher app this is very likely the **better architecture**: TPM/DPAPI-NG on Windows, Secure Enclave on macOS, each gating a locally-sealed DEK — plus a password/recovery-key fallback wrap so the DB is never single-device-lockable.

---

## Sources (with dates / tags)

- Trail of Bits, *The cryptography behind passkeys*, 2025-05-14 — https://blog.trailofbits.com/2025/05/14/the-cryptography-behind-passkeys/ [VERIFIED]
- Yubico, *Developers Guide to PRF / CTAP2 hmac-secret deep dive* — https://developers.yubico.com/WebAuthn/Concepts/PRF_Extension/ [VERIFIED, undated maintainer docs]
- Corbado, *Passkeys & WebAuthn PRF for E2E Encryption (2026)* — https://www.corbado.com/blog/passkeys-prf-webauthn [VERIFIED, dated 2026; vendor blog]
- lilting.ch, *Do not use Passkeys' PRF extension to derive encryption keys* (summarising Tim Cappalli warning), notes PRF inconsistent as of Feb 2026 — https://lilting.ch/en/articles/passkeys-prf-extension-encryption-risk [VERIFIED]
- Oblique Security, *Passkey PRFs for end-to-end encryption* — https://oblique.security/blog/passkey-prf/ [VERIFIED]
- Bitwarden, *PRF WebAuthn and its role in passkeys* + contributing-docs PRF deep dive — https://bitwarden.com/blog/prf-webauthn-and-its-role-in-passkeys/ , https://contributing.bitwarden.com/architecture/deep-dives/passkeys/implementations/relying-party/prf/ [VERIFIED]
- 1Password, *1Password can now encrypt data using your saved passkeys* — https://blog.1password.com/encrypt-data-saved-passkeys/ [VERIFIED]
- Filippo Valsorda, *Encrypting Files with Passkeys and age* — https://words.filippo.io/passkey-encryption/ [VERIFIED]
- olastor, *age-plugin-fido2-hmac* (+ spec-v2) — https://github.com/olastor/age-plugin-fido2-hmac [VERIFIED]
- Apple Developer Forums, *Passkeys and PRF extension* thread (device-specific PRF reports) — https://developer.apple.com/forums/thread/733413 [VERIFIED that issue reported; UNCERTAIN on resolution]
- Tauri docs, *Webview Versions* — https://v2.tauri.app/reference/webview-versions/ ; Tauri issue #6471 (webview WebAuthn NotAllowedError) — https://github.com/tauri-apps/tauri/issues/6471 [VERIFIED/LIKELY]
- Microsoft Learn, *CNG DPAPI* — https://learn.microsoft.com/en-us/windows/win32/seccng/cng-dpapi ; WebView2 + Entra (KB5072033) — https://techcommunity.microsoft.com/blog/windows-itpro-blog/4476166 [VERIFIED]
- Chromium, *Intent to Ship: WebAuthn PRF extension* — https://groups.google.com/a/chromium.org/g/blink-dev/c/iTNOgLwD2bI ; chromestatus 5138422207348736 [VERIFIED]

### Staleness / confidence flags
- Windows Hello PRF dates (KB5077181 / Chrome 147 / Feb 2026) and Safari WebKit bug numbers came via search-summary, not direct page reads (WebFetch was denied) — **re-verify exact build/version numbers** against the primary pages before relying on them in a spec.
- The iCloud cross-device PRF determinism question is the single biggest unknown: confirmed *reported*, not confirmed *fixed or intentional*. Empirical test on real hardware required before trusting synced-passkey PRF for any non-recoverable key.
