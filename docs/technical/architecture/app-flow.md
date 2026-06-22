# Artemis client app — app flow

_The navigation + journey anchor for the **Tauri cross-platform desktop client** (the project's first UI
surface). Per-screen specs (the re-scoped CLIENT-* corpus) implement against this; keep them coherent with
this one anchor (ADR-013 technique). Originally created 2026-06-08 for the iPhone/iPad client (ADR-010);
**re-authored 2026-06-22 for the Tauri desktop client** — ADR-023 (replatform SwiftUI → Tauri) + ADR-025
(auth/wall re-root). Visual identity = `docs/technical/architecture/design-brief.md` ("Holo Tactical" +
the summon panel)._

Scope of v1: **full shell + Review + Chat + Status**, plus the onboarding/pairing + connection/auth flow
that every screen sits behind. Voice, Telegram, vision, and the domain-module spokes (M8+) are out of scope
for the v1 client.

**Platform scope (ADR-023): one Tauri app, web-tech frontend shipped as a native binary** — Windows `.exe`
now, recompiles to a macOS `.app` (and optionally iOS/Android via Tauri 2) later. The client is a **thin
client of the brain's HTTP/SSE gateway (M1-c) over Tailscale** (or loopback when co-located — see ADR-025
topology duality). No Swift, no Xcode.

## Surfaces (desktop — replaces the iOS tabs/split-view model)

Three native desktop surfaces over one shared state + connection layer:

- **Summon panel** — the primary quick-entry surface (global hotkey; design-brief "summon panel"). A frameless
  always-on-top panel: input line + results list with engine tags (`local`/`codex`/`review`). Fast in/out;
  dismisses on blur/Esc. Reads the same lock state as the main window.
- **Main window** — the full shell holding **Review · Chat · Status** (sidebar or segmented nav, not iOS tabs).
  Opened from the tray or the summon panel ("open full window").
- **Tray / menu-bar item** — persistent presence: lock/connection indicator, quick **Lock now** / **Open** /
  **Quit**, and the hotkey reminder.

## Connection + lock states (the spine — from ADR-010 §4, unchanged by the replatform)

The app is a thin client behind two **independent** lifetimes. Every surface reads these:

| State | Meaning | How reached | What works |
|-------|---------|-------------|------------|
| **Unpaired** | No device key registered with the brain/broker | First launch, or after revoke | Onboarding/Pairing only |
| **Paired · Disconnected** | Key registered; no live API session | App relaunch/expired, off-tunnel | Reconnect prompt; nothing brain-side |
| **Connected · Vault-locked** | API session valid; vault idle/locked | Session outlives the broker unlock window | **Status only**; Review **and** Chat prompt re-unlock (both read encrypted-volume data) |
| **Connected · Unlocked** | API session valid **and** vault unlocked | Fresh **biometric** assertion (connect or re-unlock) | Everything — Review (recipes) + Chat (memory/knowledge) |

Transitions: **Unpaired → (pair) → Connected·Unlocked** (one handshake establishes session **and** unlock,
ADR-010 §4). **Unlocked → (broker idle/lock) → Connected·Vault-locked** (API session survives). **Connected →
(app expiry / off-tunnel) → Disconnected**. Any state **→ (revoke device) → Unpaired**.

The biometric is **Windows Hello / macOS Touch ID** on the client device (ADR-025) — replacing the iPhone
Face-ID relay. In **co-located dev** (brain + client on one Windows PC) the assertion is a local Hello prompt
over loopback; in the **end-state remote** case the client signs and the headless host verifies + unwraps.

## Screens + navigation

```
        global hotkey
   ─────────────────────►  ┌──────────────────────┐
                           │     Summon panel     │  input line + results (engine tags)
   first launch ────────►  │  (frameless, on-top) │  ── "open full window" ──┐
   (Unpaired)              └──────────┬───────────┘                          │
        │                            │ pair / connect / unlock              │
        ▼                            ▼                                       ▼
   ┌────────────────────┐   ┌─────────────────────────────────────────────────┐
   │ Onboarding/Pairing │   │              Main window (shell)                 │
   │ enter pairing code │   │  lock banner reflects vault state                │
   │ ▸ Hello/Touch ID   │   ├───────────────┬───────────────┬─────────────────┤
   │ ▸ register key     │   │    Review     │     Chat      │     Status      │
   │ ▸ unlock           │   │   (default)   │              │                 │
   └────────────────────┘   └───────────────┴───────────────┴─────────────────┘
                                        ▲
                       re-unlock prompt (Hello/Touch ID)  ◄── modally over any screen when an
                                                               action needs the vault and it is idle-locked

   Tray/menu-bar: lock/connection indicator · Lock now · Open · Quit · hotkey hint
```

### Onboarding / Pairing (unauthenticated; the bootstrap)
- **Journey:** brain shows a **pairing code** (out-of-band: brain CLI / local screen) → user **enters/pastes
  it** in the app → app **generates the device hardware keypair** (non-exportable: Windows TPM via CNG /
  macOS Secure Enclave — ADR-025) → **biometric** (Hello/Touch ID) → app sends `(device_id, public_key,
  pairing_code-signed assertion)` to the brain's **pairing-bootstrap** endpoint → brain registers the key in
  **both** the broker (`pair`) and its app-auth registry (ADR-010 §1) → app immediately runs the
  **connect + unlock** handshake → lands on **Review**.
- **States:** the only screen reachable while **Unpaired**. Re-runnable (idempotent pair) if interrupted.
- **Errors:** wrong/expired code → retry; off-tunnel → "can't reach Artemis, check your connection."

### Review  *(default — the milestone's reason for existing)*
- **Source:** M7-b `ReviewSurface` via CLIENT-b endpoints. Renders `pending_for_review()` (gated recipes
  awaiting approval) and `auto_enabled()` (what was auto-enabled, for transparency), each with M7-b's
  **deterministic plain-language `explanation`** (no LLM).
- **Actions:** **Approve** → `ReviewSurface.approve` (owner-gated commit → recipe `ENABLED`); **Reject** →
  `ReviewSurface.reject` (→ `RETIRED`). Optimistic row update; reconcile on response.
- **Lock:** requires **Unlocked** — recipes live on the M2 per-scope encrypted volume (M7-a1 / ADR-007), so
  listing/approving them needs the vault open. If **Vault-locked**, the screen raises the **re-unlock prompt**
  (Hello/Touch ID) before loading.
- **Empty state:** "Nothing waiting for your review." (the common case).

### Chat
- **Source:** M1-c `/ask` + `/ask/stream` (SSE) exposed behind app-auth by CLIENT-b.
- **Journey:** type → **stream tokens** as they arrive (instant-ack masks TTFT, brain.md). Shows the
  answer + a dim footer (path / tool / engine tag, from `AskResponse`).
- **Lock:** Chat touches memory/knowledge → requires **Unlocked**. If **Vault-locked**, sending raises
  the **re-unlock prompt** first, then proceeds.

### Status
- **Source:** broker `status` + the app-auth session, via a CLIENT-b status endpoint.
- **Shows:** connection state, vault lock state (+ time-to-idle-lock), this device's pairing info; a
  **Lock now** action (explicit vault lock) and a **Disconnect / Sign out** action (drop the API session).
- **Lock:** works in any **Connected** state (it *is* the lock UI). Mirrored in the tray.

## Cross-screen rules
- **The lock banner** (vault-locked / unlocked) is global chrome across the main window, summon panel, and
  tray, driven by the state table above.
- **No scope/identity is ever sent by the client** — the brain derives it from the session (ADR-010 §3).
- **Engine tags are load-bearing** — `local` / `codex` / `review` visibility on result rows is a product
  requirement (privacy/cost transparency), not decoration (design-brief forbidden-patterns).
- **Accessibility (desktop):** full keyboard operability (the summon panel is keyboard-first), visible focus
  order, screen-reader labels, and per-palette contrast on the ambient theme (apex-accessibility; the Review
  explanations are already plain-language). Detailed criteria live in the re-scoped CLIENT shell spec.
- **Reduced motion:** streaming/transitions honour `prefers-reduced-motion` (apex-animation; the design-brief
  mockups already gate animation off under it).
