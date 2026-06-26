---
status: ready
mode: deep
coder_model: codex
cross_model_review: true
risk: high
---

# m2-win-a — Windows encryption-at-rest (DPAPI key custody + real SQLCipher)

**Identity:** The Windows-host security wall, Phase-1 core (ADR-033): a `WindowsKeyProvider` that
custodies a per-scope DEK **sealed at rest via DPAPI** and a **real SQLCipher** `sqlcipher_open` keyed
by it — replacing the plain-sqlite dev shim. Owner-private stores become genuinely encrypted at rest,
bound to this Windows user+machine. The Windows Hello *unlock gesture* is the sibling spec
`m2-win-b` (this spec auto-unseals as the logged-in owner; Hello gating is additive on top).

## Assumptions
- `KeyProvider` protocol = `dek_for_scope(scope) -> SecretKey` + `is_owner_unlocked() -> bool`;
  `SecretKey` wraps 32 bytes with `.as_hex()` (hex for `PRAGMA key`) and `.wipe()`; locked scope raises
  `ScopeLockedError`. (`src/artemis/identity/key_provider.py`.) → impact: Stop (the new provider must
  match this exactly so it drops into the existing injection sites).
- `sqlcipher_open(path: Path, key_hex: str) -> sqlite3.Connection` is the single seam every
  owner-private store opens through (GATE-a staging, M8-a tokens, M8-d-a tasks, FIN-a ledger, agentic
  authority/checkpoint/inbox). It currently returns a plain `sqlite3.connect(path)` ignoring `key_hex`.
  (`src/artemis/data/sqlcipher.py`.) → impact: Stop.
- Scopes in play: `OWNER_PRIVATE = "owner-private"`, `GENERAL = "general"`
  (`src/artemis/identity/scope.py`). → impact: Low.
- `sqlcipher3-binary` publishes self-contained pre-built Windows wheels (latest 2025-12, no external
  deps) → `pip`/`uv` installs the real SQLCipher binding with no toolchain. → impact: Stop (verified
  by research 2026-06-26; confirm the wheel resolves for cp312-win at build).
- Windows DPAPI (`CryptProtectData`/`CryptUnprotectData`, crypt32.dll) is reachable from stdlib
  `ctypes` with no third-party dep, and works headless for the logged-in user. → impact: Caution
  (round-trip is an acceptance criterion below).
- `Settings` exposes `data_root: Path` (per `Settings(data_root=...)` usage in tests). → impact: Low.
- **Simplicity check:** the simplest spec that achieves at-rest encryption is exactly these three
  units (real `sqlcipher_open` · DPAPI seal/unseal · a `KeyProvider` that wires them); no broker IPC,
  no Hello, no two-tier proactive key in this spec — those are deferred (Hello → m2-win-b; broker/SE →
  Mac). Nothing speculative added.

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| `pyproject.toml` | modify | Add `sqlcipher3-binary` to the base deps (real owner-private encryption is core, not optional). |
| `src/artemis/data/sqlcipher.py` | modify | Replace the plain-sqlite shim with a real SQLCipher keyed open. |
| `src/artemis/identity/dpapi.py` | create | ctypes wrappers `dpapi_seal`/`dpapi_unseal` over crypt32. |
| `src/artemis/identity/windows_key_provider.py` | create | `WindowsKeyProvider` (provision/unlock/lock + the KeyProvider protocol). |
| `tests/test_windows_key_provider.py` | create | DPAPI round-trip, provision→unlock→dek, lock wipes, SQLCipher real-key round-trip + raw-file-has-no-plaintext. |

## Exact changes

- [x] **Task 1 — real `sqlcipher_open`** (`src/artemis/data/sqlcipher.py`). Replace the stub body:
  validate `key_hex` is exactly 64 hex chars first (raise `ValueError`, never echoing the value). Import
  `sqlcipher3` lazily — **the `sqlcipher3-binary` wheel provides it; do NOT accept the `sqlcipher3`
  source package** (comment the import: `import sqlcipher3  # from sqlcipher3-binary wheel; not the source build`).
  `conn = sqlcipher3.connect(str(path))`. **Apply the key inside a bare try/except that never leaks it
  (BLOCK fix — review):**
  ```python
  try:
      conn.execute(f"PRAGMA key = \"x'{key_hex}'\"")
      if conn.execute("PRAGMA cipher_version").fetchone() is None:
          raise SqlCipherError("binding is not SQLCipher")
  except Exception:
      conn.close()
      raise SqlCipherError("key application failed") from None   # `from None` drops the PRAGMA-text context
  ```
  On `ImportError`, raise `SqlCipherError("sqlcipher3 binding not installed")`. Keep the exact signature
  `(path: Path, key_hex: str) -> sqlite3.Connection`. The `PRAGMA key` string must never be logged and
  the connection must not be `repr()`-ed before the key is applied (docstring note).
  - done when: same-key reopen reads a written row; **different**-key reopen raises `SqlCipherError`; the
    raw `.db` bytes contain neither the row value nor `b"SQLite format 3"`; **and the wrong-key /
    corrupted-file exception text + its `__cause__`/`__context__` chain contain no substring of `key_hex`.**

- [x] **Task 2 — DPAPI seal/unseal** (`src/artemis/identity/dpapi.py`, new). `dpapi_seal(plaintext: bytes,
  *, entropy: bytes) -> bytes` and `dpapi_unseal(blob: bytes, *, entropy: bytes) -> bytearray` via `ctypes`
  to `crypt32.CryptProtectData`/`CryptUnprotectData`, passing the entropy as the optional `pOptionalEntropy`
  `DATA_BLOB`, and `kernel32.LocalFree` on the returned blob. **`entropy` is REQUIRED (no default) — callers
  pass the per-scope value (Task 3).**
  - **BLOCK fix (review): pass `dwFlags = 0` for USER-scope** (the owner's Windows credential). **Do NOT
    define or pass a `CRYPTPROTECT_LOCAL_MACHINE` constant** — the real Windows constant is value **4 =
    machine-scope**, which would let any local account decrypt the DEK. Add a code comment: `# dwFlags=0 ->
    user-scope; never CRYPTPROTECT_LOCAL_MACHINE (=4, machine-scope, wrong)`.
  - **FLAG fix (review): `dpapi_unseal` returns a mutable `bytearray`** (not immutable `bytes`) so the caller
    can zero it after use. Raise `DpapiError` on a falsey API return (with `GetLastError`, no key material in
    the message). Guard `if sys.platform != "win32": raise` at call.
  - done when: `bytes(dpapi_unseal(dpapi_seal(b, entropy=e), entropy=e)) == b` for a 32-byte `b`; a blob
    sealed with entropy `e1` fails to unseal with `e2`; **a blob sealed by Windows user A cannot be unsealed
    by a second Windows account on the same machine** (user-scope confirmed); `dpapi_unseal` returns `bytearray`.

- [x] **Task 3 — `WindowsKeyProvider`** (`src/artemis/identity/windows_key_provider.py`, new). Implements
  the `KeyProvider` protocol. Constructor `(settings: Settings, *, scopes: tuple[Scope, ...] = (OWNER_PRIVATE,))`.
  - **`__init__` asserts the key dir is owner-private (FLAG fix):** `<data_root>` MUST resolve under
    `%APPDATA%`/`%LOCALAPPDATA%` (inherited owner-only ACL); assert at construction, else raise
    `InsecureKeyStoreError`. The per-scope entropy is **`f"artemis-v1-{scope}".encode()`** (FLAG fix — the
    per-scope security boundary; a GENERAL blob must not unseal as OWNER_PRIVATE).
  - `provision() -> None`: for each scope, if `<data_root>/keys/<scope>.dek` is absent, generate
    `secrets.token_bytes(32)`, `dpapi_seal(... entropy=f"artemis-v1-{scope}".encode())`, and **write
    ATOMICALLY (FLAG fix): write to `<scope>.dek.tmp` then `os.replace(tmp, "<scope>.dek")`** (atomic on
    same volume) so an interrupted provision never leaves a half-written, unseal-failing DEK (irreversible
    data loss). `mkdir(parents=True, exist_ok=True)` the `keys/` dir.
  - `unlock() -> None`: for each scope, read the sealed file, `dpapi_unseal` (→ `bytearray`), construct
    `SecretKey(bytes(buf))`, **then zero the intermediate buffer `buf[:] = bytes(len(buf))` before
    discarding (FLAG fix — zeroization)**; hold the `SecretKey` in an in-memory dict; set `_unlocked = True`.
    Missing key file → `ScopeLockedError`.
  - `dek_for_scope(scope) -> SecretKey`: return the held key or raise `ScopeLockedError` if not unlocked
    / scope absent.
  - `is_owner_unlocked() -> bool`: return `_unlocked`.
  - `lock() -> None`: `wipe()` every held `SecretKey` (zeros its bytearray), clear the dict, `_unlocked = False`.
  - done when: `provision()` then `unlock()` makes `is_owner_unlocked()` true and `dek_for_scope(OWNER_PRIVATE)`
    return a 32-byte `SecretKey`; a second `WindowsKeyProvider` over the same data_root unlocks the **same**
    key; `lock()` flips `is_owner_unlocked()` false and `dek_for_scope` raises; a blob sealed under
    `OWNER_PRIVATE` entropy fails to unseal under `GENERAL`; an interrupted `provision()` (before `os.replace`)
    leaves no `.dek` and re-running succeeds; the `unlock` intermediate `bytearray` is zeroed before return.

## Acceptance criteria
1. `uv run python -c "from artemis.data.sqlcipher import sqlcipher_open"` imports; a round-trip test
   (Task 1 done-when) passes including the raw-file-has-no-plaintext + wrong-key checks.
2. `tests/test_windows_key_provider.py` covers Tasks 2 + 3 done-when clauses and passes.
3. Full `uv run mypy` clean and `uv run pytest -q` green (the now-real `sqlcipher_open` keeps every
   existing owner-private store test green — same signature; FakeKeyProvider's 32-byte keys now actually
   encrypt).
4. `uv sync` resolves `sqlcipher3-binary` as a cp312-win wheel (no build toolchain invoked); `uv.lock`
   committed with the wheel hash; `sqlcipher3` (source) is NOT installed alongside.
5. `uv run pip-audit` → 0 high/critical against `sqlcipher3-binary`.
6. DPAPI user-scope confirmed: a `.dek` sealed by one Windows account cannot be unsealed by another on the
   same machine.

## Commands to run
```
uv add sqlcipher3-binary
uv run pip-audit                 # 0 high/critical (supply-chain gate); commit uv.lock with the wheel hash
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest -q
```

## Wave plan
- Wave 1: [Task 1, Task 2]  (disjoint files: sqlcipher.py · dpapi.py)
- Wave 2: [Task 3]          (windows_key_provider.py depends on dpapi.py from Wave 1)

## Documentation
- Inline docstrings on `dpapi_seal/unseal`, `WindowsKeyProvider`, and the rewritten `sqlcipher_open`.
  The `WindowsKeyProvider`/`dpapi_unseal` docstrings MUST state the boundary explicitly: **protects against
  offline disk theft + cross-user access; does NOT protect against a same-user-credential attacker (malware,
  session hijack)** — deferred to m2-win-b (Hello) + the Mac SE broker. `sqlcipher_open`: the `PRAGMA key`
  string is never logged; do not `repr()` the connection before the key is applied.
- ADR: covered by **ADR-033** (Windows-host v1, lighter interim wall) — no new ADR; reference it.
