---
spec: chrome-capable-fetch-sandbox
status: ready
token_profile: lean
autonomy_level: L5
coder_effort: high
---

# Spec: Chrome-capable `FetchSandbox` (arg-quoting fix + opt-in render caps profile)

**Identity:** Fixes the two isolate-substrate defects blocking `js-rendering-fetcher`'s live smoke — WSL arg-quoting and a closed, opt-in render resource-caps profile on `FetchSandbox.run`.
→ why: see docs/technical/adr/ADR-041-fetch-sandbox-render-caps.md

## Assumptions
- The two defects and their fixes are already diagnosed and confirmed end-to-end (real render, exit 0) via host-side scratchpad debugging (`docs/progress/js-rendering-fetcher.md`) — this spec codifies the confirmed fix, it does not re-diagnose → impact: Stop
- **Arg-quoting mechanism:** `shlex.quote()` on args passed to a shell-less `create_subprocess_exec` call looks like a no-op in isolation — the fix is necessary because WSL's own interop layer reconstructs the post-`--` argv into a single command line and re-parses it via `/bin/bash -c` semantics before invoking the guest `bash -s` (a shell-reinterpretation step inside `wsl.exe` itself, not visible in the Python call site). This was empirically proven via a live round-trip against the real isolate (2026-07-03 scratchpad debug), not theorized — this spec adds an automated live regression test reproducing that proof (Task 1), not only a mocked call-site assertion → impact: Stop
- `shlex.quote()` on the positional args is a no-op for every string already used by the current test suite (no shell-special characters in `tmp_path`-derived WSL paths, `api.example.com`-style egress domains, or `python3 -m pytest`-style commands) — so the existing `test_run_isolated_converts_wslpath_and_exports_caps` test in `tests/capabilities/test_sandbox_wsl2.py` continues to pass unmodified → impact: Caution
- `unlimited_vsz=True` only changes the `ULIMIT_V` env value passed to the isolate script; it does not change cgroup `memory.max` enforcement (the real RAM ceiling). It does deliberately drop the `render` profile from two independent RAM backstops (ulimit -v + cgroup memory.max) to one (cgroup memory.max only), because RLIMIT_AS is incompatible with Chrome/V8's virtual-memory reservation behavior — an accepted, explicit trade-off (ADR-041 decision 2), not an oversight → impact: Stop
- `FetchSandbox.run`'s new `caps_profile` param is closed to `Literal["default", "render"]` (not an open `SandboxCaps` override) — `"default"` reproduces today's hardcoded `SandboxCaps()` exactly, so `invoke.py` and `api/app.py` (existing callers) need no changes → impact: Stop
- This spec does NOT wire `JsFetcher` to use `caps_profile="render"` and does NOT re-run the `js-rendering-fetcher` live smoke — that one-line wiring + smoke re-run is a follow-up amendment to `docs/changes/js-rendering-fetcher.md`, kept out of this spec to keep the security-reviewed surface minimal → impact: Caution

Simplicity check: considered raising the global default `SandboxCaps()` instead of adding an opt-in profile — rejected (ADR-041 decision 3): every other sandboxed capability would pay a larger resource cost for no benefit; the render workload is the outlier. Considered exposing a generic `caps: SandboxCaps | None` override — rejected after apex-security review (ADR-041 decision 1): an open override lets any future caller request an unreviewed, unbounded envelope; a closed `Literal["default", "render"]` is simpler code and closes that gap.

## Prerequisites
- Specs that must be complete first: none
- Environment setup required: none for the build/unit-test gate. Task 1's live regression test uses the file's existing `live_wsl` pytest fixture (already used by `test_live_no_network_default_blocks_egress` etc.) — it auto-skips if WSL2 isn't provisioned, and runs for real (proving the fix) on this dev host, which already has WSL2 provisioned.

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| src/artemis/capabilities/sandbox_wsl2.py | modify | `shlex.quote()` positional args in `run_isolated`; add `SandboxCaps.unlimited_vsz`; add `RENDER_CAPS` constant; update `_caps_env` |
| src/artemis/capabilities/fetch_sandbox.py | modify | `FetchSandbox.run` gains closed `caps_profile: Literal["default", "render"] = "default"` param |
| tests/capabilities/test_sandbox_wsl2.py | modify | tests for arg-quoting (mocked + live round-trip) and `unlimited_vsz` / `RENDER_CAPS` |
| tests/capabilities/test_fetch_sandbox.py | modify | tests for `caps_profile` default + `"render"` forwarding |

## Tasks
<!-- TDD: each task ships its implementation WITH its tests (same task, same files). -->
- [ ] Task 1: Fix WSL arg-quoting in `run_isolated` + its tests. Add `import shlex` to `src/artemis/capabilities/sandbox_wsl2.py`. In `run_isolated`, before the `asyncio.create_subprocess_exec` call, apply `shlex.quote()` to each of: `skill_wsl_path`, `",".join(egress_domains)`, `run_id`, and every item in `command` (build `quoted_command = [shlex.quote(arg) for arg in command]` and pass `*quoted_command`). Do not quote the fixed literal args (`"wsl.exe"`, `"-u"`, `"root"`, `"--"`, `"bash"`, `"-s"`, `"--"`). Add a one-line comment at the quoting call site citing the WSL-interop `/bin/bash -c` reconstruction mechanism (see `## Assumptions` above) so a future reader doesn't mistake this for a redundant no-op. Tests in `tests/capabilities/test_sandbox_wsl2.py`: (a) a mocked test (reuse the existing `fake_create_subprocess_exec`/`monkeypatch.setattr(asyncio, "create_subprocess_exec", ...)` pattern) asserting a `command` token containing shell metacharacters (e.g. `"https://en.wikipedia.org/wiki/Python_(programming_language)"`) arrives in the captured argv as `shlex.quote(...)`-wrapped, not raw; (b) a NEW live-gated round-trip test using the existing `live_wsl` fixture: call `run_isolated` with `command=["python3", "-c", "import sys; print(sys.argv[1])", "a (b) c; echo x"]` against the real isolate and assert `code == 0` and `output.strip() == "a (b) c; echo x"` — proves the value survives the real WSL/bash boundary intact, not just that `shlex.quote()` was called; (c) confirm the existing `test_run_isolated_converts_wslpath_and_exports_caps` test (unmodified) still passes. — files: src/artemis/capabilities/sandbox_wsl2.py, tests/capabilities/test_sandbox_wsl2.py — done when: all three tests in (a)-(c) pass, and (b) fails against the pre-fix code (real isolate reports a shell syntax error / SIGTRAP-adjacent failure or a corrupted argv[1]) and passes against the fixed code.
- [ ] Task 2: Add the opt-in render caps profile to `sandbox_wsl2.py` + its tests. Add `unlimited_vsz: bool = False` field to `SandboxCaps` (after `timeout_s`). In `_caps_env`, change the `"ULIMIT_V"` line to: `"unlimited" if caps.unlimited_vsz else str(max(1, caps.memory_mb) * 1024)`. Add a module-level constant directly below the `SandboxCaps` class: `RENDER_CAPS = SandboxCaps(memory_mb=1536, cpu_pct=400, pids_max=256, unlimited_vsz=True)`, with a docstring/comment noting it is the spike-confirmed chrome-headless-shell profile (1.5GB RAM / 4 CPU / 256 pids / unlimited VSZ) and referencing ADR-041, including the explicit note that it intentionally relies solely on cgroup `memory.max` for RAM containment (the ulimit -v backstop is disabled for this profile). Tests in `tests/capabilities/test_sandbox_wsl2.py`: (a) `SandboxCaps().unlimited_vsz is False` (default unchanged); (b) `_caps_env(SandboxCaps(memory_mb=1536, cpu_pct=400, pids_max=256, unlimited_vsz=True))` returns `{"MEM_MAX": str(1536*1024*1024), "CPU_MAX": "400000 100000", "PIDS_MAX": "256", "ULIMIT_V": "unlimited", ...}`; (c) `RENDER_CAPS == SandboxCaps(memory_mb=1536, cpu_pct=400, pids_max=256, unlimited_vsz=True, timeout_s=60.0)`. — files: src/artemis/capabilities/sandbox_wsl2.py, tests/capabilities/test_sandbox_wsl2.py — done when: all three assertions in (a)-(c) pass.
- [ ] Task 3: Add a closed `caps_profile` param to `FetchSandbox.run` + its tests. In `src/artemis/capabilities/fetch_sandbox.py`, import `RENDER_CAPS` alongside the existing `sandbox_wsl2` imports. Add `from typing import Literal` (or `from __future__ import annotations`-compatible equivalent already in file). Change `FetchSandbox.run`'s signature to add `caps_profile: Literal["default", "render"] = "default"` as a keyword-only param (after `secrets`, before `output_limit`). Inside `run`, resolve `caps = RENDER_CAPS if caps_profile == "render" else SandboxCaps()` and pass `caps=caps` to `run_isolated(...)` (replacing the hardcoded `caps=SandboxCaps()`). Update the `run` docstring: "`caps_profile` selects a closed, reviewed resource-caps profile: `\"default\"` (512MB/1-CPU, today's behavior) or `\"render\"` (1.5GB/4-CPU, for chrome-class workloads — see ADR-041). No arbitrary `SandboxCaps` override is accepted." Tests in `tests/capabilities/test_fetch_sandbox.py`: (a) `test_run_uses_default_caps_profile_when_omitted` — call `FetchSandbox().run(...)` with no `caps_profile` arg (mock `run_isolated` as the file already does), assert `mock.await_args.kwargs["caps"] == SandboxCaps()`; (b) `test_run_forwards_render_caps_profile` — call with `caps_profile="render"`, assert `mock.await_args.kwargs["caps"] == RENDER_CAPS` (import `RENDER_CAPS` from `artemis.capabilities.sandbox_wsl2`). — files: src/artemis/capabilities/fetch_sandbox.py, tests/capabilities/test_fetch_sandbox.py — done when: both assertions in (a)-(b) pass.

## Wave plan
Wave 1: [Task 1] | Wave 2: [Task 2] | Wave 3: [Task 3]
<!-- Sequential, not parallel: Task 1 and Task 2 both modify sandbox_wsl2.py + test_sandbox_wsl2.py (not file-disjoint, ADR-029); Task 3 depends on Task 2's RENDER_CAPS existing. -->

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
| `uv run mypy` | full-project strict type-check |
| `uv run pytest -q` | full suite (Task 1's live round-trip test auto-runs on this WSL2-provisioned host, auto-skips elsewhere) |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | the modified files above + CHANGELOG.md |
| `git commit` | "fix(sandbox): quote WSL interop args + closed opt-in render caps profile" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| (none) | no new environment variables |

### Network
| Action | Purpose |
|--------|---------|
| (none) | no new packages, no network calls |

## Specialist Context
### Security
Dispatched apex-security review (2026-07-03) — 1 BLOCK + 2 FLAGs, resolved:
- **BLOCK (arg-quoting fix backed only by a mocked, tautological test) — FIXED in Task 1.** A mocked assertion that `shlex.quote()` output appears in captured argv proves the code calls `shlex.quote()`, not that the real WSL/bash boundary handles it correctly. Task 1 adds a live round-trip regression test (gated by the existing `live_wsl` fixture) that proves a shell-metacharacter string survives `run_isolated` intact against the real isolate — reproducing the diagnosis's manual scratchpad proof as an automated, repeatable test. The spec's `## Assumptions` also now states the WSL-interop `/bin/bash -c` reconstruction mechanism explicitly, so the fix isn't mistaken for a no-op by a future reader.
- **FLAG (open `caps: SandboxCaps | None` param would let any future caller request an unreviewed envelope) — FIXED in Task 3.** Closed to `caps_profile: Literal["default", "render"]`; no arbitrary `SandboxCaps` instance reaches the public `FetchSandbox.run` API. ADR-041 decision 1 revised to match.
- **FLAG (disabling the `ulimit -v` backstop for the render profile wasn't explicitly called out as an accepted trade-off) — FIXED.** Explicit trade-off statement added to Task 2's `RENDER_CAPS` docstring, this Security section, and ADR-041 decision 2: the `render` profile intentionally relies solely on cgroup `memory.max` for RAM containment; the RLIMIT_AS/`ulimit -v` backstop is disabled because it is incompatible with Chrome/V8's virtual-memory reservation behavior.
- **Note (pre-existing `sandbox_policy.json` path already accepts unbounded numeric caps) — accepted, out of scope.** `Wsl2SandboxRunner.run_tests`'s `_policy_for`/`_int_from_policy`/`_float_from_policy` path is a different, unmodified entry point from the one this spec closes (`FetchSandbox.run`'s `caps_profile`). Flagged in ADR-041 Consequences as a future follow-up; not fixed here (surgical scope — this spec's Files to Change don't include that path).
- **Note (render profile's 4-CPU grant can contend with concurrent sandboxed runs on the dev box) — accepted, informational.** See Performance section below.

Standing invariants carried from ADR-036: egress-allowlist, de-privileged uid, and mount/pid namespace isolation are unchanged by this spec. `unlimited_vsz` affects only the `ulimit -v` value passed into the isolate script; the enforced RAM ceiling remains cgroup `memory.max` (`MEM_MAX` env, set from `caps.memory_mb`), which neither profile bypasses. The arg-quoting fix (Task 1) is a hardening, not a new capability — no behavior change for any caller passing well-formed args.

### Performance
The `render` caps profile may consume up to 1.5GB RAM / 4 CPU cores for the duration of one sandboxed run (vs 512MB/1-CPU default) — bounded by the existing `FetchSandbox.run` `timeout_s` (clamped to 300s) and cgroup caps. Expect CPU contention if a `render`-profile run executes concurrently with other sandboxed capability runs on this dev box. No change to any capability using the `"default"` profile.

### Accessibility
(none — no frontend change)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | src/artemis/capabilities/sandbox_wsl2.py, src/artemis/capabilities/fetch_sandbox.py | docstring/comment updates on `RENDER_CAPS`, `SandboxCaps.unlimited_vsz`, the arg-quoting mechanism, and `FetchSandbox.run`'s `caps_profile` param |
| Changelog | CHANGELOG.md | add entry under Unreleased (WSL arg-quoting fix + closed opt-in render caps profile) |
| ADR | docs/technical/adr/ADR-041-fetch-sandbox-render-caps.md | already written at planning (2026-07-03) — build only cross-references it |

## Acceptance Criteria
- [ ] `run_isolated(tmp_path, egress_domains=[], caps=SandboxCaps(), command=["python3", "-c", "print('a(b)c')"], timeout_s=20)` with a mocked `asyncio.create_subprocess_exec` → verify the captured argv contains `shlex.quote(...)`-wrapped values for the command token, not the raw unquoted string.
- [ ] Live (auto-runs on this WSL2-provisioned host, auto-skips elsewhere via `live_wsl`): `run_isolated(tmp_path, egress_domains=[], caps=SandboxCaps(timeout_s=20.0), command=["python3", "-c", "import sys; print(sys.argv[1])", "a (b) c; echo x"], timeout_s=30.0)` → verify `code == 0` and `output.strip() == "a (b) c; echo x"` (exact round-trip against the real isolate, no shell syntax error, no corruption).
- [ ] The pre-existing `test_run_isolated_converts_wslpath_and_exports_caps` test (unmodified) still passes → verify quoting is a no-op for the existing safe-string test fixtures.
- [ ] `SandboxCaps(unlimited_vsz=True)` → verify `_caps_env(...)["ULIMIT_V"] == "unlimited"`; `SandboxCaps()` (default) → verify `_caps_env(...)["ULIMIT_V"] == str(512 * 1024)` (unchanged from today).
- [ ] `RENDER_CAPS` → verify it equals `SandboxCaps(memory_mb=1536, cpu_pct=400, pids_max=256, unlimited_vsz=True, timeout_s=60.0)`.
- [ ] `await FetchSandbox().run(tmp_path, entrypoint="f.py", argv=[], egress_domains=[])` (no `caps_profile` arg, `run_isolated` mocked) → verify `run_isolated` is awaited with `caps=SandboxCaps()`.
- [ ] `await FetchSandbox().run(tmp_path, entrypoint="f.py", argv=[], egress_domains=[], caps_profile="render")` (`run_isolated` mocked) → verify `run_isolated` is awaited with `caps=RENDER_CAPS`.
- [ ] `uv run mypy` clean; `uv run ruff check` clean; `uv run pytest -q` green.

## Progress
- [x] Task 1 — WSL arg-quoting fix + tests. DONE. Codex built the Python-side `shlex.quote()` + tests; it also added a required guest-side decode block (the spec's shlex.quote()-alone assumption was incomplete — WSL's two-layer quoting means quotes arrive at the guest literally and must be stripped; proven via host probes `/tmp/wsl_probe*.py`). Dual-pass apex-security review BLOCKed the decode as fail-OPEN (process-sub swallows python3 crashes; non-UTF8 crash; truncation runs a different command). Hardened inline to fail-closed (plain pipeline+`|| abort`, `surrogateescape`, argv-count check, dropped the fragile heuristic; `abort()` moved to script top). Re-review dual-pass → both CLEAN. Live round-trip test PASSED for real. See docs/progress/chrome-capable-fetch-sandbox.md for the full fork write-up + the Option-B follow-up recommendation.
- [x] Task 2 — render caps profile. DONE (built inline, Opus). `SandboxCaps.unlimited_vsz` field, `RENDER_CAPS` constant, `_caps_env` ULIMIT_V ternary. 3 tests added. 41 sandbox tests pass.
- [x] Task 3 — `FetchSandbox.run(caps_profile=...)`. DONE (built inline, Opus). Closed `Literal["default","render"]` param resolving to `SandboxCaps()`/`RENDER_CAPS`. 2 tests added.

### Deviations (SMALL, logged)
| Task | Decision | Reason | Review needed? |
|------|----------|--------|----------------|
| Task 1 | Kept + hardened Codex's guest-side decode block (spec specified shlex.quote() alone). | The spec's Assumption 2 was incomplete — quoting alone leaves literal quotes in the values (proven via host probes); a guest-side decode is genuinely required. Dual-pass apex-security reviewed the hardened version → both CLEAN. | Resolved via review |
| Task 3 | Synced 3 out-of-spec test stubs (`tests/reachout/test_js_fetch.py`, `tests/capabilities/test_invoke.py`, `tests/api/test_ask_routes.py`) that subclass `FetchSandbox.run`. | The in-scope `caps_profile` signature change broke their `[override]` signatures (mypy). Same recurring mechanical sync the prior `js-fetch-output-limit` spec's Files-to-Change under-listed. `test_js_fetch.py` belongs to the sibling `js-rendering-fetcher` spec — its stub edit stays with that spec's uncommitted (untracked) files; the other two commit with this spec. | No (mechanical) |
| — | Owner A/B fork answered as A (harden in place), not B (base64 side-channel), because owner was away and B is a BIG fork. | Fork protocol: don't implement a BIG fork (changes spec approach) unilaterally while owner absent. B logged as a recommended follow-up. | Owner to decide on B follow-up ⚠️ |
