---
status: ready
mode: light
coder_model: codex
---

# voice-gate-rung2-hardening

Two surgical fail-closed hardening fixes to already-built, dev-runnable modules, carried from the
2026-06-26 build handoff (Specialist Flags). Dev-buildable + host-verifiable now (no Mac/MSVC gate).

## Intent
Close two "fail-closed contract" gaps the builder flagged: (1) `Gateway.handle_voice` (non-streaming,
M5-c) is fail-*open* on an absent `key_provider` while its streaming twin `handle_voice_stream` (M5-d)
is fail-*closed* — harmonize the non-streaming gate to fail-closed. (2) `WindowsAppContainerSandbox.run`
maps only `OSError` to a fail-closed `CommandResult`, so an icacls ACL-grant failure (raised as
`subprocess.CalledProcessError`, a `SubprocessError` not an `OSError`) escapes the contract and
propagates unhandled — map it to a fail-closed error result.

## Key decisions
- **Harmonize `handle_voice`, do not retire it.** `handle_voice` has no live caller today (only
  `tests/test_speaker_id_voice_scope.py` uses it; the live voice loop uses `handle_voice_stream`), but
  retiring it would churn 4 tests to remove a symmetric public method for a speculative cleanup. Keep
  the API; make it fail-closed. Mirror the streaming gate's posture, not its raise-style — the
  non-streaming method keeps returning `BrainResponse(text="NEEDS_PHONE_UNLOCK", …)` (its existing
  contract), the streaming one keeps raising `NeedsPhoneUnlock`.
- **Broaden, don't replace, the sandbox exception handling.** Add a `subprocess.CalledProcessError`
  (or `subprocess.SubprocessError`) arm alongside the existing `except OSError`; leave the OSError and
  `SandboxUnavailableError` arms intact. The kernel ACL/network-deny boundary already holds regardless
  — this only restores the "always return a `CommandResult`" contract.

## Gotchas / edge cases
- In `handle_voice`, the bug is the `and self._key_provider is not None` clause inside the gate `if`:
  when `key_provider is None` the whole condition is False and control falls through to
  `brain.respond`. The fix must treat `key_provider is None` as **locked** (cannot verify unlock), the
  same as `handle_voice_stream` line ~180 (`if self._key_provider is None or not
  self._key_provider.is_owner_unlocked()`).
- Non-tier1 and guest paths must be unaffected — only owner + tier1 is gated. The existing "hello" /
  "what time is it" tests (non-tier1) must stay green unchanged.
- The icacls `CalledProcessError` is raised inside `_run_appcontainer_process` (via
  `_grant_workspace_acl` / `_grant_read_execute_acl`, `check=True`), which `run()` invokes through
  `asyncio.to_thread` — so the new `except` arm belongs on the same `try` block in `run()` that already
  wraps that call (currently `src/artemis/agentic/sandbox.py` ~line 106-116).
- `CalledProcessError` subclasses `SubprocessError`; catching `subprocess.CalledProcessError` is the
  narrow choice, `subprocess.SubprocessError` the slightly wider one. Either satisfies the contract;
  prefer `CalledProcessError` (that is the only subprocess error these helpers can raise).

## Tasks
1. **Harmonize `Gateway.handle_voice` to fail-closed** — in `src/artemis/gateway.py`, rewrite the
   owner-tier1 gate in `handle_voice` so a `None` or locked `key_provider` returns
   `BrainResponse(text="NEEDS_PHONE_UNLOCK", …)` (same fields it returns today), instead of the current
   `and self._key_provider is not None` clause that skips the gate when the provider is absent.
   — done when: calling `handle_voice` with `key_provider=None`, an owner identity, and a tier1 module
   returns `text == "NEEDS_PHONE_UNLOCK"` (no `brain.respond` passthrough); all existing
   `test_speaker_id_voice_scope.py` cases still pass.
2. **Add a fail-closed regression test for the absent-key_provider voice path** — in
   `tests/test_speaker_id_voice_scope.py`, add one test that builds the Gateway with `key_provider=None`,
   resolves an owner identity on a tier1 request, and asserts `handle_voice` returns
   `text == "NEEDS_PHONE_UNLOCK"` (it would have fallen through to the brain before the fix).
   — done when: the new test fails against the pre-fix gate and passes after Task 1.
3. **Map icacls `CalledProcessError` to a fail-closed `CommandResult`** — in
   `src/artemis/agentic/sandbox.py`, add a `subprocess.CalledProcessError` arm to the `try` in
   `WindowsAppContainerSandbox.run` (alongside `except OSError`) that returns
   `CommandResult(exit_code=2, stdout="", stderr=f"sandbox setup failed: {exc}")`.
   — done when: an icacls/ACL-grant failure during `run()` yields an error `CommandResult` rather than
   an unhandled exception; a test that forces `_grant_workspace_acl` to raise `CalledProcessError`
   asserts the fail-closed `CommandResult`.

## Files to touch
- `src/artemis/gateway.py` — `handle_voice` gate made fail-closed (Task 1).
- `tests/test_speaker_id_voice_scope.py` — new absent-key_provider regression test (Task 2).
- `src/artemis/agentic/sandbox.py` — `run()` catches `CalledProcessError`→fail-closed `CommandResult` (Task 3).
- `tests/test_agent_rung2.py` — new icacls-failure → error-`CommandResult` test (Task 3 verification).

## Assumptions
- The four existing `handle_voice` tests cover owner-tier1-locked (already expects NEEDS_PHONE_UNLOCK),
  non-tier1, and guest paths; none exercise the `key_provider=None` + owner + tier1 case (that is the
  bug). Impact: low — if such a test exists it would already be failing or asserting the buggy
  passthrough, and Task 2 supersedes it.
- `tests/test_agent_rung2.py` is the home for sandbox `run()` behaviour tests (it holds the existing
  network-deny / fail-closed cases). Impact: low — if the sandbox tests live elsewhere the coder adds
  the test there instead.
- Simplicity check: no simpler version achieves the same goal — each task is a single fail-closed gap
  with its regression test; no shared code, no refactor. Three tasks, two source files, both already
  built and host-runnable on the dev box.
