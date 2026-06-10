# ADR-013 — Cross-module links: M4 as the entity backbone, ToolRegistry-mediated logical references

- **Status:** Accepted
- **Date:** 2026-06-10
- **Deciders:** owner + planning
- **Relates:** ADR-004 (owner-memory engine — `SemanticFact`/`EntityAlias` on per-person SQLCipher; this ADR promotes it to the entity backbone) · ADR-011 (spoke source-of-truth — modules own operational truth; this ADR governs how they *reference each other* without owning each other's records) · ADR-012 (gated-action staging — cross-module writes that leave the boundary still route through `ActionStagingService`) · ADR-006 (two-tier proactivity — hub synthesis runs in the heartbeat/Brain, not module joins) · ADR-007 (knowledge layer) · ADR-009 (`artemis.untrusted` — the shared boundary the Part-6 refactor candidate generalizes) · overview.md §"Domain modules" + §"Integration layer" · data-model.md (M4 schema, the home for the new entity types). Research basis: `docs/research/cross-module-links.md` (4-agent fan-out, 2026-06-09).

## Context

By the time Artemis carries ~10–15 spokes (Finance, Health, Comms, Travel, Doctor/Vet, Cooking, Shopping, …), the spokes must reference each other's entities — the *same person* appears in Calendar attendees, Gmail senders, Finance debts, and Comms threads; the *same place* appears in Calendar locations, Travel trips, and Doctor appointments. The first spoke wave (M8) already shipped one such link — the Task↔Event reference (M8-d-b) — but it was solved **ad-hoc**, as were the DESIGNED Finance→Productivity / Finance→Calendar / Gmail→Finance links. A flat web of ad-hoc per-module reference strings does not survive scale: the same person ends up keyed four different ways, links cannot be resolved or kept in sync, and "over-linking" (the Notion Relations Trap) creates decision fatigue.

The research fan-out (`cross-module-links.md`) converged on a single shape: cross-module relationships are **not a flat web** — they **hub** around three universal nodes (**Calendar**, **Memory/M4**, **Tasks**), with **Finance** as a wide passive receiver. The keystone is the **entity backbone**: M4 (`SemanticFact` + `EntityAlias`) is *already* a de-facto people/entity graph — every spoke writes person-facts to it and Gmail's urgency hook already *reads* it for "known sender." External prior-art (Notion, Obsidian, Monica, Mesh, Tana, Mem) unanimously validates a **central entity graph** and warns against hand-maintained over-linking.

A standalone Contacts/Entity module was considered and rejected on a **privacy clincher**: a separate entity registry would have to cross module scopes (whose key? which encrypted store?). M4 already lives in `owner-private` behind the M2 crypto wall — it is the correct home, and extending it avoids a new cross-scope store entirely.

This ADR must be locked **before Finance/Health/Comms/Travel are specced** — those are the spokes whose links break first under ad-hoc strings.

## Decision

Six decisions, locked together. They formalize the M8-d-b precedent into a project-wide contract.

| # | Decision | Statement |
|---|----------|-----------|
| **1** | **Canonical person pointer** | The cross-module person reference is the **stable M4 `person_fact_key`** (keyed on email / UUID per entity), **not** ad-hoc per-module strings. A module that needs to reference a person stores the `person_fact_key` and resolves it through M4. This is the single load-bearing anti-drift decision: ad-hoc keys break at ~10–15 spokes. |
| **2** | **Logical-reference contract** | A cross-module reference is a logical **`{module, entity_id}`** tuple stored on the *owning* record, resolved by calling the **target module's tool through the `ToolRegistry`** — the M8-d-b Task↔Event pattern, formalized. **Never** a cross-store DB join: scopes stay isolated behind the M2 wall (ADR-004/ADR-005), so resolution is always tool-mediated, never schema-coupled. |
| **3** | **Lifecycle-sync semantics** | When an owning entity changes or is deleted, its linked references **update or close** — no orphans. Generalizes M8-d-b's auto-cancel-old-block rule: the owning module surfaces a lifecycle change; referencing modules react via tools (e.g. Finance "bill paid" → linked Task closes; person merged → references repoint to the surviving `person_fact_key`). |
| **4** | **Hub query-time synthesis** | Unified cross-module views ("what's due this week", a person's full picture across spokes) are assembled by the **Brain at query time** via a tool fan-out across modules — **not** by module-level DB joins. Scopes stay isolated; synthesis is a read-time composition, not a shared schema. |
| **5** | **Bidirectionality + contextual surfacing** | Links are **bidirectional at the data layer** (following a link surfaces its backlink). Links are **auto-suggested, never hand-maintained** — surfaced contextually through the existing suggestion-inbox + recipe-graduation model (M8-d-c), not as a manual relation field. This is the explicit guard against the over-linking / decision-fatigue trap. |
| **6** | **Extend M4 — Person + Place + Goal** | Extend M4 (not a new module) with a **`memory.resolve_entity(ref)`** read-tool and the **`person_fact_key`** convention. **Home three entity types in M4: Person (now), Place/Location, and Goal.** Place (home/office/clinic — the currently-unhomed location entity) and Goal (yearly→project→task→habit chains, folding into the deferred Habits/Goals rail) are **committed as M4-homed entity types now**; their **detailed schema is deferred to each implementing spec** (M4-c amendment, the Habits/Goals rail, the Maps/location connector), but their **existence and home are locked here**. |

## Consequences

- **One canonical pointer kills the ad-hoc-string drift** before the spoke count crosses the breaking point. Finance/Health/Comms/Travel can be specced against a fixed person reference from day one.
- **ToolRegistry-mediated resolution preserves the M2 crypto wall** — no spoke ever joins another spoke's encrypted store; every cross-module read is an explicit, auditable tool call. The connector framing (translate external→contract) is unaffected.
- **M4 becomes load-bearing beyond memory recall** — it is now the entity registry every spoke resolves through. The `memory.resolve_entity` read-path becomes **hot** (called on most cross-module operations) and must be fast; this is a known cost to watch when M4-c is specced, not a blocker (brute-force KNN + indexed key lookup is already fine at per-person scale per ADR-004).
- **Hub synthesis is a query-time fan-out, not a schema** — unified views cost a tool round-trip per module rather than a join, but keep scopes isolated and let spokes evolve independently. This is the right trade for a privacy-partitioned system.
- **Place and Goal now exist as first-class backbone entities** — future spokes (Travel, Doctor/Vet, Health, Habits/Goals, Smart-home) point *at* them instead of re-inventing a location string or a goals table each. The Habits/Goals rail reservation in Productivity is now the designated Goal home.
- **Bidirectional + auto-suggested links fit the existing machinery** — the suggestion-inbox + recipe model (already built for M8-d-c) is the surfacing channel, so no new UI subsystem is needed; the GATE (permission-now) vs recipe-promotion (automate-later) distinction on the Review screen (ADR-012 / M7-b) must stay visibly separate.
- **Next concrete build step is an M4-c amendment spec** (separate, deferred): add `memory.resolve_entity` + `person_fact_key` + the Place/Goal entity schema. This ADR locks the *decision*; it does not itself produce build specs.

## Cross-cutting items flagged (not locked here — follow-ups)

- **Shared `artemis.untrusted` boundary helper** — the quarantine boundary is currently re-implemented per module (Gmail all-mail, Calendar external-event fields only, Productivity email-origin only, Finance all-email). Same principle, no shared helper. A refactor candidate (Part 6), tracked separately — **not** part of this ADR's lock.
- **`Tier-0` still unused** — all current spokes are Tier-1; the first Tier-0 candidate (Calendar/weather presence) is noted but not decided here.
- **Feature ideas spun off to `BACKLOG.md`** — gift-budget pipeline, person↔debt edge, unlinked-mention detection, relationship time-decay reconnection, task-deadline-vs-meeting conflict check, news-on-contact pre-meeting brief, Goal-cascade, health↔productivity correlation, Camera receipt-OCR. These are *applications* of this backbone, not part of the lock.

## Alternatives considered

- **Standalone Contacts/Entity module** — *rejected*: would have to cross module scopes (which key, which encrypted store), violating the M2 per-scope crypto wall; M4 already is the de-facto entity graph and already lives `owner-private`. Extending it is strictly less machinery and the only privacy-correct home.
- **Ad-hoc per-module reference strings (status quo)** — *rejected*: the explicit anti-pattern this ADR exists to kill; the same person keyed N ways breaks resolution and lifecycle-sync at ~10–15 spokes.
- **Cross-store DB joins for hub views** — *rejected*: would couple spoke schemas and pierce the scope isolation guaranteed by ADR-004/005; query-time tool synthesis (Decision 4) achieves the same views without the coupling.
- **Hand-maintained bidirectional relations (Notion-style)** — *rejected*: the over-linking / decision-fatigue trap surfaced unanimously in prior art; auto-suggested-contextual links (Decision 5) give the value without the maintenance burden.
- **Defer Place/Goal entirely to their owning spokes** — *considered, not chosen*: owner elected the end-state lock (all three entity types committed now) so the backbone is decided once and later spokes point at a fixed home rather than re-litigating it per spoke.

## Parked (build-phase)

M4-c amendment spec (`memory.resolve_entity` + `person_fact_key` + Place/Goal entity schema) · `memory.resolve_entity` hot-path performance check · shared `artemis.untrusted` boundary-helper refactor · Place entity ↔ Calendar deferred Maps connector reconciliation · Goal node ↔ Habits/Goals rail schema · first Tier-0 entity candidate.
