# UI Design Inventory — overhaul checklist (2026-07-04)

_Grounded in a full client-code sweep (React 19 + TS + Vite, Tauri v2, two windows: `main` + `ask`).
Purpose: the checklist for the owner's design-overhaul session — every surface that exists, every
surface incoming, and the owner's new overhaul items (theme setting + background photo upload).
Companion memory: `client-ui-travel-zoom-direction` (map direction LOCKED: pannable spatial
command-map, not tabs)._

## A. Theming foundation — do FIRST (prerequisite for any theme setting)

The good news: a real token system already exists (`src/theme/tokens.css`: `--bg/--p/--a/--text/
--muted/--glass/--hair`) plus an **ambient engine** (`src/theme/ambient.ts` + `palettes.ts`) that
auto-picks one of 16 season×time palettes and animates token transitions. A "theme setting" is
therefore mostly a control layer over machinery that exists — EXCEPT these surfaces bypass tokens
with hardcoded hex and would ignore any theme until tokenized:

- [ ] `src/settings/KeysPanel.tsx` — entirely separate inline hex palette (`#12151c`, `#84a9ff`, …)
- [ ] `src/ask/AskPopup.tsx` — deliberately PINS the winter palette (`#060c14/#58c6ff/#fff0d8`); decide: keep pinned or follow theme
- [ ] `src/App.tsx` — empty-state, gear button, top bar hexes (`#7aa2ff`, `#0b0c0f`, `#f4f7fb`)
- [ ] `src/main.tsx` — crash-boundary hexes
- [ ] Fonts: "Space Grotesk" is referenced but never loaded (`@font-face` missing — silently falls back to system). Bundle it or drop it.

**Design decision for the session:** how does a manual theme setting relate to the ambient engine?
Options: (a) modes = Ambient (auto) / fixed named themes / custom accent color; (b) ambient stays,
setting only picks the palette family. (CSP note: packaged-exe CSP already needed `'unsafe-inline'`
for styles — memory `client-exe-csp-inline-style-gotcha`; any theme mechanism must survive the exe,
so test in the built app, not just `tauri dev`.)

## B. Background photo upload (owner request)

Surprisingly low-lift — the layer already exists: `PhotoBackground.tsx` renders per-ambient-cell
photos from `src/assets/backgrounds/{cell}.jpg` with a computed gradient fallback (no photos are
committed today, so everyone sees the gradient). To make it owner-uploadable:

- [ ] Settings control: pick image → store in the app data dir (brain-side or Tauri fs)
- [ ] CSP-safe loading: packaged exe CSP is `'self'`+ipc — load via Tauri asset protocol (`convertFileSrc`) or blob URL, NOT a raw file path
- [ ] Design decisions: one global photo vs per-ambient-cell photos; dim/blur scrim intensity control; what the gradient fallback looks like per theme

## C. Surfaces that exist — restyle candidates (current state, with file)

**Screens**
- [ ] Pairing screen (`src/auth/PairingScreen.tsx`) — glass panel, animated brain mark, recovery sub-form
- [ ] Connecting splash (`src/App.tsx` inline)
- [ ] World shell + top bar (`src/App.tsx`) — brand, breadcrumb, vault status, Ask/Home/Reset buttons, keys gear (⚙ fixed top-right)
- [ ] Empty-map state (`src/App.tsx`) — "Your map is empty" + Open Ask CTA
- [ ] Ask window (`src/ask/AskWindow.tsx`) — undecorated always-on-top 640×420; the only custom-chrome window

**Map surface** (`src/world/`)
- [ ] CORE node (pulsing orb + rings) — decorative center
- [ ] World cards / nodes (`CardSlot.tsx`) — glass chrome bar + drag grip + glance face
- [ ] Glance faces (`src/card/GlanceFace.tsx`) — count + tiles variants; **nothing registered today, all nodes show placeholder "—"**
- [ ] NeuralWeb (`src/theme/NeuralWeb.tsx`) — spokes + relationship edges + comet pulses
- [ ] Dock (`src/world/Dock.tsx`) — bottom glass dock, 2-letter buttons
- [ ] Minimap (`src/world/Minimap.tsx`) — decorative, bottom-left
- [ ] Camera: continuous CSS zoom 0.42–2.4, zoom-toward-cursor, travel-dip animation. **No zoom-LOD bands yet** — the cb5b research assumed dot→pill→card LOD; that's net-new design+build, not a restyle.

**Panels / popups**
- [ ] Ask popup (`src/ask/AskPopup.tsx`) — chat thread, engine tag, mic/send row + ALL its cards: plan card, invoke-confirm card, status card, result card, pending-credentials card, message bubbles
- [ ] Keys panel (`src/settings/KeysPanel.tsx`) — saved keys, Telegram bless, Connect-Google, add-key form
- [ ] Detail overlay (`src/card/DetailOverlay.tsx`) — FLIP-morph glass dialog + Telegram bless toggle
- [ ] Domain detail shell (`src/screens/DomainDetailShell.tsx`) — shared scaffold: loading/error/empty/locked states, pills, rows, engine tags
- [ ] Per-domain details (v1 carryovers, render inside overlay): Gmail, Calendar, Tasks, Projects, Finance (SVG donut), Review, Generic (people/travel/memory/knowledge/health)

## D. Surfaces INCOMING — need first-time design (no visuals exist)

- [ ] **Models panel (part 3B, Pending Spec #13)** — per-role model dropdowns over `eligible_providers`, constraint badges, usage/cost columns, PUT-422 inline errors, dropped-overrides notice. Brain + data layer SHIPPED; this is the visible half.
- [ ] **Domain-first map rework (ADR-047 #10)** — PRIMARY nodes become domains (Calendar, Recipes, Spending) with freshness + pending badges; capabilities become satellite nodes revealed by zoom; a build-in-progress shows a construction-site node; a domain node is BORN when its domain first gets data. This reshapes the map's core visual language — biggest design item on the list.
- [ ] **Live step trace (agent-loop arc, AL-6)** — slim updating trace in Ask ("checking calendar → checking tasks → …") while the loop works; doubles as the dogfood debugging window.
- [ ] **Capability overlay + pending badges (cb5b-2/3/4, held for ADR-047 revision)** — full-page overlay, name+pending badge ("99+"), refresh toggle.
- [ ] **Settings home** — implied by the overhaul: theme setting + background upload + keys + models need a coherent settings surface (today only the Keys modal exists). Decide: one settings hub with sections vs separate panels.
- [ ] **No-match transparency (Finding D, lands with AL-4)** — visual distinction between capability-sourced answers and plain-LLM fallback answers in Ask.

## E. Cleanups the sweep surfaced (fold into overhaul or earlier specs)

- `src/screens/StatusDetail.tsx` — built but UNREACHABLE (not registered anywhere; only tests reference it). Decide: wire it (vault/status home?) or delete.
- `src/ask/ResultRow.tsx` — appears unused by AskPopup (renders its own bubbles); `EngineTag`'s `.ask-engine-tag` styles have no matching CSS. Dead-or-wire decision.
- `src/screens/GenericDomainDetail.tsx` — renders "Data not yet available" even when data exists (bug).
- World nodes have no per-card loading/error state (glance faces placeholder-only).
- Styling is inline `<style>` strings per component — fine for Tauri/CSP (with `'unsafe-inline'`), but the overhaul should at least consolidate shared card/panel styles into tokens.css classes so one theme edit propagates.

## Suggested design-session order

1. **A. tokenize** (unblocks everything; mechanical, could even be a pre-session Codex spec)
2. **Theme setting + B. background upload** (the owner's headline items; small settings surface)
3. **D. domain-first map** (biggest visual language decision — nodes, satellites, badges, construction site)
4. **D. Models panel + step trace + settings home** (new panels, conventional layouts)
5. **C. restyle pass** over Ask popup cards + Keys panel + detail screens with the new tokens
6. **E. cleanups** riding along wherever they fit
