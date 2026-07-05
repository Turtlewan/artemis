# ADR-047 — True agent loop for the ask path + build orchestration + domain-first map

- **Status:** **Accepted** — owner + planning discussion, 2026-07-03 (session 9, same discussion
  as ADR-046).
- **Date:** 2026-07-03
- **Deciders:** owner
- **Refines:** ADR-046 (local-first doctrine — the enabler: agent steps are cheap when they're
  local reads), ADR-039 (invoke/reuse — the one-shot match-first pipe becomes one tool among
  many), ADR-045 (map nodes — node identity revised: domains primary), ADR-012
  (confirm-on-expensive — unchanged), memory `agency-proactivity-scope-locked` (gates unchanged).
- **Research inputs:** HERMES + Odysseus fit memos,
  `docs/findings/{hermes,odysseus}-agent-fit-2026-07-03.md`. Both projects' top anti-pattern is
  identical — no real isolation. Artemis's sandbox + quarantine is the category advantage; it is
  explicitly NOT relaxed by anything below.

## Context

The ask path today is a router, not an agent: intent classify → exactly one of four fixed pipes
(build / web / one-capability invoke / plain answer). One step per ask; the owner is the chain.
Multi-step questions ("do I have time for lunch with Ben Friday?") need calendar + tasks +
reasoning in one ask. ADR-046 makes agent steps affordable (~ms local reads instead of 15s cloud
fetches). Separately: builds are strictly sequential and hold the owner hostage in the Ask popup.

## Decision

| # | Decision | Statement |
|---|----------|-----------|
| 1 | **Ask path = true agent loop** | The assistant chains tool steps (local store queries, capability invokes, memory) until the request is answered — not one matched thing per ask. |
| 2 | **Free vs gated steps** | Local reads chain freely, no per-step confirm. Side-effects and external actions keep their existing gates (agency scope, ADR-012 confirm-on-expensive). Web reads mid-loop follow existing precedent (quarantined; confirm only expensive aggregation). |
| 3 | **Fast driver, escalate on stall** | A haiku-class model drives the loop; escalation up the QuotaAwareRouter only when it stalls (Odysseus escalate-then-distill). |
| 4 | **Stop discipline** | Step budget + tiered failure detection (cheap regex checks before LLM judging) + verify-on-stop (a "done" claim requires evidence of what actually ran — HERMES evidence-ledger pattern). |
| 5 | **RAG tool selection** | Only relevant capabilities/tools enter the loop's context per ask (with an always-available floor) — the library scales past what fits in a prompt. |
| 6 | **Distill improvised successes** | When the loop improvises a multi-step success, offer to distill it into a permanent capability (the assistant's wins feed the library). |
| 7 | **Loop visibility = live step trace (owner: option B)** | The client shows a slim updating trace ("checking calendar → checking tasks → …") while the loop works. Animation/polish deferred. Doubles as the dogfood-era debugging window. |
| 8 | **One loop, two entrances** | The ask loop and the Spine's proactive plan→act→verify unify into one agent loop entered by chat asks and scheduled jobs (builder's call, no owner objection). |
| 9 | **Builds go fleet + decomposed (owner: parallelism 1+3)** | Builds become background scheduler-hosted jobs — many at once, owner never held in the popup; results re-enter as a NEW self-contained turn (HERMES pattern). Big requests decompose into parts built concurrently and composed via `uses`. Racing candidates (best-of-N) NOT chosen. An interactive quiet gate defers background work while the owner is actively chatting (Odysseus). |
| 10 | **Map = domain nodes with capability satellites (revises ADR-045 #1)** | Primary nodes are DOMAINS (Calendar, Recipes, Spending — the data the owner owns, per ADR-046), carrying freshness + pending badges. Capabilities render as smaller satellite nodes around their domain (zoom-LOD reveals them). A domain node is born when a new domain first gets data; a build-in-progress shows a construction-site node. |

## Amendment — 2026-07-04 (owner): loop model roles resolved

Decision #3/#4 model tiers were left open at acceptance; owner resolved them 2026-07-04
(all are ADR-049 registry roles — starting defaults, owner-toggleable):

- **Driver = Sonnet** (not haiku-class as #3 sketched); grunt-work calls
  (classify/extract/phrase) = **Haiku**.
- **Escalation = cross-family, Sonnet → Codex (`gpt-5.5`)** on stall — taps the second
  subscription's quota + a genuinely different model; the handoff crosses the provider
  boundary (state summary + schema down-conversion in the RawProvider, per architecture §2).
- **Verify-on-stop judge = independent no-tools Haiku** (evaluator-independence; quarantine
  seat — judge reads untrusted content, so tool-stripped).

## Consequences

- The intent router shrinks to a thin front-door (or dissolves into the loop's first step);
  the four fixed pipes become tools the loop can pick.
- Capability metadata grows selector-facing fields over time (`when_to_use`, runtime
  `confidence` — Odysseus schema) to sharpen tool selection and eventually relax confirm gates.
- CB-5b draft specs (cb5b-2/3/4) need revision before build: node identity changed to
  domain-primary (this ADR #10).
- Build-mode UX moves from a synchronous Ask-thread flow to background jobs + new-turn re-entry +
  construction-site nodes; the current AskPopup build state-machine becomes the fallback/inner
  view.
- NOT copied from the research: HERMES in-process skill loading; Odysseus no-sandbox execution.
  The WSL2 isolate + dual-LLM quarantine remain load-bearing.
- Memory: `ask-path-true-agent-loop`, `local-first-data-doctrine`.
