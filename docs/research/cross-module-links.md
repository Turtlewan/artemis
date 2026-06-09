# Research: Cross-Module Links Across All Functional Modules
**Date:** 2026-06-09
**Confidence:** HIGH (internal) — 2 repo-grounded agents (current + future links) + 1 entity-architecture analysis; MEDIUM-HIGH (external) — 1 prior-art research agent, sources cited.
**Re-research after:** 2026-09-09 (architecture clock) — but the **ADR below should be written before Finance/Health/Comms/Travel are specced.**

> Synthesis of a 4-agent fan-out (2026-06-09): A = current internal links (repo) · B = future-spoke links ·
> C = external prior-art (Notion/Obsidian/Monica/Mesh/Tana/Mem) · D = shared-entity backbone. The four
> converge on the same shape; this doc is the consolidated map + the ADR-shaped decisions.

## Summary
Cross-module relationships in Artemis are **not a flat web** — they hub around a small set of nodes.
**Three universal hubs** absorb almost all links: **Calendar** (every time-sensitive spoke), **Memory/M4**
(every durable-fact spoke), **Tasks** (every obligation-detecting spoke). **Finance** is a wide *passive
receiver* (every spending spoke links in). The keystone decision is the **entity backbone**: don't build a
new Contacts module — **extend Memory (M4 SemanticFacts) into a callable person/entity backbone** and make
the **M4 `fact_key` the canonical cross-module person pointer**. External prior-art unanimously validates a
central entity graph, and warns against over-linking ("auto-suggest, don't hand-maintain").

## Part 1 — The three universal hubs (the core insight)
| Hub | Who links in | Mechanism |
|-----|--------------|-----------|
| **Calendar** | Travel, Doctor/Vet, Health, Smart-home, Dev, Cooking, Shopping, Finance, Comms (≥8 spokes) | `find_time` + `calendar.schedule_task` / `create_event` tools via ToolRegistry; Task↔Event link is the precedent (M8-d-b, BUILT) |
| **Memory (M4)** | Every spoke (durable facts); highest-stakes = Doctor/Vet, Health | A.U.D.N. write path; **also the de-facto people/entity store** (see Part 5) |
| **Tasks (Productivity)** | Every obligation-detecting spoke (Doctor follow-ups, Comms action items, Shopping lists, News, Dev issues) | suggestion-inbox + recipe-graduation (M8-d-c pattern), replicated 6–8× |
| **Finance** (receiver) | Travel, Doctor, Health, Shopping, Cooking, Dev, Camera (receipts) | `QuarantinedReader` extraction generalizes to any structured-from-untrusted source |

## Part 2 — Current internal links (BUILT / DESIGNED) — from Agent A
**Uniform spoke→core (the consistent part):** every spoke (Calendar, Gmail, Productivity, Finance) does the
same three outbound flows — Knowledge push (`IngestPipeline.ingest`), Memory push (`MemoryWritePath`/A.U.D.N.),
Proactive hooks (`HookSpec` in `ModuleManifest`). All current spokes are `OWNER_PRIVATE` → all hooks **Tier-1**.

**Spoke↔spoke (the ad-hoc part):**
| Source → Target | Linked by | Mechanism | Status |
|---|---|---|---|
| Productivity ↔ Calendar | task time-blocking; Task↔Event link; reschedule auto-cancels old block | ToolRegistry `calendar.schedule_task` | **BUILT** (M8-d-b) — *the precedent* |
| Finance → Productivity | bill → task promotion; lifecycle sync (bill paid → task closes) | logical `{module, entity_id}` ref + `task.create` tool | DESIGNED (finance.md), **ad-hoc** |
| Finance → Calendar | subscription/bill → calendar marker | logical ref + `calendar.create_event` | DESIGNED, **ad-hoc** |
| Gmail → Finance | bank/receipt/subscription mail → transactions | Gmail mirror → `QuarantinedReader` → `TransactionExtract` | DESIGNED (finance.md) |
| Calendar/Gmail/Finance → GATE | external-effect writes staged | `ActionStagingService.stage` → Review | DESIGNED (GATE-a) |
| Gmail/Calendar/Finance/Productivity → DR-a | untrusted inbound content | `QuarantinedReader` | DESIGNED |

## Part 3 — Future-spoke links (DESIGNED-vision) — from Agent B
Highest-value forward links (full table in agent output; key ones):
- **Travel** → Calendar (trip blocks) · Finance (per-trip expense envelope — multi-currency already in FIN model) · Doctor/Vet (vaccinations) · Tasks (checklists) · Memory (visited places/prefs) · Smart-home (away mode).
- **Cooking** ↔ **Shopping/Pantry** (ingredients vs stock — bidirectional) · Cooking → Calendar (meal plan) · Health (nutrition) · Finance (grocery spend) · Memory (favourite recipes).
- **Doctor/Vet** → Calendar (appointments — high-stakes write) · Tasks (follow-ups) · Finance (medical bills) · Memory (diagnoses/meds/allergies — safety-critical) · Health (clinical baseline) · Knowledge (records).
- **Health & Fitness** → Calendar (workout slots, `find_time` constraints) · **Productivity Habits rail** (the deferred M8-d Habits/Goals reservation is *exactly* this) · Finance (health spend) · Memory (weight/conditions/meds) · Doctor/Vet · Cooking (macro targets).
- **Comms (Telegram)** → Tasks (action items) · Calendar (informal invites Gmail can't catch) · Memory (who-said-what) · Finance (bill splits) · **Gmail** (cross-channel contact dedup *via Memory* — neither knows the other's messages; Memory is the join).
- **Notes/Journal** → *everything* (richest episodic feed for Memory; owner-authored = **trusted**, no quarantine needed) · Tasks (capture) · Finance (cash-expense notes — fills the cash gap) · Health (symptom/mood logs).
- **Camera/Vision** → Smart-home (occupancy) · **Finance (receipt-photo OCR — closes the cash-transaction gap!)** · Memory (faces → people) · Health (form/food) · Notes (photo+voice journal). **Reads more as a sensor layer than a user-facing module.**
- **Smart-home** → Calendar (presence) · Camera (occupancy) · Health (sleep environment) · Tasks (geofenced reminders) · Memory (home/away patterns).
- **News/Web watcher** → Knowledge/Memory (via DR-b/c quarantine) · Finance (price/market context) · Tasks (reading todos).
- **Dev workstation** → Tasks (issues/PRs) · Calendar (ceremonies) · Memory (tech decisions) · Knowledge (docs/ADRs) · Finance (SaaS spend).
- **Document input** → Knowledge (Docling, M3's intended feeder) · Finance (statements/receipts — manual-import path) · Health (lab results) · Tasks (action items in docs).

## Part 4 — Non-obvious links from prior art (the "links you won't see") — from Agent C
The highest-value output of the research — links mature tools surface that a naive design misses:
1. **Person → debt/money-owed edge** ("I owe X $50 / X owes me") — Person↔Finance bidirectional. (Monica)
2. **Gift-budget pipeline** — Birthday (Calendar) → gift idea (Person) → budget line (Finance) → shopping item: a **4-hop cross-domain chain**. (Monica + Zapier)
3. **Person → travel co-occurrence** — "who was I with on Trip X" (Person↔Travel↔Finance triangle). (Gridfiti)
4. **Person → recommendations made/received** — "Alex recommended this restaurant/recipe" surfaces in Shopping/Cooking. (Gridfiti)
5. **Unlinked-mention detection** — a name in an email/note/task without an explicit link → suggested connection, across Email+Notes+Tasks+Journal. (Obsidian/Logseq)
6. **Subscription/expense → calendar renewal alert** (already in Finance design — validated).
7. **Task-deadline pressure on meeting scheduling** — flag if an attendee has a hard deadline the same day (task↔calendar↔person). *No surveyed tool does this fully* — a differentiator.
8. **Reading highlight → project/task** (Tana + Readwise) — news/email highlight pipes to Tasks/Notes.
9. **Semantic relationship time-decay** — reconnection prompts from communication-frequency patterns, not fixed intervals (Person → relationship-health-score → reminder). (Mesh)
10. **Goal-cascade** — yearly Goal → project → weekly task → daily habit. **Artemis has no Goal entity** (Habits/Goals deferred); this is the missing node. (Tana)
11. **Health-log ↔ mood/energy ↔ productivity correlation** — "low-energy days correlate with missed tasks." (Life-OS templates)
12. **News/public-update on a contact → pre-meeting brief** (Person→News→Calendar). (Mesh)

**Two design constraints from prior art:**
- **Bidirectional by default** at the data layer (PKM tools make following a link show the backlink automatically).
- **⚠️ The "Notion Relations Trap":** over-linking → decision fatigue. Consensus: **auto-suggest links, don't require hand-maintenance**; surface links *contextually* (only when relevant). This fits Artemis's suggestion-inbox + recipe model perfectly.

## Part 5 — The entity backbone (the keystone) — from Agent D, validated by C
**Recommendation: do NOT build a new Contacts/Entity module. Extend Memory (M4).**
- M4 `SemanticFact` + `EntityAlias` is *already* a de-facto people/entity graph — every spoke writes
  person-facts to it; Gmail's urgency hook already *reads* it for "known sender."
- **Privacy clincher:** a standalone entity registry would have to **cross module scopes** (whose key? which
  encrypted store?). M4 already lives in `owner-private` behind the M2 wall — the correct home.
- **The small fix:** add a `memory.resolve_entity(ref)` read-tool + a stable **`person_fact_key`** convention
  (keyed on email/UUID). An addition to **M4-c**, not a new module.
- **External corroboration (C):** every mature tool converges on a small set of first-class entity types
  (Person, Place, Event, Project, Document) whose nodes persist across domains. M4 supplies Person/fact;
  Place/Location is currently **unhomed** (flagged — Calendar's deferred Maps connector).

## Part 6 — Cross-cutting findings (beyond links)
- **`artemis.untrusted` boundary is re-implemented per-module** (Gmail all-mail, Calendar only external-event
  fields, Productivity only email-origin, Finance all-email) — same principle, no shared helper. **Refactor
  candidate:** a shared trusted/untrusted source-boundary helper.
- **GATE (`PendingAction`, permission-now) vs Recipe-promotion (M7-b, automate-later)** are correctly separate
  but share the Review screen — UI must keep them distinct.
- **Tier-0 is designed but unused** — all 4 spokes are Tier-1; no spoke opts into the always-on minimized
  corpus yet (ADR-006). Fine, but note for the first Tier-0 candidate (Calendar/weather presence).
- **No `Place/Location` entity home** and **no `Goal` entity** — two structural gaps the later spokes need.

## Part 7 — What the cross-module-links ADR must lock
1. **Canonical person pointer = M4 `fact_key`** (recommended) vs ad-hoc per-module strings. *Load-bearing:
   ad-hoc breaks at ~10–15 spokes; decide before Finance/Health/Comms/Travel.*
2. **Logical-reference contract:** `{module, entity_id}` stored on the owning record; resolved via the target
   module's tool through the **ToolRegistry** (the M8-d-b pattern, formalized) — never cross-store DB joins.
3. **Lifecycle-sync semantics:** owning entity changes/deletes → linked references update/close (no orphans);
   generalize the M8-d-b auto-cancel-old-block rule.
4. **Hub query-time synthesis:** unified views ("what's due this week") assembled by the **Brain** across
   modules, not by module-level joins (scopes stay isolated).
5. **Bidirectionality + contextual surfacing:** links bidirectional at the data layer; **auto-suggested, not
   hand-maintained** (avoid the over-linking trap).
6. **Extend M4** with `memory.resolve_entity` + `person_fact_key`; home a **Place** entity; add a **Goal** node
   (folds into the deferred Habits/Goals rail).

## Backlog spun off (feature ideas from prior art → BACKLOG)
Gift-budget pipeline · person↔debt edge · unlinked-mention detection · relationship time-decay reconnection ·
task-deadline-vs-meeting conflict check · news-on-contact pre-meeting brief · Goal entity + goal-cascade ·
health↔productivity correlation · Camera receipt-OCR (cash-gap fill).

## Sources
- Internal: `overview.md`, `data-model.md`, `brain.md`, `modules/{calendar,gmail,productivity,finance}.md`, M3/M4/M6/M7/M8-d-b/GATE specs, ADR-004/006/007/011/012.
- External (Agent C): Notion relations/rollups · Obsidian/Logseq unlinked mentions · Monica/Mesh/Dex personal CRM · Tana supertags/cascades · Mem.ai semantic links · Notion Life-OS templates · arXiv 2304.09572 (personal KG survey). Full URLs in the agent transcript.
