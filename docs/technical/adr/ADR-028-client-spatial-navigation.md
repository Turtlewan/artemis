# ADR-028 — Client navigation: spatial "travel-zoom" command-map workspace (supersedes the tab-shell)

- **Status:** Accepted — **supersedes the Review/Chat/Status tab-shell** in `app-flow.md` (originally ADR-010 §UI, carried into ADR-023). ADR-023 (Tauri platform) + ADR-025 (auth/wall) are **unchanged**.
- **Date:** 2026-06-23
- **Deciders:** owner + planning
- **Relates:** ADR-023 (Tauri desktop client — the platform this renders on) · ADR-025 (auth/lock states — still drive the chrome) · `design-brief.md` (Holo Tactical + ambient theming) · ADR-017 (superseded macOS surface).
- **Reference mockup (feel = source of truth):** `docs/research/mockups/travel-zoom-workspace.html`.

## Context
The Tauri client (ADR-023) inherited a conventional **tab-shell** home — a main window with Review · Chat · Status as sidebar/segmented tabs (`app-flow.md`). In a live design session the owner explored and rejected that and several others (left icon-rail; radar/bento/focus-strip variants; command-palette, windowed-desktop, timeline, and adaptive-briefing home paradigms), converging on a **spatial map** the user pans and zooms through. The decision is about *navigation/shell shape only* — it does not change the platform (Tauri), the auth/lock model (ADR-025), or what the screens contain.

## Decision

| # | Decision | Statement |
|---|----------|-----------|
| 1 | **Home = a pannable spatial command-map** | Not pages or tabs. **Domain glance cards** are placed on a large world plane around a central **pulsing "brain" core**; some cards sit off-screen by design. The home view is brain-centred. |
| 2 | **Navigation = pan + zoom + travel** | **Pan** (drag) and **scroll-to-zoom** (eased, toward cursor) with **gentle rubber-band bounds**. Reach any domain via its card, the **dock** (complete index of all domains), or the **minimap**. **Home / Esc** recenters. The camera **travels across** the space to a target (owner explicitly wanted visible travel, not a teleport); long hops use a zoom-out → pan → zoom-in arc for legibility. |
| 3 | **Open = travel-then-expand** | Selecting a domain flies the camera to its card, then the **glance card expands open in place** (shared-element morph) into a **full detail card that is the top-most layer**, floating over the still-visible, lightly-dimmed (~18%) map; it **collapses back into the card** on close. Transform/opacity only; layers pre-warmed so the first open isn't janky. |
| 4 | **Glance cards** | Minimal one-liner ("3 events today"); number + label **baseline-aligned, vertically centred, left-aligned**. **List domains → a count**; **fixed-metric domains** (e.g. Diet & Fitness) → fixed stat tiles. **The overview never content-scrolls** — no scrollbars inside cards (hard rule). |
| 5 | **Chat = a distinct floating "Ask Artemis" pop-up** | Branded, visually separate from the domain cards, summonable anywhere (⌥Space / top-bar button) — it is **not** a domain card or a tab. (Re-expresses the design-brief "summon panel".) |
| 6 | **Background** | Holo Tactical liquid glass floats over a **photographic background** (ambient season×time-driven per `design-brief.md`); **bundled/local in production, never fetched** (privacy-first). Glass shows the photo through — light dim only. |
| 7 | **Unchanged** | The ADR-025 connection/lock states (Unpaired · Disconnected · Vault-locked · Unlocked), the lock banner chrome, engine tags (`local`/`codex`/`review`) as a load-bearing privacy/cost signal, and accessibility (keyboard-operable, reduced-motion → crossfade) all carry over. |

## Consequences
- **`app-flow.md` is re-authored** around the map (the connection/lock spine + onboarding/pairing are retained; the three-tab main-window shell is replaced by the map + per-domain detail + the Ask pop-up).
- **`design-brief.md`** gains the spatial-navigation interaction model and the photo-background note; the "summon panel" is re-framed as the Ask-Artemis pop-up.
- **CLIENT-\* specs** (Tauri) build against this shell: a world/camera layer (pan/zoom/travel), a domain-card + detail-overlay component, a dock, a minimap, and the Ask pop-up. The Review/Chat/Status *content* is unchanged — only how you reach it.
- Domains are pluggable cards on the map (Schedule, Tasks, Finance, Diet & Fitness, People, Travel, Review, Memory, Email shown in the mockup — illustrative, not final).

## Alternatives considered
- **Tab-shell / left icon-rail** — *rejected*: conventional, doesn't fit the Jarvis-console feel or scale spatially.
- **Radar/orbital · bento wall · focus strip** (map variants) — explored; superseded by the free pan/zoom map.
- **Command-palette home · windowed desktop · timeline/day-spine · adaptive briefing** — explored as non-spatial paradigms; not chosen (briefing/command may still inform the Ask pop-up + proactivity later).
- **Brain-origin "teleport" zoom** (position-independent) — *rejected*: owner wanted to *see* the camera travel across the space.

## Parked (build-phase)
Dedicated **fonts pass** (deferred). · Final domain set + spatial grouping (work vs life clusters). · Whether to restore subtle hub→card constellation links. · Reduced-motion exact behaviour per transition. · Exact world-plane sizing / responsive bounds.
