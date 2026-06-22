# ADR-025 — Tauri client↔brain auth + privacy-wall re-root (custom challenge-response + native hardware sealing)

- **Status:** Accepted
- **Date:** 2026-06-22
- **Deciders:** owner + planning
- **Relates / supersedes:** **supersedes ADR-023 §4** (the "Passkeys / WebAuthn" client-unlock choice — reversed by research) · **re-expresses the CLIENT LAYER of ADR-010** (the brain-side verifier, two-authority model, session model, scope-from-session, and counter discipline all still hold) · **re-expresses the client-assertion path + hardware root of ADR-005** (the broker concept, host-side DEK wrap, and recovery-passphrase escrow all still hold) · ADR-022 (build-Windows-first; brain = always-on host) · ADR-023 (Tauri client). Research basis: `docs/findings/tauri-auth-deep-dive/` (`_SUMMARY.md` + tracks R1–R4).

## Context

ADR-010 (client↔brain auth) and ADR-005 (owner-key broker / privacy wall) are both rooted on the **Apple Secure Enclave** plus a **phone Face-ID relay** — a design dictated by two Apple facts (ADR-005 §Context): biometry-gated SE keychain items work only in a user-login context (not a `LaunchDaemon`), and **the Mac Mini has no Touch ID** (so the biometric had to originate on the owner's iPhone).

ADR-023 replatformed the client SwiftUI → **Tauri** (Windows `.exe` now, Mac `.app` later) and ADR-022 set **build-Windows-first, Mac = final host**. ADR-023 §4 provisionally chose **passkeys / WebAuthn** for unlock. A four-track deep-dive (R1–R4) tested that choice against the real topology and **reversed it**:

- **R1** — WebAuthn inside a Tauri webview is unreliable cross-platform: Windows (WebView2) works and reaches Windows Hello, but **macOS WKWebView is broken** for custom origins and **Linux (WebKitGTK) has no support**. Real passkeys would require a native-Rust bypass or handing the ceremony to the system browser.
- **R2** — using a passkey's **PRF/`hmac-secret`** output to wrap the vault DEK is a poor fit: the PRF API is generally unavailable in Tauri webviews, and **synced-passkey PRF output can differ across devices** → a DEK wrapped on one device becomes unrecoverable on another. Native sealing is the better fit; always keep an independent recovery wrap.
- **R3** — a hardware-backed, biometric-gated **P-256** signing key is buildable from Rust on both platforms (custom FFI; no turnkey crate). **Critical:** Windows Hello's `KeyCredentialManager` is **RSA-only — it cannot do P-256**; P-256 must go through **CNG/NCrypt + the TPM Platform Crypto Provider** with `NCRYPT_UI_POLICY` for the biometric prompt. macOS reproduces ADR-005's SE path cleanly (`objc2-security`).
- **R4** — real WebAuthn is brittle over Tailscale: a Tauri webview's origin (`tauri://localhost`) ≠ the `ts.net` RP ID, and passkeys bind to one registrable domain at registration, so the planned URL mobility (`localhost` dev → `tailnetNNNN.ts.net` → `mac.local`) would brick credentials on every move. A **custom challenge-response is URL-agnostic** and rides the existing WireGuard tunnel.

The reframe that simplifies everything: the **phone relay was a workaround for the headless, Touch-ID-less Mini**. A Tauri client on a device that has its **own** biometric (Windows Hello / Mac Touch ID) does not need the relay — so the design must support both co-located dev and remote end-state.

## Decision

Keep the existing design; swap **only** the prover (client signer) and the host key primitive. WebAuthn/passkeys are **not** used.

| Aspect | Decision |
|--------|----------|
| **Network / session auth** | **Custom P-256 ECDSA challenge-response, unchanged** — reuse the already-built M2-a `SignedKeypairVerifier` + strictly-increasing per-device counter. Brain issues nonce → client signs `(nonce ‖ context ‖ counter)` → brain verifies → short-lived opaque session token. URL-agnostic; rides Tailscale WireGuard. (ADR-010 §2 unchanged in substance.) |
| **Client signer (the prover)** | A **hardware-backed, biometric-gated P-256 key on the client device**. **Windows:** CNG/NCrypt + **TPM Platform Crypto Provider** (`NCRYPT_ECDSA_P256_ALGORITHM`, `NCRYPT_EXPORT_POLICY=0`, `NCRYPT_UI_POLICY` per-use Hello prompt) — **NOT** `KeyCredentialManager` (RSA-only). **macOS:** Secure Enclave key + `LAContext` (Touch ID) via `objc2-security` (reproduces ADR-005). The ADR-005 "phone Face-ID" generalises to **any paired Tauri device with a biometric**. |
| **Vault DEK wall** | **Native host-side sealing** — the per-scope SQLCipher DEK is wrapped to a host hardware key: **macOS Secure Enclave** (end-state Mini) / **Windows TPM** (CNG/NCrypt or DPAPI-NG) for dev. **NOT** passkey-PRF (R2). The DEK never crosses the wire; the client supplies only the signed biometric assertion. (ADR-005's wrap-on-host model unchanged.) |
| **Recovery** | The ADR-005 **recovery passphrase** (Argon2id-wrapped escrow copy of each DEK) stays — the only phone-/device-less path **and** the independent recovery wrap R2 requires so a lost client key never means lost data. |
| **Topology duality** | **Co-located dev** (brain + Tauri client on one Windows PC) → the assertion is a **local Hello prompt**; no relay, no Tailscale required. **End-state remote** (headless Mini host + a remote Tauri client) → the client signs and the host-side broker verifies + unwraps, exactly as ADR-005 but with "phone" generalised. The challenge-response supports both with no protocol change. |
| **Scope from session** | Unchanged (ADR-010 §3) — the brain derives owner scope from the authenticated session, never from the client. |

## Consequences

- **Maximal reuse.** The entire brain-side verifier (M2-a), the ADR-010 two-authority session model, and the ADR-005 host DEK-wrap + recovery passphrase all survive — only the client prover and the host key primitive are re-hosted (SE → TPM/Hello).
- **Two native FFI paths to build** (Windows CNG, macOS SE) instead of one JS path. No turnkey Rust crate exists for biometric-gated signing; a small custom Tauri command/plugin is required (effort: macOS medium, Windows medium-high).
- **We own a small amount of crypto-glue** (standard ECDSA challenge-response + counter — i.e. WebAuthn's assertion model minus the browser ceremony — plus native key sealing). No novel primitives; apex-auth counter discipline preserved.
- **`stack_skills` shift** (already flagged by ADR-023): drop `apex-swift`-for-clients; add web-frontend + Tauri. The voice audio sidecar remains the only possible Swift footprint.
- **Windows-dev wall caveat:** if the Windows biometric prompt degrades to PIN-only (see spike), the dev-time wall is weaker — acceptable because Windows is the **dev** host and the Mac Mini SE is the final-host root.
- **Revisit trigger:** reconsider real passkeys only if (a) Tauri webview WebAuthn matures cross-platform **and** (b) the cross-device PRF-stability issue is confirmed fixed.

## Alternatives considered

- **Option B — real WebAuthn / passkeys end-to-end** (the ADR-023 §4 provisional choice). *Rejected.* R1 (webview support broken on macOS/Linux), R2 (PRF-as-DEK fragile across sync + webview gap), R4 (RP-ID/origin brittle over Tailscale + URL mobility) each independently disqualify it for this topology; phishing-resistance — passkeys' main edge — is largely moot inside a private WireGuard tunnel with device-registered keys.
- **Option C — decoupled: a simple paired-device bearer token for the network + a separate local native-sealed DEK gate.** *Folded, not chosen as-is.* Its good idea (native-sealed DEK independent of any web ceremony) is adopted in the Decision; but a bearer token is coarser per-request identity than the challenge-response we already have built (ADR-010 explicitly rejected Tailscale-only/coarse network trust), so we keep the signed challenge-response for the network layer.

## Build-time spikes (gated tasks)

- **Windows biometric-prompt modality (the one MED-confidence unknown):** confirm `NCRYPT_UI_POLICY` on the TPM Platform Crypto Provider surfaces a Windows **Hello biometric** prompt (not PIN-only) from a Tauri process, including the parent-window-handle path from a windowless context.
- **Signature encoding pinned end-to-end:** Windows NCrypt returns raw `r‖s`; macOS `SecKeyCreateSignature` returns DER — normalise to whatever the brain-side `SignedKeypairVerifier` expects, with a conformance test.
- **macOS SE entitlements/code-signing** for Touch ID from a Tauri/Rust process (real Apple hardware; no simulator).

## Pointer
Full research + citations: `docs/findings/tauri-auth-deep-dive/_SUMMARY.md` (tracks R1–R4 in the same directory).
