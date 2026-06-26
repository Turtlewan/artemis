---
spec: AGENT-rung2
status: draft
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
- The Windows sandbox is a restricted-token + Job Object wrap around the spawned process — the SAME isolation Artemis already uses for the Codex coder (the `apex-coder` profile). Reuse/port that mechanism; do NOT invent a new one. Verify how the existing Codex sandbox is configured (the apex-code/Codex profile, restricted-token/Job-Object usage) and mirror it. → impact: Stop (a weaker spawn = unsandboxed command exec).
- The sandbox is built behind a `Sandbox` seam (`run(cmd, *, workspace_root, network: bool) -> CommandResult`) so it swaps to Docker/remote on the Mac (the AGENT-coder workspace abstraction is the macOS analogue) — ADR-031 C "swap-able from day one". macOS `sandbox-exec`/Seatbelt is the deprecated Mac interim; the Windows wrap is the dev analogue. → impact: Stop.
- The OpenHands LocalWorkspace (AGENT-coder) runs its commands THROUGH this sandbox on Windows — this spec's `Sandbox` is the confinement AGENT-coder's local runtime depends on. → impact: Caution (keeps the security story coherent: local-runtime is only safe because rung2 confines it).
- Command classification goes through `AuthorityGate` (AGENT-authority): no-network + workspace-confined = `IN_SANDBOX` → auto; network or out-of-workspace effect = `BOUNDARY` → staged + graduated. The sandbox ENFORCES the no-network/confinement that makes IN_SANDBOX true (network is denied unless the gate authorized a boundary crossing). → impact: Stop (classification without enforcement is theatre).
- Verification is deterministic read-back (exit code / expected output) per the spine's reliability contract — the command tool returns a `CommandResult(exit_code, stdout, stderr)`; the spine's `verify` checks it. → impact: Caution.
- Windows artifact-ownership caveat (known from the Codex sandbox): sandbox-written files carry the sandbox SID; suppress in-tree caches and document cleanup (reuse the apex-coder mitigations). → impact: Low.

Simplicity check: considered running commands directly with a path/allowlist check only — rejected (ADR-031 C): the restricted-token/Job-Object wrap is the actual blast-radius enforcement; a check without process-level confinement is not a sandbox. Reusing the proven Codex mechanism is the minimal real sandbox.

## Prerequisites
- Specs that must be complete first: **AGENT-types**, **AGENT-spine** (dispatches the command tool), **AGENT-authority** (classifies/gates the command). (AGENT-coder's LocalWorkspace consumes this sandbox; companion.)
- Environment setup required: none beyond stdlib + the Windows APIs the existing Codex sandbox uses (no new PyPI dep expected; confirm at build).

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| `src/artemis/agentic/sandbox.py` | create | `Sandbox` seam + `WindowsRestrictedSandbox` (restricted-token + Job Object) + a `DockerSandbox`/remote stub (Mac-gated, import-guarded). |
| `src/artemis/agentic/rungs/command.py` | create | Rung 2 `proc.run` tool (async) → routes through `AuthorityGate` then `Sandbox.run`; `register_rung2(registry, *, sandbox, authority, workspace_root)`. |
| `tests/test_agent_rung2.py` | create | in-sandbox command runs confined (no network); boundary command staged+graduated; deterministic result; network denied unless authorized; tool registers. |

## Exact changes
- `sandbox.py`: `class Sandbox(Protocol): async def run(cmd, *, workspace_root, network: bool) -> CommandResult`. `WindowsRestrictedSandbox` spawns under a restricted token + Job Object (port the Codex `apex-coder` mechanism), cwd pinned to `workspace_root`, network denied unless `network=True`, byte-capped stdout/stderr, timeout. `CommandResult(exit_code, stdout, stderr, timed_out)`. `DockerSandbox`/remote = Mac-gated, import-guarded, raises a clear "Mac-gated" error on the dev box.
- `command.py`: `proc.run(cmd, args)` tool — `authority.authorize(...)`; if not auto → return a needs-approval result (spine parks via inbox); else `await sandbox.run(cmd, workspace_root=…, network=<only if the authorized crossing allows it>)`. `register_rung2(...)` registers the tool with the sandbox+authority bound.

## Tasks
- [ ] Task 1: Implement the `Sandbox` seam + `WindowsRestrictedSandbox` (restricted-token + Job Object, port the Codex isolation) + a Mac-gated Docker/remote stub. — files: `src/artemis/agentic/sandbox.py` — done when: a command runs confined to `workspace_root` with network denied by default; stdout/stderr are byte-capped and a timeout is enforced; the Mac variant is import-guarded (clear error on Windows); `uv run mypy` clean.
- [ ] Task 2: Implement the Rung 2 `proc.run` tool routing through AuthorityGate→Sandbox + `register_rung2`. — files: `src/artemis/agentic/rungs/command.py` — done when: an in-sandbox (no-net, confined) command runs automatically and returns a deterministic `CommandResult`; a boundary command (network / out-of-workspace) is staged via the gate and does NOT run until graduated; network is denied unless the authorized crossing permits it; the tool registers into the ToolRegistry.
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
- [ ] Network deny-default → verify: a command cannot reach the network unless an authorized boundary crossing enabled it.
- [ ] Gate enforced → verify: a boundary command is staged via `AuthorityGate` and does NOT run until graduated; an in-sandbox command runs automatically.
- [ ] Mac parity seam → verify: the Docker/remote sandbox variant is import-guarded (clear Mac-gated error on the dev box); the seam interface is identical.
- [ ] Whole project clean → verify: `uv run mypy`, `uv run ruff check . && uv run ruff format --check .`, `uv run pytest -q` all pass.

## Progress
_(Coding mode writes here — do not edit manually)_
