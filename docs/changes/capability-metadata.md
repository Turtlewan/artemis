---
spec: capability-metadata
status: ready
token_profile: lean
autonomy_level: L5
coder_effort: medium
---

# Spec: Capability metadata — add `goal`, `built_at`, `auth_status`, `oauth_scopes` once

**Identity:** Adds four capability-metadata fields (+ frontmatter/store/DTO plumbing) in ONE place, so `verify-auth-unverified-mark`, `oauth-3-invoke-integration`, and CB-5b consume them instead of three specs colliding on the same four files.
<!-- Consolidation decided 2026-07-03: two independent planning passes (OAuth, CB-5b) flagged that
     auth_status / oauth_scopes / goal / built_at all pile onto types.py + skill_md.py + store.py +
     capability_routes.py. Add the fields ONCE here; the logic stays in the dependent specs. -->

## Assumptions
- These are FIELD DEFINITIONS + plumbing only. The behavior that SETS them lives in the dependent specs: `auth_status` is computed at promote from required-secrets presence (verify-auth-unverified-mark) and flipped on first successful invoke; `oauth_scopes` is used to mint/inject a token (oauth-3); `goal`/`built_at` feed the CB-5b node card. This spec only makes the fields exist, persist, round-trip, and surface — with safe defaults → impact: Stop
- Fully additive + back-compat: a SKILL.md without these keys reads back as defaults (`goal=""`, `built_at=None`, `auth_status="not-required"`, `oauth_scopes=[]`). Zero migration of existing library capabilities → impact: Stop
- **`goal` has no source on the draft/promote path** — it lives on `BuildProposal.goal` / `ProposeRequest.goal`, not on `SkillDraft` or in `promote(staged_id)`. This spec defines the field with default `""`; POPULATING it needs a 1-line forge thread (pass the proposal's goal into promote/stage), which is assigned to CB-5b (the goal consumer) as a prerequisite note — NOT done here → impact: Caution
- `built_at` CAN be stamped at promote (`store.promote` has the moment) — this spec stamps it (ISO-8601 UTC string) → impact: Low
- `auth_status` is a `Literal["not-required","unverified","verified"]` defaulting to `not-required`; the promote-time computation is verify-auth's job, not this spec's → impact: Stop

Simplicity check: considered leaving each dependent spec to add its own field (rejected — three specs editing the same four files serialize or clobber; ADR-029). One additive metadata spec built first is the minimal coordination.

## Prerequisites
- none (build FIRST in the capability-metadata cluster; the three dependent specs then build after it).

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| src/artemis/types.py | modify | add 4 fields to `Skill` (defaults) |
| src/artemis/capabilities/skill_md.py | modify | `write_skill_md` gains the 4 params → frontmatter |
| src/artemis/capabilities/store.py | modify | `promote` writes them (+ stamps `built_at`); `_read_skill`/`_read_draft` read them back with defaults |
| src/artemis/api/capability_routes.py | modify | expose the fields on `InstalledCard` + `CapabilitySummary` (+ the `list_capabilities` mapping) |
| tests/capabilities/test_skill_md.py | modify | round-trip + absent-key defaults |
| tests/capabilities/test_store.py | modify | promote persists + reads back; built_at stamped; legacy SKILL.md → defaults |
| tests/api/test_capability_routes.py | modify | DTO carries the fields |

## Tasks
- [ ] Task 1: Add the fields to the models + frontmatter writer. In `src/artemis/types.py` add to `Skill`: `goal: str = ""`, `built_at: str | None = None`, `auth_status: Literal["not-required", "unverified", "verified"] = "not-required"`, `oauth_scopes: list[str] = Field(default_factory=list)`. **Also add `oauth_scopes: list[str] = Field(default_factory=list)` and `goal: str = ""` to `SkillDraft`** (both are threaded through staging — `oauth_scopes` is authored per-capability like `secrets`/`egress_domains`; `goal` is threaded from `BuildProposal.goal` by the forge, the 1-line population wiring being a cb5b-2 prerequisite note. `built_at`/`auth_status` are NOT on the draft — Skill-only, set at promote). In `src/artemis/capabilities/skill_md.py` add matching keyword params to `write_skill_md` (`goal: str`, `built_at: str | None`, `auth_status: str`, `oauth_scopes: list[str]`) and include them in the `meta` dict written to frontmatter (keep existing key order, append the new keys). `read_skill_md` is generic (returns the dict) — no change; readers apply defaults via `.get(...)`. — files: src/artemis/types.py, src/artemis/capabilities/skill_md.py, tests/capabilities/test_skill_md.py — done when: `Skill(...)` and `SkillDraft(...)` accept/default the fields; `write_skill_md(...)` writes all 4; a round-trip through `write`→`read_skill_md` preserves them, and a frontmatter dict missing the keys yields the defaults.
- [ ] Task 2: Persist + read them in the store. In `src/artemis/capabilities/store.py`: `stage` — pass `oauth_scopes=list(draft.oauth_scopes)` and `goal=draft.goal` into its `write_skill_md` (both threaded fields must survive staging; `built_at`/`auth_status` default at stage). `promote` — pass all 4 fields into `write_skill_md` and the returned `Skill` (`oauth_scopes`/`goal` from the draft; `auth_status` default `"not-required"` — dependent specs override; stamp `built_at` = `datetime.now(tz=UTC).isoformat()`). `_read_draft` reads `oauth_scopes` + `goal` with `.get(..., default)`; `_read_skill` reads all 4 with `.get(..., default)` so legacy SKILL.md files and staged v0 round-trip as defaults. — files: src/artemis/capabilities/store.py, tests/capabilities/test_store.py — done when: a staged then promoted capability's SKILL.md contains the 4 keys, its authored `oauth_scopes` survives stage→promote→`get()`, `built_at` is a non-empty ISO string, and a library SKILL.md written without the keys reads back as the defaults (no exception).
- [ ] Task 3: Expose on the API DTOs. In `src/artemis/api/capability_routes.py` add `auth_status: str`, `oauth_scopes: list[str]`, `goal: str`, `built_at: str | None` to `CapabilitySummary` (and `auth_status` + `built_at` to `InstalledCard`); map them from the `Skill` in `list_capabilities` (and `promote`'s `InstalledCard`). Keep defaults so a capability missing them still serializes. — files: src/artemis/api/capability_routes.py, tests/api/test_capability_routes.py — done when: `GET /app/capabilities` returns each capability's `auth_status`/`oauth_scopes`/`goal`/`built_at`, and the promote `InstalledCard` carries `auth_status`+`built_at`.

## Wave plan
Wave 1: [Task 1] | Wave 2: [Task 2] | Wave 3: [Task 3]
<!-- Sequential: Task 2 depends on Task 1's model+writer; Task 3 depends on Task 1's Skill fields. -->

## Permissions
### File Operations
| Action | Paths |
|--------|-------|
| Modify | src/artemis/types.py, src/artemis/capabilities/skill_md.py, src/artemis/capabilities/store.py, src/artemis/api/capability_routes.py, tests/capabilities/test_skill_md.py, tests/capabilities/test_store.py, tests/api/test_capability_routes.py |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy` · `uv run ruff check src/ tests/` · `uv run ruff format --check src/ tests/` · `uv run pytest -q` | host-verify |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | the files above + CHANGELOG.md |
| `git commit` | "feat(capabilities): add goal/built_at/auth_status/oauth_scopes metadata fields" |

## Specialist Context
### Security
No new secret/egress/credential flow — this spec only adds inert metadata fields with defaults. `auth_status`/`oauth_scopes` are populated with SECURITY-RELEVANT values by their dependent specs (verify-auth, oauth-3), which carry their own review; this spec's fields default to the safe/empty state. `oauth_scopes` and `auth_status` values are non-secret. No review gate on this spec.

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Changelog | CHANGELOG.md | Added — capability metadata fields (goal/built_at/auth_status/oauth_scopes) |

## Acceptance Criteria
- [ ] `Skill(name=..., ...)` with none of the 4 fields set → `goal==""`, `built_at is None`, `auth_status=="not-required"`, `oauth_scopes==[]`.
- [ ] `write_skill_md(...)` then `read_skill_md(...)` → the 4 fields round-trip; a frontmatter dict missing the keys → readers apply the defaults (no `KeyError`).
- [ ] `promote` → the library SKILL.md contains all 4 keys; `built_at` is a non-empty ISO-8601 UTC string; `get()`/`list()` return them.
- [ ] A hand-written legacy library SKILL.md (no new keys) → `get()` reads it back with the defaults, no exception (zero migration).
- [ ] `GET /app/capabilities` → each `CapabilitySummary` carries `auth_status`/`oauth_scopes`/`goal`/`built_at`; promote `InstalledCard` carries `auth_status`+`built_at`.
- [ ] `uv run mypy` clean; `uv run ruff check` clean; `uv run pytest -q` green.

## Progress
_(Coding mode writes here — do not edit manually)_
