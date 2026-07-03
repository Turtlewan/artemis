# Local data spine — design note

_Companion to ADR-046 (local-first data doctrine). Discussion 2026-07-03 (session 9). This is the
concrete shape for spec-writing; no specs exist yet — build order is an owner call._

## The picture

```
                    BACKGROUND (slow is fine)                 FOREGROUND (owner waits)
  ┌──────────────┐   scheduled    ┌────────┐  sanitized   ┌─────────┐
  │ Google / mail│──► fetcher ───►│ ingest │────────────► │  store  │◄── query ── ask
  │ / CSV / ...  │  (capability)  │(native,│   rows       │(native, │              │
  └──────────────┘                │ 1×quar.)│             │ SQLite) │       one haiku
                                  └────────┘              └─────────┘       phrasing call
                                                                                │
  websearch / "right now" ──────────── live web-tool path ─────────────────► answer
```

- **Fetchers** = build-by-chat capabilities (dogfood), run by the existing `Scheduler`, declare
  `oauth_scopes`/`egress` as today, emit JSON rows on stdout (the cb5b-3 `{count,items}` pattern
  generalized to `{domain, rows:[...]}`).
- **Ingest** (native): validate rows → dual-LLM quarantine ONCE → upsert into the store. Two
  entry points: scheduled fetcher output + on-demand save-from-conversation ("keep that one").
- **Store** (native): single SQLite in the brain data dir. Generic record schema:
  `domain · kind · key · payload(JSON) · sanitized_text · source · fetched_at (+ owner_fields
  for annotations that feed re-pulls must never overwrite)`. New domain = new tag value, never a
  migration.
- **Read path** (native): ask → store query (domain + time + text) → ONE haiku-class phrasing
  call → answer. No isolate, no router-default synth, no per-read quarantine. Target 2–4s.
- **Freshness gate**: per-domain config `{cadence, threshold}` — values deferred. Within
  threshold → local answer; beyond → live path for that ask.

## Domain taxonomy (classification test for every future capability)

| Type | Truth | Examples | Freshness | Notes |
|------|-------|----------|-----------|-------|
| **Synced** | Local record canonical once ingested; external = pull-only source | calendar, email, finance rows | applies | one-way flow; read-only scopes; feed re-pulls update feed-fields only |
| **Curated** | Owner-created, local-only | notes, recipes, projects, journal | never stale | CRUD by chat ("save/forget that"); no fetcher |
| **Live** | Nothing stored (unless saved) | websearch, prices, "is X up" | n/a | existing web-tool fresh-pull path; "keep that one" files result into a curated domain |

## What this is NOT

- NOT two-way sync: Artemis never writes to Google/external services (owner decision — Google is
  "a source of information we pull from", not a display). No publish queue, no conflicts.
- NOT per-domain reader capabilities: the answer path is native (ADR-046 #6). Model-authored
  readers are a later per-domain escape hatch if one earns it.
- NOT per-domain tables: model-authored schema changes are hard-block class.

## Open / deferred knobs (decide at spec time or later)

1. Per-domain sync cadence + freshness threshold values.
2. Per-domain feed-vs-owner-field merge rule (protect annotations).
3. The "that one" referent mechanism (hold last result set addressable for follow-ups) — small
   conversational state; generalizes to "add that to my tasks".
4. Forge authoring guidance update: teach the taxonomy so build requests author fetchers /
   curated domains / live pulls correctly (extends the AUTHOR_SYSTEM conventions added in
   session 9).
5. Parked: pin the CURRENT invoke synth to the haiku port (owner said ignore; mooted by the read
   path). Anatomy of today's 15–30s invoke is in the session-9 discussion (handoff 2026-07-03).

## Natural build order (suggestion, not a plan)

1. Store + ingest + read path (native core, one spec-cluster) — calendar as the first synced
   domain (fetcher = rebuild of `today-calendar` as a scheduled fetcher; OAuth + API already live).
2. Freshness gate + per-domain config.
3. Curated domains + save-from-conversation + referent.
4. Briefing = cross-domain read (Path A payoff).
