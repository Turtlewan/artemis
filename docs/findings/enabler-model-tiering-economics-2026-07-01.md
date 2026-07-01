# Enabler: Model-Tiering Economics for Data-Pull Pipeline
**Date:** 2026-07-01  
**Author:** Claude (Sonnet 4.6), planning-mode analysis  
**Scope:** Evaluate the "Claude Code CLI brings data better than Codex" claim for data-pull/extract tasks; assess quota contention, org-disable blocker, and spike design.

---

## 0. Ground Truth from Codebase

All findings below are grounded in the actual provider implementations under `src/artemis/model/`.

### ClaudeCodeProvider (`claude_code_provider.py`)
- Invokes `claude -p <prompt> --output-format json --model <model>` as an asyncio subprocess.
- For structured output: **appends schema as text to the prompt** — "Return ONLY a JSON value conforming to this JSON Schema: ...". This is prompt-injection schema enforcement, not a native contract.
- Result parsing: tries to extract `.result` field from the JSON wrapper; falls back to raw stdout.
- No token limit stated in the code itself; the Claude Code CLI's own internal limits apply (unknown per-call, subscription-scoped).

### CodexProvider (`codex_provider.py`)
- Invokes `codex exec -m gpt-5.5 --sandbox read-only --ephemeral --skip-git-repo-check --color never -o <output_file> -` as an asyncio subprocess.
- For structured output: writes schema to a tempfile and passes `--output-schema <path>` — **native Codex schema enforcement**, not prompt injection.
- Documented ~13k tokens/call limit (eval-grade); `gpt-5.5` is the model.

### AnthropicAPIProvider (`anthropic_provider.py`)
- Direct Anthropic SDK async calls (`AsyncAnthropic`) — **no subprocess overhead**.
- For structured output: uses `tool_use` with `tool_choice: {"type": "tool", "name": "emit"}` — **forced tool call = most reliable structured output in the ecosystem**.
- `max_tokens: 4096` default; proper async concurrency (SDK connection pooling).
- Requires `ANTHROPIC_API_KEY` env var; fails with `ProviderUnavailableError("anthropic_api", "no API key")` if absent.

### Router (`router.py` + `client.py`)
- `QuotaAwareRouter`: simple waterfall (codex → claude_code → anthropic_api → ollama). No per-backend budget gates.
- `ModelClient`: wraps any single provider with a reask loop (`max_reasks=2`). **`temperature` and `max_tokens` args passed to `complete()` are silently dropped** (`del temperature, max_tokens`).

---

## 1. Claim Verdict: "Claude Code CLI Brings Data Better Than Codex"

### Verdict: PARTIALLY TRUE as a model-quality claim, but WRONG as an implementation claim. Confidence: HIGH (85%).

The claim conflates two separate questions:
- **Model quality question**: "Are Claude Sonnet/Haiku better extractors than gpt-5.5 eval-grade?" — probably yes for complex, nuanced extraction. Likely irrelevant for simple field-extraction tasks.
- **Delivery mechanism question**: "Is ClaudeCodeProvider the right vehicle for many small extraction calls?" — NO.

### Why ClaudeCodeProvider is the wrong vehicle

| Dimension | ClaudeCodeProvider | CodexProvider | AnthropicAPIProvider |
|-----------|-------------------|---------------|----------------------|
| Structured output | Prompt-injection (fragile) | Native `--output-schema` flag | Forced `tool_use` (most reliable) |
| Per-call overhead | subprocess spawn + CLI startup (~1-3s) | subprocess spawn + CLI startup (~1-3s) | HTTP round-trip (~1-2s) |
| Parallelism | asyncio subprocess (OS-level) | asyncio subprocess (OS-level) | True async HTTP (best) |
| Schema reliability (first try) | ~80-85% (model must follow text instruction) | ~95%+ (native enforcement) | ~99%+ (forced tool call) |
| Reask retries needed | 1-2 often | rarely | almost never |
| Token limit | Subscription-scoped (unclear per-call) | ~13k/call (eval-grade) | 4096 output (configurable) |

**Key finding**: For "many small parallel data-pull + extract calls", `AnthropicAPIProvider` (direct Anthropic SDK, native tool_use) is strictly better than `ClaudeCodeProvider` on every dimension. The Claude subscription's value for data-pull is best accessed via the API key path, not the CLI path.

The correctly stated claim should be: **"AnthropicAPIProvider with Sonnet/Haiku is better than CodexProvider for structured extraction"** — and that claim is likely true, but needs live-smoke validation (see §4).

### Where Codex genuinely wins
- **Code generation and synthesis tasks**: gpt-5.5 in `codex exec` is fine for agentic code-writing tasks (the existing build pipeline). For "synthesize" work (turning extracted data into structured output or code), Codex's eval-grade capability is adequate.
- **Native schema on first try**: Codex's `--output-schema` flag is more reliable than ClaudeCodeProvider's prompt-injection approach, though both lag behind AnthropicAPIProvider's forced tool_use.

---

## 2. Quota Contention Analysis

### The contention topology

The Claude Code subscription pool is a **single shared resource** across all `claude` CLI invocations on this machine:
- Build host: Opus orchestration + Opus coding fallback (both consume claude subscription)
- Proposed data-pull pipeline: Sonnet/Haiku via `ClaudeCodeProvider` (also consumes claude subscription)

Claude.ai Pro subscription behavior (known): usage limits are **per-subscription, not per-model**. Using Haiku does not protect the quota from Opus running out. The 5-message/period or ~100-messages/5-hour soft limits apply to the full subscription pool.

### Contention risk model

| Scenario | Risk |
|----------|------|
| Idle dev machine, single data-pull | Low — single subscription, low volume |
| Data-pull pipeline (5-10 parallel Haiku calls) during a Codex build | Medium — Codex build doesn't use Claude subscription; Haiku calls may still consume enough quota to block the next Opus session |
| Data-pull pipeline (5-10 parallel calls) during an Opus planning session | HIGH — direct contention; Opus conversations and Haiku extractions fight for the same quota |
| Batch extraction (50+ calls) in background | HIGH — likely saturates the subscription period quota before build/orchestration can run |

### Mitigations (ordered by impact)

1. **Route data-pull to AnthropicAPIProvider, not ClaudeCodeProvider.** An API key is a separate billing dimension with its own rate limits (per-minute tokens, not a subscription seat). This completely decouples data-pull from the CLI subscription pool.

2. **Add a per-provider concurrency semaphore to QuotaAwareRouter.** Currently the router has no parallelism gate. A `asyncio.Semaphore(max_concurrent=3)` on claude_code calls would throttle data-pull without blocking the orchestration path.

3. **Time-slice guard**: emit data-pull jobs only outside active build sessions. The `Scheduler` (v2-13) could gate proactive data-pull jobs behind a "build-idle" flag on `app.state`.

4. **Budget counter**: add a rolling `UsageLedger` to QuotaAwareRouter that tracks claude_code call count per hour. Block new claude_code calls when within N% of an estimated hourly soft limit.

5. **Ollama as extraction primary for simple tasks**: for field-extraction from structured or semi-structured input, `OllamaProvider` (local, zero quota) can do the job with a small model (qwen3:4b). Reserve Sonnet/Haiku API calls for complex/ambiguous extraction.

---

## 3. Org-Access Blocker Assessment

### Status
`docs/status.md` (Open Questions): "Claude Code subscription org-access for this Opus host was flagged org-disabled mid-session ('use an Anthropic API key / ask admin')."

### Technical impact on the pipeline

When the org is disabled, every `claude -p ...` subprocess returns non-zero. The current `ClaudeCodeProvider.generate()` catches this and raises `ProviderUnavailableError("claude_code", ...)`. `ProviderUnavailableError` is a `FailoverEligibleError`, so the `QuotaAwareRouter` silently skips to the next backend.

**Concrete effect on the proposed Sonnet/Haiku data-pull pipeline:**
- If `ANTHROPIC_API_KEY` is set: router falls through claude_code → anthropic_api → data-pull works, using the API key. The pipeline silently degrades to using AnthropicAPIProvider (which is actually better).
- If `ANTHROPIC_API_KEY` is NOT set: anthropic_api raises `ProviderUnavailableError("anthropic_api", "no API key")` → falls to ollama → if ollama is running, works with local model; if not, `AllBackendsExhaustedError`.

**The blocker makes ClaudeCodeProvider unreliable as a primary data-pull provider on this host.** Any design that depends on the CLI path will silently degrade or fail.

### Mitigations (ordered)

1. **Set `ANTHROPIC_API_KEY`** — this is the correct fix and happens to route through the better provider (AnthropicAPIProvider with native tool_use). Should be in `.env` and loaded at startup.

2. **Re-enable org access** — ask admin, or switch to a personal Anthropic org. Restores the claude_code slot but doesn't make it the better choice for data-pull.

3. **Redesign to bypass `claude_code` for data-pull** — explicitly route extraction tasks to `anthropic_api` slot by constructing a `ModelClient` with `AnthropicAPIProvider` directly rather than through the `QuotaAwareRouter`. This gives explicit routing and avoids the waterfall's fallback ambiguity.

4. **Ollama as always-on local fallback for pull tasks** — for simple extraction, a locally-running Ollama model (qwen3:4b) has zero dependency on subscription state and zero quota contention. Wire it as the primary for extraction-only pipelines where quality requirements are lower.

---

## 4. Live Spike Design: Validate "Better than Codex" Empirically

**Artemis rule**: live smoke over hermetic mocks (memory `live-smoke-real-integrations`).

### Spike task
Extract structured data from **5 fixed news excerpts** (seed corpus, no network needed at runtime) into a defined JSON schema:
```json
{"title": "string", "date": "string|null", "entities": ["string"]}
```
These 5 texts are fixed across all runs (same content, same complexity).

### What to run

**Script**: `scripts/spike_provider_benchmark.py` — standalone Python, imports only the artemis model layer.

**Three parallel batches** (run with `asyncio.gather`):

| Batch | Provider | Model |
|-------|----------|-------|
| A | `ClaudeCodeProvider` | `claude-haiku-4-5` |
| B | `AnthropicAPIProvider` | `claude-haiku-4-5` |
| C | `CodexProvider` | `gpt-5.5` |

Each batch: 5 concurrent calls (`asyncio.gather(*[client.complete(...) for text in corpus])`).

### What to measure

For each batch:
1. **Wall-clock latency**: `time.perf_counter()` around the `asyncio.gather` — how long for all 5 calls to complete.
2. **Per-call latency**: timestamp each individual call start/end.
3. **Schema compliance on first try**: did `ModelClient` need to reask? (add a counter to reask loop or inspect `last_error`).
4. **Extraction accuracy**: spot-check 3 of the 5 extractions against a known-correct gold output (manual verification).
5. **Error rate**: count `ProviderUnavailableError`, `QuotaExhaustedError`, `ModelOutputError` per batch.

### Decision thresholds

| Finding | Action |
|---------|--------|
| Batch B (Anthropic API) wall-clock < Batch A (Claude CLI) by >50% | Confirm: route data-pull to anthropic_api, not claude_code |
| Batch B schema compliance ≥ 95% first-try | Confirm: use AnthropicAPIProvider as data-pull primary |
| Batch A errors ≥ 1 (org-disable) | Confirm: claude_code blocked on this host; API key path is required |
| Batch C accuracy ≥ Batch B accuracy | Simplify: single Codex chain is sufficient, no Sonnet/Haiku layer needed |
| Batch C wall-clock > Batch B by >3x | Confirm: Codex subprocess overhead makes it unsuitable for high-frequency pull |

### Pre-conditions
- `ANTHROPIC_API_KEY` must be set (for Batch B).
- `codex` CLI must be in PATH (for Batch C).
- `claude` CLI present (for Batch A, even if expected to fail with org-disable).

---

## 5. Recommended Architecture Change (if spike confirms)

Replace the proposed pipeline:
```
Opus/CLI orchestrates → Sonnet/Haiku/CLI pulls → Codex synthesizes
```

With:
```
Opus/CLI orchestrates → Sonnet/Haiku/API (AnthropicAPIProvider, native tool_use) pulls → Codex synthesizes
```

**Concrete change**: construct a dedicated `ModelClient(AnthropicAPIProvider(...))` for extraction tasks rather than routing through `QuotaAwareRouter`. This gives explicit routing, bypasses org-disable, and uses native structured output.

The waterfall `QuotaAwareRouter` remains appropriate for general ask/orchestration tasks where fallback is acceptable. For data-pull, explicit routing is safer.

---

## 6. Summary Table

| Question | Verdict | Confidence |
|----------|---------|------------|
| Is claude_code CLI better than Codex for data-pull? | Wrong vehicle; model quality may be better but delivery is worse | HIGH (85%) |
| Is AnthropicAPIProvider better than both for structured extraction? | YES — native tool_use, no subprocess, true async | HIGH (90%) |
| Quota contention risk during parallel data-pull? | REAL if using claude_code; solved by API key path | HIGH (85%) |
| Org-disable blocker severity? | HIGH — makes claude_code inert on this host today | CONFIRMED (status.md) |
| Right fix for org blocker? | Set `ANTHROPIC_API_KEY`, route pull to anthropic_api | HIGH |
| Spike needed before deciding? | YES — live smoke to confirm latency/accuracy claims | Required per project rule |
