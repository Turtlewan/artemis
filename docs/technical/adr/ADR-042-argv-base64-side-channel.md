# ADR-042 — WSL argv via a base64 side-channel (supersedes ADR-041 decision 5)

- **Status:** **Proposed** — planning, 2026-07-03 (owner-requested follow-up; build not yet greenlit).
- **Date:** 2026-07-03
- **Deciders:** owner + planning
- **Supersedes:** ADR-041 decision 5 (the shlex-quote-then-guest-decode arg-passing mechanism). ADR-041's caps-profile decisions (1–4) are unaffected.
- **Design basis:** the `chrome-capable-fetch-sandbox` build (2026-07-03) and its dual-pass apex-security review; host probes of the WSL argv boundary (`/tmp/wsl_probe*.py`) proving the two-layer Windows `list2cmdline` + WSL `bash -c` quoting behavior is content-dependent; the existing `ARTEMIS_SECRETS_B64` pattern in `sandbox_wsl2.py`.

## Context

ADR-041 fixed a real WSL-interop arg-passing defect: a positional arg containing shell metacharacters
(parens, spaces) was mangled or caused a `bash` syntax error before the capability ran. The shipped fix
(`chrome-capable-fetch-sandbox`) is: `shlex.quote()` every positional on the Python side, then a
guest-side `python3`/`shlex` decode unquotes each back to its raw value. It is verified-secure
(fail-closed, dual-pass apex-security CLEAN) and the live smoke passes.

But that fix is coupled to the *behavior* of two interacting quoting layers (Windows `list2cmdline`
framing + WSL's `bash -c` reconstruction), which host probes showed is content-dependent and
surprising. It works today; it is fragile against future WSL/Windows quoting-quirk changes, and the
guest-side reconstruction needs a shlex round-trip whose edge cases the build had to reason about
carefully.

`sandbox_wsl2.py` already contains a proven, injection-safe channel that sidesteps the command line
entirely: secrets travel as a base64 JSON blob templated into the stdin script (`ARTEMIS_SECRETS_B64`),
decoded guest-side. Stdin is not subject to any WSL argv mangling.

## Decision

Pass the isolate's positional argv (`skill_wsl_path`, egress CSV, `run_id`, and the command tokens) the
same way secrets already travel: as a **single base64-encoded JSON list templated into the stdin
script**, decoded guest-side into a bash array before setup runs. No untrusted value is placed on the
`wsl.exe` command line at all.

- Python side: build `argv_list = [skill_wsl_path, egress_csv, run_id, *command]`, base64-encode
  `json.dumps(argv_list)`, template it into `_ISOLATE_SCRIPT` (mirroring `_secrets_b64` /
  `__ARTEMIS_SECRETS_B64__`). Pass **no** positionals after `bash -s --`. Remove the Python-side
  `shlex.quote()` calls (and the now-unused `import shlex`).
- Guest side: replace the shlex round-trip decode with a base64→JSON→NUL-delimited decode into a bash
  array, **fail-closed** (plain pipeline under `set -euo pipefail`, `surrogateescape`, explicit
  argv-count check — same fail-closed guarantees ADR-041 established), then `set -- "${_ARGV[@]}"`.

## Consequences

**Positive:**
- Eliminates the Windows+WSL two-layer quoting dependence entirely — no content-dependent behavior, no
  shlex round-trip heuristic. Any byte sequence a JSON string can hold round-trips exactly.
- One trusted channel (our own base64), reused from the already-reviewed secrets pattern — less novel
  surface than the quote/decode dance.
- Fail-closed by construction (base64/JSON decode either fully succeeds or the pipeline aborts).

**Costs / trade-offs:**
- Not a bug fix — ADR-041's Option A already fixed the defect and is verified-secure. This is a
  *sturdier-foundation* refactor of a security boundary; it earns its keep only as durability
  insurance, and the owner may reasonably defer it.
- Requires modifying a **pre-existing** test (`test_run_isolated_converts_wslpath_and_exports_caps`)
  that asserts the args arrive as command-line positionals — they no longer do. This is the ripple
  that made it a BIG fork during the `chrome-capable-fetch-sandbox` build (why Option A shipped first).
- Must carry the same dual-pass apex-security review at build time (the isolate execution boundary
  changes again).

## Alternatives considered
- **Keep ADR-041's Option A (shlex quote/decode)** — the status quo; verified-secure, but retains the
  WSL-quoting coupling this ADR removes. Chosen as the *interim* ship; this ADR is the durability
  follow-up.
- **WSLENV env var instead of stdin-templated blob** — env via WSLENV has its own translation quirks;
  the stdin-templated blob (exactly the secrets pattern) is the most mangling-proof channel.
