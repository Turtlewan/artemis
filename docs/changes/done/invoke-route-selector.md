---
spec: invoke-route-selector
status: done
token_profile: balanced
autonomy_level: L2
coder_model: codex
coder_effort: medium
---

# Spec: Match-first capability selector (invoke/reuse pre-classifier stage)

**Identity:** A standalone brain-side unit that takes an owner's natural-language request, shortlists
promoted capabilities via `store.retrieve`, asks a dedicated Haiku port to pick one (or none) with
typed args, validates those args against the capability's `inputs` schema, and returns a
`SelectionResult` — never raising, never running anything. Not wired into `/app/ask` (spec #5).
Third of 5 for the capability invoke/reuse path.
→ why: see docs/technical/adr/ADR-039-capability-invoke-reuse.md decisions 2 + 3.

## Assumptions
- `artemis.ports.capabilities.CapabilityStore` (a `@runtime_checkable` `Protocol` already defining
  `async def retrieve(self, query: str, *, k: int = 5, tags: Sequence[str] | None = None) ->
  list[Skill]`) is the correct injected store type for the selector — reusing it instead of
  defining a new narrower protocol in the selector module keeps one home for the store contract.
  `FileCapabilityStore` already satisfies it (`src/artemis/capabilities/store.py`) → impact: Low.
- The dedicated Haiq port is built the identical way `ask_routes._intent()` and `web_tool.py`'s
  `build_web_tool()` build theirs: `ModelClient(ClaudeCodeProvider(), model_default="haiku")` —
  never `QuotaAwareRouter` — per ADR-039 decision 3 / the `ed3783e` fix → impact: Stop.
- `Skill.inputs: list[SkillInputParam]` (shipped in spec #1) is populated for capabilities authored
  after spec #2 (`invoke-forge-inputs`); capabilities predating both specs have `inputs == []` and
  are therefore always "matched with zero required args" from the validator's point of view — no
  special-casing needed, the empty-list path is already correct by construction → impact: Low.
- `pydantic.BaseModel.model_json_schema()` on a frozen model with a `dict[str, object]` field
  produces a `response_schema` the existing `ModelPort.complete` down-conversion accepts — this is
  the same technique `intent.py`'s `Intent` and `web_tool.py`'s `ReaderExtract`/`SynthResult` already
  use for `response_schema`, just with one additional loosely-typed field → impact: Caution (if a
  backend's down-conversion rejects an untyped-object field, the selector still degrades safely to
  a no-match result rather than raising — this is exactly the failure mode the degrade-safe wrapper
  exists to absorb).
- The model is trusted to only echo back a `capability` value from the candidate list it was shown
  (or `null`) — but is NOT trusted blindly: the selector re-checks the returned name against the
  actual shortlisted candidates and treats an unrecognized name as a no-match ("capability not
  found" gate), never doing a second store lookup by name → impact: Low.
- `args` values coerce to their declared `SkillInputParam.type` (`string`/`number`/`boolean`) using
  plain Python coercion (`str()`, `int()`/`float()`-style numeric parse, a small bool-string table)
  — no third-party validation library needed for three primitive types → impact: Low.

Simplicity check: considered returning the raw model-picked `Skill` object in `SelectionResult`
instead of just its `name` string — rejected; the caller (spec #5) already has `store.get(name)`
available and a plain `str | None` keeps `SelectionResult` trivially serializable/frozen with no
nested `Skill` payload duplicating what the store already owns.

## Prerequisites
- Specs that must be complete first: `invoke-inputs-schema` (#1, `3ff63bf`), `invoke-forge-inputs`
  (#2, `5c5e2c6`)
- Environment setup required: none

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| src/artemis/capabilities/select.py | create | `SelectionResult`, `CapabilitySelector`, `build_capability_selector`, confidence threshold constant |
| tests/test_capability_select.py | create | FakeModel + fake `CapabilityStore` fixtures; all cases in Acceptance Criteria |

## Tasks
- [ ] Task 1: Result model + module scaffold — files: src/artemis/capabilities/select.py — done
  when: `SelectionResult` (frozen `BaseModel`: `matched: bool`, `capability: str | None`, `args:
  dict[str, object]`, `confidence: float`, `missing_required: list[str]`) is defined; a private
  `_SelectionPick` frozen `BaseModel` (`capability: str | None`, `args: dict[str, object]`,
  `confidence: float = Field(ge=0.0, le=1.0)`) and its `model_json_schema()` are defined; module
  constant `CONFIDENCE_THRESHOLD: float = 0.5` is defined with a docstring/comment noting it is
  tunable; `uv run mypy --strict src/artemis/capabilities/select.py` is clean (class body only, no
  logic yet beyond `...`/`NotImplementedError` stubs for Task 2's methods).
- [ ] Task 2: Selector logic + builder — files: src/artemis/capabilities/select.py — done when:
  `CapabilitySelector.__init__(self, *, store: CapabilityStore, model: ModelPort, k: int = 5,
  confidence_threshold: float = CONFIDENCE_THRESHOLD) -> None` stores its args;
  `async def select(self, request: str) -> SelectionResult` implements: (1) `candidates =
  await self._store.retrieve(request, k=self._k)` — empty → return the no-match `SelectionResult`
  immediately, no model call; (2) build the system + user messages describing each candidate's
  `name`/`description`/`inputs` and call `self._model.complete(messages=..., model="haiku",
  response_schema=_PICK_SCHEMA, temperature=0.0, max_tokens=400)` inside a single `try`/`except
  Exception` that logs (`_log.warning`, exception-type-only, mirroring `intent.py`) and returns the
  no-match result on any failure; (3) parse via `_SelectionPick.model_validate_json(response.text)`
  inside the same try/except; (4) gate: `pick.capability is None` OR `pick.confidence <
  self._confidence_threshold` OR the name not found among `candidates` → no-match; (5) on a
  passing gate, coerce `pick.args` against the matched `Skill.inputs` (helper function
  `_coerce_args(inputs: list[SkillInputParam], raw: dict[str, object]) -> tuple[dict[str, object],
  list[str]]` returning `(coerced_args, missing_required)` — a required param absent or uncoercible
  is added to `missing_required` and omitted from `coerced_args`; an optional param absent or
  uncoercible is silently omitted; extra keys in `raw` not present in `inputs` are dropped); (6)
  return `SelectionResult(matched=True, capability=pick.capability, args=coerced_args,
  confidence=pick.confidence, missing_required=missing_required)`. `def
  build_capability_selector(store: CapabilityStore) -> CapabilitySelector` returns
  `CapabilitySelector(store=store, model=ModelClient(ClaudeCodeProvider(), model_default="haiku"))`.
  `uv run mypy --strict src/artemis/capabilities/select.py` is clean.
- [ ] Task 3: Tests — files: tests/test_capability_select.py — done when: all cases in Acceptance
  Criteria pass under `uv run pytest tests/test_capability_select.py -q`.

## Wave plan
Wave 1: [Task 1] | Wave 2: [Task 2] | Wave 3: [Task 3]
<!-- All three tasks touch the same single file (select.py) in dependency order: Task 2's
     CapabilitySelector.select() needs Task 1's SelectionResult/_SelectionPick/CONFIDENCE_THRESHOLD;
     Task 3 tests the finished module. No parallelism available within this spec. -->

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | src/artemis/capabilities/select.py, tests/test_capability_select.py |
| Modify | (none) |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict src/artemis/capabilities/select.py` | task-level typecheck |
| `uv run pytest tests/test_capability_select.py -q` | task-level tests |
| `uv run mypy` | full-project strict gate |
| `uv run pytest -q` | full-project test gate |
| `uv run ruff check src tests` | lint |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | src/artemis/capabilities/select.py tests/test_capability_select.py |
| `git commit` | "feat: match-first capability selector (invoke-route-selector)" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| (none) | in-process model port call only, no direct network/secrets in this spec |

### Network
| Action | Purpose |
|--------|---------|
| (none) | `ModelClient`/`ClaudeCodeProvider` handle their own transport; no new network code here |

## Specialist Context
### Security
- The match-first LLM call MUST go through a dedicated `ModelClient(ClaudeCodeProvider(),
  model_default="haiku")`, never the shared codex-primary `QuotaAwareRouter` — reusing that router
  with a forced `model="haiku"` degrades silently (the exact `ed3783e` bug). `build_capability_selector`
  is the only construction site and is covered by an acceptance criterion asserting the port type.
- The selector never runs a capability, never reads secrets, never touches `FetchSandbox` — pure
  selection + validation. Missing-secret guard (ADR-039 decision 5) and confirm-before-run
  (decision 6) are out of scope, owned by spec #5.
- Model-returned `capability` names are re-validated against the actual shortlisted candidates
  (not blindly trusted, not used to do a second unscoped store lookup by name) — prevents a
  hallucinated or prompt-injected name from resolving to an unintended capability.

### Performance
(none — one `retrieve` call + one small-model completion per `select()`, no new hot path)

### Accessibility
(none — backend-only, no frontend surface)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | src/artemis/capabilities/select.py | docstrings on `SelectionResult`, `CapabilitySelector.select`, `build_capability_selector` noting the dedicated-Haiku-port requirement and the no-match degrade paths |
| Changelog | CHANGELOG.md | Add entry under Unreleased |

## Acceptance Criteria
- [ ] Module importable → verify: `uv run python -c "from artemis.capabilities.select import SelectionResult, CapabilitySelector, build_capability_selector, CONFIDENCE_THRESHOLD"` exits 0.
- [ ] Match with full args → verify: one candidate with two required `inputs`, fake model returns `{"capability": "<name>", "args": {both filled}, "confidence": 0.9}` → `select()` returns `SelectionResult(matched=True, capability="<name>", missing_required=[])` with both args present and correctly typed.
- [ ] Match with missing required arg → verify: fake model omits one required key from `args` → result has `matched=True`, `capability` set, and `missing_required == ["<that_key>"]`.
- [ ] Type coercion → verify: a `number`-typed input arrives from the model as the JSON string `"42"` → `args["<name>"]` is a numeric value (not the string); a required param whose value cannot be coerced to its declared type is treated as absent and appended to `missing_required`.
- [ ] No candidates → no match, no model call → verify: `store.retrieve` returns `[]` → `SelectionResult(matched=False, capability=None, args={}, confidence=0.0, missing_required=[])`, and the fake model's `complete` was never invoked.
- [ ] Low confidence → no match → verify: fake model returns `confidence=0.3` (below the default `CONFIDENCE_THRESHOLD=0.5`) → `matched=False`.
- [ ] Null capability → no match → verify: fake model returns `capability=None` → `matched=False`.
- [ ] Hallucinated/unrecognized capability name → no match → verify: fake model returns a `capability` string not present among the shortlisted candidates → `matched=False`.
- [ ] Model error degrades safely → verify: a fake model whose `complete` raises → `select()` returns the no-match `SelectionResult` and does not raise.
- [ ] Malformed model output degrades safely → verify: a fake model returning JSON that fails `_SelectionPick` validation → `select()` returns the no-match `SelectionResult` and does not raise.
- [ ] Dedicated Haiku port, not the shared router → verify: `build_capability_selector(store)._model` is a `ModelClient` wrapping a `ClaudeCodeProvider` with `model_default="haiku"` (assert via constructed attributes), and is NOT a `QuotaAwareRouter` instance.
- [ ] Full gate green → verify: `uv run mypy` (0 errors, strict), `uv run pytest -q` (all pass), `uv run ruff check src tests` (clean).

## Progress
_(Coding mode writes here — do not edit manually)_
