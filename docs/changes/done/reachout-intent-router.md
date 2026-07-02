---
spec: reachout-intent-router
status: ready
token_profile: balanced
autonomy_level: L2
coder_model: codex
coder_effort: high
cross_model_review: true
---

# Spec: R3 — brain-side intent router + Ask wiring (Haiku classifier)

**Identity:** A transport-agnostic brain-side intent classifier (Haiku) that labels an incoming
message as `build` / `web_q` / `aggregate` / `plain_ask`, wired into `/app/ask` so a question
routes to the right handler. Unifies the entry point for Ask (and, later, Telegram via R4).
→ why: ADR-035 #3 (reach-out router arc); confirm-on-expensive per ADR-012.

## Assumptions
- `/app/ask` currently does a plain `model.complete` (ask_routes.py `_answer`); AskResponse already
  carries `path` + `tool_used` fields the client reads → wiring the router in needs no DTO change →
  impact: Low
- `build_web_tool(*, tavily_api_key: str)` exists (web_tool.py) and returns a `WebTool` with
  `async answer(query) -> WebAnswer(answer, sources)` → web_q executes via it → impact: Caution
  (needs `TAVILY_API_KEY`; absent → graceful fallback to plain_ask, never a crash)
- `ModelPort.complete(response_schema=...)` returns schema-valid JSON (the fence fix landed) →
  the Haiku classifier can use structured output → impact: Low
- The gated capability BUILD flow (propose→build→promote) already lives client-side (askStore, CB-4)
  and over `/app/capabilities/*`; R3 does NOT execute a build — it only DETECTS build intent and
  signals it → impact: Low

Simplicity check: considered a keyword/heuristic classifier — rejected; a small Haiku call
generalises to Telegram phrasing (R4) and is cheap. Considered auto-running aggregate — rejected;
the aggregation pipeline (ADR-035 #4) is not built, so aggregate returns a signal, not execution.

## Design decisions (conservative calls — flag for owner review)
- **web_q auto-executes inline.** A single search→answer is not "expensive" under ADR-012, so it
  runs without a confirm gate. `aggregate` and `build` do NOT auto-execute (deferred / client-gated).
- **aggregate is a signal, not execution** (pipeline not built): returns `path="aggregate"` + a
  short message telling the user to ask a direct question meanwhile. No fallback that silently
  reinterprets intent.
- **build is a signal** (`path="build"`): the client's existing build-mode machinery handles the
  gated flow; R3 does not call the forge.
- **No TAVILY_API_KEY** → web_q degrades to a plain_ask answer with a one-line note (never a 500).

## Prerequisites
- Specs complete first: none (web tool + fence fix already in main)
- Environment: `uv sync`; `TAVILY_API_KEY` in env for a live web_q smoke (optional; hermetic tests mock it)

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| src/artemis/intent.py | create | `Route` enum/literal + `Intent` model + `IntentRouter.classify(text) -> Intent` (Haiku via ModelPort, structured output, transport-agnostic) |
| src/artemis/api/ask_routes.py | modify | classify first; route plain_ask→completion (current), web_q→WebTool.answer, build/aggregate→signal; populate AskResponse.path/tool_used |
| tests/api/test_ask_routes.py | modify | add router tests (mock classifier + mock WebTool): each route returns the right path/tool_used; no-key web_q degrades; a @pytest.mark.live real web_q smoke (docstring command) |

## Tasks
- [ ] Task 1: Intent classifier — files: src/artemis/intent.py — done when: `IntentRouter(model).classify("who won the 2022 world cup")` returns `Intent(route="web_q", ...)` and a build phrasing returns `route="build"`, using a Haiku `model.complete(response_schema=...)` call; `Route = Literal["build","web_q","aggregate","plain_ask"]`; `Intent` = {route, confidence: float, reason: str}. Prompt instructs: build=asking Artemis to CREATE/make a capability/tool; web_q=a factual question needing current web info; aggregate=a broad multi-source research/summary ask; plain_ask=everything else (chat, reasoning, no external data). mypy clean.
- [ ] Task 2: Wire the router into /app/ask (+ /ask/stream) — files: src/artemis/api/ask_routes.py — done when: `ask()` classifies, then: plain_ask → current `_answer` (path="local"/"codex" engine tag); web_q → `build_web_tool(tavily_api_key=os.environ.get("TAVILY_API_KEY",""))` .answer, AskResponse(text=answer, path="web", tool_used="web"); build → AskResponse(text="<short: opening build mode>", path="build", tool_used=None); aggregate → AskResponse(text="<short: deep research not available yet>", path="aggregate"). Missing/empty TAVILY_API_KEY on web_q → fall back to `_answer` with a "(couldn't search; answering directly)" prefix, path="local". The IntentRouter is constructed from `app.state.model` (add a `_intent(request)` dep mirroring `_router`). `/ask/stream` uses the same routing (stream the resulting text). mypy clean.
- [ ] Task 3: Tests — files: tests/api/test_ask_routes.py — done when: `uv run pytest tests/api/test_ask_routes.py -q` passes. Cover (classifier + WebTool both mocked/stubbed at the seam): (a) each of the 4 routes yields the correct `path`/`tool_used`; (b) web_q with no TAVILY_API_KEY degrades to a plain answer (path="local", note prefix); (c) a `@pytest.mark.live` test with a docstring runnable command doing a REAL web_q through /app/ask (host runs once).

## Wave plan
Wave 1: [Task 1] | Wave 2: [Task 2] | Wave 3: [Task 3]

## Permissions
### File Operations
| Action | Paths |
|--------|-------|
| Create | src/artemis/intent.py |
| Modify | src/artemis/api/ask_routes.py, tests/api/test_ask_routes.py |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run pytest tests/api/test_ask_routes.py -q` | route unit tests |
| `uv run mypy` | typecheck (full project) |
| `uv run ruff check src tests` | lint |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | src/artemis/intent.py src/artemis/api/ask_routes.py tests/api/test_ask_routes.py |
| `git commit` | "feat: R3 brain-side intent router + Ask wiring" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `TAVILY_API_KEY` | web_q execution (optional; graceful fallback if absent) |

### Network
| Action | Purpose |
|--------|---------|
| web_q route (real run) | Tavily search + guarded fetch via build_web_tool; default suite mocks it |

## Specialist Context
### Security
- The classifier sees raw user text (trusted owner input via a session-gated route) — not web
  content — so no injection-quarantine concern at the classify step. web_q execution reuses the
  existing quarantined WebTool untouched. No new egress path beyond the existing web tool.
- Session gate (`require_session`) stays on all /ask routes.

### Performance
Haiku classify adds one cheap call before routing. web_q is heavier by design (search+fetch+read+
synth) but is the requested behavior; not in the default test path (mocked).

### Accessibility
(none — no new frontend this spec)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | src/artemis/intent.py | docstrings on IntentRouter + Intent |

## Acceptance Criteria
- [ ] Classifier labels the 4 routes → verify: Task 1 unit asserts web_q + build phrasings
- [ ] /ask routes correctly → verify: Task 3 asserts path/tool_used per route
- [ ] web_q degrades without a key → verify: Task 3 no-key test
- [ ] Full gate green → verify: `uv run mypy` + `uv run ruff check src tests` + `uv run pytest -q` exit 0 (live test excluded)
- [ ] Real web_q works → verify: the @pytest.mark.live test (host runs once, records output)

## Progress
_(Coding mode writes here — do not edit manually)_
