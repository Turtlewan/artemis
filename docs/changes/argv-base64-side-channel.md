---
spec: argv-base64-side-channel
status: ready
token_profile: lean
autonomy_level: L5
coder_effort: high
---

# Spec: WSL argv via a base64 side-channel

**Identity:** Replace the shlex-quote-then-guest-decode WSL arg-passing (ADR-041 decision 5) with a base64 JSON blob templated into the stdin script — the same channel secrets already use — eliminating the Windows+WSL two-layer quoting dependence.
→ why: see docs/technical/adr/ADR-042-argv-base64-side-channel.md

<!-- This is a STURDIER-FOUNDATION refactor of a security boundary, NOT a bug fix. The defect is already
     fixed + verified-secure by `chrome-capable-fetch-sandbox` (ADR-041, shipped 2026-07-03). Build this
     only if the owner wants the durability insurance. It carries the SAME dual-pass apex-security wave
     review at build time — the isolate execution boundary changes again. -->

## Assumptions
- `sandbox_wsl2.py` already templates a base64 JSON blob into the stdin script for secrets (`_secrets_b64` + `__ARTEMIS_SECRETS_B64__`), decoded guest-side; this spec mirrors that exact, already-reviewed pattern for argv → impact: Stop
- Stdin (`bash -s`) is not subject to WSL argv mangling (the script itself already travels this way intact), so a blob templated into the script arrives byte-exact → impact: Stop
- `command`, `skill_wsl_path`, `run_id`, and the egress CSV are all JSON-serializable strings; `json.dumps`/`json.load` round-trips them exactly (including any shell metacharacter) → impact: Stop
- Removing the Python-side `shlex.quote()` calls orphans `import shlex` in the Python module (the secrets guest-side `python3` uses shlex inside the script string, not the Python import) — the import must be removed → impact: Caution
- The pre-existing `test_run_isolated_converts_wslpath_and_exports_caps` asserts the args arrive as `create_subprocess_exec` positionals; under this spec they no longer do, so that test MUST be updated (this is the expected ripple that made Option B a BIG fork; ADR-042) → impact: Stop
- `fetch_sandbox.py`, `js_fetch.py`, and the `caps_profile`/`RENDER_CAPS` work (ADR-041 decisions 1–4) are unaffected — this spec only changes how positional argv crosses into the isolate → impact: Stop

Simplicity check: the base64 channel has LESS conditional logic than the shlex round-trip it replaces (no content-dependent quoting, no `shlex.split` len-branching) — it is the simpler mechanism, not a more complex one. The only reason it did not ship first is the pre-existing-test ripple (a BIG fork the owner deferred while away).

## Prerequisites
- `chrome-capable-fetch-sandbox` (built + committed 2026-07-03, `8164ba0`) — this spec replaces the arg-quoting half of it; the `caps_profile`/`RENDER_CAPS` half stays.
- Environment for the live round-trip test only: WSL2 provisioned (this dev host is). Unit tests mock the subprocess and need no WSL2.

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| src/artemis/capabilities/sandbox_wsl2.py | modify | Python: build base64 argv blob, template into script, drop `shlex.quote()` + `import shlex`, pass no positionals. Guest: replace shlex decode with base64→JSON→NUL fail-closed decode. |
| tests/capabilities/test_sandbox_wsl2.py | modify | update the positional-args assertions to blob assertions; keep the live round-trip + fail-closed structural tests (updated to the base64 guards). |

## Tasks
- [ ] Task 1: Python-side — pass argv as a base64 blob. In `run_isolated` (`src/artemis/capabilities/sandbox_wsl2.py`): build `argv_list = [skill_wsl_path, ",".join(egress_domains), run_id, *command]`; `argv_b64 = base64.b64encode(json.dumps(argv_list).encode()).decode()`; and `argc = str(len(argv_list))`. Template BOTH into the script: `script = _ISOLATE_SCRIPT.replace("__ARTEMIS_SECRETS_B64__", blob).replace("__ARTEMIS_ARGV_B64__", argv_b64).replace("__ARTEMIS_ARGC__", argc)`. Change the `create_subprocess_exec` call to pass NO positionals after `bash -s` (drop the `"--"` and the four `quoted_*` args). Remove the four `quoted_*` lines and their WSL-interop comment. Remove `import shlex` (now unused in Python; confirm no other Python use with a grep — the secrets guest `python3 -c` string keeps its own `import shlex`, that is inside the script text, not a Python import). — files: src/artemis/capabilities/sandbox_wsl2.py — done when: `run_isolated` templates `argv_b64` + `argc` into the script and passes no positional args to `create_subprocess_exec`; `import shlex` is gone; mypy + ruff clean.
- [ ] Task 2: Guest-side — replace the shlex decode with a fail-closed base64 decode. In `_ISOLATE_SCRIPT`, replace the entire shlex round-trip block (from `_ARGC_IN=$#` through `unset _DECODED_ARGV _arg _ARGV_FILE _ARGC_IN`) with a base64 decode that mirrors the secrets pattern and keeps ADR-041's fail-closed guarantees:
  ```bash
  ARTEMIS_ARGV_B64='__ARTEMIS_ARGV_B64__'
  ARTEMIS_ARGC='__ARTEMIS_ARGC__'
  _ARGV_FILE="$(mktemp)" || abort argv-mktemp
  { printf '%s' "$ARTEMIS_ARGV_B64" | base64 -d | python3 -c '
  import json, sys
  out = sys.stdout.buffer
  for item in json.load(sys.stdin):
      out.write(item.encode("utf-8", "surrogateescape") + b"\0")
  '; } > "$_ARGV_FILE" || { rm -f "$_ARGV_FILE"; abort argv-decode; }
  _ARGV=()
  while IFS= read -r -d '' _a; do _ARGV+=("$_a"); done < "$_ARGV_FILE"
  rm -f "$_ARGV_FILE"
  [ "${#_ARGV[@]}" -eq "$ARTEMIS_ARGC" ] || abort argv-count-mismatch
  set -- "${_ARGV[@]}"
  unset _ARGV _a _ARGV_FILE
  ```
  Keep `abort()` defined above this block (as it is now). The `base64 -d | python3` pipeline runs under `set -euo pipefail` with `pipefail`, so a base64-decode failure, a `json.load` failure, or a `python3` crash all make the pipeline non-zero → `|| abort` (fail closed). `surrogateescape` prevents any non-UTF8 byte from crashing the encode. The `ARTEMIS_ARGC` check rejects any truncation. — files: src/artemis/capabilities/sandbox_wsl2.py — done when: the guest script decodes the argv blob into positionals fail-closed, with no `shlex` usage in the decode.
- [ ] Task 3: Update tests. In `tests/capabilities/test_sandbox_wsl2.py`: (a) rewrite `test_run_isolated_converts_wslpath_and_exports_caps` — the args are no longer `create_subprocess_exec` positionals, so assert instead that the stdin payload contains `__ARTEMIS_ARGV_B64__` replaced by a blob that base64/JSON-decodes to `[expected_wsl_path, "api.example.com", run_id, "python3", "-m", "pytest"]`, and that `created[0]` ends at `"bash", "-s"` with no trailing positionals; keep the caps-env assertions. (b) Replace the mocked `test_run_isolated_quotes_command_tokens_for_wsl_interop` with a mocked test asserting a metacharacter-containing command token (`.../Python_(programming_language)`) round-trips through the base64 blob (decode the templated blob, assert the token is present verbatim). (c) Update `test_argv_decode_block_is_fail_closed` structural pins to the base64 guards: assert `abort argv-decode`, `abort argv-count-mismatch`, `abort argv-mktemp`, `surrogateescape`, and `base64 -d | python3` are present, and `< <(python3` is absent. (d) Keep `test_live_command_argument_round_trips_shell_metacharacters` unchanged (behavior is identical; it must still pass live). — files: tests/capabilities/test_sandbox_wsl2.py — done when: all updated assertions pass and the live round-trip test still passes on the provisioned host.

## Wave plan
Wave 1: [Task 1, Task 2] | Wave 2: [Task 3]
<!-- Tasks 1 and 2 both edit sandbox_wsl2.py (same file) — run sequentially within the wave, not in parallel; grouped only because they are one coherent mechanism swap. Task 3 (tests) follows. In practice: do Task 1+2 as one edit pass, then Task 3. -->

## Permissions

The following actions will run autonomously during build. Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | (none) |
| Modify | src/artemis/capabilities/sandbox_wsl2.py, tests/capabilities/test_sandbox_wsl2.py |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/` | lint + format gate |
| `uv run mypy` | full-project strict type-check |
| `uv run pytest -q` | full suite (live round-trip auto-runs on this WSL2 host) |
| `uv run pytest tests/capabilities/test_sandbox_wsl2.py -q` | targeted sandbox suite incl. live round-trip |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | the two modified files + CHANGELOG.md |
| `git commit` | "refactor(sandbox): pass WSL argv via base64 side-channel (ADR-042)" |

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
**Carries a mandatory dual-pass apex-security wave review at build time** — this changes the isolate execution boundary again (the filename `sandbox_wsl2.py` does NOT match the mechanical wave-review substring triggers, so the builder must dispatch the dual-pass review explicitly, exactly as `chrome-capable-fetch-sandbox` Task 1 did).

Invariants to preserve (from ADR-036/041): the decode runs fail-closed under `set -euo pipefail` (base64/JSON/python3 failure → `abort`; `surrogateescape` → no non-UTF8 crash; `ARTEMIS_ARGC` count check → no truncation); no decoded value is re-passed through a shell-eval context (only `set -- "${_ARGV[@]}"` array expansion, never `eval`); the egress-allowlist validation, de-privilege chain, secrets block, and `OUTPUT_LIMIT` handling are untouched and run after a faithful argv reconstruction. The base64 blob is our OWN trusted encoding (not attacker-supplied framing), so there is no shlex round-trip heuristic to misfire.

### Performance
Negligible: one extra base64+JSON encode/decode per isolate run (microseconds vs the ~2s render). No change to the resource envelope.

### Accessibility
(none — no frontend change)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | src/artemis/capabilities/sandbox_wsl2.py | comment the base64 argv channel (mirror the secrets-block comment style); note it supersedes the ADR-041 shlex mechanism |
| Changelog | CHANGELOG.md | add entry under Unreleased/Changed (argv now via base64 side-channel) |
| ADR | docs/technical/adr/ADR-042-argv-base64-side-channel.md | already written at planning (2026-07-03); flip its Status Proposed→Accepted when the build is greenlit |

## Acceptance Criteria
- [ ] `run_isolated(tmp_path, egress_domains=["api.example.com"], caps=SandboxCaps(), command=["python3", "-m", "pytest"], timeout_s=20)` with a mocked `create_subprocess_exec` → verify `created[0]` is exactly `("wsl.exe", "-u", "root", "--", "bash", "-s")` (no positionals after `-s`), and the stdin payload's `__ARTEMIS_ARGV_B64__` substitution base64/JSON-decodes to `[_to_wsl_path(tmp_path), "api.example.com", <run_id>, "python3", "-m", "pytest"]`.
- [ ] A command token containing shell metacharacters (`https://en.wikipedia.org/wiki/Python_(programming_language)`) → verify it appears verbatim in the base64/JSON-decoded argv (no quoting, no corruption).
- [ ] `import shlex` is absent from `src/artemis/capabilities/sandbox_wsl2.py`'s Python imports (the secrets guest `python3 -c` string may still contain `import shlex` inside the script text) → verify via grep that no top-level `^import shlex` remains.
- [ ] `test_argv_decode_block_is_fail_closed` (updated) → verify `_ISOLATE_SCRIPT` contains `abort argv-decode`, `abort argv-count-mismatch`, `abort argv-mktemp`, `encode("utf-8", "surrogateescape")`, and `base64 -d`, and does NOT contain `< <(python3`.
- [ ] LIVE (auto-runs on this WSL2 host via `live_wsl`): `test_live_command_argument_round_trips_shell_metacharacters` still passes — `command=[..., "a (b) c; echo x"]` → `output.strip() == "a (b) c; echo x"`.
- [ ] Dual-pass apex-security wave review of the changed `sandbox_wsl2.py` → both passes CLEAN (or FLAGs resolved) before commit.
- [ ] `uv run mypy` clean; `uv run ruff check` clean; `uv run pytest -q` green (414+ passed, live round-trip ran).

## Progress
_(Coding mode writes here — do not edit manually)_
