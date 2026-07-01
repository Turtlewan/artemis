# CB-5b: Capability Node Display — IA & Interaction Design
_Research date: 2026-07-01. Scope: information architecture and interaction design only — not visual
styling. Input to the CB-5b spec. Owner decision required on the node-vs-cluster question before
speccing begins._

---

## 1. Codebase anchor

What the map currently has:

| Thing | Location | Notes |
|-------|----------|-------|
| World plane | `client/src/world/WorldPlane.tsx` | 2600×1760 px world, transform-origin 0 0 |
| Camera | `client/src/world/camera.ts` | scale 0.42–2.4; HOME=0.72; FOCUS=1.05 |
| Domain placements | `client/src/world/clusters.ts` | 11 nodes, 4 named clusters (Comms/Planning/Knowledge/Self) |
| Card slot | `client/src/world/CardSlot.tsx` | draggable button; `onOpen(domain)` fires the detail |
| Glance face | `client/src/card/GlanceFace.tsx` | `count` or `tiles` variant; compact, non-scrolling |
| Detail overlay | `client/src/card/DetailOverlay.tsx` | FLIP morph; 820×620 max; scrollable body |
| Neural web | `client/src/theme/NeuralWeb.tsx` | ambient edge lines from domains to CORE |
| Capability model | `src/artemis/types.py` `Skill` | `{name, description, version, path, tags, uses[], secrets[]}` |
| Capabilities API | `src/artemis/api/capability_routes.py` | `GET /app/capabilities` → `CapabilitiesList` (already built, CB-5a) |

Capabilities are flat today: no spatial position, no client-side rendering, no Tauri command.
The `GET /app/capabilities` brain endpoint exists; the Tauri gateway command and TS wrapper are
deferred (noted in CB-5a as "dead-until-consumed").

---

## 2. Node vs Cluster

### Core question

Should each capability be a full node on the world plane, or should multiple capabilities be
compressed into a badge/count on their parent domain card, expanding only on zoom or click?

### The fundamental tension

The world plane at HOME_SCALE (0.72) shows roughly 1872×1267 world-pixels. The 11 domain cards
sit at 250×150 px each. A handful of capability nodes (say, 5–10) can coexist without visual
crowding — but 30+ would be chaos unless some level of grouping is applied from the start.

The right answer is **both**, gated by zoom level (see §4). But the grouping question is independent:
when capability nodes ARE visible, how many are rendered as independent nodes vs. folded?

### Grouping dimension

Three candidate dimensions:

**A. By domain they serve** — e.g., `email-extractor-store` orbits the Email domain card.
- Pro: leverages existing 4-cluster geography the user already understands.
- Pro: natural fit for capabilities that were built to extend a domain (most early ones will be).
- Con: many capabilities are cross-domain (a "date-parser" utility has no obvious home).
- Con: requires a mapping from capability → domain (not in the current Skill model; would need
  either tagging or inference from `uses`).

**B. By what it acts on (data type / subject matter)** — group by the noun it processes (email,
calendar, money, text, code, …).
- Pro: grouping survives as capabilities grow beyond the 11 domain roster.
- Con: requires classification logic (a new tagging dimension).
- Con: harder to explain to the owner ("why is this over here?").

**C. By build recency** — newest capabilities are most prominent, oldest fade or compress.
- Pro: recency is always known (file mtime or a `built_at` timestamp).
- Pro: matches the owner's mental model (new builds are what they just did).
- Con: orphans the spatial metaphor; a capability shouldn't wander around the map as new ones land.
- Con: no grouping benefit — just a sort order, not a clustering strategy.

### Recommended grouping: domain proximity, with a "capabilities" home for unclassified

Capabilities orbit their most-relevant domain card. When a capability clearly extends a domain (e.g.
`email-extractor-store` → Email), it is placed within the spatial region of that domain cluster.
When a capability is generic (a utility that no domain explicitly owns), it belongs in a reserved
region near the CORE — call it the "capabilities shelf" — which is always present and labeled.

The domain mapping can be inferred from `uses`: if `email-extractor-store.uses` contains
`email` (as a domain name string), it maps to the Email region. Otherwise, it goes to the shelf.
This keeps the mapping in the data model without requiring new API fields for CB-5b.

**Single-node vs cluster fold rule:**

| Condition | Treatment |
|-----------|-----------|
| ≤ 3 capabilities in a domain region | Each is its own node |
| 4–8 capabilities in a domain region | Each is its own node; nodes are smaller than domain cards |
| > 8 capabilities in a domain region | Compress all but the 3 most-recent into a "…N more" stack node |
| 0 capabilities anywhere | Domain card shows no badge; capability shelf is absent or ghost-faded |

This avoids designing for scale that doesn't exist yet (early Artemis will have < 10 capabilities
total) while not making the rule impossible to extend.

---

## 3. Click → Detail view

### Content hierarchy

The existing DetailOverlay shell (820×620, focus-trapped, FLIP morph) fits without modification.
The capability detail panel fills its scrollable body section. Proposed sections in order:

**Section 1 — Identity (always visible, non-scrolling header zone)**
- Name (as the existing `card-overlay__title` h2) + version badge inline: `email-extractor-store · v2`
- One-line description (subtitle, muted color), truncated to 2 lines
- Status pill: "Active" (promoted to library) vs "Staged" (future; not in current model)

**Section 2 — What it does**
- Full description text (the `description` field from Skill)
- The SKILL.md `body` prose if available (the agent's authored reasoning/instructions).
  This is not currently surfaced through the API — the `CapabilitySummary` DTO omits `body`.
  CB-5b would need to either: (a) add `body` to the `CapabilitySummary` API response, or
  (b) fetch the full SKILL.md on demand (a `GET /app/capabilities/{name}` endpoint that returns body).
  Option (b) is cleaner — body can be large; lazy-load on detail-open.

**Section 3 — Dependencies (uses)**
- Header: "Requires"
- Each `uses` entry as a clickable pill. Click navigates within the overlay to that capability's
  detail (push onto an overlay nav stack; back-arrow to return). This is the main lineage UX.
- If `uses` is empty: show "No dependencies".

**Section 4 — Secrets**
- Header: "Needs access to"
- Each secret name as a pill (never a value). Grayed out if not yet configured; green-dot if set.
  This is future — the secret-status API doesn't exist yet. For CB-5b: just list the names.

**Section 5 — Provenance**
- "Built by Artemis" (always)
- Build date: requires a `built_at` timestamp. Currently not in the Skill model. Either add it at
  promote time (write to SKILL.md frontmatter) or derive from filesystem mtime (fragile on copies).
  **Recommendation: add `built_at: ISO8601` to the SKILL.md frontmatter in `write_skill_md()` at
  promote time.** Small model change, avoids filesystem fragility.
- Source request: the `goal` text from the `BuildProposal`. Also not persisted today. Same fix:
  write `goal:` to SKILL.md frontmatter at promote time.

**Section 6 — Version history**
- Simple text: "v1 → v2 → current v3". The store knows `version: int` (monotonically incremented
  on each promote). The overlay can just show the count: "Version 3 (rebuilt 2 times)".
  Full changelogs require storing previous version diffs — out of scope for CB-5b.

**Section 7 — Run/Invoke (future stub)**
- A "Try it" button, disabled for CB-5b (capability invocation is not wired). Label it "Try it —
  coming soon" so the affordance is legible without promising something that isn't there.

### Overlay navigation model

Rather than closing the overlay and reopening, `uses` clicks push a new view onto a micro nav stack
within the single overlay instance. This keeps focus inside the overlay, avoids FLIP jank on rapid
traversal, and works with the existing focus-trap. Back-arrow appears when depth > 0. Breadcrumb
trail: "email-extractor-store / date-parser".

---

## 4. Dependency / Lineage Edges

### The hairball problem

With 30 capabilities each having 2–3 `uses` references, naively rendering all edges at home zoom
produces a hairball. The existing NeuralWeb already solves an analogous problem (domain→CORE ambient
lines) by making them background texture rather than interactive overlays. The same layered approach
applies to capability dependency edges.

### Recommended three-tier progressive disclosure

**Tier 1 — Overview (scale < ~0.6):** No capability edges. Domain cards may show a small count
indicator ("5 caps") but no edge lines between capabilities. The NeuralWeb ambient lines continue
as before. Capability nodes are not rendered.

**Tier 2 — Home / cluster (0.6 ≤ scale < 1.2):** Capability nodes are visible as compact items
orbiting their domain parent. Spoke lines from the domain card center to each of its capability
nodes appear — these are short, local, and don't cross clusters. No inter-capability edges
(A `uses` B lines) at this zoom. The visual language is "each domain has satellite capabilities."

**Tier 3 — Focused (scale ≥ 1.2):** The hovered/focused capability node shows its `uses` edges
as dashed lines to the nodes it depends on. Only 1-hop edges for the active node, not the full
graph. Other capability edges are suppressed. This makes "what does X depend on" legible without
drawing the full dependency graph.

**In the detail overlay (any zoom):** The `uses` list as clickable pills (§3 above) is always the
primary lineage UI. The edge lines on the map are a secondary spatial hint, not a replacement for
the structured dependency list.

### Why not a full dependency graph view

A separate "dependency graph" tab inside the detail overlay is an obvious next step but out of
scope for CB-5b. It would require a force-directed mini-graph inside the overlay body. Defer. The
clickable-pill `uses` list gives 90% of the value without the rendering complexity.

---

## 5. Zoom-level interaction model

The existing camera has no explicit zoom thresholds that trigger rendering changes — scale is a
continuous value passed down to CardSlot as a prop. CB-5b would introduce the same pattern.

### Proposed thresholds (world-space, continuous)

```
scale < 0.55   → "galaxy": domain cards only; no capability nodes rendered;
                 domain card may show a small "N" badge in a corner.

0.55–0.85      → "home" (includes HOME_SCALE=0.72): capability nodes render as
                 compact pills (name only, truncated ~12 chars, ~100×36 px);
                 no inter-capability edges; domain→capability spoke lines appear.

0.85–1.3       → "cluster": capability nodes expand to mini-cards (~160×80 px)
                 showing name + 1-line description truncated; spoke lines visible.

1.3–2.4        → "focused" (includes FOCUS_SCALE=1.05 if camera zooms further):
                 full capability card renders; 1-hop uses-edges for hovered node;
                 click → detail overlay.
```

These thresholds are not hard-coded decisions — they need calibration against the real layout. The
key is that the pattern is: start invisible → compact pill → mini card → full card. This matches
how Figma handles frame contents at varying zoom levels.

### Glance face for capability nodes

At mini-card and full-card zoom, the capability node needs a compact Glance face. The existing
`GlanceContent` union (`count | tiles`) is sufficient:

- **Mini-card (compact):** No Glance face needed — just the name renders.
- **Full-card (focused):** Use `kind: "tiles"` with 2 tiles:
  - tile 1: `{value: "v${version}", label: "version"}`
  - tile 2: `{value: "${uses.length}", label: uses.length === 1 ? "dependency" : "dependencies"}`

This reuses the existing `GlanceFace` component without modification.

---

## 6. Data model changes required for full detail view

| Field | Where needed | Current state | Fix |
|-------|-------------|---------------|-----|
| `built_at` | Provenance section | Not in Skill model | Add to SKILL.md frontmatter at promote; expose in `CapabilitySummary` |
| `goal` | Provenance (source request) | Not persisted | Add to SKILL.md frontmatter at promote |
| `body` | "What it does" full text | Not in `CapabilitySummary` | Add `GET /app/capabilities/{name}` returning full detail |
| `tags` | Filtering / domain mapping | In Skill model but not `CapabilitySummary` | Expose in list response |

For CB-5b, the minimal viable detail view can skip `built_at`, `goal`, and `body` — show name,
description, version, uses, and secrets only. The richer provenance fields are a one-spec follow-up.

---

## 7. Open decisions for owner

1. **Node-vs-cluster threshold:** The "≤ 3 = own node, 4–8 = smaller own node, > 8 = stack" rule
   is a design choice. Simpler alternative: always one node per capability (the map stays sparse
   for a long time; the owner won't build > 30 capabilities in a month). The complexity of the
   fold is probably not worth it for CB-5b.

2. **Domain-mapping logic:** Infer from `uses` strings matching domain names, or require an explicit
   `domain` tag? The inferred approach is zero-config but fragile (a capability named `email-foo`
   with `uses: ["date-parser"]` has no email string in `uses`). Adding a `domain:` frontmatter
   field to SKILL.md is cleaner. Decide before speccing.

3. **Capability shelf (generic capabilities):** Do cross-domain capabilities float near the CORE,
   or does CB-5b simply place all capabilities in a single new "Capabilities" region separate from
   the 11 domain cards? The latter is simpler to implement first and can be refined later.

4. **Provenance data model:** Are `built_at` and `goal` worth adding to SKILL.md now, or deferred
   to when the detail view is actually built? Adding them at promote time costs 3 lines of code now
   and avoids retroactive migration. Recommendation: add them now.

---

## 8. Recommended IA (summary for spec author)

**Node rule:** One node per capability. No fold/cluster for CB-5b (the library is small; add the
fold rule when it's needed). Place capabilities near their domain cluster if the domain can be
inferred from `uses`; otherwise place in a dedicated "capabilities" region near the CORE.

**Glance face:** `kind: "tiles"` — version + dependency count. Reuse existing `GlanceFace`.

**Detail view contents (MVP for CB-5b):**
1. Name + version badge
2. Description (full text)
3. Uses (clickable pills; clicking opens that capability's detail inline in the same overlay)
4. Secrets needed (names only)
5. "Try it" (disabled stub)
Provenance (built_at, goal, body) deferred to a follow-up spec once the data model change lands.

**Edges:** Spoke lines from domain card → its capability satellites at HOME zoom. 1-hop `uses`
edges for the hovered node at FOCUS zoom only. Full dependency graph view deferred.

**Zoom levels:** Capabilities invisible below scale 0.55; compact pills at 0.55–0.85 (HOME);
mini-cards at 0.85–1.3; full cards at 1.3+.

**New API needed by the client:** Tauri `app_capabilities_list` command + TS wrapper (already
noted as deferred from CB-5a). Optionally `app_capability_detail(name)` for the body field.

---

_Pointer: raw exploration above; the §8 summary is the spec-input block._
