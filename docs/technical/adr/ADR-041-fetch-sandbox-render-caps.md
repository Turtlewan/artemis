# ADR-041 — Opt-in render resource-caps profile for `FetchSandbox`

- **Status:** **Accepted** — owner + planning, 2026-07-03.
- **Date:** 2026-07-03
- **Deciders:** owner + planning
- **Refines:** ADR-036 (hardened WSL2 isolate) — adds a caller-selectable resource-caps profile on the existing `FetchSandbox.run`/`run_isolated` path. Does not change egress, de-privilege, or mount/pid isolation (ADR-036's containment boundary is unchanged).
- **Design basis:** the build-time live smoke for `js-rendering-fetcher` (ADR-040) failing against the production isolate; root-cause diagnosis in `docs/progress/js-rendering-fetcher.md`; the `poc/wsl2_browser_userns/` spike's chrome-tuned `isolate.sh` caps (which the production isolate never adopted); host-side scratchpad debug confirming the fix end-to-end (real render, exit 0).

## Context

`FetchSandbox.run` hardcodes `caps=SandboxCaps()` — 512MB RAM / 1 CPU / 128 pids / 512MB `ulimit -v`
(VSZ) — sized for small, cheap fetch scripts. `js-rendering-fetcher` (ADR-040) runs
`chrome-headless-shell` through this same path. Chrome reserves tens of GB of *virtual* address space
even though its RSS stays low; a 512MB VSZ ulimit makes it abort instantly (SIGTRAP, empty stderr).
The `poc/wsl2_browser_userns/` spike passed only because it ran against its own throwaway `isolate.sh`
copy with chrome-tuned caps (`ULIMIT_V=unlimited`, 1.5GiB RAM, 4 CPU, 256 pids) — it never exercised the
production isolate, so the gap went undetected until the real build-time live smoke.

A second, unrelated defect surfaced in the same diagnosis: `run_isolated` passes untrusted command
tokens across the WSL interop boundary unquoted, so any arg with shell metacharacters (parens, a
space) is a syntax error before the capability runs. This ADR also records that fix, since both ship
in the same spec, but it is pure correctness/hardening — no architectural trade-off to decide.

## Decision

| # | Decision | Statement |
|---|----------|-----------|
| 1 | **Caps become caller-selectable, but only via a closed named profile** | `FetchSandbox.run` gains `caps_profile: Literal["default", "render"] = "default"`, resolved internally to `SandboxCaps()` or `RENDER_CAPS`. No open `SandboxCaps` object reaches the public API — a caller can select one of two reviewed shapes, never an arbitrary envelope. Default behavior is byte-for-byte unchanged for every existing caller. (Revised 2026-07-03 after apex-security review: an earlier draft of this decision exposed a raw `caps: SandboxCaps \| None` param, which would have let any future caller request an unreviewed, unbounded resource envelope — closed before build.) |
| 2 | **VSZ decouples from `memory_mb`** | `SandboxCaps` gains `unlimited_vsz: bool = False`. When set, `ulimit -v` is `unlimited` instead of `memory_mb*1024` KB. Per-process VSZ is not a meaningful control for Chrome's mmap-heavy address space (confirmed by the spike and the live debug); the cgroup `memory.max` (RSS-bounding) remains the real containment, unaffected by this flag. **Explicit trade-off (apex-security FLAG, accepted):** this deliberately drops from two independent RAM backstops (ulimit -v + cgroup memory.max) to one (cgroup memory.max only) for the `render` profile, because RLIMIT_AS is incompatible with Chrome/V8's virtual-memory reservation behavior — not an oversight. |
| 3 | **One named profile, not a general knob exposed to callers** | A single `RENDER_CAPS = SandboxCaps(memory_mb=1536, cpu_pct=400, pids_max=256, unlimited_vsz=True)` constant is defined once (`sandbox_wsl2.py`) using the spike-confirmed values. `JsFetcher` opts in via `caps_profile="render"` (wired in `js-rendering-fetcher`'s finishing step) — decision 1 is what enforces this stays a closed choice rather than an open-ended per-caller dial. |
| 4 | **Containment unchanged; DoS ceiling grows** | Egress-allowlist, de-privileged uid, and mount/pid namespace isolation (ADR-036) are untouched. The only change is the resource envelope available to a capability that explicitly requests `caps_profile="render"`: RAM cap 512MB → 1.5GB, CPU 1 → 4 cores, pids 128 → 256, VSZ ulimit 512MB → unlimited (superseded by the RAM cgroup cap as the real ceiling). This is a real DoS-envelope increase for opted-in capabilities, bounded and reviewed, not a containment weakening. |
| 5 | **Arg-quoting fix ships alongside (pure correctness)** | `run_isolated` now `shlex.quote()`s the positional args (`skill_wsl_path`, egress CSV, `run_id`, each `command` token) before they cross the WSL interop boundary. This is necessary specifically because WSL's interop layer reconstructs the post-`--` argv into a single command line and re-parses it via `/bin/bash -c` semantics before invoking the guest `bash -s` — a shell-reinterpretation step that happens inside `wsl.exe` itself, not in the visible Python `create_subprocess_exec` call (which has no shell of its own). Confirmed via host-side live round-trip against the real isolate, not just theorized (2026-07-03 scratchpad debug: raw `a(b)c` → shell syntax error; `shlex.quote()`-wrapped → arrives intact); the build spec adds an automated live regression test reproducing this proof, not only a mocked call-site assertion (apex-security BLOCK, resolved). |

## Consequences

**Positive:** `js-rendering-fetcher` (ADR-040) can finish — Chrome no longer SIGTRAPs on startup.
The caps mechanism is general enough for any future capability that needs a larger envelope, without
touching the default path any existing capability relies on.

**Costs / known limits (recorded so they are not reopened blind):**
- A capability running under `RENDER_CAPS` can consume up to 1.5GB RAM / 4 CPU cores for the
  duration of one sandboxed run — a real increase in per-run resource cost vs the 512MB/1-CPU default.
  Acceptable because only `JsFetcher` opts in today, and every run is still timeout-bounded
  (`FetchSandbox.run`'s `timeout_s`, clamped to 300s) and cgroup-capped (no unbounded growth).
- `unlimited_vsz` is a real, if narrow, foot-gun if a future caller sets it without also raising
  `memory_mb` — VSZ stops bounding anything and RSS becomes the sole ceiling. Mitigated by keeping it
  paired inside the single named `RENDER_CAPS` profile rather than exposed as an independent default,
  and by decision 1 closing `caps_profile` to a `Literal` so no caller can construct that combination.
- The `render` profile's 4-CPU-core grant can contend with other concurrently-running sandboxed
  capability runs on the dev box (apex-security note, accepted — informational only).
- **Pre-existing, out of scope:** `sandbox_policy.json` (the `Wsl2SandboxRunner.run_tests` path,
  `_policy_for`/`_int_from_policy`/`_float_from_policy`) already accepts unbounded numeric caps values
  with no ceiling — the same class of gap this ADR closes for `FetchSandbox.run`, but on a different,
  unmodified entry point (apex-security note). Flagged for a future follow-up, not fixed here
  (surgical scope — this ADR/spec does not touch that path).

## Alternatives considered
- **Raise the global default caps instead of adding an opt-in profile** — rejected: every other
  sandboxed capability (test verification, generic fetches) would pay a larger resource cost with no
  benefit; the render workload is the outlier, not the norm.
- **Give `FetchSandbox.run` a generic `caps` override with no named profile** — considered, but a
  single reviewed constant (`RENDER_CAPS`) is easier to reason about and review than an open dial any
  caller could set to arbitrary values; the named-profile approach was chosen (decision 3).
