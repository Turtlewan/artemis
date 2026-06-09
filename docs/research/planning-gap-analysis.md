# Research: Artemis Planning Gap Analysis
**Date:** 2026-06-09
**Confidence:** HIGH — internal audit of project docs (no web). Synthesis-level capture of an internal analyst-agent run (2026-06-09).

> Reframe: the project deliberately **front-loads specs and defers build** until the Mac arrives, so
> "not built yet" is NOT a gap. This audit looks only for *planning/spec* work still owed.

## Summary
Planning is **healthy**: all ADRs (001–012) are Accepted, no spec carries an unresolved
`[NEEDS CLARIFICATION]`, and the ~56 ready specs hold up. The real gaps are two **owed bring-up
artifacts with a real-world deadline** (the day the Mini arrives) and a handful of **safely-deferrable**
items. Top 3 gaps: `BRING-UP-RUNBOOK.md`, `SECRETS-INVENTORY.md`, ADR-001 §Deployment finalisation.

## Planning backlog
| Gap | Category | Blocking? | Effort | Depends on | Notes |
|---|---|---|---|---|---|
| `BRING-UP-RUNBOOK.md` | owed artifact | **prep-blocking** | S | PRE-ARRIVAL-PREP, M0-a..e, ADR-002, deploy.sh | Ordered power-on → green `/healthz` + voice ack. All source material exists. |
| `SECRETS-INVENTORY.md` | owed artifact | **prep-blocking** | S | PRE-ARRIVAL-PREP §A | Consolidate every secret → Keychain slot + consuming spec. Feeds the runbook. |
| ADR-001 §Deployment finalise | external/waiting | resolved-now | XS | WWDC (done) + hardware fork | One-paragraph amendment once 48/64 chosen. |
| Second-spoke-wave selection | deferrable to build | no | M/spoke | M0–M7 running | 11 future spokes named in overview.md; just-in-time by design. Decision = *which next*, not urgent. |
| E2E / UAT / eval-rubric strategy | deferrable to build | no | S | first build session | Per-task acceptance exists; no holistic doc / A.U.D.N. accuracy rubric / voice-latency budget yet. BACKLOG has RAGAS/DeepEval ideas. |

## Top priorities (plan-next order)
1. **`BRING-UP-RUNBOOK.md`** — the only artifact with a real deadline; everything needed exists.
2. **`SECRETS-INVENTORY.md`** — pairs with the runbook.
3. **ADR-001 §Deployment** — finalise once the hardware fork is decided.
4. (Optional) pick + design the next spoke, or write the E2E/eval-strategy doc.

## Genuinely DONE / safely deferred (do not re-open)
- All ADRs Accepted (001–012); GATE/ADR-012 staging resolved; module-layout resolved; M8-b2 pre-flight resolved; capture-recipe graduation resolved.
- First spoke wave (Gmail/Calendar/Productivity) COMPLETE, 0 parked.
- GATE-b/CLIENT-e additive edits + `pre_tick_steps` composition = **build-time** integration checks, not planning gaps.
- Second-spoke-wave + E2E strategy are *intentionally* deferred — not omissions.

## Sources (docs read)
- docs/status.md, ROADMAP.md, REQUIREMENTS.md, overview.md, data-model.md, brain.md
- docs/technical/modules/*.md, docs/technical/adr/ADR-001..012
- docs/changes/*.md (titles/identities), latest docs/handoff/*.md, BACKLOG.md, PRE-ARRIVAL-PREP.md
