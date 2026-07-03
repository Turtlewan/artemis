---
spec: cb5b-2-map-nodes-ui
status: draft
token_profile: lean
autonomy_level: L5
coder_effort: medium
---

# Spec: Capability nodes on the map + full-page overlay (CB-5b Phase 1, client)

**Identity:** Render each built capability as a node on the WorldPlane (name + pending-count badge, "99+"), auto-placed + drag-persisted via the existing layout store, opening a large full-page overlay with the capability's detail.
→ why: see docs/technical/adr/ADR-045-capability-map-nodes.md (decisions 1–4)

## Assumptions
- Placement reuses the existing `LayoutStore`/`/app/layout` (LWW) — a capability node is a `CardPlacement` keyed by `id = "cap:<name>"`; no brain change for placement → impact: Stop
- The full-page overlay reuses the existing `card/DetailOverlay` + `useCardOverlay` pattern → impact: Caution
- `GET /app/capabilities` returns `goal`, `built_at`, `uses`, `secrets`, egress, `auth_status` (from `capability-metadata` + verify-auth); a `pending_count` field is 0/absent until Phase 2 → impact: Stop
- The client stack is Tauri + TS (apex-tauri); session token stays in Rust (gateway command pattern) → impact: Stop

Simplicity check: node badge omitted when count is 0 (Phase 1) — no empty "0" clutter.

## Prerequisites
- **`capability-metadata`** (the DTO must carry `goal`/`built_at`/`auth_status`/`oauth_scopes` — supersedes the former `cb5b-1-capability-metadata`, folded into the one consolidated metadata spec 2026-07-03). `verify-auth-unverified-mark` optional (populates `auth_status`; overlay degrades gracefully if absent).
- **Forge goal-population (1-line, do here or as a small forge task):** `capability-metadata` defines `SkillDraft.goal`/`Skill.goal` (default `""`) but does NOT populate it. The forge must set the staged draft's `goal` from `BuildProposal.goal` when it stages (so the node card shows the owner's original ask). Add that wiring as part of this spec (or a tiny forge follow-up) — without it, `goal` renders empty.

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| client/src/api/dto.ts | modify | extend the capability DTO (goal, built_at, uses, secrets, egress, auth_status, pending_count?) |
| client/src/api/gateway.ts | modify | `listCapabilities()` wrapper (if not present) returning the typed rows |
| client/src-tauri/src/gateway.rs | modify | `app_capabilities_list` command (session token in Rust) if not already exposed |
| client/src/world/WorldPlane.tsx | modify | render capability nodes as cards at their placements; badge (name + count, "99+"); click → overlay |
| client/src/world/capabilityNodes.ts | create | derive nodes from the capabilities list; auto-seed a ring-near-CORE `CardPlacement` when none exists; persist drag via layoutBridge |
| client/src/card/CapabilityOverlay.tsx | create | the large full-page overlay: name, goal, built_at, uses list, trust info (egress/secrets/auth_status), items placeholder |
| client/src/world/capabilityNodes.test.ts, client/src/card/CapabilityOverlay.test.tsx | create | node-derivation + "99+" + overlay-content tests |

## Tasks
- [ ] Task 1: DTO + gateway — extend the capabilities DTO in `dto.ts` (goal, built_at, uses, secrets, egress_domains, auth_status?, pending_count?), add/confirm the `listCapabilities` gateway wrapper + the `app_capabilities_list` Tauri command (token stays in Rust). — files: client/src/api/dto.ts, client/src/api/gateway.ts, client/src-tauri/src/gateway.rs — done when: `listCapabilities()` returns typed rows incl. goal/built_at; cargo builds.
- [ ] Task 2: Node derivation + placement — `capabilityNodes.ts`: map each capability to a node keyed `cap:<name>`; if the layout store has no `CardPlacement` for it, auto-seed one on a ring around CORE (deterministic angle by name hash) and PUT via `layoutBridge`; expose a `formatCount(n)` → `n>99 ? "99+" : String(n)`. — files: client/src/world/capabilityNodes.ts, client/src/world/capabilityNodes.test.ts — done when: N capabilities → N placed nodes; a node with no prior placement gets a stable seeded position; `formatCount(150)==="99+"`, `formatCount(0)===""` (badge hidden).
- [ ] Task 3: Render + overlay — `WorldPlane.tsx` renders the nodes (name + badge) at their placements, drag persists (existing layoutBridge LWW), click opens `CapabilityOverlay` (reuse `useCardOverlay`). `CapabilityOverlay.tsx` shows name, goal, built_at, the `uses` list (click-through, not a graph), and trust info (egress/secrets/auth_status); an "items" region is a Phase-2 placeholder. — files: client/src/world/WorldPlane.tsx, client/src/card/CapabilityOverlay.tsx, client/src/card/CapabilityOverlay.test.tsx — done when: nodes render + drag-persist; clicking opens the overlay with goal/built_at/uses/trust; tsc/eslint/vitest green.

## Wave plan
Wave 1: [Task 1] | Wave 2: [Task 2] | Wave 3: [Task 3]

## Permissions
### File Operations
| Action | Paths |
|--------|-------|
| Create | client/src/world/capabilityNodes.ts, client/src/world/capabilityNodes.test.ts, client/src/card/CapabilityOverlay.tsx, client/src/card/CapabilityOverlay.test.tsx |
| Modify | client/src/api/dto.ts, client/src/api/gateway.ts, client/src-tauri/src/gateway.rs, client/src/world/WorldPlane.tsx |
### Commands
| Command | Purpose |
|---------|---------|
| `npm --prefix client run check` (tsc) + `npm --prefix client run lint` | type/lint (confirm exact scripts) |
| `npm --prefix client test` (vitest) | client tests |
| `cargo build --manifest-path client/src-tauri/Cargo.toml` | Rust gateway compiles |
### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | the files above |
| `git commit` | "feat(client): capability map nodes + overlay (CB-5b)" |

## Specialist Context
### Security
Session token stays in Rust (gateway command). No secret values rendered — only secret NAMES + egress domains in the trust panel.
### Accessibility
Node badge + overlay: keyboard-openable, focus-trapped overlay (reuse DetailOverlay's a11y), count badge has an aria-label ("N pending").

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Changelog | CHANGELOG.md | Unreleased/Added — capability nodes on the map |

## Acceptance Criteria
- [ ] With 3 capabilities returned, WorldPlane shows 3 nodes at stable positions; dragging one and reloading keeps its position (LWW persisted).
- [ ] A capability with `pending_count` 0/absent shows name only (no badge); 150 shows "99+".
- [ ] Clicking a node opens the full-page overlay showing goal, built_at, the `uses` list, and egress/secrets/auth_status; Esc/close returns to the map.
- [ ] tsc clean; eslint clean; vitest green; cargo builds.

## Progress
_(Coding mode writes here)_
