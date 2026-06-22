# ADR-023 — Client re-platform: Tauri cross-platform desktop (supersedes ADR-017)

- **Status:** Accepted — **supersedes ADR-017**
- **Date:** 2026-06-22
- **Deciders:** owner + planning
- **Relates:** **ADR-017 (macOS SwiftUI client — SUPERSEDED)** · ADR-010 (client app auth — re-expressed for a desktop client, see ADR-025) · ADR-005 §Refinement 2026-06-22 (recovery passphrase) · ADR-022 (build-Windows-first; brain = always-on host) · **ADR-025 (auth/wall re-root — supersedes §4 below)**.

> **Revision 2026-06-22 — §4 unlock mechanism REVERSED → ADR-025.** §4 below provisionally chose **passkeys / WebAuthn**. A four-track deep-dive (`docs/findings/tauri-auth-deep-dive/`) found passkeys a poor fit for this Tauri-over-Tailscale topology: WebAuthn is unreliable in Tauri webviews (R1), passkey-PRF-derived DEK wrapping is fragile across device sync (R2), and RP-ID/origin binding breaks under the planned URL mobility (R4). **Superseded by ADR-025:** unlock = **custom P-256 challenge-response + native hardware sealing** (Windows TPM/Hello via CNG, macOS Secure Enclave/Touch ID), reusing the already-built brain-side verifier. The recovery passphrase is unchanged. §4's struck-through text is retained below for history.

## Context
ADR-017 chose **native SwiftUI clients** (Mac + iPhone + iPad), which are Xcode/macOS-gated — they cannot be built or tested off a Mac. The owner wants to build the UI **now, on this Windows PC**, as a **real desktop app (`.exe`)** — explicitly *not* a web app and *not* Swift — while keeping the multi-surface end-state.

## Decision

| # | Decision | Statement |
|---|----------|-----------|
| 1 | **Framework** | The client is a **Tauri** cross-platform desktop app. Web-tech frontend (React/Tailwind — apex-frontend skills) shipped as a **native binary**: `.exe` on Windows now, recompiles to a macOS `.app` (and optionally iOS/Android via Tauri 2) later. **No Swift, no Xcode.** |
| 2 | **Role** | It is a **client** of the brain's HTTP/SSE gateway (M1-c) over Tailscale. The brain runs separately on the always-on host. |
| 3 | **Scope** | Replaces the SwiftUI client layer of all **CLIENT-\*** specs (chat · status · recipe Review · GATE pending-actions · settings). **Supersedes ADR-017.** |
| 4 | **Unlock** (iff the privacy wall is kept — ADR-022) | ~~**Passkeys / WebAuthn** (SE-backed biometric assertion from the device) + the **recovery passphrase** (ADR-005 refinement), replacing ADR-005's custom App-Attest scheme.~~ **REVERSED → ADR-025** (see Revision note above): **custom P-256 challenge-response + native hardware sealing** (Windows TPM/Hello via CNG; macOS Secure Enclave/Touch ID), reusing the M2-a verifier; **recovery passphrase unchanged**. Moot if the wall is retired. |
| 5 | **Swift footprint** | `apex-swift` shrinks to — at most — the **voice audio sidecar** (a separate later decision); it is no longer a client stack. |

## Consequences
- The **entire client layer comes off the Mac critical path** — PC-buildable now against the WSL2/dev brain (ADR-022 Windows-first).
- **`stack_skills` shifts:** drop `apex-swift`-for-clients; add web-frontend + Tauri.
- **CLIENT-a..f re-scoped** to Tauri; **ADR-010** auth re-expressed for a desktop client by **ADR-025** (the Apple-SE-per-device prover becomes a hardware-backed P-256 key on any paired biometric device — Windows TPM/Hello or macOS SE; the brain-side challenge-response verifier is unchanged).

## Alternatives considered
- **Web app (served in a browser)** — *rejected*: owner wants a `.exe`, not a browser tab.
- **Electron** — heavier (~150 MB) for no gain over Tauri.
- **Flutter** — true cross-platform incl. mobile, but Dart drops the web-skill base.
- **Keep SwiftUI (ADR-017)** — *rejected*: Mac/Xcode-gated, blocks build-now.

## Parked (build-phase)
Exact Tauri project structure · passkey enrolment flow · whether a thin native iOS shim is ever needed for mobile.
