---
spec: m2-c-broker-client-tier0-launchd
status: ready
token_profile: balanced
autonomy_level: L2
---

# Spec: M2-c — Brain-side broker IPC client (receive DEK, open SQLCipher via raw-hex-key, mlock, zeroize) + Tier-0 proactive-key provisioning + launchd broker LaunchAgent + owner auto-login config + per-scope volume-mount path contract

**Identity:** Implements the brain's `KeyProvider` over the M2-a broker IPC (request nonce → mock/real proof → receive DEK into mlock'd memory → open SQLCipher via `PRAGMA key="x'…'"` + `cipher_memory_security` → zeroize on idle/lock/restart), provisions the separate Tier-0 device-bound `.userPresence` proactive key, and adds the broker LaunchAgent plist + owner auto-login boot config (ADR-002 addition).
→ why: see docs/technical/adr/ADR-005-owner-key-broker.md (DEK handling: mlock, raw-hex-key, cipher_memory_security, session-only; LaunchAgent + auto-login) · docs/technical/adr/ADR-006-two-tier-proactivity.md (Tier-0 proactive key provisioned at M2).

<!-- Split rule: TWO logical phases (1: the brain-side broker client + SQLCipher keyed-open + mlock/zeroize, which IS the real KeyProvider M2-b declared; 2: the deployment additions — broker LaunchAgent plist + owner auto-login config + Tier-0 key provisioning). Kept as ONE spec because the LaunchAgent + auto-login exist precisely to run the broker the client talks to, and the Tier-0 key is provisioned via the same broker `provision-scope` path; the three are the one "make the broker reachable + keyed at runtime" unit. At the 2-phase limit; flagged per rules. Consumes M2-a (broker server + IPC contract) and M2-b (the KeyProvider PORT + ScopedConnection it now fills with a real keyed open). -->

## Assumptions
- **M2-a** is complete: the broker server speaks the length-prefixed-JSON IPC at `<dataRoot>/<slot>/run/broker.sock`, with `requestNonce`/`getDEK(proof)`/`lock`/`status`, and `provision-scope`/`pair` sub-commands, and the contract is frozen in `docs/technical/protocol/broker-ipc.md`. → impact: Stop (the Python client implements that exact wire format).
- **M2-b** is complete: the `KeyProvider` Protocol (`dek_for_scope` → `SecretKey`, `is_owner_unlocked`), `SecretKey`, `ScopeLockedError`, and `ScopedConnection.pragma_key_statement()` exist; M2-c provides the REAL `KeyProvider` + fills the keyed SQLCipher open. → impact: Stop (signatures must match M2-b exactly).
- **M0-b** is complete: `render_plists.py` + the launchd template pattern + `Settings`/`paths`. M2-c ADDS a broker LaunchAgent template into that mechanism. → impact: Stop (reuse the renderer; don't fork it).
- SQLCipher is reached from Python via **`sqlcipher3`/`pysqlcipher3`** (or APSW + sqlite3mc per ADR-004's note) using the **raw-hex-key path** (`PRAGMA key = "x'<64hex>'"`, no runtime PBKDF2) + `PRAGMA cipher_memory_security = ON`. The exact binding choice is an ADR-004 build-time spike (sqlite-vec-under-SQLCipher) — M2-c proves only the keyed OPEN of a SQLCipher file (no sqlite-vec, no schema; that's M4). → impact: Caution. The keyed-open sits behind a thin swappable `sqlcipher_open(path, key_hex)` wrapper; the concrete Python SQLCipher binding (APSW+sqlite3mc vs sqlcipher3) is decided at the M4 sqlite-vec-under-SQLCipher spike and is NOT chosen in M2-c. The mlock/zeroize/raw-hex logic is binding-independent.
- **mlock**: the received DEK is copied into a page-locked buffer via `mlock(2)` (through `ctypes`/`mmap` + `libc.mlock`) so it never swaps; zeroized + `munlock`'d on idle/lock/restart. → impact: Caution. macOS `mlock` + `cipher_memory_security` on Apple Silicon is an ADR-005 build-time spike → gated on-hardware verification (Task 7).
- In M2 there is no iPhone app; the client obtains proofs from the **M2-a `MockProver`** (test harness) for tests and for the on-hardware bring-up. The real phone proof is the client milestone; the client code path is identical (it sends an `UnlockProof` it received from *some* prover). → impact: Low (the prover is injected; mock vs real is a swap).
- **Owner auto-login** is a macOS boot config (`com.apple.loginwindow autoLoginUser` + the FileVault interaction) enabling the broker LaunchAgent to load after a power cut. It does NOT unlock data (still needs the phone proof). → impact: Stop (without it the LaunchAgent never starts headless; WITH it the wall is intact because data still needs the proof). This is an ADR-005 build-time spike (auto-login + FileVault boot yields a usable owner session) → gated on-hardware (Task 8).
- The Tier-0 proactive key is a SEPARATE small `.userPresence`, device-bound key unwrapped at boot, protecting ONLY the minimised proactive corpus (ADR-006). In M2 it is PROVISIONED (its own wrapped key + its own `proactive` pseudo-scope dir); the minimised-corpus schema + the Heartbeat that uses it are M6. → impact: Caution (M2 provisions the key + reserves the scope; no corpus, no Heartbeat here).
- The per-scope encrypted volume is mounted by the broker (M2-a / ADR-007) at `/opt/artemis/<slot>/<scope>/vault/` on a verified unlock; the brain-side `sqlcipher_open` and (M3) LanceDB open their files UNDER that mounted path. `BrokerKeyProvider.is_owner_unlocked()` (via broker `status`) is the seam M3-a uses to know the volume is mounted/unlocked; M2-c does NOT itself attach the volume (broker's native job). → impact: Caution (mount path + `is_owner_unlocked()` seam are the frozen contract M3-a consumes).

Simplicity check: considered having the brain talk XPC to the broker — rejected to keep the Python client thin (a length-prefixed-JSON Unix socket is trivial from `socket`/`asyncio`); the transport is behind M2-a's contract anyway. Considered provisioning Tier-0 via a wholly separate code path — rejected; it reuses the broker `provision-scope` mechanism with a distinct `proactive` scope + a distinct (boot-unwrapped, no-phone-proof) key policy, which is the minimum delta. Considered skipping mlock for M2 — rejected; ADR-005 makes mlock + zeroize a hard requirement for the DEK-in-brain blast-radius mitigation.

## Prerequisites
- Specs that must be complete first: **M2-a** (broker server + IPC contract + MockProver + provision-scope), **M2-b** (`KeyProvider` port + `SecretKey` + `ScopedConnection`), **M0-b** (`render_plists.py` + launchd pattern), **M0-a** (paths/config). 
- Environment setup required: a Python SQLCipher binding + `outlines`-unrelated; the broker built (M2-a). Off-hardware: the IPC client + mlock/zeroize logic test against a Python FAKE broker server + a temp file; **the real broker round-trip, real SQLCipher keyed open + `cipher_memory_security`, real mlock, and auto-login are GATED on-hardware (Tasks 6–8).**

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| /Users/artemis-build/artemis/src/artemis/identity/broker_client.py | create | `BrokerClient` (Unix-socket IPC) + `BrokerKeyProvider` implementing the M2-b `KeyProvider` port; mlock'd DEK cache + zeroize |
| /Users/artemis-build/artemis/src/artemis/data/sqlcipher.py | create | `sqlcipher_open(path, key_hex)` raw-hex-key + `cipher_memory_security` wrapper; fills `ScopedConnection`'s keyed open |
| /Users/artemis-build/artemis/src/artemis/proactive/tier0_key.py | create | Tier-0 proactive-key provisioning (separate `.userPresence` device-bound key via the broker) |
| /Users/artemis-build/artemis/deploy/launchd/com.artemis.broker.plist.template | create | LaunchAgent: the ArtemisBroker (owner-runtime user session) |
| /Users/artemis-build/artemis/scripts/setup_autologin.sh | create | owner auto-login boot config (ADR-002 addition) — on-hardware gated |
| /Users/artemis-build/artemis/scripts/render_plists.py | modify | include the broker LaunchAgent template in the render set |
| /Users/artemis-build/artemis/tests/test_broker_client.py | create | IPC client + mlock/zeroize + keyed-open wrapper tests against a fake broker server |

## Tasks
- [ ] Task 1: Implement the broker IPC client — files: `/Users/artemis-build/artemis/src/artemis/identity/broker_client.py` — `class BrokerClient` constructed with the socket path (from `paths`: `<slot>/run/broker.sock`). Implements the M2-a length-prefixed-JSON contract: `request_nonce(scope) -> bytes`, `get_dek(scope, proof: dict) -> bytes` (returns the raw 32-byte DEK), `lock(scope)`, `status() -> dict`. Frame = 4-byte big-endian length + UTF-8 JSON; parse `error(code,message)` into a typed `BrokerError`. The proof dict matches M2-a's `UnlockProof` Codable shape; the prover is INJECTED (`Callable[[str, bytes, int], dict]`) so the MockProver (tests/bring-up) or a future phone prover slots in. — done when: `uv run mypy --strict src` passes; against a fake in-process socket server speaking the contract, `request_nonce`→`get_dek` returns 32 bytes (Task 7 test).

- [ ] Task 2: Implement the mlock'd, zeroizing BrokerKeyProvider — files: `/Users/artemis-build/artemis/src/artemis/identity/broker_client.py` (same file) — `class BrokerKeyProvider` implementing the M2-b `KeyProvider` Protocol over a `BrokerClient` + the injected prover. `dek_for_scope(scope) -> SecretKey`: if a non-expired mlock'd DEK is cached for the scope, return it; else `nonce = client.request_nonce(scope)`, `proof = prover(scope, nonce, next_counter)`, `dek = client.get_dek(scope, proof)`, copy `dek` into a `mlock`'d buffer (via a small `secure_buffer` helper: `ctypes` allocate + `libc.mlock`), build a `SecretKey` backed by that buffer, cache it under the session window, and **zeroize the transient `dek` bytes immediately**. `is_owner_unlocked() -> bool`: `client.status()` reports an unlocked owner session. `lock_all()`: zeroize + `munlock` every cached buffer and call `client.lock(scope)` per scope. Register zeroize on process exit (`atexit`) and provide an idle-driven invalidation hook. Raise `ScopeLockedError` (M2-b) when the broker returns locked/no-proof. The DEK is NEVER written to disk or logged. — done when: `uv run mypy --strict src` passes; a test shows the cached `SecretKey` buffer is zeroized after `lock_all()` (the underlying bytes read back as zero) and that `dek_for_scope` on a locked broker raises `ScopeLockedError`.

- [ ] Task 3: Implement the SQLCipher raw-hex keyed-open wrapper — files: `/Users/artemis-build/artemis/src/artemis/data/sqlcipher.py` — `def sqlcipher_open(path: Path, key_hex: str) -> Connection`: open the SQLCipher DB and immediately execute `PRAGMA key = "x'<key_hex>'"` (raw-hex, no PBKDF2) then `PRAGMA cipher_memory_security = ON`, then a `PRAGMA cipher_version`/`SELECT count(*) FROM sqlite_master` smoke to confirm the key is correct (a wrong key raises `NotADatabaseError`-equivalent). Behind a thin binding seam so `sqlcipher3` vs APSW+sqlite3mc is swappable (binding decided at the M4 sqlite-vec spike — see Assumptions). Wire it into M2-b's `ScopedConnection`: add a method `ScopedConnection.open(key: SecretKey) -> Connection` that calls `sqlcipher_open(self.path, key.as_hex())` — i.e. M2-b's handle now actually opens, keyed, only for its own scope (the wall, enforced). The `key.as_hex()` string is used transiently and not retained. — done when: `uv run mypy --strict src` passes; an off-hardware test using a STANDARD sqlite file (no SQLCipher) is SKIPPED with a note, and the real keyed open is the gated Task 6 (since SQLCipher isn't guaranteed in CI). [If a `sqlcipher3` wheel is installable off-hardware, run the keyed round-trip in CI instead of skipping — prefer that.]

- [ ] Task 4: Provision the Tier-0 proactive key — files: `/Users/artemis-build/artemis/src/artemis/proactive/tier0_key.py` (create `src/artemis/proactive/__init__.py` too) — `def provision_tier0_key(settings, broker_provision: Callable[[str], None]) -> None`: provision a SEPARATE small device-bound `.userPresence` key + wrapped key for the reserved pseudo-scope `"proactive"` via the broker `provision-scope --scope proactive` path, and ensure the `<slot>/proactive/{keys,corpus}/` dirs exist (corpus stays EMPTY in M2 — the minimised corpus + Heartbeat are M6). Document: this key is unwrapped at boot (no phone proof — it protects only the minimised, mostly-derived corpus per ADR-006) — contrast with the per-scope owner DEKs which REQUIRE a phone proof. M2 only provisions; nothing reads/writes the corpus yet. — done when: `uv run mypy --strict src` passes; with a fake `broker_provision` the function records a `proactive` provision call and creates the `proactive/` dirs (Task 7 test). The Tier-0 `proactive` key uses a distinct broker key policy `proof_required=false` (boot-unwrappable, no phone proof) — defined as an explicit policy in M2-a's key store (M2-a Task 2/7 edits); M2-c PROVISIONS the `proactive` scope via the broker `provision-scope --scope proactive --no-proof` path and reserves the empty corpus dirs. Boot-unwrap CONSUMPTION lands at M6. The `proactive` key protects ONLY the minimised, mostly-derived corpus (ADR-006); it must never gate any owner-private/general data.

- [ ] Task 5: Add the broker LaunchAgent template + render integration + auto-login script — files: `/Users/artemis-build/artemis/deploy/launchd/com.artemis.broker.plist.template`, `/Users/artemis-build/artemis/scripts/render_plists.py` (modify), `/Users/artemis-build/artemis/scripts/setup_autologin.sh` —
  - broker plist template: `Label` `com.artemis.{SLOT}.broker`; **LaunchAgent** (installed to the runtime user's `~/Library/LaunchAgents`, runs in the owner login session — REQUIRED for SE access per ADR-005, mirrors the M0-b audio agent); `ProgramArguments` = `{BROKER_BIN} serve` (`{BROKER_BIN}` = the built `swift/ArtemisBroker/.build/release/artemis-broker`, env-overridable); `EnvironmentVariables` `ARTEMIS_DATA_ROOT={DATA_ROOT}`, `ARTEMIS_SLOT={SLOT}`; `RunAtLoad` true; `KeepAlive{Crashed:true}`; logs `{LOGS_DIR}/broker.*`. Header comment: produced by M2-a; loads only in a user session; needs owner auto-login at boot.
  - render_plists.py: ADD the broker template to the rendered set + resolve `{BROKER_BIN}` (env `ARTEMIS_BROKER_BIN` with the documented default release path). Keep all existing M0-b behaviour.
  - setup_autologin.sh: bash `set -euo pipefail`, requires root; sets the owner-runtime user as the macOS auto-login user (`defaults write /Library/Preferences/com.apple.loginwindow autoLoginUser <RUNTIME_USER>` + the `/etc/kcpassword` step) and prints a WARNING that auto-login + FileVault interact (FileVault may require the unlock at boot before auto-login proceeds) — documented as the gated on-hardware spike. The script is authored deterministically; it only takes effect on the Mini. — done when: `render_plists.py --slot dev` now emits 5 plists (the 4 from M0-b + the broker) all passing `plutil -lint`; `bash -n scripts/setup_autologin.sh` passes off-hardware.

- [ ] Task 6 (GATED — on-hardware): Real SQLCipher keyed open + `cipher_memory_security` — files: (uses Task 3) — on the Mini with the SQLCipher binding installed: create a SQLCipher DB with a known DEK, `sqlcipher_open` it with the correct hex key (succeeds), with a WRONG key (fails), and confirm `PRAGMA cipher_memory_security` reports ON. ADR-005 build-time spike (cipher_memory_security on Apple Silicon). — done when: correct-key opens, wrong-key fails, memory-security ON — recorded in handoff.

- [ ] Task 7: Write the IPC client + mlock/zeroize + tier0 tests — files: `/Users/artemis-build/artemis/tests/test_broker_client.py` — typed pytest with a FAKE broker server (a Python `asyncio`/thread Unix-socket server speaking the M2-a contract, returning a fixed 32-byte DEK after a valid MockProver-shaped proof + enforcing nonce-single-use + counter-increase to mirror the real broker): 
  - `BrokerClient.request_nonce`→`get_dek` returns 32 bytes; a replayed nonce → `BrokerError`.
  - `BrokerKeyProvider.dek_for_scope` returns a `SecretKey`; after `lock_all()` the backing buffer reads back all-zero (zeroize proof) and a subsequent locked-broker `status` makes `is_owner_unlocked()` false / `dek_for_scope` raise `ScopeLockedError`.
  - `provision_tier0_key` with a fake `broker_provision` records a `proactive` provision + creates `proactive/` dirs.
  - the `mlock` helper is invoked (assert via a spy that `libc.mlock` was called; tolerate `mlock` EPERM by falling back + flagging — the real lock is Task 8).
  — done when: `uv run pytest -q` passes AND `uv run mypy --strict src tests/test_broker_client.py` passes.

- [ ] Task 8 (GATED — on-hardware): Real mlock + auto-login + broker LaunchAgent boot — files: (uses Tasks 2/5) — on the Mini: (a) confirm `libc.mlock` on the DEK buffer succeeds (no EPERM) and the page is resident; (b) run `setup_autologin.sh`, reboot, and confirm the owner session comes up and the broker LaunchAgent loads (`launchctl print gui/$(id -u)/com.artemis.dev.broker`) AND that data is still LOCKED until a phone (Mock for bring-up) proof unlocks it AND that the per-scope encrypted volume at /opt/artemis/<slot>/<scope>/vault/ is NOT mounted until the proof verifies, and unmounts on lock/idle (ADR-007 mount-lifecycle spike, cross-ref M2-a Task 9); (c) confirm a full brain→broker→DEK→SQLCipher-open works end-to-end with the broker as a LaunchAgent. ADR-005 build-time spikes (mlock; auto-login+FileVault boot; macOS-26 daemon-restriction re-check). — done when: all three verified on the Mini and recorded in handoff.

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | /Users/artemis-build/artemis/src/artemis/identity/broker_client.py, /Users/artemis-build/artemis/src/artemis/data/sqlcipher.py, /Users/artemis-build/artemis/src/artemis/proactive/__init__.py, /Users/artemis-build/artemis/src/artemis/proactive/tier0_key.py, /Users/artemis-build/artemis/deploy/launchd/com.artemis.broker.plist.template, /Users/artemis-build/artemis/scripts/setup_autologin.sh, /Users/artemis-build/artemis/tests/test_broker_client.py |
| Modify | /Users/artemis-build/artemis/scripts/render_plists.py |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv add <sqlcipher binding>` — binding chosen at the M4 sqlite-vec spike (APSW+sqlite3mc vs sqlcipher3); M2-c installs whichever the M4 spike selects, behind the `sqlcipher_open` wrapper | SQLCipher Python binding |
| `uv run mypy --strict src tests/test_broker_client.py` | Type gate |
| `uv run ruff check . ; uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q` | Test gate (fake broker server) |
| `uv run python scripts/render_plists.py --slot dev` | Render plists (now 5 incl. broker) |
| `plutil -lint <rendered broker>.plist` | Validate the broker plist |
| `bash -n scripts/setup_autologin.sh` | Syntax-check the auto-login script |
| `ARTEMIS_SE_AVAILABLE=1 swift run artemis-broker serve` (GATED, on-Mini) | Run the real broker for the on-hardware round-trip |
| `sudo bash scripts/setup_autologin.sh` (GATED, on-Mini) | Configure owner auto-login |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | src/artemis/identity/broker_client.py, src/artemis/data/sqlcipher.py, src/artemis/proactive/**, deploy/launchd/com.artemis.broker.plist.template, scripts/setup_autologin.sh, scripts/render_plists.py, tests/test_broker_client.py, pyproject.toml, uv.lock |
| `git commit` | "feat: M2-c brain broker IPC client (mlock DEK, raw-hex SQLCipher open) + Tier-0 proactive key + broker LaunchAgent + auto-login" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_DATA_ROOT` | Locate the broker socket + per-scope keys/dirs |
| `ARTEMIS_SLOT` | Which slot's broker/socket |
| `ARTEMIS_BROKER_BIN` | Path to the built `artemis-broker` binary (plist render) |
| `ARTEMIS_RUNTIME_USER` | Owner-runtime user for the LaunchAgent + auto-login |

### Network
| Action | Purpose |
|--------|---------|
| `uv add <sqlcipher binding>` (binding per M4 spike) | Package install (PyPI) |
| (no outbound at runtime) | Broker IPC is a local Unix socket; no network |

## Specialist Context
### Security
M2-c is the brain-side blast-radius mitigation for ADR-005's core risk (prompt-injected DEK exfiltration). Invariants the build MUST honour: the DEK lives only in an `mlock`'d buffer, never on disk, never in a log; it is zeroized on idle/explicit-lock/process-exit; the SQLCipher open uses raw-hex-key (no PBKDF2) + `cipher_memory_security`; the broker LaunchAgent runs as the owner-runtime user (never the build user); owner auto-login does NOT unlock data (the phone proof gate remains). The Tier-0 key is deliberately weaker (boot-unwrap, no proof) and therefore protects ONLY the minimised corpus — keep its scope reservation empty in M2. [HARD FLAG for the apex-security gate (M2-d): the mlock/zeroize completeness, the no-DEK-to-log guarantee, and the Tier-0-key scope-creep risk (ADR-006) are gate subjects before M3/M4.]

### Performance
The mlock'd DEK cache + the broker session window mean steady-state owner reads do NOT re-request a proof or re-hit the enclave; only idle-expiry/lock forces a fresh proof. Keep the IPC client connection short-lived per call (no long-held socket).

### Accessibility
(none — headless; the LOCKED/unlock UX is the client milestone)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | src/artemis/identity/broker_client.py, src/artemis/data/sqlcipher.py, src/artemis/proactive/tier0_key.py | Type + docstring all exports; document mlock/zeroize lifecycle + the raw-hex-key contract + Tier-0 vs per-scope key policy |
| Header comments | deploy/launchd/com.artemis.broker.plist.template | Note LaunchAgent-not-Daemon requirement + auto-login dependency |
| ADR addition | docs/technical/adr/ADR-002-deployment-method.md | (optional, at planning) note the broker LaunchAgent + owner auto-login addition cross-referenced from ADR-005 — do NOT edit code; a planning-mode doc touch only |

## Acceptance Criteria
- [ ] Run `uv run mypy --strict src tests/test_broker_client.py` → verify: exit 0.
- [ ] Run `uv run pytest -q tests/test_broker_client.py` → verify: IPC nonce→DEK round-trip (fake server), replayed-nonce error, `SecretKey` zeroized after `lock_all`, `ScopeLockedError` on locked broker, `provision_tier0_key` creates `proactive/` + records the provision.
- [ ] Run `uv run python scripts/render_plists.py --slot dev --out-dir /tmp/plists` → verify: 5 plists incl. `com.artemis.dev.broker.plist`; `plutil -lint /tmp/plists/*.plist` all `OK`; no `{` placeholders remain.
- [ ] Run `bash -n scripts/setup_autologin.sh` → verify: exit 0 (syntax OK).
- [ ] Run `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.
- [ ] (GATED, on Mini) Real SQLCipher keyed open: correct key opens, wrong key fails, `cipher_memory_security` ON → verify recorded in handoff.
- [ ] (GATED, on Mini) `mlock` succeeds; owner auto-login + broker LaunchAgent load after reboot; data still LOCKED until a proof; full brain→broker→DEK→SQLCipher round-trip works → verify recorded in handoff.

## Progress
_(Coding mode writes here — do not edit manually)_
