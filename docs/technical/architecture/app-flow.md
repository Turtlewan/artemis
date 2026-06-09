# Artemis client app — app flow

_The navigation + journey anchor for the iPhone/iPad client (the project's first UI surface). Per-screen
specs (CLIENT-c/d) implement against this; keep them coherent with this one anchor (ADR-013 technique).
Created 2026-06-08 alongside ADR-010 (auth) — the client milestone._

Scope of v1 (chosen 2026-06-08): **full shell + Review + Chat + Status**, plus the onboarding/pairing +
connection/auth flow that every screen sits behind. Voice, Telegram, vision, and the domain-module spokes
(M8+) are out of scope for the v1 client.

**Device scope (chosen 2026-06-08): Universal — iPhone + iPad polished to parity.** Adaptive layout from
day one: the root shell is **bottom tabs on compact width (iPhone) → `NavigationSplitView` sidebar on
regular width (iPad)**; iPad gets larger-canvas affordances + keyboard shortcuts. Both surfaces are
primary/tested in v1 (not iPhone-first-iPad-later).

## Connection + lock states (the spine — from ADR-010)

The app is a thin client behind two **independent** lifetimes (ADR-010 §4). Every screen reads these:

| State | Meaning | How reached | What works |
|-------|---------|-------------|------------|
| **Unpaired** | No device key registered with the brain/broker | First launch, or after revoke | Onboarding/Pairing only |
| **Paired · Disconnected** | Key registered; no live API session | App backgrounded/expired, off-tunnel | Reconnect prompt; nothing brain-side |
| **Connected · Vault-locked** | API session valid; vault idle/locked | Session outlives the broker unlock window | **Status only**; Review **and** Chat prompt re-unlock (both read encrypted-volume data) |
| **Connected · Unlocked** | API session valid **and** vault unlocked | Fresh Face-ID assertion (connect or re-unlock) | Everything — Review (recipes) + Chat (memory/knowledge) |

Transitions: **Unpaired → (pair) → Connected·Unlocked** (one handshake establishes session **and** unlock,
ADR-010 §4). **Unlocked → (broker idle/lock) → Connected·Vault-locked** (API session survives). **Connected →
(app expiry / off-tunnel) → Disconnected**. Any state **→ (revoke device) → Unpaired**.

## Screens + navigation

```
                          ┌────────────────────────┐
   first launch  ───────► │  Onboarding / Pairing   │  (unauthenticated)
   (Unpaired)             │  scan QR ▸ Face ID ▸     │
                          │  register key ▸ unlock   │
                          └───────────┬─────────────┘
                                      │ paired + connected + unlocked
                          ┌───────────▼─────────────┐
                          │  Root shell (adaptive)  │  (lock banner reflects vault state)
                          │  tabs ↔ split-view      │  compact=bottom tabs · regular=sidebar
                          ├──────────┬──────────┬───┤
                          │  Review  │   Chat   │ Status │   ◄── Review is the default/first destination
                          │  (first) │          │        │
                          └──────────┴──────────┴───┘
                                      ▲
                          re-unlock sheet (Face ID)  ◄── modally over any tab when an action needs
                                                          the vault and it is idle-locked
```

### Onboarding / Pairing (unauthenticated; the bootstrap)
- **Journey:** brain shows a pairing code/QR (out-of-band: brain CLI / local screen) → app **scans/enters
  it** → app **generates the SE keypair** (non-exportable) → **Face ID** → app sends `(device_id, public_key,
  pairing_code-signed assertion)` to the brain's **pairing-bootstrap** endpoint → brain registers the key in
  **both** the broker (`pair`) and its app-auth registry (ADR-010 §1) → app immediately runs the
  **connect + unlock** handshake → lands on **Review**.
- **States:** the only screen reachable while **Unpaired**. Re-runnable (idempotent pair) if interrupted.
- **Errors:** wrong/expired code → retry; off-tunnel → "can't reach Artemis, check your connection."

### Review  *(default tab — the milestone's reason for existing)*
- **Source:** M7-b `ReviewSurface` via CLIENT-b endpoints. Renders `pending_for_review()` (gated recipes
  awaiting approval) and `auto_enabled()` (what was auto-enabled, for transparency), each with M7-b's
  **deterministic plain-language `explanation`** (no LLM).
- **Actions:** **Approve** → `ReviewSurface.approve` (owner-gated commit → recipe `ENABLED`); **Reject** →
  `ReviewSurface.reject` (→ `RETIRED`). Optimistic row update; reconcile on response.
- **Lock:** requires **Unlocked** — recipes live on the M2 per-scope encrypted volume (M7-a1 / ADR-007), so
  listing/approving them needs the vault open. If **Vault-locked**, the tab raises the **re-unlock sheet**
  (Face ID) before loading.
- **Empty state:** "Nothing waiting for your review." (the common case).

### Chat
- **Source:** M1-c `/ask` + `/ask/stream` (SSE) exposed behind app-auth by CLIENT-b.
- **Journey:** type → **stream tokens** as they arrive (instant-ack masks TTFT, brain.md). Shows the
  answer + a dim footer (path / tool / escalated, from `AskResponse`).
- **Lock:** Chat touches memory/knowledge → requires **Unlocked**. If **Vault-locked**, tapping send raises
  the **re-unlock sheet** (Face ID) first, then proceeds.

### Status
- **Source:** broker `status` + the app-auth session, via a CLIENT-b status endpoint.
- **Shows:** connection state, vault lock state (+ time-to-idle-lock), this device's pairing info; a
  **Lock now** action (explicit vault lock) and a **Disconnect / Sign out** action (drop the API session).
- **Lock:** works in any **Connected** state (it *is* the lock UI).

## Cross-screen rules
- **The lock banner** (vault-locked / unlocked) is global chrome, driven by the state table above.
- **No scope/identity is ever sent by the client** — the brain derives it from the session (ADR-010 §3).
- **Accessibility:** every screen is VoiceOver-labelled, Dynamic Type-respecting, and 44pt touch targets
  (apex-accessibility); the Review explanations are already plain-language. Detailed criteria live in the
  CLIENT-d spec.
- **Reduced motion:** streaming/transitions honour `Reduce Motion` (apex-animation).
