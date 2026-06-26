---
spec: m7-a2-escalation-distill-replay-brainseam
status: ready
token_profile: balanced
autonomy_level: L2
---
<!-- amended 2026-06-11 per contracts.md (Seam 1) + m7-cap-teacher-distill.md BLOCKs B1, B2; UPGRADE U2; Decision D1 -->

# Spec: M7-a2 — Escalate→teacher→distill→candidate + replay-verify + recipe-apply substitution into the Brain escalate seam + claude-cli teacher adapter

**Identity:** Implements the escalate→teacher→distill→**candidate** flow wired to the M1-b router escalation seam, replay-verify of a candidate against the original teacher outcome, the runtime token-cheap `apply_recipe` substitution (script behind a sandbox, or one local-responder call), the `Brain` escalate-stub replacement, and the live `claude-cli` teacher `ModelPort` adapter (gated).
→ why: see docs/technical/architecture/brain.md § "Self-improvement" + § "Routing" (escalation seam) · docs/technical/adr/ADR-003 (teacher method/data split). Consumes M7-a1's `Recipe`/`RecipeStore`/`RECIPE_SCHEMA`.

<!-- TERMINOLOGY: "recipe" not "skill". Sub-split of former M7-a (gate 2026-06-08): a2 = escalation+distill+replay-verify+brain-seam+claude-cli. -->

## Assumptions
- **M7-a1 complete**: `Recipe`, `RecipeStatus`, `RecipeStore` (`write`/`get`/`list`/`set_status`/`retrieve_recipes`), `RECIPE_SCHEMA` exist. M0-d (`ModelPort`, `ModelResponse`, `Scope`), M1-a, M1-b (`SemanticRouter` → `RouteDecision(path="escalate", ...)`, `Brain` with the `escalate` stub returning `ESCALATION_NOT_AVAILABLE`) complete. → impact: Stop (M7-a2 replaces the M1-b escalate stub; signatures must match).
- The teacher is reached via the `ModelPort` logical role `"teacher"`, adapter = `claude-cli` (subprocess), NOT an OpenAI base-URL swap. M7-a2 depends only on the `ModelPort.complete(role="teacher", ...)` seam; fully testable with a `FakeTeacher`/`SpyModelPort`. The live adapter is **Task 7 (GATED — on-hardware)**. → impact: Stop.
- **Distillation is task-class, not instance** (ADR-003): the teacher writes the *method* for the *task class*. The distill prompt (step 2) MUST use an **instance-free framing** — a fixed template over `task_class_key` + `action_class`, never embedding `request_text` raw (the solve call in step 1 uses `request_text`; the distill call must not). → impact: Stop (privacy + generality boundary).
- **Cloud-egress boundary is enforced IN M7-a2 code**, not merely trusted to the adapter map: a sensitive (`is_cloud_safe == False`) escalation must resolve `role="teacher"` to the LOCAL reasoner; if `self.teacher_origin == "cloud"` while `is_cloud_safe is False`, `escalate_and_distill` raises `CloudEgressForbiddenError`. The `teacher_origin` value is injected at construction by the composition root (see Task 1); `ModelResponse.origin` is audit-only and is not probed. → impact: Stop (the load-bearing privacy line; see Task 1 + the SpyModelPort test).
- **Script-class recipes run only behind a sandbox.** `apply_recipe` and `replay_verify` execute recipe-supplied Python ONLY via an injected `SandboxPort`; absent a ready sandbox they refuse (`SandboxNotAvailableError`, fail-closed). A stripped-builtins `exec` is NOT a sandbox. The hardened VM-per-exec (Apple `container`) implements `SandboxPort` later (security module). → impact: Stop (a SCRIPT-class recipe must never run on real data without the sandbox).

Simplicity check: considered a heavyweight replay harness — rejected; replay-verify = re-run the recipe's apply path on the original inputs and compare to the recorded outcome with a declared comparator. Considered exact-string replay comparison — rejected (unsound for LLM output); default comparator = **schema-conformance** against `outputs_schema`.

## Prerequisites
- Specs that must be complete first: **M7-a1**, M0-a, M0-d, M1-a, M1-b. Sequenced-with: M2 (the security module that provides the concrete `SandboxPort`; off-hardware uses a `FakeSandbox`).
- Environment setup required: none beyond the above for the off-hardware suite (fakes for teacher + sandbox). The live `claude-cli` teacher adapter probe is **GATED on-hardware** (`claude` CLI logged in on the Mini).
- **Reservation note (architecture-validation 2026-06-23, reservation F — shared durable-exec + idempotency convention; ADR-024 Refinement 2026-06-23):** the recipe-runner (`apply_recipe`) is the third consumer of the **shared checkpoint/replay + idempotency-key convention** (with the Task Executor and heartbeat). A recipe that performs external-effect steps must carry an idempotency key conformant to the shared convention so a re-applied / resumed recipe can't double-fire those effects (naïve-retry duplication is the named 2026 failure mode). M7-a2 builds replay-verify against the recorded outcome; the durable cross-surface replay model is M9/ADR-024 — keep `apply_recipe`'s effect path idempotency-key-ready so it slots into that model without reshaping. → impact: Low (no v1 behaviour change; aligns the effect path to the shared convention).

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| /Users/artemis-build/artemis/src/artemis/recipes/sandbox.py | create | `SandboxPort` Protocol (`run(script, inputs, *, outputs_schema) -> dict`) + `SandboxNotAvailableError`; a `FakeSandbox` for tests |
| /Users/artemis-build/artemis/src/artemis/recipes/distill.py | create | `DistillService` (holds `escalate_and_distill`/`replay_verify` methods), `EscalationRequest`, `TeacherOutcome`, `task_class_key`, `apply_recipe`, `CloudEgressForbiddenError`, `RecipeReplayError` |
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
  - Define `@dataclass class DistillService:` with fields `model: ModelPort`, `store: RecipeStore`, `teacher_origin: Literal["local", "cloud"]`, `sandbox: SandboxPort | None = None`. `teacher_origin` is injected by the **composition root** that wires the teacher `ModelPort` adapter. The composition root knows which adapter it is wiring (local vs cloud); it passes the corresponding literal. The privacy/provenance gate reads `self.teacher_origin` — **no probe call is made**. `ModelResponse.origin` (contracts.md Seam 1) remains available on every response for audit/OBS logging; it is NOT used for the egress guard. No `_resolve_teacher_is_cloud` function is needed. `escalate_and_distill` and `replay_verify` are methods on `DistillService`.
  — done when: `uv run mypy --strict src` passes; `task_class_key` returns the candidate id when present else a stable hash; two normalised-equal texts with the same candidate → same key.

- [ ] Task 2: Implement escalate→teacher→distill→candidate — files: `/Users/artemis-build/artemis/src/artemis/recipes/distill.py` — method on `DistillService`: `async def escalate_and_distill(self, req: EscalationRequest) -> Recipe:` (uses `self.model`, `self.store`, `self.teacher_origin`, `self.sandbox`). `Message` is the frozen dataclass `{role: str, content: str}` from `artemis.ports` (M0-d / contracts.md Seam 1) — `messages` is `Sequence[Message]`, NOT raw dicts.
  1. **Cloud-egress guard:** if `req.is_cloud_safe is False` AND `self.teacher_origin == "cloud"` → raise `CloudEgressForbiddenError` (sensitive data must never reach the cloud teacher). No probe call.
  2. teacher solve: `solution = await self.model.complete(role="teacher", messages=[Message(role="user", content=<solve framing of req.request_text>)], max_tokens=1024)` → `TeacherOutcome(text=solution.text, outcome_hash=sha256(solution.text))`.
  3. distill: `distilled = await self.model.complete(role="teacher", messages=[Message(role="user", content=<INSTANCE-FREE distill template over req.task_class_key + the action-class framing — NEVER embeds req.request_text>)], response_schema=RECIPE_SCHEMA, max_tokens=2048)`.
  4. build `Recipe(...)` from `distilled` with `status=CANDIDATE`, `task_class_key=req.task_class_key`, `provenance={"source":"teacher","teacher_outcome_hash":outcome.outcome_hash,"verified_at":""}`.
  5. `await self.replay_verify(recipe, req, outcome)` — on failure raise `RecipeReplayError` (do NOT write an unverified candidate).
  6. `self.store.write(recipe)` (signs + indexes); return it.
  — done when: `uv run mypy --strict src` passes; against a `DistillService(model=FakeTeacher(), store=store, teacher_origin="local")` the flow produces a signed `CANDIDATE` persisted in the store; with `is_cloud_safe=False` + `teacher_origin="cloud"` it raises `CloudEgressForbiddenError`.

- [ ] Task 3: Implement replay-verify + apply_recipe (sandbox-gated) — files: `/Users/artemis-build/artemis/src/artemis/recipes/distill.py` —
  - method on `DistillService`: `async def replay_verify(self, recipe: Recipe, req: EscalationRequest, expected: TeacherOutcome) -> bool:` (uses `self.model`, `self.sandbox`): re-run the recipe's **apply path** and compare. The `sandbox.run` inputs are derived from `req` (the SCRIPT path feeds `req.request_text` / the recipe `inputs_schema`-shaped fields as the run inputs). SCRIPT-class → require `self.sandbox is not None and self.sandbox.ready()` else raise `SandboxNotAvailableError` (fail-closed — never `exec` recipe code without a sandbox); run via `self.sandbox.run(recipe.script, inputs, outputs_schema=recipe.outputs_schema)`. INSTRUCTIONS-class → one `self.model.complete(role="responder", messages=[Message(role="user", content=...)], response_schema=recipe.outputs_schema, max_tokens=...)`. **Comparator default = schema-conformance** of the replayed output against `recipe.outputs_schema` (structural correctness — NOT exact-string match, which false-negatives ~always on LLM output); richer comparators deferred. On pass set `recipe.provenance["verified_at"] = now_iso()`.
  - `async def apply_recipe(recipe: Recipe, inputs: Mapping[str, object], model: ModelPort, *, sandbox: SandboxPort | None = None) -> dict[str, object]` (module-level function — runtime apply path called by the Brain, NOT a `DistillService` method): the runtime token-cheap apply (SCRIPT → `sandbox.run(...)`, same fail-closed gate; INSTRUCTIONS → one `model.complete(role="responder", messages=[Message(role="user", content=...)], response_schema=outputs_schema)`). NEVER calls `role="teacher"`.
  — done when: `uv run mypy --strict src` passes; a SCRIPT-class recipe with `sandbox=None` (or `ready()==False`) raises `SandboxNotAvailableError` from BOTH `replay_verify` and `apply_recipe`; an INSTRUCTIONS-class recipe verifies by schema-conformance against a `FakeModelPort` whose responder output satisfies `outputs_schema`.

- [ ] Task 4: Wire the recipe-apply substitution into the Brain escalate seam — files: `/Users/artemis-build/artemis/src/artemis/brain.py` — replace the `escalate` stub. On `decision.path == "escalate"`: (a) `key = task_class_key(decision, request_text)`; (b) `names = store.retrieve_recipes(request_text, k=1, status=ENABLED)` — if a matching ENABLED recipe exists, `apply_recipe(...)` it and return `BrainResponse(text=<applied>, path="recipe", tool_used=<name>, escalated=False)` (token-cheap, NO teacher call); (c) else return a `BrainResponse(path="escalation_queued", text="", escalated=True)` — **no persistent queue; no enqueue call**. The escalation is surfaced to the Curiosity Loop solely via the OBS-a telemetry tap (an `ESCALATION` event is emitted via the existing OBS telemetry writer, which M7-c's `TelemetrySource.escalations()` reads). No `EscalationQueue` type is needed; the OBS telemetry tap is the authoritative escalation record. Inject `RecipeStore` (+ optional `SandboxPort` + optional `telemetry_writer` for the OBS tap — additive, all default `None`) via the ctor (default `None` → old stub behaviour, M1 tests still pass). Keep `respond` non-raising. — done when: `uv run mypy --strict src` passes; `Brain` with a store containing a matching ENABLED recipe returns `path="recipe"` (zero teacher calls); with none returns `path="escalation_queued"` and emits an OBS telemetry event (verified via a `SpyTelemetryWriter` in the test).

- [ ] Task 5: Extend the package surface — files: `/Users/artemis-build/artemis/src/artemis/recipes/__init__.py`, `/Users/artemis-build/artemis/src/artemis/recipes/adapters/__init__.py` (create) — extend `__all__` with `DistillService`, `EscalationRequest`, `TeacherOutcome`, `escalate_and_distill`, `replay_verify`, `apply_recipe`, `task_class_key`, `CloudEgressForbiddenError`, `RecipeReplayError`, `SandboxPort`, `SandboxNotAvailableError`, `TeacherMalformedResponseError`. (`TeacherMalformedResponseError` is defined in `adapters/claude_cli.py` and re-exported here.) — done when: `uv run python -c "from artemis.recipes import escalate_and_distill, apply_recipe, EscalationRequest, SandboxPort"` exits 0.

- [ ] Task 6: Write the distill/replay/brain tests (off-hardware, fakes) — files: `/Users/artemis-build/artemis/tests/test_recipes_distill.py` — typed pytest with `FakeEmbedder`, `FakeTeacher` (returns a fixed valid recipe JSON for `response_schema=RECIPE_SCHEMA`; a fixed solution string for plain solve; a schema-valid responder output equal-by-schema so replay passes), `SpyModelPort` (records which role+adapter was called + whether teacher resolves cloud), `FakeKeyProvider`, `FakeSandbox`. Tests:
  - escalate→distill→candidate: `DistillService(model=FakeTeacher(), store=store, teacher_origin="local").escalate_and_distill(req)` → a signed `CANDIDATE`, `provenance["verified_at"]` set; **the distill (step 3) prompt does NOT contain `req.request_text`** (instance-free assertion).
  - cloud-egress refusal: `DistillService(model=SpyModelPort(), store=store, teacher_origin="cloud")` + `is_cloud_safe=False` → `escalate_and_distill(req)` raises `CloudEgressForbiddenError` before any `model.complete` call; assert the teacher adapter was NEVER called (zero calls on the `SpyModelPort`).
  - replay-verify failure: a `FakeTeacher` whose responder output violates `outputs_schema` → `escalate_and_distill` raises `RecipeReplayError`, writes NO candidate.
  - sandbox-absent refusal: a SCRIPT-class recipe + `sandbox=None` → `apply_recipe`/`replay_verify` raise `SandboxNotAvailableError`.
  - brain substitution: a `Brain` with a `RecipeStore` holding an ENABLED recipe matching the query returns `path="recipe"` and makes ZERO `role="teacher"` calls; with none returns `path="escalation_queued"` AND fires one OBS telemetry event (via `SpyTelemetryWriter`).
  — done when: `uv run pytest -q tests/test_recipes_distill.py` passes AND `uv run mypy --strict src tests/test_recipes_distill.py` passes.

- [ ] Task 7 (GATED — on-hardware, live teacher): Implement + probe the `claude-cli` ModelPort adapter — files: `/Users/artemis-build/artemis/src/artemis/recipes/adapters/claude_cli.py` — `class ClaudeCliModelPort` structurally satisfying `artemis.ports.ModelPort` for `role="teacher"` only: `async def complete(role="teacher", messages, *, stream=False, response_schema=None, max_tokens=None) -> ModelResponse` (contracts.md Seam 1: `async def complete`; returns `ModelResponse` with `origin="cloud"`, `model_id=<model string from response>`). **Resolve the executable at init: `self._exe = shutil.which("claude")` — raise `RuntimeError("claude CLI not found on PATH")` if None** (handles `.cmd`/`.ps1` shim on Windows without `shell=True`). **Spawn the subprocess with a SANITISED `env=`** (only the minimal vars needed — NO credential/`ARTEMIS_ENV_FILE` inheritance). **Use the verified P1 interface: `[self._exe, "-p", prompt, "--output-format", "json"]`; take `.result` from the parsed JSON; treat `.is_error == True` or non-zero exit as failure.** When `response_schema` is set: JSON-parse `.result` → Pydantic-validate → **on failure retry ONCE with a repair prompt → on second failure raise `TeacherMalformedResponseError`** (so `escalate_and_distill` writes no candidate). Raise `NotImplementedError` for non-teacher roles. NO API key (subscription OAuth). On the Mini with `claude` logged in: run `escalate_and_distill` against a NON-SENSITIVE synthetic task → a verified, signed `CANDIDATE`. Also verify that `ModelResponse.origin == "cloud"` is returned by this adapter (audit only; the egress guard reads the injected `teacher_origin`, not the response field). — done when: on the Mini, one live `escalate_and_distill` on a synthetic non-sensitive task yields a replay-verified signed `CANDIDATE`; recorded in handoff. [GATED — live cloud-teacher egress; non-sensitive synthetic input only.]

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
- [ ] Run `uv run pytest -q tests/test_recipes_distill.py` → verify: escalate→distill produces a signed verified CANDIDATE; the distill prompt is instance-free; `is_cloud_safe=False`+`teacher_origin="cloud"` (injected) → `CloudEgressForbiddenError` with zero teacher model calls; replay-verify failure writes no candidate; a SCRIPT recipe with no sandbox raises `SandboxNotAvailableError`; Brain with a matching ENABLED recipe returns `path="recipe"` with zero teacher calls; Brain with no matching recipe returns `path="escalation_queued"` and emits one OBS telemetry event.
- [ ] Run `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.
- [ ] (GATED, on Mini) One live `escalate_and_distill` on a synthetic NON-SENSITIVE task via `ClaudeCliModelPort` → verify: a replay-verified, signed CANDIDATE; no sensitive data left the box.

## Progress
_(Coding mode writes here — do not edit manually)_
