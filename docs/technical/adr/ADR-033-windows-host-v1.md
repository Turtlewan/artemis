# ADR-033 — Windows-host v1 (run on the dev box; Mac deferred to migration)

**Status:** Accepted 2026-06-26
**Refines:** ADR-022 (Windows-first build) · ADR-001 (Mac Mini appliance — deferred, not dropped) · ADR-025 (client TPM/Hello unlock) · ADR-005 (SE key broker — Mac end-state, deferred)

## Context
The dev-buildable corpus is ~90% built + host-verified on the Windows/WSL2 box. Two big unknowns
were resolved 2026-06-26: the cognitive layer runs on real local models (Ollama `qwen3:4b` +
`qwen3-embedding:0.6b`, first live signal), and the Tauri client compiles cleanly under MSVC (whole
dep tree; only a missing `icon.ico` short of a built `.exe`). The Mac Mini is **not bought**. Rather
than gate a running system on hardware, the owner chose to make **this Windows PC the actual running
host (v1)** and treat Mac as a later migration.

## Decision
1. **Windows is the v1 running host.** Mac becomes a migration target, not a prerequisite for a
   running system.
2. **Subsystem substitutions (Windows now → Mac later):**
   - Local models: **Ollama + CUDA** (RTX 5060 Ti 8GB) — not MLX.
   - Voice: the **Windows voice twin** (Moonshine/Kokoro + headphones AEC) — not CoreAudio/MLX.
   - Client unlock: **TPM 2.0 + Windows Hello** (already chosen in ADR-025) — not SE/Touch ID.
   - Daemon/scheduling: **Windows Service / Task Scheduler** — not launchd (M0-b).
   - Tunnel / push (Tailscale, ntfy): unchanged, cross-platform.
3. **Security wall = LIGHTER INTERIM (owner choice).** Encryption-at-rest via a SQLCipher DEK
   **sealed to the machine's TPM 2.0 / DPAPI**, unlocked via **Windows Hello**; **single-user, NO
   phone-attestation, NO two-tier proactive key**. The full ADR-005 phone-attested SE broker +
   two-tier proactivity (ADR-006) is **deferred to the Mac** (its natural hardware home). The
   `KeyProvider` + `sqlcipher_open` seams already exist (M2-c dev shim), so this is a **backend swap**
   ("M2-win"), not a re-architecture.
4. **8GB VRAM constraint accepted.** Models are juggled (not all resident at once); the sensitive
   reasoner uses a **smaller** local model on Windows until the Mac's larger memory hosts the 27B /
   distilled reasoner.

## Consequences
- **New build (M2-win):** a Windows-native `KeyProvider` (DPAPI/TPM seal + Hello unlock) + real
  SQLCipher keyed by it, replacing the plain-SQLite dev shim. Contained — the injection seams exist.
- **Mac migration =** swap three backends behind existing seams: KeyProvider sealing (TPM→SE), model
  runtime (Ollama→MLX), daemon (Service→launchd). Protocol + app code carry over; the lighter
  Windows wall is therefore *mostly* not throwaway (the cross-platform `KeyProvider`/challenge
  contract is reused; only the sealing backend changes).
- **Interim privacy posture:** encrypted-at-rest + Hello-gated + single-user — weaker than the
  phone-attested two-tier end-state, **accepted as interim** while this box is the trusted solo host.
- Unblocks a genuinely-running (and reasonably-private) Artemis on Windows without waiting on the
  Mac purchase. The Mac decision remains open (ADR-001) but is no longer on the critical path to v1.

## Refinement 2026-06-27 — Windows brain runtime (launch mechanism)

How the brain process runs on Windows (no `launchd`). **Decision: dev-process now → background
service end-state; Tauri sidecar rejected.**

- **Now (⑤a `win-brain-runtime`):** a `uvicorn` dev launcher (`artemis-brain`, 127.0.0.1:brain_port).
  ADR-033's "lighter interim" — gets the stack live without packaging work; pure Python, runs on Mac
  verbatim. The proactive **heartbeat is started in the FastAPI lifespan** as a cancellable
  background task (it was never wired before — proactivity was dark).
- **Rejected: Tauri sidecar** (bundling the brain into the app). The proactive heartbeat must keep
  running when the app window is closed (it delivers via ntfy); a sidecar ties the brain's life to
  the window and would **silence proactivity**. The sidecar is only correct for an app that does
  nothing while closed — Artemis is the opposite.
- **End-state: a background service** — a Windows service/Task-Scheduler entry now-ish, whose Mac
  twin is **`launchd` (M0-b, already specced)**. Same always-on posture; the daemon backend is the
  one piece that differs per OS (already noted in this ADR's Mac-migration seam list).
- **Reversibility:** the dev-process choice is throwaway-free for the transport — the client's
  `brain_base_url` wiring and the whole `/app/*` contract are identical regardless of launcher; only
  "who starts uvicorn" changes.
