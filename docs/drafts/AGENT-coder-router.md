---
spec: AGENT-coder-router
status: draft
cross_model_review: false
token_profile: balanced
autonomy_level: L2
---

# Spec: AGENT-coder-router — pluggable coder backend router (LiteLLM)

**Identity:** The per-task coder-model router (ADR-031 D/E): selects a coder backend (Codex / DeepSeek
/ GLM / Ollama) by cost+capability and returns an OpenHands-compatible `LLM` config, via LiteLLM.
Coding is not privacy-constrained (cloud backends acceptable for code).
<!-- → why: docs/technical/adr/ADR-031-...md (D pluggable backend, E models/budget; Refinement 2026-06-26 LiteLLM) + docs/drafts/AGENT-engine-design.md (seam #5 router). -->

## Assumptions
<!-- Coding mode verifies each item against the codebase before executing. -->
- OpenHands' `LLM` is configured via LiteLLM model strings (`LLM(model=, api_key=, base_url=)`) — verified by the 2026-06-26 research (`docs/research/2026-06-26-openhands-windows/README.md`). The router produces that config; it does NOT call the model itself. → impact: Stop (the router is config, not a client).
- `litellm` is a NEW dependency in the `[agentic]` optional group (with `openhands-sdk`). Verify the current package name + maintained version at build (typosquat/maintenance). → impact: Stop.
- Backend selection is policy-driven from `RuntimeConfig` (a coder-routing table: task-class/cost → model string + endpoint env-ref), defaults-in-code/overrides-in-policy (mirror the existing `RuntimeConfig` pattern in `src/artemis/runtime_config.py`). API keys are env-refs, never literals. → impact: Stop (hardcoded keys = secret leak).
- Coding is non-sensitive (ADR-031 D) — cloud coder backends are allowed; the router does NOT apply the ADR-022 sensitivity wall (that governs the driving/reasoning model, not the coder). → impact: Caution (document this explicitly so review doesn't flag cloud egress here).
- The router exposes `select(task_class) -> CoderBackend` (model string + base_url + api-key-env name + a cheap/standard tier hint per ADR-031 E intra-model tiering). → impact: Low.

Simplicity check: considered hardcoding Codex only — rejected (ADR-031 D pluggable backend is a locked design principle); a small policy table + LiteLLM is the minimal pluggable seam and matches the existing RuntimeConfig idiom.

## Prerequisites
- Specs that must be complete first: **AGENT-types** (shared package). (Pairs with AGENT-coder, which consumes the router; AGENT-coder declares this a Prerequisite.)
- Environment setup required: `litellm` in the `[agentic]` optional dependency group.

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| `pyproject.toml` | modify | Add `litellm` to `[project.optional-dependencies] agentic`. |
| `src/artemis/agentic/coder/__init__.py` | create | Coder package marker. |
| `src/artemis/agentic/coder/router.py` | create | `CoderRouter.select(task_class)` + `CoderBackend` + policy table from RuntimeConfig. |
| `src/artemis/runtime_config.py` | modify | Add a `coder_routing` sub-config (task-class→backend map; defaults-in-code). |
| `tests/test_agent_coder_router.py` | create | select returns the right backend per task class; api keys are env-refs; default fallback. |

## Tasks
- [ ] Task 1: Add `litellm` to the `[agentic]` extra + a `coder_routing` RuntimeConfig sub-model (defaults-in-code, env-ref keys). — files: `pyproject.toml`, `src/artemis/runtime_config.py` — done when: `uv sync --extra agentic` resolves; `get_runtime_config().coder_routing` returns the default table; no API key literal appears in config (env-ref names only); `uv run mypy` clean.
- [ ] Task 2: Implement `CoderRouter.select(task_class) -> CoderBackend` (LiteLLM model string + base_url + key-env + tier). — files: `src/artemis/agentic/coder/__init__.py`, `src/artemis/agentic/coder/router.py` — done when: a known task class returns its configured backend; an unknown class falls back to the default; the returned config carries the env var NAME for the key, not its value.
- [ ] Task 3: Tests. — files: `tests/test_agent_coder_router.py` — done when: per-task-class selection, default fallback, and env-ref-not-literal assertions pass under `uv run pytest -q`.

## Wave plan
Wave 1: [Task 1] | Wave 2: [Task 2] | Wave 3: [Task 3]

## Permissions
The following actions will run autonomously during build. Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | `src/artemis/agentic/coder/__init__.py`, `src/artemis/agentic/coder/router.py`, `tests/test_agent_coder_router.py` |
| Modify | `pyproject.toml`, `src/artemis/runtime_config.py` |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv add --optional agentic litellm` (or pyproject edit + `uv lock`) | Add LiteLLM to the optional group. |
| `uv sync --extra agentic` | Install the extra. |
| `uv run mypy` | Full-project type check. |
| `uv run ruff check . && uv run ruff format --check .` | Lint + format gate. |
| `uv run pytest -q` | Full test suite. |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | The five files above, by name (incl. `uv.lock`). |
| `git commit` | "feat: AGENT-coder-router pluggable coder backend via LiteLLM (ADR-031 D)" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| (coder API key env names, referenced not read) | The router carries env var NAMES for backend keys; it does not read or log key values. |

### Network
| Action | Purpose |
|--------|---------|
| Package index | `uv` resolves `litellm` into the `[agentic]` extra (one-time). |

## Specialist Context
### Security
(No `cross_model_review` — config/selection only, no model call, no execution.) Note for any reviewer: coder backends are intentionally non-sensitive/cloud-allowed (ADR-031 D); the sensitivity wall is not applied here. Keys are env-refs, never literals or logged.

### Performance
(none — a table lookup.)

### Accessibility
(none.)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | `src/artemis/agentic/coder/router.py` | Docstring: pluggable per-task backend, LiteLLM config, env-ref keys, coding-is-non-sensitive. |
| ADR | (none) | ADR-031 D records the decision. |

## Acceptance Criteria
- [ ] Per-task selection → verify: `select(task_class)` returns the configured backend for known classes.
- [ ] Default fallback → verify: an unknown task class returns the default backend.
- [ ] No secret literals → verify: the config + returned backend carry env var NAMES for keys, not values; nothing logs a key.
- [ ] Whole project clean → verify: `uv run mypy`, `uv run ruff check . && uv run ruff format --check .`, `uv run pytest -q` all pass.

## Progress
_(Coding mode writes here — do not edit manually)_
