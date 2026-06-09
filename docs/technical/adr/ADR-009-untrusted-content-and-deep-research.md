# ADR-009 — Untrusted-content security layer + the Deep-Research engine

- **Status:** Accepted
- **Date:** 2026-06-08
- **Deciders:** owner + planning
- **Relates:** brain.md §Security (Dual-LLM/CaMeL, spotlighting), §Self-improvement (Curiosity Loop), §Cloud/privacy policy; M7-c (defines the `Researcher` port + grounding gate + token caps this engine plugs into); ADR-008 (observability — the layer that *observes* the security envelope).

## Context

The Curiosity Loop (M7-c) needs a concrete `Researcher` that fills a knowledge gap from the open web.
M7-c ships only a stub behind the `Researcher` port + the grounding gate (≥2 independent reachable
external sources, never self-generated) + hard token caps. The real engine reads the **untrusted web**,
so brain.md's rule governs: *"assume the LLM WILL be injected"* — enforce in deterministic code OUTSIDE
the model, via Dual-LLM/CaMeL + spotlighting. brain.md also states this is not research-specific: *"All
ingested content = untrusted data."* And it parks *"CaMeL Q-LLM feasibility on local models"* as an open
build-time question.

## Decision

1. **A reusable untrusted-content security layer (DR-a), not research-specific.** Spotlighting + a
   dual-LLM quarantine primitive live in a standalone `artemis.untrusted` module. The Deep-Research engine
   is its **first consumer**; M3 ingestion and connectors reuse it later. Shaped for the first consumer now
   — not speculatively generalised (the OBS lesson).

2. **Pragmatic dual-LLM, not the full CaMeL data-plane (yet).** A **Quarantined-LLM** reads raw untrusted
   content with **no tools** and emits only a **schema-validated structured extract**; a **Privileged-LLM**
   orchestrates + holds the tools and **never sees raw content** — only the extracts. Spotlighting wraps all
   untrusted content. This gets most of CaMeL's protection (the model that saw the poison cannot reach a
   tool) without per-value capability/provenance tracking. The full capability data-plane is a **clean
   additive upgrade**, triggered by what OBS observes (injection attempts/anomalies) or by the parked
   local-Q-LLM-feasibility spike resolving. Rejected: single-LLM-with-spotlighting (brain.md forbids
   reader == actor); full-CaMeL-now (research-grade complexity, parked feasibility).

3. **Iterative multi-step engine (DR-c), bounded.** search → fetch → quarantined-extract → sufficiency-judge
   → loop or synthesise, hard-bounded by M7-c's `token_cap` **and** a max-iteration stop (whichever first →
   synthesise with what's gathered). Implements `artemis.curiosity.research.Researcher`; returns a
   `ResearchResult` whose sources let M7-c's grounding gate pass/reject. Never fabricates: no external
   sources gathered → return an empty-source result that fails the gate, never a self-generated answer.

4. **Two research modes (profiles), reader always local.** **Standard** (orchestrator = DeepSeek,
   non-sensitive cloud; the idle Curiosity Loop's default; cheaper, more compensating iterations,
   prompt-caching + structured extraction + a build-time tuning spike) and **Deep** (orchestrator = Claude
   teacher; owner-invoked). The **Quarantined reader is a local model in both modes** (default Qwen3-4B,
   swappable via the `ModelPort` role seam) so the high-volume untrusted-read step is cheap + private.
   Mode is set at construction → **no change to M7-c's ready `research(query, token_cap)` contract**.
   *Escalation deferral:* auto-escalating a high-value recurring gap to Deep needs a hint passed into
   `research()` → a small M7-c follow-up; v1 = idle loop runs Standard, Deep is owner-invoked.

5. **Web access (DR-b) behind ports, under controlled egress.** `SearchProvider` (default **Brave** — ZDR,
   independent index, cheapest metered; fallback **Tavily** — agentic, free tier, own injection defense) +
   `Fetcher` (default local **trafilatura** — clean text on-box, zero token waste; **Jina Reader** /
   **Playwright MCP** as port upgrades). All outbound calls pass a **controlled-egress allowlist** (search
   host + fetched domains only), logged via OBS; everything else default-deny. The code-exec sandbox stays
   fully egress-blocked — this network access lives in the trusted fetch component, not in sandboxed code.
   (Google CSE / Bing Web Search are dead as of 2025–27 — see docs/research/2026-06-08-search-providers.md.)

6. **Non-sensitive only; raw pages never persisted.** The research query is non-sensitive (M7-c enforces
   instance-free, owner-telemetry-derived queries); the provenance gate bars sensitive data from this path.
   Raw fetched pages are held in memory for the cycle and discarded after extraction — leaner and no
   untrusted content at rest.

## Consequences

- Three specs: **DR-a** (`artemis.untrusted`: spotlight + quarantine — shared), **DR-b** (`artemis.research`:
  search + fetch + egress), **DR-c** (`artemis.research.engine`: `DeepResearcher` + modes + the loop).
  DR-a + DR-b are independent foundations (parallel-buildable); DR-c consumes both + M7-c.
- New logical model roles in `config/roles.toml` (additive): a local `research_reader` (Qwen3-4B) and a
  `research_orchestrator` mapping by mode (Claude teacher / DeepSeek). New env secrets: `BRAVE_API_KEY`,
  `TAVILY_API_KEY`, optional `JINA_API_KEY` (from Keychain/env, never committed).
- New deps: `trafilatura` (+ `httpx`, already present). Jina/Playwright are optional adapters.
- The full CaMeL data-plane, chunk-level reuse by M3/connectors, and the recurrence-auto-escalate M7-c hint
  are documented follow-ups — not built here.
