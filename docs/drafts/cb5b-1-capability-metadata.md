---
spec: cb5b-1-capability-metadata
status: draft
token_profile: lean
autonomy_level: L5
coder_effort: medium
---

# Spec: Capability `goal` + `built_at` metadata (CB-5b Phase 1)

**Identity:** Add `goal` (one-line "what it does") and `built_at` (promote timestamp) to a capability's SKILL.md frontmatter, the `Skill` model, and the `/app/capabilities` DTO, so the CB-5b node overlay has human content.
→ why: see docs/technical/adr/ADR-045-capability-map-nodes.md (decision 4)

## Assumptions
- `BuildProposal.goal` already exists (src/artemis/types.py) — `goal` is threaded from the proposal, not newly authored → impact: Caution
- `promote` (store.py) is the natural place to stamp `built_at`; a clock seam keeps it testable → impact: Caution
- Legacy SKILL.md files omit `goal`/`built_at`; readers default them (`goal=""`, `built_at=None`) — zero migration → impact: Stop

Simplicity check: considered stamping `built_at` client-side — rejected; the brain owns promote, so it stamps authoritatively.

## Prerequisites
- **⚠️ METADATA-FILE COLLISION (ADR-045):** this edits `types.py`, `skill_md.py`, `store.py`, `capability_routes.py` — the SAME files as `verify-auth-unverified-mark` (`auth_status`) and `oauth-3-invoke-integration` (`oauth_scopes`). **STRONGLY RECOMMENDED: build a single consolidated `capability-metadata` spec (auth_status + oauth_scopes + goal + built_at together) instead of these three serially.** If kept separate, build STRICTLY SEQUENTIALLY (verify-auth → oauth-3 → this), each rebasing — never concurrent.

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| src/artemis/capabilities/skill_md.py | modify | `write_skill_md`/`read_skill_md` carry `goal`, `built_at` in frontmatter |
| src/artemis/types.py | modify | `Skill.goal: str = ""`, `Skill.built_at: str \| None = None`; thread `goal` onto `SkillDraft` |
| src/artemis/capabilities/store.py | modify | write goal at stage/promote; stamp `built_at` at promote (clock seam); read both in `_read_skill`/`_read_draft` |
| src/artemis/api/capability_routes.py | modify | `CapabilitySummary` + `InstalledCard` gain `goal`, `built_at` |
| tests/capabilities/test_skill_md.py, tests/capabilities/test_store.py, tests/api/test_capability_routes.py | modify | cover the new fields + legacy-default |

## Tasks
- [ ] Task 1: `skill_md.py` — add `goal: str` and `built_at: str | None` params to `write_skill_md` (into the frontmatter mapping) and have `read_skill_md` return them (already returns the whole mapping — no change to read, but add to the write meta). Add `SkillDraft.goal: str = ""` in types.py and `Skill.goal`, `Skill.built_at` fields. — files: src/artemis/capabilities/skill_md.py, src/artemis/types.py, tests/capabilities/test_skill_md.py — done when: a written SKILL.md round-trips `goal`+`built_at`; a legacy file (no keys) reads back `goal=""`, `built_at=None`.
- [ ] Task 2: `store.py` — thread `goal` through `stage`/`promote`/`_read_draft`/`_read_skill`; stamp `built_at` at promote via an injected `now: Callable[[], datetime] = lambda: datetime.now(UTC)` seam on `FileCapabilityStore.__init__` (ISO string). `_read_skill` reads `goal` (default "") and `built_at` (default None). — files: src/artemis/capabilities/store.py, tests/capabilities/test_store.py — done when: promoting a draft with `goal="reads inbox"` yields a `Skill` with that goal + a stamped `built_at`; re-reading the library SKILL.md preserves both.
- [ ] Task 3: `capability_routes.py` — add `goal`, `built_at` to `CapabilitySummary` (list) and `InstalledCard` (promote), populated from the `Skill`. — files: src/artemis/api/capability_routes.py, tests/api/test_capability_routes.py — done when: `GET /app/capabilities` returns each capability's `goal`+`built_at`; the promote `InstalledCard` includes them.

## Wave plan
Wave 1: [Task 1] | Wave 2: [Task 2] | Wave 3: [Task 3]

## Permissions
### File Operations
| Action | Paths |
|--------|-------|
| Modify | src/artemis/capabilities/skill_md.py, src/artemis/types.py, src/artemis/capabilities/store.py, src/artemis/api/capability_routes.py, tests/capabilities/test_skill_md.py, tests/capabilities/test_store.py, tests/api/test_capability_routes.py |
### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy` | type gate |
| `uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/` | lint/format |
| `uv run pytest -q` | full suite |
### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | the files above + CHANGELOG.md |
| `git commit` | "feat(capabilities): goal + built_at metadata (CB-5b)" |

## Specialist Context
### Security
No new credential/egress flow — metadata only. `built_at`/`goal` are non-sensitive display strings.

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Changelog | CHANGELOG.md | Unreleased/Added — capability goal + built_at metadata |
| ADR | docs/technical/adr/ADR-045-capability-map-nodes.md | written at planning |

## Acceptance Criteria
- [ ] `write_skill_md(..., goal="g", built_at="2026-07-03T…")` then `read_skill_md` → frontmatter has `goal`, `built_at`.
- [ ] Reading a SKILL.md lacking both keys → `Skill.goal == ""`, `Skill.built_at is None` (no exception).
- [ ] Promote a draft (goal="reads inbox") with a fixed clock seam → `Skill.goal == "reads inbox"`, `Skill.built_at == <fixed iso>`.
- [ ] `GET /app/capabilities` → each row has `goal` + `built_at`; promote `InstalledCard` includes them.
- [ ] `uv run mypy` clean; `uv run ruff check` clean; `uv run pytest -q` green.

## Progress
_(Coding mode writes here)_
