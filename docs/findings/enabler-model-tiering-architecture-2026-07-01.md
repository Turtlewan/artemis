# Model-Tiered Aggregation Pipeline — Architecture Findings
_Date: 2026-07-01_

## 1. Codebase Ground Truth

### QuotaAwareRouter (`src/artemis/model/router.py`)

Selection logic is **purely sequential failover**:

```python
for name, backend in self._backends:
    try:
        return await backend.complete(...)
    except FailoverEligibleError:
        continue
raise AllBackendsExhaustedError(failures)
```

The chain (hardwired in `src/artemis/model/compose.py`):

| Position | Name | Default model |
|---|---|---|
| 1 | codex | gpt-5.5 |
| 2 | claude_code | sonnet |
| 3 | anthropic_api | claude-sonnet-4-6 |
| 4 | ollama | qwen3:4b |

The `model: str | None` parameter is passed through; each backend uses its `model_default` when
`None`. There is **no role concept** — only quota/availability drives which backend wins.

`FailoverEligibleError` covers two cases: `QuotaExhaustedError` and `ProviderUnavailableError`.
These are the only trigger conditions for failover.

### Spine (`src/artemis/spine/spine.py`)

```python
class Spine:
    def __init__(self, model: ModelPort, ...)
    async def run(self, task: Task, ...) -> RunResult:
        # plan step  → self._model.complete(..., response_schema=PLAN_SCHEMA)
        # act step   → self._model.complete(...)
        # verify     → acceptance(out)  # in-process callable
```

One `ModelPort` injected; the same instance handles BOTH planning and acting. No multi-model or
per-phase routing exists.

The Spine is wired in `src/artemis/proactivity/worker.py`:
`ProactiveWorker → Spine(model=router) → QuotaAwareRouter`.

### Capability / Sandbox System

`src/artemis/capabilities/forge.py` is the critical file.

The forge explicitly marks network capabilities as BLOCKED until a WSL2 sandbox exists:

```python
# forge.py, line 56-58
UNSAFE_IMPORTS: frozenset[str] = frozenset({
    "socket", "ssl", "http", "urllib", "requests", "httpx", "aiohttp", ...
})
```

```python
# forge.py, line 111-116
if found:
    return (
        f"capability imports network/process modules ({names}); "
        "blocked until the isolated WSL2 sandbox exists"
    )
```

`SubprocessSandbox` in `src/artemis/capabilities/sandbox.py` runs pytest in a subprocess — it is
the **interim** sandbox (no network isolation). The WSL2 runner is referenced in docstrings but not
implemented.

`SkillDraft` (in `src/artemis/types.py`) currently has: `name`, `description`, `body`,
`tool_script`, `uses`, `secrets`, `tests`. **No pipeline/tier declaration field exists.**

---

## 2. Sandbox/Host Boundary Decision: Option B Recommended

### Option A — Sandbox calls models itself

The sandboxed capability runs all three tiers internally. It needs:
- Model credentials (ANTHROPIC_API_KEY, Codex binary accessible) inside the untrusted container
- Network egress to both the target data sources AND the model endpoints
- Its own quota management and failover logic

**Why A is wrong here:**
- Security anti-pattern: model credentials inside untrusted code. The forge already blocks
  network capabilities because untrusted code + arbitrary egress = dangerous. Adding model
  credential scope makes it worse.
- Capability code could exfiltrate API keys via the same egress it uses for data fetching.
- Every aggregation capability would re-implement quota management and failover, defeating the
  purpose of the central QuotaAwareRouter.
- Violates the WSL2 sandbox's trust model: the sandbox is meant to be containment, not a
  full agent runtime.

### Option B — Sandbox is a dumb fetch pipe; host runs tiering

The sandbox's only job: fetch raw data from egress-allowlisted sources and return it as bytes/text
to the host. The host's router runs Opus/Sonnet-Haiku/Codex tiering entirely outside the sandbox.

**Why B is correct:**
1. **Security alignment**: model credentials stay on the host. The sandbox boundary is: raw HTTP
   in, raw bytes out. Nothing else crosses the wall.
2. **Existing precedent**: `SubprocessSandbox.run_tests()` already works this way — subprocess
   executes a constrained task, host inspects structured results. The WSL2 sandbox is the same
   pattern at a higher isolation level.
3. **Centralized routing**: the existing `QuotaAwareRouter` + all three tier `ModelPort`s live
   on the host. Quota management, failover, and cost telemetry remain in one place.
4. **Capability simplicity**: the capability's `tool.py` becomes a pure fetcher (URL → raw text).
   The intelligence (what to fetch, how to extract, how to synthesize) lives in the tiered host
   pipeline. This also makes sandbox verification straightforward: test that the fetch returns
   valid bytes, not that a multi-step LLM pipeline produces correct output.

**Boundary contract under Option B:**
```
capability tool.py (inside WSL2)
  input:  fetch_targets: list[FetchTarget]   # planned by host Opus call
  output: FetchResult(items: list[RawItem])  # raw text/bytes, no model calls

host AggregationPipeline
  step 1 (orchestrate): Opus plans fetch_targets from goal
  step 2 (pull):        FetchSandbox.fetch(fetch_targets) → RawItem list
  step 3 (extract):     Sonnet/Haiku parallel calls, RawItem → ExtractedFact list
  step 4 (synthesize):  Codex combines ExtractedFact list → final aggregate
```

---

## 3. Tiering Map onto Router + Spine

### Is this a router change, a Spine change, or a new component?

**New component.** The existing abstractions each own a distinct concern:
- `QuotaAwareRouter`: availability-first failover across backends
- `Spine`: plan→act→verify loop for a single task against a single model

A data-aggregation pipeline is neither of these. It is a specialized multi-stage pipeline that
needs per-stage model selection and parallel fan-out at the pull/extract stage. Stuffing it into
the Spine or the router would conflate concerns and require breaking changes to both.

The right answer is a new `AggregationPipeline` class that:
- Holds three named `ModelPort` slots (orchestrate, pull, synthesize)
- Manages the four-stage flow
- Can back each slot with a `QuotaAwareRouter` for resilience

The existing `Spine` and `QuotaAwareRouter` are **unchanged**. Reactive tasks (the existing
ProactiveWorker → Spine path) stay on the existing router. Aggregation capabilities opt into
the new pipeline.

### Role selection: what would it take to add per-tier/role model selection?

Three options, ranked:

**A. Separate `ModelPort` instances (preferred for now)**
Each tier is a distinct `ModelPort` — the pipeline coordinator picks the right one per stage. No
changes to `ModelPort`, `QuotaAwareRouter`, or `Spine`. The three instances can internally be
`ModelClient`s wrapping specific providers, or narrow `QuotaAwareRouter`s.

Downside: model assignment is baked into `build_aggregation_pipeline()` rather than being
runtime-configurable.

**B. Role tag on `complete()` call**
Add `role: Literal["orchestrate", "pull", "synthesize"] | None = None` to `ModelPort.complete()`.
The router would branch on `role` to pick a different backend.

Downside: contaminates `ModelPort` (a clean protocol) with pipeline-specific semantics. Every
backend implementation needs updating. Breaks existing `Spine` callers if `role` is required.
Only worth doing if the same router instance must serve both reactive and aggregation tasks.

**C. Router-side named pools**
Extend `QuotaAwareRouter` with named pools (`orchestrate_chain`, `pull_chain`, `synthesize_chain`)
and a `complete(..., pool=...)` dispatch. Similar to B but scoped inside the router.

Verdict: start with **A**. If runtime reconfigurability of tier assignments becomes a product
requirement, migrate to B or C at that point.

---

## 4. How a Capability Declares Its Tier

Current `SkillDraft` in `src/artemis/types.py` has `uses: list[str]`. The minimum-touch approach:

Add one optional field:

```python
class SkillDraft(BaseModel):
    ...
    pipeline: str | None = None  # "standard" | "aggregation" | None (default = standard)
```

Same addition to `Skill`. The forge reads this field when routing a build:
- `None` / `"standard"` → existing `SubprocessSandbox` path
- `"aggregation"` → `FetchSandbox` + `AggregationPipeline` path

In SKILL.md front matter, this would render as `pipeline: aggregation`.

Alternative: use an existing field by convention — e.g., `uses: ["pipeline:aggregation"]`. Avoids
a schema change but is looser. The structured field is preferred for type safety and routing
clarity.

---

## 5. Concrete Code Changes (Minimal Set)

### File 1: `src/artemis/types.py`
Add `pipeline: str | None = None` to `SkillDraft` and `Skill`. ~2 lines.

### File 2: `src/artemis/model/aggregation.py` (new, ~60 lines)

```python
"""Three-tier data-aggregation pipeline: orchestrate → fetch → extract → synthesize."""

from __future__ import annotations
import asyncio
from artemis.ports.model import ModelPort
from artemis.types import Message


class AggregationPipeline:
    def __init__(
        self,
        *,
        orchestrator: ModelPort,   # Opus-class
        puller: ModelPort,          # Sonnet/Haiku — called in parallel
        synthesizer: ModelPort,     # Codex
    ) -> None:
        self._orchestrator = orchestrator
        self._puller = puller
        self._synthesizer = synthesizer

    async def run(self, goal: str, raw_items: list[str]) -> str:
        """
        Phase 3 + 4: parallel extract then synthesize.
        Phase 1 (orchestrate) and Phase 2 (fetch) happen before this call;
        raw_items come from FetchSandbox.
        """
        extracted: list[str] = await self._extract_all(raw_items)
        return await self._synthesize(goal, extracted)

    async def plan_fetch_targets(self, goal: str) -> list[str]:
        """Phase 1: Opus decides what to fetch."""
        resp = await self._orchestrator.complete(
            messages=[
                Message(role="system", content=(
                    "You are Artemis. Given a data-aggregation goal, return a JSON list of "
                    "URL strings to fetch — only sources likely to have the needed data."
                )),
                Message(role="user", content=goal),
            ],
            response_schema={
                "type": "object",
                "properties": {"urls": {"type": "array", "items": {"type": "string"}}},
                "required": ["urls"],
            },
            model="claude-opus-4-5",
        )
        return (resp.structured or {}).get("urls", [])

    async def _extract_all(self, raw_items: list[str]) -> list[str]:
        """Phase 3: Sonnet/Haiku extracts structured facts from each raw item in parallel."""
        tasks = [self._extract_one(item) for item in raw_items]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return [r for r in results if isinstance(r, str)]

    async def _extract_one(self, raw: str) -> str:
        resp = await self._puller.complete(
            messages=[
                Message(role="system", content=(
                    "Extract the key facts from this raw fetched content. "
                    "Return a concise structured summary."
                )),
                Message(role="user", content=raw[:8000]),
            ],
        )
        return resp.text

    async def _synthesize(self, goal: str, facts: list[str]) -> str:
        """Phase 4: Codex synthesizes the final aggregate."""
        combined = "\n\n---\n\n".join(facts)
        resp = await self._synthesizer.complete(
            messages=[
                Message(role="system", content=(
                    "Synthesize the extracted facts into a concise final answer for the goal."
                )),
                Message(role="user", content=f"Goal:\n{goal}\n\nFacts:\n{combined}"),
            ],
            model="gpt-5.5",
        )
        return resp.text
```

### File 3: `src/artemis/capabilities/sandbox.py`

When the WSL2 sandbox lands, add a `FetchSandbox` class beside `SubprocessSandbox`:

```python
class FetchResult(BaseModel):
    items: list[str]    # raw text/bytes from each fetched URL
    errors: list[str]   # URLs that failed, for partial-success handling

class FetchSandbox:
    """WSL2-isolated fetch pipe. Runs capability's fetch code; returns raw bytes only.
    Model credentials NEVER enter this sandbox.
    """
    async def fetch(self, skill_dir: Path, targets: list[str]) -> FetchResult:
        ...  # WSL2 invocation: pass targets in, get raw items out; no model calls inside
```

No model credentials, no model calls inside this class.

### File 4: `src/artemis/model/compose.py`

Add a factory function:

```python
def build_aggregation_pipeline(*, anthropic_api_key: str | None = None) -> AggregationPipeline:
    from artemis.model.aggregation import AggregationPipeline
    opus = ModelClient(
        AnthropicAPIProvider(api_key=anthropic_api_key, model_default="claude-opus-4-5"),
        model_default="claude-opus-4-5",
    )
    puller = QuotaAwareRouter([
        ("claude_code", ModelClient(ClaudeCodeProvider(), model_default="sonnet")),
        ("anthropic_api", ModelClient(
            AnthropicAPIProvider(api_key=anthropic_api_key, model_default="claude-haiku-4-5"),
            model_default="claude-haiku-4-5",
        )),
    ])
    synthesizer = ModelClient(CodexProvider(), model_default="gpt-5.5")
    return AggregationPipeline(orchestrator=opus, puller=puller, synthesizer=synthesizer)
```

### File 5: `src/artemis/capabilities/forge.py`

When building a capability with `pipeline == "aggregation"`:
- Block until `FetchSandbox` exists (same guard pattern as `UNSAFE_IMPORTS`)
- Route approved proposals through `FetchSandbox.fetch()` → `AggregationPipeline.run()`

Add constant:
```python
AGGREGATION_BLOCK_REASON = (
    "aggregation pipeline requires FetchSandbox (WSL2); blocked until sandbox is implemented"
)
```

And in `_safety_reason()`:
```python
if draft.pipeline == "aggregation":
    if not _fetch_sandbox_available():
        return AGGREGATION_BLOCK_REASON
```

---

## 6. Open Forks

### Fork 1: WSL2 FetchSandbox spec not written
The forge blocks network capabilities with "blocked until the isolated WSL2 sandbox exists" (forge.py
line 116). The `FetchSandbox` boundary contract (what goes in, what comes out, egress allowlist
enforcement, resource limits) needs a dedicated spec before any fetch-pipe work can begin. This is a
blocker for any aggregation capability running end-to-end.

### Fork 2: Parallel pull concurrency cap
"Many cheap parallel calls" needs a bounded `asyncio.Semaphore` — uncapped fan-out can exhaust
connection pools and rate limits simultaneously. Not yet designed.

### Fork 3: Partial-success model
If 3 of 5 pulls fail, does the synthesizer run on partial data? Fail the whole capability? Return
with a warning? No policy exists yet. The `FetchResult.errors` field above is a placeholder.

### Fork 4: Per-capability egress allowlist
Each aggregation capability may need different allowed domains. Who approves new egress targets —
the owner at capability promotion time? A static list in the sandbox config? This is a governance
question that shapes the FetchSandbox API design.

### Fork 5: Tier model IDs are hardwired in compose.py
The Opus orchestrator is pinned to `claude-opus-4-5` in the factory. If model IDs change or the
owner wants to swap tiers (e.g. use Claude for synthesis instead of Codex), there is no
configuration surface. A `TierConfig` dataclass passed to `build_aggregation_pipeline()` would
solve this.

### Fork 6: No capability-level telemetry for cross-tier cost
The current `Usage` model in `src/artemis/types.py` has `prompt_tokens`, `completion_tokens`,
`total_tokens` — all zeroed by most providers today. Cross-tier cost attribution (Opus orchestrate
call vs 10 Sonnet extract calls vs Codex synthesize) requires per-tier telemetry aggregation.
Not blocking for an initial implementation, but needed before production cost management.

---

## Summary Table

| Question | Answer |
|---|---|
| Sandbox/host boundary | **Option B**: sandbox = dumb fetch pipe; host runs all model tiers |
| Router change needed? | No — router is availability-only failover; no role concept needed there |
| Spine change needed? | No — Spine is single-model reactive loop; aggregation is a separate path |
| New component needed? | Yes: `AggregationPipeline` in `src/artemis/model/aggregation.py` |
| Capability declaration | Add `pipeline: str | None` field to `SkillDraft` + `Skill` in `types.py` |
| Blocking dependency | `FetchSandbox` (WSL2) must be specced before any aggregation capability can run E2E |
| Files touched (minimal) | `types.py`, `model/aggregation.py` (new), `model/compose.py`, `capabilities/sandbox.py`, `capabilities/forge.py` |
