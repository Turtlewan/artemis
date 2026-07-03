---
spec: sandbox-policy-caps-bound
status: ready
token_profile: lean
autonomy_level: L5
coder_effort: medium
---

# Spec: Bound the policy-driven sandbox caps

**Identity:** Clamp capability-supplied `sandbox_policy.json` resource caps to sane upper bounds so a capability cannot request an unbounded resource envelope through the `Wsl2SandboxRunner.run_tests` verify path (apex-security note, 2026-07-03).

## Assumptions
- `_policy_for` (`src/artemis/capabilities/sandbox_wsl2.py`) reads `sandbox_policy.json` and builds `SandboxCaps` via `_int_from_policy`/`_float_from_policy`, which only floor via a default fallback — there is NO upper bound, so a policy with `memory_mb: 999999` is honored → impact: Stop
- The fix clamps at the UNTRUSTED policy path only (`_policy_for`), not on the `SandboxCaps` model — so `RENDER_CAPS` (1536 MB / cpu_pct 400 / pids 256) and all in-code `SandboxCaps(...)` constructions stay valid, and no pydantic `ValidationError` handling is needed in `_policy_for` → impact: Stop
- Chosen ceilings are safely above `RENDER_CAPS`: `memory_mb ≤ 4096`, `cpu_pct ≤ 800`, `pids_max ≤ 1024`, `timeout_s ≤ 300.0` (matches `fetch_sandbox._MAX_TIMEOUT_S`) → impact: Caution

Simplicity check: considered `Field(gt=0, le=…)` bounds on `SandboxCaps` — rejected: `_policy_for` doesn't catch `ValidationError` (only OSError/JSONDecodeError), so an over-large policy would crash instead of degrade; clamping at `_policy_for` is the smaller, fail-safe change and leaves the trusted `RENDER_CAPS` path untouched.

## Prerequisites
- none, BUT: touches `src/artemis/capabilities/sandbox_wsl2.py` + `tests/capabilities/test_sandbox_wsl2.py` — the SAME files as `argv-base64-side-channel`. Do NOT build these two concurrently; sequence them (either order; each rebases on the other).

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| src/artemis/capabilities/sandbox_wsl2.py | modify | add `_POLICY_MAX_*` ceiling constants; clamp each policy-supplied cap to its ceiling in `_policy_for` |
| tests/capabilities/test_sandbox_wsl2.py | modify | test that an over-large policy clamps to the ceilings |

## Tasks
- [ ] Task 1: Add ceiling constants + clamp in `_policy_for` (`src/artemis/capabilities/sandbox_wsl2.py`). Define module-level constants near the other limits: `_POLICY_MAX_MEMORY_MB = 4096`, `_POLICY_MAX_CPU_PCT = 800`, `_POLICY_MAX_PIDS = 1024`, `_POLICY_MAX_TIMEOUT_S = 300.0`. In `_policy_for`, wrap each cap in `min(...)` against its ceiling: `memory_mb=min(_int_from_policy(raw.get("memory_mb"), default_caps.memory_mb), _POLICY_MAX_MEMORY_MB)` and likewise for `cpu_pct`, `pids_max`, `timeout_s`. Leave `_int_from_policy`/`_float_from_policy` signatures unchanged (clamp at the call site). — files: src/artemis/capabilities/sandbox_wsl2.py — done when: `_policy_for` never returns a cap above its ceiling regardless of policy input.
- [ ] Task 2: Test in `tests/capabilities/test_sandbox_wsl2.py`. Write a `sandbox_policy.json` with over-large values (`memory_mb: 999999, cpu_pct: 99999, pids_max: 99999, timeout_s: 99999`) into a tmp dir → `_policy_for(tmp)` → assert `caps == SandboxCaps(memory_mb=4096, cpu_pct=800, pids_max=1024, timeout_s=300.0)`. Also confirm a within-bounds policy (e.g. the existing `test_policy_present_parses_egress_and_caps` fixture) still parses unchanged (no clamping of legal values). — files: tests/capabilities/test_sandbox_wsl2.py — done when: over-large policy clamps to ceilings; legal policy unaffected.

## Wave plan
Wave 1: [Task 1] | Wave 2: [Task 2]

## Permissions
### File Operations
| Action | Paths |
|--------|-------|
| Modify | src/artemis/capabilities/sandbox_wsl2.py, tests/capabilities/test_sandbox_wsl2.py |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy` · `uv run ruff check src/ tests/` · `uv run pytest -q` | host-verify |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | the two files above + CHANGELOG.md |
| `git commit` | "fix(sandbox): clamp policy-supplied resource caps to sane ceilings" |

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Changelog | CHANGELOG.md | Fixed — bound `sandbox_policy.json` resource caps |

## Acceptance Criteria
- [ ] `sandbox_policy.json` with `{memory_mb: 999999, cpu_pct: 99999, pids_max: 99999, timeout_s: 99999}` → `_policy_for(dir).caps == SandboxCaps(memory_mb=4096, cpu_pct=800, pids_max=1024, timeout_s=300.0)`.
- [ ] A within-ceiling policy (e.g. `memory_mb: 256, cpu_pct: 50, pids_max: 64, timeout_s: 12.5`) parses to those exact values (no clamping of legal input).
- [ ] `RENDER_CAPS` unchanged and all existing sandbox tests pass; `uv run mypy` / `ruff` clean; `uv run pytest -q` green.

## Progress
_(Coding mode writes here — do not edit manually)_
