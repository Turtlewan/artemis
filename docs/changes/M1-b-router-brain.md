---
spec: m1-b-router-brain
status: ready
token_profile: balanced
autonomy_level: L2
---
<!-- amended 2026-06-11 per contracts.md (Seam 1) + m0-m1-foundation-brain.md BLOCKs B2, B3, B7, B11, F11 -->
<!-- amended 2026-06-17: EmbeddingModel port split embed→embed_documents/embed_query (embedding-layer decision; research/2026-06-17-embedding-implementation.md) -->

# Spec: M1-b — Embedding-based semantic Router + Brain reactive loop (router-first; responder path; escalation stub)

**Identity:** Implements the `Router` port as an embedding-based semantic router (Qwen3-Embedding-0.6B via the `EmbeddingModel`/`ModelPort` seam) that classifies a request into a candidate tool set + path, plus the small router-first Brain reactive loop that dispatches the deterministic/tool path, calls the Qwen3-4B responder with constrained decoding for tool-call args, and stubs escalation.
→ why: see docs/technical/architecture/brain.md § "Routing — router-first (the frugality core)" + § "Inference + models" (responder Qwen3-4B + Outlines constrained decoding) + § "Shape — thin custom orchestrator".

<!-- Split rule: TWO logical phases (1: the Router; 2: the Brain loop) and 3 src files + 1 test. At the 2-phase / borderline-files limit. Kept together because the Brain loop's only non-trivial collaborator is the Router it drives, and the end-to-end loop test is the proof of both; splitting would leave the Router untested against a consumer. If review wants leaner: sub-split into M1-b1 (Router) and M1-b2 (Brain loop). Flagged per rules. M1-a provides the registry the Router queries; M1-d provides the concrete tool + an OpenAI-compatible ModelPort adapter is assumed (see Assumptions). -->

## Assumptions
- M0-a + M0-d + M1-a complete: `config`/`paths`, `ports` (`Router`, `RouteDecision`, `ModelPort`, `ModelResponse`, `EmbeddingModel`, `Scope`), and `ToolRegistry`/`retrieve_tools` exist. → impact: Stop (the Router consumes the registry; the Brain consumes the Router + ModelPort; signatures must match M0-d/M1-a exactly).
- A concrete OpenAI-compatible `ModelPort` adapter (responder via mlx-openai-server) and a concrete `EmbeddingModel` adapter (embedder via mlx-openai-server) are needed for live use, but **M1-b depends only on the ports** and is fully testable with fakes. The concrete adapters are created in **this spec, Task 5 (gated, on-hardware probe)** as a thin wrapper over the M0-c `model_client` base-URL seam. → impact: Caution (off-hardware everything passes against fakes; the live adapter probe is gated).
- The `OpenAIModelPort` resolves ANY openai-adapter role generically via the M0-c base-URL seam (`base_url_for_role`/`model_id_for_role`) — NOT hardcoded to responder/embedder. This includes `sensitive_reasoner` (Qwen3.6-27B, openai adapter, mlx lazy), which does sensitive reasoning + sensitive memory extraction. M4-b calls `model.complete(role="sensitive_reasoner", ...)` through this same adapter, no special-casing. The adapter raises `NotImplementedError` ONLY for `claude-cli` (teacher). → impact: Stop.
- Constrained decoding: the `ModelPort.complete(..., response_schema=...)` seam (M0-d) carries the schema. The adapter maps `response_schema` → the OpenAI request body field `response_format={"type":"json_schema","json_schema":{"name":...,"schema":response_schema,"strict":true}}` (B11: Outlines constrains at the *logits* level inside the inference server, not in the HTTP client; the client only passes the JSON-schema via `response_format`; `uv add outlines` belongs to the server install M0-c, NOT M1-b — drop it from M1-b's Commands). No validate-retry loop — no manual JSON-parse-and-retry; the schema seam is the contract. → impact: Stop.
- The escalation path (local teacher / cloud) is a **STUB** in M1: when the Router returns `path="escalate"`, the Brain returns a fixed `ESCALATION_NOT_AVAILABLE` typed response (no teacher call). → impact: Low (escalation is M3+; the stub keeps the loop total).
- The Router is **semantic via centroid/prototype matching**: each registered tool contributes its embedded description as a prototype; the request embedding's max cosine to any tool prototype decides `local`-with-candidates vs `deterministic` vs `escalate` via two thresholds. Thresholds are config-tunable with documented M1 defaults. → impact: Caution. M1 default thresholds (drafted defaults, GATED for empirical confirm at Task 5): `route_deterministic_threshold = 0.6`, `route_local_threshold = 0.35`, `route_escalate_floor = 0.15`. Constructor args; do not change code shape; confirm empirically on-hardware at Task 5.

Simplicity check: considered a trained classifier head or an LLM-based router — rejected; brain.md locks an *embedding-based* router (~3–7ms CPU, zero LLM tokens). Centroid/cosine over the same tool embeddings the registry already holds is the minimum that reuses M1-a's index and adds no model. Considered making the Brain a framework graph (LangGraph) — rejected by brain.md "thin custom orchestrator, no heavyweight framework". A small reactive function is the minimum.

## Prerequisites
- Specs that must be complete first: M0-a (config/paths/mypy), M0-c (`model_client` base-URL seam), M0-d (`Router`/`RouteDecision`/`ModelPort`/`EmbeddingModel`/`Scope` ports), M1-a (`ToolRegistry`/`retrieve_tools`/`get_tool`/manifest models).
- Environment setup required: `outlines` + an OpenAI-compatible client dependency for the live adapter (added in Task 5). Off-hardware logic is deterministic against fakes; **the live responder/embedder adapter probe is GATED on-hardware (needs M0-c models served).**

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| /Users/artemis-build/artemis/src/artemis/router.py | create | `SemanticRouter` implementing the `Router` port (cosine over tool prototypes → `RouteDecision`) |
| /Users/artemis-build/artemis/src/artemis/brain.py | create | `Brain` reactive loop: route → dispatch tool (constrained decoding for args) → responder → escalation stub |
| /Users/artemis-build/artemis/src/artemis/adapters/model_adapters.py | create | thin `OpenAIModelPort` + `OpenAIEmbeddingModel` adapters over the M0-c base-URL seam (Outlines for constrained decode) |
| /Users/artemis-build/artemis/src/artemis/config.py | modify | add `embedding_dimension: int = 1024` field to the M0-a `Settings` (consumed by `OpenAIEmbeddingModel.dimension`) |
| /Users/artemis-build/artemis/tests/test_router_brain.py | create | router classification + end-to-end Brain loop against fakes (the M1 end-to-end-brain proof minus surfaces) |

## Tasks
- [ ] Task 1: Implement the semantic Router — files: `/Users/artemis-build/artemis/src/artemis/router.py` — `class SemanticRouter` structurally satisfying `artemis.ports.Router`. Constructed with a `ToolRegistry` (M1-a) + an `EmbeddingModel` + three thresholds (defaults per the M1 default thresholds in Assumptions above, accepted as constructor args). `async def route(self, request_text: str, scope: Scope) -> RouteDecision` (ASYNC — ADR-015: `Router.retrieve`-tier calls are async because `retrieve_tools_scored` now `await`s the embedder; the M0-d `Router` port `retrieve` is async, so `route` conforms):
  1. `await registry.retrieve_tools_scored(request_text, k=3)` (B3: use the new scored method added to M1-a Task 3 — this avoids touching `registry.py` internals and gives the top cosine score directly; do NOT re-search the index separately; ADR-015: `retrieve_tools_scored` is async). Extract the `fq_ids` list and the `top_score` from the first tuple (or 0.0 if empty).
  2. decide `path`: top score ≥ `deterministic_threshold` → `"deterministic"` (single confident tool); ≥ `local_threshold` → `"local"` (responder with candidate tools); < `escalate_floor` → `"escalate"`; otherwise `"local"`.
  3. return `RouteDecision(path=..., candidate_tools=<fq ids>, confidence=<top score>)` using the M0-d frozen dataclass exactly.
  (B7) If `await retrieve_tools_scored` raises (e.g. embedder connection failure), catch the exception, log a warning, and return `RouteDecision(path="escalate", candidate_tools=[], confidence=0.0)` — degrade-don't-crash so the CLI acceptance test passes even with a dead embedder.
  Add a static `_check: Router = SemanticRouter(...)`-style type assertion in the test (Protocol structural check still holds with the async `route`). — done when: `uv run mypy --strict src` passes.

- [ ] Task 2: Implement the Brain reactive loop — files: `/Users/artemis-build/artemis/src/artemis/brain.py` — `class Brain` constructed with a `Router`, a `ToolRegistry`, and a `ModelPort`. Define a frozen `BrainResponse` dataclass `{text: str, path: str, tool_used: str | None, escalated: bool}`. `async def respond(self, request_text: str, scope: Scope) -> BrainResponse`:
  - `decision = await router.route(request_text, scope)` (ADR-015: `route` is async).
  - if `decision.path == "escalate"`: return `BrainResponse(text="ESCALATION_NOT_AVAILABLE", path="escalate", tool_used=None, escalated=True)` (the M1 stub — no teacher call).
  - if `decision.candidate_tools`: pick the top candidate; `spec = registry.get_tool(fq)`; build the tool-call args by calling `await model.complete(role="responder", messages=[...], response_schema=spec.args_json_schema())` (Seam 1: `complete` is async; constrained decoding via the adapter — NO manual retry); validate the returned text into `spec.args_schema` (`model_validate_json`); `await spec.callable_ref(args_model)` to get the typed return (ADR-016: `callable_ref` is `async def`); render a final answer string from the return model (in M1, use a template `f"{return_model}"`-style deterministic render to keep the loop cheap and avoid a second model call; document this). Return `BrainResponse(text=<rendered>, path=decision.path, tool_used=fq, escalated=False)`.
  - if no candidate tools and `path == "local"`: call `await model.complete(role="responder", messages=[{"role":"user","content":request_text}])` (Seam 1: async; free-form, no schema) and return its text with `tool_used=None`.
  - Wrap tool dispatch in a try/except that degrades to a typed `BrainResponse(text="TOOL_ERROR", ...)` (degrade-don't-crash, brain.md) — log the exception, never raise out of `respond`.
  - (cross-milestone back-fill, consumed by M5-d) `async def respond_stream(self, request_text: str, scope: Scope) -> AsyncIterator[str]`: yields text segments. Determine the path via `decision = await router.route(request_text, scope)` (ADR-015: `route` is async). For the free-form responder path, call `model.complete_stream(role="responder", messages=[...])` (Seam 1: call `complete_stream`, NOT `complete(stream=True)` — `complete` has no `stream` param in the Seam 1 interface) and yield each text segment as it arrives; for the tool path and the escalation stub, yield the rendered answer as ONE segment. Same degrade-don't-crash contract as `respond`.
  - (cross-milestone back-fill, consumed by M5-c) `async def pre_route(self, request_text: str, scope: Scope) -> str | None`: ASYNC (ADR-015: `await router.route(request_text, scope)` because `route` is now async). Reuse `await router.route(request_text, scope)` and return the top `candidate_tools` id (the candidate module/tool) BEFORE serving, so the Gateway can classify the Tier pre-serve and withhold sensitive data. Return `None` when there is no candidate (escalate/no-match). No model call — routing only.
  — done when: `uv run mypy --strict src` passes; `respond` is `async` and never raises for the three paths; `respond_stream` yields ≥1 segment for each path; `pre_route` is `async` and returns the top candidate id or `None`.

- [ ] Task 3: Implement the OpenAI-compatible ModelPort + EmbeddingModel adapters — files: `/Users/artemis-build/artemis/src/artemis/adapters/model_adapters.py` (create `src/artemis/adapters/__init__.py` too if absent) — `class OpenAIModelPort` satisfying `artemis.ports.ModelPort` (Seam 1): constructed from `Settings`; resolves the per-role base URL via M0-c `model_client.base_url_for_role` and model id via `model_id_for_role`. `async def complete(self, *, role, messages, response_schema=None, temperature=0.7, max_tokens=None)` calls the OpenAI-compatible `/v1/chat/completions`; when `response_schema` is provided, map it to `response_format={"type":"json_schema","json_schema":{"name":"response","schema":response_schema,"strict":true}}` in the request body (B11: Outlines constrains at the logits level inside mlx-openai-server — the client only passes the schema via `response_format`; do NOT `uv add outlines` in M1-b); returns `ModelResponse` with `origin="local"` and `model_id=<resolved model id>` (Seam 1: `ModelResponse` has `origin` + `model_id`). **No `stream` param on `complete`** — there is no `stream=` parameter on `complete` per Seam 1. `def complete_stream(self, *, role, messages, temperature=0.7) -> AsyncIterator[str]` calls `/v1/chat/completions` with `stream=True` and yields text delta chunks. Resolve any openai-adapter role generically (responder, embedder, `sensitive_reasoner`) via `base_url_for_role`/`model_id_for_role`; raise `NotImplementedError` ONLY for a `claude-cli` role. Do NOT hardcode an allowlist of role names. `class OpenAIEmbeddingModel` satisfying `artemis.ports.EmbeddingModel`: implements BOTH `async def embed_documents(self, texts) -> list[Vector]` (ADR-015: async — network I/O) which `await`s `/v1/embeddings` for the `embedder` role on the RAW texts with **NO instruction prefix** (Qwen3-Embedding: "no instruction for retrieval documents"), and `async def embed_query(self, query) -> Vector` (async) which applies the Qwen3-Embedding query instruction prefix — wrap the query as `f"Instruct: {task}\nQuery:{query}"` (default `task` = "Given a search query, retrieve relevant passages") BEFORE the `/v1/embeddings` call, then `await` it and return the single `Vector` (list in/out internally, return `result[0]`). The asymmetric prefix is applied HERE in the adapter, not in any caller or store (the silent ~1–5% retrieval-quality footgun — see docs/research/2026-06-17-embedding-implementation.md §6). `dimension` property STAYS sync, returns the configured embedder dimension (add field `embedding_dimension: int = 1024` to the M0-a `Settings` in `/Users/artemis-build/artemis/src/artemis/config.py` for Qwen3-Embedding-0.6B; do NOT use the lazy-first-call probe so M3/M4's LanceDB schema has a stable value to trust — deferred decision R5 resolved here). Add `uv add httpx` or `uv add openai` unconditionally in Task 3 with a lazy import inside the adapter (F11: the conditional dep gating "IF the off-hardware suite can run" is executor-hostile — add the HTTP client unconditionally). Both bind only `127.0.0.1` endpoints from Settings. — done when: `uv run mypy --strict src` passes (the live calls are exercised only in the gated Task 5).

- [ ] Task 4: Write the router + brain tests (the end-to-end brain proof, surfaces excluded) — files: `/Users/artemis-build/artemis/tests/test_router_brain.py` — typed pytest using `FakeEmbedder` (reuse the M1-a test pattern — deterministic hash-based embedding so "what time is it" is closest to the time tool's description; implements BOTH `async def embed_documents(self, texts) -> list[Vector]` and `async def embed_query(self, query) -> Vector` per the split port, `dimension` stays sync) and a `FakeModelPort` that satisfies the Seam 1 `ModelPort` protocol. Async tests are `async def` + `@pytest.mark.anyio` (match the M1-a convention; if no async runner is configured in the spec set, coding mode configures `anyio`/`pytest-asyncio` — flag if absent): `async def complete(self, *, role, messages, response_schema=None, temperature=0.7, max_tokens=None) -> ModelResponse` returns, when given a `response_schema`, a `ModelResponse(text=<JSON valid for that schema>, finish_reason="stop", usage=Usage(...), origin="local", model_id="fake-model")`, and free-form text `ModelResponse` otherwise. `def complete_stream(self, *, role, messages, temperature=0.7) -> AsyncIterator[str]` yields fixed text segments (async generator). Register a manifest with the M1-d-style time tool (use a minimal in-test `ToolSpec` with bare `name="get_current_time"` — Seam 2; fq id = `"time.get_current_time"` — if M1-d not yet built — args schema `{tz: str}`, return schema `{iso: str}`, callable is an `async def` that returns a fixed time — ADR-016: every `callable_ref` is `async def`). Tests:
  - router (`async def`, `@pytest.mark.anyio`): `await router.route("what time is it", scope)` returns `path` in `{"deterministic","local"}` with the time tool in `candidate_tools`; `await router.route("asdfqwer zzz", scope)` (no match) returns `path == "escalate"` (below floor).
  - brain tool path: `await brain.respond("what time is it", scope)` returns `tool_used == "<module>.get_current_time"`, `escalated is False`, and `text` contains the fixed time the fake callable produced.
  - brain escalation stub: a no-match request returns `text == "ESCALATION_NOT_AVAILABLE"`, `escalated is True`.
  - brain degrade: a `ToolSpec` whose `callable_ref` is an `async def` that raises (ADR-016) → `respond` returns `text == "TOOL_ERROR"` and does NOT raise.
  - brain stream: `await`-iterate `respond_stream("what time is it", scope)` yields ≥1 segment; the concatenation of segments contains the fixed time (`FakeModelPort.complete_stream` yields fixed segments — Seam 1: `respond_stream` calls `complete_stream`, not `complete(stream=True)`).
  - brain pre_route: `await brain.pre_route("what time is it", scope)` returns the time tool fq id; `await brain.pre_route("asdfqwer zzz", scope)` returns `None` (ADR-015: `pre_route` is async).
  - static port conformance: `_r: Router = SemanticRouter(...)` type-checks under mypy.
  — done when: `uv run pytest -q` passes AND `uv run mypy --strict src tests/test_router_brain.py` passes.

- [ ] Task 5 (GATED — on-hardware): Live responder + embedder probe through the real adapters — files: (no repo files; uses Task 3 adapters + M0-c served models) — on the Mini with mlx-openai-server serving Qwen3-4B + Qwen3-Embedding-0.6B: instantiate `OpenAIModelPort`/`OpenAIEmbeddingModel` from dev Settings, run `Brain.respond("what time is it")` through the real responder (the server applies Outlines constrained decoding server-side via `response_format`), confirm the tool-call args validate against the schema first-try (no retry) and the time tool fires. Build-time empirical (needs served models + MLX). — done when: on the Mini, a live `respond("what time is it")` returns the current time via the constrained-decoded tool call with zero schema-validation retries.

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | /Users/artemis-build/artemis/src/artemis/router.py, /Users/artemis-build/artemis/src/artemis/brain.py, /Users/artemis-build/artemis/src/artemis/adapters/__init__.py, /Users/artemis-build/artemis/src/artemis/adapters/model_adapters.py, /Users/artemis-build/artemis/tests/test_router_brain.py |
| Modify | /Users/artemis-build/artemis/src/artemis/config.py |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv add httpx` | HTTP client for OpenAI-compatible calls (or `uv add openai`; add unconditionally with lazy import — B11/F11: `uv add outlines` belongs to the server install M0-c, not M1-b) |
| `uv run mypy --strict src tests/test_router_brain.py` | Type gate |
| `uv run ruff check . ; uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q` | Test gate (router + brain against fakes) |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | src/artemis/router.py, src/artemis/brain.py, src/artemis/adapters/**, src/artemis/config.py, tests/test_router_brain.py, pyproject.toml, uv.lock |
| `git commit` | "feat: M1-b semantic router + router-first brain loop + OpenAI ModelPort adapter (Outlines)" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_ENV_FILE` | Slot Settings the adapters resolve role→endpoint from |

### Network
| Action | Purpose |
|--------|---------|
| `uv add httpx` (or `uv add openai`) | Package install (PyPI) — `uv add outlines` is NOT run in M1-b (server-side via M0-c) |
| local `127.0.0.1` calls to mlx-openai-server (GATED) | Live responder/embedder inference |

## Specialist Context
### Security
The Brain only ever sees the relevant handful of tools (RAG-for-tools from M1-a) — all tools stay OUT of the model context. Adapters bind `127.0.0.1` only. The escalation path is a stub — no cloud/teacher egress happens in M1 (the sensitivity router that would gate it is a later milestone). [FLAG apex-security at M3: the escalation stub must be replaced behind the sensitivity/provenance gate before any cloud call is wired.]

### Performance
Router is embedding-cosine only (zero LLM tokens, brain.md ~3–7ms target). The tool path renders the answer from the typed return model deterministically (no second model call) to keep M1 cheap; constrained decoding (Outlines) removes the validate-retry loop. Responder kept warm is an M0-c/runtime concern, not M1-b.

### Accessibility
(none — no frontend)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | src/artemis/router.py, src/artemis/brain.py, src/artemis/adapters/model_adapters.py | Type + docstring all exports; document the three router paths + the constrained-decode no-retry contract |

## Acceptance Criteria
- [ ] Run `uv run mypy --strict src tests/test_router_brain.py` → verify: exit 0 (incl. `Router`/`ModelPort`/`EmbeddingModel` structural assertions).
- [ ] Run `uv run pytest -q tests/test_router_brain.py` → verify: router classifies the time query with the time tool as candidate; brain tool path returns the fixed time with `escalated is False`; no-match returns `ESCALATION_NOT_AVAILABLE`; a raising callable yields `TOOL_ERROR` without raising; `respond_stream` yields ≥1 segment containing the time; `await pre_route` returns the time tool id and `None` for no-match.
- [ ] Run `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.
- [ ] (GATED, on Mini) Live `Brain.respond("what time is it")` via `OpenAIModelPort` + served Qwen3-4B → verify: returns the current time via a constrained-decoded tool call with zero schema-validation retries.

## Progress
_(Coding mode writes here — do not edit manually)_
