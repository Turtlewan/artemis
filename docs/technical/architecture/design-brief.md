# Artemis — Design Brief (visual identity + tokens)

_The home for visual decisions: art-direction, design tokens, and forbidden patterns. The image-less
coder reads this for every UI decision. Visual source-of-truth mockups live in `docs/design/*.html`
(open in Cursor via `Ctrl+P`)._

_Locked 2026-06-22 (owner + planning). UI build is later (Tauri client — ADR-023; Mac final host)._

## Art direction — "Holo Tactical"

A **liquid-glass, Jarvis-adjacent** command surface: dark, luminous, calm-tech. Frosted translucent
panels over a deep radial-gradient void, a faint tactical grid masked into the glass, soft coloured
glow, hairline borders, a blinking caret. Restrained, not arcade-y. Fonts: **Space Grotesk** (display /
UI labels / numerals) + **Inter** (body). Reference: `docs/design/summon-panel-mockup.html` variant ②.

## Locked — the "Ask Artemis" pop-up (shape)

Per **ADR-028** the home surface is the spatial command-map (see below); this panel is the floating
**"Ask Artemis" chat pop-up** (global hotkey ⌥Space), summonable over any view. Structure LOCKED:
- **Brand mark** (arc-reactor-style ringed circle, stroked in the primary colour, soft drop-glow).
- **Input line** (Space Grotesk, blinking caret) + a mode **hint** chip (`TASK` / `DIGEST` / `WIND-DOWN`…).
- **Results list** — each row: rounded icon tile · title + subtitle · a right-aligned **engine tag**.
  - Engine tags are first-class and load-bearing (the privacy/cost story is visible): `local` (local
    8B), `codex` (cloud), `review` (Gate / approval-pending, rendered in the **accent** colour).
- **Footer** — engine status chips: `● local 8B` · `● codex · <quota> left`, + a keyboard hint.

Two row colour roles drive everything: **`--p` primary** (brand, selection, most icons, glow) and
**`--a` accent** (alerts / `review` / secondary), over a near-black **`--bg`**.

## Locked — client navigation: spatial "travel-zoom" workspace (ADR-028)

The home is a **pannable spatial command-map**, not tabs/pages. Domain **glance cards** sit on a large
world plane around a central **pulsing "brain" core** (some off-screen by design). Locked behaviour:
- **Pan** (drag) + **scroll-to-zoom** (eased, toward cursor) with **gentle rubber-band bounds**; reach any
  domain via its card, the **dock** (complete index of domains), or the **minimap**; **Home / Esc** recenters.
- **Open a domain** = the camera **travels across** to its card, then the card **expands open in place**
  (shared-element morph) into a **full detail card = the top-most layer**, floating over the still-visible,
  lightly-dimmed (~18%) map; it **collapses back into the card** on close. Transform/opacity only; pre-warm
  the glass/blur layers so the first open isn't janky.
- **Glance cards:** one line; number + label **baseline-aligned, vertically centred, left-aligned**. List
  domains show a **count** ("3 events today"); fixed-metric domains (e.g. Diet & Fitness) show **fixed stat tiles**.
- **Chat** is the Ask-Artemis pop-up above — never a domain card or a tab.
Reference mockup (the feel = source of truth): `docs/research/mockups/travel-zoom-workspace.html`.

## Locked — connection lines: neural web + two-tier flow (2026-06-23)

The domains are wired into one **neural web** — a calm, living constellation. Canonical implementation (exact CSS/JS) lives in `docs/research/mockups/travel-zoom-workspace.html`. Three layers, all rendered in ONE SVG that sits **behind** the cards (`pointer-events:none`) and **transforms with the world plane** — it MUST share the world's `transform-origin:0 0`, or the lines drift off on zoom.

**1 — Curve skeleton (static).** Gentle quadratic-bezier bows, ambient-tinted via `--p`, restrained:
- **Spokes** — every domain → the central brain core: `stroke: color-mix(in srgb, var(--p) 20%, transparent)`, `stroke-width: 1.4`, bow ≈ 10% of the chord.
- **Edges** — domain ↔ related domain: `color-mix(in srgb, var(--p) 16%, transparent)`, `1.3`, bow ≈ 16%.
- The edge set is the **real relationship map** (Email↔Calendar/Tasks/Finance/People, Calendar↔Tasks/Travel/People, Finance↔Tasks/Travel, People↔Travel, Memory↔People, Review↔Finance/Schedule), mirroring the ADR-021 reaction design — NOT decorative.

**2 — Ambient drift (always-on heartbeat).** A faint **white** current flows slowly along every curve: `stroke: rgba(255,255,255,.15)`, `stroke-width: 1.4`, `stroke-dasharray: 4 14`, dash-march `~9s linear infinite`. Present but quiet — "alive and watching."

**3 — Firing comets (two tiers).** A short comet sweeps the **full length** of a curve — length scales to the curve (`dash = clamp(32, len·0.24, 100)`), gap > path length so exactly one shows, and a **linear full-length sweep** (it travels the whole curve; do NOT hardcode the travel distance, or long curves stall near the start):
- **White comet = ambient flair only — NOT a reaction.** Fires on a random *edge* ~every 3 s. `stroke: rgba(255,255,255,.95)`, `stroke-width: 2.1`, white glow (`drop-shadow(0 0 5px rgba(255,255,255,.7))`). Pure life/movement.
- **Gold comet = a lower-level event being sensed** (new email, a memory write…). Fires on a *spoke*, flowing **inward** toward the brain core, ~every 1.7 s. `stroke: rgba(255,201,94,.97)`, gold glow (`drop-shadow(0 0 7px rgba(255,186,74,.82))`). This is the only tier that *means* something today.

**Reserved (not yet built):** a genuine cross-spoke **reaction** has no distinct on-map signal yet (white is decorative). When the reaction layer ships, give a real reaction its OWN treatment (distinct colour / double-pulse) so "Artemis acting" reads apart from the ambient shimmer.

**Reduced-motion:** render the curve skeleton statically — NO drift, NO comets.

## Locked — ambient theming system

The palette is **not fixed** — it **auto-shifts** with the real clock + calendar (a "living" identity).
Two axes:

- **Time-of-day (clock-driven), 4 states:** `morning` (cool, soft) → `afternoon` (bright, peak) →
  `evening` (warm-then-cool) → **`night`** (dim, low-luminance, calm). `night` aligns to the owner's
  **quiet hours 23:30 → 07:15** (owner-rules S1); the other three split the waking window.
- **Season (calendar-date-driven), 4 seasons:** Spring · Summer · Autumn · Winter.
  **Decorative, not climatic** — the owner is in **Singapore (seasonless / equatorial)**; seasons are an
  intentional aesthetic rotation by Northern-hemisphere months, chosen *because* SG lacks them, not to
  reflect local weather.

→ **4 seasons × 4 time-states = 16 ambient palettes.** Each cell defines `--bg` / `--p` / `--a`.

The home's **photographic background also rotates with the season×time state** — a curated, **bundled/local**
image per cell (never fetched, per ADR-028); the liquid-glass panels float over it with a light dim only.

## Palette matrix

9 cells are **vetted** (rendered + owner-approved in `docs/design/seasonal-time-schemes.html`). 7 cells
are **draft** (Summer ×4 + night ×3 — not yet mocked); the hexes below are *starting points to hand-tune*,
following the stated feel (Summer = bright/warm/saturated tropical; night = dim/deep/low-luminance).

> **Tune them live:** open `docs/design/theme-tuner.html` — all 16 cards with bg/primary/accent colour
> pickers that update each panel in real time; "Copy all as table" exports the current palette to paste
> back into this matrix. The table below is the canonical record; refresh it from the tuner when tuned.

| Season | Time | `--bg` | `--p` (primary) | `--a` (accent) | Status |
|--------|------|--------|-----------------|----------------|--------|
| Spring | morning   | `#08120e` | `#8fecb8` | `#ffc2a6` | vetted (re-derived) |
| Spring | afternoon | `#0a1612` | `#5fee9c` | `#84d2ff` | vetted (re-derived) |
| Spring | evening   | `#0a0c0d` | `#f2b487` | `#93d59a` | vetted (re-derived) |
| Spring | night     | `#05080f` | `#5aa6d0` | `#8fd0a8` | draft |
| Summer | morning   | `#0e0a10` | `#ff9e6e` | `#8fb0ff` | draft |
| Summer | afternoon | `#11140a` | `#ffd64a` | `#58c4f2` | draft |
| Summer | evening   | `#0d0908` | `#ff9f4a` | `#ff5e8a` | draft |
| Summer | night     | `#06080f` | `#4f9fc8` | `#e3a06f` | draft |
| Autumn | morning   | `#0f0c08` | `#e3b572` | `#93b39c` | vetted |
| Autumn | afternoon | `#100a05` | `#f0a23f` | `#c2552b` | vetted |
| Autumn | evening   | `#0d0606` | `#ff7338` | `#9a5ab0` | vetted |
| Autumn | night     | `#0a0707` | `#a06a44` | `#6a5a7a` | draft |
| Winter | morning   | `#080d14` | `#abe0ff` | `#ffc7a6` | vetted |
| Winter | afternoon | `#060c14` | `#58c6ff` | `#fff0d8` | vetted |
| Winter | evening   | `#07091a` | `#8aa6ff` | `#ffb479` | vetted |
| Winter | night     | `#05070e` | `#5a76b0` | `#b88a5c` | draft |

_(A fixed-scheme catalogue of 15 named palettes — Jarvis, Arctic, Nebula… — survives in
`docs/design/holo-color-schemes.html` as a fallback / alternate-skin bank, NOT the chosen direction.)_

## Structural tokens (stable across all palettes)

- **Panel:** `border-radius:18–22px`; `backdrop-filter:blur(22px) saturate(140–145%)`; border
  `1px` of `color-mix(in srgb, var(--p) 26%, transparent)`; layered shadow incl. a primary-tinted glow.
- **Grid mask:** 20–22px tactical grid of `var(--p) @ ~7%`, radial-masked to fade downward.
- **Specular sheen:** top-left `linear-gradient` white highlight, `mix-blend-mode:screen`.
- **Selection row:** `var(--p) @ 9%` fill + `1px` inset ring; hover nudges `translateX(2px)`.
- **Glow/caret/dots:** primary-coloured `box-shadow`/`drop-shadow` for the lit-glass feel.

## Accessibility (gate before any palette ships)

- **Every** palette cell (incl. all 7 draft + the 9 vetted) must hold text contrast on `--bg`
  (body text + the subtitle `small`) and a discernible `--p`/`--a` distinction — verify per cell, since
  ambient means any of the 16 can be on screen. (apex-accessibility review at UI-build time.)
- Honour `prefers-reduced-motion` (all mockups already gate animation off under it).

## Forbidden patterns (image-less coder)

- Do **not** hard-code a single palette — colours come from the active `--bg`/`--p`/`--a` tokens chosen
  by the ambient (season × time) resolver. No literal hex in components.
- Do **not** drop the **engine tag** on result rows — `local`/`codex`/`review` visibility is a product
  requirement (privacy/cost transparency), not decoration.
- Do **not** add a light theme — the identity is dark-only liquid-glass.
- Do **not** invent new seasons/time-states — the matrix is 4 × 4.
- Do **not** let the overview scroll — the map navigates by **pan + zoom only**; glance cards never
  content-scroll (no scrollbars inside a card). (ADR-028)
- Do **not** make the chat a domain card or a tab — it is the floating **Ask-Artemis pop-up** (ADR-028).
- Do **not** render the connection-line SVG with a transform-origin different from the world plane — both must be `transform-origin:0 0`, or the lines drift away from the cards when zooming.
- Do **not** tokenize the connection **flow/comet** colours to the palette: the curve skeleton is `--p`-tinted (ambient), but the **white** drift/flair and the **gold** event comet are intentional semantic constants — keep them white and gold across all 16 palettes.
- Do **not** hardcode a comet's travel distance — it sweeps the full measured length of each curve (short *and* long), or long curves visibly stall near the start.
