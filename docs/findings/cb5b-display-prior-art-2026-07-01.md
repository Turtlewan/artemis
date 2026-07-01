# CB-5b — Capability-Node Display: External Prior-Art Scan

**Date:** 2026-07-01
**Purpose:** Feed the CB-5b design decision — "what a capability node looks like on the map" — with concrete visual patterns from mature spatial/canvas/node-graph UIs. Research angle: external prior-art on visual node design, not Artemis internals.
**Blocking context:** CB-5b is deferred pending this display-design decision (see `docs/handoff/2026-07-01.md`). The data half (CB-5a) already ships `GET /app/capabilities` returning `{name, description, version, uses, secrets}` per promoted capability. The map is LOCKED to a pannable travel-zoom spatial command-map and must be **capability-driven** (render what agents built), not a hardcoded domain roster (memory `client-map-capability-driven`).
**Confidence tags:** OBSERVED = confirmed behavior of the named tool; SYNTHESIS = reasoned recommendation combining patterns.

---

## What data a capability node actually has (CB-5a contract)

From `src/artemis/api/capability_routes.py` `CapabilitySummary`, each node has exactly:

- `name` — instance identity (the label)
- `description` — one-liner (tooltip / close-zoom body)
- `version` — integer, bumps on rebuild
- `uses` — list of other capabilities it depends on (→ **edges** on the map)
- `secrets` — list of secret keys it needs (→ a lock/key affordance)

There is **no** status/health, no usage-count, no category/domain field, and no icon in the current
data. That shapes the design: importance-by-usage and status-badge patterns below are **not yet
backable by data** — they are future hooks, not launch features. The immediately backable signals
are: label (`name`), body (`description`), version tag (`version`), dependency edges (`uses`), and a
secret indicator (`secrets`). A category/color grouping would need a new field (or be derived from
`uses` topology).

---

## 1. Node anatomy

### Icon vs text vs icon+label

The dividing line across mature tools is **entity-nodes vs function-nodes**:

- **Function/verb nodes** → color + text, no icon. **Blender Shader Editor** (OBSERVED): header bar
  color encodes category (green=input, purple=shader, grey=converter), white title text, socket dots
  colored by data type — zero icons. **Unreal Blueprint** (OBSERVED): red=event, blue=function,
  colored pins; verbose text titles, no icons.
- **Entity/service nodes** → icon-primary. **n8n** (OBSERVED): a large colored circle with the
  service logo (Slack, Gmail) IS the identity; the text label is secondary. **Raycast** (OBSERVED):
  icon + name + a muted source pill.

**Implication for Artemis:** capabilities are entity-like (things you invoke), so icon-primary is the
right instinct — BUT there is no icon in the CB-5a data and self-authored capabilities have no logo.
Options: (a) derive a glyph from the first letter / a hash-to-icon; (b) a small fixed set of
category glyphs once a category field exists; (c) ship text-primary first (label + version), add
icons later. Text-primary-first is the honest launch given the data.

### Status / state badges

- **n8n** (OBSERVED) — canonical pattern: a **pill badge at fixed top-right**, same position on every
  node type so users learn where to look. Green pill = success (+ execution count), red pill+✕ =
  error, orange = waiting, spinning border ring = actively running. Badge only shown when there IS a
  status.
- **ComfyUI** (OBSERVED): state via **border glow** — yellow = queued, green = processing, red =
  error. No separate badge element.
- **Blender** (OBSERVED): disabled = header greys + body ~50% opacity; muted = dashed border. Best
  prior art for an **inactive** look: *desaturate + reduce opacity*.
- **Apple Vision OS / Launchpad** (OBSERVED): **radial progress ring overlaid on the icon** for
  install/update — the cleanest "loading/building" affordance.

**Implication:** no status field exists yet, so a status badge is a **future hook**. But the *build
flow* (CB-4) does have live stages (Authoring → Sandboxing → Verified). A node that is mid-build
could borrow the Vision-OS radial ring or ComfyUI border glow; a freshly-verified node could pulse
once (Launchpad "just installed"). Reserve the n8n top-right pill slot for later run-status.

### Version tagging

Almost no mainstream node tool shows version always-on (OBSERVED across n8n/Blender/ComfyUI). Where
it appears (Snyk dep-graph, n8n deprecation banner): **version is hover/detail content, and only
becomes glanceable when a mismatch is a problem** (then it's an orange warning). CB-5a has an integer
`version` — show it as muted small text at close zoom (e.g. `v3`) or in the detail overlay, not as a
prominent chip. A version bump could trigger a brief "updated" pulse.

### Size / weight for importance

- **Obsidian Graph View** (OBSERVED): node radius ∝ √(backlink count) — highly-connected notes are
  visibly bigger, capped ~3×. Creates automatic hub/periphery hierarchy from data.
- **Kumu.io** (OBSERVED): size encodes a mapped attribute, explicit.
- **n8n / iOS Springboard** (OBSERVED): all nodes identical size; importance = position/convention.
- **Raycast** (OBSERVED): lower-relevance results at ~70% opacity.

**Implication:** Artemis has no usage data yet. The one quantitative signal available is `uses`
degree (how many capabilities depend on this one) — an Obsidian-style √(dependents) size scaling is
data-backable *today* and would make foundational capabilities read as hubs. Otherwise, prefer
**opacity for inactive/unused** and keep sizes uniform until real usage data exists (size-encoding
without data feels arbitrary).

### Load-bearing vs decorative (cross-tool synthesis)

- **Load-bearing:** header/category color, port/edge color by relationship type, icon-or-first-glyph
  (identity), label text (name).
- **Decorative:** border radius, shadows, gradients, texture.
- **Frequently over-used:** node *shape* (nearly everyone uses rectangles/circles and encodes meaning
  elsewhere).

---

## 2. Clustering & grouping on a pannable canvas

### Spatial proximity vs explicit containers

- **ComfyUI Group node** (OBSERVED): drag-select → "Group" → a colored labeled bounding rectangle
  that is *purely visual* (doesn't change topology). Closest prior art for a "domain cluster."
- **Blender frames** (OBSERVED): rectangular containers that move with their contents.
- **n8n sticky notes** (OBSERVED): yellow post-it rectangles for manual grouping; otherwise grouping
  = manual proximity only (no auto-layout).
- **Obsidian** (OBSERVED): **auto-clustering** — force-directed layout where shared links pull nodes
  together; color-by-tag makes clusters legible. Clustering is *emergent from data*, not imposed.
- **tldraw / Excalidraw** (OBSERVED): no auto-clustering; pure spatial + optional group-as-unit.
  Excalidraw frames collapse to a label at far zoom.

**Implication:** Artemis's existing map already uses hand-tuned cluster poles (`world/clusters.ts`
seeds 11 domains around Comms/Planning/Knowledge/Self) — but that's the hardcoded roster CB-5b must
move away from. For capability nodes the choice is: (a) **force-directed with a category/`uses`
bias** (Obsidian-style, emergent, handles unknown counts) vs (b) **explicit labeled cluster
containers** (ComfyUI-style, deterministic, memorable positions). Force layout is prettier and
scales but positions are non-deterministic (user can't memorize locations); explicit containers are
predictable but need a grouping key (category field doesn't exist yet — would derive from `uses`).

### Level-of-detail (LOD) zooming

The **dot → title/pill → full-card** three-level LOD is near-universal:

- **Miro/Mural** (OBSERVED): far = colored dot, mid = title only, close = full content.
- **Figma** (OBSERVED): text → solid block → label-only as you zoom out.
- **Obsidian** (OBSERVED): below a zoom threshold, labels hide, circles remain.
- **n8n / Unreal** (OBSERVED): **no LOD** — nodes stay fixed size and become illegibly tiny at far
  zoom. A known pain point; a cautionary tale.

**Implication:** the Artemis map already has a real camera with `minScale 0.42 … maxScale 2.4`
(`world/camera.ts`). Wiring LOD to those scale bands is the single most reusable pattern here:
- zoom < ~0.55 → dot (category color)
- ~0.55–1.05 → pill (glyph + name)
- > 1.05 → full card (name, description, version, secret/lock, dependency edges)

### Category grouping strategies

- **Blender** (OBSERVED): header color alone lets you parse "all green = inputs" without spatial
  clustering — color-as-category is high leverage.
- **Raycast filter** (OBSERVED): applying a category filter **dims non-matching to ~20% opacity**
  in place rather than reorganizing — an in-place filter, cheap and non-disorienting.

---

## 3. Prior-art tool survey — concrete patterns

### Blender Shader Editor
Header-bar color = category (6 colors). Socket color = data type (8 colors). Disabled = grey header +
50% body opacity. Muted = dashed border. Selected = orange border. Error = red socket/text.
**Steal:** color grammar carries all categorical info; desaturate+dim for inactive.

### Unreal Blueprint
Red=event, blue=function, dark-grey=comment frame. White pins = execution flow, colored pins = data
flow (visually separable). Error = red exclamation overlay. **Steal:** two edge *types* rendered
distinctly (Artemis has one edge type today — `uses` — but the principle: make edge semantics
visible).

### n8n Workflow Canvas
Icon-circle identity; **top-right pill badge** (green+count / red+✕ / orange) at a fixed position;
disabled = desaturated 60%; active = spinning orange border ring; trigger nodes get a lightning-bolt
corner overlay; connections are grey beziers that animate traveling dots during execution.
**Steal:** fixed-position status pill; animated edges to show live activity.

### ComfyUI
Dark header + text label; ports labeled with data-type dots; **live output preview embedded inside
the node body**; border glow for state (queued/processing/error); user-colored Group containers.
**Steal:** embed the last-run result / a micro-preview inside the card at close zoom — the node IS
its own output panel, no separate detail trip needed for a glance.

### Obsidian Graph View
Circles; **size ∝ backlink count** (auto hub/periphery); color by tag/folder; orphans = small grey
circles (instantly spot unused/disconnected); hover highlights node+neighbors and dims rest to ~20%;
force-directed emergent clustering; labels hide below a zoom threshold. **Steal:** size-by-degree
(from `uses`) for automatic importance; orphan styling for capabilities nothing depends on;
hover-to-highlight-neighborhood.

### tldraw / Excalidraw
No semantic vocabulary (pure user shapes). Excalidraw frames collapse to a label at far zoom.
**Steal:** frame-label-at-far-zoom for any cluster containers; also a caution — a fully freeform
canvas gives zero affordance for system-generated state, so Artemis needs *some* imposed grammar.

### macOS Launchpad
Empty state = grid of dashed placeholder slots + prominent App Store icon (the grid structure itself
signals "more should be here"); install = radial progress ring + %; update = blue dot; folder =
thumbnail grid of contained icons; growth fills left-to-right, top-to-bottom. **Steal:** a ghost/
placeholder structure makes emptiness read as "expecting growth" rather than "broken."

### Raycast
Icon + bold name + **muted source pill** (which extension provided it) + right-aligned shortcut.
Filter dims non-matches. **Steal:** the **source/origin pill** maps directly to Artemis — show which
agent/recipe authored a capability as a secondary muted label.

### Apple Vision OS app grid
Floating cards in space with no grid background read as *objects*, not data points; radial progress
ring for install. **Steal:** gridless floating placement makes each node feel like a "thing" (fits
the spatial-command-map metaphor better than a rigid grid).

---

## 4. Empty → growth legibility

The problem: 0 nodes must not look broken; 3 nodes must not feel sparse; 50 nodes must not overwhelm.
Artemis's map **already shows an "Open Ask" empty-state** (memory + `capability-build-ux.md`), so the
0-node case is partly handled.

### Patterns (OBSERVED origins)

1. **Hero node first** (App Store featured / Miro onboarding): first node large + centered +
   "First capability built by Artemis"; later nodes normal size around it. *Tradeoff:* makes the
   first special; awkward when "first" is arbitrary.
2. **Orbital / force layout from a center of gravity** (Obsidian, MindNode): first node at center,
   later nodes attracted by category/`uses` and orbit; empty categories invisible. *Tradeoff:*
   beautiful when populated, jittery, non-deterministic positions.
3. **Expectation grid / ghost placeholders** (Launchpad, Notion gallery): faint dashed slots fill in
   as capabilities build; empty slots say "more coming" with a "+ Build a recipe" hint. *Tradeoff:*
   legible emptiness, but a grid can feel imposed on an organic spatial map.
4. **Fade-in constellation** ("stars appearing"): dim dot-grid background; each new node fades/scales
   in; related nodes drawn together by proximity force. *Tradeoff:* most satisfying, needs animation
   work, positions can feel arbitrary.
5. **Fixed-grid temporal ordering** (iOS home screen): new nodes append end-of-grid; position =
   creation order. *Tradeoff:* simple/predictable, but position encodes nothing about relationships.

### Population-level behavior (SYNTHESIS)

- **0 nodes:** keep the existing empty-state; illustrated map outline + "Build your first recipe" CTA.
- **1 node:** empty-state fades, single node appears at the brain-core center, one attention pulse.
- **2–5 nodes:** all full cards, labels visible; loose cluster, no clustering machinery needed;
  camera auto-fits (`travelTo`/`home` already exist).
- **6–15 nodes:** category color / `uses`-bias grouping matters; weak clustering force or soft halos.
- **16–50 nodes:** LOD engages (dot at far zoom); clusters gain labeled halos; pan required.
- **50+ nodes:** filter/search overlay becomes primary; Raycast-style in-place dimming of
  non-matches; far-zoom cluster collapse to a single cluster node.

---

## Top design conclusions (ranked by leverage)

1. **LOD: dot → pill → card across the existing `minScale…maxScale` bands.** Highest-leverage, proven
   everywhere, and the camera already exists. Not doing it = n8n/Unreal's illegible-at-far-zoom trap.
2. **Icon/glyph + label + muted source pill (Raycast pattern).** Entity-node grammar; the source pill
   ("built by <agent/recipe>") is the one attribution signal that fits the self-authored story. Ship
   text-primary first since CB-5a has no icon.
3. **Force-directed layout with a `uses`/category bias (Obsidian pattern), rendering `uses` as
   edges.** Handles unknown, growing node counts and clusters emergently — the antithesis of the
   hardcoded roster CB-5b must retire. Tradeoff = non-deterministic positions (mitigate with the
   existing layout-persistence bridge so positions stick once settled).
4. **Fixed top-right status-pill slot + Vision-OS radial ring for mid-build (n8n + Launchpad).**
   Reserve the slot now; wire real run-status when the data exists. The build flow's live stages can
   drive a ring/border-glow immediately.

### Backable-today vs future-hook

- **Backable now (CB-5a data):** label (`name`), body/description at close zoom, version as muted
  text, `uses` → edges + size-by-dependent-degree, `secrets` → lock/key affordance, LOD, source pill
  (if the builder is recorded), empty→growth staging.
- **Future hooks (need new data):** run status badge, usage-frequency importance, category color
  (unless derived from `uses` topology), embedded live output preview.

---

## Sources / tools surveyed

Blender Shader Editor, Unreal Blueprint, n8n, ComfyUI, Obsidian Graph View, tldraw, Excalidraw,
macOS Launchpad, Raycast, Apple Vision OS app grid, Figma/Miro/Mural (LOD), Kumu.io, Snyk dependency
graph. Cross-referenced against Artemis internals: `client/src/world/` (camera, clusters, WorldPlane),
`src/artemis/api/capability_routes.py` (CB-5a `CapabilitySummary`), `docs/v2/capability-build-ux.md`,
`docs/handoff/2026-07-01.md`.
