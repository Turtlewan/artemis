---
slice: capability-build
status: ready
coder_effort: medium
depends_on: cb-1-gated-forge
---

# CB-2 — Brain build endpoints (propose / build / promote)

**Identity:** Second spec of the capability-build slice. Exposes CB-1's gated forge over HTTP as three session-gated endpoints under `/app/capabilities` so the client can drive the gated build conversation: `propose` (→ plan card), `build` (SSE status + result card), `promote` (→ installed). Wires a `CapabilityForge` onto `app.state` pointed at the **real data root** (`<data_dir>/capabilities`), holding each in-flight proposal in server-side state between the two gates. No client code, no intent detection (the client routes — CB-4), no map (CB-5). Design note: `docs/v2/capability-build-ux.md`; depends on `cb-1-gated-forge` (uses `forge.propose/build_proposed/promote`).

**Contract notes (define what gets built):**
- The SSE protocol uses **named events** (`event: status`, `event: result`) terminated by `data: [DONE]`, distinct from `/app/ask`'s bare-`data:` text stream — the build stream carries structured stages + a result object, not free text. CB-3's Rust bridge maps these to typed `Channel` events.
- In-flight proposals live in an **in-memory** dict on `app.state` keyed by an opaque `build_id`. Not durable (a build straddling a brain restart is lost — acceptable; builds are short-lived) and not evicted (single-user hub, short-lived — note the unbounded-growth interim).
- The store root is `<data_dir>/capabilities` (the **real** root), so capabilities built here persist — this lands the "real data root" half of the old CR-7 note; CB-5 adds only the list endpoint + map node.

## Files to change

1. `src/artemis/api/app.py` — **modify**: add a `sandbox` injection seam to `create_app`; wire `app.state.forge` + `app.state.builds`; include the new router.
2. `src/artemis/api/capability_routes.py` — **create**: DTOs, in-memory `BuildState`, and the `propose` / `build` / `promote` endpoints.
3. `tests/test_api_capabilities.py` — **create**: endpoint tests (plan, blocked plan, build SSE, promote, 409, session-gating).

One new route module + its wiring + its test → a single cohesive surface.

## Exact changes

### 1. `src/artemis/api/app.py`

**a.** Add imports:
```python
from artemis.api import ask_routes, capability_routes, domain_routes
from artemis.capabilities.forge import CapabilityForge
from artemis.capabilities.sandbox import SandboxRunner, SubprocessSandbox
from artemis.capabilities.store import FileCapabilityStore
```

**b.** Extend `create_app`'s signature with a sandbox seam (mirrors the existing `model` seam so tests can inject a fast fake sandbox):
```python
def create_app(
    *,
    data_dir: str | Path | None = None,
    model: ModelPort | None = None,
    sandbox: SandboxRunner | None = None,
) -> FastAPI:
```

**c.** After `app.state.model = ...`, wire the forge + the in-flight build store:
```python
    resolved_sandbox: SandboxRunner = sandbox if sandbox is not None else SubprocessSandbox()
    app.state.forge = CapabilityForge(
        app.state.model,
        FileCapabilityStore(resolved_data_dir / "capabilities"),
        resolved_sandbox,
    )
    app.state.builds = {}  # build_id -> capability_routes.BuildState (in-memory, interim)
```

**d.** Register the router alongside the others:
```python
    app.include_router(capability_routes.router)
```

### 2. `src/artemis/api/capability_routes.py` (create)

```python
"""Capability-build routes: drive CB-1's gated forge over HTTP (propose -> build -> promote)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from artemis.api.auth import Principal, require_session
from artemis.capabilities.forge import CapabilityForge
from artemis.types import BuildProposal


@dataclass
class BuildState:
    """Server-side state for one in-flight build, between the plan gate and the result gate."""

    proposal: BuildProposal
    staged_id: str | None = None


class ProposeRequest(BaseModel):
    goal: str


class PlanCard(BaseModel):
    build_id: str
    name: str
    description: str
    summary: str
    secrets: list[str]
    blocked: bool
    block_reason: str | None = None


class PromoteRequest(BaseModel):
    build_id: str


class InstalledCard(BaseModel):
    name: str
    version: int
    path: str


router = APIRouter(prefix="/app/capabilities")


def _forge(request: Request) -> CapabilityForge:
    forge: CapabilityForge = request.app.state.forge
    return forge


def _builds(request: Request) -> dict[str, BuildState]:
    builds: dict[str, BuildState] = request.app.state.builds
    return builds


def _named_event(event: str, data: str) -> str:
    """One named SSE event; multi-line data is split into `data:` lines per the SSE spec."""
    lines = "".join(f"data: {line}\n" for line in data.split("\n"))
    return f"event: {event}\n{lines}\n"


@router.post("/propose", response_model=PlanCard)
async def propose(
    req: ProposeRequest,
    request: Request,
    _principal: Principal = Depends(require_session),
) -> PlanCard:
    proposal = await _forge(request).propose(req.goal)
    build_id = uuid4().hex
    _builds(request)[build_id] = BuildState(proposal=proposal)
    draft = proposal.draft
    return PlanCard(
        build_id=build_id,
        name=draft.name,
        description=draft.description,
        summary=draft.body,
        secrets=draft.secrets,
        blocked=proposal.blocked,
        block_reason=proposal.block_reason,
    )


@router.post("/{build_id}/build")
async def build(
    build_id: str,
    request: Request,
    _principal: Principal = Depends(require_session),
) -> StreamingResponse:
    forge = _forge(request)
    state = _builds(request).get(build_id)

    async def event_stream() -> AsyncIterator[str]:
        if state is None:
            yield _named_event("error", "unknown build")
            yield "data: [DONE]\n\n"
            return
        if state.proposal.blocked:
            reason = state.proposal.block_reason or "blocked"
            yield _named_event("status", reason)
            yield _named_event(
                "result",
                json.dumps({"build_id": build_id, "passed": False, "blocked": True, "output": reason}),
            )
            yield "data: [DONE]\n\n"
            return
        yield _named_event("status", "Testing in sandbox…")
        attempt = await forge.build_proposed(state.proposal)
        state.staged_id = attempt.staged_id
        yield _named_event(
            "result",
            json.dumps(
                {
                    "build_id": build_id,
                    "passed": attempt.passed,
                    "blocked": False,
                    "output": attempt.output[:1000],
                }
            ),
        )
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/promote", response_model=InstalledCard)
async def promote(
    req: PromoteRequest,
    request: Request,
    _principal: Principal = Depends(require_session),
) -> InstalledCard:
    builds = _builds(request)
    state = builds.get(req.build_id)
    if state is None or state.staged_id is None:
        raise HTTPException(status_code=409, detail="build not verified")
    skill = await _forge(request).promote(state.staged_id)
    del builds[req.build_id]
    return InstalledCard(name=skill.name, version=skill.version, path=skill.path)
```

### 3. `tests/test_api_capabilities.py` (create)

Mirror the harness in `tests/test_api_ask.py` exactly:
- Authenticated client = `create_app(data_dir=tmp_path, model=<fake>, sandbox=<fake>)` with the session dependency overridden:
  ```python
  app.dependency_overrides[require_session] = lambda: Principal(person_id="owner", device_id="dev")
  client = TestClient(app)
  ```
  (Check `tests/test_api_ask.py` for the exact `Principal(...)` field names and copy them.)
- The **session-gating** test omits the override and asserts the unauthenticated request returns **401** (same as `test_ask_requires_session`).
- `FakeModel` and `FakeSandbox`: copy the exact shapes from `tests/test_forge.py` — `FakeModel(draft: SkillDraft)` whose `complete(...)` returns `ModelResponse(text="", model_id=..., structured=draft.model_dump(), finish_reason="stop", usage=Usage(...))`, and `FakeSandbox(VerifyResult(passed=True, output="ok"))`. Build a small `SkillDraft` inline (a trivial passing draft for the clean case; one with `tool_script="import imaplib\n..."` for the blocked case).
- For the SSE `build` test, read the streamed body via `client.post(..., )` (TestClient returns the full streamed text in `resp.text`) and assert it contains `event: status`, an `event: result` line, and `data: [DONE]`.

Cover:
- `propose` on a clean goal → 200, `blocked is False`, non-empty `build_id`, `name`/`summary` from the draft.
- `propose` on a network-draft model (`tool_script` importing `imaplib`) → 200, `blocked is True`, reason names `imaplib`.
- `build` on a clean `build_id` → stream body contains `event: status`, an `event: result` line whose JSON has `"passed": true`, and `data: [DONE]`.
- `build` on a blocked `build_id` → result JSON `"blocked": true`, and nothing is promoted.
- `promote` after a passed `build` → 200 `InstalledCard`, and the store now has the skill.
- `promote` with an unknown / unbuilt `build_id` → 409.
- Each endpoint without a session → the same unauthorized status the other `/app/*` routes return.

## Acceptance criteria

1. `propose` returns a `PlanCard` (clean → `blocked=False` with a `build_id`; network draft → `blocked=True` naming the module) → propose tests.
2. `build` streams `event: status` → `event: result` (`passed=true`) → `[DONE]` and records `staged_id`; a blocked proposal streams `blocked=true` and stages nothing → build tests.
3. `promote` installs a verified build (store has the skill, returns `InstalledCard`) and returns 409 when the build isn't verified → promote tests.
4. All three endpoints reject an unauthenticated request → session-gating test.
5. Whole project green: `uv run mypy` clean and `uv run pytest -q` all pass.

## Commands to run

```bash
uv run ruff format src/artemis/api/app.py src/artemis/api/capability_routes.py tests/test_api_capabilities.py
uv run ruff check src/artemis/api/capability_routes.py tests/test_api_capabilities.py
uv run mypy
uv run pytest -q
```
