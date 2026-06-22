# Deep Dive: Auth — Tauri/Windows-first client↔brain auth + privacy-wall re-root

_Status: IN PROGRESS — research dispatched 2026-06-22. Supersedes the Apple-SE assumptions in ADR-010/ADR-005 for the client layer (ADR-023 replatform). Analysis only; no spec yet._

## The question
ADR-023 replatforms the client SwiftUI → Tauri (Windows `.exe` now, Mac `.app` later; ADR-022 build-Windows-first). ADR-010 (client↔brain auth) and ADR-005 (owner-key broker / privacy wall) are both rooted on the **Apple Secure Enclave** + a **phone Face-ID relay** (a workaround for the headless, Touch-ID-less Mac Mini). Re-express both for a Tauri desktop client whose host device may have its *own* biometric (Windows Hello / Touch ID).

Two separable concerns (ADR-010 already separates them):
1. **API-session auth** — client proves identity to the brain over Tailscale (reachability/identity token).
2. **Vault unlock / DEK release** — a biometric releases the per-scope SQLCipher DEK (the actual privacy wall; ADR-005).

## Candidate architectures (to be fully worked after research lands)
- **A — Keep the custom P-256 challenge-response; re-express the prover in Tauri.** Reuse the already-built brain-side verifier (M2-a `SignedKeypairVerifier` + counter). Private key in TPM/Hello (Win) or SE/Keychain (Mac), biometric-gated. (Depends on R3.)
- **B — Real WebAuthn/passkeys end-to-end.** Brain becomes a WebAuthn relying party (py_webauthn). Platform authenticator via `navigator.credentials`. DEK release via the PRF extension. (Depends on R1, R2, R4.)
- **C — Decoupled: simple device token for the network + local TPM-sealed DEK gate.** Network auth = paired-device token over Tailscale; DEK gate = local OS biometric sealing the key, independent of the network handshake. (Depends on R2, R3.)

## Research tracks
- **R1** — WebAuthn/`navigator.credentials` support inside Tauri 2 webviews (WebView2 / WKWebView / WebKitGTK) → `R1-webauthn-in-webview.md`
- **R2** — WebAuthn PRF / hmac-secret extension to derive a DEK-wrapping key (Win Hello / Touch ID / webview) → `R2-prf-derived-dek.md`
- **R3** — Native hardware-key access from Tauri/Rust: Windows TPM/CNG + Hello, macOS SE + LocalAuthentication → `R3-native-hardware-keys.md`
- **R4** — WebAuthn without a public domain (Tailscale/LAN/localhost RP-ID constraints) → `R4-webauthn-no-public-domain.md`

## Findings (all four tracks in — 2026-06-22)

| Track | One-line verdict | Confidence |
|-------|------------------|-----------|
| **R1** WebAuthn in webview | Unreliable cross-platform: Windows (WebView2) works + reaches Hello; **macOS WKWebView broken** for custom origins; **Linux none**. Real passkeys need a native-Rust bypass or system browser. | HIGH |
| **R2** PRF→DEK | Production-real (Bitwarden/1Password/age) but **poor fit for Artemis**: PRF unavailable in Tauri webviews + **synced-passkey PRF output differs across devices** → DEK unrecoverable. Use **native sealing**; always keep an independent recovery wrap. | MED-HIGH |
| **R3** native HW keys from Rust | **Viable both platforms, custom FFI (no turnkey crate).** macOS reproduces ADR-005 SE cleanly (`objc2-security`). Windows: **Hello `KeyCredentialManager` is RSA-only — cannot do P-256**; must use **CNG/NCrypt + Platform Crypto Provider (TPM)** with `NCRYPT_UI_POLICY` for the biometric prompt. | HIGH (MED on Win prompt modality) |
| **R4** WebAuthn over Tailscale | **Poor fit:** Tauri webview origin (`tauri://localhost`) ≠ `ts.net` RP ID, and URL mobility (localhost→ts.net→mac.local) bricks passkeys. **Custom challenge-response is URL-agnostic** and rides WireGuard. (`ts.net` is a PSL eTLD → RP ID must be `tailnetNNNN.ts.net`.) | HIGH |

**Convergent conclusion:** three independent tracks (R1, R2, R4) point *away* from real WebAuthn/passkeys for this topology, and R3 confirms the **custom challenge-response + native hardware sealing** path is buildable. **This contradicts ADR-023 §4** ("Passkeys / WebAuthn"), which was decided before this research — ADR-023 §4 needs revision.

## Recommendation: Option A — port the existing design to Tauri/Rust, swap Apple-SE → TPM/Hello

Keep everything the brain already implements and ADR-010/ADR-005 already designed; change only the **prover** (client signer) and the **host key primitive**:

- **Network/session auth:** custom P-256 ECDSA challenge-response (existing M2-a `SignedKeypairVerifier` + strictly-increasing counter — already built + tested). URL-agnostic (R4), rides Tailscale WireGuard.
- **Client signer (the prover):** hardware-backed, biometric-gated P-256 key on the client device. **Windows: CNG/NCrypt + TPM Platform Crypto Provider + `NCRYPT_UI_POLICY`** (NOT `KeyCredentialManager` — RSA-only, R3). **macOS: Secure Enclave + LAContext via `objc2-security`** (reproduces ADR-005). Generalises ADR-005's "phone Face-ID" to **any paired Tauri device with a biometric**.
- **Vault DEK wall:** native host-side sealing — **macOS SE** (end-state Mini), **Windows TPM** (CNG/NCrypt or DPAPI-NG) for dev. NOT passkey-PRF (R2). Recovery passphrase (ADR-005 refinement) stays as the independent recovery wrap.
- **Reframe the relay:** ADR-005's phone relay was a workaround for the **headless, Touch-ID-less Mini**. The challenge-response naturally supports both (a) **co-located dev** (brain + Tauri client on one Windows PC → local Hello, no relay/Tailscale needed) and (b) **end-state remote** (headless Mini host + remote Tauri client provides the assertion).

### Trade-offs accepted
- Custom FFI per platform (no turnkey crate; macOS medium, Windows medium-high effort).
- We maintain the prover code (but it's small, standard ECDSA, and the verifier already exists).
- Forgo WebAuthn's standardisation + cloud-synced passkey convenience (both of which actively hurt this topology today).
- **One gated build spike:** confirm `NCRYPT_UI_POLICY` on the TPM Platform Crypto Provider surfaces a Windows Hello **biometric** prompt (not PIN-only) from a Tauri process — the one MED-confidence unknown.

### Opposing view
The case for real passkeys (Option B): standard, phishing-resistant, no custom crypto to maintain, future-proof. **Why it's outweighed:** R1+R2+R4 show passkeys are actively hostile to a Tauri-over-Tailscale topology *today*, the PRF-as-wall story is the weakest link, and phishing-resistance is largely moot inside a private WireGuard tunnel with device-registered keys. Revisit only if (a) Tauri webview WebAuthn matures cross-platform AND (b) the cross-device PRF-stability bug is confirmed fixed.

## Implementation implications (for the re-anchor)
1. **Revise ADR-023 §4** — passkeys/WebAuthn → custom challenge-response + native hardware sealing (this research supersedes the pre-research call).
2. **New ADR (or ADR-010 + ADR-005 refinements)** — re-root the wall on TPM/Hello; generalise "phone" → "any paired biometric Tauri device"; document the co-located-dev vs remote-end-state duality.
3. **app-flow.md** — re-author for the Tauri desktop lock-states (still mechanical once the above lands).
4. **stack_skills** — drop `apex-swift`-for-clients; add web-frontend + Tauri (ADR-023 already says this).
5. **Gated build spike** — Windows CNG P-256 + `NCRYPT_UI_POLICY` biometric prompt from Tauri; signature encoding pinned (Windows raw `r||s` / macOS DER → match the verifier).

## Risks to monitor
- Windows biometric-prompt modality (could degrade to PIN-only → weakens the Windows-dev wall; it's dev-only, Mac is final host, so acceptable but note it).
- Signature-encoding mismatch (Win raw vs Mac DER vs verifier expectation).
- Custom-FFI maintenance burden across OS updates.

