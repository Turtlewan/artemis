---
spec: client-theme
status: ready
token_profile: balanced
autonomy_level: L2
---

# Spec: CLIENT-theme — Holo Tactical design system + ambient theming + photo background

**Identity:** The Tauri client's visual foundation — design tokens (`--bg`/`--p`/`--a` + structural glass tokens), the 16-cell season×time ambient resolver that drives them, the bundled in-webview photo background (gradient fallback), and the neural-web SVG layer + its animation contract. The other 6 CLIENT specs render against these tokens.
→ why: see docs/technical/architecture/design-brief.md (source of truth) · docs/technical/adr/ADR-028-client-spatial-navigation.md.

<!-- Split rule: flagged atomic exception (precedent: CLIENT-c shipped a whole cohesive package as one spec). CLIENT-theme is ONE cohesive design-system module under client/src/theme/ whose parts are mutually dependent (the resolver feeds the provider which sets the tokens the glass + neural-web consume); sub-splitting leaves a non-functional theme. Touches only client/src/theme/ + client/src/assets/backgrounds/ — file-disjoint from CLIENT-core (scaffold/gateway/state-machine) so the two foundation specs build without clobber. Theme ships COMPONENTS; the shell (CLIENT-core/world) wires them into main.tsx — theme never edits main.tsx. -->

## Assumptions
- CLIENT-core has scaffolded `client/` (Tauri 2 + React 19 + TS + Vite per apex-tauri): `client/src/`, `main.tsx`, `vite.config.ts`, a non-transparent main window. Theme adds files under `client/src/theme/` + `client/src/assets/`; it does NOT edit `main.tsx` (the shell composes the exported providers). → impact: Stop (theme's files live inside core's scaffold; if the dir layout differs, match it).
- The window is **non-transparent** (apex-tauri WebKit-safe rule) — the photo background is an in-webview DOM element, NOT OS-desktop show-through. → impact: Stop (the entire glass approach depends on this; a transparent window breaks `backdrop-filter` on both WebView2 #12437 + WKWebView #13801).
- The design-brief palette matrix (9 vetted + 7 draft cells) + structural tokens + neural-web spec + forbidden patterns are frozen inputs; the canonical CSS/JS is `docs/research/mockups/travel-zoom-workspace.html`. → impact: Stop (reproduce its token/animation behaviour; do not invent palettes or tokenize the white/gold comet constants).
- The 7 draft palette cells carry the design-brief hexes but ship `vetted:false` → **excluded from live rotation** (the resolver falls back to a vetted+passing cell) until hand-tuned + a11y-passed + flipped to `vetted:true` (hand-tuning is a parked build-phase task). The 16 photo assets are not yet sourced (gradient fallback ships now). → impact: Low (placeholders are intended; the gate keeps unverified cells off-screen).

Simplicity check: considered hardcoding one palette + skipping the resolver — rejected; ambient theming (the living identity) is a locked design-brief requirement, and the resolver is a pure, well-bounded function. Considered Canvas/WebGL for the neural web — rejected at this scale (a handful of concurrent comets, not 100+ nodes); SVG + transform/opacity animation is WebKit-safe and matches the canonical mockup.

## Prerequisites
- Specs that must be complete first: **CLIENT-core** (provides the `client/` Tauri+React+Vite scaffold + the non-transparent window). File-disjoint from CLIENT-core otherwise.
- Environment setup required: none beyond CLIENT-core's `npm install` (no new runtime deps; pure CSS + React + TS).

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| client/src/theme/tokens.css | create | `@property --bg/--p/--a` (animatable) + the `.8s` ambient transition on `:root` **+ a `@media (prefers-reduced-motion: reduce){ :root{ transition: none } }` CSS-layer hard-stop** (a11y F2, independent of the JS provider); derived `--glass/--glass2/--hair` + a **`--focus-ring`** token (a11y F3); structural classes/utilities: `.glass` panel (radius 18–22px, `backdrop-filter: blur(22–30px) saturate(140–150%)` + `-webkit-` prefix + a `linear-gradient(var(--glass),var(--glass2))` background whose `--glass` fill is a **scrim floor of `≥0.72`-opacity `--bg`** (a11y B2 — guarantees ≥4.5:1 body text over the blurred photo) so blur samples **in-content**), grid mask, **specular sheen as a SEPARATE child element — NO `mix-blend-mode` on any element that also carries `backdrop-filter`** (apex-tauri #2, WebKit #176830), selection row, glow/caret, and `:focus-visible` rings using `--focus-ring` drawn **above** the glass (z-index). No literal hex in any component (forbidden pattern). |
| client/src/theme/palettes.ts | create | `PALETTES: Record<CellKey, {bg,p,a, vetted: boolean}>` — all 16 season×time cells from the design-brief matrix (**9 `vetted:true`, 7 draft `vetted:false`** per the matrix Status column); `CellKey = `${Season}-${TimeState}``; typed `Season`/`TimeState` unions. |
| client/src/theme/contrast.ts | create | Pure, dependency-free: WCAG relative-luminance **contrast ratio** + CIELab **ΔE76**; `cellPasses(cell): boolean` = body-on-`--bg` ≥4.5:1 AND large/UI-on-`--bg` ≥3:1 AND `--p`↔`--a` distinguishable (≥3:1 contrast OR ΔE≥20); `--focus-ring`↔`--bg` and ↔`--glass` ≥3:1 (a11y B1/F3/F4). |
| client/src/theme/ambient.ts | create | Pure resolver: `resolveCell(d: Date) -> CellKey` — season by N-hemisphere month, time-state by clock with **night = quiet-hours 23:30–07:15** (others split the waking window); **gates the result (a11y B1): if the cell is `vetted:false` OR `!cellPasses(cell)`, fall back to the nearest VERIFIED+passing cell** (same season's vetted time-state → else a fixed global default vetted cell) so draft/failing cells NEVER enter live rotation until hand-tuned+vetted; + `applyCell(cell, root=document.documentElement)` setting `--bg/--p/--a`. No side effects beyond the optional apply. |
| client/src/theme/AmbientProvider.tsx | create | React provider: resolves the cell on mount + on a clock tick (re-check at each minute / on the next state boundary), applies tokens to `:root`; exposes the active cell via context; honors `prefers-reduced-motion` (skip the `.8s` transition → instant set). Exports `useAmbientCell()`. |
| client/src/theme/PhotoBackground.tsx | create | In-webview DOM background element (**`aria-hidden="true"`** — decorative, a11y note) keyed to the active cell: loads the bundled local image `assets/backgrounds/{cell}.jpg` (never fetched — privacy), **per-cell CSS gradient fallback** when the asset is absent/fails (`onerror`), light dim overlay only. Sits behind the glass layers. |
| client/src/theme/relationships.ts | create | The real domain relationship edge map (Email↔Calendar/Tasks/Finance/People, Calendar↔Tasks/Travel/People, Finance↔Tasks/Travel, People↔Travel, Memory↔People, Review↔Finance/Schedule, **Projects↔Tasks, Projects↔Calendar** — design-brief + DECISIONS-LOG Tasks/Projects split) + the spoke set (every domain→core). **Domain ids imported from CLIENT-core `domains.ts`** (canonical 11 incl. `projects`). Consumed by the neural web (and later the world layout). |
| client/src/theme/NeuralWeb.tsx | create | The ONE SVG layer (**`aria-hidden="true"`** — purely decorative, carries NO actionable info: white = ambient flair, gold = ambient "event being sensed" but real events surface via ntfy/M6 proactivity not the comet; the genuine cross-spoke reaction signal is reserved/unbuilt — so reduced-motion suppression loses nothing) (behind cards, `pointer-events:none`, `transform-origin:0 0`, accepts the world `transform` as a prop so it transforms with the plane): curve skeleton (spokes `--p@20%`/edges `--p@16%`, quad-bezier bows) + ambient white drift (slow dash-march via `stroke-dashoffset` — **a known WKWebView perf risk, accepted because it's faint + fully suppressed under reduced-motion**) + two-tier comets (white flair on a random edge ~3s; gold event-comet inward on a spoke ~1.7s, full-length sweep). **The prominent comet sweep is animated via `transform: translate`/`opacity`/`clip-path` on a SHORT overlay path — NOT `stroke-dashoffset`** (apex-tauri #1 — not a safe property, janks on WKWebView). Animate via WAAPI/`@keyframes`/rAF — **NO SMIL**. White/gold are literal semantic constants (never tokenized). `prefers-reduced-motion` → static skeleton only. |
| client/src/assets/backgrounds/.gitkeep | create | Placeholder dir for the 16 bundled photo assets (sourcing = parked build-phase task; the loader's gradient fallback covers their absence). |
| client/src/theme/ambient.test.ts | create | Vitest: resolver maps known dates/times to the correct cell; the 23:30–07:15 night boundary (incl. the wrap across midnight); every Season×TimeState combination yields a defined palette; `applyCell` sets the three CSS vars; **(a11y B1) the resolver NEVER returns a `vetted:false`/failing cell — a date/time landing on a draft cell falls back to a vetted+passing one; (a11y B1/B2/F3/F4) `cellPasses` over all 16 cells reports body≥4.5 / large≥3 / `--p`↔`--a` distinguishable / `--focus-ring` legible, AND the `.glass` scrim composite ≥4.5:1 for the lightest + darkest photo cells**. |

## Tasks
- [ ] Task 1: Design tokens + WebKit-safe glass CSS — files: `client/src/theme/tokens.css` — `@property` color vars + ambient transition + the **`prefers-reduced-motion` CSS hard-stop** (F2) + derived glass/hair tokens + a **`--focus-ring`** token (F3) + the `.glass`/grid-mask/selection/glow utilities, with the in-content `backdrop-filter` background (the mitigation), a **`≥0.72`-opacity `--bg` scrim floor** in the glass gradient (B2), the **specular sheen as a separate child element (no `mix-blend-mode` on a `backdrop-filter` element)** (apex-tauri #2), and `:focus-visible` rings above the glass, all with `-webkit-backdrop-filter` prefix. — done when: `tokens.css` imports cleanly in the Vite build; a `.glass` element over a coloured parent shows the blur sampling that parent (manual/visual check noted); the sheen child carries no `backdrop-filter`; no literal hex outside the palette source.
- [ ] Task 2: Palette matrix + contrast util + gated ambient resolver + tests — files: `client/src/theme/palettes.ts`, `client/src/theme/contrast.ts`, `client/src/theme/ambient.ts`, `client/src/theme/relationships.ts`, `client/src/theme/ambient.test.ts` — the 16-cell matrix **with the `vetted` flag**, the `contrast.ts` WCAG-ratio + ΔE76 + `cellPasses` util, the pure `resolveCell` **gated to vetted+passing cells (B1)**/`applyCell`, the relationship/spoke map, and the resolver + contrast tests. — done when: `npx vitest run client/src/theme/ambient.test.ts` passes (all 16 cells defined; night boundary incl. midnight wrap; **resolver never returns a draft/failing cell; `cellPasses` reports the contrast results for all 16 cells**); `npx tsc --noEmit` clean.
- [ ] Task 3: AmbientProvider (clock-driven token application) — files: `client/src/theme/AmbientProvider.tsx` — resolves on mount + clock tick, applies tokens to `:root`, reduced-motion-aware, exports `useAmbientCell()`. — done when: `tsc --noEmit` clean; a mounted provider sets `--bg/--p/--a` on `document.documentElement` matching `resolveCell(now)` (unit/RTL check).
- [ ] Task 4: PhotoBackground loader + gradient fallback — files: `client/src/theme/PhotoBackground.tsx` — in-webview DOM bg (`aria-hidden="true"`) keyed to the active cell with a per-cell gradient `onerror` fallback. — done when: `tsc --noEmit` clean; the container carries `aria-hidden="true"`; with no asset present the component renders the cell's gradient fallback (no network request issued — verify no `fetch`/remote URL).
- [ ] Task 5: NeuralWeb SVG layer + animation contract — files: `client/src/theme/NeuralWeb.tsx`, `client/src/assets/backgrounds/.gitkeep` — the skeleton + drift + two-tier comets, **the prominent comet sweep via `transform`/`opacity`/`clip-path` (NOT `stroke-dashoffset`)** (apex-tauri #1), `aria-hidden="true"` + a decorative-only comment, shares `transform-origin:0 0`, reduced-motion static. — done when: `tsc --noEmit` clean; the SVG element carries `aria-hidden="true"`; renders the spoke+edge skeleton from `relationships.ts`; greps confirm NO SMIL and the comet colours are literal constants (see ACs).

## Wave plan
Wave 1: [Task 1, Task 2] | Wave 2: [Task 3, Task 4, Task 5]
<!-- Task 1 (CSS) + Task 2 (pure logic: palettes + contrast + gated resolver + relationships) are independent. Task 3 consumes Task 2's resolver + Task 1's tokens; Task 4 consumes Task 2's cell keys + Task 1; Task 5 consumes Task 1's --p + Task 2's relationships — all three are mutually independent → Wave 2. -->

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | client/src/theme/tokens.css, client/src/theme/palettes.ts, client/src/theme/contrast.ts, client/src/theme/ambient.ts, client/src/theme/AmbientProvider.tsx, client/src/theme/PhotoBackground.tsx, client/src/theme/relationships.ts, client/src/theme/NeuralWeb.tsx, client/src/theme/ambient.test.ts, client/src/assets/backgrounds/.gitkeep |
| Modify | (none) |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `cd client && npx tsc --noEmit` | Type gate (frontend layer — apex-tauri recipe) |
| `cd client && npx vitest run client/src/theme/ambient.test.ts` | Resolver test gate |
| `cd client && npm run build` | Vite build (confirms tokens.css + components compile) |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | client/src/theme/, client/src/assets/backgrounds/.gitkeep |
| `git commit` | "feat: CLIENT-theme Holo Tactical tokens + ambient resolver + photo bg + neural-web" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| (none) | pure frontend; no env/secrets |

### Network
| Action | Purpose |
|--------|---------|
| (no install) | reuses CLIENT-core's React/Vite; no new deps |
| (no runtime fetch) | photo assets are bundled/local only (privacy — forbidden to fetch) |

## Specialist Context
### Security
No secrets, no network. The privacy-relevant rule: the photo background is **bundled/local, never fetched** (design-brief / ADR-028) — the build must issue no remote image request. [Dispatch apex-tauri + apex-frontend reviewers; apex-accessibility for the palette-contrast gate.]

### Performance
WebKit-safe is a perf constraint, not polish: in-content `backdrop-filter` (no transparent-window blur), animate only transform/opacity/clip-path (compositor-friendly on WKWebView), `will-change:transform` only on the actively-animating world/comet nodes, no stacked blur passes, no `stroke-dashoffset` for the prominent comet sweep. The `.8s` ambient transition uses `@property` color interpolation (GPU-friendly). Comet sweep is rAF/WAAPI, one comet per curve at a time. The faint white drift's `stroke-dashoffset` march is an accepted minor WKWebView risk (suppressed under reduced-motion). **Recipe note (apex-tauri #4):** the Tauri integration compile gate (`tauri build --no-bundle`) is intentionally **deferred to CLIENT-core** — theme is frontend-only and adds no Rust; the frontend recipe (`tsc --noEmit`/`vite build`/`vitest`) is the full gate here.

### Accessibility
The contrast gate is **enforced at build, not deferred** (a11y B1): the resolver routes live traffic only through `vetted:true` cells that pass `cellPasses`; the 7 draft cells are excluded from rotation (fall back to the nearest vetted+passing cell) until hand-tuned + flipped to `vetted:true`. An AC computes, for **all 16** cells, body-on-`--bg` ≥4.5:1, large/UI ≥3:1, and `--p`↔`--a` distinguishable (≥3:1 or ΔE≥20). **Text-over-glass** (B2): the `.glass` scrim floor (`≥0.72`-opacity `--bg`) guarantees ≥4.5:1 worst-case body text over the blurred photo — checked for the lightest + darkest photo cells. `--focus-ring` (F3) ≥3:1 vs both adjacent bg and the glass surface, rendered above the glass. Decorative elements (NeuralWeb SVG, PhotoBackground container) are `aria-hidden` (notes); comets carry no actionable info (F1) so reduced-motion suppression loses nothing. Reduced-motion is enforced at both the JS provider AND a CSS hard-stop (F2). [apex-accessibility re-review the 7 draft cells when they're hand-tuned, before flipping `vetted:true`.]

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | client/src/theme/*.ts, *.tsx | TSDoc all exports; document the CellKey scheme, the resolver boundaries (quiet-hours night), and the neural-web animation contract |
| Design | docs/technical/architecture/design-brief.md | No change (source of truth); spec implements it. Note in commit that the 7 draft palettes + 16 photo assets remain parked. |

## Acceptance Criteria
- [ ] Run `cd client && npx tsc --noEmit` → verify: exit 0.
- [ ] Run `cd client && npx vitest run client/src/theme/ambient.test.ts` → verify: passes; all 16 Season×TimeState cells resolve to a defined palette; the night window 23:30–07:15 (incl. midnight wrap) maps to `night`; `applyCell` sets `--bg/--p/--a`.
- [ ] (a11y B1) Resolver-gate test → verify: for a date/time landing on each of the 7 draft cells, `resolveCell` returns a `vetted:true` cell that passes `cellPasses` — no draft/failing cell ever returned.
- [ ] (a11y B1/F4) Contrast test over all 16 cells → verify: each cell reports body-on-`--bg` ≥4.5:1, large/UI ≥3:1, and `--p`↔`--a` ≥3:1-contrast OR ΔE≥20. (Draft cells may FAIL here — that is expected and is exactly why the resolver excludes them; the test asserts the pass/fail classification, and that every `vetted:true` cell passes.)
- [ ] (a11y B2) Text-over-glass composite test → verify: with the `.glass` `≥0.72`-`--bg` scrim, worst-case body text contrast ≥4.5:1 for the lightest and darkest photo/gradient cells.
- [ ] (a11y F3) Focus-ring test → verify: `--focus-ring` ≥3:1 against both `--bg` and the `.glass` surface for all `vetted:true` cells.
- [ ] Run `cd client && npm run build` → verify: exit 0 (tokens.css + all theme components compile).
- [ ] Run `grep -RInE "<animate|animateMotion|stroke-dashoffset" client/src/theme/NeuralWeb.tsx` → verify: no `<animate`/`animateMotion` (no SMIL); any `stroke-dashoffset` is ONLY on the faint white-drift path, never the prominent comet sweep (manual confirm) — the sweep uses `transform`/`opacity`/`clip-path` (apex-tauri #1).
- [ ] (apex-tauri #3) Comet-colour greps → verify: a `grep -nE "var\(--" ` of the comet-rendering block is **EMPTY** (no tokenized comet colour), AND `grep -nE "rgba\(255,\s*201|rgba\(255,\s*255,\s*255,\s*\.9"` finds the literal white + gold constants (positive match).
- [ ] (a11y notes) Run `grep -nE "aria-hidden" client/src/theme/NeuralWeb.tsx client/src/theme/PhotoBackground.tsx` → verify: the SVG layer and the photo-bg container both carry `aria-hidden="true"`.
- [ ] (a11y F2) Inspect `tokens.css` → verify: a `@media (prefers-reduced-motion: reduce)` block sets `:root{ transition: none }`; the specular-sheen utility is a separate element with no `backdrop-filter`.
- [ ] Inspect `PhotoBackground.tsx` → verify: no `fetch`/remote URL; missing asset → per-cell gradient fallback.
- [ ] Inspect components → verify: no literal hex colours outside `palettes.ts` (tokens-only — forbidden pattern).

## Progress
_(Coding mode writes here — do not edit manually)_
