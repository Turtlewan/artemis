# ADR-045 — Built capabilities as nodes on the spatial command-map (CB-5b)

- **Status:** **Proposed** — owner + planning, 2026-07-03 (build not yet greenlit).
- **Date:** 2026-07-03
- **Deciders:** owner + planning
- **Refines:** the capability-driven client map (memory `client-map-capability-driven`, `client-ui=travel-zoom-map`) and ADR-039 (capability invoke/reuse). Reuses the existing `LayoutStore`/`/app/layout` (CR-4), the `card/DetailOverlay` pattern, and the `Scheduler`/`ProactiveWorker` (Slice 3).
- **Design basis:** CB-5b display research (`docs/findings/cb5b-display-*-2026-07-01.md`) + owner decisions 2026-07-03.

## Context

Built capabilities are invisible: `/app/capabilities` lists them but nothing renders them on the map,
which still shows the empty v1 domain screens. CB-5b makes each built capability a node on the locked
spatial travel-zoom command-map, turning the map into "here's what you built + what needs you" — the
concrete form of the capabilities-not-spokes reframe.

## Decision

| # | Decision | Statement |
|---|----------|-----------|
| 1 | **One node per capability; glance = name + pending-count badge** | The node itself shows only the capability **name** and a **pending-count badge**; counts > 99 render **"99+"**. No other detail on the node. |
| 2 | **Open → large full-page overlay** | Opening/zooming a node loads a **large full-page pop-up overlay** (reusing the `card/DetailOverlay` pattern) with `goal`, `built_at`, `uses` lineage (a click-through list, **not** a graph), trust info (egress domains, secrets, `auth_status`), and the capability's surfaced items. |
| 3 | **Deliberate, persisted placement (reuse the layout store)** | Node positions persist via the existing `LayoutStore`/`/app/layout` (a capability node is a `CardPlacement` keyed by capability name). The client **auto-seeds** an initial position (a ring near CORE) on first render if none exists, and drag-to-rearrange persists through the existing LWW endpoint. No new layout store. |
| 4 | **`goal` + `built_at` metadata** | Add `goal` (one-line "what it does" — already produced as `BuildProposal.goal`, just threaded through) and `built_at` (stamped at promote) to SKILL.md frontmatter + the `Skill` model + the capabilities DTO. Shown in the overlay. |
| 5 | **Pending count via proactive refresh, consent-gated** | The pending count = items the capability surfaces needing attention. Kept current by **reusing the `Scheduler`**: a capability **opted into background-refresh** (a consent flag mirroring the bless model) is run on an interval by a refresh runner that caches its latest count+items brain-side; the node reads the cache (**no live invoke on render**). Not opted in = no refresh, count 0. Never run a credentialed capability on a timer without the opt-in. |
| 6 | **Structured refresh-output contract** | A refresh run expects the capability's tool to print a small JSON `{"count": int, "items": [{"title": str, "detail": str}]}` to stdout (distinct from freeform invoke output). The refresh runner parses it **fail-soft** (unparseable/absent → count 0, keep last-known). A capability declares it surfaces items via its refresh opt-in; no new sandbox mechanism. |
| 7 | **Domain grouping deferred** | No `domain:` frontmatter tag now; nodes are placed by hand (decision 3). Revisit auto-grouping/coloring later. |

## Consequences

**Phasing (so the visible map ships without the refresh subsystem):**
- **Phase 1 — visible map:** metadata (`goal`/`built_at`) + client nodes (name + count-from-DTO, 0 until Phase 2) + placement (client-seeded into the existing layout store) + the full-page overlay. Buildable on existing data.
- **Phase 2 — live attention:** the refresh subsystem (structured `{count,items}` contract + a refresh cache + scheduler wiring + the consent opt-in) + the refresh opt-in UI.

**⚠️ Metadata-file collision (coordination — see specs' Prerequisites).** `goal`/`built_at` touch
`types.py`, `skill_md.py`, `store.py`, `capability_routes.py` — the **same files** as
`verify-auth-unverified-mark` (`auth_status`) and `oauth-3-invoke-integration` (`oauth_scopes`).
**Recommendation:** merge all four field-additions (`auth_status` + `oauth_scopes` + `goal` + `built_at`)
into ONE small `capability-metadata` spec built once, rather than three specs serially rewriting the
same four files. If not merged, they MUST be strictly sequenced (no concurrent build).

**Positive:** the map becomes a live, owner-arranged attention board; the empty v1 domain screens can
retire. **Costs:** Phase 2 runs credentialed capabilities on a timer (bounded by the opt-in + the
existing sandbox); the refresh cache is new brain state.

## Alternatives considered
- **Rich card on the node (zoom-LOD dot→pill→card)** — the research default; owner instead chose a minimal node + full-page overlay (decisions 1–2).
- **Last-run count (no refresh subsystem)** — simpler, but a stale badge defeats the glance-board purpose; owner chose proactive refresh (decision 5).
- **New layout store for capabilities** — rejected; the existing `LayoutStore`/`CardPlacement` already models positioned map cards (decision 3).
