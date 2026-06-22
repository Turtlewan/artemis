# ADR-023 — Client re-platform: Tauri cross-platform desktop (supersedes ADR-017)

- **Status:** Accepted — **supersedes ADR-017**
- **Date:** 2026-06-22
- **Deciders:** owner + planning
- **Relates:** **ADR-017 (macOS SwiftUI client — SUPERSEDED)** · ADR-010 (client app auth — re-expressed for a desktop client + passkeys) · ADR-005 §Refinement 2026-06-22 (recovery passphrase) · ADR-022 (build-Windows-first; brain = always-on host).

## Context
ADR-017 chose **native SwiftUI clients** (Mac + iPhone + iPad), which are Xcode/macOS-gated — they cannot be built or tested off a Mac. The owner wants to build the UI **now, on this Windows PC**, as a **real desktop app (`.exe`)** — explicitly *not* a web app and *not* Swift — while keeping the multi-surface end-state.

## Decision

| # | Decision | Statement |
|---|----------|-----------|
| 1 | **Framework** | The client is a **Tauri** cross-platform desktop app. Web-tech frontend (React/Tailwind — apex-frontend skills) shipped as a **native binary**: `.exe` on Windows now, recompiles to a macOS `.app` (and optionally iOS/Android via Tauri 2) later. **No Swift, no Xcode.** |
| 2 | **Role** | It is a **client** of the brain's HTTP/SSE gateway (M1-c) over Tailscale. The brain runs separately on the always-on host. |
| 3 | **Scope** | Replaces the SwiftUI client layer of all **CLIENT-\*** specs (chat · status · recipe Review · GATE pending-actions · settings). **Supersedes ADR-017.** |
| 4 | **Unlock** (iff the privacy wall is kept — ADR-022) | **Passkeys / WebAuthn** (SE-backed biometric assertion from the device) + the **recovery passphrase** (ADR-005 refinement), replacing ADR-005's custom App-Attest scheme. Moot if the wall is retired. |
| 5 | **Swift footprint** | `apex-swift` shrinks to — at most — the **voice audio sidecar** (a separate later decision); it is no longer a client stack. |

## Consequences
- The **entire client layer comes off the Mac critical path** — PC-buildable now against the WSL2/dev brain (ADR-022 Windows-first).
- **`stack_skills` shifts:** drop `apex-swift`-for-clients; add web-frontend + Tauri.
- **CLIENT-a..f re-scoped** to Tauri; **ADR-010** auth re-expressed for a desktop client + passkeys (the SE-key-per-device model is replaced by passkeys).

## Alternatives considered
- **Web app (served in a browser)** — *rejected*: owner wants a `.exe`, not a browser tab.
- **Electron** — heavier (~150 MB) for no gain over Tauri.
- **Flutter** — true cross-platform incl. mobile, but Dart drops the web-skill base.
- **Keep SwiftUI (ADR-017)** — *rejected*: Mac/Xcode-gated, blocks build-now.

## Parked (build-phase)
Exact Tauri project structure · passkey enrolment flow · whether a thin native iOS shim is ever needed for mobile.
