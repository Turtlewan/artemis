# Curated-domain machinery — Wave 3 design note (decision pending)

_Functional design from the 2026-07-03 (session 10) discussion, after the ADR-046 spine shipped
(Waves 0–2d). NOT a spec — captures the shape + the open fork so the owner can decide next session.
Companion to `local-data-spine.md` (ADR-046 step 3: curated domains + save-from-conversation)._

## The native-vs-dogfood boundary (why curated CRUD is native)
ADR-046 #6 line, restated from the discussion:
- **Native (spec-built, human-reviewed):** anything touching the canonical store or the answer
  path — store, ingest, read, **and the curated write machinery** (save/forget + referent).
- **Build-by-chat (forge, via ask-Artemis):** **fetchers** only — the arms that reach *out* to
  external services. Per-capability, sandboxed, model-authored.

Curated CRUD is native for three reasons (none = "we know we need tasks"): it's **shared** (one
mechanism every curated domain reuses), **safety-critical** (writes to the source-of-truth store),
and has **no outside to sandbox** (curated data never leaves the box).

**Key realization:** a curated *domain* (tasks, notes, workouts) is **just a tag**, not a code build
(ADR-046 #7 — domains are labels, not schemas). So we don't "build tasks/notes" — we build the
generic machinery **once**; a domain is a near-free registration (or emerges from conversation).

## ✅ FORK 1 RESOLVED (2026-07-04): A→C — see ADR-048
- **A — Pure machinery, domains emerge from conversation.** Nothing pre-seeded; "start tracking my
  workouts" → the domain exists. Truest dogfood.
- **B — Machinery + pre-seed a couple** (tasks/notes). Minor polish + guaranteed briefing inputs;
  cost = hardcoding what "counts."
- **C — Machinery + dynamic discovery.** Seed nothing; read/briefing routing reads whatever domains
  exist (live `SELECT DISTINCT domain`).
- **Recommendation: A converging to C** (pure machinery + dynamic domain routing) — matches the
  dogfood thesis + end-state-scope preference. Owner never "builds a capability" to track something new.
- **RESOLVED: owner chose A→C (2026-07-04).** Decision + anti-fragmentation rule (extractor gets
  the live domain list, reuses existing labels) recorded in
  `docs/technical/adr/ADR-048-curated-domain-machinery.md`. B also rejected on a new argument:
  empty domains are invisible to `SELECT DISTINCT`, so pre-seeding would need an extra registry
  mechanism — B is *more* machinery, not less.

**Fork 2 RESOLVED (2026-07-04): DEFER — dogfood first.** Build the machinery, save real curated
data for a few days, then design the briefing from observed use (what's actually in the store +
what the owner found themselves asking for). Decision returns to the queue after that dogfood window.

## The machinery — 4 small parts on top of the built spine
Flow: `utterance → verb-prefilter → [①extract] → [③resolve referent] → ②trusted write → confirm`;
otherwise falls through to the local read (② over the live domain list) → selector/invoke → router.

1. **Curate-extractor.** Cheap verb prefilter (save/note/remember/add/forget/log/track) gates ONE
   haiku extraction → `{op: save|forget|none, domain, content, referent}`. `op=none` → fall through.
   One call, only on likely-writes (reads stay free). New module (`curate.py`), wired into
   `ask_routes` before the read short-circuit.
2. **Trusted write (design correction).** Curated content is owner-typed OR copied from
   already-sanitized rows → **trusted → BYPASSES the ingest quarantine**, `store.upsert` **verbatim**
   (`store.delete` for forget). ⚠️ The Wave-1a `IngestService.save_row` (which *runs* the quarantine)
   is therefore the WRONG primitive for curated saves — it would "restate"/mangle the owner's note.
   Curated needs a thin trusted-write path (no quarantine). Reuses `store.upsert`/`store.delete`.
3. **Referent ("that one").** After any read, stash the ordered result set in per-session state
   (`app.state.last_results`, TTL-evicted via the existing `expiry.py`). A write referent ("the second
   one" / "the dentist one" / "that") resolves against it — ordinal deterministically, fuzzy via the
   extractor — then copies that row's **sanitized_text** (never raw payload) into the target domain.
4. **Dynamic domain awareness.** `store.domains()` = `SELECT DISTINCT domain`; read/curate routing
   matches the utterance against the **live** domain list instead of the hardcoded `DEFAULT_DOMAINS`.
   This is what makes A/C work — any conversationally-created domain is readable with no code.

**Likely decomposition (incremental, Wave-2 style):** `curate-extract` → `curate-write + referent`
→ `dynamic-domain-routing`. None of it is per-domain — it's the engine every curated domain reuses.

## Reused vs new
- **Reused (already built):** `store.upsert`/`delete`/`query` (Wave 0), `expiry.py` eviction, the
  haiku-port idiom, the `ask_routes` short-circuit pattern (Wave 2a).
- **New:** `curate.py` (extractor+schema), a trusted-write wrapper, per-session referent state,
  `store.domains()`, and read-routing over the live domain list.
