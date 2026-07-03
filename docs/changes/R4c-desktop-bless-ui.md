---
spec: R4c-desktop-bless-ui
status: ready
autonomy_level: L5
coder_effort: medium
---

# Spec: R4c — desktop bless / revoke UI

**Identity:** Brain routes + Tauri/TS client UI to bless a capability and see/revoke the blessed list from the desktop — parity with the Telegram bless-from-chat, over the rich card.
→ why: see docs/technical/adr/ADR-043-telegram-inbound-and-bless-consent.md (decisions 4, 5, 8)

## Assumptions
- `BlessStore` (from R4b) is the single source of truth; the desktop routes read/write the SAME shared JSON under `ARTEMIS_DATA_DIR` the runner's gate uses → impact: Stop
- Bless is version-scoped: the desktop toggle blesses the capability's CURRENT `Skill.version`; the UI shows "blessed (v2)" and reflects auto-reset after an update (stored version ≠ current) as un-blessed → impact: Stop
- Desktop bless is session-gated (same AppAuth session as other `/app/*` routes) → impact: Stop
- The client map/keys surfaces already exist (capability nodes + keys panel); the toggle attaches to the capability's detail/summary, not a new screen → impact: Caution

## Prerequisites
- `R4b-bless-invoke-gate` (defines `BlessStore` + its data-file location/format — this spec depends on it; NOT file-disjoint via `bless.py` semantics, so build after R4b).
- No file overlap with `verify-auth-unverified-mark` (that spec edits capability_routes.py/CapabilitySummary; this spec adds a NEW `bless_routes.py` rather than editing capability_routes.py, to avoid the collision — call this out at build).

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| src/artemis/api/bless_routes.py | create | session-gated `GET /app/bless` (list), `POST /app/bless/{name}` (bless current version), `DELETE /app/bless/{name}` (unbless) |
| src/artemis/api/app.py | modify | wire `BlessStore` onto `app.state` (shared data dir) + include `bless_routes.router` |
| client/src-tauri/src/commands.rs (or equivalent) | modify | `app_bless_list` / `app_bless_set` / `app_bless_clear` commands (session token stays in Rust) |
| client/src/api/bless.ts (or gateway module) | create | TS wrappers over the commands |
| client/src/... capability detail + keys panel | modify | a "Allow from Telegram" toggle on a capability + a blessed-list view with revoke |
| tests (brain) tests/api/test_bless_routes.py | create | route behavior |

## Tasks
- [ ] Task 1: Brain bless routes + wiring. Create `src/artemis/api/bless_routes.py` (session-gated list/bless/unbless over `BlessStore`); in `src/artemis/api/app.py` construct `BlessStore(resolved_data_dir / "bless.json")` onto `app.state.bless` and `include_router(bless_routes.router)`. Blessing reads the capability's current `Skill.version` from `capability_store.get(name)` and blesses that version; blessing an unknown capability → 404. — files: src/artemis/api/bless_routes.py, src/artemis/api/app.py, tests/api/test_bless_routes.py — done when: list/bless/unbless round-trip through the shared store; bless records the current version; session-gated (401 without session).
- [ ] Task 2: Client gateway. Tauri commands `app_bless_list/set/clear` (session token in Rust) + TS wrappers. — files: client/src-tauri commands, client/src/api/bless.ts — done when: the three commands call the routes with the session token and return typed results; `tsc`/`eslint`/`cargo`/`clippy` clean.
- [ ] Task 3: Client UI. A "Allow from Telegram" toggle on a capability's detail (shows blessed-vX / off; toggling calls set/clear) + a blessed-list with per-row revoke (reuse the keys-panel list idiom). Baseline styling (owner refines visuals). — files: client/src capability detail + keys/blessed view — done when: toggling reflects the brain state and a revoke removes the row; `vitest` green.

## Wave plan
Wave 1: [Task 1] | Wave 2: [Task 2] | Wave 3: [Task 3]

## Permissions
### File Operations
| Action | Paths |
|--------|-------|
| Create | src/artemis/api/bless_routes.py, client/src/api/bless.ts, tests/api/test_bless_routes.py |
| Modify | src/artemis/api/app.py, client/src-tauri commands, client/src capability detail + keys panel |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy` · `uv run ruff check` · `uv run pytest -q` | brain verify |
| `npm run tsc` · `npm run lint` · `npm run test` · `cargo clippy` | client verify (per client Verification Recipe) |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | the files above + CHANGELOG.md |
| `git commit` | "feat(client): desktop bless / revoke for Telegram invoke" |

## Specialist Context
### Security
Session-gated like other `/app/*` routes. Bless writes go through the same shared `BlessStore` the runner gate reads — the R4b apex-security review covers the store's atomicity/version-scoping invariants; this spec must not add a second write path that bypasses them. No secret values cross the bless routes (bless keys on name+version only).
### Accessibility
The toggle + revoke list follow the existing keys-panel a11y patterns (focus, labels).

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Changelog | CHANGELOG.md | Added — desktop bless/revoke UI |
| ADR | docs/technical/adr/ADR-043-... | cross-reference |

## Acceptance Criteria
- [ ] `POST /app/bless/{name}` blesses the capability's current version; `GET /app/bless` lists it; `DELETE` removes it; all 401 without a session.
- [ ] Blessing an unknown capability → 404.
- [ ] After a capability update (version bump), the desktop shows it as un-blessed (stored version ≠ current).
- [ ] The client toggle reflects + changes brain state; the blessed-list revoke removes a row.
- [ ] Brain: `mypy`/`ruff`/`pytest` clean. Client: `tsc`/`eslint`/`vitest`/`cargo`/`clippy` clean.

## Progress
_(Coding mode writes here — do not edit manually)_
