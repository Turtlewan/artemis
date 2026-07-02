---
spec: invoke-inputs-schema
status: done
token_profile: balanced
autonomy_level: L2
coder_model: codex
coder_effort: medium
---

# Spec: Typed `inputs` schema for capability invoke (data model + calling convention)

**Identity:** Adds a typed `inputs` schema to the capability data model (`SkillDraft`/`Skill`),
persists/reads it through SKILL.md frontmatter and the file store, and pins the exact runtime
calling convention a capability's `tool.py` uses to receive extracted args. Prerequisite #1 of 5
for the capability invoke/reuse path.
→ why: see docs/technical/adr/ADR-039-capability-invoke-reuse.md decision 4.

## Assumptions
- `write_skill_md`/`read_skill_md` frontmatter is plain YAML (`yaml.safe_dump`/`safe_load`); a
  list of flat dicts (`inputs`) round-trips cleanly alongside the existing `tags`/`uses`/`secrets`
  lists, no custom YAML representer needed → impact: Low.
- Every promoted capability in `library/*/SKILL.md` today predates this field and has no
  `inputs:` key at all — `meta.get("inputs", [])` must default cleanly on read in both
  `_read_draft` and `_read_skill` so pre-existing capabilities stay invokable as parameterless
  with zero migration → impact: Stop.
- `forge.py`'s `SKILL_DRAFT_SCHEMA` (the LLM `response_schema` used to validate an authored draft)
  does NOT declare `inputs` yet — this spec gives `SkillDraft.inputs` a safe empty default so
  `SkillDraft(**(resp.structured or {}))` in `forge._author` keeps working unmodified. Teaching the
  forge to actually author `inputs` is spec `invoke-forge-inputs` (#2) — forge.py is NOT touched
  here → impact: Low.
- `FetchSandbox.run`'s `argv: list[str]` parameter and call sites are untouched by this spec — the
  new `build_invoke_argv` helper only pins the convention a future caller (the spec #3 selector)
  uses to build that list; no `FetchSandbox` code changes → impact: Low.
- `SkillInputParam.type` is a `Literal["string", "number", "boolean"]` only (no array/object/enum)
  — matches the locked "keep it simple + typed" shape → impact: Caution (a later spec extends the
  Literal if the forge ever needs richer param types; not built speculatively now).

Simplicity check: considered a JSON-Schema-shaped `inputs` (an arbitrary nested `dict`) for max
flexibility — rejected; the locked design pins a flat list of `{name, type, description,
required}` records, which is sufficient for single-level structured args, trivially diffable in
YAML frontmatter, and needs no schema-validator dependency. A flat typed-param list is simpler and
was the locked choice.

## Prerequisites
- Specs that must be complete first: none
- Environment setup required: none

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| src/artemis/types.py | modify | add `SkillInputParam`, `build_invoke_argv`; add `inputs` field to `SkillDraft` and `Skill` |
| src/artemis/capabilities/skill_md.py | modify | add `inputs` param to `write_skill_md`; persist in frontmatter |
| src/artemis/capabilities/store.py | modify | carry `inputs` through `stage`/`promote`/`_read_draft`/`_read_skill` |
| tests/test_types.py | create | `SkillInputParam` validation + `build_invoke_argv` unit tests |
| tests/test_capability_store.py | modify | extend `_draft()` helper with `inputs`; round-trip + legacy-default tests |

## Tasks
- [ ] Task 1: Data model — files: src/artemis/types.py — done when: `SkillInputParam` (frozen
  `BaseModel`: `name: str`, `type: Literal["string", "number", "boolean"]`, `description: str`,
  `required: bool = True`) is defined; `build_invoke_argv(inputs: list[SkillInputParam], args:
  dict[str, object]) -> list[str]` is defined (returns `[]` when `inputs` is empty, else
  `[json.dumps(args, separators=(",", ":"), sort_keys=True)]`); `SkillDraft.inputs: list[SkillInputParam]
  = Field(default_factory=list)` and `Skill.inputs: list[SkillInputParam] = Field(default_factory=list)`
  are added; `uv run mypy --strict src/artemis/types.py` is clean.
- [ ] Task 2: Frontmatter persistence — files: src/artemis/capabilities/skill_md.py — done when:
  `write_skill_md` gains a required keyword-only `inputs: list[dict[str, Any]]` parameter and
  writes it into the `meta` dict (key `"inputs"`) alongside `tags`/`uses`/`secrets`;
  `read_skill_md` is unchanged (still returns the raw loaded mapping, `inputs` present when
  written); `uv run mypy --strict src/artemis/capabilities/skill_md.py` is clean.
- [ ] Task 3: Store plumbing — files: src/artemis/capabilities/store.py — done when: `stage()` and
  `promote()` both pass `inputs=[p.model_dump() for p in draft.inputs]` into their `write_skill_md`
  calls; `promote()`'s returned `Skill(...)` includes `inputs=draft.inputs`; `_read_draft()` builds
  `inputs=[SkillInputParam(**item) for item in meta.get("inputs", [])]`; `_read_skill()` builds the
  same for `Skill`; `uv run mypy --strict src/artemis/capabilities/store.py` is clean.
- [ ] Task 4: Tests — files: tests/test_types.py, tests/test_capability_store.py — done when: all
  cases in Acceptance Criteria pass under `uv run pytest tests/test_types.py
  tests/test_capability_store.py -q`.

## Wave plan
Wave 1: [Task 1, Task 2] | Wave 2: [Task 3] | Wave 3: [Task 4]
<!-- Task 1 (types.py) and Task 2 (skill_md.py) are file-disjoint and independent of each other:
     write_skill_md takes plain list[dict], not SkillInputParam. Task 3 needs both (imports
     SkillInputParam from Task 1, calls the Task-2 signature). Task 4 tests the finished plumbing. -->

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | tests/test_types.py |
| Modify | src/artemis/types.py, src/artemis/capabilities/skill_md.py, src/artemis/capabilities/store.py, tests/test_capability_store.py |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict src/artemis/types.py src/artemis/capabilities/skill_md.py src/artemis/capabilities/store.py` | task-level typecheck |
| `uv run pytest tests/test_types.py tests/test_capability_store.py -q` | task-level tests |
| `uv run mypy` | full-project strict gate |
| `uv run pytest -q` | full-project test gate |
| `uv run ruff check src tests` | lint |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | src/artemis/types.py src/artemis/capabilities/skill_md.py src/artemis/capabilities/store.py tests/test_types.py tests/test_capability_store.py |
| `git commit` | "feat: typed inputs schema for capability invoke (invoke-inputs-schema)" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| (none) | pure data-model + file I/O, no secrets/network |

### Network
| Action | Purpose |
|--------|---------|
| (none) | no network in this spec |

## Specialist Context
### Security
- `inputs` values themselves are declared parameter METADATA (name/type/description), never
  secret values — secrets stay in the separate `secrets: list[str]` field, unaffected by this
  spec. `type` is restricted to a closed `Literal` of primitives (no array/object), which prevents
  arbitrary nested structures from entering the frontmatter or the eventual argv-serialization
  path. `build_invoke_argv` does not validate `args` against `inputs` (no type coercion, no
  injection surface) — it only serializes what the caller already extracted; typed-arg validation
  against the schema is the spec #3 selector's job, not this spec's.

### Performance
(none — pure in-memory model + local file I/O, no new hot path)

### Accessibility
(none — backend-only, no frontend surface)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | src/artemis/types.py, src/artemis/capabilities/skill_md.py, src/artemis/capabilities/store.py | docstrings on `SkillInputParam`, `build_invoke_argv`, and the `inputs` frontmatter field noting the legacy-default (`[]`) contract |
| Changelog | CHANGELOG.md | Add entry under Unreleased |

## Acceptance Criteria
- [ ] Data model importable → verify: `uv run python -c "from artemis.types import SkillInputParam, build_invoke_argv, Skill, SkillDraft"` exits 0.
- [ ] `build_invoke_argv` parameterless → verify: `build_invoke_argv([], {})== []`.
- [ ] `build_invoke_argv` typed → verify: `build_invoke_argv([SkillInputParam(name="q", type="string", description="d")], {"q": "x"}) == ['{"q":"x"}']`.
- [ ] `SkillInputParam.type` rejects unknown types → verify: `SkillInputParam(name="q", type="array", description="d")` raises `pydantic.ValidationError`.
- [ ] Frontmatter round-trip → verify: a staged skill's `SKILL.md` frontmatter (`read_skill_md`) contains an `inputs` list matching `[p.model_dump() for p in draft.inputs]` for a draft with a non-empty `inputs` list.
- [ ] `stage`/`promote` carry inputs → verify: `store.promote(staged_id).inputs == draft.inputs` and `store.get(name).inputs == draft.inputs` for a draft with a non-empty `inputs` list.
- [ ] `_read_draft` round-trip → verify: re-staging a skill and reading it back (`store._read_draft`) reproduces the original draft's `inputs` list exactly.
- [ ] Legacy/parameterless default → verify: a `SKILL.md` file written with no `inputs` key at all (simulating a pre-existing capability) is read via `store.get(...)` / `store._read_draft(...)` and both produce `inputs == []` without raising.
- [ ] Full gate green → verify: `uv run mypy` (0 errors, strict), `uv run pytest -q` (all pass), `uv run ruff check src tests` (clean).

## Progress
_(Coding mode writes here — do not edit manually)_
