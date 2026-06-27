---
status: done
weight: light
cross_model_review: true
coder_effort: medium
---

> **BUILT 2026-06-27** (Codex `gpt-5.5`, host-verified, Opus cross-model reviewed). Full `uv run mypy`
> clean (333 files), full `uv run pytest -q` green (905 passed / 6 skipped); scoped suite 8 passed.
> All 4 tasks; surgical scope (4 files). **Cross-model review (Opus) = FLAG, 2 low, all security
> invariants clear** (generic clean-fail, no key/exception leak, fail-closed exit 2, factory propagates
> unlock errors): (1) **folded** — added the missing `UnlockDeniedError` clean-fail tests for both CLIs
> (review found only `UnlockUnavailableError` was tested); (2) **flag for planning** — `email_rules.py`
> `_EnvKeyProvider` (lines ~213) is now dead code (its sole caller `build_key_provider` now delegates
> to the owner factory); left in place (don't delete pre-existing code without an explicit ask) —
> recommend a follow-up surgical removal. NB the spec's assumption that email_rules' `build_key_provider`
> "raises on win32" was inaccurate — it returned a dev `_EnvKeyProvider()`; built to spec intent
> (Hello-gated owner factory, owner-present by design).

# win-owner-cli-keyprovider — wire owner-private CLIs to the Windows key provider (Phase D prereq)

## Intent
Make the owner-present CLIs work on Windows so the Phase-D Google activation can run. Both
`artemis-google-auth` (`integrations/google/cli.py`) and `artemis-dev-email-rules`
(`dev/email_rules.py`) call a `build_key_provider()` that is a Mac-broker stub — it **raises
`RuntimeError` on win32**, so `artemis-google-auth login` crashes before reaching Google. m2-win-b
shipped `WindowsKeyProvider` (Hello-gated); this wires the CLIs to it via a shared platform factory.

## Assumptions
- m2-win-b's `WindowsKeyProvider(settings)` exposes `provision()` / `unlock()` (Hello-enforced) /
  `dek_for_scope` / `is_owner_unlocked`. → impact: Stop.
- Both CLIs construct their owner-private store from a `KeyProvider` and currently obtain it from a
  local `build_key_provider()` that raises on every platform (the broker factory is unbuilt). →
  impact: Stop (replace that body, don't add a new seam).
- `main.py` already platform-branches the provider (m2-win-b). This spec does **not** touch `main.py`
  — adopting the shared factory there is a deferred follow-up (avoid re-editing the critical lifespan).
  → impact: Low.

## Key decisions
- **Shared factory** `build_owner_key_provider(settings) -> KeyProvider` (new
  `identity/owner_provider.py`) — win32 → `WindowsKeyProvider(settings)`, `provision()`, `unlock()`
  (Hello), return unlocked; non-win32 → raise the existing "broker factory unbuilt" `RuntimeError`
  (Darwin behaviour unchanged until M2-a/c land). DRY — both CLIs call it.
- **Owner-present by design:** these CLIs touch owner-private data, so triggering a real Hello
  gesture on invocation is correct (not a regression).

## Gotchas / edge cases
- `unlock()` raises `UnlockUnavailableError` / `UnlockDeniedError` (m2-win-b). Each CLI must catch
  these at the call site and exit non-zero with a **generic** message (mirror `artemis-unlock`'s
  posture — no traceback, no exception-class name, log the specific reason at WARNING). Never print
  key material.
- Tests mock `windows_hello.hello_available`/`verify` and pin `APPDATA`/`LOCALAPPDATA` + `data_root`
  to a tmp dir under the profile (the established m2-win-b / finance fixture pattern), so no live
  gesture is needed.
- The factory provisions-then-unlocks (creates DEKs if absent) — identical to `artemis-unlock`; safe
  to call repeatedly.

## Tasks
1. `build_owner_key_provider(settings)` factory — files: `src/artemis/identity/owner_provider.py`
   (create) — win32 branch (provision + Hello unlock + return); else raise the existing broker-unbuilt
   `RuntimeError`. — done when: `uv run mypy` clean; a win32 test (Hello mocked True, tmp profile)
   returns a provider with `is_owner_unlocked()` True; Hello-unavailable raises `UnlockUnavailableError`.
2. Wire `artemis-google-auth` — files: `src/artemis/integrations/google/cli.py` (modify) — replace
   the raising `build_key_provider()` body with a call to `build_owner_key_provider(get_settings())`;
   wrap the `login`/`status`/`revoke` key-provider construction so an unlock failure exits 2 with a
   generic message. — done when: `artemis-google-auth status` (Hello mocked, fake token store)
   constructs the provider with no `RuntimeError` on win32; Hello-unavailable → exit 2 generic.
3. Wire `artemis-dev-email-rules` — files: `src/artemis/dev/email_rules.py` (modify) — same: its
   `build_key_provider()` → the shared factory; unlock-failure → exit non-zero generic. — done when:
   the harness builds its runtime with the Windows provider (Hello mocked) and fails cleanly when Hello
   is unavailable.
4. Tests — files: `tests/test_owner_provider_cli.py` (create) — the factory win32 happy/​unavailable
   paths + both CLIs' construct-and-clean-fail paths (Hello mocked; tmp profile). — done when:
   `uv run pytest -q tests/test_owner_provider_cli.py` passes and full `uv run mypy` + `uv run pytest -q`
   stay green.

## Files to touch
- `src/artemis/identity/owner_provider.py` — create (the shared factory)
- `src/artemis/integrations/google/cli.py` — modify (`build_key_provider` → factory + clean-fail)
- `src/artemis/dev/email_rules.py` — modify (`build_key_provider` → factory + clean-fail)
- `tests/test_owner_provider_cli.py` — create
