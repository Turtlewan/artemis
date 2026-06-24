---
spec: client-card
status: ready
token_profile: balanced
autonomy_level: L2
---

# Spec: CLIENT-card — glance→detail expand-morph + the per-domain content contract

**Identity:** The card layer of the map shell — the glance-card face (count / stat-tiles, never-scroll), the travel-then-expand shared-element morph into a top-most detail overlay over the dimmed map (collapse-back on close, focus-trapped dialog), and the `DomainDetail` contract + registry that CLIENT-screens fills.
→ why: see docs/technical/adr/ADR-028-client-spatial-navigation.md (§3–4 open=travel-then-expand; glance cards) · docs/technical/architecture/app-flow.md (domain detail = top-most over the lightly-dimmed map).

<!-- Split rule: flagged atomic exception (precedent: CLIENT-core/theme/world each shipped a cohesive client package as one spec). CLIENT-card is ONE cohesive module under client/src/card/ whose parts are mutually dependent (the glance face + the morph overlay + the registry contract + the open store compose one open/close interaction); sub-splitting leaves a non-functional card layer. It modifies two CLIENT-world files (App.tsx, WorldPlane.tsx) to wire the seam → NOT file-disjoint from CLIENT-world (serialize after world). -->

## Assumptions
- **CLIENT-world is ready** (`docs/changes/CLIENT-world.md`): `client/src/world/CardSlot.tsx` is a native `<button>` that takes the glance face as `children` and calls an injected `onOpen(domainId)` on activate; `client/src/world/useCamera.ts` exposes `travelTo(target)` + an `onArrive(target)` callback; `client/src/App.tsx` mounts `WorldPlane`+`Dock`+`Minimap` and wires the `onOpen`/`onArrive`/`travelTo` seams. CLIENT-card modifies `App.tsx` (mount the overlay + wire open-on-arrive + the background-inert toggle) and `WorldPlane.tsx` (render the glance face into `CardSlot` children). → impact: Stop (these are the consumed seams; if the seam names differ, match them; the two shared files force build-after-world).
- **CLIENT-core is ready, and owns `client/src/domains.ts`** (the canonical domain set — amended into CLIENT-core): `DomainId` + `domainLabel(id): string`. CLIENT-card imports both from there (**NOT** `theme/relationships.ts`) for the registry keys, the GlanceHost default label, the CardSlot accessible name, and the overlay title. `useConnection()` also exists; the overlay mounts inside the connected map (CLIENT-world gates the render). → impact: Stop (single source of domain ids/labels; drift = a card that never opens its detail).
- **CLIENT-theme is ready** (`docs/changes/CLIENT-theme.md`): the `.glass` panel class (in-content `backdrop-filter`, the ≥0.72 `--bg` scrim floor) + `--p`/`--a`/`--bg`/`--focus-ring` tokens are available. The morph overlay + glance face render against these tokens — no literal hex (forbidden pattern); **DetailOverlay applies `.glass` only** (CLIENT-theme owns the blur params — no second/inline `backdrop-filter`). → impact: Stop.
- The concrete per-domain detail + glance CONTENT is **CLIENT-screens** (it registers components into CLIENT-card's registries). CLIENT-card ships the shell + the contract + a graceful fallback only. → impact: Caution (the fallback "detail coming" panel is what an unregistered domain shows until screens wires it).

Simplicity check: considered rendering each domain's detail inline in its CardSlot (no overlay) — rejected; ADR-028 mandates the top-most expand-morph over the dimmed map, and inline detail would force the overview to scroll (a hard-rule violation). Considered one registry of `{glance, detail}` tuples vs two parallel registries — chose **one `registerDomain(id, {glance?, detail?})`** with two lookup maps behind it (CLIENT-screens registers both in one call; either may be absent → falls back). Considered a third-party modal lib — rejected; a focus-trapped `role=dialog` overlay with a FLIP morph is small, dependency-free, and WebKit-safe.

## Prerequisites
- Specs complete first: **CLIENT-core**, **CLIENT-theme**, **CLIENT-world** (consumes their seams; modifies two world files → builds AFTER world, not parallel with it).
- Sequenced-with: **CLIENT-screens** (registers the concrete content into CLIENT-card's registries — off-screens the registries are empty and every domain shows the fallback; card is testable standalone with a fake registered component).
- Environment: none new (reuses CLIENT-core's React/Vite/vitest + @testing-library/react). No new deps.

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| client/src/card/types.ts | create | imports `DomainId` from `client/src/domains.ts`; `interface DomainDetailProps { domainId: DomainId; onClose: () => void }`; `interface DomainGlanceProps { domainId: DomainId }`; `type GlanceContent = { kind: "count"; value: string \| number; label: string } \| { kind: "tiles"; tiles: { value: string; label: string }[] }`; `type DomainDetailComponent = React.ComponentType<DomainDetailProps>`; `type DomainGlanceComponent = React.ComponentType<DomainGlanceProps>` |
| client/src/card/registry.ts | create | the registry seam CLIENT-screens fills: module-level `detailRegistry`/`glanceRegistry` maps (keyed `DomainId`); `registerDomain(id, { glance?, detail? })`; `getDomainDetail(id): DomainDetailComponent \| undefined`; `getDomainGlance(id): DomainGlanceComponent \| undefined`. Pure registration; no React. |
| client/src/card/GlanceFace.tsx | create | presentational `GlanceFace({ content }: { content: GlanceContent })` — `count` → number + label **baseline-aligned, vertically-centred, left-aligned** (design-brief); `tiles` → fixed stat tiles; **`overflow:hidden`, NO scrollbar — never content-scrolls (ADR-028 hard rule, grep AC)**. + `GlanceHost({ domainId })` — looks up `getDomainGlance(id)` → render it, else a default `<GlanceFace content={{kind:"count", value:"—", label: domainLabel(id)}}/>` (**`domainLabel` from `client/src/domains.ts`**). The CardSlot's accessible name is the domain label even in this placeholder phase (F1). |
| client/src/card/morph.ts | create | pure FLIP geometry: `firstLastInvert(fromRect, toRect): { tx, ty, scale }` (the inverse transform from the glance-card rect to the overlay rect); `morphKeyframes(invert)` → **transform/opacity-only** keyframes for `element.animate()` (WAAPI); **no layout-animated props, no SMIL**. Caller does **both `getBoundingClientRect()` reads (card=First, overlay=Last) in ONE synchronous block BEFORE any DOM write/class toggle** (reads-before-writes; no forced reflow mid-setup — T4). Dependency-free, unit-testable. |
| client/src/card/useCardOverlay.ts | create | the open-card store: `{ openId: DomainId \| null, open(domainId), close() }` (+ the originating `CardSlot` element ref for focus return). `open` is called by App on `onArrive` (after the camera travels). Exposes `useCardOverlay()`. |
| client/src/card/DetailOverlay.tsx | create | the top-most overlay shell: a **dim scrim over the map = `background: rgba(0,0,0,0.18)` ONLY — no `mix-blend-mode`** (WebKit #176830 with the `.glass` backdrop-filter — T5) + a `.glass` (class only; no inline `backdrop-filter`) **focus-trapped dialog** (`role="dialog" aria-modal="true"`, `aria-labelledby="card-overlay-title"`) that renders `<h2 id="card-overlay-title">{domainLabel(openId)}</h2>` (B2) and **expands from the originating card rect via the FLIP morph** and **collapses back into the card on close**. **Pre-warm** = mount with `opacity:0`/`visibility:hidden` (element stays in the render tree; **NOT `content-visibility:hidden`**, which suppresses compositing and defeats the pre-warm — T1). `will-change:transform,opacity` is applied **immediately before** the WAAPI animation and **removed in `animation.onfinish`** (never carried on the idle pre-warmed state — T3). On close, **validate the originating CardSlot ref (`isConnected`) before measuring**; if stale → fall back to a fade-out (T2). Renders `getDomainDetail(openId)` or the inline **fallback "detail coming" panel** (its own non-empty `<h2 id="card-overlay-title">` heading, same `aria-labelledby` pattern — F3/B2); the detail content region **MAY scroll internally** (`overflow:auto`) — only the glance never scrolls. Close on **Esc / ✕ only** (Home dropped — it conflicts with AT Home-key nav). **Initial focus = the dialog container (`tabIndex=-1` on the `.glass`) or the title heading — NOT the close button** (F4); focus **returns to the originating `CardSlot`** on close. `prefers-reduced-motion` → crossfade (opacity/instant) on **both open AND close** — no spatial morph either way; the open/close state is conveyed by focus move + dialog presence, never motion alone (F2). |
| client/src/App.tsx | modify | mount `<DetailOverlay/>` as the **top-most layer** (above WorldPlane/Dock); wire CLIENT-world's `onOpen(domainId)` = `travelTo(card)` **then `useCardOverlay.open(domainId)` on `onArrive`**; pass the originating CardSlot ref for focus-return; **while an overlay is open, set `inert` + `aria-hidden="true"` on the background containers (WorldPlane/Dock/Minimap) and remove both on close** (B1). |
| client/src/world/WorldPlane.tsx | modify | render `<GlanceHost domainId={p.domain_id}/>` as the `CardSlot` `children` (replaces world's minimal placeholder face). CardSlot nodes are **stable while an overlay is open** (no remount), so the close-morph ref stays valid (T2). |
| client/src/card/morph.test.ts | create | vitest: `firstLastInvert` produces the correct `{tx,ty,scale}` for sample from/to rects; `morphKeyframes` emits only `transform`/`opacity` (no top/left/width/height). |
| client/src/card/card.test.tsx | create | RTL: GlanceFace count + tiles render; **GlanceFace/GlanceHost never produce a scrollable node**; the CardSlot accessible name = domain label in the placeholder phase (F1); opening sets `role=dialog`/`aria-modal`, **the dialog accessible name = the domain label** (B2), **focus is on the dialog container/title (not the close button)** (F4), and the **background WorldPlane/Dock/Minimap carry `inert`+`aria-hidden` while open and lose both on close** (B1); Esc/✕ closes and **focus returns to the originating CardSlot**; an unregistered domain shows the fallback **with a non-empty heading** (F3); a registered fake `DomainDetail` renders; under `prefers-reduced-motion` **no spatial morph runs on open OR close** (F2). |

## Tasks
- [ ] Task 1: Contract + registry — files: `client/src/card/types.ts`, `client/src/card/registry.ts` — the `DomainDetailProps`/`DomainGlanceProps`/`GlanceContent` types (importing `DomainId` from `client/src/domains.ts`) + the `registerDomain`/`getDomainDetail`/`getDomainGlance` registry CLIENT-screens consumes. — done when: `cd client && npx tsc --noEmit` clean; `registerDomain("x",{detail:Fake})` then `getDomainDetail("x")` returns it and `getDomainDetail("unknown")` is `undefined` (Task 6).
- [ ] Task 2: FLIP morph geometry — files: `client/src/card/morph.ts` — pure `firstLastInvert` + `morphKeyframes` (transform/opacity only, no SMIL, no layout props; document the reads-before-writes discipline for the caller — T4). — done when: `tsc --noEmit` clean; `firstLastInvert` maps a sample card-rect→overlay-rect to the expected `{tx,ty,scale}`; `morphKeyframes` output contains only `transform`/`opacity` keys (Task 6 grep/assert).
- [ ] Task 3: Glance face + host — files: `client/src/card/GlanceFace.tsx` — the presentational count/tiles face (baseline-aligned, left, vertically-centred; **overflow:hidden, no scrollbar**) + `GlanceHost` (registry lookup → registered glance or the default placeholder face; **label from `client/src/domains.ts`**). — done when: `tsc --noEmit` clean; `npm run build` compiles; a `count` and a `tiles` face render correctly; **no node inside GlanceFace is scrollable** (Task 6 assertion); the placeholder face exposes the domain label as the CardSlot accessible name (F1).
- [ ] Task 4: Detail overlay (morph shell + focus-trap dialog + fallback) — files: `client/src/card/DetailOverlay.tsx`, `client/src/card/useCardOverlay.ts` — the open store + the top-most `rgba(0,0,0,0.18)` dim scrim (no mix-blend — T5) + `.glass`-only `role=dialog aria-modal` focus-trapped panel with an `<h2 id="card-overlay-title">` title + `aria-labelledby` (B2) that FLIP-expands from the card and collapses back on Esc/✕ (Home dropped); pre-warm via `opacity/visibility` not `content-visibility` (T1); `will-change` applied just-before / removed in `onfinish` (T3); stale-ref `isConnected` guard → fade-out fallback on close (T2); renders the registered detail or the inline fallback (own heading — F3); content region scrolls internally; **initial focus on the dialog container/title, not the close button** (F4); return-to-CardSlot on close; reduced-motion crossfade on **open AND close** (F2). — done when: `tsc --noEmit` clean; opening renders `role=dialog`+`aria-modal=true` with accessible name = the domain label, focus lands on the dialog container/title, Esc closes and focus returns to the opener; an unregistered id shows the fallback with a non-empty heading; under `prefers-reduced-motion` no spatial transform animates on open or close (Task 6).
- [ ] Task 5: Wire the seam into the shell — files: `client/src/App.tsx`, `client/src/world/WorldPlane.tsx` — mount `<DetailOverlay/>` top-most; `onOpen(domainId)` → `travelTo` then `open(domainId)` on `onArrive`; toggle `inert`+`aria-hidden` on WorldPlane/Dock/Minimap while open (B1); render `<GlanceHost>` as the CardSlot face. — done when: `tsc --noEmit` clean; `npm run build` compiles; activating a CardSlot travels the camera then expands that domain's overlay after arrival; the background is `inert`+`aria-hidden` while open and restored on close; closing collapses it and returns focus to the card (Task 6).
- [ ] Task 6: Tests + manual SR pass — files: `client/src/card/morph.test.ts`, `client/src/card/card.test.tsx` — the morph + face + overlay + registry + inert + focus + reduced-motion (both paths) assertions above; **a manual screen-reader pass — NVDA (Windows) AND VoiceOver (macOS/WebKit) — (open a card → dialog announced with the domain name + focus-trapped → Esc returns focus) is a REQUIRED gate** (F5) — record the result. — done when: `cd client && npx vitest run client/src/card/` passes; `npx tsc --noEmit` clean; `npx eslint . --max-warnings 0` clean; the NVDA + VoiceOver passes are recorded in the handoff.

## Wave plan
Wave 1: [Task 1, Task 2] | Wave 2: [Task 3, Task 4] | Wave 3: [Task 5] | Wave 4: [Task 6]

## Permissions

The following actions will run autonomously during build. Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | client/src/card/{types,registry,morph,useCardOverlay}.ts, client/src/card/{GlanceFace,DetailOverlay}.tsx, client/src/card/{morph.test.ts,card.test.tsx} |
| Modify | client/src/App.tsx, client/src/world/WorldPlane.tsx |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `cd client && npx tsc --noEmit` | Frontend typecheck gate |
| `cd client && npm run build` | Vite build (confirms the card module + the modified shell compile) |
| `cd client && npx vitest run client/src/card/` | Card unit/RTL tests |
| `cd client && npx eslint . --max-warnings 0` | Lint gate |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | client/src/card/**, client/src/App.tsx, client/src/world/WorldPlane.tsx |
| `git commit` | "feat: CLIENT-card glance→detail expand-morph + per-domain content contract" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| (none) | pure frontend; no env, no network, no secrets |

### Network
| Action | Purpose |
|--------|---------|
| (none) | no deps added; no runtime network (detail data is fetched by CLIENT-screens' registered components, not here) |

## Specialist Context
### Security
(none — pure presentational shell; no token, no network, no secrets. The registered detail components (CLIENT-screens) own their own data access via CLIENT-core's Rust gateway.)

### Performance
WebKit-safe morph (apex-tauri): the expand/collapse animates **transform/opacity only** via WAAPI (FLIP — both `getBoundingClientRect()` reads in one synchronous block **before** any DOM write, then invert + play; no forced reflow mid-setup — T4), never layout props (top/left/width/height) and **no SMIL**. The `.glass`/blur layer is **pre-warmed with `opacity:0`/`visibility:hidden`** (stays in the render tree; **not `content-visibility:hidden`** — that suppresses compositing and defeats the pre-warm — T1). `will-change:transform,opacity` is set **immediately before** the animation and **removed in `animation.onfinish`** (no idle compositor lock — T3). The dim scrim is a single `rgba(0,0,0,0.18)` opacity layer — **no `mix-blend-mode`** (WebKit #176830 with `.glass` backdrop-filter — T5); no stacked blur over the moving morph. Only one overlay is open at a time. Close-morph guards a stale CardSlot ref (`isConnected`) → fade-out fallback (T2).

### Accessibility
The detail overlay is a **focus-trapped dialog** (`role="dialog"`, `aria-modal="true"`, `aria-labelledby="card-overlay-title"` → a real `<h2>` carrying the **domain label**; the fallback panel renders the same heading pattern — B2/F3). While open, the background (**WorldPlane/Dock/Minimap) carries `inert` + `aria-hidden="true"`**, removed on close (B1). **Initial focus = the dialog container (`tabIndex=-1`) or the title — never the close button** (F4); focus **returns to the originating `CardSlot`** on close; focus is never left on an off-screen card. The CardSlot exposes the domain label as its accessible name even in the placeholder phase (F1). The glance face **never content-scrolls** (ADR-028); the detail content region may scroll. `prefers-reduced-motion` → crossfade/instant on **both open AND close** (state conveyed by focus + dialog presence, never motion alone — F2). Close triggers = **Esc + ✕ only** (Home dropped — conflicts with AT Home-key nav). Because the background is `inert`, no separate scrim-contrast check is required. [apex-accessibility + apex-ui-ux-design + apex-tauri reviewed 2026-06-24 — findings folded; a manual **NVDA + VoiceOver** pass is a Task-6 gate (F5).]

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | client/src/card/*.ts(x) | TSDoc all exports; document the `DomainDetailProps`/`registerDomain` contract (the seam CLIENT-screens implements) + the FLIP-morph (reads-before-writes, will-change lifecycle) + focus-return + background-inert model |
| API | docs/product/api/client-app-api.md | note the card registry contract (`registerDomain(id, {glance, detail})`) that per-domain screens plug into |

## Acceptance Criteria
- [ ] Run `cd client && npx tsc --noEmit` → verify: exit 0 (types, registry, morph, overlay, glance all typed; `DomainId` from `client/src/domains.ts`).
- [ ] Run `cd client && npm run build` → verify: `dist/` produced; exit 0.
- [ ] Run `cd client && npx vitest run client/src/card/` → verify: `firstLastInvert` geometry; `morphKeyframes` contains only `transform`/`opacity`; GlanceFace count + tiles render; **GlanceFace/GlanceHost produce no scrollable node**; the CardSlot placeholder accessible name = the domain label (F1); opening sets `role=dialog`+`aria-modal=true` with **accessible name = the domain label** (B2), focus lands on the **dialog container/title (not the close button)** (F4), and **WorldPlane/Dock/Minimap carry `inert`+`aria-hidden` while open and lose both on close** (B1); Esc/✕ closes and focus returns to the originating CardSlot; an unregistered domain shows the fallback **with a non-empty heading** (F3); a registered fake `DomainDetail` renders; reduced-motion = crossfade with **no spatial morph on open OR close** (F2).
- [ ] Run `grep -nE "overflow.*(scroll\|auto)" client/src/card/GlanceFace.tsx` → verify: EMPTY (the glance face never scrolls; ADR-028 hard rule).
- [ ] Run `grep -rnE "<animate\|<set\b\|stroke-dashoffset\|content-visibility\|mix-blend-mode" client/src/card/ client/src/App.tsx client/src/world/WorldPlane.tsx` → verify: EMPTY (no SMIL / non-compositor animation; no `content-visibility` pre-warm; no `mix-blend-mode` on the scrim/glass).
- [ ] Run `cd client && npx eslint . --max-warnings 0` → verify: exit 0.
- [ ] (a11y) **Manual NVDA + VoiceOver pass** (open a card → dialog announced with the domain name + focus-trapped; Esc → focus returns to the card; background not reachable) → verify: announced + operable on both; record in the build handoff. Required gate.

## Progress
_(Coding mode writes here — do not edit manually)_
