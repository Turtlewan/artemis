---
spec: build-gate-consent
status: ready
token_profile: balanced
autonomy_level: L2
coder_model: codex
coder_effort: high
cross_model_review: true
---

# Spec: 5b — build-gate consent UI (plan-card egress + end-of-build credential pending item)

**Identity:** Client half of the build-flow gate: show a capability's `egress_domains` on the plan
card (network-scope consent up front) and, after the build completes, surface any `missing_secrets`
as an end-of-build pending item that deep-links into the 4b keys panel to capture each.
→ why: ADR-035 enabler #2 (build-flow gate); consumes step-5a PlanCard fields (egress_domains,
missing_secrets). Owner decision: build proceeds WITHOUT the credential; the key is an end-of-build
pending item, not a pre-build block.

**STYLING:** baseline only (UI overhaul comes later, owner directive) — keep it style-separable.

## Assumptions
- Step 5a shipped: the brain PlanCard now returns `egress_domains: string[]` + `missing_secrets:
  string[]` → the client just needs the matching DTO fields + rendering → impact: Caution (the DTO
  must match the brain shape exactly)
- 4b shipped `openKeys(pendingKey?: string)` in client/src/settings/keysStore.ts + a mounted
  `<KeysPanel>` (App.tsx) → the pending item's "Add key" deep-links via `openKeys(name)` → impact: Low
- The build flow lives in src/ask/askStore.ts (states: plan→status→result/installed) + renders in
  src/ask/AskPopup.tsx; the plan (BuildPlanCard) is stored on the plan message → impact: Caution
  (thread missing_secrets to where the end-of-build item renders)

Simplicity check: the pending item reads `missing_secrets` off the existing plan message (already in
the message list) rather than duplicating it onto the result message — no new askStore state if the
plan message is reachable at render; add threading only if it isn't.

## Prerequisites
- Specs complete first: secret-routes (4a), secret-capture-ui (4b), plan-card egress (5a)
- Environment: client Verification Recipe (tsc/eslint/vitest/cargo/clippy); node_modules + target exist

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| client/src/api/dto.ts | modify | `BuildPlanCard` += `egress_domains: string[]` + `missing_secrets: string[]` (match the brain PlanCard) |
| client/src/ask/AskPopup.tsx | modify | plan card shows egress (domains or "No network access") + flags missing secrets; after a successful build/promote, render an end-of-build "pending credentials" item listing each missing secret with an "Add key" button → `openKeys(name)` |
| client/src/ask/askStore.ts | modify | ONLY if the plan's missing_secrets isn't reachable where the pending item renders — thread it onto the result/installed message; otherwise no change |
| client/src/ask/AskPopup.test.tsx | create/modify | vitest: plan card renders egress + missing secrets; the end-of-build pending item appears when missing_secrets is non-empty and its button calls openKeys(name); no pending item when empty |

## Tasks
- [ ] Task 1: DTO — files: client/src/api/dto.ts — done when: `BuildPlanCard` has `egress_domains: string[]` and `missing_secrets: string[]`; `tsc` clean.
- [ ] Task 2: plan-card egress + build-time consent — files: client/src/ask/AskPopup.tsx — done when: the plan card renders the granted network scope (list `egress_domains`, or "No network access" when empty) alongside the existing secrets line, and visually flags which secrets are missing (from `missing_secrets`). Baseline styling.
- [ ] Task 3: end-of-build credential pending item — files: client/src/ask/AskPopup.tsx (+ askStore.ts only if needed) — done when: after a build reaches a successful result/installed state, if the plan's `missing_secrets` is non-empty, an end-of-build pending item renders listing each missing secret with an "Add key" button that calls `openKeys(name)` (imported from ../settings/keysStore) to deep-link into the keys panel. When `missing_secrets` is empty, no pending item shows. The build is NOT blocked on capturing the key (owner decision — pending, not a gate).
- [ ] Task 4: tests — files: client/src/ask/AskPopup.test.tsx — done when: the client test command passes: (a) a plan with egress_domains + missing_secrets renders both; (b) after a successful build the pending item appears and its "Add key" button invokes openKeys with the missing name; (c) empty missing_secrets → no pending item.

## Wave plan
Wave 1: [Task 1] | Wave 2: [Task 2, Task 3] | Wave 3: [Task 4]

## Permissions
### File Operations
| Action | Paths |
|--------|-------|
| Create | client/src/ask/AskPopup.test.tsx (if absent) |
| Modify | client/src/api/dto.ts, client/src/ask/AskPopup.tsx, client/src/ask/askStore.ts |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| (client Verification Recipe — tsc / eslint / vitest / cargo build / clippy) | per apex-tauri |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | client/src/api/dto.ts client/src/ask/AskPopup.tsx client/src/ask/askStore.ts client/src/ask/AskPopup.test.tsx |
| `git commit` | "feat: build-gate consent UI — plan-card egress + credential pending item" |

## Specialist Context
### Security
- Consent surface only — the plan card DISPLAYS egress_domains + missing secret NAMES (never values).
  Capturing a value reuses the 4b keys panel (session-token-in-Rust path); this spec adds no new
  command or transport. Informed consent: the owner sees network scope up front + which keys are
  needed before the capability can run.

### Performance
(none)

### Accessibility
- Baseline: the "Add key" control is a real button with an accessible label; the pending item is
  readable text. Full a11y/visual polish is the owner's later overhaul.

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | AskPopup.tsx | brief comments on the pending-item + deep-link |

## Acceptance Criteria
- [ ] Plan card shows egress + missing secrets → verify: Task 4 test (a)
- [ ] End-of-build pending item deep-links to capture → verify: Task 4 test (b): button calls openKeys(name)
- [ ] No pending item when nothing missing → verify: Task 4 test (c)
- [ ] Build not blocked on the key → verify: the build/promote flow is unchanged; the item is post-build
- [ ] Client gate green → verify: the client Verification Recipe passes (tsc/eslint/vitest/cargo/clippy)

## Progress
_(Coding mode writes here — do not edit manually)_
