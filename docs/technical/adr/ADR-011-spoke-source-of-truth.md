# ADR-011 — First-spoke-wave source-of-truth model (default-mirror, no bidirectional sync)

- **Status:** Accepted
- **Date:** 2026-06-08
- **Deciders:** owner + planning
- **Relates:** overview.md §"Domain modules" + §"Integration layer" (the module-owns-truth principle; connectors translate external→contract); M7-b / ADR-010 (the CLIENT Review screen — the owner-approval surface gated writes route through); ADR-009 (`artemis.untrusted` — the quarantine all ingested email/external content passes through); ROADMAP.md §"After the core — spokes (M8+)".

## Context

The first spoke wave is **Productivity & time** (Calendar · Tasks · Projects · Habits/Goals) as a domain
**module** plus the **Gmail connector**. The overview's hub-spoke principle says *"domain modules own
operational truth."* But several of these domains have a **strong external system of record that multiple
parties write to** — Google Calendar (others invite you), Gmail (the provider owns the inbox) — while others
(Projects, Habits, Goals) have **no external system at all**. A single global "own vs mirror" choice is
therefore wrong in both directions: pure-own forces bidirectional sync onto the worst domains, and pure-mirror
is undefined for the Artemis-native ones.

The decision that actually carries cost is **not** "who is primary" but **"do we take on bidirectional
sync"** — the conflict-resolution / echo-loop / reconciliation subsystem. That is the expensive, data-loss-prone
part, and it is the same problem regardless of which side is called primary.

## Decision

1. **Source of truth is per-domain, not global.** **Mirror** (external = truth) for **Email** and
   **Calendar**; **Own** (Artemis = truth) for **Tasks, Projects, Habits/Goals** (Tasks with an optional
   *one-way* read-only export to Google Tasks — never read back).

2. **No bidirectional sync in wave-1.** Every domain is **single-direction-of-truth**: either external-is-truth
   with write-through, or Artemis-is-truth with one-way export. The conflict-resolution/echo-loop subsystem is
   **not built** — it becomes a **later, per-domain, on-demand** upgrade, added only when a concrete need
   appears (and never speculatively). Rationale: the always-on Mini + thin live clients mean offline editing —
   the only thing that *requires* bidirectional reconciliation — essentially never happens.

3. **Mirror is active, not passive — read + write-through.** A mirror domain reads via incremental sync tokens
   (near-real-time awareness of others' changes) **and writes through** to the external API for every mutation.
   Because writes hit the external system directly (not "edit a local copy, sync later"), the external system is
   **authoritative at every instant** → no divergent copies, no conflict resolution, no echo loops. A write
   either succeeds against the provider or fails and is surfaced.

4. **Calendar = active manager (mirror + write-through + a thin native proposal overlay).** Beyond read +
   write-through (create/move/cancel/RSVP), Artemis owns a **small native overlay** of things Google has no
   concept of — **proposals** ("move your 3pm to open a focus block"), **tentative holds**, **soft intentions**
   projected onto open slots. These are **Artemis-native data, NOT copies of Google events**, so they can never
   conflict; they render alongside the real calendar and are **promoted to real Google events via write-through
   on owner approval** (the CLIENT Review screen). This makes Artemis an active calendar manager without owning
   the calendar.

5. **Gmail = mirror, read-only/awareness in wave-1.** OAuth via apex-google (read scope) → every message
   through the `artemis.untrusted` quarantine (ADR-009 — email is the canonical injection vector) → searchable
   summaries to the knowledge layer + facts to memory. **Sending is deferred** (a later write capability).

6. **All external-effect writes are gated `TAKES_ACTION` recipes routed through the CLIENT Review screen;
   reads/awareness need no approval.** Write classification follows M7-b's safety classes: **auto-safe** =
   private/self-only changes (a private focus block); **gated** = anything that leaves your boundary or touches
   other people (a meeting invite to attendees, cancelling a meeting others are in, an RSVP on your behalf,
   sending mail later). This is the build order's narrative: the CLIENT milestone is the **unlock** for
   write-enabled spokes.

## Consequences

- **The knowledge + memory layer is orthogonal to ownership.** Every domain — mirror or own — pushes searchable
  text to the knowledge layer and extracts facts to memory, so the brain's *awareness* is identical regardless
  of who owns the operational record. Ownership governs only where the record lives + who may write it.
- **Bidirectional sync is a named, deferred future upgrade** — per-domain, demand-triggered. The connector
  framing (translate external→contract) supports adding it later without reworking the module.
- **The proposal/overlay pattern is reusable** — any domain can carry an Artemis-native overlay of
  pending/suggested state that promotes to the external system on approval, without conflicting with it.
- **Privacy/scope unchanged** — Calendar + email content is owner-private (M2 wall, encrypted scope); mirror
  read-caches live in the encrypted vault; email runs through `artemis.untrusted`.
- **Wave-1 build is cheap and low-risk** — no domain carries the conflict-resolution subsystem; the riskiest
  domain (Calendar) is handled by write-through + a non-conflicting native overlay.

## Alternatives considered

- **Pure mirror-only (global)** — *rejected*: undefined for Projects/Habits/Goals (no external system to
  mirror); would force dropping or rethinking the Artemis-native domains.
- **Pure own-with-bidirectional-sync (global)** — *rejected*: forces the hard conflict-resolution/echo-loop
  subsystem onto Calendar and Email, the domains where it is worst and least necessary; real data-loss risk;
  weeks of build; hard to reverse. The always-on hub removes the offline-editing need that would justify it.
- **Calendar = own** — *rejected*: a multi-party calendar (others write to it) cannot have Artemis as sole
  source of truth without round-tripping every external change through reconciliation — exactly the swamp #2
  avoids.
