---
status: ready
mode: deep
coder_model: codex
cross_model_review: true
risk: high
---

# m2-win-b — Windows Hello unlock gate + brain wiring

**Identity:** Phase-1 unlock layer of the Windows-host wall (ADR-033): gate `WindowsKeyProvider.unlock()`
behind a **Windows Hello** verification (console-window HWND), add an `artemis-unlock` setup/check CLI,
and **wire `WindowsKeyProvider` into the brain startup** (`main.py`) in place of the Mac `BrokerKeyProvider`
on Windows. Builds on `m2-win-a`.

## Prerequisites
- `m2-win-a-encryption-at-rest` (provides `WindowsKeyProvider`, `dpapi.py`, real `sqlcipher_open`).

## Assumptions
- `m2-win-a` shipped `WindowsKeyProvider(settings)` with `provision()/unlock()/lock()/dek_for_scope/
  is_owner_unlocked`. → impact: Stop.
- `winsdk` (PyWinRT) exposes `windows.security.credentials.ui.UserConsentVerifier`; Win32/desktop
  processes must call `RequestVerificationForWindowAsync(hwnd, message)` via the interop, not the bare
  UWP `RequestVerificationAsync`. A console process supplies its HWND via `kernel32.GetConsoleWindow()`.
  → impact: Caution (console-HWND is the build-time confirm item). **When Hello is unavailable (no console
  HWND / not enrolled / no hardware) `unlock()` MUST raise `UnlockUnavailableError` — there is NO silent
  auto-unseal fallback** (BLOCK fix — that would be a downgrade-attack path).
- **Threat boundary (FLAG — accepted Phase-1 risk):** Phase-1 Hello is a **process-level software gate, not
  a TPM-attested cryptographic binding** — `verify()` returns a bool that `unlock()` trusts, then DPAPI-unseals
  separately. A local attacker with in-process code execution (DLL injection, a compromised dependency, a
  malicious tool) can bypass it. Accepted until Phase 2 moves the gesture to the Tauri HWND (ADR-025/033) and
  the Mac SE broker; the threat model assumes the process image is not compromised. State this in the module docstring.
- **Rate limiting (FLAG):** delegated to Windows Hello's OS/TPM lockout (≈5 failed gestures → lockout); no
  app-level counter for the live gesture. A non-gesture code path (tests) must not loop against the OS counter.
- `main.py` lifespan composes the brain at line ~35 `compose_brain(settings, embedder=embedder)` **without**
  a key_provider, and separately builds a Mac `BrokerKeyProvider(broker_client, _relay_prover)` over
  `broker.sock` (a Unix socket; absent on Windows). The `slot=="prod"` guard (line ~42) currently demands
  `BrokerKeyProvider`. → impact: Stop (the wiring + guard must branch by platform).
- `Settings` carries `require_hello_unlock: bool = True`. **It gates whether startup ABORTS when Hello is
  unavailable — it does NOT toggle whether Hello is called** (BLOCK fix; no bypass param exists). → impact: Low.
- **Simplicity check:** the gesture is one `verify()` call gating `unlock()`'s DPAPI unseal; no new key
  material, no second factor. The CLI is a thin provision+verify utility, not a daemon.

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| `src/artemis/identity/windows_hello.py` | create | `hello_available()` + `verify(message) -> bool` via winsdk + console HWND. |
| `src/artemis/identity/windows_key_provider.py` | modify | Refactor m2-win-a's unseal body into a private `_unseal_all()`; new public `unlock()` is ALWAYS Hello-enforced — **no bypass param**. |
| `tests/test_windows_key_provider.py` | modify | m2-win-a tests that drove `unlock()` now mock `windows_hello.verify`→True (or call `_unseal_all()` directly) so they don't require a live gesture. |
| `src/artemis/cli/unlock.py` | create | `artemis-unlock` CLI: provision + Hello verify + report (no DEK printed). |
| `src/artemis/main.py` | modify | Platform-branch the key_provider: win32 → `WindowsKeyProvider` (provision+unlock) passed to `compose_brain` **and** `app.state.key_provider`; keep `BrokerKeyProvider` on Darwin; fix the prod-slot guard. |
| `pyproject.toml` | modify | Add `winsdk` dep; add `artemis-unlock = "artemis.cli.unlock:main"` to `[project.scripts]`. |
| `tests/test_windows_hello_unlock.py` | create | `unlock(verify_hello=True)` with `verify` mocked True→unseals / False→raises `UnlockDeniedError`; CLI smoke with mocked Hello. |

## Exact changes

- [ ] **Task 1 — `windows_hello.py`** (new). `hello_available() -> bool` (winsdk
  `UserConsentVerifier.check_availability_async()` == Available, run to completion synchronously).
  `verify(message: str) -> bool`: resolve the console HWND via `ctypes.windll.kernel32.GetConsoleWindow()`;
  if `0`, raise `NoConsoleWindowError`; call the `UserConsentVerifierInterop.RequestVerificationForWindowAsync(hwnd, message)`
  and return `result == UserConsentVerificationResult.VERIFIED`. Guard `sys.platform == "win32"`.
  - done when: on this Hello-enrolled box, `hello_available()` is True and `verify("Unlock Artemis")` returns
    True after a successful gesture (MANUAL/interactive — gate behind an env-marked test; the unit test mocks
    the winsdk call).

- [ ] **Task 2 — Hello-enforced `unlock()`** (`windows_key_provider.py`). **BLOCK fix: no bypass param.**
  Refactor m2-win-a's DPAPI-unseal loop into a **private `_unseal_all() -> None`** (test/internal only).
  The public **`unlock() -> None`** (zero args) is ALWAYS Hello-enforced:
  ```python
  def unlock(self) -> None:
      if not windows_hello.hello_available():
          raise UnlockUnavailableError("Windows Hello is not available")   # no auto-unseal fallback
      if not windows_hello.verify("Unlock Artemis owner-private data"):
          raise UnlockDeniedError("Hello gesture was not verified")        # never unseal on deny
      self._unseal_all()
  ```
  Production callers use `unlock()` only; `_unseal_all()` is private (tests may call it directly or mock
  `windows_hello.verify`). There is NO `verify_hello` parameter anywhere.
  - done when: `unlock()` with `verify` mocked→False raises `UnlockDeniedError`, `is_owner_unlocked()` stays
    False, nothing unsealed; mocked→True unseals; `hello_available()` mocked→False raises `UnlockUnavailableError`
    and unseals nothing; `_unseal_all()` is not part of the public surface (leading underscore).

- [ ] **Task 3 — `artemis-unlock` CLI** (`cli/unlock.py`, new). `main()`: load settings →
  `WindowsKeyProvider(settings)` → `provision()` → `unlock()` → print `"unlocked: <n> scope(s)"` (NEVER
  print key material) → `lock()` and exit 0. On failure exit 2 with a **generic** message that does not
  expose the exception class or distinguish enrolled-vs-denied (note fix): `"Unlock failed."` (log the
  specific reason at WARNING for the local owner, not to stdout). Add the `[project.scripts]` entry.
  - done when: `artemis-unlock` with Hello mocked→True prints the scope count and exits 0; mocked→False exits 2
    with the generic message; no hex/DEK and no exception-class name ever appears in stdout.

- [ ] **Task 4 — wire into `main.py`** + `Settings`. Add `require_hello_unlock: bool = True` to `Settings`.
  In `lifespan`, replace the unconditional `BrokerKeyProvider` with a platform branch:
  - **`slot=="prod"` hard-block (FLAG fix):** `if settings.slot == "prod" and not settings.require_hello_unlock:
    raise RuntimeError("prod requires Hello unlock; require_hello_unlock=False is blocked")`. Log a WARNING
    whenever `require_hello_unlock` is False in any slot (the bypass must be visible in structured logs).
  - `if sys.platform == "win32":` build `kp = WindowsKeyProvider(settings); kp.provision()`; then
    `try: kp.unlock()` (always Hello-enforced, no arg) `except UnlockUnavailableError:` → if
    `settings.require_hello_unlock` **re-raise (abort startup)**, else WARN-log and continue with owner-private
    scopes **LOCKED** (`is_owner_unlocked()` False — never a silent unseal). Pass `key_provider=kp` to
    `compose_brain` and set `app.state.key_provider = kp`. Keep `BrokerKeyProvider` on Darwin; update the
    prod-slot type check to accept `WindowsKeyProvider` on win32.
  - done when: `uv run mypy` clean; a win32 lifespan test (`verify` mocked True) composes the brain with a
    `WindowsKeyProvider` as `app.state.key_provider`; `slot=="prod"` + `require_hello_unlock=False` raises at
    startup; Hello-unavailable + `require_hello_unlock=True` aborts; the Darwin path is unchanged.

## Acceptance criteria
1. Tasks 1–4 done-when clauses pass; `tests/test_windows_hello_unlock.py` green (winsdk + GetConsoleWindow mocked).
2. Full `uv run mypy` clean + `uv run pytest -q` green; existing main.py/auth tests stay green (Darwin path untouched).
3. `uv sync` resolves a **pinned** `winsdk` (cp312-win wheel); `uv.lock` committed; `uv run pip-audit` → 0
   high/critical; `winsdk` package name verified on PyPI (correct publisher, no typosquat).
4. No public `unlock()` bypass: `grep -r "verify_hello" src/` returns nothing; `slot=="prod"` +
   `require_hello_unlock=False` raises at startup.
5. **MANUAL (gated, on the dev box):** `artemis-unlock` triggers a real Windows Hello prompt and unlocks on success — recorded in the spec Progress, not a CI gate.

## Commands to run
```
uv add "winsdk>=1.0.0b10,<2"     # pinned; verify publisher/no-typosquat on PyPI
uv run pip-audit                 # 0 high/critical; commit uv.lock
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest -q
```

## Wave plan
- Wave 1: [Task 1]              (windows_hello.py — standalone)
- Wave 2: [Task 2, Task 3]      (key-provider gate · CLI — both consume Task 1; disjoint files)
- Wave 3: [Task 4]              (main.py wiring — consumes Tasks 2/3)

## Documentation
- Docstrings noting the console-HWND requirement and — explicitly — the **process-level-gate threat boundary**
  (not a crypto binding; bypassable by in-process code; accepted Phase-1 risk) and that **Hello-unavailable
  raises `UnlockUnavailableError`, never auto-unseals**.
- Confirm m2-win-a's `lock()`/`SecretKey.wipe()` zeroes the in-memory DEK (cite it); the Hello path adds no
  new long-lived key copy.
- Reference **ADR-033**; note Phase 2 moves the gesture to the Tauri client (HWND) per ADR-025.
- **Critical file:** `main.py` and `Settings` change the production unlock path — confirm at review.
