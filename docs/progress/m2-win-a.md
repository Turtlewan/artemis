# m2-win-a — build progress / decisions

Spec: docs/changes/m2-win-a-encryption-at-rest.md · risk: high · coder: codex · cross_model_review: true

## Outcome
All 3 tasks built (Codex, host-verified). Baseline green: full `uv run mypy` clean (327 files),
`uv run pytest -q` → 876 passed / 5 skipped, ruff clean. pip-audit: sqlcipher3-wheels has 0 advisories.

## Decisions / deviations (for planning to ratify)

1. **Dependency substitution (owner-approved)** — spec named `sqlcipher3-binary`; it ships NO cp312-win
   wheel (caps at cp311), so `uv add` failed (pre-flight Stop assumption 4 wrong). Verified + substituted
   **`sqlcipher3-wheels==0.5.7`** (cp312/cp313-win wheel, bundles SQLCipher 4.12.0 community, exposes the
   same `import sqlcipher3`). Drop-in: round-trip encrypts, wrong-key rejected, no plaintext/header in raw
   file. Owner approved. Same upstream project (github.com/laggykiller/sqlcipher3, zlib). Single-maintainer
   repackaging — supply-chain note; pip-audit clean.

2. **Scope expansion (owner-approved): row-factory regression.** Real SQLCipher connections reject
   `conn.row_factory = sqlite3.Row` (the dev shim returned a genuine sqlite3 conn, so it worked). 71 of 74
   failing tests were this. Fix: new **connection-aware `set_row_factory(conn)` seam** in sqlcipher.py
   (picks sqlcipher3.Row vs sqlite3.Row by `type(conn).__module__`), applied at 7 owner-private store sites
   (gateway, agentic/checkpoint, agentic/inbox, gmail/cache, gmail/extract_store, productivity/repository,
   finance/repository). Connection-aware so it also serves finance's plain-sqlite3 dev fallback. 8 production
   files beyond the spec's Files-to-Change.

3. **Scope expansion: test-inspection fixes.** 3 tests opened owner-private DBs with plain `sqlite3.connect`
   for raw inspection → now fail ("file is not a database") because the file is genuinely encrypted. Switched
   to `sqlcipher_open(db_path, key_hex)` with the test's known FakeKeyProvider key: test_agent_checkpoint,
   test_reactions_compose, test_reactions_dispatcher.

## Flags for planning (review-needed)

- **⚠ Finance unencrypted dev fallback** — `src/artemis/modules/finance/store.py:48` falls back to plain
  `sqlite3.connect` ("no encryption — CI/dev only") when no key. With real SQLCipher now live, this means
  finance data can persist UNENCRYPTED on the dev box when the key provider is locked. Security-relevant;
  planning should decide whether to keep the fallback or fail-closed.
- **AC #6 not unit-testable** — "a .dek sealed by one Windows account cannot be unsealed by another" needs a
  second Windows account; covered by the dwFlags=0 user-scope impl + entropy-mismatch proxy test. Manual
  verification step only.

## Cross-model review (both directions; risk: high)
- **Opus apex-reviewer: no BLOCK** — all 7 security priorities verified clean (no key leakage, user-scope
  DPAPI, zeroization, atomic provision, entropy isolation, connection-aware row factory, fail-closed dir guard).
- **Codex (read-only): BLOCK** (advisory). Substantive findings overlapped with Opus.

**Folded (all in-scope SMALL forks, re-verified green):**
1. `sqlcipher_open` now forces a `SELECT count(*) FROM sqlite_master` read after keying → wrong-key/corruption
   fails closed through the sanitized `SqlCipherError` path (meets the spec's own done-when "different-key
   reopen raises SqlCipherError"; also fixes the previously-dead `cipher_version` branch). [Codex B1, Opus L3/L4]
2. Wrong-key test now asserts neither key appears in the exception text/`__cause__`/`__context__` chain
   (criterion 1). [Codex F3 + Opus M1 — both raised]
3. `dpapi_seal` zeroes the plaintext (DEK) ctypes buffer in a `finally`; `provision()` holds the DEK in a
   wipeable `bytearray` and wipes it after sealing. [Codex B2 + Opus L5 — both raised; full zeroization is a
   Python limit, same-user-memory attacks remain deferred to m2-win-b/Mac SE per the spec threat model]
4. Added an autouse fixture pinning APPDATA/LOCALAPPDATA under tmp_path so the provider tests are deterministic
   on any CI %TEMP% (else a non-profile %TEMP% silently false-greens the whole security suite). [Opus M2]
5. `provision()` flush+fsyncs the sealed `.dek` before `os.replace` (power-loss durability). [Codex F2]

Codex F4 / Opus "AC #6" (cross-Windows-account isolation) is NOT unit-testable — manual verification only
(impl uses dwFlags=0 user-scope; entropy-mismatch is the automated proxy).

Final baseline: full `uv run mypy` clean (327 files) · `uv run pytest -q` 876 passed / 5 skipped · ruff clean.
