# AGENT-spine — build progress / deviations / flags

Built by Codex (Tasks 2-4) + host (Task 1 dep). Host-verified: full `uv run mypy` clean
(281 files), ruff clean, 802 passed / 3 skipped. Opus cross-model (security) review: CLEAN on
all security BLOCKs (auth-before-every-ACT incl. re-plans, deterministic-verify-only +
fail-closed-on-unknown-check, budget/breaker->inbox with None->FAILED, role-separated untrusted
goal, parked-tasks-checkpoint-and-stop, authorize-raises->fail-closed-park).

## DEVIATIONS (logged)
1. Task 1 mechanism: spec said `[project.optional-dependencies] agentic` + `uv sync --extra agentic`,
   but the project uses PEP 735 `[dependency-groups]` (the docling precedent the spec cites).
   Added `pydantic-ai>=2.0.0` to `[dependency-groups] agentic`, installed via `uv sync --group agentic`.
   Same intent (optional, lean base — base `uv sync` confirmed lean). Done by HOST (not Codex sandbox)
   per the Windows sandbox-ownership rule.
2. OUT-OF-SPEC FILE TOUCHED: `tests/test_api_app.py`. The Task-1 dep (pydantic-ai) pulled `httpx2`
   into the tree, so `starlette.testclient.TestClient` now returns `httpx2.Response` instead of
   `httpx.Response`, breaking that test's `httpx.Response` annotations (14 mypy errors) — a direct
   ripple from this spec's dep change, not pre-existing. Fixed minimally + env-agnostically: replaced
   the concrete `httpx.Response` annotation with a structural `_JsonResponse` Protocol (json()+status_code)
   on `_json_obj`/`_pair`, dropping the now-unneeded `cast(Response, ...)`. Test-only, behaviour
   unchanged; works whether httpx2 is installed (agentic-synced) or not (lean base).

## FLAG 1 (composition seam, review-needed) — approve->graduate wiring incomplete
The executor calls `authority.graduate(pending.id)` right after an inbox "yes", but
`AuthorityGate.graduate` only enrols when the staged `PendingAction.status is ActionStatus.APPROVED`
— a state set ONLY by `ActionStagingService.approve()` (the GATE surface). The executor neither
injects the staging service nor calls `approve`, so against the REAL AuthorityGate a boundary step
parks at "authority graduation failed" rather than proceeding (inbox "yes" doesn't flip the staging
row to APPROVED). FAIL-CLOSED (never proceeds ungated) — safe — but the approve->proceed happy path
for boundary crossings is functionally incomplete. The AGENT-authority spec itself suggested
graduation should fire "as a passive listener inside the staging-approval path" rather than via the
executor. Tests pass via a fake authority. ACTION: complete the staging-approval->graduate wiring
when the GATE approval surface (GATE-b, currently Tauri-gated) lands; prefer moving graduation to a
staging-approval listener so it never flows through the executor.

## FLAG 2 (review-needed) — token budget not enforced
`BudgetTracker.check` is always called with `tokens_used=0` (the executor accumulates no planner/tool
token usage), so `token_budget` never trips — only `step_budget`/no-progress are enforced. Wire
pydantic-ai usage accounting to enforce the token ceiling.
