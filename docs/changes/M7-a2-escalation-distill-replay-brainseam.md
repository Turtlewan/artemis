---
spec: m7-a2-escalation-distill-replay-brainseam
status: ready
token_profile: balanced
autonomy_level: L2
---

# Spec: M7-a2 — Escalate→teacher→distill→candidate + replay-verify + recipe-apply substitution into the Brain escalate seam + claude-cli teacher adapter

**Identity:** Implements the escalate→teacher→distill→**candidate** flow wired to the M1-b router escalation seam, replay-verify of a candidate against the original teacher outcome, the runtime token-cheap `apply_recipe` substitution (script behind a sandbox, or one local-responder call), the `Brain` escalate-stub replacement, and the live `claude-cli` teacher `ModelPort` adapter (gated).
→ why: see docs/technical/architecture/brain.md § "Self-improvement" + § "Routing" (escalation seam) · docs/technical/adr/ADR-003 (teacher method/data split). Consumes M7-a1's `Recipe`/`RecipeStore`/`RECIPE_SCHEMA`.

<!-- TERMINOLOGY: "recipe" not "skill". Sub-split of former M7-a (gate 2026-06-08): a2 = escalation+distill+replay-verify+brain-seam+claude-cli. -->

## Assumptions
- **M7-a1 complete**: `Recipe`, `RecipeStatus`, `RecipeStore` (`write`/`get`/`list`/`set_status`/`retrieve_recipes`), `RECIPE_SCHEMA` exist. M0-d (`ModelPort`, `ModelResponse`, `Scope`), M1-a, M1-b (`SemanticRouter` → `RouteDecision(path="escalate", ...)`, `Brain` with the `escalate` stub returning `ESCALATION_NOT_AVAILABLE`) complete. → impact: Stop (M7-a2 replaces the M1-b escalate stub; signatures must match).
- The teacher is reached via the `ModelPort` logical role `"teacher"`, adapter = `claude-cli` (subprocess), NOT an OpenAI base-URL swap. M7-a2 depends only on the `ModelPort.complete(role="teacher", ...)` seam; fully testable with a `FakeTeacher`/`SpyModelPort`. The live adapter is **Task 7 (GATED — on-hardware)**. → impact: Stop.
- **Distillation is task-class, not instance** (ADR-003): the teacher writes the *method* for the *task class*. The distill prompt (step 2) MUST use an **instance-free framing** — a fixed template over `task_class_key` + `action_class`, never embedding `request_text` raw (the solve call in step 1 uses `request_text`; the distill call must not). → impact: Stop (privacy + generality boundary).
- **Cloud-egress boundary is enforced IN M7-a2 code**, not merely trusted to the adapter map: a sensitive (`is_cloud_safe == False`) escalation must resolve `role="teacher"` to the LOCAL reasoner; if the resolved teacher adapter is the cloud adapter while `is_cloud_safe is False`, `escalate_and_distill` raises `CloudEgressForbiddenError`. → impact: Stop (the load-bearing privacy line; see Task 1 + the SpyModelPort test).
- **Script-class recipes run only behind a sandbox.** `apply_recipe` and `replay_verify` execute recipe-supplied Python ONLY via an injected `SandboxPort`; absent a ready sandbox they refuse (`SandboxNotAvailableError`, fail-closed). A stripped-builtins `exec` is NOT a sandbox. The hardened VM-per-exec (Apple `container`) implements `SandboxPort` later (security module). → impact: Stop (a SCRIPT-class recipe must never run on real data without the sandbox).

Simplicity check: considered a heavyweight replay harness — rejected; replay-verify = re-run the recipe's apply path on the original inputs and compare to the recorded outcome with a declared comparator. Considered exact-string replay comparison — rejected (unsound for LLM output); default comparator = **schema-conformance** against `outputs_schema`.

## Prerequisites
- Specs that must be complete first: **M7-a1**, M0-a, M0-d, M1-a, M1-b. Sequenced-with: M2 (the security module that provides the concrete `SandboxPort`; off-hardware uses a `FakeSandbox`).
- Environment setup required: none beyond the above for the off-hardware suite (fakes for teacher + sandbox). The live `claude-cli` teacher adapter probe is **GATED on-hardware** (`claude` CLI logged in on the Mini).

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| /Users/artemis-build/artemis/src/artemis/recipes/sandbox.py | create | `SandboxPort` Protocol (`run(script, inputs, *, outputs_schema) -> dict`) + `SandboxNotAvailableError`; a `FakeSandbox` for tests |
| /Users/artemis-build/artemis/src/artemis/recipes/distill.py | create | `EscalationRequest`, `TeacherOutcome`, `task_class_key`, `escalate_and_distill`, `replay_verify`, `apply_recipe`, `CloudEgressForbiddenError`, `RecipeReplayError` |
| /Users/artemis-build/artemis/src/artemis/recipes/adapters/__init__.py | create | adapters package marker |
| /Users/artemis-build/artemis/src/artemis/recipes/adapters/claude_cli.py | create | `ClaudeCliModelPort` (`role="teacher"`; subprocess; structured-output failure path; sanitised env) — live only |
| /Users/artemis-build/artemis/src/artemis/recipes/__init__.py | modify | extend re-exports + `__all__` with the a2 symbols |
| /Users/artemis-build/artemis/src/artemis/brain.py | modify | replace the M1-b `escalate` stub with the recipe-apply / escalation-queue substitution (additive `RecipeStore` ctor param, default `None`) |
| /Users/artemis-build/artemis/tests/test_recipes_distill.py | create | escalate→distill→candidate, replay-verify, cloud-egress refusal, sandbox-absent refusal, brain substitution — all fakes |

## Tasks
- [ ] Task 1: Define the sandbox port + escalation types + task_class_key + cloud-egress guard — files: `/Users/artemis-build/artemis/src/artemis/recipes/sandbox.py`, `/Users/artemis-build/artemis/src/artemis/recipes/distill.py` —
  - `sandbox.py`: `class SandboxPort(Protocol)`: `def ready(self) -> bool: ...`; `def run(self, script: str, inputs: Mapping[str, object], *, outputs_schema: dict[str, object]) -> dict[str, object]: ...` (default-deny network/fs; the hardened impl is the security module). `class SandboxNotAvailableError(Exception)`. Provide a `FakeSandbox` (constructor takes a canned output + a `ready` flag) for tests.
  - `distill.py`: frozen dataclass `EscalationRequest { request_text: str, scope: Scope, task_class_key: str, is_cloud_safe: bool }`; `TeacherOutcome { text: str, outcome_hash: str }`; `class CloudEgressForbiddenError(Exception)`; `class RecipeReplayError(Exception)`.
  - `def task_class_key(decision, request_text) -> str`: **router top-candidate-id if the `RouteDecision` carries one, else `sha256(normalise(request_text))`** (lowercase/strip/collapse-whitespace) — so paraphrases routed to the same candidate collapse to one key (M7-b's N≥2 gate depends on this).
  - `def _resolve_teacher_is_cloud(model: ModelPort) -> bool`: report whether the model's `role="teacher"` resolves to the cloud (`claude-cli`) adapter (a small capability the `ModelPort`/config exposes). Used by the guard below.
  — done when: `uv run mypy --strict src` passes; `task_class_key` returns the candidate id when present else a stable hash; two normalised-equal texts with the same candidate → same key.

- [ ] Task 2: Implement escalate→teacher→distill→candidate — files: `/Users/artemis-build/artemis/src/artemis/recipes/distill.py` — `async def escalate_and_distill(req: EscalationRequest, model: ModelPort, store: RecipeStore, *, sandbox: SandboxPort | None = None) -> Recipe`:
  1. **Cloud-egress guard:** if `req.is_cloud_safe is False` AND `_resolve_teacher_is_cloud(model)` → raise `CloudEgressForbiddenError` (sensitive data must never reach the cloud teacher).
  2. teacher solve: `solution = await model.complete(role="teacher", messages=[{"role":"user","content": <solve framing of req.request_text>}], max_tokens=1024)` → `TeacherOutcome(text=solution.text, outcome_hash=sha256(solution.text))`.
  3. distill: `distilled = await model.complete(role="teacher", messages=[{"role":"user","content": <INSTANCE-FREE distill template over req.task_class_key + the action-class framing — NEVER embeds req.request_text>}], response_schema=RECIPE_SCHEMA, max_tokens=2048)`.
  4. build `Recipe(...)` from `distilled` with `status=CANDIDATE`, `task_class_key=req.task_class_key`, `provenance={"source":"teacher","teacher_outcome_hash":outcome.outcome_hash,"verified_at":""}`.
  5. `replay_verify(recipe, req, outcome, model, sandbox=sandbox)` — on failure raise `RecipeReplayError` (do NOT write an unverified candidate).
  6. `store.write(recipe)` (signs + indexes); return it.
  — done when: `uv run mypy --strict src` passes; against a `FakeTeacher` the flow produces a signed `CANDIDATE` persisted in the store; with `is_cloud_safe=False` + a cloud-resolving teacher it raises `CloudEgressForbiddenError`.

- [ ] Task 3: Implement replay-verify + apply_recipe (sandbox-gated) — files: `/Users/artemis-build/artemis/src/artemis/recipes/distill.py` —
  - `async def replay_verify(recipe, original_inputs, expected, model, *, sandbox=None) -> bool`: re-run the recipe's **apply path** and compare. SCRIPT-class → require `sandbox is not None and sandbox.ready()` else raise `SandboxNotAvailableError` (fail-closed — never `exec` recipe code without a sandbox); run via `sandbox.run(recipe.script, inputs, outputs_schema=recipe.outputs_schema)`. INSTRUCTIONS-class → one `model.complete(role="responder", response_schema=recipe.outputs_schema, max_tokens=...)`. **Comparator default = schema-conformance** of the replayed output against `recipe.outputs_schema` (structural correctness — NOT exact-string match, which false-negatives ~always on LLM output); richer comparators deferred. On pass set `recipe.provenance["verified_at"] = now_iso()`.
  - `async def apply_recipe(recipe, inputs, model, *, sandbox=None) -> dict[str, object]`: the runtime token-cheap apply (SCRIPT → `sandbox.run(...)`, same fail-closed gate; INSTRUCTIONS → one `model.complete(role="responder", response_schema=outputs_schema)`). NEVER calls `role="teacher"`.
  — done when: `uv run mypy --strict src` passes; a SCRIPT-class recipe with `sandbox=None` (or `ready()==False`) raises `SandboxNotAvailableError` from BOTH `replay_verify` and `apply_recipe`; an INSTRUCTIONS-class recipe verifies by schema-conformance against a `FakeModelPort` whose responder output satisfies `outputs_schema`.

- [ ] Task 4: Wire the recipe-apply substitution into the Brain escalate seam — files: `/Users/artemis-build/artemis/src/artemis/brain.py` — replace the `escalate` stub. On `decision.path == "escalate"`: (a) `key = task_class_key(decision, request_text)`; (b) `names = store.retrieve_recipes(request_text, k=1, status=ENABLED)` — if a matching ENABLED recipe exists, `apply_recipe(...)` it and return `BrainResponse(text=<applied>, path="recipe", tool_used=<name>, escalated=False)` (token-cheap, NO teacher call); (c) else return a typed `ESCALATION_QUEUED` `BrainResponse` and enqueue an `EscalationRequest` (the actual teacher call is owner-gated / Curiosity-driven — M7-a2 does NOT auto-fire a cloud teacher call inline). Inject `RecipeStore` (+ optional `SandboxPort`) via the ctor (additive, default `None` → old stub behaviour, M1 tests still pass). Keep `respond` non-raising. — done when: `uv run mypy --strict src` passes; `Brain` with a store containing a matching ENABLED recipe returns `path="recipe"` (zero teacher calls); with none returns `ESCALATION_QUEUED`.

- [ ] Task 5: Extend the package surface — files: `/Users/artemis-build/artemis/src/artemis/recipes/__init__.py`, `/Users/artemis-build/artemis/src/artemis/recipes/adapters/__init__.py` (create) — extend `__all__` with `EscalationRequest`, `TeacherOutcome`, `escalate_and_distill`, `replay_verify`, `apply_recipe`, `task_class_key`, `CloudEgressForbiddenError`, `RecipeReplayError`, `SandboxPort`, `SandboxNotAvailableError`. — done when: `uv run python -c "from artemis.recipes import escalate_and_distill, apply_recipe, EscalationRequest, SandboxPort"` exits 0.

- [ ] Task 6: Write the distill/replay/brain tests (off-hardware, fakes) — files: `/Users/artemis-build/artemis/tests/test_recipes_distill.py` — typed pytest with `FakeEmbedder`, `FakeTeacher` (returns a fixed valid recipe JSON for `response_schema=RECIPE_SCHEMA`; a fixed solution string for plain solve; a schema-valid responder output equal-by-schema so replay passes), `SpyModelPort` (records which role+adapter was called + whether teacher resolves cloud), `FakeKeyProvider`, `FakeSandbox`. Tests:
  - escalate→distill→candidate: `escalate_and_distill(req, FakeTeacher(), store)` → a signed `CANDIDATE`, `provenance["verified_at"]` set; **the distill (step 3) prompt does NOT contain `req.request_text`** (instance-free assertion).
  - cloud-egress refusal: `is_cloud_safe=False` + a `SpyModelPort` whose teacher resolves cloud → raises `CloudEgressForbiddenError`; assert the cloud adapter was NEVER called.
  - replay-verify failure: a `FakeTeacher` whose responder output violates `outputs_schema` → `escalate_and_distill` raises `RecipeReplayError`, writes NO candidate.
  - sandbox-absent refusal: a SCRIPT-class recipe + `sandbox=None` → `apply_recipe`/`replay_verify` raise `SandboxNotAvailableError`.
  - brain substitution: a `Brain` with a `RecipeStore` holding an ENABLED recipe matching the query returns `path="recipe"` and makes ZERO `role="teacher"` calls; with none returns `ESCALATION_QUEUED`.
  — done when: `uv run pytest -q tests/test_recipes_distill.py` passes AND `uv run mypy --strict src tests/test_recipes_distill.py` passes.

- [ ] Task 7 (GATED — on-hardware, live teacher): Implement + probe the `claude-cli` ModelPort adapter — files: `/Users/artemis-build/artemis/src/artemis/recipes/adapters/claude_cli.py` — `class ClaudeCliModelPort` structurally satisfying `artemis.ports.ModelPort` for `role="teacher"` only: `complete(role="teacher", messages, *, stream=False, response_schema=None, max_tokens=None)` shells out to the logged-in `claude` CLI (`claude -p` headless). **Spawn the subprocess with a SANITISED `env=`** (only the minimal vars needed — NO credential/`ARTEMIS_ENV_FILE` inheritance). When `response_schema` is set: parse stdout as JSON → Pydantic-validate → **on failure retry ONCE with a repair prompt → on second failure raise `TeacherMalformedResponseError`** (so `escalate_and_distill` writes no candidate). Raise `NotImplementedError` for non-teacher roles. NO API key (subscription OAuth). On the Mini with `claude` logged in: run `escalate_and_distill` against a NON-SENSITIVE synthetic task → a verified, signed `CANDIDATE`. — done when: on the Mini, one live `escalate_and_distill` on a synthetic non-sensitive task yields a replay-verified signed `CANDIDATE`; recorded in handoff. [GATED — live cloud-teacher egress; non-sensitive synthetic input only.]

## Permissions
The following actions will run autonomously during build. Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | /Users/artemis-build/artemis/src/artemis/recipes/sandbox.py, /Users/artemis-build/artemis/src/artemis/recipes/distill.py, /Users/artemis-build/artemis/src/artemis/recipes/adapters/__init__.py, /Users/artemis-build/artemis/src/artemis/recipes/adapters/claude_cli.py, /Users/artemis-build/artemis/tests/test_recipes_distill.py |
| Modify | /Users/artemis-build/artemis/src/artemis/recipes/__init__.py, /Users/artemis-build/artemis/src/artemis/brain.py |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict src tests/test_recipes_distill.py` | Type gate |
| `uv run ruff check . ; uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q tests/test_recipes_distill.py` | Test gate |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | src/artemis/recipes/sandbox.py, distill.py, adapters/**, __init__.py, src/artemis/brain.py, tests/test_recipes_distill.py |
| `git commit` | "feat: M7-a2 escalate→distill→replay-verify + brain recipe-apply seam + sandbox gate + cloud-egress guard + claude-cli adapter" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_ENV_FILE` | Slot Settings → role→endpoint resolution (NOT inherited by the claude-cli subprocess) |

### Network
| Action | Purpose |
|--------|---------|
| live `claude` CLI subprocess (GATED, Task 7) | Live teacher distillation probe — non-sensitive synthetic input only |

## Specialist Context
### Security
- **Cloud-egress boundary enforced in-code** (`CloudEgressForbiddenError`) + a `SpyModelPort` test proving the cloud adapter is never called when `is_cloud_safe is False` — the load-bearing privacy line (ADR-003 method/data split).
- **Script execution is sandbox-gated, fail-closed** (`SandboxNotAvailableError`) in BOTH `replay_verify` and `apply_recipe`; the hardened VM-per-exec (`SandboxPort` impl) is the security module's job. No stripped-builtins `exec` on teacher-generated code.
- **Distillation is instance-free** — the distill prompt never embeds `request_text`; the cloud teacher sees the method framing, never the instance values.
- **claude-cli** runs with a sanitised subprocess env (no credential inheritance) and a validate→retry-once→fail structured-output path.

### Performance
`apply_recipe` is the token-saving payoff: a script recipe is token-free; an instructions recipe is one cheap local-responder call vs a teacher escalation. Both teacher calls are `max_tokens`-capped.

### Accessibility
(none — no frontend)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | src/artemis/recipes/distill.py, sandbox.py, adapters/claude_cli.py | Type + docstring all exports; document the escalate→distill→candidate→replay-verify lifecycle, the cloud-egress guard, the sandbox-gated apply, and "apply = automation, not a teacher call" |

## Acceptance Criteria
- [ ] Run `uv run mypy --strict src tests/test_recipes_distill.py` → verify: exit 0.
- [ ] Run `uv run pytest -q tests/test_recipes_distill.py` → verify: escalate→distill produces a signed verified CANDIDATE; the distill prompt is instance-free; `is_cloud_safe=False`+cloud-teacher → `CloudEgressForbiddenError` (cloud adapter never called); replay-verify failure writes no candidate; a SCRIPT recipe with no sandbox raises `SandboxNotAvailableError`; Brain with a matching ENABLED recipe returns `path="recipe"` with zero teacher calls.
- [ ] Run `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.
- [ ] (GATED, on Mini) One live `escalate_and_distill` on a synthetic NON-SENSITIVE task via `ClaudeCliModelPort` → verify: a replay-verified, signed CANDIDATE; no sensitive data left the box.

## Progress
_(Coding mode writes here — do not edit manually)_
