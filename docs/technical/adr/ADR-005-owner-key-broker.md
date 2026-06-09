# ADR-005 — Owner-key delivery: remote-attested key-broker (M2 security wall)

**Status:** Accepted (SP0 phase 6, M2 key-model deep-dive, 2026-06-04)
**Builds on:** ADR-001 (SQLCipher per-scope) · ADR-002 (launchd, Tailscale, native appliance) · ADR-004 (memory in SQLCipher). Research: `docs/research/owner-key-brain-architecture.md`. Paired with ADR-006 (two-tier proactivity).

## Context
Owner data lives in per-scope **SQLCipher** DBs, each encrypted with a data-encryption key (DEK). LOCKED rule: data is unlockable **only by that person** (biometric); FileVault (whole-disk, boot-time) does NOT satisfy it. The **brain is an always-on background service** that needs the DEK to read/write owner data — but it "isn't the owner." Two hard platform facts decide the architecture:
1. **Biometry-gated Secure-Enclave keychain items only work in a user login context — NOT from a `LaunchDaemon`.**
2. **The Mac Mini has no Touch ID** → no local biometric; the biometric must originate on the owner's iPhone.

## Decision
A **remote-attested key-broker** (Pattern B + a slice of C):

| Element | Decision |
|--------|----------|
| **Key-broker** | A minimal, hardened **LaunchAgent** (runs in the owner's user session) is the ONLY process that touches the Secure-Enclave key. Exposes a tiny local IPC (XPC/Unix socket, peer-credential + code-signing checked) to the brain. |
| **DEK wrapping** | Each per-scope SQLCipher DEK (32-byte random) is **ECIES-wrapped to a Secure-Enclave key** (`.eciesEncryptionStandardX963SHA256AESGCM`); ciphertext on disk; SE private key non-exportable. SE access-control flag = **`.userPresence`** on the Mini-side key (no local biometric exists; biometric is enforced on the phone). |
| **Remote unlock** | Owner does **Face ID on the iPhone** → phone returns a **fresh-nonce + monotonic-counter signed assertion** over the Tailscale tunnel (App Attest **or** an SE-backed signing keypair registered at pairing — build-time choice, same replay-proof contract). **Neither the DEK nor biometric data ever crosses the wire** — only the signed proof. |
| **Verification** | Broker verifies signature against the registered phone public key + **counter strictly increasing** (replay/rollback block) → unwraps the DEK via `SecKeyCreateDecryptedData`. |
| **Key handling** | DEK passed to the brain over local IPC into **mlock'd memory**; SQLCipher opened via raw-hex-key (`PRAGMA key="x'…'"`, no runtime PBKDF2) with `cipher_memory_security` on. **Session-only**: zeroized on idle timeout / explicit lock / brain restart. |
| **Unlock-once-per-session** | Broker-enforced session lifetime + idle re-lock; one phone unlock covers the session until it re-locks. |
| **Boot/headless** | Broker is a LaunchAgent → Mini uses **owner auto-login at boot** so the agent loads after a power cut. Auto-login does NOT unlock data (still needs the phone proof). Re-check macOS 26.x for lifting the daemon restriction → would drop auto-login. |
| **Brain** | Stays a LaunchDaemon (per ADR-002); receives only a transient DEK. Never touches the SE key. |

## Runner-ups ruled out
- **A — brain reads the login keychain directly:** fails the LOCKED rule on a headless no-Touch-ID Mini (degrades to "unlocked at login" ≈ FileVault); whole brain in the keyed blast radius.
- **C — raw key only on the phone, sent over the wire:** best at-rest story but puts the raw DEK on the wire and makes the phone a brittle single point. We borrow its "biometric-on-phone" idea via a *signed assertion*, not its raw-key transport.
- **24/7 service-held DEK:** defeats the wall (≈ FileVault). Rejected.

## Consequences
- **Smallest trusted base** — only the tiny auditable broker touches the SE key; the large, injection-exposed brain holds only a transient session DEK.
- **Honours the LOCKED wall, strictly stronger than FileVault** — no phone proof → no key; guest/thief cannot open owner data; nothing usable at rest on a powered-off stolen Mini.
- **⭐ Irreducible core risk:** a prompt-injected tool exfiltrating the DEK from the live brain during a session → keep the DEK in a native crypto boundary the model/tool layer can't address; scoped tool I/O; egress filtering. **Deepest apex-security focus.**
- **Phone = key authority** → phone loss = key compromise; need enrol/de-enrol/rotate/escrow flows.
- **ADR-002 addition:** a new **broker LaunchAgent** + **owner auto-login**; the brain remains a LaunchDaemon.
- **Cross-milestone:** M2 builds the broker + wall; M3/M4 stores born encrypted under this DEK model; M6 proactivity uses the Tier-0 proactive key (ADR-006). **Refinement (ADR-007):** the broker also **mounts a per-scope encrypted volume** on unlock (holding the LanceDB doc index + the SQLCipher memory DB) — one unlock opens the whole per-scope vault. The M2 broker specs gain this volume-mount step at finalization.

## Build-time spikes (gated tasks at M2)
Prototype App-Attest (or SE-signed-keypair) appliance↔phone assertion loop · confirm `.userPresence` semantics on the Mini-side SE key (doesn't degrade to login-unlock) · verify SQLCipher `cipher_memory_security` on Apple Silicon · verify auto-login + FileVault boot yields a usable owner session for the LaunchAgent · re-verify the daemon/data-protection-keychain restriction on the running macOS 26 build.

## apex-security threat-model gate
Fires at M2 before any sensitive store is built (M3/M4). Focus areas = the five residual risks in the research doc, led by prompt-injection DEK exfiltration.
