---
spec: cred-store
status: ready
token_profile: balanced
autonomy_level: L2
coder_model: codex
coder_effort: high
cross_model_review: true
risk: high
---

# Spec: Credential store — keyring-backed SecretStore behind a port (enabler #2, part i)

**Identity:** The trusted at-rest home for owner credentials: a `SecretStorePort` + an OS-keychain-
backed `KeyringSecretStore` (Windows Credential Manager / macOS Keychain via `keyring`). Foundation
for secret-capture (step 4) + the build-flow key gate (step 5). Retires the env-var stopgap.
→ why: ADR-035 enabler #2 ("secret-capture UI on the OS-keychain store").

## Assumptions
- The BRAIN runs on the host (Windows/Mac), NOT inside WSL2 — so OS-keychain access is available;
  the WSL2 sandbox never reads the keychain (secrets are injected at runtime in step 5) → impact: Low
- `keyring` is a well-known, actively-maintained PyPI package (jaraco) → adding it is safe → impact: Low
- No app-level lock (CR-2 no-lock decision): the OS keychain IS the at-rest protection; no master
  passphrase in this spec → impact: Caution (revisit only if the owner later wants an app lock)
- `keyring` has NO native enumerate/list → a names-only index (names are NOT secret) is kept
  separately so the store can list what's held → impact: Low

Simplicity check: considered a `cryptography`-Fernet encrypted-file store (no new dep) — rejected;
it needs a master key with nowhere secure to live (re-introduces the lock problem CR-2 dropped),
whereas the OS keychain solves at-rest + key custody natively. keyring is the ADR-035 choice.

## OPEN DECISION (surface to owner — does NOT block the build; conservative default taken)
- **Headless/CI fallback.** `keyring` needs an OS backend; on headless Linux/CI it has none. This
  spec targets the host (Windows/Mac) where a backend exists, and makes the backend an INJECTABLE
  SEAM so tests use an in-memory fake. If the owner later wants the brain to run headless, add a
  `cryptography`-Fernet file backend behind the same port then. Not built now.

## Prerequisites
- Specs complete first: none
- Environment: `uv sync` (adds keyring); real keychain only exercised manually — tests are hermetic

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| pyproject.toml | modify | add `keyring>=25` to dependencies |
| src/artemis/ports/secrets.py | create | `SecretStorePort` protocol: get/set/delete/list_names |
| src/artemis/secrets_store.py | create | `KeyringSecretStore` — keyring backend seam + names-only JSON index |
| tests/test_secrets_store.py | create | hermetic: injected in-memory backend + tmp_path index |

## Tasks
- [ ] Task 1: SecretStorePort — files: src/artemis/ports/secrets.py — done when: a `@runtime_checkable Protocol` with `get(name: str) -> str | None`, `set(name: str, value: str) -> None`, `delete(name: str) -> None`, `list_names() -> list[str]` imports clean; mypy clean. Docstrings note values are never logged.
- [ ] Task 2: KeyringSecretStore — files: src/artemis/secrets_store.py — done when: `KeyringSecretStore(index_path: Path, *, backend=<keyring seam>)` implements the port over a fixed service namespace "artemis". The backend is an injectable seam (default = the real `keyring` get/set/delete_password) so tests use an in-memory fake. `set` writes the value to the backend AND adds the name to a names-only JSON index at `index_path` (atomic write, 0o600); `delete` removes both; `list_names` reads the index; `get` reads the backend. NEVER log or exception-message a secret VALUE (redact). Names are not secret. mypy clean.
- [ ] Task 3: Hermetic tests — files: tests/test_secrets_store.py — done when: `uv run pytest tests/test_secrets_store.py -q` passes with NO real keychain access (inject an in-memory dict backend, index in tmp_path). Assert: set→get round-trips; delete removes value + name; list_names reflects sets/deletes; a missing name → get returns None; the index file contains names but NOT values; overwriting a name updates the value and keeps one index entry.

## Wave plan
Wave 1: [Task 1] | Wave 2: [Task 2] | Wave 3: [Task 3]

## Permissions
### File Operations
| Action | Paths |
|--------|-------|
| Create | src/artemis/ports/secrets.py, src/artemis/secrets_store.py, tests/test_secrets_store.py |
| Modify | pyproject.toml (add keyring dep only) |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv sync` | install keyring |
| `uv run pytest tests/test_secrets_store.py -q` | store tests (hermetic) |
| `uv run mypy` | typecheck |
| `uv run ruff check src tests` | lint |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | pyproject.toml uv.lock src/artemis/ports/secrets.py src/artemis/secrets_store.py tests/test_secrets_store.py |
| `git commit` | "feat: keyring-backed credential store behind SecretStorePort" |

### Network
| Action | Purpose |
|--------|---------|
| (none) | store is local; no network |

## Specialist Context
### Security
- This is the trust boundary's at-rest store — apex-security MUST review. Invariants: secret VALUES
  never hit logs / exception messages / the names index (redact everywhere); index holds NAMES ONLY;
  index file written atomically with 0o600; the store is host-side only (never handed into the WSL2
  sandbox — step 5 injects specific values at runtime, it does not expose the store).
- No plaintext-at-rest: values live in the OS keychain, not in the index or any file.

### Performance
(none — trivial)

### Accessibility
(none)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | src/artemis/ports/secrets.py, src/artemis/secrets_store.py | docstrings; note the no-log-values invariant |

## Acceptance Criteria
- [ ] Port defined + importable → verify: `uv run python -c "from artemis.ports.secrets import SecretStorePort"` exits 0
- [ ] Round-trip + list + delete → verify: Task 3 tests green
- [ ] Values never in the index → verify: Task 3 asserts index file has names, not values
- [ ] Full gate green → verify: `uv run mypy` + `uv run ruff check src tests` + `uv run pytest -q` exit 0

## Progress
_(Coding mode writes here — do not edit manually)_
