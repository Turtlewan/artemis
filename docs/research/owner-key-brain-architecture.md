# Owner-key ↔ always-on-brain architecture — research (2026-06-04)

_Grounds ADR-005 (owner-key broker) + ADR-006 (two-tier proactivity). Single deep-dive agent, Apple primary sources. Confidence: HIGH on Apple platform mechanics; MEDIUM on proactivity patterns. Re-verify the daemon/keychain constraint on each macOS 26.x release._

## The decisive constraint
On macOS, **biometry-gated Secure-Enclave keychain items (the "data-protection keychain") only work inside a user login context — NOT from a `LaunchDaemon`** [VERIFIED — Apple docs/forums]. Combined with **the Mac Mini having no local Touch ID**, the brain cannot be a root system daemon that biometrically unwraps the data key locally. → biometric authority must live on the **iPhone**; the key-touching component must be a **LaunchAgent**.

## Decision (→ ADR-005 + ADR-006)
**B+C hybrid — a "remote-attested key-broker":** a minimal hardened **LaunchAgent** key-broker is the only process that touches a per-scope **Secure-Enclave-wrapped** SQLCipher key; it releases the key to the brain (over local IPC, into mlock'd memory, session-only, zeroized on idle/lock/restart) **only after verifying a fresh, replay-proof signed assertion from the owner's iPhone** (biometric happens on the phone; only a signed proof crosses the Tailscale tunnel — never the key or biometric data). Proactivity is **two-tier** (→ ADR-006).

## Key mechanics (Apple, 2026 — VERIFIED)
- **SE keys** (`SecKeyCreateRandomKey` + `kSecAttrTokenIDSecureEnclave`) are EC-only, non-exportable; do ECIES/ECDH/sign **inside** the enclave.
- **Wrap/unwrap the DEK:** ECIES-encrypt the 32-byte SQLCipher data-encryption key (DEK) to the SE key's public key (`SecKeyCreateEncryptedData`, `.eciesEncryptionStandardX963SHA256AESGCM`); store ciphertext on disk; unwrap via `SecKeyCreateDecryptedData` on the SE private key whose `SecAccessControl` gates the op.
- **Access-control flag:** prefer **`.userPresence`** over `.biometryCurrentSet` on the **Mini-side** SE key (the Mini has no biometric; the real biometric is enforced on the phone). ⚠️ Confirm this doesn't degrade to "unlocked at login" — flag for the apex-security pass.
- **SQLCipher:** use the raw-hex-key path (`PRAGMA key = "x'<64hex>'"`) so no runtime PBKDF2; enable `cipher_memory_security` (lock pages vs swap); zeroize the key buffer on lock.
- **Remote unlock:** **App Attest** assertion (server-issued nonce + monotonic sign counter) gives a replay-proof, device-bound proof. ⚠️ App-Attest is app↔Apple-server by design; appliance↔phone use is slightly off-label → **prototype it**. Simpler alternative: a plain **SE-backed signing keypair on the phone** (biometry-gated), public key registered with the broker at pairing — same nonce+signature+counter replay model, no Apple-server dependency. Build-time choice behind one "signed proof" contract.
- **Tailscale** secures the channel (node-key mutual auth + E2E) but is NOT owner-auth (a compromised tailnet device is still trusted) → the assertion layer sits on top.
- **Session/zeroization:** session lifetime is a broker-enforced app concept (idle timer + explicit lock + brain-restart → zeroize). Client-side `touchIDAuthenticationAllowableReuseDuration` (≤5min) only smooths the *phone* UX.

## Patterns evaluated
| Pattern | Verdict |
|---|---|
| **A — brain in owner account reads login keychain** | Fails the LOCKED rule on a headless no-Touch-ID Mini (degrades to "unlocked at login" ≈ FileVault). Whole brain in blast radius. **Rejected.** |
| **B — key-broker LaunchAgent** | **Spine of the recommendation.** Smallest trusted base; brain only ever holds a transient DEK. |
| **C — key only on phone, sent over wire** | Best at-rest story but raw DEK transits the tunnel + phone = brittle single point. **Borrow its "biometric-on-phone" idea via signed assertion, not its raw-key-on-wire.** |

## Operational wart
Broker must be a LaunchAgent (user session) → Mini needs **owner auto-login at boot** so the agent loads after a power cut. Safe: auto-login does NOT unlock data (still needs the phone proof). Re-check whether macOS 26.x lifts the daemon restriction (would drop auto-login).

## Two-tier proactivity (→ ADR-006)
- **Tier 0 (always-on, no owner DEK):** Heartbeat runs over **low-sensitivity, pre-minimised** data behind a separate small **"proactive key"** (`.userPresence`, device-bound, unwrapped at boot) — calendar/weather/public context + derived bits (thresholds, reminder times), **read-mostly**, never raw finance/health/journal.
- **Tier 1 (sensitive):** anything needing a real per-scope DEK is **queued for the next owner session**, or runs in a short, opt-in, **append-only-audited unlock window** the owner pre-approves per task.
- Rejected: a 24/7 service-held DEK (defeats the wall ≈ FileVault).

## Threat model (per surface)
- **Brain compromise (DEK in memory during a live session):** exposure ≤ current session; broker + SE key intact. Mitigate: short session, aggressive idle-zeroize, mlock, never DEK→disk/log/swap. Irreducible core: code-exec in the brain during an unlocked session.
- **Mini stolen powered-OFF:** only ECIES ciphertext on disk; unwrap needs SE key + phone proof. Strong (+ FileVault at-rest).
- **Mini stolen powered-ON, session live:** worst case (DEK in RAM) → short idle-lock + periodic re-assertion.
- **Remote replay/MITM:** defeated by Tailscale E2E + fresh-nonce + increasing counter. A fully-compromised enrolled phone can mint proofs → treat phone loss as key-compromise (remote de-enrol/rotate).
- **Build-agent (separate macOS user):** no path to the owner data-protection keychain or broker IPC (peer-cred + code-signing ACL).
- **⭐ Prompt-injected tool exfiltrating the DEK:** highest-likelihood threat — the brain holds the DEK during a session. Keep the DEK in a native crypto boundary the model/tool layer cannot address; scoped tool I/O; egress filtering; all tool/web/file content = untrusted data. **Deepest apex-security focus.**

## Residual risks → apex-security pass focus
1. Prompt-injection DEK/data exfil from the live brain (the core).
2. `.userPresence` vs `.biometryCurrentSet` semantics on the Mini-side key.
3. Proactive-key scope creep (keep the always-on corpus genuinely minimised).
4. Phone-as-authority compromise/loss → enrol/de-enrol/rotate/escrow.
5. macOS 26.x daemon/data-protection-keychain status (version-dependent).

## Sources
Apple: Protecting keys with the Secure Enclave · `kSecUseDataProtectionKeychain` (daemon limitation) · `biometryCurrentSet`/`userPresence` · `touchIDAuthenticationAllowableReuseDuration` · App Attest (WWDC21 10244) · Platform Security (keychain/biometric). SQLCipher (zetetic.net). Tailscale (how-it-works/security). Reference impl: Secretive (SE keys via launch agent).
