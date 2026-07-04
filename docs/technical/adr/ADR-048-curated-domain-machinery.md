# ADR-048 — Curated-domain machinery: domains emerge from conversation

- **Status:** **Accepted** — owner decision, 2026-07-04 (resolves Fork 1 from the session-10
  Wave-3 discussion).
- **Date:** 2026-07-04
- **Deciders:** owner
- **Refines:** ADR-046 (#7 domains-are-labels, #8 curated taxonomy, #9 referent). Design note:
  `docs/v2/curated-domains-machinery.md`.
- **Driver:** the ADR-046 spine ships synced domains (calendar); curated domains (tasks, notes,
  …) need the write machinery. The open fork: how do curated domains come to exist — emerge from
  conversation, or pre-seeded?

## Context

A curated domain is one string value in the store's `domain` column — no table, no schema, no
code (ADR-046 #7). The machinery (extractor, trusted write, referent, routing) is generic and
built once; a domain itself is near-free. The fork was therefore only about seeding: pre-make
canonical domains (`tasks`, `notes`) or let every domain appear on first save.

## Decision

| # | Decision | Statement |
|---|----------|-----------|
| 1 | **Domains emerge from conversation (option A→C)** | Nothing is pre-seeded. A curated domain exists the moment its first row is written — "add a task: …" creates `tasks`; "start tracking my workouts" creates `workouts`. |
| 2 | **Dynamic domain routing** | Read/curate routing matches utterances against the **live** domain list (`store.domains()` = `SELECT DISTINCT domain`), never a hardcoded roster. This is what makes emergence usable — any conversationally-created domain is immediately readable with no code change. |
| 3 | **Curated writes are trusted — they BYPASS the ingest quarantine** | Curated content is owner-typed, or copied from already-sanitized rows. It is written verbatim via `store.upsert` (`store.delete` for forget). `IngestService.save_row` (which runs the quarantine) is the wrong primitive for curated saves — it would restate/mangle the owner's words. |
| 4 | **One gated extraction call** | A cheap verb prefilter (save/note/remember/add/forget/log/track) gates ONE haiku-class extraction → `{op: save\|forget\|none, domain, content, referent}`; `op=none` falls through to the normal ask path. Reads pay nothing. |
| 5 | **Anti-fragmentation rule** | The extractor prompt receives the live domain list and MUST reuse an existing label when one fits semantically ("to-do" → `tasks`), creating a new domain only when genuinely new. This replaces pre-seeding as the canonical-label mechanism. |
| 6 | **Referent resolution** | The last read's ordered result set is held per-session, TTL-evicted (existing `expiry.py`). "Save the second one" resolves ordinals deterministically, fuzzy references via the extractor; only the row's `sanitized_text` is copied — never the raw payload. |

## Alternatives rejected

- **B — pre-seed `tasks` + `notes`:** an empty domain is invisible to `SELECT DISTINCT`, so
  pre-seeding needs an extra registry mechanism just to make empty folders visible to routing —
  *more* machinery than A→C, not less — and it hardcodes the ontology ADR-046 #7 exists to avoid.
  Its benefits are covered elsewhere: canonical labels by decision #5, briefing inputs by Fork 2's
  own sequencing.

## Consequences

- The briefing (Fork 2, still open) reads whatever domains exist — no guaranteed inputs; it must
  degrade gracefully over the live domain list.
- The per-domain freshness gate must treat curated domains as **always fresh** (no fetcher, no
  upstream, never stale).
- Discoverability: "what are you tracking for me?" answers from `store.domains()`.
- Build decomposition (incremental, Wave-2 style): `curate-extract` → `curate-write + referent`
  → `dynamic-domain-routing`. None of it is per-domain.
