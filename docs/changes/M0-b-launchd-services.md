---
spec: m0-b-launchd-services
status: ready
token_profile: balanced
autonomy_level: L2
---

# Spec: M0-b — launchd service supervision + deploy/promote/rollback script

**Identity:** launchd plist templates for the four Artemis services (brain FastAPI + mlx-openai-server + ntfy as LaunchDaemons, Swift audio sidecar as a LaunchAgent) with boot-start + KeepAlive, health-check stub endpoints on the brain, and the local deploy/promote+rollback script (lean-default + full-UAT-for-risky per ADR-002).
→ why: see docs/technical/adr/ADR-002-deployment-method.md (launchd spine, lean-vs-full pipeline, rollback).

<!-- Split rule: this spec has TWO logical phases (1: plist templates + health stubs; 2: the deploy/promote/rollback script). It is at the 2-phase limit and stays one spec because the deploy script directly drives the launchd jobs the templates define (tight coupling). If review wants it leaner, sub-split into M0-b1 (plists+health) and M0-b2 (deploy script). Flagged per rules. -->

## Assumptions
- M0-a is complete: repo at `/Users/artemis-build/artemis`, `src/artemis/config.py` + `paths.py` exist, data-dir setup script exists, per-slot ports are the ones in M0-a Task 7. → impact: Stop (plists and the deploy script template these paths/ports).
- Services run under the **owner-runtime** macOS user (LaunchDaemons run as a configured `UserName`; the LaunchAgent runs in the runtime user's GUI/audio session), NOT the build-agent user. → impact: Stop (audio needs the user session per ADR-002; daemons must not run as the build user).
- The Swift audio sidecar binary and the mlx-openai-server + ntfy binaries are installed by their own specs (mlx by M0-c; the Swift sidecar and ntfy binary install are out of M0 scope and stubbed here). → impact: Caution (the audio LaunchAgent points at a sidecar binary path that may not yet exist; the plist is a template + the job will fail-restart until the binary lands — acceptable for M0). DECISION (FINALIZATION-NOTES): the ntfy binary IS installed in M0 — via Homebrew (`brew install ntfy`) in M0-c's install step / the deploy bootstrap; M0-b writes its plist against `/opt/homebrew/bin/ntfy` (path confirmed on-hardware). The Swift audio sidecar binary remains out of M0 scope (a later spec).
- macOS 26; `launchctl bootstrap`/`bootout` (the modern API) is used, not the deprecated `load`/`unload`. → impact: Caution (command syntax differs; templates use the modern domain-target form).
- ADR-002 "risky change" trigger = touches a data migration, sensitive module (finance/health/journal/memory), or the security/identity wall. M0-b encodes the trigger as a label-list/flag, not auto-detection. → impact: Low (a manual `--full` flag plus a documented risky-paths list is sufficient for M0; auto-detection can come later).

Simplicity check: considered using a third-party supervisor (pm2/supervisord) instead of launchd — rejected, ADR-002 locks launchd as the operational spine (boot-start, crash-restart, scheduled backups all ride it). launchd is the minimum and the decided tool.

## Prerequisites
- Specs that must be complete first: M0-a (paths, ports, slots).
- Environment setup required: macOS host with `launchctl` (the Mini). The plist *templates* are deterministic and verifiable on any mac; **actually `bootstrap`-ing the daemons and confirming KeepAlive restart is an on-hardware step** (see gated Task 8).

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| /Users/artemis-build/artemis/deploy/launchd/com.artemis.brain.plist.template | create | LaunchDaemon: FastAPI brain via uvicorn |
| /Users/artemis-build/artemis/deploy/launchd/com.artemis.mlx.plist.template | create | LaunchDaemon: mlx-openai-server |
| /Users/artemis-build/artemis/deploy/launchd/com.artemis.ntfy.plist.template | create | LaunchDaemon: ntfy server |
| /Users/artemis-build/artemis/deploy/launchd/com.artemis.audio.plist.template | create | LaunchAgent: Swift audio sidecar |
| /Users/artemis-build/artemis/src/artemis/main.py | create | FastAPI app + health stub endpoints |
| /Users/artemis-build/artemis/scripts/render_plists.py | create | renders `.template` → real plists with slot/port/path substitution |
| /Users/artemis-build/artemis/scripts/deploy.sh | create | lean-default + `--full` deploy/promote with rollback |
| /Users/artemis-build/artemis/scripts/pipeline.sh | create | lint → typecheck → unit → integration → migration-rehearsal(stub) → smoke |
| /Users/artemis-build/artemis/deploy/risky_paths.txt | create | path globs that auto-escalate to full-UAT |
| /Users/artemis-build/artemis/tests/test_health.py | create | tests the health stub endpoints |
| /Users/artemis-build/artemis/tests/test_render_plists.py | create | tests plist rendering substitution |

## Tasks
- [ ] Task 1: Write the brain FastAPI app with health stubs — files: `/Users/artemis-build/artemis/src/artemis/main.py` — `app = FastAPI()`; `GET /healthz` → `{"status":"ok","slot":<slot>}` (liveness, no deps); `GET /readyz` → `{"status":"ok"|"degraded","checks":{...}}` returning a STUB that for M0 always reports `ok` with an empty checks dict (real readiness checks land when engines exist). Both `async def`, no blocking I/O. Reads slot from `get_settings()`. — done when: `uv run mypy --strict src` passes and TestClient `GET /healthz` returns 200 with `status==ok`.

- [ ] Task 2: Write the brain LaunchDaemon template — files: `/Users/artemis-build/artemis/deploy/launchd/com.artemis.brain.plist.template` — `Label` `com.artemis.{SLOT}.brain`; `ProgramArguments` = the slot's `uv run uvicorn artemis.main:app --host 127.0.0.1 --port {BRAIN_PORT}` (full absolute uv path `{UV_BIN}`); `WorkingDirectory` `{REPO_DIR}`; `UserName` `{RUNTIME_USER}`; `EnvironmentVariables` `ARTEMIS_ENV_FILE={ENV_FILE}`; `RunAtLoad` true; `KeepAlive` `{Crashed: true}`; `StandardOutPath`/`StandardErrorPath` under `{LOGS_DIR}/brain.{out,err}.log`. All `{...}` are render placeholders. — done when: `render_plists.py` substitutes all placeholders and `plutil -lint` validates the rendered file (asserted Task 7/Acceptance).

- [ ] Task 3: Write the mlx + ntfy LaunchDaemon templates — files: `/Users/artemis-build/artemis/deploy/launchd/com.artemis.mlx.plist.template`, `/Users/artemis-build/artemis/deploy/launchd/com.artemis.ntfy.plist.template` — mlx: `Label` `com.artemis.{SLOT}.mlx`, `ProgramArguments` = `{MLX_LAUNCH_CMD}` placeholder (filled by M0-c's launch command), `--port {MLX_PORT}`, `UserName {RUNTIME_USER}`, `RunAtLoad`+`KeepAlive{Crashed:true}`, logs `{LOGS_DIR}/mlx.*`. ntfy: `Label` `com.artemis.{SLOT}.ntfy`, `ProgramArguments` = `{NTFY_BIN} serve --listen-http 127.0.0.1:{NTFY_PORT}`, same KeepAlive/logs. — done when: both templates render and pass `plutil -lint`.

- [ ] Task 4: Write the audio sidecar LaunchAgent template — files: `/Users/artemis-build/artemis/deploy/launchd/com.artemis.audio.plist.template` — `Label` `com.artemis.{SLOT}.audio`; LaunchAgent (installed to `~/Library/LaunchAgents` of the runtime user, runs in the audio/GUI session per ADR-002); `ProgramArguments` `{AUDIO_SIDECAR_BIN} --port {AUDIO_PORT} --brain-url http://127.0.0.1:{BRAIN_PORT}`; `RunAtLoad` true; `KeepAlive{Crashed:true}`; logs `{LOGS_DIR}/audio.*`. Add a header comment noting the binary is produced by the Swift sidecar spec (not M0) and the job will restart-fail until it exists. — done when: template renders and passes `plutil -lint`.

- [ ] Task 5: Write the plist renderer — files: `/Users/artemis-build/artemis/scripts/render_plists.py` — typed Python; reads `Settings` for the given slot (`--slot`), resolves `{REPO_DIR}`, `{UV_BIN}` (`shutil.which("uv")`), `{ENV_FILE}`, `{LOGS_DIR}` (from `paths.logs_dir`), `{RUNTIME_USER}` (from env `ARTEMIS_RUNTIME_USER`), the 4 ports, and the binary-path placeholders (`{MLX_LAUNCH_CMD}`,`{NTFY_BIN}`,`{AUDIO_SIDECAR_BIN}` from env with documented defaults), then writes rendered plists to `--out-dir` (default `deploy/launchd/rendered/{slot}/`). Fails loudly (`SystemExit`) on any unresolved `{...}` placeholder remaining. — done when: `uv run mypy --strict scripts/render_plists.py` passes and running it for `dev` emits 4 plists with zero remaining `{` placeholders.

- [ ] Task 6: Write the local pipeline script — files: `/Users/artemis-build/artemis/scripts/pipeline.sh` — bash `set -euo pipefail`; runs in order: `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy --strict src`, `uv run pytest -q -m "not integration"` (unit), `uv run pytest -q -m integration` (integration; passes vacuously in M0 — no integration tests yet), a migration-rehearsal STUB (`echo "migration rehearsal: no migrations in M0"` — real rehearsal arrives with the first migration), then a smoke STUB (`echo`). Each stage prints a header; any non-zero stage aborts. — done when: `bash scripts/pipeline.sh` exits 0 on the M0 codebase.

- [ ] Task 7: Write the deploy/promote/rollback script — files: `/Users/artemis-build/artemis/scripts/deploy.sh`, `/Users/artemis-build/artemis/deploy/risky_paths.txt` — bash `set -euo pipefail`. `deploy.sh` flags: `--from <slot>` `--to <slot>` `[--full]`. Behaviour: (1) determine risky = `--full` OR any changed file (`git diff --name-only <prev-prod-tag>..HEAD`) matches a glob in `risky_paths.txt`; (2) run `pipeline.sh`; (3) if risky → also bootstrap a UAT instance (render UAT plists, `launchctl bootstrap`), print "FULL UAT: owner sign-off required" and wait for an explicit `--confirm` token file (`touch deploy/.uat-approved`) before promoting; (4) **backup-before-promote**: call the M0-e backup script for the target slot (placeholder call `scripts/backup.sh --slot <to>`); (5) record the current PROD git tag as `rollback-point` (`git tag -f artemis-prod-prev`); (6) promote = `launchctl bootout` the target slot's jobs, render the target plists at the new commit, `launchctl bootstrap` them; (7) `--rollback` flag: `git checkout artemis-prod-prev`, re-render, re-bootstrap, restore the pre-promote backup. `risky_paths.txt` seeds globs: `src/artemis/security/*`, `src/artemis/identity/*`, `**/migrations/*`, `src/artemis/modules/finance/*`, `src/artemis/modules/health/*`, `src/artemis/modules/journal/*`, `src/artemis/memory/*`. — done when: `bash scripts/deploy.sh --from dev --to uat` (dry, on a mac without bootstrapping — guarded by an `ARTEMIS_DEPLOY_DRYRUN=1` that skips `launchctl`) runs the pipeline + prints the planned actions and exits 0.

- [ ] Task 8 (GATED — on-hardware): Bootstrap the dev daemons and verify KeepAlive — files: (no new files; uses rendered plists from Task 5) — on the Mac Mini only: `sudo launchctl bootstrap system deploy/launchd/rendered/dev/com.artemis.dev.brain.plist`, confirm `curl http://127.0.0.1:8030/healthz` returns 200, `kill` the uvicorn PID and confirm launchd restarts it within ~10s. Mark this task **build-time empirical**; cannot be verified off-hardware. — done when: on the Mini, the brain daemon answers `/healthz` and auto-restarts after a kill.

- [ ] Task 9: Write the health + render tests — files: `/Users/artemis-build/artemis/tests/test_health.py`, `/Users/artemis-build/artemis/tests/test_render_plists.py` — test_health uses FastAPI `TestClient` for `/healthz` and `/readyz`; test_render_plists renders to a temp dir with a temp Settings and asserts no `{` remains and `Label` contains the slot. — done when: `uv run pytest -q` passes.

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | /Users/artemis-build/artemis/deploy/launchd/com.artemis.*.plist.template, /Users/artemis-build/artemis/deploy/launchd/rendered/** (script output), /Users/artemis-build/artemis/deploy/risky_paths.txt, /Users/artemis-build/artemis/src/artemis/main.py, /Users/artemis-build/artemis/scripts/render_plists.py, /Users/artemis-build/artemis/scripts/deploy.sh, /Users/artemis-build/artemis/scripts/pipeline.sh, /Users/artemis-build/artemis/tests/test_health.py, /Users/artemis-build/artemis/tests/test_render_plists.py |
| Modify | (none) |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict src scripts/render_plists.py` | Type gate |
| `uv run pytest -q` | Test gate |
| `uv run python scripts/render_plists.py --slot dev` | Render plists |
| `plutil -lint <rendered>.plist` | Validate plist XML |
| `bash scripts/pipeline.sh` | Run the local pipeline |
| `ARTEMIS_DEPLOY_DRYRUN=1 bash scripts/deploy.sh --from dev --to uat` | Dry deploy |
| `sudo launchctl bootstrap system <plist>` (GATED, on-Mini only) | Load a daemon |
| `curl http://127.0.0.1:8030/healthz` (GATED) | Health check |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | deploy/**, scripts/**, src/artemis/main.py, tests/test_health.py, tests/test_render_plists.py |
| `git commit` | "feat: M0-b launchd service templates + deploy/rollback script + health stubs" |
| `git tag` | `artemis-prod-prev` (rollback point, set by deploy.sh) |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_ENV_FILE` | Slot env consumed by the daemons |
| `ARTEMIS_RUNTIME_USER` | macOS user the daemons run as |
| `ARTEMIS_DEPLOY_DRYRUN` | Skip launchctl for off-hardware dry runs |
| `MLX_LAUNCH_CMD`, `NTFY_BIN`, `AUDIO_SIDECAR_BIN` | Binary paths for the non-brain plists |

### Network
| Action | Purpose |
|--------|---------|
| `uv sync` | Package installation (PyPI) |
| `curl localhost` (GATED) | Local health probe |

## Specialist Context
### Security
Daemons bind `127.0.0.1` only — no public listener (ADR-002: no web surface, Tailscale for remote). Daemons run as the runtime user, never the build-agent user. The deploy script does a backup-before-promote and keeps a `git tag` rollback point (ADR-002 backup-before-migrate + restore-snapshot rollback). [FLAG apex-security: review the `risky_paths.txt` globs at M2 once the security/identity module paths are finalised.]

### Performance
ADR-002 live↔build are mutually exclusive — the deploy script assumes it may stop the live assistant during promotion; document that promotion causes a brief unavailability window (accepted per ADR-002).

### Accessibility
(none — no frontend)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | scripts/render_plists.py, src/artemis/main.py | Type + docstring all exports |
| Header comments | deploy/launchd/*.template | Note placeholder list + which spec provides each binary |

## Acceptance Criteria
- [ ] Run `uv run python scripts/render_plists.py --slot dev --out-dir /tmp/plists` → verify: 4 `.plist` files produced; `grep -L '{' /tmp/plists/*.plist` lists all 4 (no unresolved placeholders).
- [ ] Run `plutil -lint /tmp/plists/*.plist` → verify: each prints `OK`.
- [ ] Run `uv run pytest -q` → verify: test_health + test_render_plists pass.
- [ ] Run `bash scripts/pipeline.sh` → verify: every stage header prints and exit 0.
- [ ] Run `ARTEMIS_DEPLOY_DRYRUN=1 bash scripts/deploy.sh --from dev --to uat` → verify: prints the planned bootout/bootstrap actions, runs the pipeline, exits 0, and creates no real launchd jobs.
- [ ] (GATED, on Mini) Bootstrap the dev brain daemon, `curl /healthz` → 200, kill the PID → verify: launchd restarts it within ~10s.

## Progress
_(Coding mode writes here — do not edit manually)_
