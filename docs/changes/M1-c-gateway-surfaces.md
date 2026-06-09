---
spec: m1-c-gateway-surfaces
status: ready
token_profile: balanced
autonomy_level: L2
---

# Spec: M1-c — Gateway (text ingress + single-owner scope stub) + dev CLI + loopback streaming HTTP API

**Identity:** Implements the text Gateway that attaches a stubbed single-owner scope to every request before the Brain sees it, a dev CLI that drives the Brain from a terminal, and a loopback (127.0.0.1) streaming HTTP API on the existing FastAPI brain app — both text-only surfaces.
→ why: see docs/technical/architecture/brain.md § "Shape — thin custom orchestrator" (Gateway resolves person + scope before the Brain) · docs/technical/architecture/overview.md § "Interaction surfaces" + "Core — the brain".

<!-- Split rule: ONE logical phase (text surfaces + the gateway that fronts them), 3 new src files + 1 modify (main.py, the existing M0-b FastAPI app) + 1 test. The modify of main.py is additive (a new router/endpoint) and tightly coupled to the gateway, so it belongs here. At/just over the file guideline — justified atomic exception: the gateway is the single seam both surfaces share; a CLI or API without the gateway-scope-attach step would violate brain.md's "scope attached before the Brain". Flagged per rules. -->

## Assumptions
- M0-a (config/paths), M0-b (`src/artemis/main.py` FastAPI app with `/healthz` + `/readyz` + `get_settings()`), M0-d (`Scope`), M1-a (`ToolRegistry`), M1-b (`Brain`, `SemanticRouter`, `BrainResponse`, model adapters) complete. → impact: Stop (this spec wires those into surfaces; signatures must match).
- M1 is **single-owner stub**: the Gateway attaches a fixed `OWNER_SCOPE = "owner-private"` (M0-d `Scope`) and a fixed owner `PersonId` to every request. NO voice-ID, NO app login, NO guest path — those are M2. → impact: Low (the scope-attach seam exists and is honoured; the resolution logic is deliberately a constant).
- The streaming API uses **Server-Sent Events (SSE)** for server→client token streaming (the 2026 default for LLM token streams; FastAPI `StreamingResponse` with `text/event-stream`). → impact: Caution. Decision: SSE (`text/event-stream` via FastAPI `StreamingResponse`) for M1 — matches brain.md streaming + the eventual voice/app surfaces (apex-realtime SSE default). No on-hardware gate (code-shape).
- Brain assembly (which embedder/model adapters + which registered modules) happens in a single composition function so both surfaces and tests share one wired Brain. The wired Brain registers M1-d's `get_current_time` tool when present (Task references M1-d's manifest factory; if M1-d not yet built, the composition imports a placeholder that M1-d replaces). → impact: Caution (explicit dependency on M1-d's manifest factory name — fixed below).
- The CLI and API stream the Brain's answer. In M1 the Brain renders a single answer string (M1-b); the API streams it as one-or-more SSE chunks (token-streaming is real once the responder adapter streams; the tool path may emit a single chunk). → impact: Low.

Simplicity check: considered separate FastAPI apps per surface — rejected; M0-b already defines the one brain app + launchd daemon, so the API endpoint mounts there (one process, brain.md). Considered a full TUI for the CLI — rejected; a minimal `argparse`/`typer`-free stdin-loop CLI is the minimum dev surface. Considered WebSocket — rejected for M1; the M1 flow is one-shot request→streamed-answer (server→client only), which is SSE's exact shape.

## Prerequisites
- Specs that must be complete first: M0-a, M0-b (the FastAPI app to extend), M0-d, M1-a, M1-b. Soft dependency on M1-d (the time tool registered in composition — composition tolerates its absence by registering nothing, so M1-c is testable standalone with an in-test tool).
- Environment setup required: `sse-starlette` (or FastAPI native SSE) dependency for the streaming endpoint. Off-hardware testable via FastAPI `TestClient` + fakes; no on-hardware gate for the surfaces themselves (live model is M1-b's gated task).

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| /Users/artemis-build/artemis/src/artemis/gateway.py | create | `Gateway`: attaches single-owner scope/PersonId → calls Brain; `compose_brain()` wiring helper |
| /Users/artemis-build/artemis/src/artemis/api.py | create | FastAPI `APIRouter` with `POST /ask` (JSON) + `GET/POST /ask/stream` (SSE) over the Gateway |
| /Users/artemis-build/artemis/src/artemis/cli.py | create | dev CLI: stdin prompt loop → Gateway → prints streamed answer |
| /Users/artemis-build/artemis/src/artemis/main.py | modify | `include_router` the M1-c api router; build the shared Gateway at app startup |
| /Users/artemis-build/artemis/tests/test_gateway_surfaces.py | create | gateway scope-attach + `/ask` + `/ask/stream` via TestClient with a fake Brain |

## Tasks
- [ ] Task 1: Implement the Gateway + composition helper — files: `/Users/artemis-build/artemis/src/artemis/gateway.py` — define `OWNER_PERSON_ID: PersonId` (a fixed constant, e.g. `PersonId("owner")`) and `OWNER_SCOPE: Scope = "owner-private"`. `class Gateway` constructed with a `Brain`. `async def handle_text(self, request_text: str) -> BrainResponse`: attach the single-owner scope (M1 stub — log that scope resolution is stubbed) and call `await self.brain.respond(request_text, OWNER_SCOPE)`. Add `async def handle_text_stream(self, request_text: str) -> AsyncIterator[str]`: for M1, yield the final answer text as a single chunk (wraps `handle_text`); structured so the responder's real token stream slots in later. Add `def pre_route(self, request_text: str) -> str | None` (cross-milestone, consumed by M5-c's `handle_voice`): delegate to `self.brain.pre_route(request_text, OWNER_SCOPE)` so the voice surface can classify the Tier pre-serve through the same single-owner scope seam. Add `def compose_brain(settings: Settings) -> Brain`: build `OpenAIEmbeddingModel` + `OpenAIModelPort` (M1-b adapters), a `ToolRegistry` (M1-a) with those, register modules (call `artemis.tools.time_tool.manifest()` from M1-d if importable — wrap in a try/except ImportError that registers nothing, so M1-c stands alone), build a `SemanticRouter`, return a `Brain`. — done when: `uv run mypy --strict src` passes and `compose_brain(get_settings())` returns a `Brain` without contacting any network (adapters are lazy; no call made at construction).

- [ ] Task 2: Implement the streaming HTTP API router — files: `/Users/artemis-build/artemis/src/artemis/api.py` — `router = APIRouter()`. Pydantic request model `AskRequest {text: str}` and response model `AskResponse {text: str, path: str, tool_used: str | None, escalated: bool}`. `POST /ask` (`async def`): get the app's shared `Gateway` (via a dependency reading `request.app.state.gateway`), `r = await gateway.handle_text(req.text)`, return `AskResponse(**r as dict)`. `GET /ask/stream` + `POST /ask/stream` (`async def`): return an SSE `StreamingResponse` (media type `text/event-stream`) that iterates `gateway.handle_text_stream(text)` yielding `data: <chunk>\n\n` frames, then a terminal `data: [DONE]\n\n`. Bind nothing to a public host — the app already binds `127.0.0.1` via the M0-b daemon. — done when: `uv run mypy --strict src` passes.

- [ ] Task 3: Implement the dev CLI — files: `/Users/artemis-build/artemis/src/artemis/cli.py` — a `main() -> None` entry: build the Gateway via `compose_brain(get_settings())`, then a stdin REPL loop (`while True: read a line; on EOF/"/quit" exit 0`); for each line run the async `gateway.handle_text_stream` (drive the async iterator from sync via `asyncio.run`/`anyio`) and print each chunk to stdout as it arrives; print the path/tool/escalated as a dim footer line. Register a `[project.scripts]` console entry `artemis = "artemis.cli:main"` in `pyproject.toml` (modify pyproject — note: this is a 6th file touched; justified — the CLI is unusable without its entry point; alternatively invoke via `uv run python -m artemis.cli` and add `if __name__ == "__main__": main()` to avoid touching pyproject — PREFER the `python -m` form to keep the file count at the spec's set and avoid a pyproject edit). — done when: `uv run python -m artemis.cli` starts, accepts a typed line, prints an answer, and exits 0 on `/quit`.

- [ ] Task 4: Wire the api router + shared Gateway into the brain app — files: `/Users/artemis-build/artemis/src/artemis/main.py` — additive only: import the M1-c `router` and `compose_brain`/`Gateway`; in a FastAPI startup hook (`@app.on_event("startup")` or a lifespan) build the shared `Gateway` and store it on `app.state.gateway`; `app.include_router(router)`. Do NOT alter the existing `/healthz`/`/readyz` handlers. — done when: `uv run mypy --strict src` passes and `TestClient(app)` exposes `/ask` + `/ask/stream` alongside the unchanged `/healthz`.

- [ ] Task 5: Write the gateway + surfaces tests — files: `/Users/artemis-build/artemis/tests/test_gateway_surfaces.py` — typed pytest. Build a `FakeBrain` whose `respond` returns a fixed `BrainResponse(text="42 o'clock", path="deterministic", tool_used="time.get_current_time", escalated=False)`. Override `app.state.gateway` with a `Gateway(FakeBrain())` (or a dependency override). Tests via FastAPI `TestClient`:
  - gateway scope-attach: `await Gateway(FakeBrain()).handle_text("hi")` returns the fixed response (and the FakeBrain asserts it received `OWNER_SCOPE`).
  - gateway pre_route passthrough: `Gateway(FakeBrain()).pre_route("hi")` returns the FakeBrain's fixed candidate id (FakeBrain.pre_route returns `"time.get_current_time"`), confirming the M5-c seam delegates through `OWNER_SCOPE`.
  - `POST /ask` returns 200 with `{"text":"42 o'clock","path":"deterministic","tool_used":"time.get_current_time","escalated":false}`.
  - `POST /ask/stream` returns `text/event-stream`, the body contains `data: 42 o'clock` and a terminal `data: [DONE]`.
  - `/healthz` still returns 200 (regression: M1-c did not break M0-b).
  — done when: `uv run pytest -q` passes AND `uv run mypy --strict src tests/test_gateway_surfaces.py` passes.

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | /Users/artemis-build/artemis/src/artemis/gateway.py, /Users/artemis-build/artemis/src/artemis/api.py, /Users/artemis-build/artemis/src/artemis/cli.py, /Users/artemis-build/artemis/tests/test_gateway_surfaces.py |
| Modify | /Users/artemis-build/artemis/src/artemis/main.py |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv add sse-starlette` | SSE streaming dependency (or use FastAPI native `StreamingResponse`) |
| `uv run mypy --strict src tests/test_gateway_surfaces.py` | Type gate |
| `uv run ruff check . ; uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q` | Test gate (TestClient surfaces) |
| `uv run python -m artemis.cli` | Manual smoke of the dev CLI |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | src/artemis/gateway.py, src/artemis/api.py, src/artemis/cli.py, src/artemis/main.py, tests/test_gateway_surfaces.py, pyproject.toml, uv.lock |
| `git commit` | "feat: M1-c gateway (single-owner stub) + dev CLI + loopback SSE streaming API" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_ENV_FILE` | Slot Settings the composition resolves adapters/ports from |

### Network
| Action | Purpose |
|--------|---------|
| `uv add sse-starlette` | Package install (PyPI) |
| (no outbound at runtime) | API binds `127.0.0.1` via the M0-b daemon; Brain's model calls are M1-b's concern |

## Specialist Context
### Security
The Gateway is the single point that attaches scope BEFORE the Brain — brain.md's hard ordering. In M1 it attaches a fixed owner scope (single-owner stub); the seam is real so M2 drops in voice-ID/login + guest least-privilege without changing the Brain. The API binds loopback only (no public listener — overview "remote via private tunnel later"). [FLAG apex-security at M2: replace the constant owner scope with real per-person resolution + the guest wall before any non-owner can reach a surface.]

### Performance
SSE streams the answer so TTFT is masked (brain.md "stream tokens; instant ack masks TTFT"). M1 emits the answer as available; per-token streaming activates when the responder adapter streams.

### Accessibility
(none — text CLI + machine API; no rendered UI in M1. The eventual chat app surface carries a11y at M-app.)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | src/artemis/gateway.py, src/artemis/api.py, src/artemis/cli.py | Type + docstring all exports; document the single-owner-stub scope attach + the SSE frame contract |

## Acceptance Criteria
- [ ] Run `uv run mypy --strict src tests/test_gateway_surfaces.py` → verify: exit 0.
- [ ] Run `uv run pytest -q tests/test_gateway_surfaces.py` → verify: `/ask` returns the fixed JSON; `/ask/stream` is `text/event-stream` containing the answer + `[DONE]`; `/healthz` still 200; the gateway attaches `OWNER_SCOPE`.
- [ ] Run `printf 'what time is it\n/quit\n' | uv run python -m artemis.cli` → verify: prints an answer line then exits 0 (uses the in-composition tool or, absent a model, the escalation/local stub — exit 0 either way).
- [ ] Run `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.

## Progress
_(Coding mode writes here — do not edit manually)_
