---
spec: plan-gate-egress
status: ready
token_profile: lean
autonomy_level: L5
coder_effort: low
---

# Spec: Plan-gate egress visibility

**Identity:** Surface a capability's granted `egress_domains` on the build approval PlanCard so the owner sees which network domains a build is granted before approving "Build it" (informed-consent gap).

## Assumptions
- The brain already exposes `egress_domains` on `PlanCard` (`src/artemis/api/capability_routes.py:42-56`, populated at `/propose` from `draft.egress_domains`, line 145) — NO brain change needed → impact: Stop
- The TS DTO already carries it (`client/src/api/dto.ts:189-199`, `BuildPlanCard.egress_domains`) and the render already displays it (`client/src/ask/AskPopup.tsx:455-463` maps `plan.egress_domains`) — NO TS change needed → impact: Stop
- The ONLY missing link is the Rust gateway `PlanCard` struct (`client/src-tauri/src/gateway.rs:82-90`), which omits `egress_domains` — so serde drops the field when the plan flows brain → Rust gateway → webview, leaving `plan.egress_domains` undefined at the render → impact: Stop

Simplicity check: no simpler version — it is already a one-field addition. Considered adding brain/TS/render changes; rejected — they already exist (verified by reading the files).

## Prerequisites
- none. File-disjoint from all other pending specs (client Rust only).

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| client/src-tauri/src/gateway.rs | modify | add `egress_domains: Vec<String>` to the `PlanCard` struct so serde deserializes it from the brain and re-serializes it to the webview |

## Tasks
- [ ] Task 1: Add `egress_domains: Vec<String>` to the `PlanCard` struct in `client/src-tauri/src/gateway.rs` (the struct at ~line 82, alongside `secrets`/`missing_secrets`). Match the field name exactly (`egress_domains`, snake_case) so it maps to the brain JSON and the TS `BuildPlanCard.egress_domains`. — files: client/src-tauri/src/gateway.rs — done when: the struct compiles with the field and a proposed plan's egress domains reach the webview.

## Permissions
### File Operations
| Action | Paths |
|--------|-------|
| Modify | client/src-tauri/src/gateway.rs |

### Commands
| Command | Purpose |
|---------|---------|
| `cd client/src-tauri && cargo build` | Rust compile gate |
| `cd client && npm run tauri build` (or `cargo clippy`) | full client build/lint (as available) |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | client/src-tauri/src/gateway.rs |
| `git commit` | "fix(client): pass egress_domains through the gateway to the build plan card" |

## Acceptance Criteria
- [ ] `client/src-tauri/src/gateway.rs` `PlanCard` struct contains `egress_domains: Vec<String>` → verify `cargo build` succeeds.
- [ ] A proposed capability with a non-empty `egress_domains` → verify the plan card in the Ask popup lists the domains (the render at `AskPopup.tsx:455-463` now receives them, no longer undefined).

## Progress
_(Coding mode writes here — do not edit manually)_
