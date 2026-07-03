---
spec: cb5b-4-refresh-ui
status: draft
token_profile: lean
autonomy_level: L5
coder_effort: medium
---

# Spec: Refresh opt-in + live count/items UI (CB-5b Phase 2, client)

**Identity:** The client half of live attention: a per-capability "background refresh" opt-in toggle in the overlay, the live pending-count badge on the node, and the surfaced items list in the overlay.
→ why: see docs/technical/adr/ADR-045-capability-map-nodes.md (decision 5)

## Assumptions
- The backend (`cb5b-3`) exposes `pending_count` + an items payload on the capabilities/overlay DTO and a `POST /app/capabilities/{name}/refresh-optin` route → impact: Stop
- The node + overlay already exist (`cb5b-2`); this extends them → impact: Stop
- Opting a capability into background refresh means it runs credentialed on a timer — the toggle copy must say so (informed consent), mirroring the bless-card wording → impact: Caution

Simplicity check: reuse the node badge + overlay from cb5b-2; this only adds the toggle + wires live data.

## Prerequisites
- `cb5b-2-map-nodes-ui` (node + overlay) and `cb5b-3-refresh-backend` (DTO fields + optin route).

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| client/src/api/dto.ts | modify | add `pending_count` + items to the capability DTO type |
| client/src/api/gateway.ts | modify | `setRefreshOptin(name, enabled, intervalS)` wrapper |
| client/src-tauri/src/gateway.rs | modify | `app_capability_refresh_optin` command (token in Rust) |
| client/src/card/CapabilityOverlay.tsx | modify | render the items list; add the "background refresh" opt-in toggle (informed-consent copy) |
| client/src/world/capabilityNodes.ts | modify | badge reads live `pending_count` |
| client/src/card/CapabilityOverlay.test.tsx, client/src/world/capabilityNodes.test.ts | modify | toggle + live-count + items tests |

## Tasks
- [ ] Task 1: Gateway — `setRefreshOptin(name, enabled, intervalS)` TS wrapper + the `app_capability_refresh_optin` Tauri command (session token stays in Rust). Extend the capability DTO with `pending_count` + items. — files: client/src/api/gateway.ts, client/src-tauri/src/gateway.rs, client/src/api/dto.ts — done when: the wrapper calls the route; cargo builds.
- [ ] Task 2: Overlay toggle + items — in `CapabilityOverlay.tsx`, add a "Refresh in the background" toggle whose label states it runs the capability on a timer using its credentials (informed consent); wire it to `setRefreshOptin`; render the surfaced `items` (title + detail) in the overlay's items region. — files: client/src/card/CapabilityOverlay.tsx, client/src/card/CapabilityOverlay.test.tsx — done when: toggling calls the route with the right args; items render; the consent copy is present.
- [ ] Task 3: Live badge — `capabilityNodes.ts` badge reads live `pending_count` ("99+" rule from cb5b-2); a not-opted-in capability shows no badge. — files: client/src/world/capabilityNodes.ts, client/src/world/capabilityNodes.test.ts — done when: a capability with cached count 5 shows badge "5"; 150 shows "99+"; count 0 / not-opted-in shows no badge.

## Wave plan
Wave 1: [Task 1] | Wave 2: [Task 2, Task 3]

## Permissions
### File Operations
| Action | Paths |
|--------|-------|
| Modify | client/src/api/dto.ts, client/src/api/gateway.ts, client/src-tauri/src/gateway.rs, client/src/card/CapabilityOverlay.tsx, client/src/world/capabilityNodes.ts, client/src/card/CapabilityOverlay.test.tsx, client/src/world/capabilityNodes.test.ts |
### Commands
| Command | Purpose |
|---------|---------|
| `npm --prefix client run check` + `npm --prefix client run lint` + `npm --prefix client test` | client gate |
| `cargo build --manifest-path client/src-tauri/Cargo.toml` | Rust compiles |
### Git Operations
| Operation | Scope |
|-----------|-------|
| `git commit` | "feat(client): refresh opt-in + live pending-count UI (CB-5b)" |

## Specialist Context
### Security
The opt-in toggle is an informed-consent surface — its copy must state background refresh runs the capability credentialed on a timer (mirror the bless card). No secret values shown. Items are untrusted content rendered as text (no HTML injection).
### Accessibility
Toggle is keyboard-operable with a clear label; items list is navigable; badge aria-label "N pending".

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Changelog | CHANGELOG.md | Unreleased/Added — refresh opt-in + live counts UI |

## Acceptance Criteria
- [ ] Toggling "Refresh in the background" calls `app_capability_refresh_optin(name, enabled, interval)`; the consent copy names the credentialed-timer behavior.
- [ ] The overlay renders the surfaced items (title + detail) from the DTO.
- [ ] Node badge shows the live count ("5", "99+"); count 0 / not-opted-in → no badge.
- [ ] tsc/eslint/vitest green; cargo builds.

## Progress
_(Coding mode writes here)_
