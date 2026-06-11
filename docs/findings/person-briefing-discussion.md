# Design discussion: Person Briefing (relationship / personal-CRM cluster)

**Date:** 2026-06-11
**Type:** functional design discussion — NOT a spec, NOT an ADR (per owner's "discuss the functions, don't create specs" preference). Captured so the thinking survives; revisit when the relationship layer / Comms spoke is designed.
**Origin:** drained from BACKLOG.md — the "relationship/personal-CRM cluster" (relationship-decay · person↔debt · unlinked-mention · news-on-contact). Owner chose to discuss the cluster; the discussion converged the **core** onto one bounded feature, with the rest as opt-in extras.

## The itch (owner's words)
"Never get caught off-guard when I am meeting someone — but it does not need to be that crazy unless I spec it to be."

→ The spine is a **pre-meeting briefing**, deliberately **bounded** (the proactive/wilder facets are opt-in, not core). Note: this is the one feature where the owner explicitly put a *ceiling* on scope rather than choosing the fullest end-state — the sensible-default is the target here.

## The converged core — "Person Briefing"
On-demand, you ask *"brief me on Dave"* → Artemis returns a short, **non-obvious** brief.

| Decision | Choice | Why |
|----------|--------|-----|
| **Trigger / proactivity** | **On-demand only** — you pull it, it never pushes | Quietest; inside the "not crazy" ceiling. (Owner accepted the trade-off that he must remember to ask.) |
| **Content** | **Open threads & promises** + **stored facts** only — *skip* identity + chronological history | Sharp owner call: don't tell me what I already know (who they are, that we talked); tell me what I'd *drop* — unresolved threads + human details. Fits the lean profile / "context-stinginess". |
| **Open-threads engine** | **Both** — auto-detect from recent comms *at ask-time* (shown as **dismissable suggestions**) + manual logging | Auto finds the value; suggestions-not-assertions means it never confidently lies; manual = control. Auto runs only when asked → stays passive. |

**One-line:** *"remind me what's hanging between us, and the human details I'd lose — only when I ask."*

## Parked opt-in extras (off by default — the owner's "unless I spec it" switches)
- **Auto-brief before scheduled meetings** — the safety net for forgetting to ask (Calendar-triggered). The first toggle most worth offering, since on-demand-only's weakness is exactly "you forget to ask."
- **Add identity / history** to the brief (for people he *doesn't* already know cold).
- **Person↔debt** tracking ("you owe Dave $50 / Dave owes you") — needs Finance.
- **Reconnection nudges** ("haven't talked to X in a while") — proactive; needs a Comms spoke (contact-frequency).
- **News-on-contact** (public update/job-change before a meeting) — needs a News spoke.
- **Unlinked-mention detection** (a name in an email/note without a link → suggested connection) — needs Notes/Journal.

## Dependencies / reuse
Mostly reuses locked subsystems — the only genuinely new work is the **on-demand thread-extraction**:
- **M4 memory** — Person entity + `person_fact_key` (ADR-013); semantic facts (decay-ranked) supply the "stored facts"; entity resolution (`memory.resolve_entity`) handles "*which* Dave."
- **Gmail (read)** — source for auto-detected open threads; runs through **`artemis.untrusted`** (email is the canonical injection vector — DR-a quarantine applies to the extraction).
- **Calendar** — only for the opt-in auto-brief-before-meetings toggle.
- The extras reach into spokes not yet designed (Finance / Comms / News / Notes) — discussing this now helps shape what those owe a relationship layer.

## Status / next step
Discussed + converged; **not specced** (owner preference). When the relationship layer or Comms spoke is taken up, this is the core feature to build first; the parked extras layer on around it. No ADR yet — revisit if/when locked.
