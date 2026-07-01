---
spec: m0-f-env-injection
status: ready
token_profile: balanced
autonomy_level: L2
cross_model_review: true
---
<!-- amended 2026-06-11 per m0-m1-foundation-brain.md BLOCKs B8, B9 -->

# Spec: M0-f — Keychain→slot-`.env` secrets-injection script (`inject_env.py`) + deploy.sh wiring

**Identity:** A typed Python script that reads the owner macOS Keychain (`security find-generic-password`) for the Medium-tier runtime secrets, preserves the generated ntfy topic-secret, and writes a `0600` owner-only slot `.env` (the file the M0-b daemon plists already reference via `ARTEMIS_ENV_FILE`); wired into M0-b's `deploy.sh` as a pre-bootstrap step and invoked at bring-up. Resolves SECRETS-INVENTORY P1 (exact Keychain service/account names) + P5 (the injection mechanism).
→ why: see docs/bring-up/SECRETS-INVENTORY.md (S1/S2/S4/S5/S6/S7 Keychain→`.env`; S11 generated/preserved; P1/P5) · docs/technical/adr/ADR-002-deployment-method.md (launchd spine; deploy/promote). Mechanism decision (persisted `.env` over wrapper-exec, to sidestep launchd-keychain-at-boot): this session's planning discussion.

<!-- A spec is an EXECUTION SCRIPT, not a design doc. DeepSeek executes literally. -->

<!-- Split rule: ONE logical phase (the secrets loader) across 1 create (inject_env.py) + 1 modify (deploy.sh) + 1 create (test). Within the 3-file limit; no split. The macOS `security` shell-out is GATED on-hardware; the writer/merge/perms logic is fully testable off-hardware behind an injected fake Keychain reader. -->

## Assumptions
- M0-a complete: `src/artemis/config.py` `Settings` + `get_settings()` + `src/artemis/paths.py`; **the slot `.env` path is resolved by `paths.env_file(settings)` — the canonical single-source-of-truth function added to M0-a `paths.py` in the B9 amendment** (returns `Path("config") / f".env.{settings.slot}"`). `inject_env.py` MUST call `paths.env_file(settings)` and so must `render_plists.py`'s `{ENV_FILE}` — both reference the same function. Do NOT hardcode a divergent path. → impact: Stop (B9: three contradictory candidates collapsed to one; the resolver is `paths.env_file`).
- (B8) **The slot `.env` path is resolved WITHOUT first constructing a full `Settings` that reads secrets.** `Settings` declares NO secret fields (`BRAVE_API_KEY` etc. are NOT `Settings` fields — they are written by this script into the `.env` file). Resolving the env-file path requires only `slot: str` (the one non-secret field `inject_env.py` gets from `--slot` CLI arg). To avoid the bootstrap circularity (calling `get_settings()` before the `.env` file exists), `inject_env.py` derives the path as `paths.env_file_for_slot(slot)` — add this thin helper `def env_file_for_slot(slot: str) -> Path: return Path("config") / f".env.{slot}"` to `paths.py` (a slot-string form of `env_file(settings)` that does NOT require a `Settings` object). → impact: Stop (the circularity is eliminated; `inject_env.py` never calls `get_settings()` for path resolution).
- M0-b complete: `scripts/deploy.sh` exists with the promote flow `render plists → backup-before-promote → launchctl bootstrap`; this spec inserts the `inject_env.py` call **after render, before `launchctl bootstrap`** for the `--to` slot. → impact: Stop (the injection must run before the daemons start so the `.env` exists at first read).
- Runs as the **owner-runtime macOS user** in an interactive/unlocked-Keychain context (bring-up step 3 of SECRETS-INVENTORY §"Provisioning order", and `deploy.sh` run by the owner) — NOT a boot-time daemon. This is the whole point of the persisted-`.env` design: Keychain is read while unlocked, decoupled from daemon start (LaunchDaemons may start before the login keychain unlocks). → impact: Stop (the script is never invoked from a LaunchDaemon; it is a deploy/bring-up-time tool).
- **Keychain item map (locks SECRETS-INVENTORY P1 — the single source of truth, mirrors S1/S2/S4/S5/S6/S7):**
  | env var | Keychain service | account | required |
  |---|---|---|---|
  | `GOOGLE_OAUTH_CLIENT_ID` | `artemis.google.oauth` | `client_id` | required |
  | `GOOGLE_OAUTH_CLIENT_SECRET` | `artemis.google.oauth` | `client_secret` | required |
  | `BRAVE_API_KEY` | `artemis.search.brave` | `api_key` | required |
  | `TAVILY_API_KEY` | `artemis.search.tavily` | `api_key` | required |
  | `JINA_API_KEY` | `artemis.search.jina` | `api_key` | optional |
  | `DEEPSEEK_API_KEY` | `artemis.deepseek` | `api_key` | optional |
  → impact: Stop (these exact names are now canonical; they must match what `Settings` reads and what the runbook loads into Keychain).
- **The slot `.env` PRE-EXISTS with non-secret config — MERGE, never clobber.** The env file is `config/.env.<slot>` (RUNBOOK Step 4 copies `config/.env.<slot>.example` → `config/.env.<slot>` and sets `ARTEMIS_DATA_ROOT`, `ARTEMIS_RUNTIME_USER`, etc.). `inject_env.py` MUST **start from the existing parsed file and overlay only the managed keys** — preserving every existing non-managed `KEY=value` line (DATA_ROOT, RUNTIME_USER, future config). The "managed" keys are exactly the six Keychain env vars (overwrite if Keychain returns a value) + `ARTEMIS_NTFY_TOPIC_SECRET`. Writing a secrets-only file would destroy the slot config and break the daemons. → impact: Stop (merge-not-clobber is load-bearing; the file is the daemons' whole environment, not just secrets).
- **S11 ntfy topic-secret is GENERATED, not from Keychain, and PRESERVED across re-runs:** `ARTEMIS_NTFY_TOPIC_SECRET` is `secrets.token_hex(16)`. If a prior value is present in the existing `.env` it is CARRIED FORWARD unchanged (rotating it silently would break the phone's ntfy subscription — M6-c); only if absent does the script generate a fresh one. → impact: Stop (preserve-not-rotate is load-bearing; a re-deploy must not change the topic secret).
- **Out of scope (NOT secrets / not Keychain→`.env`):** S3 Google refresh token (owner-private SQLCipher, never `.env`); S10 Claude CLI session (managed by `claude` CLI); S13 macOS boot creds; S8/S9 Tailscale; S12 phone public key. Also OUT: the non-secret DeepSeek CONFIG (`DEEPSEEK_BASE_URL`, `DEEPSEEK_JUDGE_MODEL`) — those are plain config (roles.toml / Settings), not secrets this loader owns. → impact: Stop (this script touches ONLY the six Keychain secrets above + the generated S11).
- **macOS-only `security` shell-out is GATED on-hardware; the writer/merge/perms logic is tested off-hardware behind an injected reader.** `inject_env.py` reads Keychain through a single function `read_keychain(service, account) -> str | None` that runs `security find-generic-password -s <service> -a <account> -w` (returns the password on stdout; non-zero exit / not-found → `None`). Tests inject a `fake_reader` so the file-writing/merge/perms/required-missing/ntfy-preserve behaviour is fully deterministic without macOS. The real `security` invocation is the GATED on-hardware task. → impact: Caution (correctness proven off-hardware; the live Keychain read is the on-Mini gate).
- The repo `.gitignore` (VERIFIED) ignores the secret-bearing slot files via `.env` + `.env.*` while keeping the examples tracked via `!.env.*.example` — `.env.*` matches `config/.env.<slot>` at any depth, so the written file is never committable. No `.gitignore` change needed. → impact: Low.
- (B8) **`Settings` does NOT declare secret fields** — `Settings` has no `BRAVE_API_KEY` etc. fields; it is a config-only object (slot, ports, data_root, roles). The "fails LOUD" layer is handled by each daemon/service validating its own required secrets at startup (e.g. `GoogleOAuthClient` raises at construction if `GOOGLE_OAUTH_CLIENT_SECRET` is absent from the env). The `--allow-missing` per-key stderr WARNING is the loud signal at injection time; daemon-side validation is the loud signal at service start. → impact: Caution (removes the implicit dependency on Settings fields that don't exist in M0-a).

Simplicity check: considered a wrapper-exec design (each daemon plist runs a wrapper that reads Keychain live and `exec`s the command, no on-disk secrets) — REJECTED: macOS LaunchDaemons start at boot before the login keychain is reliably unlocked, so a per-start Keychain read fails headless after a power-cut reboot; persisting a `0600` `.env` written interactively (Keychain unlocked) is the robust choice, and the at-rest exposure is bounded (Medium-tier secrets only — the HIGH refresh token stays in SQLCipher — behind FileVault + `0600` + the owner-private slot dir). Considered storing these in a SQLCipher store like S3 — REJECTED: overkill for Medium API keys and reintroduces the broker/DEK boot-ordering dependency. This script is the minimum that loads the runtime secrets without the boot-keychain footgun.

## Prerequisites
- Specs that must be complete first: **M0-a** (`Settings`/`paths`/`get_settings`), **M0-b** (`scripts/deploy.sh` + `scripts/render_plists.py` `{ENV_FILE}` resolver). Sequenced-with: the SECRETS-INVENTORY (the Keychain item names this spec locks).
- Environment setup required: none new off-hardware (stdlib `subprocess`/`secrets`/`os` only; no new package). On-hardware: the owner Keychain pre-loaded with S1/S2/S4/S5 (+ optional S6/S7) per the runbook — that is the GATED step.

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| /Users/artemis-build/artemis/scripts/inject_env.py | create | the Keychain→`.env` loader: item map, `read_keychain` shell-out, existing-`.env` parse + ntfy-preserve, atomic `0600` write, required-missing handling, `--slot`/`--allow-missing` CLI |
| /Users/artemis-build/artemis/src/artemis/paths.py | modify | add `env_file_for_slot(slot: str) -> Path` helper (B8/B9: avoids bootstrap circularity; used by inject_env.py to resolve path without constructing Settings) |
| /Users/artemis-build/artemis/scripts/deploy.sh | modify | call `inject_env.py --slot <to>` AFTER render_plists, BEFORE `launchctl bootstrap` (skipped under `ARTEMIS_DEPLOY_DRYRUN=1` like the other launchctl steps, but the injection itself still runs in dry-run to validate — see Task 2) |
| /Users/artemis-build/artemis/tests/test_inject_env.py | create | deterministic tests with an injected fake Keychain reader: full `.env` write, required-missing exit, optional-missing skip, ntfy-preserve vs generate, `0600` perms, no-secret-value-in-logs |

## Tasks
- [ ] Task 1: Implement `inject_env.py` — files: `/Users/artemis-build/artemis/scripts/inject_env.py` — typed Python, `uv run mypy --strict`-clean, stdlib only.
  - Module constant `KEYCHAIN_ITEMS: tuple[KeychainItem, ...]` where `KeychainItem` is a frozen dataclass `{env_var: str, service: str, account: str, required: bool}`, seeded EXACTLY from the Assumptions item map (6 items). Add a comment: "mirrors SECRETS-INVENTORY S1/S2/S4/S5/S6/S7; this map is the canonical P1 resolution."
  - `def read_keychain(service: str, account: str) -> str | None`: wrap in `try: result = subprocess.run(["security", "find-generic-password", "-s", service, "-a", account, "-w"], capture_output=True, text=True) except (FileNotFoundError, OSError): return None` (if the `security` binary is absent / the call fails unexpectedly, fail closed to `None` — never let a raw traceback with the args propagate) — **arg LIST, never `shell=True`** (no shell injection); on `result.returncode != 0` return `None` (item absent); else return `result.stdout.rstrip("\n")` (strip the trailing newline `security -w` adds). **NEVER log `result.stdout`; DISCARD `result.stderr` entirely** — do not log, surface, or include it in any exception/message (some macOS `security` versions emit secret-adjacent material on stderr).
  - `def parse_existing_env(path: Path) -> dict[str, str]`: if the file exists, parse `KEY=value` lines (ignore blank lines + `#` comments; split on the FIRST `=`; strip surrounding whitespace) into a dict; else `{}`. This captures ALL existing keys (non-secret config + any prior secrets) so the merge preserves them.
  - `def build_env(*, reader: Callable[[str, str], str | None], existing: Mapping[str, str], allow_missing: bool, ntfy_factory: Callable[[], str] = lambda: secrets.token_hex(16)) -> tuple[dict[str, str], list[str]]`: **start `env = dict(existing)`** (preserve every existing key — DATA_ROOT/RUNTIME_USER/etc.). Then for each `KEYCHAIN_ITEMS` entry call `reader(service, account)`; if a value is returned, set `env[env_var] = value` (overlay/overwrite the managed key); if `None` and `required` **and `env_var not in env`** (not already preserved from a prior run), collect `env_var` into `missing_required`. Then the ntfy secret: read `env.get("ARTEMIS_NTFY_TOPIC_SECRET")` and **validate it** with `re.fullmatch(r"[0-9a-f]{32}", v)` — if present-and-valid leave it unchanged; if present-but-invalid (corrupted/tampered) OR absent, set `env["ARTEMIS_NTFY_TOPIC_SECRET"] = ntfy_factory()` (log a WARNING `"ntfy secret absent/invalid — regenerating"` on the invalid case, never the value). Return `(env, missing_required)`. (`ntfy_factory` injectable for deterministic tests.)
  - `def write_env_file(path: Path, env: Mapping[str, str]) -> None`: write atomically — `fd = os.open(tmp, os.O_WRONLY|os.O_CREAT|os.O_TRUNC, 0o600)` in the SAME dir as `path`, then **`with os.fdopen(fd, "w") as f:`** (bridge the 0600 fd to a text file object — do NOT use a bare `open()` which would bypass the creation mode) write a header `# Artemis slot env (config + secrets) — generated by inject_env.py; DO NOT COMMIT; DO NOT EDIT BY HAND\n` then sorted `KEY=value\n` lines; after the `with` block `os.replace(tmp, path)` then `os.chmod(path, 0o600)`. NEVER log any value. (The `os.replace`→`os.chmod` gap is accepted: the slot dir is owner-only + FileVault-backed, so no other user process can observe an intermediate mode.)
  - `def main(argv: Sequence[str] | None = None) -> int`: argparse `--slot <name>` (required), `--allow-missing` (flag — downgrade required-missing to a warning, for partial bring-up). Resolve the env-file path via `paths.env_file_for_slot(args.slot)` — **do NOT call `get_settings()` here** (B8: avoids the bootstrap circularity; `get_settings()` would fail before injection because secrets aren't in the env yet; the path needs only the slot string). `existing = parse_existing_env(path)`; `env, missing = build_env(reader=read_keychain, existing=existing, allow_missing=args.allow_missing)`; if `missing` and not `allow_missing`: print to stderr `f"ERROR: missing required Keychain secrets: {', '.join(missing)} (load them then re-run; or --allow-missing for partial bring-up)"` and `return 1` (write NOTHING — no half `.env`). If `missing` and `allow_missing`: for each missing key print to stderr `f"WARNING: required secret {k} is MISSING from the written .env — daemon startup will fail until it is loaded"` (loud, per-key), then proceed. `write_env_file(path, env)`; print a SUMMARY of env-var NAMES written + count (NAMES ONLY, never values), note any optional-missing as a warning; `return 0`. `if __name__ == "__main__": raise SystemExit(main())`.
  — done when: `uv run mypy --strict scripts/inject_env.py` passes; running `main(["--slot","dev"])` (env path monkeypatched to a temp file pre-seeded with `ARTEMIS_DATA_ROOT=/opt/artemis`) with a fake reader returning all required values writes a `0600` `.env` that contains every required var, a generated `ARTEMIS_NTFY_TOPIC_SECRET`, AND the preserved `ARTEMIS_DATA_ROOT`; and `main` with a required item absent (no `--allow-missing`) returns `1` and writes no file.

- [ ] Task 2: Wire `inject_env.py` into `deploy.sh` — files: `/Users/artemis-build/artemis/scripts/deploy.sh` (modify) — insert a step in the promote flow AFTER the plists are rendered for the `--to` slot and BEFORE `launchctl bootstrap`: `echo "== inject secrets =="; uv run python scripts/inject_env.py --slot "$TO"` (use the existing `$TO`/`--to` variable). The injection runs in BOTH normal and `ARTEMIS_DEPLOY_DRYRUN=1` modes (it does not touch launchd — it only reads Keychain + writes the slot `.env`; in dry-run it still validates the secrets are loadable and the path resolves). A non-zero exit from `inject_env.py` ABORTS the deploy (the script already runs `set -euo pipefail`). Add a one-line comment: "secrets must exist before bootstrap; see M0-f / SECRETS-INVENTORY". — done when: `ARTEMIS_DEPLOY_DRYRUN=1 bash scripts/deploy.sh --from dev --to uat` shows the `== inject secrets ==` step running `inject_env.py` before the (skipped) bootstrap, and a forced `inject_env.py` failure (e.g. missing required secret on a box with no Keychain entries) aborts the deploy with non-zero exit.

- [ ] Task 3: Write the injection tests — files: `/Users/artemis-build/artemis/tests/test_inject_env.py` — typed pytest, fully off-hardware (no `security` call — inject a `fake_reader`):
  - **full write:** a `fake_reader` returning a value for every item → `build_env` returns all 6 env vars + an `ARTEMIS_NTFY_TOPIC_SECRET`; `write_env_file` to `tmp_path/.env` produces a file whose parsed contents equal the env dict + the header; `os.stat(path).st_mode & 0o777 == 0o600`.
  - **merge preserves non-secret config (no clobber):** pre-seed `tmp_path/.env` with `ARTEMIS_DATA_ROOT=/opt/artemis\nARTEMIS_RUNTIME_USER=owner\n`; run with a full `fake_reader` → the written file STILL contains `ARTEMIS_DATA_ROOT=/opt/artemis` and `ARTEMIS_RUNTIME_USER=owner` AND the 6 secrets + ntfy (existing config preserved, secrets overlaid).
  - **subprocess raises → fail closed:** monkeypatch `subprocess.run` to raise `FileNotFoundError` → `read_keychain("svc","acct")` returns `None` (no traceback escapes); with all items thus `None` and required, `main` (no `--allow-missing`) returns `1`.
  - **required missing → no file, exit 1:** a `fake_reader` returning `None` for `BRAVE_API_KEY` (required) → `main` (with the path monkeypatched to `tmp_path`) returns `1`, `missing` lists `BRAVE_API_KEY`, and NO `.env` is written.
  - **optional missing → skipped, still writes:** a `fake_reader` returning `None` for `JINA_API_KEY`/`DEEPSEEK_API_KEY` (optional) but all required present → returns `0`, the `.env` is written WITHOUT those keys.
  - **--allow-missing downgrades + warns:** the required-missing case WITH `--allow-missing` → returns `0`, writes the `.env` without the missing required key, AND a captured stderr line names the missing key (`"required secret BRAVE_API_KEY is MISSING"`).
  - **ntfy preserve / regenerate / invalid:** with an existing `.env` holding a VALID `ARTEMIS_NTFY_TOPIC_SECRET=<32 hex>`, a re-run CARRIES it forward unchanged; with no existing file, a fresh secret is generated (assert 32 hex chars); with an existing INVALID value (`ARTEMIS_NTFY_TOPIC_SECRET=not-hex`), it is REGENERATED to valid 32-hex (not carried forward).
  - **no secret value logged:** capture stdout/stderr of a successful `main`; assert NO secret VALUE substring appears (only env-var NAMES + counts); e.g. seed a sentinel value `"SENTINEL_SECRET_VALUE"` via the fake reader and assert it is absent from captured output.
  - **shell-injection safety (structural):** assert `read_keychain` builds a subprocess ARG LIST (no `shell=True`) — e.g. monkeypatch `subprocess.run` to capture the call and assert the first arg is a `list` and `shell` is not True.
  — done when: `uv run pytest -q tests/test_inject_env.py` passes AND `uv run mypy --strict scripts/inject_env.py tests/test_inject_env.py` passes.

- [ ] Task 4 (GATED — on-hardware, on the Mini): live Keychain read — files: (no new files) — with the owner Keychain pre-loaded (runbook bring-up step 3: S1/S2/S4/S5 minimum), run `uv run python scripts/inject_env.py --slot dev`; confirm it exits 0, writes `0600` `<slot>/.env` with the real values, and that `security find-generic-password -s artemis.search.brave -a api_key -w` returns the same value the file holds. Then re-run and confirm `ARTEMIS_NTFY_TOPIC_SECRET` is unchanged (preserve). — done when: on the Mini, the real Keychain read populates the slot `.env` at `0600` and a re-run preserves the ntfy secret; recorded in handoff.

## Wave plan
- **Wave 1:** [Task 1 (`inject_env.py`)] — the script both other tasks consume.
- **Wave 2:** [Task 2 (deploy.sh wiring), Task 3 (tests)] — independent of each other; both depend only on Task 1.
- **Wave 3:** [Task 4 (GATED on-hardware)] — needs the script + a real Keychain on the Mini.

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | /Users/artemis-build/artemis/scripts/inject_env.py, /Users/artemis-build/artemis/tests/test_inject_env.py |
| Modify | /Users/artemis-build/artemis/scripts/deploy.sh |
| Delete | (none) |
| Write (runtime, GATED) | the slot `.env` at the M0-a/M0-b-resolved `{ENV_FILE}` path (`0600`) — only when the script is RUN, not at build |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict scripts/inject_env.py tests/test_inject_env.py` | Type gate |
| `uv run ruff check . ; uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q tests/test_inject_env.py` | Test gate (fake reader; no macOS) |
| `ARTEMIS_DEPLOY_DRYRUN=1 bash scripts/deploy.sh --from dev --to uat` | Verify the inject step is wired into deploy |
| `uv run python scripts/inject_env.py --slot dev` (GATED, on-Mini) | Live Keychain → `.env` |
| `security find-generic-password -s <service> -a <account> -w` (GATED, on-Mini) | Live Keychain read (invoked by the script) |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | scripts/inject_env.py, scripts/deploy.sh, tests/test_inject_env.py |
| `git commit` | "feat: M0-f Keychain→slot-.env secrets-injection script + deploy.sh wiring" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_ENV_FILE` | (read indirectly) the script writes the file this points at; resolved via Settings/paths, not read as a var here |
| `ARTEMIS_DEPLOY_DRYRUN` | deploy.sh dry-run (the inject step still runs) |

### Network
| Action | Purpose |
|--------|---------|
| (none) | No network; `security` is a local Keychain read |

## Specialist Context
### Security
This script handles secrets — the load-bearing concerns: (1) the output `.env` is written `0600` (owner-only) via `os.open(..., 0o600)` + `os.chmod`, atomically (`os.replace`), in the owner-private slot dir behind FileVault — the accepted single-layer-at-rest posture for Medium-tier secrets (the HIGH-tier S3 refresh token is NOT here; it stays in SQLCipher). (2) **Secret VALUES are NEVER logged** — `read_keychain` captures stdout and never prints it; the summary logs env-var NAMES + counts only; a test asserts no value leaks to stdout/stderr. (3) **No shell injection** — `security` is invoked with an argument LIST (`subprocess.run([...])`), never `shell=True`. (4) `ARTEMIS_NTFY_TOPIC_SECRET` is **preserved across re-runs** (never silently rotated — rotation is the ntfy egress-capability break). (5) The script runs only in an interactive owner-runtime context (Keychain unlocked) — never from a LaunchDaemon (the persisted-`.env` design exists precisely to keep Keychain reads out of the boot path). **Planning security review (apex-spec-reviewer) — folded:** `os.fdopen`-backed 0600 write + accepted replace→chmod race (owner-only + FileVault); `read_keychain` fails closed on `FileNotFoundError`/`OSError` and DISCARDS stderr (no secret-adjacent leak); `--allow-missing` emits a per-key stderr WARNING and relies on `Settings` failing loud at daemon start; recovered ntfy secret is regex-validated (regenerate if corrupt); merge-not-clobber preserves slot config. **Accepted with reasoning:** the at-rest posture (Medium-tier secrets plaintext in a 0600 file behind FileVault; HIGH-tier S3 stays in SQLCipher) — single-layer-at-rest is the deliberate trade for sidestepping the launchd-keychain-at-boot footgun. [FLAG for apex-security (build-time re-check): confirm 0600 + fdopen + no-value/stderr-logging + arg-list subprocess + ntfy-preserve.] `cross_model_review: true` — secrets-handling spec; coding mode runs an independent second-model review before shipping (apex-governance).

### Performance
(negligible — six `security` subprocess calls + one small file write, run at bring-up/deploy only, never on a hot path)

### Accessibility
(none — a deploy/bring-up CLI tool, no frontend)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | scripts/inject_env.py | Type + docstring all exports; document the Keychain item map (= P1 resolution), the ntfy preserve-not-rotate rule, the `0600`/atomic-write/no-value-log invariants, and that the script is interactive-context-only (never a daemon) |
| Bring-up runbook | docs/bring-up/BRING-UP-RUNBOOK.md | ✅ updated in planning (this session): the secrets-loading step now invokes `inject_env.py`. **No build-time doc edit needed.** |
| Secrets inventory | docs/bring-up/SECRETS-INVENTORY.md | ✅ updated in planning (this session): P1 + P5 marked resolved (item map locked; mechanism = this script). **No build-time doc edit needed.** |

## Acceptance Criteria
- [ ] Run `uv run mypy --strict scripts/inject_env.py tests/test_inject_env.py` → verify: exit 0.
- [ ] Run `uv run pytest -q tests/test_inject_env.py` → verify: full write (`0600` + all required + generated ntfy), required-missing→no-file+exit-1, optional-missing→skip, `--allow-missing` downgrade, ntfy preserve-vs-generate, no-secret-value-in-output, arg-list-not-shell all pass.
- [ ] Run `uv run python -c "import ast,sys; ast.parse(open('scripts/inject_env.py').read()); print('ok')"` → verify: prints `ok` (the script parses).
- [ ] Run `ARTEMIS_DEPLOY_DRYRUN=1 bash scripts/deploy.sh --from dev --to uat` → verify: the `== inject secrets ==` step runs `inject_env.py` before the (skipped) `launchctl bootstrap`.
- [ ] Run `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.
- [ ] (GATED, on Mini) Task 4: real Keychain → `0600` slot `.env`; re-run preserves `ARTEMIS_NTFY_TOPIC_SECRET` → verify in handoff.

## Progress
_(Coding mode writes here — do not edit manually)_
