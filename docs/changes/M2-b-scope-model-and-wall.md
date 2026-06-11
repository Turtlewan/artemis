---
spec: m2-b-scope-model-and-wall
status: ready
token_profile: balanced
autonomy_level: L2
---
<!-- amended 2026-06-11 per Decision D4/D5 (contracts.md Seam 10) -->

# Spec: M2-b — Scope model (owner/guest) + per-scope store provisioning + brain-side scope attachment (replace M1 Gateway stub) + crypto-wall enforcement at the data layer

**Identity:** Defines the real owner/guest scope model, replaces M1-c's single-owner Gateway stub with real owner-authenticated scope resolution (+ guest scope infrastructure with recognition deferred), provisions a separate SQLCipher DB handle + separate vector-index handle per scope, and enforces the crypto wall at the data layer (a scope can only open its own DB with its own key).
→ why: see docs/technical/adr/ADR-005-owner-key-broker.md (per-scope keys + wall) · docs/technical/architecture/brain.md § "Security — owner↔guest wall by CRYPTOGRAPHY" + § "Identity & scoping" · docs/technical/adr/ADR-004-memory-engine.md (per-scope SQLCipher file, born encrypted under this key).

<!-- Split rule: ONE logical phase (the scope/data-layer wall) but it touches >3 files because the wall is enforced across three seams that must agree: the scope model + provisioning (new), the data-layer ScopedStore guard (new), and the Gateway scope-attach (modify M1-c). They share the `Scope`/`PersonId` vocabulary and the same key-handle abstraction; splitting would let the Gateway attach a scope the data layer can't enforce. Justified atomic exception, flagged per rules. The brain↔broker IPC client + the actual DEK delivery is M2-c; M2-b consumes an injected `KeyProvider` PORT (real impl wired in M2-c) so the wall logic is testable now with a fake. -->

## Assumptions
- M0-a (`Scope`/`paths.scope_dir`), M0-d (`Scope`/`PersonId`/`MemoryStore`/`VectorStore` ports), M1-c (the `Gateway` with the single-owner stub to replace) are complete. → impact: Stop (this spec extends those exact symbols).
- M2-b does NOT implement the broker IPC client, mlock, or SQLCipher `PRAGMA key` raw-hex opening — those are M2-c. M2-b defines a `KeyProvider` PORT (`def dek_for_scope(scope: Scope) -> SecretKey`) that M2-c implements over the broker; M2-b ships a `FakeKeyProvider` for tests. → impact: Stop (keeps M2-b testable off-hardware and keeps the IPC concern in M2-c; the port is the seam).
- The scope model is exactly two roles: **owner** (full access; scope `owner-private` + the shared `general` scope) and **guest** (light access + a tiny preference profile, walled off; scope `guest-<person_id>`). Owner is identified by the phone unlock (the proof verified in M2-a, delivered via M2-c); the text/app surface in M2 is **owner-authenticated**. **Guest *recognition* (voice-ID) is M5** — M2 builds the guest scope INFRASTRUCTURE (separate DB + vector handle + provisioning) but recognition is a documented stub/seam. → impact: Caution (M2 ships no path that lets an unauthenticated caller obtain a guest scope at runtime; the guest provisioning + wall are real, the auto-recognition is deferred).
- "Owner-authenticated" in M2 means: the Gateway accepts a request only when an owner session is unlocked (the broker reports a valid unlocked session via M2-c's `KeyProvider`/session check); absent an unlocked owner session the Gateway returns a typed `LOCKED` response rather than silently serving owner data. → impact: Caution. M2 binds "the text surface is owner" to "an owner session is currently unlocked at the broker" (unlocked-owner-session ⇒ owner scope; else LOCKED). A per-request auth token is deferred to the client milestone. This is the M2 owner-auth model the M2-d gate reviews (no unauthenticated path may reach owner scope).
- The wall is enforced at the DATA layer: a `ScopedStore` opened for scope X can only ever open the SQLCipher file under `scope_dir(X)` with the DEK for X; passing a mismatched scope/key is rejected before any file handle opens. → impact: Stop (this is the structural wall; ADR-005/004).
- Each scope gets a SEPARATE vector-index handle. Per ADR-004, owner *memory* vectors live INSIDE the per-scope SQLCipher file (sqlite-vec) — NOT LanceDB; LanceDB stays for the non-sensitive document corpus (owner-private/general only, M3). In M2 the "vector-index handle" is a typed HANDLE/locator object per scope (not an initialised engine — engines are M3/M4); M2 proves the handles are distinct per scope and that a guest scope gets its own. → impact: Caution (M2 provisions handles + the wall; engine init is later). Decision D4: the LanceDB doc-corpus index for owner scopes lives at `scope_dir(scope)/vault/` — the APFS encrypted-volume mount point (M2-a `VolumeMount`); in M2-b the vector-index handle is a locator pointing to `paths.vault_dir(settings, scope)` (the `vault/` subpath), NOT to `scope_dir` directly. SQLCipher DBs, by contrast, open directly at `scope_dir(scope)/` — no `vault/` segment.

Simplicity check: considered enforcing the wall only logically (a `scope` column / row filter in one shared DB) — rejected: ADR-005/004 lock a STRUCTURAL wall (one SQLCipher file per scope, separate key); a logical filter is exactly the FileVault-equivalent weakness the wall exists to beat. Considered building real guest voice-recognition now — rejected: voice-ID is M5; M2 only needs the guest scope to EXIST and be walled. The minimum here is: real per-scope provisioning + a data-layer guard + owner-only attach + a deferred guest-recognition seam.

## Prerequisites
- Specs that must be complete first: **M0-a** (paths/scope_dir/config), **M0-d** (`Scope`/`PersonId`/`MemoryStore`/`VectorStore` ports), **M1-c** (`Gateway`/`compose_brain` to modify). Soft/sequenced-with: **M2-a** (the broker that ultimately backs the real `KeyProvider`; M2-b uses a fake), **M2-c** (implements the `KeyProvider`/session check ports M2-b declares).
- Environment setup required: none beyond M0/M1. Fully testable off-hardware with `FakeKeyProvider` (no SQLCipher engine, no broker, no SE). The real keyed `PRAGMA key` open is M2-c/M4.

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| /Users/artemis-build/artemis/src/artemis/identity/scope.py | create | `Identity`, `Role` (owner/guest), scope resolution helpers; the owner/guest scope model |
| /Users/artemis-build/artemis/src/artemis/identity/key_provider.py | create | `KeyProvider` Protocol (`dek_for_scope`, `is_owner_unlocked`) + `SecretKey` wrapper + `FakeKeyProvider` |
| /Users/artemis-build/artemis/src/artemis/data/scoped_store.py | create | `ScopedStore` + `provision_scope` + `vector_index_handle` — the data-layer crypto-wall guard |
| /Users/artemis-build/artemis/src/artemis/gateway.py | modify | replace the single-owner stub with owner-authenticated scope resolution + guest seam |
| /Users/artemis-build/artemis/tests/test_scope_wall.py | create | scope model + provisioning-isolation + wall-enforcement + Gateway LOCKED/owner tests |

## Tasks
- [ ] Task 1: Define the scope model — files: `/Users/artemis-build/artemis/src/artemis/identity/scope.py` (create `src/artemis/identity/__init__.py` too) — `Role = Literal["owner","guest"]`; frozen dataclass `Identity { person_id: PersonId, role: Role }`; constants `OWNER_PERSON_ID: PersonId` and `OWNER_PRIVATE: Scope = "owner-private"`, `GENERAL: Scope = "general"`. Functions: `owner_scopes() -> tuple[Scope, ...]` = `("owner-private","general")`; `guest_scope(person_id: PersonId) -> Scope` = `f"guest-{person_id}"`; `primary_scope(identity: Identity) -> Scope` (owner → `owner-private`; guest → `guest-{id}`); `scopes_for(identity: Identity) -> tuple[Scope, ...]` (owner → both owner scopes; guest → only its own guest scope — the wall: a guest never sees owner scopes). Reject malformed scopes with `ValueError`. — done when: `uv run mypy --strict src` passes; `scopes_for(guest)` excludes every owner scope (asserted in Task 5).

- [ ] Task 2: Define the KeyProvider port + SecretKey + fake — files: `/Users/artemis-build/artemis/src/artemis/identity/key_provider.py` — `class SecretKey` — an opaque wrapper around `bytes` that (a) refuses to render in `__repr__`/`__str__` (returns `"SecretKey(<redacted>)"`), (b) exposes `as_hex() -> str` (64-hex for SQLCipher `PRAGMA key="x'...'"`, used only by M2-c/M4), (c) exposes `wipe()` that best-effort zeroizes its buffer. `class KeyProvider(Protocol)`: `def dek_for_scope(self, scope: Scope) -> SecretKey: ...` (raises `ScopeLockedError` if the scope is not currently unlocked); `def is_owner_unlocked(self) -> bool: ...` (true only when an owner session is unlocked at the broker — M2-c implements via the broker `status`). Define `ScopeLockedError(Exception)`. `class FakeKeyProvider` (TEST) — constructed with a dict `{scope: 32-byte}` + an `owner_unlocked: bool`; `dek_for_scope` returns a `SecretKey` for known scopes else raises `ScopeLockedError`. — done when: `uv run mypy --strict src` passes; `repr(SecretKey(b"..."))` never leaks the bytes (asserted in Task 5).

- [ ] Task 3: Implement the data-layer crypto wall — files: `/Users/artemis-build/artemis/src/artemis/data/scoped_store.py` (create `src/artemis/data/__init__.py` too) — `class ScopedStore` constructed with `(scope: Scope, settings: Settings, key_provider: KeyProvider)`. On construction it records the scope but opens nothing. `def db_path(self) -> Path` = `paths.scope_dir(settings, scope) / "memory" / "memory.db"` (the per-scope SQLCipher file location; the actual keyed open is M2-c/M4). Decision D4: `ScopedStore` opens SQLCipher at `scope_dir(scope)/` **directly** — `db_path` resolves under `scope_dir`, NOT under `scope_dir/vault/`. The `vault/` sub-path is exclusively for the LanceDB encrypted volume. `def open_connection(self) -> ScopedConnection`: fetch `key = key_provider.dek_for_scope(self.scope)` (raises `ScopeLockedError` → propagates as the wall: no key, no open) and return a `ScopedConnection` HANDLE bound to `(db_path, scope, key)` — in M2 this is a typed handle that records the binding and exposes `pragma_key_statement()` returning `PRAGMA key = "x'<hex>'"` for M2-c/M4 to execute; it does NOT yet open sqlite (no engine in M2). **Wall guard:** a module-level `assert_same_scope(handle_scope, requested_scope)` that raises `CrossScopeError` if any caller tries to use a handle for a different scope. `def vector_index_handle(self) -> VectorIndexHandle`: returns a per-scope handle locator — for memory vectors: `{scope, kind: Literal["sqlite-vec"], path: db_path}`; for the LanceDB doc corpus (owner-private/general only, D4): `{scope, kind: Literal["lancedb"], path: paths.vault_dir(settings, scope)}` (i.e. `scope_dir/vault/`, the mounted APFS encrypted-volume path — distinct from the SQLCipher path and from `scope_dir` directly); document that LanceDB engine init at the `vault_dir` path arrives at M3. `def provision_scope(scope, settings, key_provider, broker_provision)` — calls `broker_provision(scope)` (a callable that in M2-c invokes `artemis-broker provision-scope --scope <s>`; in tests a fake) to create the wrapped DEK, then ensures the scope's `keys/`+`memory/` dirs exist (via `paths`), then verifies `key_provider.dek_for_scope(scope)` now succeeds. Define `CrossScopeError`, `VectorIndexHandle`, `ScopedConnection` (frozen dataclasses where logic-free). — done when: `uv run mypy --strict src` passes; opening a `ScopedStore("owner-private")` then asserting against `"guest-x"` raises `CrossScopeError` (Task 5); `vector_index_handle()` for `owner-private` returns a LanceDB locator whose `path` == `paths.vault_dir(settings, "owner-private")` (asserted in Task 5).

- [ ] Task 4: Replace the Gateway single-owner stub with real scope attachment — files: `/Users/artemis-build/artemis/src/artemis/gateway.py` — modify `Gateway`: constructor now also takes a `KeyProvider`. Replace the M1 fixed-constant attach with: `def _resolve_identity(self) -> Identity` — M2 text/app surface is owner-authenticated: if `key_provider.is_owner_unlocked()` return `Identity(OWNER_PERSON_ID, "owner")`; else raise `LockedError`. (Guest recognition is deferred: add `def _resolve_guest(self, person_id) -> Identity` returning a guest Identity, marked `# M5: voice-ID will call this; no runtime caller in M2`.) `handle_text`/`handle_text_stream`: resolve identity → `scope = primary_scope(identity)` → call `brain.respond(request_text, scope)`; on `LockedError`/`ScopeLockedError` return a typed `BrainResponse(text="LOCKED", path="locked", tool_used=None, escalated=False)` (do NOT serve owner data without an unlocked session). Update `compose_brain` to construct and inject the `KeyProvider` (default: the M2-c real provider via a factory; tests inject `FakeKeyProvider`) and build the `Gateway` with it. Keep the SSE/CLI surfaces unchanged in shape. — done when: `uv run mypy --strict src` passes; with an `owner_unlocked=False` FakeKeyProvider the Gateway returns `LOCKED`; with `True` it attaches `owner-private` and calls the Brain (Task 5).

- [ ] Task 5: Write the scope + wall tests — files: `/Users/artemis-build/artemis/tests/test_scope_wall.py` — typed pytest:
  - scope model: `scopes_for(Identity(owner))` == `("owner-private","general")`; `scopes_for(Identity(guest "bob"))` == `("guest-bob",)` and contains NO owner scope; `guest_scope("bob") == "guest-bob"`.
  - SecretKey hygiene: `"deadbeef" not in repr(SecretKey(bytes.fromhex("deadbeef"*8)))`; `as_hex()` is 64 hex chars for a 32-byte key.
  - provisioning isolation: provision `owner-private` and `guest-bob` with a fake `broker_provision` recording calls + a `FakeKeyProvider` seeded post-provision; assert each `ScopedStore.db_path()` is under its OWN `scope_dir` directly (NOT under `vault/`), the two paths differ, `vector_index_handle()` returns distinct objects per scope, and the `owner-private` LanceDB handle's `path` == `paths.vault_dir(settings, "owner-private")` (D4: LanceDB locator points at `scope_dir/vault/`, not `scope_dir` directly).
  - wall enforcement: a `ScopedStore("owner-private")` handle asserted against `"guest-bob"` raises `CrossScopeError`; `dek_for_scope` for an unprovisioned scope raises `ScopeLockedError` and `open_connection` propagates it (no key → no open).
  - Gateway owner-auth: `Gateway(FakeBrain(), FakeKeyProvider(owner_unlocked=False))` → `handle_text("hi")` returns `text=="LOCKED"`; with `owner_unlocked=True` the FakeBrain asserts it received `OWNER_PRIVATE` scope.
  — done when: `uv run pytest -q` passes AND `uv run mypy --strict src tests/test_scope_wall.py` passes.

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | /Users/artemis-build/artemis/src/artemis/identity/__init__.py, /Users/artemis-build/artemis/src/artemis/identity/scope.py, /Users/artemis-build/artemis/src/artemis/identity/key_provider.py, /Users/artemis-build/artemis/src/artemis/data/__init__.py, /Users/artemis-build/artemis/src/artemis/data/scoped_store.py, /Users/artemis-build/artemis/tests/test_scope_wall.py |
| Modify | /Users/artemis-build/artemis/src/artemis/gateway.py |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict src tests/test_scope_wall.py` | Type gate |
| `uv run ruff check . ; uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q` | Test gate |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | src/artemis/identity/**, src/artemis/data/**, src/artemis/gateway.py, tests/test_scope_wall.py |
| `git commit` | "feat: M2-b scope model (owner/guest) + per-scope provisioning + data-layer crypto wall + real Gateway scope attach" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_ENV_FILE` | Slot Settings for paths/scope dirs |

### Network
| Action | Purpose |
|--------|---------|
| (none) | No engines, no broker, no outbound in M2-b (fakes only) |

## Specialist Context
### Security
M2-b is the data-layer half of the crypto wall (ADR-005/004). Invariants the build MUST honour: a guest scope's `scopes_for` NEVER includes an owner scope; a `ScopedStore` can only bind its own scope's key+path (`CrossScopeError` otherwise); no owner data is served without an unlocked owner session (Gateway returns `LOCKED`); `SecretKey` never renders its bytes. The real key never appears in M2-b (only the `KeyProvider` port + a fake). [HARD FLAG for the apex-security gate (M2-d): review the owner-auth model (unlocked-session ⇒ owner) and the guest-recognition deferral seam — confirm no unauthenticated path reaches owner scope, before M3/M4.]

### Performance
`ScopedStore` opens nothing at construction (lazy); the key is fetched only when a connection is actually opened, so the per-request scope-attach is cheap. The session window (M2-a) means `dek_for_scope` does not re-hit the enclave each call (M2-c caches the mlock'd DEK).

### Accessibility
(none — no frontend; the LOCKED response is surfaced by the eventual app at the client milestone)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | src/artemis/identity/*.py, src/artemis/data/scoped_store.py | Type + docstring all exports; document the wall invariants + the M5 guest-recognition seam |

## Acceptance Criteria
- [ ] Run `uv run mypy --strict src tests/test_scope_wall.py` → verify: exit 0.
- [ ] Run `uv run pytest -q tests/test_scope_wall.py` → verify: scope model, SecretKey hygiene, provisioning isolation, `CrossScopeError`, `ScopeLockedError`, and Gateway LOCKED/owner cases all pass.
- [ ] Run `uv run python -c "from artemis.identity.scope import scopes_for, Identity; print('owner-private' not in scopes_for(Identity('bob','guest')))"` → verify: prints `True` (guest cannot see owner scope).
- [ ] Run `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.

## Progress
_(Coding mode writes here — do not edit manually)_
