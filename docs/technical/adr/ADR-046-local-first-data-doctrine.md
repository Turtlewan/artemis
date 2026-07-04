# ADR-046 — Local-first data doctrine (system-of-record, sync-not-fetch)

- **Status:** **Accepted** — owner + planning discussion, 2026-07-03 (session 9, after the first
  full live build-by-chat smoke).
- **Date:** 2026-07-03
- **Deciders:** owner
- **Refines:** ADR-035 (reach-out stack — the fresh-pull web path stays as the live exception),
  ADR-039 (capability invoke/reuse — its per-invoke quarantine moves to ingest for stored data),
  memory `daily-briefing-path-a-dogfood` (briefing = local reads across domains).
- **Driver:** invoke latency. The live smoke showed every ask stacks sequential cloud model calls
  (intent classify → select → isolate spin-up → live OAuth fetch → 2-call quarantine → synth via
  the codex-first router) — 15–30s for "show me today's calendar". Owner: this is the top pain.

## Context

Every capability invoke re-fetched external data live and re-paid the dual-LLM quarantine tax in
the owner's ask path. The owner wants asks to feel near-instant-to-conversational (~2–4s), wants
owner data stored locally, and wants the owner's system — not external services — to be the
canonical record.

## Decision

| # | Decision | Statement |
|---|----------|-----------|
| 1 | **Sync, don't fetch** | Any data that *can* live locally *does*: scheduled background jobs pull external data into a local store. The ask path never does network fetches for storable data. |
| 2 | **The owner's system is the source of truth; external services are pull-only sources** | Data flows ONE WAY: external → ingest → local store. Artemis NEVER writes back to external services (no publish, no two-way sync, no conflict machinery; OAuth scopes stay read-only). Once ingested, the local record is canonical. Owner-created data (tasks, notes, saved items) lives only locally and is authoritative by definition. |
| 3 | **Quarantine at ingest, once** | The dual-LLM quarantine (ADR-009 posture) runs when data ENTERS the store, storing the sanitized form. Reads of stored data pay no per-read quarantine. Same safety, paid in the background. |
| 4 | **Read path = local read + ONE small phrasing call** | An ask over stored data is an in-process store query plus a single small/fast model call (haiku-class) that phrases rows conversationally. No isolate spin-up, no router-default (codex-first) synth in the ask path. Target ~2–4s. |
| 5 | **Freshness threshold gates the slow path** | Per-domain threshold: synced data younger than it → answer locally, instantly; older → take the live fetch path for that ask. Cadence + threshold values are deliberately deferred, per domain. |
| 6 | **Native store/ingest/read; build-by-chat fetchers** ("option C") | The store, ingest sanitizer, read/query layer, and phrasing step are native brain plumbing — written once, human-reviewed, no model-authored code in the answer path. Build-by-chat authors only FETCHERS (scheduled capabilities that emit JSON rows) — the dogfood loop keeps building Artemis's data arms. Per-domain model-authored READERS are an explicit later escape hatch, not built now. |
| 7 | **One generic record store; domains are labels, not schemas** | Records: `domain · kind · key · payload(JSON) · sanitized_text · source · fetched_at`. A new capability introduces a new domain tag — never a table/migration (model-authored schema changes are a hard-block class). Native per-domain views may be added deliberately if a domain earns real structure. |
| 8 | **Domain taxonomy** | **Synced** (external feed mirrored locally: calendar, email, finance rows) — freshness applies. **Curated** (owner-created: notes, recipes, projects) — no upstream, never stale, light CRUD by chat ("save that", "forget that"). **Live** (websearch, "price right now") — the fresh-pull exception via the existing web-tool path; results optionally saved into a curated domain ("keep that one"). |
| 9 | **Save-from-conversation needs a referent** | "Save the second one" requires the ask flow to hold the last result set addressable for a follow-up. Small conversational state; generalizes to "add that to my tasks". |

## Consequences

- Every future capability/module is classified at design time: synced fetcher / curated domain /
  live pull. The forge's authoring guidance must encode this taxonomy so build-by-chat steers to
  the right shape.
- The daily briefing (Path A) becomes pure local reads across domains + one phrasing call —
  instant by construction.
- Feed re-pulls add/update feed-fields only; owner annotations are never overwritten (merge rule
  per domain — deferred knob with cadence/thresholds).
- Parked (owner: "ignore first"): pinning the CURRENT invoke path's synth call to the dedicated
  haiku port (today it resolves to the codex-first router — `ask_routes.py` `_router`). Largely
  mooted by decision 4 when the read path lands.
- Design note with the concrete shape: `docs/v2/local-data-spine.md`. Memory:
  `local-first-data-doctrine`.

## Security — accepted residual

- **Quarantine-once (#3) is a single soft gate — accepted residual (recorded 2026-07-04, from the
  session-10 data-spine security review):** the read path trusts stored `sanitized_text` verbatim
  (hardened by spotlight-wrapping records as data-only in the phrasing prompt, `48899ba`, at zero
  extra latency). A jailbroken ingest sanitizer could therefore smuggle attacker *text* into an
  answer. Bounded: the phrasing call is no-tools, so there is no exec/exfil path — worst case is a
  misleading sentence in a reply. Accepted as this ADR's latency trade (#3/#4).
