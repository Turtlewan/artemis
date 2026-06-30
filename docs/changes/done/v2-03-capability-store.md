# Spec: v2-03 — Capability store (SKILL.md library)

status: ready
slice: 0
builds-on: v2-02 (committed c017838); implements ports/capabilities.py CapabilityStore

## Identity
The durable skill library: a file-backed `CapabilityStore` that stages authored capabilities to quarantine, promotes verified ones into a versioned `SKILL.md` library (Agent-Skills format), and retrieves them. This is the storage half of the capability lifecycle; the author→sandbox-verify→promote forge is v2-04. Semantic-embedding retrieval is a documented swap behind the same signature when the memory engine lands (Slice 2); this slice ships a lexical interim.

## Files to change
- create `src/artemis/capabilities/__init__.py`
- create `src/artemis/capabilities/skill_md.py`
- create `src/artemis/capabilities/store.py`
- create `tests/test_capability_store.py`
- modify `pyproject.toml` (add runtime dep `pyyaml>=6`; dev dep `types-PyYAML`)

## Exact changes

### Task 1 — SKILL.md serialization (`skill_md.py`)
Agent-Skills format = YAML frontmatter + markdown body.
- `write_skill_md(path: Path, *, name, description, version, tags, uses, secrets, body) -> None` — write `path` with `---\n<yaml frontmatter>\n---\n\n<body>`; frontmatter keys: `name, description, version, tags, uses, secrets`. Use `yaml.safe_dump`.
- `read_skill_md(path: Path) -> tuple[dict, str]` — split frontmatter/body, `yaml.safe_load` the frontmatter, return `(meta, body)`. Raise `SkillFormatError` on malformed frontmatter.

### Task 2 — file-backed store (`store.py`, implements `CapabilityStore`)
- `class FileCapabilityStore:` `__init__(self, root: Path)` → `self._staging = root/"staging"`, `self._library = root/"library"`; create both.
- `async def stage(self, draft: SkillDraft) -> StagedSkill`:
  - `staged_id = f"{slug(draft.name)}-{uuid4().hex[:8]}"`; dir = `staging/<staged_id>/`.
  - write `SKILL.md` (version 0, `tags=[]`, body=draft.body), `tool.py` if `draft.tool_script`, `tests/test_skill.py` if `draft.tests`.
  - return `StagedSkill(id=staged_id, draft=draft)`.
- `async def promote(self, staged_id: str) -> Skill`:
  - read `staging/<staged_id>/`; `name = draft.name`; `version = (existing library/<name> version) + 1 else 1`.
  - write `library/<name>/` with `SKILL.md` (frontmatter version=version, `tags=[]`, uses/secrets from draft), `tool.py`, `tests/` copied over.
  - return `Skill(name=name, description=..., version=version, path=str(library/<name>), tags=[], uses=draft.uses, secrets=draft.secrets)`. Raise `StagedSkillNotFound` if missing.
- `async def retrieve(self, query, *, k=5, tags=None) -> list[Skill]`:
  - scan `library/*/SKILL.md` → `Skill`s; score by **lexical token-overlap** of `query` against `name + description` (lowercased, set intersection / len(query tokens)); if `tags` given, keep only skills whose `tags` ⊇ requested; sort desc, return top-`k`.
  - docstring: lexical interim; swap to embedding retrieval behind this signature in the memory slice.
- `def get(self, name) -> Skill | None`: read `library/<name>/SKILL.md` → `Skill`, or None.
- helper `slug(s)` → lowercase, non-alnum → `-`.

### Task 3 — tests (`test_capability_store.py`, use `tmp_path`)
- `isinstance(FileCapabilityStore(tmp_path), CapabilityStore)`.
- `stage`: writes `staging/<id>/SKILL.md` + `tool.py` (when tool_script) + `tests/`; returns `StagedSkill` with matching draft.
- `promote`: creates `library/<name>/SKILL.md` with correct frontmatter (parse it back), `version == 1`; staging a second draft of the same name and promoting → `version == 2`.
- `retrieve`: two promoted skills with distinct descriptions → query matching one returns it first; `tags=[...]` filter excludes non-matching; `k` caps results.
- `get`: returns the `Skill` for a promoted name; `None` for unknown.
- malformed SKILL.md → `read_skill_md` raises `SkillFormatError`.

## Acceptance criteria
- `uv sync` succeeds (pyyaml added).
- `uv run mypy src tests` → clean (strict).
- `uv run pytest -q` → green.
- A staged draft can be promoted to a versioned `SKILL.md` library entry and retrieved by description.

## Commands to run
```
uv sync
uv run mypy src tests
uv run pytest -q
```
