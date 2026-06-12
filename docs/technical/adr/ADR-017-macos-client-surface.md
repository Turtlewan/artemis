# ADR-017 — macOS client surface (native multiplatform, Athena-style)

- **Status:** Accepted · **Date:** 2026-06-12 · **Deciders:** owner + planning
- **Relates:** ADR-001 (stack — SwiftUI app) · ADR-002 (deployment — native clients, **no web UI**) · ADR-010 (client↔brain paired-device auth — the registry already supports N devices) · overview.md §Interaction surfaces · CLIENT-c (ArtemisKit shared SPM package) · CLIENT-d (iOS app shell) · CLIENT-e (screens) · research `docs/research/2026-06-12-multiplatform-swift-client.md`. Trigger: owner wants end-state coverage — a native Mac app ("like Athena"), not just iPhone/iPad.

## Context

The client was specced as a **universal iOS app (iPhone + iPad)** only (CLIENT-d: `platform: iOS`). The brain is a **headless Python appliance** on the Mac Mini; every Swift app is a **thin client** reaching it over the Tailscale tunnel via the authenticated `/app/*` API. The owner wants Artemis usable as a **native Mac app** day-to-day, alongside iPhone/iPad — one codebase, three surfaces.

The audit found the groundwork already cross-platform: **`ArtemisKit` (CLIENT-c) is platform-agnostic by design** ("no SwiftUI, no UIKit, unit-tests on macOS"; system frameworks only — URLSession/CryptoKit/LocalAuthentication/Security), and **the screens (CLIENT-e) are already size-class-adaptive**. So a Mac surface is **additive**, not a rewrite. Research (2026-06-12, macOS 26 / iOS 26 era) settled the four open questions: target structure, Mac form factor, auth portability, and personal-use distribution.

## Decision

1. **Add a native macOS client as a first-class surface.** End-state: **Mac + iPhone + iPad**, one shared core. The Mac is the day-to-day desktop surface (a MacBook or any Mac over Tailscale); the **Mini stays headless** (loopback only if ever run on the Mini with a display).

2. **Structure: a separate native `ArtemisMac` app target sharing the `ArtemisKit` SPM package** — *not* a single multiplatform target. Rationale: the Mac build ships **outside the App Store** (Developer ID), and its **scene graph diverges** (menu-bar + floating panel + window) from the iOS tab/split-view shell. Use **native SwiftUI (AppKit-backed)** — **not** Mac Catalyst (a bridge for legacy UIKit apps; Artemis has none) and **not** "Designed for iPad on Mac" (the non-native feel the owner explicitly rejected). All platform divergence lives in the **view/scene layer** (`#if os(macOS)` / `Sources/macOS`), never in `ArtemisKit`.

3. **Mac form factor: the Athena-style stack** (research recommendation, owner-accepted): **`MenuBarExtra(.window)`** as the always-available home + a **global-hotkey floating `NSPanel`** (summon-from-anywhere; `NSStatusItem`/`NSHostingView` + the `KeyboardShortcuts` SPM dependency) + a singleton **`Window`** (`.hiddenTitleBar`) for full Chat/Review history + a **`Settings`** scene. Optionally `LSUIElement` for a Dock-iconless ambient presence. The three primitives coexist in one app; the floating surface **must** be an `NSPanel` (SwiftUI `WindowGroup`+`openWindow` misbehaves for float-on-top across Spaces/full-screen).

4. **The Mac is just another paired device (ADR-010 unchanged).** It generates its **own** Secure-Enclave P-256 keypair at pairing, registered with both the broker (vault-unlock authority) and the brain app-auth registry (API-session authority). ADR-010's registry already supports N devices, so this is **additive** — no change to the auth protocol, only a new enrolled device.

5. **Auth portability behind one `AuthService` (a Mac code path in ArtemisKit).** The SE-P256 + `LAContext` + `SecKey` model ports to Apple-Silicon Macs (Touch ID) with the **same APIs** (`biometryType` adapts at runtime). Four deltas handled in the Mac code path: (a) opt into the **data-protection keychain** (`kSecUseDataProtectionKeychain`) so access-group/SE semantics match iOS — the main footgun; (b) a **passcode / `deviceOwnerAuthentication` fallback** for Macs with **no biometric** (the Mini case); (c) modality-aware prompt strings; (d) verify the `.biometryCurrentSet .or .devicePasscode` prompt behaviour on hardware. **(a)–(c) are determinate now; (d) and the Mini-fallback are hardware-gated — parked as build-time verification, not planning blockers.**

6. **Distribution (personal use):** **Developer ID Application cert + notarization + Hardened Runtime** (so it launches cleanly on the owner's Macs). Entitlements: **App Sandbox ON** + **Keychain Sharing** (`keychain-access-groups`) + **network-client**; SE/biometrics need no extra entitlement. **App Sandbox is enabled** (revised 2026-06-12 after the apex-security review): the data-protection keychain (`kSecUseDataProtectionKeychain`) works correctly under sandbox with the declared `keychain-access-groups`, and `KeyboardShortcuts` uses sandbox-compatible Carbon hotkeys (`RegisterEventHotKey`, not a `CGEvent` tap) — so the global-hotkey panel still works. For an app holding the SE key that unlocks the owner's private vault, the OS containment is worth the entitlement precision (defense-in-depth; the initial "skip sandbox for convenience" call was reversed).

## Consequences

- **Spec changes (front-loaded into the same batch handoff — does NOT delay existing iOS work):**
  - **New spec `CLIENT-f` (ArtemisMac target + Athena scene):** XcodeGen macOS target, the MenuBarExtra + NSPanel(global-hotkey) + Window + Settings scene graph, `KeyboardShortcuts` dep, reusing CLIENT-e screens in Mac chrome, Developer-ID/notarization/Hardened-Runtime config. Atomic-target exception to the 3-file split rule (precedent: CLIENT-d).
  - **CLIENT-c amended:** a macOS auth code path in `Signer`/`KeychainStore` (data-protection keychain + passcode fallback + `deviceOwnerAuthentication`), behind the existing `Signer`/`Authenticator` seam — module stays SwiftUI/UIKit-free.
  - **CLIENT-e:** confirm a few `#if os(macOS)` view tweaks (already adaptive — trivial).
  - **overview.md §Interaction surfaces + ADR index + ROADMAP** updated to name the Mac surface.
- **Two hardware-gated auth unknowns** (Mini biometric-less fallback; macOS 26 `.or` passcode prompt) → resolved on the first real Mac build, recorded in handoff. Mirrors the existing on-hardware gating across the corpus.
- **apex-swift recipe is still v0.1.0 unvalidated** — the first Mac build validates it (→ 1.0.0).
- **Dependency order:** CLIENT-f builds on CLIENT-c/d/e (shared kit + screens) — same wave as the rest of CLIENT; no new milestone.

## Alternatives considered

- **Single multiplatform target (one app, Mac destination)** — *rejected*: Apple's own guidance is "separate target if you ship the Mac build outside the App Store" (Artemis's case), and the Mac scene graph diverges enough that a shared scene would be `#if`-soup. (Soft call — revisit only if the Mac UI converges to near-identical to iPad.)
- **Mac Catalyst** — *rejected*: a UIKit-bridge for porting legacy iPad apps; Artemis is pure SwiftUI with no UIKit to bridge, and Catalyst's Mac feel is second-tier.
- **"Designed for iPad on Mac"** (run the iPad app unmodified) — *rejected*: explicitly the non-native, website-like feel the owner is rejecting.
- **Web UI** — *rejected* long ago (ADR-002, no owner data in a browser; native-only posture).
- **Tailscale-only trust (no per-device Mac credential)** — *rejected* for the same reasons as ADR-010 §Alternatives (coarse, no per-device revocation).
