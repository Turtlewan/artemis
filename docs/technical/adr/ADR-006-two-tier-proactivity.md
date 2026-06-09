# ADR-006 — Two-tier proactivity (security-vs-proactivity resolution)

**Status:** Accepted (SP0 phase 6, M2 key-model deep-dive, 2026-06-04)
**Builds on:** ADR-005 (owner-key broker) · brain.md § Proactive engine (Heartbeat). Research: `docs/research/owner-key-brain-architecture.md`.

## Context
The Heartbeat / proactive engine wants to act **while the owner is away/locked** (overnight briefings, spending alerts). But ADR-005 makes the owner DEK available **only during an unlocked session** (phone-attested). These pull in opposite directions: always-on proactivity vs "key only when unlocked." A 24/7 service-held DEK would resolve it but defeats the security wall (≈ FileVault) — rejected.

## Decision
**Two tiers of proactivity:**

| Tier | When | Data it may touch | Key |
|------|------|-------------------|-----|
| **Tier 0 — always-on** | Continuously, even while locked | **Low-sensitivity, pre-minimised** only: calendar/weather/public context + *derived* bits (budget thresholds, reminder times, "due today" flags) — **never** raw finance/health/journal/episodic records. **Read-mostly.** | A separate, small **"proactive key"** (`.userPresence`, device-bound, unwrapped at boot — protects only the minimised corpus) |
| **Tier 1 — sensitive** | Only when the owner is present | Real per-scope owner data | The session DEK (ADR-005) — so it **queues for the next owner session**, OR runs in a short, opt-in, **append-only-audited unlock window** the owner pre-approves per task |

## Runner-ups ruled out
- **Service-held owner DEK 24/7** — defeats the wall. Rejected.
- **Broad pre-authorised unlock windows** — a window where data is decryptable with no fresh biometric is a theft/replay window; only allowed **narrow-scope, short, audited, per-task opt-in** (the constrained Tier-1 option).

## Consequences
- Overnight/locked proactivity still delivers value (the light, derived stuff); **the standing-while-locked secret is reduced to a deliberately minimised, mostly-derived corpus**, bounding the blast radius of always-on work.
- Full-fidelity sensitive proactivity still requires a fresh phone unlock — accepted trade-off.
- **Cross-milestone:** M6 (Heartbeat) implements the two tiers; the Tier-0 proactive key is provisioned at M2 alongside the per-scope DEKs; the minimised-corpus derivation is a per-module concern (modules emit Tier-0-safe derived signals via their manifest).
- **apex-security focus:** prevent **proactive-key scope creep** — audit exactly what the Tier-0 corpus can decrypt; keep it minimised and read-mostly.

## Parked (build-phase)
Exact minimised-corpus schema per module · the unlock-window UX + audit-log format · whether Tier-0 needs its own tiny store or rides a non-sensitive partition.
