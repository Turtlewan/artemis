# AGENT-rung2 — build progress / validation / flags

Built by Codex, host-verified: full `uv run mypy` clean (294 files), ruff clean, 828 passed / 4 skipped.
Opus cross-model (security) review: CLEAN. The critical network-deny BLOCK was INDEPENDENTLY
HOST-VALIDATED (normal user, real network): all 8 rung2 tests pass host-side INCLUDING
test_windows_sandbox_live_network_denied_or_host_guarded (PASSED, not skipped) — an in-AppContainer
process cannot connect to 1.1.1.1:80 while the host can (positive control). Mechanism verified:
zero-capability AppContainer (no internetClient/etc.) → kernel outbound+loopback block, no admin.
Also verified: shell=False inertness ('; echo injected' is a literal filename fragment, not shell-
interpreted), 1MB output cap, 30s timeout->TerminateJobObject(124), MPSSVC fail-closed refuse,
authorize-raise fail-closed, boundary-staged-not-run-until-graduated, Job Object (kill-on-close +
512MB/768MB memory caps), workspace+temp ACL'd to the package SID, Mac DockerSandbox import-guarded.

## FLAG (minor robustness, review-needed)
_grant_workspace_acl / _grant_read_execute_acl call icacls with check=True, so an icacls failure
raises subprocess.CalledProcessError (a SubprocessError, NOT OSError) which the run() wrapper's
`except OSError` does NOT catch — it would propagate as an unhandled exception rather than a
fail-closed CommandResult. Effect is still fail-closed (the command does not run), but it breaks the
"return a CommandResult" contract. ACTION: catch subprocess.CalledProcessError (or SubprocessError)
in run() and map to an error CommandResult. Not a security hole; the kernel ACL boundary + network
deny hold regardless.
