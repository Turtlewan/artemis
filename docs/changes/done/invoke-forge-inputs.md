---
spec: invoke-forge-inputs
status: done
token_profile: balanced
autonomy_level: L2
coder_model: codex
coder_effort: medium
---

# Spec: Forge authors a typed `inputs` schema for new capabilities

**Identity:** Teaches `CapabilityForge`'s authoring step to emit a typed `inputs` array (matching
`SkillInputParam`) on every authored `SkillDraft`, so newly-built capabilities declare their
invoke parameters instead of always defaulting to `[]`. Spec #2 of 5 in the capability
invoke/reuse path.
→ why: see docs/technical/adr/ADR-039-capability-invoke-reuse.md decision 4.

## Assumptions
- `SkillDraft.inputs: list[SkillInputParam]` and `SkillInputParam` (frozen: `name: str`,
  `type: Literal["string", "number", "boolean"]`, `description: str`, `required: bool = True`)
  already exist in `src/artemis/types.py`, shipped by spec #1 (`invoke-inputs-schema`,
  commit `3ff63bf`) → impact: Stop (if absent, this spec has nothing to populate).
- `forge._author` builds the draft via `SkillDraft(**(resp.structured or {}))` where
  `resp.structured` is a `dict | None` returned by `ModelPort.complete(response_schema=...)`
  after `jsonschema.validate(instance=parsed, schema=response_schema)`
  (`src/artemis/model/client.py`). Adding `"inputs"` to `SKILL_DRAFT_SCHEMA`'s top-level
  `"required"` list forces every authored response to include an `inputs` array (possibly
  empty); Pydantic then coerces each item dict into `SkillInputParam` during
  `SkillDraft(**...)` construction — no new code needed to populate the field, only the
  schema + prompt change → impact: Stop.
- Marking `"inputs"` required in the JSON schema (rather than optional) is intentional: it is
  the authoring contract this spec adds. `SkillDraft.inputs` still defaults to `[]` via
  `Field(default_factory=list)` (spec #1) for any OTHER construction path that omits the key
  (e.g. a future authoring path, or existing SKILL.md reads) — this spec does not touch or
  weaken that default → impact: Low.
- `type` values are constrained via a JSON-schema `"enum": ["string", "number", "boolean"]` on
  each `inputs[]` item, matching `SkillInputParam.type`'s `Literal`; `jsonschema.validate` will
  reject a model response using any other type string before it ever reaches
  `SkillDraft(**...)` → impact: Low.
- `tests/test_forge.py`'s local `_draft()` helper does not currently accept an `inputs` kwarg
  (unlike `tests/test_capability_store.py`'s `_draft()`, already extended by spec #1). This
  spec extends `test_forge.py`'s helper the same way, so `FakeModel(_draft(inputs=[...]))` can
  simulate an authored draft carrying inputs → impact: Low.

Simplicity check: considered leaving `inputs` optional in `SKILL_DRAFT_SCHEMA` (relying solely
on `SkillDraft`'s Pydantic default for omission) — rejected. The ADR requires the forge to
*author* an inputs declaration (empty when parameterless), not merely tolerate its absence;
making it schema-required is the simplest way to guarantee the model actually declares intent
on every authoring call, while the Pydantic default remains the backward-compat safety net for
any other/older code path. No new module or abstraction is added — this is a schema + prompt
edit to existing constants.

## Prerequisites
- Specs that must be complete first: `invoke-inputs-schema` (spec #1) — **complete** (commit
  `3ff63bf`; `SkillInputParam`, `build_invoke_argv`, `SkillDraft.inputs`/`Skill.inputs` already
  shipped).
- Environment setup required: none

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| src/artemis/capabilities/forge.py | modify | extend `AUTHOR_SYSTEM` prompt + `SKILL_DRAFT_SCHEMA` with an `inputs` array |
| tests/test_forge.py | modify | extend `_draft()` helper with `inputs`; add non-empty and parameterless authoring tests |

## Tasks
- [ ] Task 1: Schema + prompt — files: src/artemis/capabilities/forge.py — done when:
  `SKILL_DRAFT_SCHEMA["properties"]` gains an `"inputs"` key of shape `{"type": "array",
  "description": "Parameters this capability needs at invoke time (empty array if the
  capability takes no parameters). NEVER include secrets here -- secret names go in
  `secrets`.", "items": {"type": "object", "properties": {"name": {"type": "string"}, "type":
  {"type": "string", "enum": ["string", "number", "boolean"]}, "description": {"type":
  "string"}, "required": {"type": "boolean"}}, "required": ["name", "type", "description",
  "required"], "additionalProperties": False}}`; `SKILL_DRAFT_SCHEMA["required"]` gains
  `"inputs"` (now `["name", "description", "body", "tool_script", "uses", "secrets",
  "egress_domains", "tests", "inputs"]`); `AUTHOR_SYSTEM` gains a new bullet instructing the
  model to declare `inputs` as the parameters the capability needs at invoke time (empty list
  when parameterless) and that secrets never belong in `inputs` — they stay in the separate
  `secrets` field; `uv run --frozen mypy src/artemis/capabilities/forge.py` is clean.
- [ ] Task 2: Tests — files: tests/test_forge.py — done when: `_draft()` gains a keyword-only
  `inputs: list[SkillInputParam] | None = None` parameter (mirroring
  `tests/test_capability_store.py`'s `_draft()`) passed through as `inputs=inputs or []` to
  `SkillDraft(...)`; a new test asserts that when `FakeModel` is given a draft built with a
  non-empty `inputs` list (e.g. one `SkillInputParam(name="query", type="string",
  description="search text", required=True)`), `forge.propose(goal).draft.inputs` equals that
  same list; a new test asserts that when `FakeModel` is given a draft built with no `inputs`
  kwarg (parameterless), `forge.propose(goal).draft.inputs == []`; both run through
  `CapabilityForge.propose` (no sandbox/store involvement needed beyond the existing fixture
  pattern already used in this file); `uv run --frozen pytest tests/test_forge.py -q` passes.

## Wave plan
Wave 1: [Task 1] | Wave 2: [Task 2]
<!-- Task 2 imports the schema/prompt shape from Task 1 only insofar as it exercises
     CapabilityForge.propose end-to-end via FakeModel; it does not need Task 1's exact prompt
     text, but sequencing keeps the test authored against the finished schema. -->

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | (none) |
| Modify | src/artemis/capabilities/forge.py, tests/test_forge.py |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run --frozen mypy src/artemis/capabilities/forge.py` | task-level typecheck |
| `uv run --frozen pytest tests/test_forge.py -q` | task-level tests |
| `uv run --frozen mypy` | full-project strict gate |
| `uv run --frozen pytest -q` | full-project test gate |
| `uv run --frozen ruff check src tests` | lint |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | src/artemis/capabilities/forge.py tests/test_forge.py |
| `git commit` | "feat: forge authors typed inputs schema for new capabilities (invoke-forge-inputs)" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| (none) | prompt/schema + test-only change, no secrets/network |

### Network
| Action | Purpose |
|--------|---------|
| (none) | no network in this spec |

## Specialist Context
### Security
- `inputs` items are declared parameter METADATA only (name/type/description/required); the
  new schema bullet explicitly instructs the model never to place secret values or credential
  names in `inputs` — secrets stay in the existing separate `secrets: list[str]` field,
  unaffected by this spec. `type` stays a closed 3-value enum (no array/object), matching
  `SkillInputParam`'s `Literal` and preventing arbitrary nested structures from an authored
  response. This spec does not add a runtime argv/injection path — `build_invoke_argv`
  (spec #1) and typed-arg extraction/validation (spec #3) are untouched here.

### Performance
(none — prompt/schema text change only, no new hot path)

### Accessibility
(none — backend-only, no frontend surface)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | src/artemis/capabilities/forge.py | comment/docstring noting `inputs` is now a required authoring field (empty array = parameterless) |
| Changelog | CHANGELOG.md | Add entry under Unreleased |

## Acceptance Criteria
- [ ] Schema declares inputs → verify: `python -c "from artemis.capabilities.forge import SKILL_DRAFT_SCHEMA; assert 'inputs' in SKILL_DRAFT_SCHEMA['properties']; assert 'inputs' in SKILL_DRAFT_SCHEMA['required']"` exits 0.
- [ ] Prompt instructs inputs authoring → verify: `python -c "from artemis.capabilities.forge import AUTHOR_SYSTEM; assert 'inputs' in AUTHOR_SYSTEM and 'secrets' in AUTHOR_SYSTEM"` exits 0.
- [ ] Authored draft carries typed inputs → verify: `tests/test_forge.py`'s new non-empty-inputs test — `forge.propose(goal)` result's `draft.inputs` equals the `SkillInputParam` list the `FakeModel` was seeded with.
- [ ] Parameterless authored draft → verify: `tests/test_forge.py`'s new parameterless test — `forge.propose(goal)` result's `draft.inputs == []` when `FakeModel` is seeded with a draft built without an `inputs` kwarg.
- [ ] Existing forge tests unaffected → verify: `uv run --frozen pytest tests/test_forge.py -q` — all pre-existing tests in the file still pass unmodified (only `_draft()`'s signature grows an optional kwarg).
- [ ] Full gate green → verify: `uv run --frozen mypy` (0 errors), `uv run --frozen pytest -q` (all pass), `uv run --frozen ruff check src tests` (clean).

## Progress
_(Coding mode writes here — do not edit manually)_
