---
spec: js-fetch-output-limit
status: ready
token_profile: lean
autonomy_level: L5
coder_effort: high
---

# Spec: Configurable isolate output cap

**Identity:** Make the hardened WSL2 isolate's 4000-char output truncation configurable so a fetch capability can return full page text, not a verification-log-sized snippet.
→ why: see docs/technical/adr/ADR-040-js-rendering-fetcher.md

## Assumptions
- The isolate's `${OUT:0:4000}` truncation is the ONLY place output length is capped on the return path (verified: `_ISOLATE_SCRIPT` line ~225 + `_parse_isolate_output`'s `_OUTPUT_LIMIT`) → impact: Stop
- `OUTPUT_LIMIT` reaches the outer isolate bash via the same `WSLENV` env-passthrough the resource caps use (`MEM_MAX` etc.), and is read in the ROOT-side outer script (not the de-privileged inner command), so it is not a privilege concern → impact: Caution
- Raising the cap does not change memory safety: the returned `OUT` is already fully buffered by `proc.communicate()` and bounded by the cgroup `memory.max`; `OUTPUT_LIMIT` only controls how much of it is echoed back → impact: Low
- Leaving `FetchSandbox.run`'s default at 4000 preserves current invoke-path behaviour (only the JS fetcher opts into a larger cap) → impact: Caution

Simplicity check: considered having the render script itself cap output — rejected: the 4000 truncation happens in the isolate wrapper AFTER the capability prints, so a capability cannot raise its own ceiling; the cap must be a `run_isolated` parameter. This is the minimal change (one new threaded int).

## Prerequisites
- none (this is the prerequisite for `js-rendering-fetcher`)
- Environment setup required: none

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| src/artemis/capabilities/sandbox_wsl2.py | modify | parametrize the output cap through `run_isolated` + the isolate script + `_parse_isolate_output`; reserve the env name |
| src/artemis/capabilities/fetch_sandbox.py | modify | thread `output_limit` through `FetchSandbox.run` to `run_isolated` |
| tests/capabilities/test_sandbox_wsl2.py | modify | assert the cap is forwarded to env/script and drives the `truncated` flag; default preserved |
| tests/capabilities/test_fetch_sandbox.py | modify | assert `FetchSandbox.run` forwards `output_limit`; default preserved |

## Tasks
- [ ] Task 1: Parametrize the output cap in `sandbox_wsl2.py`. Rename module constant `_OUTPUT_LIMIT = 4000` → public `OUTPUT_LIMIT_DEFAULT = 4000`; add `OUTPUT_LIMIT_MAX = 1_000_000`. Add `output_limit: int = OUTPUT_LIMIT_DEFAULT` to `run_isolated`; clamp it to `[1, OUTPUT_LIMIT_MAX]`; set `env["OUTPUT_LIMIT"] = str(clamped)` and append `:OUTPUT_LIMIT` to the `cap_names` string in `_wsl_env`. In `_ISOLATE_SCRIPT`: (a) add an early default line `OUTPUT_LIMIT="${OUTPUT_LIMIT:-4000}"` before first use (immediately after the `SID=...`/`VETH_*` setup line, so `set -u` never sees it unset); (a2) immediately after that default, RE-VALIDATE at the consumption boundary — `[[ "$OUTPUT_LIMIT" =~ ^[0-9]+$ ]] || abort bad-output-limit` — mirroring the script's existing `EGRESS_CSV` domain re-validation, so a non-numeric value can never reach the `${OUT:0:$OUTPUT_LIMIT}` bash arithmetic/substring context (defense-in-depth even though the host already Python-clamps to a `str(int)`); (b) change the final `printf '%s\n%s' "${#OUT}" "${OUT:0:4000}"` to `"${OUT:0:$OUTPUT_LIMIT}"`. Add `"OUTPUT_LIMIT"` to `_RESERVED_ENV_NAMES`. Change `_parse_isolate_output` signature to `(stdout, stderr, output_limit: int = OUTPUT_LIMIT_DEFAULT)` and compare `original_len > output_limit`; have `run_isolated` call it with the clamped value. — files: src/artemis/capabilities/sandbox_wsl2.py — done when: `run_isolated(..., output_limit=200000)` sets `OUTPUT_LIMIT=200000` in the subprocess env and the script echoes up to that many chars; default call still caps at 4000.
- [ ] Task 2: Thread `output_limit` through the fetch pipe. Import `OUTPUT_LIMIT_DEFAULT` from `sandbox_wsl2`; add `output_limit: int = OUTPUT_LIMIT_DEFAULT` to `FetchSandbox.run` and forward it to `run_isolated`. — files: src/artemis/capabilities/fetch_sandbox.py — done when: `FetchSandbox.run` passes the caller's `output_limit` into `run_isolated`; omitting it forwards 4000.
- [ ] Task 3: Tests for both layers. In `test_sandbox_wsl2.py`: assert `run_isolated(output_limit=N)` puts `OUTPUT_LIMIT=str(N)` in the captured subprocess `env`, that `WSLENV` contains `OUTPUT_LIMIT`, that the value is clamped to `[1, OUTPUT_LIMIT_MAX]`, and that `_parse_isolate_output` uses the passed limit for the `truncated` flag; assert `"OUTPUT_LIMIT"` is rejected by `_validate_secret_name`. In `test_fetch_sandbox.py`: extend the AsyncMock `run_isolated` assertion to check `output_limit` is forwarded (explicit value and default). — files: tests/capabilities/test_sandbox_wsl2.py, tests/capabilities/test_fetch_sandbox.py — done when: new assertions pass and the existing suite is unchanged-green.

## Wave plan
Wave 1: [Task 1] | Wave 2: [Task 2] | Wave 3: [Task 3]

## Permissions

The following actions will run autonomously during build. Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | (none) |
| Modify | src/artemis/capabilities/sandbox_wsl2.py, src/artemis/capabilities/fetch_sandbox.py, tests/capabilities/test_sandbox_wsl2.py, tests/capabilities/test_fetch_sandbox.py |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/` | lint + format gate |
| `uv run mypy` | full-project strict type-check (files = src, evals, tests) |
| `uv run pytest -q` | full test suite |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | the four files above |
| `git commit` | "feat(sandbox): configurable isolate output cap for fetch capabilities" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `OUTPUT_LIMIT` | new WSLENV-passed isolate control var (set by `run_isolated`, read by the isolate script) |

### Network
| Action | Purpose |
|--------|---------|
| (none) | no new packages |

## Specialist Context
### Security
Reviewed surface (apex-security spec review, 2026-07-03 — no BLOCKs): `OUTPUT_LIMIT` is set by the host in the ROOT-side outer isolate script only, added to `_RESERVED_ENV_NAMES` so an untrusted capability cannot inject a secret of that name to influence truncation. Host-clamped `[1, 1_000_000]` AND re-validated numeric at the bash consumption site (Task 1 a2). It does not widen egress, privilege, or the mount/pid isolation — it only changes how many chars of already-captured output are returned.
- Host-volume ceiling (FLAG, accepted): raising the per-call cap from 4000 to ≤1 MB raises the guest→host stdout volume per invocation. Accepted because no caller opts into the max — the invoke path keeps the 4000 default and the only large-cap caller (`js-rendering-fetcher`'s `JsFetcher`) passes `output_limit=max_chars` (≈20 000) and runs behind the single-flight `WebTool`. `OUTPUT_LIMIT_MAX` stays a hard ceiling; large values should be reserved for concurrency-bounded callers.
- Downstream payload (note, accepted): larger untrusted output still flows through the existing ADR-009 dual-LLM quarantine; the fetch payload the reader sees (≈20 KB) is the same order as today's trafilatura `max_chars`, so no new quarantine-scaling concern.

### Performance
Larger returned output = more host memory per fetch (bounded by `OUTPUT_LIMIT_MAX` = 1 MB and the cgroup `memory.max`). No hot-loop impact.

### Accessibility
(none — no frontend change)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | src/artemis/capabilities/sandbox_wsl2.py | docstring on `run_isolated`'s new `output_limit` param |
| ADR | docs/technical/adr/ADR-040-js-rendering-fetcher.md | written by the sibling `js-rendering-fetcher` spec (this change is the substrate it references) |

## Acceptance Criteria
- [ ] Call `run_isolated(dir, ..., output_limit=200_000)` with a patched `create_subprocess_exec` → verify the captured `env["OUTPUT_LIMIT"] == "200000"` and `"OUTPUT_LIMIT" in env["WSLENV"]`.
- [ ] Call `run_isolated(dir, ...)` with no `output_limit` → verify `env["OUTPUT_LIMIT"] == "4000"` (default preserved).
- [ ] Pass `output_limit=5_000_000` → verify the env value is clamped to `"1000000"`; pass `0` → verify clamped to `"1"`.
- [ ] `_parse_isolate_output("120000\n" + "x"*4000, b"", output_limit=200_000)` → verify `truncated is False`; same input with `output_limit=4000` → verify `truncated is True`.
- [ ] `FetchSandbox().run(dir, entrypoint="f.py", argv=[], egress_domains=[], output_limit=200_000)` with mocked `run_isolated` → verify the mock received `output_limit=200000`; omitting it → verify it received `4000`.
- [ ] `_validate_secret_name("OUTPUT_LIMIT")` raises `ValueError` (reserved).
- [ ] `uv run mypy` clean; `uv run ruff check` clean; `uv run pytest -q` green (no regression in the existing sandbox/fetch suites).

## Progress
_(Coding mode writes here — do not edit manually)_
