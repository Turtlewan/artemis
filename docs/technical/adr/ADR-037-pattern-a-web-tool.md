# ADR-037 — Pattern-A web tool: concrete design (quarantined reader + clean-context reads)

- **Status:** **Accepted** — owner + planning, 2026-07-01.
- **Date:** 2026-07-01
- **Deciders:** owner + planning
- **Refines:** ADR-035 (reach-out capabilities) decision 3 (Pattern A) + decision 4 (Dual-LLM quarantine) + the model/role map. **Adopts:** ADR-009 (untrusted-content Dual-LLM posture). Does not re-decide the locked substrate.
- **Design basis:** live host probes 2026-07-01 (the `claude -p` clean-context pollution + fix, and the Haiku extraction behaviour).

## Context

R1 (`reachout-web-primitives`, shipped) gave the trusted host-side fetch foundation: SSRF-guarded `EgressPolicy`, `TavilySearch`, `TrafilaturaFetcher`. ADR-035 decision 3 defines **Pattern A** — "look this up and answer" — as a lightweight web tool with no tier stack, but leaves the concrete shape (who reads, who answers, escalation mechanism, the clean-context read mechanism) open. This ADR fixes those so R2 can be built against frozen decisions.

## Decision

| # | Decision | Statement |
|---|----------|-----------|
| 1 | **Deterministic orchestration (no LLM planner in Pattern A)** | The `WebTool` pipeline is plain Python: `search → fetch (top-N) → quarantined-read each → synthesize`. There is **no LLM orchestrator** (that is Pattern B/`AggregationPipeline`). The pipeline code is the "orchestrator that holds the plan and never sees raw content" — it passes raw pages **only** to the quarantined reader and passes **only validated extracts** to the synthesizer. |
| 2 | **Quarantined reader (ADR-009)** | Each fetched page is read by a reader model that is **given no tools, emits structured output only, and receives the page content spotlighted** (wrapped in explicit UNTRUSTED-CONTENT delimiters with a do-not-follow-instructions preamble). Reader output schema: `{ relevant: bool, extract: str, confidence: "low"|"medium"|"high" }`. The reader never influences control flow beyond returning this record. |
| 3 | **Reader = Haiku → Sonnet, full escalation** | First pass on **Haiku** (cheapest capable Claude tier). A single source escalates to **Sonnet** on **either** trigger: (a) **hard** — Haiku's response fails schema validation after one retry; (b) **soft** — Haiku returns `confidence: "low"` (or an empty `extract` for a non-trivial page). Only tripped sources escalate; Sonnet's result replaces Haiku's for that source. Soft escalation is acknowledged heuristic (a model grading its own work) — it catches self-aware failures, not silent ones. |
| 4 | **Synthesizer = Codex → Claude fallback** | The final answer is written by **Codex** (ChatGPT subscription; keeps the Max pool free), falling back to **Claude Sonnet-tier** (grounded synthesis over a handful of extracts does not need Opus-tier — right-sized per the ai-systems review; Opus reserved for a raised quality bar), operating on `{query + [spotlighted extracts with source URLs]}` — never raw pages. Output is **structured** (`{answer, cited_urls}`); the tool surfaces only the sources the synthesizer actually cited (∩ fetched), so citations are not overstated. |
| 5 | **Clean-context subscription reads** | The Claude-CLI reader MUST run hook- and CLAUDE.md-free or it returns polluted output (proven live: Haiku prepended an APEX status banner). **`--bare` is rejected** — it forces `ANTHROPIC_API_KEY` auth and skips keychain reads, breaking subscription-only OAuth. **Mechanism (proven live):** invoke `claude -p` with `CLAUDE_CONFIG_DIR` pointed at a **sanitized config dir** containing only a fresh copy of `~/.claude/.credentials.json` (no `CLAUDE.md`, no `settings.json` hooks), plus `--exclude-dynamic-system-prompt-sections`. OAuth (file-based creds) is preserved; CLAUDE.md + hooks are gone. |
| 6 | **Partial-fetch = synthesize-on-partial** | If some sources fail (egress-denied, fetch-degraded-to-empty, reader unusable), the pipeline synthesizes from whatever `relevant` extracts remain and appends a **coverage note** (e.g. "based on N of M sources"). It aborts only if **zero** usable extracts remain. |
| 7 | **Model access via injected seams** | `WebTool` takes an injected reader and synthesizer (ModelPort-shaped callables), wired at the composition root to the concrete Claude-CLI / Codex providers. This keeps the pipeline hermetically testable (mock reader/synth) and the model identities swappable. |

**Defaults:** top-N = **5** sources (configurable); reader/synth calls bounded by the providers' own timeouts.

## Consequences

- **Two specs (file-disjoint, one build session):**
  1. `reachout-clean-context-provider` — harden `ClaudeCodeProvider` + `cli_support.run_cli` (env passthrough) for the sanitized-`CLAUDE_CONFIG_DIR` invocation (decision 5). Model-layer; independently live-smokeable. **Also unblocks Pattern-B's pull tier.**
  2. `reachout-web-tool` — the `WebTool` pipeline (decisions 1–4, 6, 7) on the R1 primitives, hermetic-tested then live-smoked end-to-end (depends on #1 for the live leg).
- **The quarantined reader is inlined in `web_tool.py` for now** (single consumer). When Pattern-B (`AggregationPipeline`, ADR-035 #4) lands and needs the same reader, that spec extracts it into a shared module — not built speculatively now (simplicity-first).
- **Quota contention** (reader shares the Claude pool with the build host) remains **parked** to ADR-035's semaphore/build-idle-gate item — R2 does not implement it; live-smoke is run when the host is idle.
- **Credentials staleness:** the sanitized config dir must re-copy `.credentials.json` when the source changes (OAuth token refresh), or reads fail after a refresh — handled in spec #1.

## Alternatives considered

- **`--bare` for clean context** — *rejected* (forces API-key auth + skips keychain → breaks subscription OAuth).
- **LLM orchestrator in Pattern A** — *rejected* (ADR-035: Pattern A is a thin tool, no tier stack; deterministic Python suffices).
- **Separately-reusable reader module now** — *rejected for R2* (speculative; single consumer until Pattern B — extract then).
- **Synthesizer sees raw pages** — *rejected* (ADR-009 injection rule: only the quarantined reader touches raw content).
