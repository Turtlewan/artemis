---
spec: agent-loop-wiring
status: ready
token_profile: balanced
autonomy_level: L3
coder_effort: high
---

# Spec: agent-loop-wiring — AL-4a — run the built agent loop behind /app/ask (feature-flagged)

**Identity:** Replace the `plain_ask` one-shot completion in the ask path with the committed agent
loop (AL-1/AL-2/AL-3), constructed per-request from the ADR-049 role registry and gated by an
`ARTEMIS_AGENT_LOOP` feature flag (default OFF). Wiring only — no loop machinery is built here.
→ why: docs/technical/adr/ADR-047-agentic-assistant-loop.md (#1 ask-path-as-loop; 2026-07-04 Amendment: driver/judge/escalation roles).

<!-- SCOPE FENCE (ADR-047 arc). AL-4a WIRES the loop into the plain_ask pipe ONLY. Explicitly EXCLUDED
(do NOT build here): client rendering of verdict/answered_from/escalated (AL-4c — anchors on the brain
DTO fields defined here); gateway.rs struct additions for the three new fields (AL-4c); RAG tool
selection (AL-5); SSE step-trace serialization of StepRecords (AL-6); Spine unification (AL-7); the
go-live flip of the flag (later owner step, gated on the eval cluster). The loop machinery itself
(AgentLoop / EscalatingLoop / VerifyJudge / tools) is already committed and is consumed UNMODIFIED.
FORWARD NOTE for AL-4c (security review): `verdict_reason` is judge free text derived from analysis
of untrusted ingested content — the client MUST render it as plain text only, never HTML/markdown. -->

## Assumptions
<!-- Format: assumption → impact if wrong (Stop | Caution | Low) -->
- The `plain_ask` one-shot lives at `src/artemis/api/ask_routes.py` L180-182 (`_routed_answer`'s
  `if intent.route == "plain_ask":` branch calling `_answer(model, text)`), and BOTH no-match
  fall-throughs — the stale-capability case (L245) and the no-selection case (L267) — reach it by
  calling `_routed_answer`. Changing only that branch therefore covers both fall-throughs → impact:
  Stop (this is the single wiring point; a wrong anchor wires the loop into the wrong pipe).
- The web_q-without-key degrade path (`_routed_answer` L192-200) ALSO calls `_answer` but is NOT the
  `plain_ask` route — it must stay exactly as-is (still `_answer`, still `_NO_SEARCH_PREFIX`) → impact:
  Stop (wiring the loop here would change the web-degrade contract, out of scope per frozen decision #1).
- The loop's public surface is importable from `artemis.agent`: `AgentLoop`, `EscalatingLoop`,
  `LoopResult`, `ToolRegistry`, `build_local_read_tool` (verified `src/artemis/agent/__init__.py`).
  `AgentLoop.__init__` is keyword-only (`*, driver, tools, judge=None, …`) and takes `tools:
  ToolRegistry` (so `build_local_read_tool(store)` must be wrapped in `ToolRegistry([...])`);
  `EscalatingLoop.__init__(*, primary, escalation=None)` (verified `loop.py`, `escalation.py`,
  `tools.py`) → impact: Stop (a wrong constructor shape fails the build).
- `LoopResult` carries `answer: str`, `steps: tuple[StepRecord, …]`, `stop_reason: StopReason`,
  `verdict: Verdict` (default `"unjudged"`), `verdict_reason: str` (default `""`), and `escalated:
  bool` (default `False`). Non-answered returns in `loop.py` NEVER set `verdict`, so `result.verdict`
  is `"unjudged"` for every non-answered stop by default — a uniform `verdict=result.verdict` mapping
  is therefore correct for all stop reasons (verified `loop.py` L177/L279/L289 vs `_answered`) →
  impact: Caution (if a future non-answered path set a verdict, the mapping would leak it — it does not today).
- `StepRecord.ok` is `True` only when a tool ran and returned. `answered_from` derives from it:
  `"local_data"` iff `any(s.ok for s in result.steps)`, else `"general_knowledge"` (zero steps OR
  only-failed steps → the answer was not grounded in a successful local read; this is the Finding-D
  transparency signal) → impact: Caution (a looser rule would mislabel an ungrounded answer as local).
- `create_app` always constructs `app.state.model_roles` (L115) and `app.state.data_store` (L145),
  and exposes the `enable_sync: bool = False` kwarg precedent (L100) + the `ARTEMIS_DATA_DIR` env-read
  precedent (L103). The registry-absent fallback (`getattr(app.state, "model_roles", None) is None`)
  is the same guard the other seams use (`_role_port` L94-98, `_read_service` L138-141) — reachable in
  tests by setting `app.state.model_roles = None` → impact: Low.
- Adding three optional fields to `AskResponse` (all `= None`) makes FastAPI serialize three extra
  `null` keys on EVERY `/app/ask` response (default `response_model_exclude_none=False`). This is an
  ADDITIVE contract change, NOT byte-identical: the one existing exact-dict assertion
  (`tests/api/test_ask_routes.py::test_plain_ask_keeps_completion_path`, L280-291) must be updated to
  include the three null keys. All other ask-route tests assert individual fields and are unaffected
  (grepped) → impact: Stop (the exact-dict test fails otherwise; see the return note).
- No `MemoryPort` exists on `app.state` in `create_app` today, so the loop is wired with the
  local-read tool ONLY; a one-line seam comment marks where a memory tool joins later → impact: Low.

Simplicity check: considered constructing the loop inside `_routed_answer` from the `Request`
directly (no threaded param) — rejected: `_routed_answer`/`_invoke_or_routed_answer` are plain
functions taking injected deps (not `Request`), and the house pattern resolves app.state seams in a
`_name(request)` dependency and threads the result down (mirrors `_read_service`/`_intent`/`_selector`).
So the loop is built in one `_agent_loop(request)` dependency and threaded as a `loop` param — minimal,
consistent, and directly overridable in tests. Considered a new `enable_agent_loop: bool = False`
kwarg identical to `enable_sync` — rejected: the flag must also read `ARTEMIS_AGENT_LOOP`, which a
plain `bool` default cannot express; a tri-state `bool | None = None` (explicit kwarg wins, else env,
else off) is the minimal shape and matches the env-resolution already in `create_app` (L103).

## Prerequisites
- Specs complete first: AL-1 (`agent-loop-core`, 932da44), AL-2 (`agent-loop-stop-discipline`,
  d44af9a), AL-3 (`agent-loop-escalation`, e01842c + 58e1c70) — all committed on `v2-rebuild`; their
  surfaces are consumed UNMODIFIED. Also consumed as-built: `src/artemis/model/roles.py`
  (`for_role`, the `loop_driver`/`judge`/`escalation_driver` roles + their invariants),
  `src/artemis/data/store.py` (`DataStore`).
- Environment setup: none beyond `uv sync`. No new dependencies.

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| `src/artemis/api/app.py` | modify | Add `enable_agent_loop: bool \| None = None` kwarg + `_env_flag` helper + `app.state.agent_loop_enabled` (env `ARTEMIS_AGENT_LOOP`). |
| `src/artemis/api/ask_routes.py` | modify | Loop imports; `_agent_loop` dependency; three new `AskResponse` fields; `_loop_answer` mapper; thread `loop` through `_routed_answer` / `_invoke_or_routed_answer` / both handlers. |
| `tests/test_ask_loop.py` | create | Hermetic: flag on/off parity, injected-loop answer flow (verdict/answered_from/escalated in the JSON), non-answered stop mapping, no-registry fallback, env read. |
| `tests/api/test_ask_routes.py` | modify | Update the one exact-dict assertion (`test_plain_ask_keeps_completion_path`) to include the three new null keys. |

Non-test files touched: 2 (`app.py`, `ask_routes.py`) — within the ≤3 rule. ✓

## Tasks
- [ ] Task 1: Add the feature flag to the app factory — `_env_flag(name)` helper, `enable_agent_loop:
  bool | None = None` kwarg on `create_app`, and `app.state.agent_loop_enabled = enable_agent_loop if
  not None else _env_flag("ARTEMIS_AGENT_LOOP")` — files: `src/artemis/api/app.py` — done when:
  `create_app(enable_agent_loop=True).state.agent_loop_enabled is True`; with the kwarg omitted and
  `ARTEMIS_AGENT_LOOP=1` set it is `True`; unset → `False`; `uv run mypy` clean.
- [ ] Task 2: Wire the loop into the plain_ask pipe — add loop imports; add `_agent_loop(request) ->
  EscalatingLoop | None` (returns None when the flag is off OR the registry is absent, else builds
  `EscalatingLoop(primary=AgentLoop(loop_driver, tools, judge), escalation=AgentLoop(escalation_driver,
  tools, judge))` with `tools = ToolRegistry([build_local_read_tool(data_store)])`); add the three
  optional `AskResponse` fields; add `_loop_answer(loop, text) -> AskResponse`; add a `loop:
  EscalatingLoop | None = None` param to `_routed_answer` (use it in the plain_ask branch only) and to
  `_invoke_or_routed_answer` (pass to both `_routed_answer` calls); add `Depends(_agent_loop)` to
  `ask` and `ask_stream` and thread it in — files: `src/artemis/api/ask_routes.py` — done when: flag
  OFF ⇒ legacy `_answer` runs unchanged; flag ON + plain_ask ⇒ `loop.run` result maps onto the DTO;
  `uv run mypy` clean.
- [ ] Task 3: Hermetic tests + fix the exact-dict assertion — files: `tests/test_ask_loop.py`,
  `tests/api/test_ask_routes.py` — done when: `uv run pytest -q tests/test_ask_loop.py` passes all
  cases and `uv run pytest -q` is fully green.

## Wave plan
Wave 1: [Task 1, Task 2] | Wave 2: [Task 3]
<!-- Task 1 (app.py) and Task 2 (ask_routes.py) are file-disjoint and share only the app.state
attribute NAME "agent_loop_enabled" (a string contract, not an import) — both workers must use exactly
that name. Task 2's `_agent_loop` reads it via getattr(..., False), so it is robust even if built
before Task 1 lands. Task 3 imports/exercises both and runs after. -->

## Exact changes

### Task 1 — `src/artemis/api/app.py` (modify)

**Edit A — env-flag helper.** Add a module-level helper near `_CALENDAR_SYNC_CRON` (top of module,
`os` is already imported at L6):

```python
def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true"}
```

**Edit B — kwarg.** Extend the `create_app` signature (add after `enable_sync: bool = False,`):

```python
def create_app(
    *,
    data_dir: str | Path | None = None,
    model: ModelPort | None = None,
    sandbox: SandboxRunner | None = None,
    secrets: SecretStorePort | None = None,
    enable_sync: bool = False,
    enable_agent_loop: bool | None = None,
) -> FastAPI:
```

**Edit C — resolve + store the flag.** Immediately AFTER the existing
`app.state.data_store = DataStore(...)` line (L145) and BEFORE the `if enable_sync:` block, add:

```python
    app.state.agent_loop_enabled = (
        enable_agent_loop if enable_agent_loop is not None else _env_flag("ARTEMIS_AGENT_LOOP")
    )
```

No other change to `app.py` (the loop is built in `ask_routes.py`, not here).

### Task 2 — `src/artemis/api/ask_routes.py` (modify)

**Edit A — imports.** After the existing `from artemis.api.auth import Principal, require_session`
line (L13), add:

```python
from artemis.agent import (
    AgentLoop,
    EscalatingLoop,
    LoopResult,
    ToolRegistry,
    build_local_read_tool,
)
```

**Edit B — AskResponse gains three optional fields.** Append to the `AskResponse` model (after
`missing: list[str] | None = None`, L58):

```python
    verdict: str | None = None  # AL-2 verify-on-stop: "passed"/"flagged"/"unjudged"; None off-loop
    verdict_reason: str | None = None  # judge's reason on passed/flagged; None when absent/off-loop
    answered_from: str | None = None  # "local_data" (≥1 ok tool step) | "general_knowledge" | None
```
<!-- escalated already exists (L52); AL-4a is the first path to SET it from a real signal. -->

**Edit C — the loop-construction dependency.** Add near the other `_name(request)` seams (e.g. after
`_read_service`, L142). Mirrors the registry-absent guard used by `_role_port`/`_read_service`:

```python
def _agent_loop(request: Request) -> EscalatingLoop | None:
    """Build the per-request agent loop, or None to fall back to the legacy one-shot _answer.

    None when the ARTEMIS_AGENT_LOOP flag is off OR the ADR-049 role registry is absent (same
    getattr guard the other seams use). Loop machinery (AL-1/2/3) is consumed unmodified.
    """
    if not getattr(request.app.state, "agent_loop_enabled", False):
        return None
    roles = getattr(request.app.state, "model_roles", None)
    if roles is None:
        return None
    store: DataStore = request.app.state.data_store
    tools = ToolRegistry([build_local_read_tool(store)])
    # SEAM: no MemoryPort on app.state today (create_app builds none). When one lands, append
    # build_memory_tool(memory) to the tools list here — no other change needed.
    # FAIL-SAFE DIRECTION (security review): ANY role-resolution failure — raise OR None — falls
    # back to the legacy one-shot. Never construct a judge-less or partially-resolved loop.
    try:
        judge_port = roles.for_role("judge")
        driver_port = roles.for_role("loop_driver")
        escalation_port = roles.for_role("escalation_driver")
    except Exception:  # noqa: BLE001 — resolution failure = legacy answer, never a degraded loop.
        _log.warning("agent_loop: role resolution failed — legacy fallback", exc_info=True)
        return None
    if judge_port is None or driver_port is None or escalation_port is None:
        _log.warning("agent_loop: a role resolved to None — legacy fallback")
        return None
    return EscalatingLoop(
        primary=AgentLoop(driver=driver_port, tools=tools, judge=judge_port),
        escalation=AgentLoop(driver=escalation_port, tools=tools, judge=judge_port),
    )
```

<!-- NOTE for the coder: use the module's existing logger if ask_routes.py has one; otherwise add
`_log = logging.getLogger(__name__)` beside the imports (stdlib logging is already imported or
trivially added). -->

**Edit D — the LoopResult → AskResponse mapper.** Add near `_answer` (after L170). Reads result
fields only; it cannot raise. `EscalatingLoop.run` never raises into the caller (its contract), and a
non-answered stop already carries a graceful partial answer:

```python
async def _loop_answer(loop: EscalatingLoop, text: str) -> AskResponse:
    result: LoopResult = await loop.run(text)
    answered_from = "local_data" if any(step.ok for step in result.steps) else "general_knowledge"
    return AskResponse(
        text=result.answer,
        path="loop",
        tool_used=None,
        escalated=result.escalated,
        verdict=result.verdict,
        verdict_reason=result.verdict_reason or None,
        answered_from=answered_from,
    )
```
<!-- Uniform mapping across every stop_reason: on "answered", result.verdict is the judge outcome; on
any non-answered stop, loop.py leaves result.verdict == "unjudged" (default) and result.verdict_reason
== "" (→ None here). result.answer is the answer on "answered" and the graceful partial otherwise. -->

**Edit E — thread `loop` through `_routed_answer` (plain_ask branch ONLY).** Add a trailing param and
use it in the plain_ask branch. Signature:

```python
async def _routed_answer(
    model: ModelPort,
    intent_router: IntentRouter,
    text: str,
    secrets: SecretStorePort,
    loop: EscalatingLoop | None = None,
) -> AskResponse:
```

Replace ONLY the plain_ask branch (current L180-182):

```python
    if intent.route == "plain_ask":
        if loop is not None:
            return await _loop_answer(loop, text)
        answer, path = await _answer(model, text)
        return AskResponse(text=answer, path=path, tool_used=None, escalated=False)
```

Do NOT touch the `build`, `aggregate`, web_q-with-key, or web_q-without-key (`_NO_SEARCH_PREFIX`)
branches — they stay exactly as-is.

**Edit F — thread `loop` through `_invoke_or_routed_answer`.** Add a trailing param:

```python
    session_key: str,
    loop: EscalatingLoop | None = None,
) -> AskResponse:
```

and change BOTH `_routed_answer` calls (the stale-capability fall-through at L245 and the no-match
fall-through at L267) from:

```python
        return await _routed_answer(model, intent_router, text, secrets)
```
to:
```python
        return await _routed_answer(model, intent_router, text, secrets, loop)
```

The curate, local_read, invoke_confirm, and invoke_clarify returns are UNCHANGED (verdict/
verdict_reason/answered_from default to None on those paths).

**Edit G — wire the dependency into both handlers.** In `ask` (L273) and `ask_stream` (L304), add the
new dependency parameter after `last_results: … = Depends(_last_results)`:

```python
    agent_loop: EscalatingLoop | None = Depends(_agent_loop),
```

and pass `loop=agent_loop` into the `_invoke_or_routed_answer(...)` call in each (append after
`session_key=principal.device_id,`):

```python
        session_key=principal.device_id,
        loop=agent_loop,
    )
```

### Task 3 — tests

**`tests/api/test_ask_routes.py` (modify) — one edit.** In `test_plain_ask_keeps_completion_path`
(L280-291), add the three new keys to the expected dict so the exact-equality assertion still holds
(flag is OFF by default in that test, so all three are null):

```python
    assert response.json() == {
        "text": "the answer",
        "path": "codex",
        "tool_used": None,
        "escalated": False,
        "invoke_id": None,
        "capability": None,
        "egress_domains": None,
        "secrets": None,
        "args": None,
        "missing": None,
        "verdict": None,
        "verdict_reason": None,
        "answered_from": None,
    }
```

**`tests/test_ask_loop.py` (create).** Hermetic. Reuse the house fixtures from
`tests/api/test_ask_routes.py`: `create_app(model=…)`, `app.dependency_overrides[require_session]`,
`FixedIntentRouter`, `FixedSelector(_no_match())`, `TestClient`. Inject the loop by overriding the
`ask_routes._agent_loop` dependency with a scripted fake (the same override style used for `_intent`/
`_selector`). Fake `LoopResult`s are constructed directly.

```python
from __future__ import annotations

from collections.abc import Sequence
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from artemis.agent import EscalatingLoop
from artemis.agent.loop import LoopResult, StepRecord
from artemis.api import ask_routes
from artemis.api.app import create_app
from artemis.api.auth import Principal, require_session
from artemis.data.store import DataStore
from artemis.intent import Intent, IntentRouter, Route
from artemis.types import Message, ModelResponse, Usage


class FakeModel:  # satisfies ModelPort
    def __init__(self, text: str = "legacy answer", model_id: str = "qwen3:4b") -> None:
        self._text, self._model_id = text, model_id

    async def complete(self, *, messages, model=None, response_schema=None,
                       temperature=0.7, max_tokens=None):  # type: ignore[no-untyped-def]
        del messages, model, response_schema, temperature, max_tokens
        return ModelResponse(text=self._text, model_id=self._model_id, structured=None,
                             finish_reason="stop",
                             usage=Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0))


class FixedIntentRouter(IntentRouter):
    def __init__(self, route: Route) -> None:
        self._route = route

    async def classify(self, text: str) -> Intent:
        return Intent(route=self._route, confidence=1.0, reason=text)


class FakeLoop:  # satisfies the EscalatingLoop.run surface the route calls
    def __init__(self, result: LoopResult) -> None:
        self._result = result
        self.calls: list[str] = []

    async def run(self, request: str) -> LoopResult:
        self.calls.append(request)
        return self._result


class FakeRegistry:  # satisfies the .for_role() surface _agent_loop uses
    def for_role(self, role: str):  # type: ignore[no-untyped-def]
        return FakeModel()


def _ok_step() -> StepRecord:
    return StepRecord(index=0, tool="local_read", args={"domain": "calendar"},
                      outcome="1 record", ok=True, duration_ms=1, driver_ms=1, driver_tokens=0)


def _fail_step() -> StepRecord:
    return StepRecord(index=0, tool="nope", args={}, outcome="unknown tool",
                      ok=False, duration_ms=1, driver_ms=1, driver_tokens=0)


def _lr(answer: str, *, steps: tuple[StepRecord, ...] = (), stop_reason="answered",
        verdict="unjudged", verdict_reason="", escalated=False) -> LoopResult:
    return LoopResult(answer=answer, steps=steps, stop_reason=stop_reason, driver_turns=1,
                      driver_tokens_total=0, verdict=verdict, verdict_reason=verdict_reason,
                      escalated=escalated)


def _client(model: FakeModel, *, route: Route = "plain_ask",
            loop: FakeLoop | None = None, enable: bool | None = None) -> TestClient:
    app = create_app(model=model, enable_agent_loop=enable)
    app.dependency_overrides[require_session] = lambda: Principal(device_id="dev", person_id="owner")
    app.dependency_overrides[ask_routes._intent] = lambda: FixedIntentRouter(route)
    app.dependency_overrides[ask_routes._selector] = lambda: ask_routes.CapabilitySelector  # placeholder
    # match the house no-match selector exactly:
    from artemis.capabilities.select import SelectionResult

    class _Sel:
        async def select(self, request: str) -> SelectionResult:
            return SelectionResult(matched=False, capability=None, args={}, confidence=0.0,
                                   missing_required=[])
    app.dependency_overrides[ask_routes._selector] = lambda: _Sel()
    if loop is not None:
        app.dependency_overrides[ask_routes._agent_loop] = lambda: loop
    return TestClient(app)
```

Cases (each an async test unless noted):

1. **flag OFF → legacy `_answer`, all three loop fields null** → `_client(FakeModel("legacy",
   "qwen3:4b"), enable=False)` (no `_agent_loop` override); POST `/app/ask {"text":"hi"}` →
   `text=="legacy"`, `path in {"local","codex"}`, `verdict is None`, `verdict_reason is None`,
   `answered_from is None`, `escalated is False`.
2. **flag ON + injected loop, answered/passed with an ok step → local_data** → `loop =
   FakeLoop(_lr("you have lunch", steps=(_ok_step(),), verdict="passed", verdict_reason="grounded"))`;
   `_client(FakeModel(), loop=loop, enable=True)`; POST → `text=="you have lunch"`,
   `path=="loop"`, `verdict=="passed"`, `verdict_reason=="grounded"`, `answered_from=="local_data"`,
   `escalated is False`; `loop.calls==["hi"]` (the request text reached the loop).
3. **answered with ZERO tool steps → general_knowledge, empty reason → None** →
   `FakeLoop(_lr("from memory", steps=(), verdict="unjudged", verdict_reason=""))`; enable=True; POST →
   `answered_from=="general_knowledge"`, `verdict=="unjudged"`, `verdict_reason is None`.
4. **answered but only a FAILED step → general_knowledge** → `FakeLoop(_lr("x", steps=(_fail_step(),)))`;
   enable=True; POST → `answered_from=="general_knowledge"` (no ok step).
5. **non-answered stops → partial delivered, verdict unjudged, no raise (parametrized over ≥2 reasons)** →
   parametrize `stop_reason` over `["budget_exhausted", "stalling"]`:
   `FakeLoop(_lr("I couldn't fully answer — partial.", steps=(_ok_step(),), stop_reason=<reason>))`;
   enable=True; POST → status 200, `text=="I couldn't fully answer — partial."`, `verdict=="unjudged"`,
   `verdict_reason is None`, `answered_from=="local_data"`, `path=="loop"` — confirming the uniform
   mapping holds across distinct non-answered stop paths, not one representative.
6. **escalated flag propagates** → `FakeLoop(_lr("done", steps=(_ok_step(),), escalated=True))`;
   enable=True; POST → `escalated is True`.
7. **loop runs on the stream route too** → same loop as case 2; POST `/app/ask/stream` → 200, body
   contains `data: you have lunch` and ends with `data: [DONE]`.
8. **flag ON but intent != plain_ask → loop NOT run** → `_client(FakeModel(), route="build",
   loop=FakeLoop(_lr("SHOULD-NOT-APPEAR")), enable=True)`; POST → `path=="build"`, `verdict is None`,
   and `loop.calls==[]` (build pipe never touches the loop).
9. **no-registry fallback (unit)** → `req = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
   agent_loop_enabled=True, model_roles=None, data_store=DataStore(":memory:"))))`;
   `ask_routes._agent_loop(req) is None`.
10. **flag off → dependency returns None (unit)** → same as 9 but `agent_loop_enabled=False`,
    `model_roles=FakeRegistry()` → `_agent_loop(req) is None`.
11. **flag on + registry present → builds an EscalatingLoop (unit)** → `req = …(agent_loop_enabled=True,
    model_roles=FakeRegistry(), data_store=DataStore(":memory:"))`;
    `isinstance(ask_routes._agent_loop(req), EscalatingLoop)`.
12. **env read (create_app) incl. fail-closed garbage** → `monkeypatch.setenv("ARTEMIS_AGENT_LOOP","1")`;
    `create_app(model=FakeModel()).state.agent_loop_enabled is True`; with `"0"` → `False`; with a
    garbage value `"yes"` → `False` (anything but exactly 1/true is OFF — fail-closed regression);
    with the kwarg `enable_agent_loop=True` passed explicitly while env is unset → `True` (kwarg wins).
13. **role-resolution raise → legacy fallback (unit)** → `FakeRegistry` variant whose `for_role`
    raises `RuntimeError`; `req = SimpleNamespace(...agent_loop_enabled=True, model_roles=<raising
    registry>, data_store=DataStore(":memory:"))` → `ask_routes._agent_loop(req) is None` (no raise).
14. **role resolves to None → legacy fallback, never a judge-less loop (unit)** → `FakeRegistry`
    variant whose `for_role("judge")` returns `None` (others valid) → `_agent_loop(req) is None`.
15. **integration fail-safe: flag ON + registry absent → HTTP serves LEGACY** → real
    `create_app(model=FakeModel("legacy"), enable_agent_loop=True)`; set `app.state.model_roles = None`
    post-construction; POST `/app/ask {"text":"hi"}` via TestClient → 200, `path != "loop"`,
    `text=="legacy"`, `verdict is None`, `verdict_reason is None`, `answered_from is None` (the
    end-to-end HTTP path proves the fail-safe, not just the dependency unit).

<!-- NOTE for the coder: the `_client` helper above pins the no-match selector inline; prefer lifting
`_no_match()`/`FixedSelector` from tests/api/test_ask_routes.py if a shared conftest exists — otherwise
inline as shown. Match the require_session override and Principal shape EXACTLY as the house file. -->

## Permissions

The following actions will run autonomously during build. Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | `tests/test_ask_loop.py` |
| Modify | `src/artemis/api/app.py`, `src/artemis/api/ask_routes.py`, `tests/api/test_ask_routes.py` |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv sync` | Resolve dependencies (no new packages). |
| `uv run ruff format .` / `uv run ruff format --check .` | Format + verify. |
| `uv run ruff check .` | Lint. |
| `uv run mypy` | Full-project type check. |
| `uv run pytest -q tests/test_ask_loop.py` | Run this spec's suite. |
| `uv run pytest -q` | Full suite (zero regression). |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | `src/artemis/api/app.py src/artemis/api/ask_routes.py tests/test_ask_loop.py tests/api/test_ask_routes.py` |
| `git commit` | "feat(ask): wire the agent loop behind /app/ask (AL-4a, ARTEMIS_AGENT_LOOP flag)" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_AGENT_LOOP` | Read only (`"1"`/`"true"` = loop on, default OFF). Read in `create_app`; toggled via `monkeypatch.setenv` in tests. **HARD GATE: must remain unset/0 in owner-facing deployments until the AL-4 eval cluster passes — this spec does not authorize the flip.** |

### Network
| Action | Purpose |
|--------|---------|
| (none) | No network. Tests are hermetic (in-memory sqlite + fakes); the loop is never live-driven here. |

## Specialist Context
### Security
- No new external surface. The loop consumes the SAME quarantined `DataStore` reads the read-path
  already uses (`build_local_read_tool` renders `sanitized_text` only — the ingest-quarantine
  boundary, unchanged). The judge (AL-2) is wired via `for_role("judge")`, which the ADR-049 registry
  pins tool-free and temperature-0 and forces to differ from `loop_driver`; AL-4a does not
  re-implement or relax any of those invariants.
- The flag defaults OFF; go-live is a later owner step gated on the eval cluster. AL-4a delivers only
  the SIGNAL fields (verdict/answered_from/escalated) — it does not withhold or gate any answer.
- **Review FLAG (folded): fail-safe direction is total.** `_agent_loop` falls back to the legacy
  one-shot on flag-off, registry-absent, role-resolution RAISE, or any role resolving to None — a
  degraded/judge-less loop is never constructed (cases 13/14), and the fail-safe is proven at the
  HTTP level, not just the dependency unit (case 15).
- **Review FLAG (folded): HARD GATE — this spec does NOT authorize flipping the flag.**
  `ARTEMIS_AGENT_LOOP` must remain unset/`0` in any owner-facing deployment until the AL-4 eval
  cluster (driver golden-set, adversarial injection, judge calibration, escalation efficacy) passes.
  Restated in Permissions § Environment Access.

### Performance
- Loop cost is the budget-bounded driver completions + at most one judge call per answered stop +
  (on a non-convergent primary stop) one cross-family escalation pass. Already role-metered via
  `MeteredPort` (do NOT add new metering). Flag OFF adds zero cost (dependency returns None before
  any construction).
- **Review FLAG (accepted, latency posture named):** worst case flag-on plain_ask ≈ budget(8) ×
  driver-turn (~2-4s CLI) + judge (~1-2s) + a full escalation pass — tens of seconds on a
  pathological ask; typical multi-read asks ≈ 2-3 turns (~10s). Owner explicitly accepted the
  blocking-verify posture for the dogfood phase; a request-level timeout decision (uvicorn imposes
  none by default) joins the GO-LIVE checklist alongside the eval gates — deliberately not built here.
- **Review FLAG (accepted, scoped regression):** `/app/ask/stream` emits the full loop answer as ONE
  `data:` chunk after the loop completes (case 7). The stream route was already non-token-level
  (owner Option A); true incremental step/trace streaming is AL-6's contract. Accepted for AL-4a.

### Accessibility
(none — no frontend surface here; client rendering of the new fields is AL-4c.)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | `src/artemis/api/ask_routes.py` | Docstrings on `_agent_loop` / `_loop_answer` (as written above). |
| API | (none) | The `/app/ask` contract gains three optional response fields; no new endpoint. |
| Changelog | CHANGELOG.md | Add under Unreleased: "Wire the agent loop behind /app/ask (AL-4a) — feature-flagged via ARTEMIS_AGENT_LOOP (default off); AskResponse gains verdict / verdict_reason / answered_from and now sets escalated." |
| ADR | (none) | ADR-047 (+2026-07-04 Amendment) already covers the decision. |

## Acceptance Criteria
- [ ] Flag OFF is legacy behavior (values unchanged; three new keys null) → verify: `uv run pytest -q
  tests/test_ask_loop.py -k off` green AND `uv run pytest -q tests/api/test_ask_routes.py` green
  (updated exact-dict test passes).
- [ ] Flag ON runs the loop only on plain_ask; result maps onto the DTO → verify: `uv run pytest -q
  tests/test_ask_loop.py` — all cases green (answered/passed→local_data, zero-steps→general_knowledge,
  failed-only→general_knowledge, non-answered→partial+unjudged, escalated propagates, stream route,
  build pipe does not touch the loop).
- [ ] Loop is built from roles + local-read tool only → verify: `rg -n "build_local_read_tool|build_memory_tool"
  src/artemis/api/ask_routes.py` shows `build_local_read_tool` only; `rg -n "for_role\(" src/artemis/api/ask_routes.py`
  shows `loop_driver`, `judge`, `escalation_driver` (plus the pre-existing seam roles).
- [ ] Fail-safe is total → verify: cases 9/10/13/14 assert `_agent_loop(...) is None` on registry-absent / flag-off / role-resolution raise / role-None; case 15 proves the fail-safe at the HTTP level (flag ON + registry absent ⇒ legacy response).
- [ ] Env flag resolves as specified, fail-closed on garbage → verify: case 12 (`1`/`0`/`"yes"`→OFF, kwarg override).
- [ ] Non-answered stop never raises into the route → verify: case 5 returns 200 with the partial.
- [ ] Type + lint clean → verify: `uv run mypy` clean; `uv run ruff check .` + `uv run ruff format
  --check .` clean.
- [ ] Zero regression → verify: `uv run pytest -q` full suite green.
- [ ] Surgical → verify: `git diff --stat` shows only the four files above.

## Commands to run
```bash
uv sync
uv run ruff format .
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest -q tests/test_ask_loop.py
uv run pytest -q
```

## Progress
_(Coding mode writes here — do not edit manually)_
