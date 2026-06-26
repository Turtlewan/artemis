---
spec: AGENT-rung2
status: ready
cross_model_review: true
token_profile: balanced
autonomy_level: L2
---

# Spec: AGENT-rung2 — sandboxed command execution + Windows sandbox seam

**Identity:** Rung 2 (ADR-031 B): execute commands/scripts inside a swap-able sandbox. The Windows-dev
sandbox = Artemis restricted-token + Job Object (the existing Codex/`apex-coder` isolation pattern);
the seam swaps to Docker/remote on the Mac. Boundary-crossing commands route through the
`AuthorityGate` graduated allowlist; in-sandbox commands run automatically.
<!-- → why: docs/technical/adr/ADR-031-...md (B Rung 2, C sandbox + Refinement 2026-06-26 Windows sandbox) + docs/research/2026-06-26-openhands-windows/README.md + docs/drafts/AGENT-engine-design.md (seam #6). -->

## Assumptions
<!-- Coding mode verifies each item against the codebase before executing. -->
- The Windows sandbox is a **Windows AppContainer** (launched WITHOUT the `internetClient`/`internetClientServer`/`privateNetworkClientServer` capabilities) + a Job Object on top. Research (`docs/research/2026-06-26-windows-network-deny/README.md`) selected AppContainer: it gets a UNIQUE package SID and an automatic kernel "Block Outbound Default" filter — real network-deny with **NO admin** (this is how Chromium/Edge sandbox renderers). It REPLACES the restricted-token model the Codex `apex-coder` profile uses (that profile runs network-ON with the dev user's own SID — it is NOT a network sandbox and must NOT be mirrored for this). The Job Object still composes on top (resource caps + process-tree kill, mitigating child-spawn bypass). → impact: Stop (the restricted-token/WFP-per-SID approach is wrong — same user SID + admin-required; AppContainer is the correct mechanism).
- The sandbox is built behind a `Sandbox` seam (`run(cmd, *, workspace_root, network: bool) -> CommandResult`) so it swaps to Docker/remote on the Mac (the AGENT-coder workspace abstraction is the macOS analogue) — ADR-031 C "swap-able from day one". macOS `sandbox-exec`/Seatbelt is the deprecated Mac interim; the Windows wrap is the dev analogue. → impact: Stop.
- The OpenHands LocalWorkspace (AGENT-coder) runs its commands THROUGH this sandbox on Windows — this spec's `Sandbox` is the confinement AGENT-coder's local runtime depends on. → impact: Caution (keeps the security story coherent: local-runtime is only safe because rung2 confines it).
- Command classification goes through `AuthorityGate` (AGENT-authority): no-network + workspace-confined = `IN_SANDBOX` → auto; network or out-of-workspace effect = `BOUNDARY` → staged + graduated. The sandbox ENFORCES the no-network/confinement that makes IN_SANDBOX true (network is denied unless the gate authorized a boundary crossing). → impact: Stop (classification without enforcement is theatre).
- Verification is deterministic read-back (exit code / expected output) per the spine's reliability contract — the command tool returns a `CommandResult(exit_code, stdout, stderr)`; the spine's `verify` checks it. → impact: Caution.
- **AppContainer imposes a kernel FS boundary** (the package SID has no access by default): `workspace_root` (+ any temp dir the child needs) MUST be ACL-granted to the package SID at sandbox setup (`icacls` or `SetEntriesInAcl`) — this is a real kernel boundary ON TOP of the Python `resolve_within` check, not a replacement. Files the child writes carry the package SID (cleanup via the ACL'd workspace). → impact: Caution (extra setup per sandbox; without the ACL grant the child can't read/write the workspace).
- **Loopback is also blocked by default** under AppContainer (good for deny-all). A future scoped `allow_network` that needs localhost requires a loopback exemption (`CheckNetIsolation`/admin) or a per-host capability — note as a deferred refinement; v1 is deny-all + boundary-gated outbound. → impact: Low.
- Runtime precondition: the Windows Defender Firewall service (MPSSVC) must be running for the AppContainer network block to apply (default-on). The sandbox asserts MPSSVC is running and **fail-closed refuses to run** (no auto IN_SANDBOX command) if it is not. → impact: Stop (a down firewall service voids the block).

Simplicity check: considered the restricted-token + WFP/firewall-rule approach — rejected (research): restricted tokens keep the user's own SID (a per-SID rule blocks the user's traffic too) and every WFP/firewall route needs admin. AppContainer is the only no-admin, distinct-SID, kernel-enforced option; it is the minimal real network sandbox on Windows.

## Prerequisites
- Specs that must be complete first: **AGENT-types**, **AGENT-spine** (dispatches the command tool), **AGENT-authority** (classifies/gates the command). (AGENT-coder's LocalWorkspace consumes this sandbox; companion.)
- Environment setup required: none beyond stdlib `ctypes` against Windows `userenv.dll`/`kernel32` AppContainer APIs (NO new PyPI dep, NO admin). Per-run: a one-time `CreateAppContainerProfile` + ACL-grant of the workspace to the package SID (done by the sandbox itself).

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| `src/artemis/agentic/sandbox.py` | create | `Sandbox` seam + `WindowsAppContainerSandbox` (no-network AppContainer + Job Object, ctypes) + a `DockerSandbox`/remote `--network none` stub (Mac-gated, import-guarded). |
| `src/artemis/agentic/rungs/command.py` | create | Rung 2 `proc.run` tool (async) → routes through `AuthorityGate` then `Sandbox.run`; `register_rung2(registry, *, sandbox, authority, workspace_root)`. |
| `tests/test_agent_rung2.py` | create | in-sandbox command runs confined (no network); boundary command staged+graduated; deterministic result; network denied unless authorized; tool registers. |

### Network-deny mechanism — AppContainer (mechanically enforced, no admin) (BLOCK)
Network-deny is enforced by launching the command in a **Windows AppContainer with NO network capabilities** (omit `internetClient`/`internetClientServer`/`privateNetworkClientServer`): the package SID gets an automatic kernel outbound-block (and loopback block) — **no admin, no firewall rule to add** (`docs/research/2026-06-26-windows-network-deny/README.md`). This REPLACES the restricted token (AppContainer is a stricter low-box token); the Job Object composes on top. **Precondition:** the sandbox asserts the Windows Defender Firewall service (MPSSVC) is running; if not, it **fail-closed refuses to run** (no nominal-deny auto-run). Task 1's done-criteria MUST include a **verifiable network-deny test**: an in-sandbox child doing `socket.create_connection(("1.1.1.1", 80))` FAILS, with a positive control (the same payload OUTSIDE the sandbox connects) so the test discriminates. **No more "gate-everything fallback"** — the mechanism is real, so IN_SANDBOX command auto-run is enabled on Windows. (Mac parity: the same `Sandbox` seam swaps to a Docker workspace launched `--network none`; `allow_network=None` ⇒ no-network container.)

### Sandbox + command tool
- `sandbox.py`: `class Sandbox(Protocol): async def run(argv: Sequence[str], *, workspace_root, allow_network: frozenset[str] | None = None, timeout_s: int = 30) -> CommandResult`. **`argv` is an argument LIST — `subprocess`/`CreateProcess` is invoked `shell=False`; shell-string evaluation is prohibited (command-injection fix, FLAG).** `WindowsAppContainerSandbox` (implemented via **ctypes**, not pywin32: `CreateAppContainerProfile`/`DeriveAppContainerSidFromAppContainerName` in `userenv.dll` + `STARTUPINFOEX` + `SECURITY_CAPABILITIES` + `CreateProcess`) launches the child in a network-capability-free AppContainer + Job Object; **`workspace_root` (+ temp) is ACL-granted to the package SID** at setup (`icacls`/`SetEntriesInAcl`); cwd pinned to `workspace_root`; **stdout+stderr capped at 1 MB combined, default 30 s timeout (configurable)**. `allow_network` is the approved destination set (`None` = deny-all — the AppContainer has no net capability; a non-empty set = a future scoped-capability/loopback-exemption refinement, NOT v1 — v1 supports deny-all and defers scoped outbound). `CommandResult(exit_code, stdout, stderr, timed_out)`. `DockerSandbox`/remote = Mac-gated, import-guarded, raises a clear "Mac-gated" error on the dev box.
- `command.py`: `proc.run(argv)` tool — `decision = authority.authorize(step, workspace_root=…)`; **if `authority.authorize` raises, the command MUST NOT run** (return an error `CommandResult`, never fall through — fail-closed, BLOCK); if `not decision.auto` → return a needs-approval result (spine parks via inbox); else `await sandbox.run(argv, workspace_root=…, allow_network=<the approved destinations, or None>)`. `register_rung2(registry, *, sandbox, authority, workspace_root)` registers the tool.
- **`CommandResult.stdout/stderr` is UNTRUSTED data** from an arbitrary subprocess (may carry adversarial "ignore previous instructions" / fake tool-call text). This spec defines the surface; the spine MUST treat it as data, never instructions (prompt-injection defence is the spine's responsibility). stderr is returned verbatim for verification — callers must NOT surface raw stderr externally without sanitisation (may leak host paths/env).

## Tasks
- [ ] Task 1: Implement the `Sandbox` seam + `WindowsAppContainerSandbox` (AppContainer with no network capabilities, via ctypes/userenv.dll + STARTUPINFOEX + SECURITY_CAPABILITIES; Job Object on top; `workspace_root` ACL-granted to the package SID; **`shell=False` argv only**; 1 MB output cap; 30 s timeout) + a Mac-gated Docker/remote (`--network none`) stub. — files: `src/artemis/agentic/sandbox.py` — done when: a command runs confined to `workspace_root` (ACL-granted); **MPSSVC-running is asserted (fail-closed refuse if down)**; **the network-deny test passes — an in-sandbox `socket.create_connection(("1.1.1.1",80))` FAILS while the same payload OUTSIDE the sandbox connects (positive control)**; shell-metacharacter input is NOT shell-interpreted (`; rm -rf .` inert); output capped + timeout enforced; the Mac variant import-guarded; `uv run mypy` clean.
- [ ] Task 2: Implement the Rung 2 `proc.run(argv)` tool routing through AuthorityGate→Sandbox + `register_rung2`. — files: `src/artemis/agentic/rungs/command.py` — done when: an in-sandbox (no-net, confined) command runs automatically and returns a deterministic `CommandResult`; **if `authority.authorize` raises, the command does NOT run (fail-closed)**; a boundary command (network / out-of-workspace) is staged and does NOT run until graduated; network is denied unless the approved `allow_network` destinations permit it (scoped, not blank `network=True`); the tool registers into the ToolRegistry.
- [ ] Task 3: Tests. — files: `tests/test_agent_rung2.py` — done when: confined-run, network-denied-by-default, boundary-staged-not-run, post-graduation-runs, deterministic-result, and registration assertions pass under `uv run pytest -q` (Windows sandbox specifics may be marked/guarded if CI lacks the APIs — document any skip).

## Wave plan
Wave 1: [Task 1] | Wave 2: [Task 2] | Wave 3: [Task 3]

## Permissions
The following actions will run autonomously during build. Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | `src/artemis/agentic/sandbox.py`, `src/artemis/agentic/rungs/command.py`, `tests/test_agent_rung2.py` |
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
| `git add` | The three files above, by name. |
| `git commit` | "feat: AGENT-rung2 sandboxed command exec + Windows restricted-token sandbox seam (ADR-031 B/C)" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| (none) | — |

### Network
| Action | Purpose |
|--------|---------|
| (none for the build) | The sandbox DENIES network to executed commands by default; a boundary crossing that needs network is gated + graduated. No package install. |

## Specialist Context
### Security
`cross_model_review: true` — this is the actual command-execution blast radius. Reviewer confirms: (1) commands run under a real process-level sandbox (restricted-token + Job Object), not just a path check; (2) network is denied by default and only an authorized+graduated boundary crossing can enable it; (3) execution is confined to `workspace_root`; (4) every command passes `AuthorityGate` before running (in-sandbox auto / boundary staged); (5) the sandbox seam swaps to Docker/remote on the Mac (parity), and the Mac variant is import-guarded on the dev box; (6) the Windows SID artifact-ownership caveat is mitigated (cache suppression + documented cleanup, reusing the Codex pattern).

### Performance
(none — per-command spawn; budgets enforced by the spine.)

### Accessibility
(none — no frontend change.)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | `src/artemis/agentic/sandbox.py`, `rungs/command.py` | Docstrings: restricted-token/Job-Object confinement, network-deny-default, swap-able seam, gate routing. |
| Overview | docs/technical/architecture/overview.md | Add Rung-2 sandboxed command exec to Capabilities on archive. |
| ADR | (none) | ADR-031 B/C + Refinement 2026-06-26 record the decision. |

## Acceptance Criteria
- [ ] Confined run → verify: an in-sandbox command runs under the restricted-token/Job-Object sandbox, cwd-pinned to `workspace_root`, returning a deterministic `CommandResult`.
- [ ] Network deny is ENFORCED via AppContainer (BLOCK) → verify: an in-sandbox `socket.create_connection(("1.1.1.1",80))` FAILS while the same payload outside the sandbox connects (positive control); MPSSVC-down → sandbox fail-closed refuses to run (no nominal-deny auto-run). No admin required.
- [ ] Workspace ACL boundary → verify: the child can read/write only under the package-SID-ACL'd `workspace_root`; a path outside it is denied at the kernel (in addition to `resolve_within`).
- [ ] No shell injection (FLAG) → verify: a cmd containing shell metacharacters (`; rm -rf .`) is passed as argv and NOT interpreted by a shell (`shell=False`).
- [ ] Authorize fail-closed (BLOCK) → verify: if `authority.authorize` raises, the command does not execute.
- [ ] Deny-all v1 (FLAG) → verify: `allow_network=None` gives a no-network AppContainer (v1); scoped per-destination outbound is documented as a deferred loopback-exemption/capability refinement, not built in v1.
- [ ] Gate enforced → verify: a boundary command is staged via `AuthorityGate` and does NOT run until graduated; an in-sandbox command runs automatically.
- [ ] Output bounds → verify: stdout+stderr capped (1 MB) and the timeout (30 s default) is enforced.
- [ ] Mac parity seam → verify: the Docker/remote sandbox variant is import-guarded (clear Mac-gated error on the dev box); the seam interface is identical.
- [ ] Whole project clean → verify: `uv run mypy`, `uv run ruff check . && uv run ruff format --check .`, `uv run pytest -q` all pass.

## Progress
_(Coding mode writes here — do not edit manually)_
