---
spec: AGENT-rung01
status: draft
cross_model_review: true
token_profile: balanced
autonomy_level: L2
---

# Spec: AGENT-rung01 — Rung 0 read-only introspection + Rung 1 reversible file ops

**Identity:** The first two capability rungs as executor tools: Rung 0 read-only host introspection
(~no risk) and Rung 1 reversible, workspace-confined file ops (trash-not-delete) — both registered
into the ToolRegistry so the spine dispatches + the AuthorityGate classifies them (ADR-031 B/C).
<!-- → why: docs/technical/adr/ADR-031-...md (B ladder Rung 0/1, C authority) + docs/drafts/AGENT-engine-design.md. -->

## Assumptions
<!-- Coding mode verifies each item against the codebase before executing. -->
- Rung 0/1 are dev-box-safe (ADR-031 B/G Phase 2, "Dev now"). No network, no out-of-workspace writes → every Rung-0/1 tool classifies `IN_SANDBOX` under `AuthorityGate` (so they run automatically). → impact: Stop (a tool that crosses the boundary belongs to Rung 2, not here).
- Tools register into the existing `ToolRegistry` with the same `ToolSpec` shape modules/reactions use (async `callable_ref`, `args_schema`, fq name) — verify `src/artemis/manifest.py` `ToolSpec` + a module manifest (e.g. `modules/calendar/manifest.py`) and mirror it. → impact: Stop.
- Rung 1 is REVERSIBLE: writes/moves/deletes are confined to a declared `workspace_root` (path resolved + asserted under the root, fail-closed on traversal) and deletes go to a workspace-local trash dir (move-not-unlink), never `os.remove`. → impact: Stop (an unconfined or hard delete violates the rung's reversibility guarantee).
- Rung 0 introspection is strictly read-only (cwd, listdir, read text file, env-allowlist, process/OS info) — no mutation, no secrets (env reads are allowlisted, never dumping the full environment). → impact: Stop.
- Path confinement reuses any existing workspace/path helper if present (check `src/artemis/paths.py`); else implement a `resolve_within(root, candidate)` that rejects symlink/`..` escapes. → impact: Caution.

Simplicity check: considered separate Rung-0 and Rung-1 specs — bundled: they are one concern layer (host-introspection + reversible-file tools), share the workspace-confinement helper and the manifest registration, and are both "Dev now" Phase 2 with no cross-dependency; one spec keeps the path helper single-owned.

## Prerequisites
- Specs that must be complete first: **AGENT-types** (shared types), **AGENT-spine** (the executor that dispatches these tools) — Rung tools are exercised through the spine. (AuthorityGate classifies them; AGENT-authority is a sibling Prerequisite for the integration test.)
- Environment setup required: none (stdlib only).

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| `src/artemis/agentic/rungs/__init__.py` | create | Rungs package marker. |
| `src/artemis/agentic/rungs/introspect.py` | create | Rung 0 read-only tools + their ToolSpecs. |
| `src/artemis/agentic/rungs/fileops.py` | create | Rung 1 reversible workspace-confined file ops + `resolve_within` + trash-not-delete + ToolSpecs + a `register_rung01(registry, *, workspace_root)`. |
| `tests/test_agent_rungs.py` | create | introspection read-only; file ops confined + trash-not-delete; traversal rejected; tools register + classify IN_SANDBOX. |

### Path confinement helper (BLOCK — mechanism pinned; `paths.py` has none)
`resolve_within(root: Path, candidate: Path) -> Path`: call `root.resolve()` AND `candidate.resolve()` (follows symlinks for BOTH), then assert `resolved_candidate.is_relative_to(resolved_root)` — NEVER a string-prefix/component check (`/workspace/a/../../etc/passwd` defeats a prefix check). Any `OSError`/resolution failure → raise `PermissionError("path outside workspace")` (fail-closed). **The error message MUST NOT embed `resolved_candidate`/`resolved_root` or any path fragment** (invariant #8); the wrapping tool returns a generic refusal to the spine. Returns `resolved_candidate`.

### Rung 0 introspection (`introspect.py`)
- `host.cwd`, `host.os_info` — trivial read-only, `IN_SANDBOX`.
- `host.env_get(name)` — **allowlist ENUMERATED in-spec**: `{PATH, HOME, USERPROFILE, USERNAME, COMPUTERNAME, TEMP, TMP, APPDATA, LOCALAPPDATA, PWD, SHELL, LANG, LC_ALL, TERM, OS, PROCESSOR_ARCHITECTURE}`; **reject any name matching `*KEY*`/`*SECRET*`/`*TOKEN*`/`*PASSWORD*`/`*CREDENTIAL*`/`*AUTH*` (case-insensitive) even if somehow allowlisted**; a non-allowlisted name returns a fixed sentinel (`None`), does NOT raise (raising would leak recognition). `IN_SANDBOX`.
- `host.read_text(path)` — **caps at 64 KB (65 536 bytes); larger files return the first 64 KB + a trailing `[truncated: <size> bytes total]` sentinel** (bounds a prompt-injected large-file context-flood DoS on the 8 GB box). `host.list_dir(path)`. **Path scope (FLAG — exfil surface):** a target under `workspace_root` (via `resolve_within`) → `IN_SANDBOX` (auto); a target OUTSIDE the workspace → classified `BOUNDARY` by `AuthorityGate` (gated/ask), NOT auto — read-only + auto-run + arbitrary host path would otherwise be an unrestricted exfil surface under prompt injection (the read content can reach the planner/cloud). Host-wide diagnostic reads remain available, just owner-gated.

### Rung 1 file ops (`fileops.py`)
- `fs.write_text(path, content)`, `fs.mkdir(path)`, `fs.trash(path)` (move into `<workspace_root>/.agent_trash/<ts>-<name>`, NEVER `os.remove`/unlink), `fs.move(src, dst)` — **`fs.move` passes BOTH `src` AND `dst` through `resolve_within` before any fs op (note)**. All confined to `workspace_root` via `resolve_within`. `register_rung01(registry, *, workspace_root)` registers all tools (partials binding `workspace_root`) under fq `host.*`/`fs.*` names.
- Each tool's `args_schema` is a small frozen pydantic model; `callable_ref` is async (ADR-016).

## Tasks
- [ ] Task 1: Rung 0 introspection tools + ToolSpecs. — files: `src/artemis/agentic/rungs/__init__.py`, `src/artemis/agentic/rungs/introspect.py` — done when: `host.env_get` returns only the enumerated allowlist, rejects `*KEY*/*SECRET*/*TOKEN*/*PASSWORD*/*CREDENTIAL*/*AUTH*` (returns the `None` sentinel, never raises/leaks a secret); `host.read_text` caps at 64 KB with the truncation sentinel; in-workspace `read_text`/`list_dir` classify `IN_SANDBOX` while an out-of-workspace target classifies `BOUNDARY`; `uv run mypy` clean.
- [ ] Task 2: Rung 1 reversible file ops + hardened `resolve_within` + trash + `register_rung01`. — files: `src/artemis/agentic/rungs/fileops.py` — done when: `resolve_within` uses `Path.resolve()` on BOTH + `is_relative_to` (no prefix check) and raises a path-free `PermissionError` on escape; writes/mkdir/move resolve under `workspace_root`; `fs.move` validates BOTH src and dst; a `../`-normalising-outside target AND a symlink-escape are rejected (fail-closed); `fs.trash` moves into the workspace trash dir (recoverable; no `os.remove`); `register_rung01` puts all tools on the registry.
- [ ] Task 3: Tests (incl. an AuthorityGate classify check). — files: `tests/test_agent_rungs.py` — done when: env-allowlist+secret-rejection, read-text-cap, **`/workspace/a/../../etc/passwd`-style traversal rejected**, **symlink-target-outside rejected**, **`resolve_within` error leaks no path**, fs.move-both-endpoints, trash-not-delete, registration, in-workspace→IN_SANDBOX, **out-of-workspace read→BOUNDARY** assertions pass under `uv run pytest -q`.

## Wave plan
Wave 1: [Task 1, Task 2] | Wave 2: [Task 3]

## Permissions
The following actions will run autonomously during build. Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | `src/artemis/agentic/rungs/__init__.py`, `src/artemis/agentic/rungs/introspect.py`, `src/artemis/agentic/rungs/fileops.py`, `tests/test_agent_rungs.py` |
| Modify | (none) |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy` | Full-project type check. |
| `uv run ruff check . && uv run ruff format --check .` | Lint + format gate. |
| `uv run pytest -q` | Full test suite. |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | The four files above, by name. |
| `git commit` | "feat: AGENT-rung01 read-only introspection + reversible file ops (ADR-031 B Rung 0/1)" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| (allowlisted reads only) | `host.env_get` reads a fixed allowlist of non-secret names; never dumps the environment or returns secrets. |

### Network
| Action | Purpose |
|--------|---------|
| (none) | Rung 0/1 are offline by definition. |

## Specialist Context
### Security
`cross_model_review: true` — first host-reaching tools. Reviewer confirms: (1) Rung 0 is strictly read-only and `env_get` is allowlisted (no secret/full-env exposure); (2) Rung 1 is confined to `workspace_root` with fail-closed traversal rejection (no `..`/symlink escape); (3) deletes are trash-not-unlink (reversible); (4) all Rung-0/1 tools classify `IN_SANDBOX` (so the AuthorityGate auto-runs them) and none can perform a boundary crossing.

### Performance
(none.)

### Accessibility
(none — no frontend change.)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | `src/artemis/agentic/rungs/{introspect,fileops}.py` | Docstrings: read-only contract; workspace confinement; trash-not-delete. |
| ADR | (none) | ADR-031 records the ladder. |

## Acceptance Criteria
- [ ] Rung 0 read-only + env allowlist → verify: introspection tools return expected results; `env_get` returns only the enumerated allowlist and rejects secret-pattern names (sentinel, no raise/leak).
- [ ] Read cap → verify: `host.read_text` on a >64 KB file returns 64 KB + the truncation sentinel.
- [ ] Hardened confinement (BLOCK) → verify: `resolve_within` rejects a `..`-normalising-outside path AND a symlink-escape via `resolve()`+`is_relative_to`; the error carries no resolved path; `fs.move` validates both src and dst.
- [ ] Reversible delete → verify: `fs.trash` moves the file into the workspace trash dir (recoverable); no hard unlink.
- [ ] Classification → verify: `register_rung01` registers all tools; `host.cwd/os_info/env_get` + in-workspace `read_text/list_dir` + all `fs.*` classify `IN_SANDBOX`; an OUT-of-workspace `read_text/list_dir` target classifies `BOUNDARY` (gated, not auto).
- [ ] Whole project clean → verify: `uv run mypy`, `uv run ruff check . && uv run ruff format --check .`, `uv run pytest -q` all pass.

## Progress
_(Coding mode writes here — do not edit manually)_
