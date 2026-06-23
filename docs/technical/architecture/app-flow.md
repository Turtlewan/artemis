# Artemis client app — app flow

_The navigation + journey anchor for the **Tauri cross-platform desktop client** (the project's first UI
surface). Per-screen specs (the CLIENT-* corpus) implement against this anchor (ADR-013 technique)._

_History: created 2026-06-08 (iOS client, ADR-010) → re-authored 2026-06-22 for the Tauri desktop client
(ADR-023 replatform + ADR-025 auth/wall) → **re-authored 2026-06-23 for ADR-028: the home is a spatial
"travel-zoom" command-map, which SUPERSEDES the earlier Review/Chat/Status tab-shell.** Platform = Tauri
(ADR-023); auth/lock = ADR-025; visual identity + the travel-zoom interaction = `design-brief.md`. Reference
mockup (the feel): `docs/research/mockups/travel-zoom-workspace.html`._

Scope of v1: **the command-map shell + domain open/close + the Ask-Artemis pop-up + Status**, plus the
onboarding/pairing + connection/auth flow that every surface sits behind. Voice, Telegram, vision, and the
domain-module spokes beyond the v1 card set are out of scope for the v1 client.

**Platform scope (ADR-023): one Tauri app, web-tech frontend shipped as a native binary** — Windows `.exe`
now, recompiles to a macOS `.app` (and optionally iOS/Android via Tauri 2) later. The client is a **thin
client of the brain's HTTP/SSE gateway (M1-c) over Tailscale** (or loopback when co-located — ADR-025
topology duality). No Swift, no Xcode.

## Surfaces (spatial map — replaces the iOS tabs / the desktop tab-shell)

- **Command-map (home)** — the primary surface: a **pannable, zoomable spatial map** of **domain glance
  cards** arranged around a central pulsing **brain core** (some cards off-screen by design). The resting
  view is brain-centred. (design-brief "travel-zoom".)
- **Domain detail** — opening a domain flies the camera across to its card, then the card **expands open in
  place** into a **top-most detail panel** floating over the still-visible, lightly-dimmed map; it collapses
  back into the card on close. Review · Status · Schedule · Tasks · Memory · etc. are domains reached this way.
- **Ask-Artemis pop-up** — a distinct floating chat panel summoned anywhere (global hotkey / top-bar button),
  visually separate from the domain cards. This is the chat surface (formerly its own tab).
- **Tray / menu-bar item** — persistent presence: lock/connection indicator, quick **Lock now** / **Open** /
  **Quit**, and the hotkey reminder.

## Connection + lock states (the spine — from ADR-010/ADR-025, unchanged by the nav change)

The app is a thin client behind two **independent** lifetimes. Every surface reads these:

| State | Meaning | How reached | What works |
|-------|---------|-------------|------------|
| **Unpaired** | No device key registered with the brain/broker | First launch, or after revoke | Onboarding/Pairing only |
| **Paired · Disconnected** | Key registered; no live API session | App relaunch/expired, off-tunnel | Reconnect prompt; nothing brain-side |
| **Connected · Vault-locked** | API session valid; vault idle/locked | Session outlives the broker unlock window | Map + **Status** only; opening Review **or** Chat prompts re-unlock (both read encrypted-volume data) |
| **Connected · Unlocked** | API session valid **and** vault unlocked | Fresh **biometric** assertion (connect or re-unlock) | Everything — all domains + Chat (memory/knowledge) |

Transitions: **Unpaired → (pair) → Connected·Unlocked** (one handshake establishes session **and** unlock).
**Unlocked → (broker idle/lock) → Connected·Vault-locked** (API session survives). **Connected → (app expiry
/ off-tunnel) → Disconnected**. Any state **→ (revoke device) → Unpaired**.

The biometric is **Windows Hello / macOS Touch ID** on the client device (ADR-025): a local Hello/Touch-ID
prompt over loopback in co-located dev; the client signs and the headless host verifies + unwraps in the
end-state remote case.

## Map + navigation

```
                                   ⌥Space / "Ask" button
   first launch ──► Onboarding/Pairing ──(pair·connect·unlock)──►  ┌───────── Ask-Artemis pop-up ─────────┐
   (Unpaired)                                                       │  floating, top-most, over any view    │
        │                                                           └───────────────────────────────────────┘
        ▼
   ┌──────────────────────── Command-map (home) ────────────────────────┐
   │   top bar: brand · crumb · Home · status dots · Ask · (lock banner) │
   │                                                                     │
   │        [Schedule]        ( ◎ brain core )        [Tasks]            │   pan = drag
   │   [People]                                            [Diet&Fit]    │   zoom = scroll (toward cursor)
   │        [Finance]                                  [Travel]          │   off-screen cards reachable via
   │                                                                     │     dock / minimap / fly-to
   │   minimap ◰                                   dock ▣▣▣▣▣▣           │
   └─────────────────────────────────────────────────────────────────────┘
            │ click card / dock / minimap → camera travels across → card EXPANDS OPEN
            ▼
   ┌──── Domain detail (top-most, over the lightly-dimmed map) ────┐     ✕ / Esc / Home → collapse back
   │  full content for that domain (Review cards · agenda · …)     │
   └───────────────────────────────────────────────────────────────┘
   re-unlock prompt (Hello/Touch ID) ◄── modally when opening a domain that needs the vault while idle-locked
   Tray/menu-bar: lock/connection indicator · Lock now · Open · Quit · hotkey hint
```

### Onboarding / Pairing (unauthenticated; the bootstrap)
- **Journey:** brain shows a **pairing code** (out-of-band) → user enters it → app generates the device
  hardware keypair (Windows TPM via CNG / macOS Secure Enclave — ADR-025) → **biometric** (Hello/Touch ID) →
  app sends `(device_id, public_key, pairing_code-signed assertion)` to the brain's pairing-bootstrap
  endpoint → brain registers the key in **both** the broker and its app-auth registry → app runs the
  **connect + unlock** handshake → **lands on the command-map (home)**.
- **States:** the only surface reachable while **Unpaired**. Re-runnable (idempotent pair) if interrupted.
- **Errors:** wrong/expired code → retry; off-tunnel → "can't reach Artemis, check your connection."

### Domains on the map (the screens, reached by travel-zoom)
- **Review** *(the milestone's reason for existing)* — **Source:** M7-b `ReviewSurface` via CLIENT-b. Opens
  from its map card; renders `pending_for_review()` + `auto_enabled()` with M7-b's deterministic
  plain-language `explanation`. **Actions:** Approve → `ReviewSurface.approve`; Reject → `ReviewSurface.reject`
  (optimistic, reconcile on response). **Lock:** requires **Unlocked** (recipes on the encrypted volume); if
  Vault-locked, opening it raises the re-unlock prompt. **Empty:** "Nothing waiting for your review."
- **Chat → the Ask-Artemis pop-up** — **Source:** M1-c `/ask` + `/ask/stream` (SSE) behind app-auth
  (CLIENT-b). Summon with the hotkey / top-bar; stream tokens (instant-ack masks TTFT); answer + a dim footer
  (path / tool / engine tag). **Lock:** touches memory/knowledge → requires **Unlocked**; sending while
  locked raises the re-unlock prompt.
- **Status** — **Source:** broker `status` + the app-auth session via a CLIENT-b status endpoint. Shows
  connection state, vault lock state (+ time-to-idle-lock), this device's pairing info; **Lock now** +
  **Disconnect / Sign out**. **Lock:** works in any **Connected** state (it *is* the lock UI). Mirrored in the
  tray and the top-bar lock banner.
- **Other domains** (Schedule · Tasks · Finance · Diet & Fitness · People · Travel · Memory · Email — the v1
  card set, illustrative) — glance card → expand to detail; per-domain lock rules follow data sensitivity
  (owner-private data → Unlocked). Detail content per domain is the existing module surface; the map only
  changes *how you reach it*.

## Cross-screen rules
- **The lock banner** (vault-locked / unlocked) is global chrome (top bar) across the map, domain detail,
  the Ask pop-up, and the tray, driven by the state table above.
- **No scope/identity is ever sent by the client** — the brain derives it from the session (ADR-010 §3 /
  ADR-025).
- **Engine tags are load-bearing** — `local` / `codex` / `review` visibility is a product requirement
  (privacy/cost transparency), not decoration (design-brief forbidden-patterns).
- **The overview never content-scrolls** — the map navigates by **pan + zoom only**; glance cards never
  scroll internally (ADR-028). Domain detail panels may scroll internally if their content overflows.
- **Accessibility (desktop):** full keyboard operability — the **dock** + **Home** + **Esc** give
  keyboard-reachable navigation to every domain (including off-screen ones), so navigation never depends on
  pointer pan/zoom; visible focus order; screen-reader labels; per-palette contrast on the ambient theme
  (apex-accessibility).
- **Reduced motion:** the camera travel + card expand collapse to a **crossfade** under
  `prefers-reduced-motion` (apex-animation).
