---
spec: m0-e-isolation-backup
status: ready
token_profile: balanced
autonomy_level: L2
---

# Spec: M0-e — Build-agent isolation + backup-script skeleton

**Identity:** Sets up build-agent isolation (a dedicated macOS user account + Claude Code OS-sandbox config + sample-data discipline) and the backup-script skeleton (clean DB dumps via the SQLite backup API / `VACUUM INTO`, never raw copy; an append-only/immutable copy; scheduled via launchd).
→ why: see docs/technical/adr/ADR-002-deployment-method.md (build-agent isolation: dedicated user + sandbox + sample data; backups: clean snapshots only + append-only copy + launchd-scheduled + tested restores).

<!-- Split rule: TWO logical phases (1: build-agent isolation; 2: backup skeleton). At the 2-phase limit; kept together because both are the "protect the box" cross-cutting concern and share the launchd-scheduling mechanism + the dedicated-user boundary. If review wants leaner: sub-split into M0-e1 (isolation) and M0-e2 (backups). Flagged per rules. -->

## Assumptions
- M0-a is complete (data-dir layout + scope dirs); M0-b is complete (launchd render mechanism, `deploy.sh` calls `scripts/backup.sh`). → impact: Stop (the backup script targets M0-a's per-scope SQLCipher file locations and is scheduled via the M0-b launchd pattern; `deploy.sh` already references `scripts/backup.sh`).
- Two macOS users exist on the Mini: `artemis-build` (the build agent, runs Claude Code) and the runtime user that owns the data + runs the daemons. The build user must NOT be able to read the runtime user's Keychain or `owner-private/`. → impact: Stop (the whole isolation boundary depends on this; ADR-002 "dedicated user + cannot decrypt owner data").
- Creating macOS user accounts + applying the Claude Code OS sandbox + setting filesystem ACLs are **on-hardware administrative steps** (need `sudo`, `dscl`/`sysadminctl`, real macOS). → impact: Stop (these are GATED build-time tasks; the spec writes the *scripts/config* deterministically but they only take effect on the Mini).
- The SQLCipher backup uses the SQLite Online Backup API or `VACUUM INTO` issued **through an SQLCipher-keyed connection** (the dump is itself encrypted, source already encrypted per ADR-002). The backup script must obtain the per-scope key from Keychain at run time — the *mechanism* (`security find-generic-password` / a keyed helper) is stubbed in M0 since no DBs/keys exist yet. → impact: Caution. DECISION (FINALIZATION-NOTES): M0-e ships the backup script as a runnable skeleton over sample/empty DBs (proving the VACUUM-INTO-not-raw-copy mechanic + immutable copy + retention); the real keyed dump (per-scope Keychain key) is deferred to M4 when the encrypted DBs exist.
- "append-only/immutable copy" in M0 = a local directory with macOS `uchg` (immutable) flag or an append-only-permission scheme; the offsite/object-lock target is deferred per ADR-002. → impact: Low.

Simplicity check: considered a devcontainer for the build agent instead of a dedicated user — rejected by ADR-002 (Linux container = Metal wall, can't run the MLX tests). Dedicated-user + Claude Code sandbox is the decided, minimal native boundary. For backups, considered plain `cp` of the DB files — rejected by ADR-002 (raw copy of a live DB is corruption-prone; must be a clean `VACUUM INTO`/backup-API snapshot).

## Prerequisites
- Specs that must be complete first: M0-a (scope dir layout + paths), M0-b (launchd render + deploy.sh's `backup.sh` reference).
- Environment setup required: the Mac Mini with admin rights (for user creation + sandbox + ACLs + launchd). Script authoring is deterministic; **account creation, sandbox enforcement, ACLs, and a real scheduled run are GATED on-hardware tasks.**

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| /Users/artemis-build/artemis/scripts/setup_build_user.sh | create | creates the `artemis-build` macOS user + sets ACLs walling it off from `owner-private/` + the runtime Keychain |
| /Users/artemis-build/artemis/deploy/sandbox/claude-code-sandbox.json | create | Claude Code OS-sandbox config (filesystem + network walls for the build agent) |
| /Users/artemis-build/artemis/scripts/seed_sample_data.sh | create | populates a `sample-data/` tree (synthetic only) the build/test path uses instead of real owner data |
| /Users/artemis-build/artemis/scripts/backup.sh | create | clean per-scope snapshot via `VACUUM INTO` (skeleton over empty/sample DBs) + immutable copy + retention |
| /Users/artemis-build/artemis/scripts/restore_test.sh | create | restores the latest snapshot to a scratch dir + integrity-checks it (tested-restores requirement) |
| /Users/artemis-build/artemis/deploy/launchd/com.artemis.backup.plist.template | create | LaunchDaemon (StartCalendarInterval) that runs backup.sh on a schedule |
| /Users/artemis-build/artemis/tests/test_backup_script.py | create | tests the VACUUM-INTO snapshot mechanic against a temp SQLite DB (no SQLCipher key needed) |

## Tasks
- [ ] Task 1: Write the build-user setup script — files: `/Users/artemis-build/artemis/scripts/setup_build_user.sh` — bash `set -euo pipefail`, requires root; idempotent. Creates the `artemis-build` user via `sysadminctl -addUser artemis-build -fullName "Artemis Build Agent" -password -` (non-admin, standard); sets the home to `/Users/artemis-build`; applies `chmod`/`chmod +a` ACLs DENYING `artemis-build` read on the runtime data root `/opt/artemis` (especially `/opt/artemis/<slot>/owner-private`) and the runtime user's `~/Library/Keychains`. Prints the resulting `ls -le` ACLs. Pure scripting; takes effect only on a real mac. — done when: the script passes `bash -n` (syntax) off-hardware; on-Mini (GATED, Task 7) it creates the user and the ACL denies are present.

- [ ] Task 2: Write the Claude Code sandbox config — files: `/Users/artemis-build/artemis/deploy/sandbox/claude-code-sandbox.json` — a Claude Code OS-sandbox profile granting the build agent read/write ONLY within `/Users/artemis-build/artemis` + the model dir + `sample-data/`, DENYING the runtime data root + Keychain paths, and walling network to PyPI/HF/git + the DeepSeek/Claude endpoints only (per ADR-002 "filesystem + network walls; blocks prompt-injection exfiltration"). — done when: the JSON parses (`uv run python -c "import json,sys; json.load(open('deploy/sandbox/claude-code-sandbox.json'))"`) and the allowed-fs list excludes the runtime data root. DECISION (on-hardware confirm): ship the drafted JSON sandbox profile now; the exact Claude Code OS-sandbox config schema/filename (settings.json `permissions`/sandbox keys vs a standalone profile) is confirmed against the installed Claude Code on the Mini (GATED, Task 7) and adapted there. The drafted JSON encodes the intended fs/network walls regardless of the final schema.

- [ ] Task 3: Write the sample-data seeder — files: `/Users/artemis-build/artemis/scripts/seed_sample_data.sh` — bash `set -euo pipefail`; creates `sample-data/<slot>/owner-private/` etc. mirroring the real layout and writes SYNTHETIC fixtures only (clearly-fake names/values, a header banner "SYNTHETIC — never real owner data"). The build/test path points here; never at the runtime data root. — done when: running it creates `sample-data/dev/owner-private/` with a synthetic-marker file; the script never references the real data root.

- [ ] Task 4: Write the backup script (clean-snapshot mechanic) — files: `/Users/artemis-build/artemis/scripts/backup.sh` — bash `set -euo pipefail`; flags `--slot <slot>` `[--data-root <path>]`. For each scope dir under the slot, for each `*.db`/`*.sqlite` file: produce a clean snapshot using `sqlite3 "<db>" "VACUUM INTO '<snapshot>'"` (NOT `cp`) — for SQLCipher DBs the connection must be keyed first (`PRAGMA key`), with the key fetched via a `get_scope_key()` helper that in M0 is a documented STUB returning the empty key for unencrypted sample/empty DBs (real Keychain fetch lands at M4). Write snapshots to `<slot>/backups/<UTC-timestamp>/<scope>/`; then make the timestamp dir immutable (`chflags uchg`); apply retention (keep last N, default 7). Refuses to run if it detects a live raw-copy fallback. — done when: against a temp plain SQLite DB the script produces a `VACUUM INTO` snapshot that opens and `PRAGMA integrity_check` returns `ok` (asserted in Task 6/Acceptance), and the snapshot dir has the `uchg` flag.

- [ ] Task 5: Write the restore-test script + the backup launchd template — files: `/Users/artemis-build/artemis/scripts/restore_test.sh`, `/Users/artemis-build/artemis/deploy/launchd/com.artemis.backup.plist.template` — restore_test.sh: copies the latest snapshot dir to a scratch path (clearing `uchg` on the copy, never the original) and runs `PRAGMA integrity_check` on each restored DB, exiting non-zero if any is not `ok` (this is the "tested restores" requirement). backup plist template: `Label` `com.artemis.{SLOT}.backup`, `ProgramArguments` `{REPO_DIR}/scripts/backup.sh --slot {SLOT}`, `StartCalendarInterval` (default 03:00 daily), `UserName {RUNTIME_USER}` (needs the runtime user's Keychain access for real keys), `RunAtLoad` false, logs `{LOGS_DIR}/backup.*`. — done when: restore_test.sh exits 0 on a snapshot produced by Task 4, and `render_plists.py` (extended to include the backup plist, OR a direct render) emits a `plutil -lint`-valid backup plist.

- [ ] Task 6: Write the backup-mechanic test — files: `/Users/artemis-build/artemis/tests/test_backup_script.py` — typed pytest: create a temp SQLite DB with a row, invoke `backup.sh --slot test --data-root <tmp>` (point it at the temp DB via the sample layout), assert a snapshot file exists, assert it is NOT byte-identical to a naive `cp` (i.e. VACUUM INTO ran — compare via opening + `integrity_check`), assert `PRAGMA integrity_check` returns `ok`, assert the snapshot dir carries the immutable flag (`ls -lO`/`stat`). — done when: `uv run pytest -q` passes.

- [ ] Task 7 (GATED — on-hardware): Provision the build user + sandbox + a scheduled backup run — files: (uses Tasks 1/2/5 outputs) — on the Mini, as admin: run `setup_build_user.sh`, apply the Claude Code sandbox config, render + `launchctl bootstrap` the backup daemon for `dev`, trigger one run (`launchctl kickstart`), confirm a snapshot appeared and `restore_test.sh` passes. Build-time empirical (needs real macOS users/ACLs/launchd). — done when: the build user exists with the deny-ACLs, a scheduled backup produced an immutable snapshot, and the restore test passes — all on the Mini.

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | /Users/artemis-build/artemis/scripts/setup_build_user.sh, /Users/artemis-build/artemis/deploy/sandbox/claude-code-sandbox.json, /Users/artemis-build/artemis/scripts/seed_sample_data.sh, /Users/artemis-build/artemis/scripts/backup.sh, /Users/artemis-build/artemis/scripts/restore_test.sh, /Users/artemis-build/artemis/deploy/launchd/com.artemis.backup.plist.template, /Users/artemis-build/artemis/tests/test_backup_script.py |
| Modify | (none in M0; render_plists.py extension noted in Task 5 may modify /Users/artemis-build/artemis/scripts/render_plists.py to include the backup plist) |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `bash -n scripts/*.sh` | Syntax-check the shell scripts off-hardware |
| `uv run pytest -q` | Test gate (backup mechanic) |
| `sqlite3 <db> "VACUUM INTO '<snap>'"` | Clean snapshot (inside backup.sh) |
| `chflags uchg <dir>` | Mark a snapshot immutable |
| `sysadminctl -addUser artemis-build ...` (GATED, on-Mini) | Create the build user |
| `dscl . / chmod +a ...` (GATED) | Deny-ACL the build user off owner data |
| `launchctl bootstrap system <backup-plist>` + `launchctl kickstart` (GATED) | Schedule + trigger a backup |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | scripts/setup_build_user.sh, scripts/seed_sample_data.sh, scripts/backup.sh, scripts/restore_test.sh, deploy/sandbox/**, deploy/launchd/com.artemis.backup.plist.template, tests/test_backup_script.py |
| `git commit` | "feat: M0-e build-agent isolation + backup skeleton (VACUUM INTO + immutable + launchd)" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_DATA_ROOT` | Locate per-scope DBs to snapshot |
| `ARTEMIS_RUNTIME_USER` | The user the backup daemon runs as (Keychain access) |

### Network
| Action | Purpose |
|--------|---------|
| (none for the backup path) | Backups are local-only in M0 (offsite deferred per ADR-002) |

## Specialist Context
### Security
This spec IS a security control surface (ADR-002 defense-in-depth). Two boundaries: (1) the dedicated build user + Claude Code sandbox + sample-data discipline keep the cloud build agent off real owner data and Keychain; (2) backups are clean encrypted snapshots with an immutable copy (2026 ransomware baseline). [FLAG apex-security at M2: review the deny-ACLs + sandbox profile once the real Keychain key flow and `owner-private/` ownership are implemented; the M0 backup key fetch is a STUB and must be replaced with the real keyed dump at M4 — do not ship real backups on the stub.]

### Performance
Backups run at 03:00 (off-peak), `RunAtLoad false`; `deploy.sh` also calls `backup.sh` before a risky promotion (backup-before-migrate, ADR-002). VACUUM INTO on a live DB is safe (reader snapshot) but I/O-heavy — schedule respects the off-peak window.

### Accessibility
(none — no frontend)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | scripts/*.sh, scripts/backup.sh `get_scope_key` stub | Comment the stub + the "never raw copy" + "never real owner data" invariants |
| Header banner | scripts/seed_sample_data.sh output | "SYNTHETIC — never real owner data" |

## Acceptance Criteria
- [ ] Run `bash -n scripts/setup_build_user.sh scripts/seed_sample_data.sh scripts/backup.sh scripts/restore_test.sh` → verify: all exit 0 (valid shell syntax).
- [ ] Run `uv run python -c "import json; json.load(open('deploy/sandbox/claude-code-sandbox.json'))"` → verify: exit 0 (valid JSON; runtime data root NOT in the allowed-fs list).
- [ ] Run `bash scripts/seed_sample_data.sh` → verify: `sample-data/dev/owner-private/` exists with a SYNTHETIC marker; the real data root is untouched.
- [ ] Run `uv run pytest -q` (test_backup_script) → verify: a `VACUUM INTO` snapshot is produced, `integrity_check` returns `ok`, snapshot dir has the immutable flag, and it is not a naive byte-copy.
- [ ] Run `bash scripts/restore_test.sh --slot test --data-root <tmp>` against that snapshot → verify: exit 0 (restored DBs pass `integrity_check`).
- [ ] (GATED, on Mini) Run `setup_build_user.sh`; `ls -le` the runtime `owner-private` dir → verify: `artemis-build` has a deny ACL; a kickstarted backup produces an immutable snapshot and `restore_test.sh` passes.

## Progress
_(Coding mode writes here — do not edit manually)_
