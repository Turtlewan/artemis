---
spec: invoke-sandbox-secrets-guard
status: done
token_profile: balanced
autonomy_level: L2
coder_model: codex
coder_effort: high
risk: high
---

# Spec: Missing-key run-guard + WSL2 secrets injection (invoke/reuse path)

**Identity:** Two prerequisites for running a promoted capability: (1) a presence-only check of a
capability's required secret NAMES against the cred-store, and (2) runtime injection of secret
VALUES into the WSL2 isolate as environment variables scoped to ONLY the final `python3
<entrypoint>` process — never argv, never logged, never seen by the isolate's own setup shell,
nginx, or dnsmasq. Fourth of 5 for the capability invoke/reuse path.
→ why: see docs/technical/adr/ADR-039-capability-invoke-reuse.md decisions 5 + 7.

## Assumptions
- `setpriv` (util-linux, already invoked at the isolate's final exec line in
  `sandbox_wsl2.py`'s `_ISOLATE_SCRIPT`) forwards its calling process's current environment to the
  exec'd target unless `--reset-env` is passed — the script never passes `--reset-env` today, so
  variables `export`-ed in the OUTER setup shell right before the `OUT=$(ip netns exec "$NS" unshare
  --mount --pid --fork bash -c '...')` line are inherited across fork→inner-bash→`setpriv`→`python3
  <entrypoint>` and reach the final capability process. This is pre-existing, untested-in-CI sandbox
  behavior (only exercised by the `live_wsl`-gated tests) that this spec now makes
  security-load-bearing for secret material, not just resource caps → impact: Stop (verify via the
  live-only acceptance test; if wrong, no secret reaches the capability process at all — a safe
  failure mode, not a leak, but the feature wouldn't work).
- Standard base64 output (`A-Za-z0-9+/=`, via Python's `base64.b64encode`, not the urlsafe variant)
  cannot contain the sentinel marker text used for template substitution
  (`__ARTEMIS_SECRETS_B64__`, which contains underscores at both ends) — a plain `str.replace()` on
  the static `_ISOLATE_SCRIPT` template is therefore collision-free with no need for a random
  per-run delimiter → impact: Low.
- `shlex.quote()` output, generated at runtime inside the outer root setup shell (by the piped
  `python3` decoder) from host-constructed JSON, is safe to feed to `eval` as `export NAME=<quoted>`
  lines — this is a single re-parse by one POSIX shell (bash), which is exactly `shlex.quote`'s
  contract. The `eval` target is entirely derived from the base64 blob the host built; no value ever
  touches the script TEXT or any argv → impact: Caution (covered by a unit test asserting round-trip
  correctness for values containing spaces, quotes, `$`, backticks, and embedded newlines).
- `Skill.secrets: list[str]` names are LLM-authored (via the forge) and are not guaranteed to be
  safe shell/env identifiers by construction — this spec's guard and injection functions validate
  names defensively regardless of upstream trust, never assuming the forge already sanitized them
  → impact: Stop (an unvalidated name becoming a literal `export <name>=...` statement is a shell
  injection vector).
- `SecretStorePort.list_names()` is a presence-only, no-value-read operation per its own docstring
  ("List known secret names only, never values") — the missing-key guard uses `list_names()`, never
  `get()`, matching "presence check only" literally → impact: Low.

Simplicity check: considered doing the JSON→env decode via a heredoc-fed `read` executed at
runtime inside the isolate script (mid-script stdin continuation) instead of a literal base64
substitution — rejected. Bash's behavior when a script sourced from a non-seekable pipe (`bash -s`)
also issues a runtime `read` against the same stdin stream is not a reliably-documented guarantee
(the common `curl | sh -s -- args` convention explicitly avoids this exact pattern, redirecting
interactive prompts from `/dev/tty` instead, precisely because it's unreliable). A plain
`str.replace()` template substitution sent once as part of the existing single stdin write is
simple, already how the rest of `_ISOLATE_SCRIPT` reaches the guest, and has no runtime-timing
ambiguity.

## Prerequisites
- Specs that must be complete first: none (Wave 1, parallel with `invoke-inputs-schema` per
  ADR-039 — disjoint files)
- Environment setup required: none (WSL2 provisioning per `sandbox_wsl2.py`'s runbook, unchanged)

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| src/artemis/capabilities/sandbox_wsl2.py | modify | secret-name validation, base64 templating into `_ISOLATE_SCRIPT`, `run_isolated(..., secrets=...)` |
| src/artemis/capabilities/fetch_sandbox.py | modify | `missing_required_secrets`, `resolve_secret_values`, `FetchSandbox.run(..., secrets=...)` |
| tests/capabilities/test_sandbox_wsl2.py | modify | name validation + stdin/argv/env non-leak assertions + live-only injection smoke |
| tests/capabilities/test_fetch_sandbox.py | modify | guard/resolve unit tests + `FetchSandbox.run` forwarding |

## Tasks
- [ ] Task 1: WSL2 secrets injection core — files: src/artemis/capabilities/sandbox_wsl2.py — done
  when: (a) new module-level `_SAFE_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")` and
  `_RESERVED_ENV_NAMES = frozenset({"PATH", "LD_PRELOAD", "LD_LIBRARY_PATH", "LD_AUDIT",
  "GLIBC_TUNABLES", "IFS", "BASH_ENV", "ENV", "SHELL", "PYTHONPATH", "PYTHONSTARTUP", "MEM_MAX",
  "CPU_MAX", "PIDS_MAX", "ULIMIT_T", "ULIMIT_V", "WSLENV", "ARTEMIS_SECRETS_B64", "_"})` are
  defined (the trailing `"_"` blocks the bare-underscore name the regex would otherwise allow); (b) `def
  _validate_secret_name(name: str) -> None` raises `ValueError` when `name` fails
  `_SAFE_ENV_NAME_RE.fullmatch` or is in `_RESERVED_ENV_NAMES`; (c) `def _secrets_b64(secrets:
  dict[str, str] | None) -> str` returns `""` for `None`/`{}`, otherwise calls
  `_validate_secret_name` on every key (raising before any encoding happens on invalid input), then
  returns `base64.b64encode(json.dumps(secrets, separators=(",", ":")).encode()).decode()`; (d)
  `_ISOLATE_SCRIPT` gains exactly ONE edit to the existing template: immediately BEFORE the final
  `OUT=$(ip netns exec "$NS" unshare --mount --pid --fork bash -c '...')` line (i.e. AFTER nginx,
  dnsmasq, and all iptables rules are already set up and running, so those already-launched
  processes never inherit the secrets), insert:
  ```bash
  ARTEMIS_SECRETS_B64='__ARTEMIS_SECRETS_B64__'
  if [ -n "$ARTEMIS_SECRETS_B64" ]; then
    eval "$(printf '%s' "$ARTEMIS_SECRETS_B64" | base64 -d 2>/dev/null | python3 -c '
  import json, shlex, sys
  for k, v in json.load(sys.stdin).items():
      print("export " + k + "=" + shlex.quote(v))
  ' 2>/dev/null)" || abort secrets-decode
  fi
  unset ARTEMIS_SECRETS_B64
  ```
  Because the `OUT=$(... unshare ...)` line runs NEXT in the SAME outer shell, the exported vars are
  inherited across fork→bash→`setpriv` (no `--reset-env` in the existing invocation)→`python3
  <entrypoint>`. `printf` is a bash builtin and `base64`/`python3` read the blob via stdin pipes, so
  the blob is never in any argv/`cmdline`; the secret VALUES are never in the script TEXT (only the
  base64 blob is). The `2>/dev/null` on BOTH the `base64 -d` and the `python3` steps ensures a
  decode/parse failure emits only the static `abort secrets-decode` message — no traceback, no value
  — so nothing leaks into `FetchResult.output`. There is NO inner-`bash -c` splice and NO
  `ARTEMIS_SECRETS_EXPORTS` variable. (e) `async def run_isolated(...)` gains a new
  keyword-only parameter `secrets: dict[str, str] | None = None`; inside, compute `blob =
  _secrets_b64(secrets)`, build `script = _ISOLATE_SCRIPT.replace("__ARTEMIS_SECRETS_B64__", blob)`,
  and send `script.encode()` (not the raw `_ISOLATE_SCRIPT`) via `proc.communicate(...)`; the
  existing `env`/`WSLENV` construction (`_caps_env`, `_wsl_env`) is UNTOUCHED — secrets never enter
  `env` or `WSLENV`, and never enter `command`/the `wsl.exe` argv list; (f) `uv run mypy --strict
  src/artemis/capabilities/sandbox_wsl2.py` is clean.
- [ ] Task 2: Guard + resolve + FetchSandbox wiring — files:
  src/artemis/capabilities/fetch_sandbox.py — done when: (a) `from artemis.ports.secrets import
  SecretStorePort` is imported; (b) `def missing_required_secrets(required: list[str], store:
  SecretStorePort) -> list[str]` returns the subset of `required` not present in
  `set(store.list_names())`, calling `list_names()` exactly once and never calling `store.get(...)`;
  (c) `def resolve_secret_values(names: list[str], store: SecretStorePort) -> dict[str, str]` uses
  an EXPLICIT loop that raises BEFORE assembling the return dict (NOT a dict-comprehension): `out:
  dict[str, str] = {}`; then `for name in names:` — `value = store.get(name)`; `if not value:` raise
  `ValueError(f"secret not available for injection: {name}")` (fail closed on `None` or `""`, no
  partial dict returned); else `out[name] = value`; finally `return out`; (d) `FetchSandbox.run(...)`
  gains a new keyword-only parameter `secrets: dict[str, str] | None = None`, passed straight
  through to `run_isolated(..., secrets=secrets)` alongside the existing `command=`/`egress_domains=`/
  `timeout_s=` kwargs — no other change to `run`'s existing body/validation; (e) the module
  docstring's SECURITY note gains one sentence: secret values passed via `secrets` are injected as
  isolate-scoped env vars for the capability process only, never included in `FetchResult.output`
  (this is inherently true because `run`/`run_isolated` never write secret material into the
  captured `OUT`/`output` string — no new code path touches it); (f) `uv run mypy --strict
  src/artemis/capabilities/fetch_sandbox.py` is clean.
- [ ] Task 3: sandbox_wsl2 tests — files: tests/capabilities/test_sandbox_wsl2.py — done when: all
  cases in Acceptance Criteria under "Injection mechanism" pass via `uv run pytest
  tests/capabilities/test_sandbox_wsl2.py -q` (live-only cases skip cleanly without a provisioned
  WSL2 host, mirroring the existing `live_wsl` fixture pattern already in this file).
- [ ] Task 4: fetch_sandbox tests — files: tests/capabilities/test_fetch_sandbox.py — done when: all
  cases in Acceptance Criteria under "Guard + resolve + wiring" pass via `uv run pytest
  tests/capabilities/test_fetch_sandbox.py -q`.

## Wave plan
Wave 1: [Task 1] | Wave 2: [Task 2] | Wave 3: [Task 3, Task 4]
<!-- Task 2 depends on Task 1's run_isolated(secrets=...) signature. Tasks 3 and 4 test disjoint
     files and run in parallel once both source tasks are done. -->

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | (none) |
| Modify | src/artemis/capabilities/sandbox_wsl2.py, src/artemis/capabilities/fetch_sandbox.py, tests/capabilities/test_sandbox_wsl2.py, tests/capabilities/test_fetch_sandbox.py |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict src/artemis/capabilities/sandbox_wsl2.py` | task-level typecheck |
| `uv run mypy --strict src/artemis/capabilities/fetch_sandbox.py` | task-level typecheck |
| `uv run pytest tests/capabilities/test_sandbox_wsl2.py -q` | task-level tests |
| `uv run pytest tests/capabilities/test_fetch_sandbox.py -q` | task-level tests |
| `uv run --frozen mypy` | full-project strict gate |
| `uv run --frozen pytest -q` | full-project test gate |
| `uv run --frozen ruff check src tests` | lint |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | src/artemis/capabilities/sandbox_wsl2.py src/artemis/capabilities/fetch_sandbox.py tests/capabilities/test_sandbox_wsl2.py tests/capabilities/test_fetch_sandbox.py |
| `git commit` | "feat: missing-key run-guard + WSL2 secrets injection (invoke-sandbox-secrets-guard)" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_WSL_SMOKE` | (existing, unchanged) gates the live-only WSL2 smoke tests |

### Network
| Action | Purpose |
|--------|---------|
| (none) | no new network code; egress model unchanged |

## Specialist Context
### Security
- **Injection mechanism (pinned — Option A, admin-only environ):** secret values never appear in the
  `wsl.exe`/`bash` argv list passed to `asyncio.create_subprocess_exec` (ps-visible), never enter the
  `env`/`WSLENV` name-forwarding mechanism used for resource caps, and — critically — never appear in
  any process's world-readable `/proc/<pid>/cmdline`. The base64-encoded JSON blob is embedded as a
  literal string inside the SAME stdin payload that already carries `_ISOLATE_SCRIPT` (one
  `str.replace()` on a fixed sentinel, sent in the existing single `proc.communicate()` write — no new
  channel, no new argv, no new host env var). At the VERY END of setup — AFTER nginx, dnsmasq, and all
  iptables rules are already launched, so none of those already-running processes inherit anything —
  the outer root shell decodes the blob through `printf | base64 -d | python3` (all reading via stdin
  pipes, so the blob is never in an argv/`cmdline`) and `eval`s the resulting pre-`shlex.quote`d
  `export NAME=...` lines directly into ITS OWN environment. The very next line, `OUT=$(ip netns exec
  "$NS" unshare --mount --pid --fork bash -c '...')`, runs in that same shell, so the exports are
  inherited across fork→inner-bash→`setpriv` (no `--reset-env`)→`python3 <entrypoint>` — the capability
  chain. Those secrets live only in the outer setup shell's environ and its capability-chain
  descendants; `/proc/<pid>/environ` is EUID-restricted (readable only by same-EUID/root processes in
  the guest), so a non-root peer never reads them, and they are NEVER in any `cmdline`/argv or in
  WSLENV. The `2>/dev/null` on both the `base64 -d` and `python3` steps guarantees a decode/parse
  failure emits only the static `abort secrets-decode` message — no traceback, no value — so nothing
  leaks into `FetchResult.output`.
- **Trade-offs / residual risk (honestly stated, flag for review):** (1) the outer setup shell's
  environ holds the secrets as real env vars for the remaining duration of the run (from the end-of-setup
  decode through the capability's execution), readable only by same-EUID (root) processes inside the
  guest — this sits squarely within the already-accepted "root can read anything in the isolate"
  residual (root can already ptrace/read any guest process), and is strictly better than the rejected
  plaintext-in-`cmdline` design which was world-readable; (2) this relies on `setpriv` forwarding the
  calling process's env by default (no `--reset-env` in the existing invocation) — pre-existing sandbox
  behavior this spec now makes security-load-bearing, called out as a Stop-impact assumption with a
  live-only acceptance test; (3) if the capability's OWN code prints an injected secret env var to
  stdout, it lands in `FetchResult.output` — an inherent limitation of ANY env-var-injection approach
  (the sandbox boundary controls what's injected, not what the capability does with it once running)
  and out of scope for this spec.
- **Guard (presence-only):** `missing_required_secrets` calls `SecretStorePort.list_names()` only,
  never `get()` — per `SecretStorePort`'s own contract ("List known secret names only, never
  values"). The caller (spec #5) blocks the run when the returned list is non-empty; this spec does
  not run anything.
- **Fail-closed on partial credentials:** `resolve_secret_values` raises on any missing/empty name
  rather than silently omitting it or injecting an empty string — matches ADR-039 decision 5 ("The
  capability does not run with partial credentials") even if a caller bypasses the guard.
- **Name validation:** every secret name is validated as a safe POSIX shell/env identifier
  (`^[A-Za-z_][A-Za-z0-9_]{0,63}$`) and checked against a reserved-name blocklist (`PATH`,
  `LD_PRELOAD`, `LD_AUDIT`, `GLIBC_TUNABLES`, the existing caps var names, the internal
  `ARTEMIS_SECRETS_B64` plumbing name, and the bare-underscore `_` name the regex would otherwise
  allow) BEFORE the name is ever placed into an `export NAME=...` statement — closes the injection
  vector where a crafted `Skill.secrets` entry (LLM-authored, not assumed pre-sanitized) could smuggle
  a second shell command via its own name or shadow a loader/tunable var. Invalid input raises before
  any subprocess is created.
- **Never logged:** no new code path in either file calls `_log`/`print`/writes to the `--json`
  event stream with the `secrets` dict or resolved values; `FetchResult.output`/`exit_code`/
  `truncated` are built exclusively from the guest's stdout/stderr capture, which never contains the
  base64 blob nor the exported values (verified by Acceptance Criteria).

### Performance
(none — one extra `base64`/`json` round trip on the guest, negligible relative to sandbox
provisioning cost)

### Accessibility
(none — backend-only, no frontend surface)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | src/artemis/capabilities/sandbox_wsl2.py | comment on the single `_ISOLATE_SCRIPT` decode-export insertion point explaining the end-of-setup timing (after nginx/dnsmasq launch) and admin-only-environ inheritance |
| Inline | src/artemis/capabilities/fetch_sandbox.py | docstrings on `missing_required_secrets`/`resolve_secret_values` noting presence-only vs. value-read and the fail-closed contract |
| Changelog | CHANGELOG.md | Add entry under Unreleased |

## Acceptance Criteria

**Guard + resolve + wiring**
- [ ] Guard is presence-only → verify: `missing_required_secrets(["A", "B"], store)` with a fake
  store whose `list_names()` returns `["A"]` returns `["B"]`, and the fake's `get` method is never
  called (assert call count == 0).
- [ ] Guard returns empty when nothing missing → verify: `list_names() == ["A", "B"]` →
  `missing_required_secrets(["A", "B"], store) == []`.
- [ ] Resolve returns values for present names → verify: fake store `get("A") == "va"` →
  `resolve_secret_values(["A"], store) == {"A": "va"}`.
- [ ] Resolve fails closed on missing → verify: fake store `get("B") is None` →
  `resolve_secret_values(["B"], store)` raises `ValueError`.
- [ ] Resolve fails closed on empty string → verify: fake store `get("C") == ""` →
  `resolve_secret_values(["C"], store)` raises `ValueError`.
- [ ] `FetchSandbox.run` forwards secrets → verify: mock `run_isolated`, call `FetchSandbox().run(...,
  secrets={"A": "b"})` → `mock.await_args.kwargs["secrets"] == {"A": "b"}`.
- [ ] `FetchSandbox.run` defaults to no secrets → verify: calling `run(...)` without `secrets` →
  `mock.await_args.kwargs["secrets"] is None`, and existing callers/tests without `secrets` still
  pass unmodified (no regression to `test_run_assembles_command_and_passes_egress` et al.).

**Injection mechanism**
- [ ] Name validation rejects unsafe/reserved names → verify: `_validate_secret_name` raises
  `ValueError` for `"1FOO"`, `"FOO-BAR"`, `"FOO;ls"`, `"PATH"`, `"MEM_MAX"`, `"LD_AUDIT"`,
  `"GLIBC_TUNABLES"`, `"_"`, `""`, `"FOO BAR"`; accepts `"GITHUB_TOKEN"`, `"_PRIVATE"`, `"API_KEY2"`.
- [ ] Invalid secret name fails closed before touching the sandbox → verify: `run_isolated(...,
  secrets={"PATH": "evil"})` raises `ValueError` and the mocked `asyncio.create_subprocess_exec` is
  never called.
- [ ] Secret values never in argv → verify: with `secrets={"GITHUB_TOKEN": "sekret-value-123"}`, the
  `cmd` tuple captured from the mocked `create_subprocess_exec` call, joined, does not contain
  `"sekret-value-123"`.
- [ ] Secret values never in `env`/`WSLENV` → verify: same call — the `env` kwarg dict's values
  (including `env["WSLENV"]`) do not contain `"sekret-value-123"` or `"GITHUB_TOKEN"`; `env["WSLENV"]`
  still equals the pre-existing caps-only value.
- [ ] Secret values reach stdin only in encoded form → verify: `fake_process.stdin_payload` does NOT
  contain the literal substring `"sekret-value-123"`, but DOES contain
  `base64.b64encode(json.dumps({"GITHUB_TOKEN": "sekret-value-123"}, separators=(",",
  ":")).encode()).decode()` and the single decode-export block's `eval "$(printf '%s'
  "$ARTEMIS_SECRETS_B64" | base64 -d` marker (confirming the block is present, positioned in the
  outer shell, with no inner-`bash -c` splice).
- [ ] Secret value never in the isolate script text as plaintext → verify: the fully-templated
  script string (`_ISOLATE_SCRIPT.replace("__ARTEMIS_SECRETS_B64__", blob)` for
  `secrets={"GITHUB_TOKEN": "sekret-value-123"}`) contains the base64 blob and does NOT contain the
  raw substring `"sekret-value-123"` nor any `export GITHUB_TOKEN=sekret-value-123` plaintext line.
- [ ] No-secrets path is unchanged → verify: `run_isolated(..., secrets=None)` produces a
  `stdin_payload` containing `ARTEMIS_SECRETS_B64=''` (empty blob substituted) and the pre-existing
  `test_run_isolated_converts_wslpath_and_exports_caps` assertions (`b"set -euo pipefail" in
  stdin_payload`, argv shape, caps env/WSLENV) still pass unmodified; the decode-export block appears
  exactly once, immediately before the `OUT=$(ip netns exec "$NS" unshare` line (no inner-`bash -c`
  splice anywhere).
- [ ] Decode failure emits no secret/traceback → verify: routing a malformed blob through the
  decode-export block (asserted via the seam — e.g. running `printf '%s' "$blob" | base64 -d
  2>/dev/null | python3 -c '<decoder>' 2>/dev/null` on a bad blob in a local subprocess where a shell
  is available, or a static assertion that both pipe stages carry `2>/dev/null` and the block ends
  `|| abort secrets-decode`) produces only `secrets-decode` / empty output — no Python traceback and
  no secret value in captured output.
- [ ] Quoting round-trip is safe for hostile values → verify: a unit test feeds `_secrets_b64` (or an
  equivalent seam) a value containing a space, single quote, `$VAR`, a backtick, and an embedded
  newline; decoding the produced base64 blob and running the generated `export NAME=$(shlex.quote(...))`
  line through Python's own `shlex.split`/a local bash parse (or an equivalent non-live assertion) round-trips
  to the original value.
- [ ] **Live-only:** injected secret reaches only the capability process → verify (skip if WSL2 not
  provisioned, mirroring `live_wsl`): a tiny test capability entrypoint reads
  `os.environ.get("ARTEMIS_TEST_SECRET")` and prints only `"match"`/`"nomatch"` (never the raw
  value) comparing it to an expected sentinel; `FetchSandbox.run(..., secrets={"ARTEMIS_TEST_SECRET":
  "<sentinel>"})` returns `output` containing `"match"`, and the raw sentinel string does not appear
  anywhere in `FetchResult.output`.
- [ ] Full gate green → verify: `uv run --frozen mypy` (0 errors), `uv run --frozen pytest -q` (all
  pass, live-only cases skip cleanly without a provisioned host), `uv run --frozen ruff check src
  tests` (clean).

## Progress
_(Coding mode writes here — do not edit manually)_
