---
spec: client-auth-windows-bringup
status: ready
risk: high
coder: codex
coder_effort: high
cross_model_review: true
autonomy_level: L5
---

# Spec: Reconcile client↔brain session-proof contract + Windows unlock path

**Identity:** Align the brain session-proof framing to the client's length-prefixed canonical, define the Windows unlock short-circuit, and freeze the device-auth seam so the live Tauri client connects-in and reads owner domains on the Windows host (finishes gated CLIENT-auth Task 7).
→ why: see docs/technical/adr/ADR-033-windows-host-v1.md, docs/technical/adr/ADR-025-tauri-client-auth-wall-reroot.md

## Assumptions
- The 401 at `session/complete` is solely the proof-framing divergence (brain raw-concat vs client length-prefixed); pairing already passes with identical length-prefixed framing on both sides → impact: Stop.
- The unlock-proof verifier on Mac is the out-of-repo Secure-Enclave broker; this repo's `/app/unlock/*` only relays (`BrokerKeyProvider.complete_unlock` → `self._client.get_dek`), so NO Python unlock-proof message is reconstructed in this repo and the canonical `b"unlock"` framing is a reserved contract the broker must honour when built → impact: Caution.
- On Windows `app.state.key_provider` is `WindowsKeyProvider` (main.py win32 branch), the owner vault is unsealed at startup via Hello, and `is_owner_unlocked()` already gates domain reads via `require_unlocked` → impact: Stop.
- `auth.rs` needs NO change: with the brain short-circuiting `/unlock/*` to success, the client's existing pair→connect→unlock flow works unmodified → impact: Caution (if false, add the apex-tauri client branch + cargo verify in Permissions).
- Real owner-DEK/OAuth-backed domain readers stay deferred (`DefaultDomainReadSource` typed fakes); the #5 verify confirms the gate+route path post-unlock on Windows custody, not real data → impact: Low.
- The dispatched review surfaced one adjacent security-completion fold: `/app/unlock/complete` lacks the `Depends(rate_limited)` its four sibling auth routes carry. This is a 1-line addition on the exact route this spec hardens (not a new feature), folded into Task 2 → impact: Caution.

Simplicity check: Considered splitting into two specs (proof-fix vs Windows-unlock). Rejected: this is ONE atomic contract reconciliation — splitting lands a red intermediate state (brain framing changed while the existing brain tests still encode the old framing) and the frozen seam (contracts.md Seam 11) must describe both halves at once. Kept as one Deep Details spec with an ordered wave plan.

## Prerequisites
- none (CLIENT-auth Tasks 1–6 complete; pairing verified live to `pair 200 → session/begin 200`).
- Environment: host has run `uv sync --group agentic` before verify (else mypy reds on `openhands.sdk`). Windows host (win32) required to exercise the Task 5 DPAPI custody path.
- **Build SERIALLY with `voice-ask-wiring` — not in the same parallel wave.** Both specs modify `src/artemis/api_app.py` and `tests/test_api_app.py` (disjoint regions, but two parallel Codex processes on one file is unsafe). Either spec may go first; the second rebases.

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| C:\Users\User\artemis\src\artemis\identity\app_auth.py | modify | Length-prefix the session-proof message; rename `API_SESSION_CONTEXT` to `b"session"`; update the module docstring to the canonical framing. |
| C:\Users\User\artemis\src\artemis\identity\windows_key_provider.py | modify | Add `begin_unlock` / `complete_unlock` / `lock_all` already-unlocked short-circuits so `WindowsKeyProvider` satisfies the `UnlockProvider` protocol. Methods MUST NOT mutate `is_owner_unlocked()`. |
| C:\Users\User\artemis\src\artemis\api_app.py | modify | Add the missing `Depends(rate_limited)` to the `/app/unlock/complete` route (its four sibling auth routes all carry it; it is the sole omission — line ~670). Security-completion fold from the dispatched review. |
| C:\Users\User\artemis\tests\test_app_auth.py | modify | Update `_sign` helper to the canonical length-prefixed framing + `b"session"` context (it currently encodes the OLD raw format — it was the mock that hid the divergence). |
| C:\Users\User\artemis\tests\test_api_app.py | modify | Update `Phone.sign_session` to the canonical framing + `b"session"` context (same old-format mock). |
| C:\Users\User\artemis\tests\test_auth_contract_conformance.py | create | Real-signer (client byte-layout reproduced) ↔ real-verifier (`AppAuth.complete_session`) conformance test for connect; documents the reserved `b"unlock"` framing. No mock of either side. |
| C:\Users\User\artemis\tests\test_windows_unlock_shortcircuit.py | create | Unit-asserts the Windows unlock short-circuit + verifies a post-unlock domain GET returns 200 on the real `WindowsKeyProvider` custody path. |
| C:\Users\User\artemis\docs\technical\contracts.md | modify | Add **Seam 11 — Client↔brain device-auth & session-proof contract** (the seam the handoff calls "specified nowhere"). |
| C:\Users\User\artemis\docs\technical\adr\ADR-033-windows-host-v1.md | modify | Add a `## Refinement` entry recording the Windows-unlock-short-circuit decision. |

## Tasks
- [ ] Task 1: Conform the brain session-proof to the client's length-prefixed canonical — files: C:\Users\User\artemis\src\artemis\identity\app_auth.py — done when: `complete_session` builds `message = len(nonce).to_bytes(2,"big") + nonce + len(ctx).to_bytes(2,"big") + ctx + counter.to_bytes(8,"big")` with `ctx = API_SESSION_CONTEXT`; `API_SESSION_CONTEXT` is `b"session"`; the module docstring (top of file) documents the new framing; `uv run mypy` clean on the file.
- [ ] Task 2: Add the Windows unlock short-circuit + close the unlock-route rate-limit gap — files: C:\Users\User\artemis\src\artemis\identity\windows_key_provider.py, C:\Users\User\artemis\src\artemis\api_app.py — done when: (a) `WindowsKeyProvider` exposes `begin_unlock(scope) -> bytes` (returns `secrets.token_bytes(32)`), `complete_unlock(scope, nonce, proof) -> None` (no-op success — startup-Hello owns vault state; fail-closed stays at `require_unlocked`/`is_owner_unlocked`), and `lock_all() -> None` (delegates to `self.lock()`); the class structurally satisfies `api_app.UnlockProvider`. (b) **`complete_unlock` MUST NOT set `is_owner_unlocked()` to True** — it returns `None` and leaves vault-state unchanged; `is_owner_unlocked()` reflects ONLY the startup-Hello path (security-review invariant: a garbage proof on a sealed-at-startup vault must not grant access). (c) The three new methods' docstrings name the short-circuit + the fail-closed location AND state that the `nonce`/`proof` bytes must never be logged at any level. (d) `/app/unlock/complete` in `api_app.py` gains `dependencies=[Depends(rate_limited)]` to match its four sibling auth routes (`/pair`, `/session/begin`, `/session/complete`, `/unlock/begin`).
- [ ] Task 3: Update the existing brain auth tests to the canonical framing — files: C:\Users\User\artemis\tests\test_app_auth.py, C:\Users\User\artemis\tests\test_api_app.py — done when: `_sign` and `Phone.sign_session` produce the length-prefixed `b"session"` message; `uv run pytest -q tests/test_app_auth.py tests/test_api_app.py` green.
- [ ] Task 4: Add the real-signer↔real-verifier conformance test (incl. replay invariants) — files: C:\Users\User\artemis\tests\test_auth_contract_conformance.py — done when: the test builds the connect message byte-for-byte as the Rust client does (u16-BE length prefixes, `b"session"`, 8-byte BE counter), signs via `private_key.sign(message, ECDSA(SHA256()))` with a fresh P-256 key registered in a real `DeviceRegistry`, and `AppAuth.complete_session` accepts it; AND the test pins the replay invariants the framing refactor must not break (both reviewers, convergent): (a) a deliberately raw-concat-framed signature is REJECTED; (b) **a replayed already-consumed nonce is REJECTED** (call `complete_session` twice with the same nonce → second raises `AuthError`); (c) **an equal-or-lower counter is REJECTED** (after a successful `complete_session` at counter N, a correctly-framed proof at counter ≤ N raises `AuthError`); (d) an inline golden vector documents the reserved `b"unlock"` framing. No `app_auth` import of the framing helper into the test (reproduce the layout independently). Add a one-line comment that the ephemeral test private key's `__repr__` is safe (cryptography lib redacts key bytes).
- [ ] Task 5: Verify post-unlock domain reads on the Windows custody path (+ the fail-closed negative case) — files: C:\Users\User\artemis\tests\test_windows_unlock_shortcircuit.py — done when: (a) a unit test asserts `begin_unlock` returns 32 bytes, `complete_unlock` is a no-op, `lock_all()` flips `is_owner_unlocked()` to False; (b) a FastAPI route test wires a real `WindowsKeyProvider` (tmp APPDATA-rooted, provisioned, `_unseal_all()`'d — mirror tests/test_windows_hello_unlock.py setup) as `app.state.key_provider`, completes a session, and `GET /app/calendar` returns 200 (passing the `require_unlocked` gate); the test docstring states real owner-DEK readers remain deferred (`DefaultDomainReadSource` fake); (c) **the fail-closed negative case (both reviewers, convergent): a SEALED vault (provisioned but NOT `_unseal_all()`'d) + `begin_unlock` + `complete_unlock` called with arbitrary garbage proof bytes → assert `is_owner_unlocked()` stays False AND `GET /app/calendar` returns 423** — proving the no-op 200 from `complete_unlock` never bypasses the gate.
- [ ] Task 6: Freeze the device-auth seam in contracts.md — files: C:\Users\User\artemis\docs\technical\contracts.md — done when: a new "Seam 11" section defines the pairing, connect (`b"session"`), and unlock (`b"unlock"`) proof byte layouts, the hash (SHA256), signature encoding (DER ECDSA-P256), nonce single-use + strictly-increasing per-device counter rules, and names the producer (`app_auth` / `api_app` + client `auth.rs`). It ALSO records (from the dispatched review): (a) **context domain-separation** — the device P-256 key signs exactly three distinct, length-prefixed structures (pairing = `len|code + device_id`, connect = `len|nonce + len|"session" + counter`, unlock = `len|nonce + len|"unlock" + counter`); `b"session"` is the sole user of that context string (codebase-grep confirmed), so the shortening from `b"artemis-api-session"` carries no cross-protocol signature-reuse risk; (b) **constant-time posture** — ECDSA verify is constant-time (cryptography lib); the counter int-compare and nonce dict-lookup are over non-secret values and need not be (documented so no future contributor assumes otherwise); (c) **rate-limit posture** — all five device-auth routes (`/pair`, `/session/begin`, `/session/complete`, `/unlock/begin`, `/unlock/complete`) carry `Depends(rate_limited)` (5 attempts / 15 min per peer IP) after Task 2's fix; the host binds loopback for a single owner, so this is defense-in-depth; (d) **Windows `/app/unlock/complete` semantics** — returns 200 (no-op) on win32 regardless of vault state; the client discovers a still-locked vault via 423 on the next domain call, NOT via the unlock endpoint.
- [ ] Task 7: Record the Windows-unlock-short-circuit decision — files: C:\Users\User\artemis\docs\technical\adr\ADR-033-windows-host-v1.md — done when: a new `## Refinement <date> — Windows unlock short-circuit` section explains that Windows has no `begin/complete_unlock` broker relay, the vault unseals at startup via Hello, and the `/app/unlock/*` endpoints short-circuit to success with fail-closed enforcement retained at `require_unlocked`.

## Wave plan
Wave 1: [Task 1, Task 2] | Wave 2: [Task 3, Task 4, Task 5] | Wave 3: [Task 6, Task 7]

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | C:\Users\User\artemis\tests\test_auth_contract_conformance.py, C:\Users\User\artemis\tests\test_windows_unlock_shortcircuit.py |
| Modify | C:\Users\User\artemis\src\artemis\identity\app_auth.py, C:\Users\User\artemis\src\artemis\identity\windows_key_provider.py, C:\Users\User\artemis\src\artemis\api_app.py, C:\Users\User\artemis\tests\test_app_auth.py, C:\Users\User\artemis\tests\test_api_app.py, C:\Users\User\artemis\docs\technical\contracts.md, C:\Users\User\artemis\docs\technical\adr\ADR-033-windows-host-v1.md |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv sync --group agentic` | Sync agentic deps before verify (else mypy reds on openhands.sdk). |
| `uv run mypy` | Full-project strict type check (host re-verify; not file-scoped). |
| `uv run pytest -q` | Full test suite (connect conformance, Windows short-circuit, existing auth tests). |

Client (`auth.rs`) is NOT touched — no `cargo check` / `cargo test` / `cargo clippy` is required. Only if the build discovers a client branch is genuinely needed (Assumption 4 false) does the apex-tauri Verification Recipe (`cargo check`, `cargo test`, `cargo clippy -- -D warnings` in `client/src-tauri`) apply.

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | The nine files listed under File Operations, by name. |
| `git commit` | "fix(client-auth): conform brain session-proof framing + Windows unlock short-circuit" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `APPDATA` / `LOCALAPPDATA` | Task 5 sets a tmp value to satisfy `WindowsKeyProvider`'s owner-profile key-store guard. |

### Network
| Action | Purpose |
|--------|---------|
| (none) | No package installs beyond `uv sync`. |

## Specialist Context
### Security
- Canonical framing is length-prefixed (u16-BE) for every field, preventing concatenation ambiguity between `nonce`/`ctx`/`counter` (the pairing path already did this; the session path was the outlier). Context domain-separation is preserved: connect = `b"session"`, unlock = `b"unlock"` — never reuse one context's signature for the other authority.
- **Variant analysis (security review):** a codebase grep for `.sign(` / `.verify(` in `src/artemis/` confirmed the session path (`app_auth.py:285`) was the SOLE raw-concat signing outlier; pairing (`api_app.py:975`) was already length-prefixed; `broker_client.py:161` is IPC frame-length, not a signed message. No other message-construction path needs the fix.
- **Context narrowing accepted eyes-open (auth review):** `b"artemis-api-session"`→`b"session"` is forced by the owner-locked "client unchanged" decision (the Rust client signs `b"session"`). The device key signs only three mutually-distinct length-prefixed structures, so `b"session"` is the unique user of that context — documented in Seam 11 (no cross-protocol reuse). Switching it would reopen the locked decision (touch `auth.rs`).
- Nonce single-use (`ChallengeStore.consume`) and strictly-increasing per-device counter (`complete_session`: `counter <= device.counter` → reject) are unchanged and pinned by the Task 4 conformance test (the framing refactor touches the function that hosts them) and recorded in Seam 11.
- Windows `complete_unlock` performs NO signature verification (no second authority on Windows) and MUST NOT mutate `is_owner_unlocked()`; fail-closed stays at `require_unlocked` → 423 when `is_owner_unlocked()` is False, pinned by the Task 5 sealed-vault negative case. This is the explicit ADR-033 refinement, not an oversight.
- **Rate limiting:** all five device-auth routes carry `Depends(rate_limited)` after Task 2's fold (`/unlock/complete` was the sole omission); `RateLimiter` = 5 attempts / 900 s per peer IP. Loopback single-owner host → defense-in-depth.
- **Supply chain:** no new dependencies. `pip-audit` runs in CI on the PR; not a required local step for this spec.

### Performance
(none)

### Accessibility
(none — no frontend change)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Contract | C:\Users\User\artemis\docs\technical\contracts.md | Add Seam 11 (device-auth & session-proof) — the frozen byte-level contract for pairing/connect/unlock. |
| ADR | C:\Users\User\artemis\docs\technical\adr\ADR-033-windows-host-v1.md | Add `## Refinement` — Windows unlock short-circuit decision + fail-closed location. |
| Architecture | C:\Users\User\artemis\docs\technical\architecture\overview.md | No touch — overview describes the client↔brain auth seam conceptually (the two-authority handshake, §"Client ↔ brain auth") and routes byte-level detail to ADR-010/025 + contracts.md; ADR-033's row already records the Windows TPM/Hello unlock substitution. The new byte format's home is contracts.md Seam 11. |
| Inline | (changed src files) | Update `app_auth.py` module docstring (Task 1); add concise docstrings to the three new `WindowsKeyProvider` methods naming the short-circuit + fail-closed location. |

## Acceptance Criteria
- [ ] Apply Task 1 → verify: `python -c "from artemis.identity.app_auth import API_SESSION_CONTEXT; print(API_SESSION_CONTEXT)"` prints `b'session'`; the `complete_session` message construction matches `len(nonce).to_bytes(2,'big')+nonce+len(ctx).to_bytes(2,'big')+ctx+counter.to_bytes(8,'big')`.
- [ ] Apply Task 2 → verify: `python -c "from artemis.api_app import UnlockProvider; from artemis.identity.windows_key_provider import WindowsKeyProvider; print(issubclass(WindowsKeyProvider, UnlockProvider) or hasattr(WindowsKeyProvider,'begin_unlock') and hasattr(WindowsKeyProvider,'complete_unlock') and hasattr(WindowsKeyProvider,'lock_all'))"` is True.
- [ ] Run Task 4 conformance test → verify: `uv run pytest -q tests/test_auth_contract_conformance.py` passes — a client-framed signature is accepted by `AppAuth.complete_session`; a raw-concat-framed one is rejected; a replayed consumed nonce is rejected; an equal-or-lower counter is rejected.
- [ ] Run Task 5 verify → verify: `uv run pytest -q tests/test_windows_unlock_shortcircuit.py` passes — `GET /app/calendar` returns 200 with a real unlocked `WindowsKeyProvider`; `lock_all()` then makes `is_owner_unlocked()` False; AND a sealed vault + garbage-proof `complete_unlock` leaves `is_owner_unlocked()` False and `GET /app/calendar` returns 423.
- [ ] Apply Task 2 rate-limit fold → verify: `grep -n "unlock/complete" -A2 docs/../src/artemis/api_app.py` shows `Depends(rate_limited)` on the route (or a route test asserts the 6th rapid `/app/unlock/complete` call returns 429).
- [ ] Host re-verify → verify: `uv run mypy` clean (full project) and `uv run pytest -q` green (full suite — confirms the updated existing tests Task 3 no longer encode the old framing).
- [ ] contracts.md Seam 11 present → verify: `grep -n "Seam 11" docs/technical/contracts.md` returns a heading defining connect=`b"session"` and unlock=`b"unlock"` byte layouts.
- [ ] ADR-033 refinement present → verify: `grep -n "unlock short-circuit" docs/technical/adr/ADR-033-windows-host-v1.md` returns the new section.

## Progress
_(Coding mode writes here — do not edit manually)_

### 2026-06-28 — build RECOVERED after coding window closed mid-session
The original coding window applied all 7 tasks to disk but closed before verify/commit (Progress section was never written; nothing committed). Recovery session re-verified the on-disk state.

- [x] Task 1 — `app_auth.py`: `API_SESSION_CONTEXT = b"session"`; `complete_session` builds the length-prefixed message `len(nonce)|nonce|len(ctx)|ctx|counter(8B-BE)` (app_auth.py:286–293). Counter/nonce checks preserved (nonce consume L277, counter `<= reject` L279).
- [x] Task 2 — `windows_key_provider.py`: `begin_unlock` (32-byte nonce), `complete_unlock` (no-op, never mutates `is_owner_unlocked`), `lock_all` (delegates to `lock()`); docstrings name the short-circuit + no-log rule. `api_app.py`: `Depends(rate_limited)` added to `/app/unlock/complete`.
- [x] Task 3 — `test_app_auth.py` / `test_api_app.py` mocks updated to canonical framing.
- [x] Task 4 — `test_auth_contract_conformance.py` created (112 lines).
- [x] Task 5 — `test_windows_unlock_shortcircuit.py` created (186 lines).
- [x] Task 6 — contracts.md Seam 11 present.
- [x] Task 7 — ADR-033 `## Refinement` (unlock short-circuit) present.

**Host re-verify (full, not file-scoped):** `uv sync --group agentic` ✅ · `uv run mypy` ✅ clean (342 files) · `uv run pytest -q` ✅ **932 passed, 6 skipped** (751s).

**Cross-model review:** dispatched (`cross_model_review: true`, high-risk auth) — see commit decision.

**Out-of-scope working-tree changes (NOT this spec):** `client/src-tauri/Cargo.toml` (pre-existing dirty edit, untouched all session), `docs/status.md` (status maintenance), and deletions of `docs/progress/{client-live-overlay,m2-win-a}.md` (progress-record cleanup). Commit staged BY NAME — only the 9 spec files.
