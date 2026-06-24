---
spec: client-world
status: ready
token_profile: balanced
autonomy_level: L2
---

# Spec: CLIENT-world — the spatial map shell (world plane + camera + cluster layout + user-arrange/persist + dock + minimap)

**Identity:** Implements the ADR-028 travel-zoom command-map shell — the pannable/zoomable world plane and its camera (pan · scroll-zoom-toward-cursor · travel-across · rubber-band · Home/Esc), the functional-cluster default layout, user-arrange + brain-synced persistence (via CLIENT-core's layout store), the dock + minimap (the keyboard nav path), and the placed glance-card slots + pulsing brain core. Composes CLIENT-theme's `NeuralWeb` (sharing the world transform) and tokens. The glance→detail morph + detail content are NOT here (CLIENT-card / CLIENT-screens).
→ why: see docs/technical/adr/ADR-028-client-spatial-navigation.md (the map decisions) · docs/technical/architecture/app-flow.md (navigation + a11y) · docs/technical/architecture/design-brief.md (travel-zoom + neural web) · mockup docs/research/mockups/travel-zoom-workspace.html (canonical camera/CSS).

<!-- Split rule: flagged atomic exception — CLIENT-world is ONE cohesive shell module under client/src/world/ (camera math + world plane + dock + minimap + layout bridge are mutually dependent; the plane renders the cards the dock/minimap index, all driven by one camera store). It modifies client/src/App.tsx to mount the shell (the placeholder core left). The expand-morph + per-domain detail are CLIENT-card/CLIENT-screens; the Ask popup is CLIENT-ask; the tokens/neural-web internals are CLIENT-theme. -->

## Assumptions
- **CLIENT-core is ready** (`docs/changes/CLIENT-core.md`): `client/` Tauri+React+Vite scaffold; `client/src/state/layout.ts` exposes the layout store — `layoutGet()`/`layoutPut(LayoutDTO)` (debounced, LWW on `updated_at`)/`resetToDefault()`; `LayoutDTO {placements: CardPlacement[], updated_at}`, `CardPlacement {domain_id, cluster, x, y}`; `client/src/state/connection.ts` exposes `ConnectionState` (`unpaired·disconnected·connectedLocked·unlocked`). World consumes these verbatim. → impact: Stop (if the store API/DTO names differ, match them — same wire contract).
- **CLIENT-theme is ready** (`docs/changes/CLIENT-theme.md`): `client/src/theme/NeuralWeb.tsx` accepts the world `transform` as a prop (its SVG shares `transform-origin:0 0`); `client/src/theme/relationships.ts` exports the domain set + edge/spoke map; `AmbientProvider`/`useAmbientCell`; the `.glass`/`--p`/`--focus-ring` tokens. World composes these; it does NOT reimplement the neural web or tokens. → impact: Stop.
- **The map functions in `Connected·Vault-locked`** (app-flow.md: Map + Status work while locked). World renders whenever the connection state is `connectedLocked` or `unlocked`; the onboarding/reconnect/unlock screens are CLIENT-auth — world gates its render on the connection store, it does not own those screens. → impact: Stop.
- **WebKit-safe (apex-tauri):** the world plane animates via `transform`/`opacity` ONLY (no SMIL, no layout-thrash, no animating non-compositor props); `will-change:transform` only while the camera is actively moving; reduced-motion → crossfade/instant (no travel arc). → impact: Stop (the camera must be smooth on both WebView2 + WKWebView).
- **The 11-domain / 4-cluster seed is a DEFAULT, not a cage** (ADR-028 + DECISIONS-LOG 2026-06-23): Comms (Email·People) · Planning (Schedule·Tasks·**Projects**·Travel) · Knowledge (Memory·Knowledge·Review) · Self (Health·Finance). **`projects` is a separate card from `tasks`** (Tasks/Projects module split). The user drags any card anywhere/between clusters; the arrangement persists. → impact: Caution (seed positions live in `clusters.ts`; the canonical id set is CLIENT-core `domains.ts`, mirrored by `relationships.ts`).

Simplicity check: considered Canvas/WebGL for the plane — rejected (a handful of cards + one SVG link layer, not 100+ nodes; CSS transform on one plane div is WebKit-safe and matches the mockup). Considered owning the glance-card face here — rejected; the card face + expand-morph are CLIENT-card (world renders a positioned, focusable *slot* that takes the card as a child). Considered a local-only layout store — rejected; persistence is CLIENT-core's brain-synced store (decision 2).

## Prerequisites
- Specs complete first: **CLIENT-core** (scaffold + layout store + connection store) and **CLIENT-theme** (NeuralWeb + relationships + tokens). Sequenced-after both.
- Note (ADR-029 file overlap): this spec **modifies `client/src/App.tsx`** (created by CLIENT-core) — so CLIENT-world is NOT file-disjoint from CLIENT-core; build core first. Otherwise all new files live under `client/src/world/`.
- Environment: none beyond CLIENT-core's `npm install` (pure frontend; no new deps). **`vitest` + `@testing-library/react` come from CLIENT-core's scaffold** — if absent, install + wire them in Task 6 (the apex-tauri frontend test add-ons).
- Note: the Rust gates (`cargo check`/`clippy` in `src-tauri/`) are CLIENT-core's responsibility (world adds no Rust) but must still pass on the integrated tree.

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| client/src/world/camera.ts | create | Pure camera math + a typed `Camera = {tx, ty, scale}` reducer: `pan(cam, dx, dy)`, `zoomToward(cam, factor, px, py)` (eased; keeps the cursor world-point fixed), `clampRubberband(cam, bounds)` (eased overshoot back into bounds), `home(bounds)`, `worldToScreen`/`screenToWorld`. No DOM, no React — unit-testable. |
| client/src/world/clusters.ts | create | The default functional-cluster layout: the **11-domain** seed in 4 poles → `defaultPlacements(): CardPlacement[]` (`{domain_id, cluster, x, y}` around the centred brain core, mirroring the mockup `cx/cy` poles). **Domain ids imported from CLIENT-core `client/src/domains.ts`** (canonical 11 incl. `projects`); positions for the new `projects` card sit in the Planning pole beside `tasks`. |
| client/src/world/useCamera.ts | create | React hook/store wiring pointer-drag (pan), wheel (zoom-toward-cursor, eased), and keyboard (Home/Esc→`travelTo(home)`, arrow-pan) to `camera.ts`; rAF-batched transform writes; `travelTo(target)` = a **rAF JS loop that interpolates `{tx,ty,scale}` and commits to the camera store each frame** (the store stays the single source of truth so dock/minimap read live positions — **NOT** WAAPI on the transform); short hop = direct ease, long hop = zoom-out→pan→zoom-in arc; **reduced-motion → a TRUE instant position set (no arc, no opacity fade)**; calls an `onArrive(target)` callback at completion (used for focus + the live announce — F1/F3); exposes `{cam, travelTo, home, isMoving}`. |
| client/src/world/WorldPlane.tsx | create | The single transformed plane div (`transform: translate(tx,ty) scale(s)`, `transform-origin:0 0`, `overflow:hidden` container — **NO scrollbars, pan/zoom only**, ADR-028 hard rule); `will-change:transform` set only while `isMoving` and **removed (→ `auto`/unset) within one rAF of `isMoving`→false** (no idle compositor lock — apex-tauri T1); renders the pulsing brain core (**`aria-hidden="true"`** — decorative) at centre, `<NeuralWeb transform={…}/>` (same transform; its root SVG must carry `transform-origin:0 0` + `aria-hidden` — T2/F2), and a positioned `CardSlot` per placement. |
| client/src/world/CardSlot.tsx | create | A positioned, keyboard-focusable **native `<button>`** at a `CardPlacement` (NOT div+role — F-note; `:focus-visible` ring via `--focus-ring`; **static `aria-label="{domain name}"`** as the baseline accessible name, valid even before CLIENT-card fills the face — F4). Drag handle (grip) drives pointer reposition; **keyboard reposition alternative (WCAG 2.5.7 — B1):** Enter on the grip enters "move mode" (visible indicator + `aria` state), arrow keys move in coarse steps, Enter commits / Esc cancels. Takes the glance-card face as `children` (CLIENT-card fills it — here a minimal placeholder). On activate (Enter/click) calls injected `onOpen(domainId)`. Never scrolls internally. |
| client/src/world/Dock.tsx | create | The dock: a **complete, keyboard-reachable index of ALL domains** (incl. off-screen), a focusable list of native buttons; Enter/click on an item → `travelTo(card)` then **focus moves to the target `CardSlot`** at arrival (F1). The dock is the **sole keyboard+pointer nav path** (app-flow a11y). Uses `.glass`. |
| client/src/world/Minimap.tsx | create | Minimap reflecting **current (user) card positions** + a viewport rect from the camera — **`aria-hidden="true"`, decorative, NO pointer interaction** (B2: visual orientation only; the dock is the sole nav path, so the minimap needs no keyboard path). Updates as cards move. |
| client/src/world/layoutBridge.ts | create | Bridges placements ↔ CLIENT-core's layout store: on mount `layoutGet()` → if placements exist use them, else `clusters.defaultPlacements()`; on card drag-end persist via `layoutPut()` (debounce handled by the core store; LWW on `updated_at`); `resetToDefault()` → cluster default + persist. Holds the live `placements` the plane/dock/minimap read. |
| client/src/App.tsx | modify | Replace the CLIENT-core placeholder shell: mount `AmbientProvider` + `PhotoBackground` (theme) → gate on `useConnection()`: `connectedLocked`/`unlocked` → render `WorldPlane` + `Dock` + `Minimap` (+ the top-bar Home/crumb/status chrome) + an **`aria-live="polite"` visually-hidden status region** announcing "Navigated to {domain}" on travelTo arrival (F3); other states → render nothing of the map (CLIENT-auth's onboarding/reconnect screens take over). Wire `travelTo`/`onArrive`(→focus target CardSlot + announce)/`onOpen` seams (CLIENT-card/ask consume them later). |
| client/src/world/camera.test.ts | create | Vitest: pan offsets; zoom-toward-cursor keeps the cursor world-point fixed; rubber-band clamps past bounds and eases back; `worldToScreen`/`screenToWorld` round-trip; `home` centres. |
| client/src/world/clusters.test.ts | create | Vitest: `defaultPlacements()` yields all **11** seed domains (incl. `projects`) in the 4 named clusters; ids match `domains.ts`; positions are within world bounds. |
| client/src/world/world.test.tsx | create | RTL: the dock lists every domain and is keyboard-operable (Tab/Enter → travelTo called); Home/Esc recenter; under `prefers-reduced-motion` no travel arc runs (instant); the world container has no scrollbars / cards don't scroll; render is gated to connected states. |

## Tasks
- [ ] Task 1: Camera math + cluster default (pure) — files: `client/src/world/camera.ts`, `client/src/world/clusters.ts`, `client/src/world/camera.test.ts`, `client/src/world/clusters.test.ts` — the `Camera` reducer (pan/zoomToward/clampRubberband/home/world↔screen) and the **11-domain**/4-pole `defaultPlacements()`; both pure + unit-tested. — done when: `cd client && npx vitest run client/src/world/camera.test.ts client/src/world/clusters.test.ts` passes (zoom keeps cursor point fixed; rubber-band clamps; **all 11 domains (incl. `projects`)** placed in 4 clusters with ids imported from `domains.ts`); `npx tsc --noEmit` clean.
- [ ] Task 2: Camera hook + interaction wiring — files: `client/src/world/useCamera.ts` — pointer-drag pan, wheel zoom-toward-cursor (eased), keyboard Home/Esc/arrow, rAF-batched writes, `travelTo` as a **rAF JS loop committing `{tx,ty,scale}` to the camera store each frame** (NOT WAAPI — T3), short ease / long arc, **reduced-motion = true instant set (no arc, no fade)**, `onArrive` callback at completion. — done when: `tsc --noEmit` clean; a `travelTo` to an off-screen card ends with that card centred at `FOCUS` scale and `onArrive` fired; with `prefers-reduced-motion` the position is set in one frame (no arc, no fade) — asserted in Task 6.
- [ ] Task 3: World plane + card slots + brain core + neural web — files: `client/src/world/WorldPlane.tsx`, `client/src/world/CardSlot.tsx` — the transformed plane (`transform-origin:0 0`, overflow hidden, **`will-change` removed within 1 rAF of `isMoving`→false** — T1), the pulsing core (`aria-hidden`), `<NeuralWeb transform>` composed with the same transform, and a native-`<button>` `CardSlot` per placement (pointer drag-handle reposition **+ keyboard move-mode: Enter→move, arrows step, Enter commit/Esc cancel** — B1; `onOpen` seam; `--focus-ring`; static `aria-label="{domain}"` — F4; never scrolls). — done when: `tsc --noEmit` clean; `npm run build` compiles; the plane and NeuralWeb receive the identical transform string; the brain core + NeuralWeb root SVG carry `aria-hidden` and the SVG carries `transform-origin:0 0` (T2/F2); a `CardSlot` is reachable by keyboard with a visible focus ring AND repositionable by keyboard (move-mode) — asserted in Task 6.
- [ ] Task 4: Dock (the sole nav path) + decorative minimap — files: `client/src/world/Dock.tsx`, `client/src/world/Minimap.tsx` — the dock indexes ALL domains as native buttons (keyboard-operable; Enter → `travelTo` then focus the target CardSlot at arrival — F1); the minimap reflects current positions + viewport rect but is **`aria-hidden`, decorative, no pointer/keyboard interaction** (B2). — done when: `tsc --noEmit` clean; the dock renders every domain; Tab+Enter on a dock item calls `travelTo` for that domain and focus lands on the target CardSlot at arrival (Task 6); the minimap viewport rect tracks the camera and is `aria-hidden`.
- [ ] Task 5: Layout bridge + shell wiring + live region — files: `client/src/world/layoutBridge.ts`, `client/src/App.tsx` — load placements (else cluster default), persist on drag-end via `layoutPut`, `resetToDefault`; mount Ambient+Photo+World+Dock+Minimap gated on `connectedLocked`/`unlocked`; add the **`aria-live="polite"` "Navigated to {domain}" status region** + wire `onArrive`→focus+announce (F1/F3). — done when: `tsc --noEmit` clean; `npm run build` compiles; empty layout → cluster default; moving a card calls `layoutPut` once (debounced); `resetToDefault` restores the seed; map renders only in connected states; the live region announces on arrival (Task 6).
- [ ] Task 6: Shell tests + manual SR pass — files: `client/src/world/world.test.tsx` — RTL: dock keyboard nav → `travelTo` + focus lands on target CardSlot + live region announces; CardSlot keyboard move-mode repositions + persists; Home/Esc recenter; reduced-motion = no arc/no fade; no internal scroll; brain core + NeuralWeb SVG `aria-hidden`; CardSlot has a non-empty accessible name; connection-gated render; layoutBridge load/persist/reset against a mocked core store. **A manual NVDA screen-reader pass (dock → CardSlot activation → keyboard reposition → Home/Esc → reduced-motion) is a REQUIRED gate (F5)** — record the result. — done when: `cd client && npx vitest run client/src/world/world.test.tsx` passes; `npx tsc --noEmit` clean; `npx eslint . --max-warnings 0` clean; the NVDA pass is recorded.

## Wave plan
Wave 1: [Task 1] | Wave 2: [Task 2] | Wave 3: [Task 3, Task 4] | Wave 4: [Task 5] | Wave 5: [Task 6]
<!-- Task 1 (pure math/data) first. Task 2 (hook) consumes camera.ts. Tasks 3+4 consume the hook + theme contracts and are mutually independent (plane vs dock/minimap). Task 5 wires them + the layout store into App.tsx. Task 6 tests the integrated shell. -->

## Permissions
The following actions will run autonomously during build. Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | client/src/world/{camera,clusters,useCamera,layoutBridge}.ts(x), client/src/world/{WorldPlane,CardSlot,Dock,Minimap}.tsx, client/src/world/{camera,clusters}.test.ts, client/src/world/world.test.tsx |
| Modify | client/src/App.tsx (replace the CLIENT-core placeholder shell) |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `cd client && npx tsc --noEmit` | Frontend typecheck gate (apex-tauri recipe) |
| `cd client && npx vitest run` | Camera/cluster/shell unit + RTL tests |
| `cd client && npx eslint . --max-warnings 0` | Lint gate |
| `cd client && npm run build` | Vite build (plane/dock/minimap compile) |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | client/src/world/, client/src/App.tsx |
| `git commit` | "feat: CLIENT-world map shell (camera + cluster layout + user-arrange/persist + dock + minimap)" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| (none) | pure frontend; layout persists via CLIENT-core's Rust-side layout store (no env/secrets here) |

### Network
| Action | Purpose |
|--------|---------|
| (no install) | reuses CLIENT-core's React/Vite; no new deps |
| (no direct network) | layout persistence goes through CLIENT-core's `invoke` layout commands — world makes no network calls |

## Specialist Context
### Accessibility
Navigation never depends on pointer pan/zoom (app-flow.md): the **dock** is the sole nav path — a complete, keyboard-operable index of every domain (incl. off-screen) as native buttons; `Home`/`Esc` recenter, arrow keys pan. `CardSlot`s are native `<button>`s, focusable with a visible `--focus-ring` and a static `aria-label="{domain}"` accessible name (F4). **Drag has a keyboard alternative** (WCAG 2.5.7 — B1): Enter on the grip → move-mode, arrows step, Enter/Esc commit/cancel. The **minimap is decorative `aria-hidden`** (B2 — no keyboard burden; the dock covers nav). On `travelTo` arrival, **focus moves to the target CardSlot** (F1, at animation end / instant under reduced-motion — 2.4.11) and an **`aria-live="polite"`** region announces "Navigated to {domain}" (F3). Decorative layers (brain core, NeuralWeb SVG) are `aria-hidden` (F2). Reduced-motion = a true instant position set (no arc, no fade); any crossfade CSS is gated `not(prefers-reduced-motion)`. The overview never content-scrolls. **A manual NVDA pass is a required Task-6 gate (F5).** [apex-accessibility + apex-ui-ux-design + apex-tauri reviewed 2026-06-24 — findings folded.]

### Performance
WebKit-safe is the perf constraint: one transformed plane div (`transform: translate scale`, `transform-origin:0 0`), `will-change:transform` set only while moving and **removed within 1 rAF of movement end** (no idle compositor/GPU lock — apex-tauri T1), rAF-batched camera writes, `travelTo` via a rAF JS loop committing to the camera store (T3 — not WAAPI), transform/opacity-only animation (compositor-friendly on WKWebView), no SMIL, no stacked blur on the moving plane. The NeuralWeb shares the exact transform so links don't reflow. Layout `layoutPut` is debounced on drag-end (no per-frame writes).

### Security
No secrets, no direct network — layout reads/writes go through CLIENT-core's session-gated Rust layout commands (ADR-030; the layout endpoint is `require_session` so the map works while vault-locked). World holds no token.

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | client/src/world/*.ts(x) | TSDoc all exports; document the camera model (transform-origin:0 0, zoom-toward-cursor, travel arc), the CardSlot/onOpen seam (CLIENT-card consumes), and the layout-store integration |
| App-flow | docs/technical/architecture/app-flow.md | No change (source of truth); this spec implements the "Command-map (home)" + "Map + navigation" sections + the cross-screen a11y rules |

## Acceptance Criteria
- [ ] Run `cd client && npx tsc --noEmit` → verify: exit 0.
- [ ] Run `cd client && npx vitest run` → verify: camera (zoom-toward-cursor keeps the world-point under the cursor fixed; rubber-band clamps + eases; world↔screen round-trips; home centres); clusters (all 11 seed domains incl. `projects` in the 4 named clusters, ids from `domains.ts`); shell (dock lists every domain + Tab/Enter→travelTo **and focus lands on the target CardSlot at arrival — F1**; the **`aria-live` region announces "Navigated to {domain}" — F3**; **CardSlot keyboard move-mode repositions + persists — B1**; Home/Esc recenter; **reduced-motion → no arc and no opacity fade**; no internal scroll; render gated to connectedLocked/unlocked; layoutBridge loads default when empty, persists on drag-end via a mocked `layoutPut`, resetToDefault restores the seed).
- [ ] Run `cd client && npx eslint . --max-warnings 0` → verify: exit 0.
- [ ] Run `cd client && npm run build` → verify: exit 0 (plane/dock/minimap/App compile).
- [ ] Run `grep -RInE "<animate[A-Za-z]*|<set\b|animateMotion|overflow:\s*scroll|overflow-y:\s*auto" client/src/world/` → verify: no SMIL (`<animate*`/`<animateTransform`/`<set`/`<animateMotion`); no scroll containers in the map (pan/zoom only — ADR-028 hard rule). (T4)
- [ ] Inspect `WorldPlane.tsx` → verify: the plane and `<NeuralWeb>` receive the identical `transform`; `transform-origin:0 0`; `will-change` is set only while moving and **removed (→ `auto`/unset) within one rAF of movement end — T1** (Task-6 assertion on the removal).
- [ ] (T2) Assert the **`<NeuralWeb>` root SVG carries `transform-origin:0 0`** end-to-end (the consumer's check — links must not drift on zoom even though CLIENT-theme owns the component).
- [ ] (a11y F2) Run `grep -nE "aria-hidden" client/src/world/WorldPlane.tsx client/src/world/Minimap.tsx` → verify: the brain core, the NeuralWeb SVG, and the minimap all carry `aria-hidden="true"`.
- [ ] (a11y F4) Inspect/RTL → verify: every `CardSlot` is a native `<button>` with a non-empty accessible name (`aria-label="{domain}"`), a visible `--focus-ring`, and is keyboard-repositionable (move-mode); the dock is keyboard-operable and indexes every domain; Home/Esc bound.
- [ ] (a11y F5) **Manual NVDA pass** (dock → CardSlot activation → keyboard reposition → Home/Esc → reduced-motion) → verify: announced + operable; record the result in the build handoff. Required gate.

## Progress
_(Coding mode writes here — do not edit manually)_
