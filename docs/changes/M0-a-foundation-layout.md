---
spec: m0-a-foundation-layout
status: ready
token_profile: balanced
autonomy_level: L2
---
<!-- amended 2026-06-11 per m0-m1-foundation-brain.md BLOCKs B1, B8 -->
<!-- amended 2026-06-11 per Decision D4/D5 (contracts.md Seam 10) -->

# Spec: M0-a — Foundation layout (repo, per-scope encrypted data dir, typed config, dev/UAT/PROD slots)

**Identity:** Scaffolds the Artemis Python repo skeleton, the consolidated backup-ready per-scope-encrypted data directory structure (structure + setup script, NO data/engines), the typed `pydantic-settings` config system including the ModelPort logical-role→endpoint map, and the dev/UAT/PROD slot directories.
→ why: see docs/technical/adr/ADR-002-deployment-method.md (slots, backups, native) · docs/technical/architecture/data-model.md (scope-partition map) · docs/technical/adr/ADR-001-stack.md (Python/uv stack).

<!-- Split rule: this spec creates a repo skeleton + data-dir + config in ONE logical phase (filesystem foundation). It exceeds 3 files because it bootstraps a new repo; this is the unavoidable atomic "create the project" unit and cannot be meaningfully sub-split without leaving a non-compiling repo. Flagged per rules. -->

## Assumptions
- The repo lives at `~/artemis` on the Mac Mini, checked out under the build-agent macOS user account (set up in M0-e). The owner-runtime user runs the services. → impact: Caution (paths in plists/scripts derive from this; if wrong, fix all `$HOME` references).
- `~` for the build-agent user resolves to `/Users/artemis-build`; runtime data lives under a fixed absolute root `/opt/artemis` writable by the runtime service user. → impact: Stop (the data root must NOT be inside a user home that the build agent can read; see M0-e isolation). DECISION: the runtime data root is `/opt/artemis` (chosen over a runtime-user home like `/Users/artemis/Library/Application Support/Artemis` precisely because it is outside any user home, so the build-agent user cannot read it; all five M0 specs inherit `/opt/artemis`).
- Python 3.12+ available via `uv`-managed toolchain (uv installs the interpreter). → impact: Stop (whole stack assumes this).
- No SQLCipher/sqlite-vec/LanceDB engine code is written in M0 — only directories + config keys + empty marker files. → impact: Stop (M0 scope is structure-only; engines are M3/M4).
- macOS 26 target (per locked fork). → impact: Low for M0-a (only matters for M0-b/M0-e sandbox).

Simplicity check: considered a single flat `data/` dir with logical (row-level) scope separation instead of physical per-scope directories — rejected because the crypto wall (data-model.md, ADR-004) is *structural* (one SQLCipher file per scope), so the directory layout must mirror it from day one. This is the minimum structure that honours the locked wall.

## Prerequisites
- Specs that must be complete first: none (this is the first M0 spec; M0-b/c/d/e depend on this).
- Environment setup required: `uv` installed on the Mini (the deploy bootstrap installs it; see Commands). A macOS host (the Mini); deterministic on any Apple Silicon mac, no on-hardware empirical gate.

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| /Users/artemis-build/artemis/pyproject.toml | create | uv project; deps: `fastapi`, `pydantic`, `pydantic-settings`, `uvicorn[standard]`; dev group: `ruff`, `mypy`, `pytest`, `pytest-asyncio` (ADR-015: the I/O ports are async, so memory/retriever/router/ingestion tests are `async def`) |
| /Users/artemis-build/artemis/.python-version | create | pin `3.12` |
| /Users/artemis-build/artemis/.gitignore | create | ignore `.venv/`, `__pycache__/`, `*.db`, `*.sqlite*`, `.env`, `.env.*`, keep `!.env.*.example`, local data roots — B1: `.env` alone does NOT match `config/.env.dev`; `.env.*` is required |
| /Users/artemis-build/artemis/src/artemis/__init__.py | create | package marker |
| /Users/artemis-build/artemis/src/artemis/config.py | create | typed `Settings` (pydantic-settings) incl. slot, data-root, ports, ModelPort role→endpoint map |
| /Users/artemis-build/artemis/src/artemis/paths.py | create | pure functions resolving per-slot + per-scope data paths from `Settings` |
| /Users/artemis-build/artemis/config/roles.toml | create | logical-model-role → endpoint/model-id map (the ModelPort swap seam, consumed by config.py) |
| /Users/artemis-build/artemis/config/.env.dev.example | create | example env for the dev slot (ports, data root, slot name) |
| /Users/artemis-build/artemis/config/.env.uat.example | create | example env for the UAT slot |
| /Users/artemis-build/artemis/config/.env.prod.example | create | example env for the PROD slot |
| /Users/artemis-build/artemis/scripts/setup_data_dir.sh | create | idempotent script that creates the per-slot, per-scope data directory tree + marker files |
| /Users/artemis-build/artemis/tests/test_config.py | create | tests Settings loads, role map parses, paths resolve per slot/scope |
| /Users/artemis-build/artemis/tests/test_paths.py | create | tests path-resolution functions |

## Tasks
- [ ] Task 1: Initialise the uv project skeleton — files: `/Users/artemis-build/artemis/pyproject.toml`, `/Users/artemis-build/artemis/.python-version`, `/Users/artemis-build/artemis/.gitignore`, `/Users/artemis-build/artemis/src/artemis/__init__.py` — pyproject uses src-layout (`[tool.hatch.build.targets.wheel] packages = ["src/artemis"]`), `[tool.mypy] plugins = ["pydantic.mypy"]` + `strict = true`, runtime deps `fastapi`, `pydantic>=2`, `pydantic-settings`, `uvicorn[standard]`, dev tools in `[dependency-groups] dev` (PEP 735, so plain `uv sync` installs them — not `[project.optional-dependencies]`): `ruff`, `mypy`, `pytest`, `pytest-asyncio` (ADR-015 async I/O ports → async tests across the corpus). `.gitignore` must include EXACTLY: `.env`, `.env.*`, `!.env.*.example` (B1: `.env` alone does NOT match `config/.env.dev`; `.env.*` + negation-exception is required so slot secret files are never committable but examples are tracked). Also add `[tool.pytest.ini_options]` with `markers = ["integration: ..."]` (so `--strict-markers` doesn't fail and `pytest -m integration` exits 0 (not 5) when no integration tests exist — B5) AND `asyncio_mode = "auto"` (ADR-015: `async def test_*` functions run without a per-test marker; pytest-asyncio is in the dev group). — done when: `uv sync` succeeds; `uv run python -c "import artemis"` exits 0; `git check-ignore config/.env.dev` exits 0 (file is ignored); `git check-ignore config/.env.dev.example` exits 1 (example is NOT ignored).

- [ ] Task 2: Define the ModelPort logical-role→endpoint map — files: `/Users/artemis-build/artemis/config/roles.toml` — one table per logical role with keys `endpoint` (OpenAI-compatible base URL or the literal `claude-cli` for the teacher adapter), `model_id`, `adapter` (`openai` | `claude-cli`). Seed exactly these roles from brain.md: `responder` (endpoint = local mlx-openai-server base URL, model `Qwen3-4B-Instruct-2507`, adapter `openai`), `teacher` (endpoint `claude-cli`, adapter `claude-cli`, model `claude-opus`), `embedder` (local mlx base URL, model `Qwen3-Embedding-0.6B`, adapter `openai`), `reranker` (local mlx base URL, model `Qwen3-Reranker-0.6B`, adapter `openai`), `sensitive_reasoner` (local mlx base URL, model `Qwen3.6-27B`, adapter `openai` — local heavy: sensitive reasoning + sensitive memory extraction, lazy). Each value commented `# logical role — physical endpoint is the swap seam`. — done when: `tomllib.load` parses the file and yields all 5 roles with the 3 required keys each (asserted in Task 6).

- [ ] Task 3: Write the typed config system — files: `/Users/artemis-build/artemis/src/artemis/config.py` — a `pydantic-settings` `Settings(BaseSettings)` with `env_prefix="ARTEMIS_"` and `env_file` taken from `ARTEMIS_ENV_FILE`; fields: `slot: Literal["dev","uat","prod"]`, `data_root: Path`, `brain_port: int`, `mlx_port: int`, `ntfy_port: int`, `audio_sidecar_port: int`. Add a typed `ModelRole` pydantic model (`endpoint: str`, `model_id: str`, `adapter: Literal["openai","claude-cli"]`) and a `roles: dict[str, ModelRole]` field populated by a validator that reads `config/roles.toml` via `tomllib` (path = `roles_file` field, default `config/roles.toml`). Provide `@lru_cache get_settings() -> Settings` with the single localized `# type: ignore[call-arg]`. No secrets are read here (SQLCipher keys come from Keychain at M2, not env). — done when: `uv run mypy --strict src` passes and `get_settings()` returns a `Settings` with a populated `roles` dict under a test env file.

- [ ] Task 4: Write per-slot/per-scope path resolution — files: `/Users/artemis-build/artemis/src/artemis/paths.py` — pure typed functions: `slot_root(s: Settings) -> Path` = `s.data_root / s.slot`; `scope_dir(s: Settings, scope: str) -> Path` where `scope` ∈ `{"owner-private","general"}` or `f"guest-{person_id}"` — returns the **parent** `<data_root>/<slot>/<scope>/` directly (Decision D4 — this is where SQLCipher DBs live); subdirs per scope: `memory/` (SQLCipher memory DB, M4), `relational/` (SQLCipher operational DBs, later), `keys/` (key-reference metadata only, never the key itself). Also add `vault_dir(s: Settings, scope: str) -> Path` = `scope_dir(s, scope) / "vault/"` (Decision D4 — the APFS encrypted-volume mount point; holds LanceDB only; the `vault/` segment is created as a mount-point directory by the setup script). Also `backups_dir(s)` = `slot_root / "backups"`, `logs_dir(s)` = `slot_root / "logs"`, and `env_file(s: Settings) -> Path` = `Path("config") / f".env.{s.slot}"` (B9: the canonical single-source-of-truth resolver for the slot `.env` path — this is the one expression `render_plists.py`'s `{ENV_FILE}` and `inject_env.py` BOTH call; eliminates the three contradictory candidates in B9). Functions return paths only; they do NOT create directories (the setup script does). Reject unknown scope strings with `ValueError`. NOTE (D4): SQLCipher DBs (memory, GATE, modules, telemetry) open at `scope_dir(s, scope)` directly — NO `vault/` segment. The `vault/` sub-path is exclusively the LanceDB APFS encrypted-volume mount point (M2-a); double-encryption is intentionally avoided. — done when: `uv run mypy --strict src` passes; `env_file(Settings(slot="dev", ...))` returns `Path("config/.env.dev")`; `vault_dir(s, "owner-private")` returns `scope_dir(s, "owner-private") / "vault"`; functions return the documented paths in `test_paths.py`. (B8: `Settings` declares NO secret fields — `BRAVE_API_KEY` etc. are NOT `Settings` fields; secrets are handled by `inject_env.py` writing the `.env` file before daemon start; daemons validate secrets via their own service-layer startup checks, not via `Settings` construction. This avoids the bootstrap circularity where `inject_env.py`'s `get_settings()` call would fail before injection.)

- [ ] Task 5: Write the idempotent data-dir setup script — files: `/Users/artemis-build/artemis/scripts/setup_data_dir.sh` — bash, `set -euo pipefail`; takes `--slot {dev|uat|prod}` and `--data-root <path>` (defaults from env `ARTEMIS_DATA_ROOT`); creates, with `mkdir -p` and `chmod 700`: `<root>/<slot>/{owner-private,general}/{memory,relational,keys}` (no `vectors/` — the SQLCipher stores live directly at `scope_dir`; the LanceDB corpus is at `scope_dir/vault/` on the encrypted volume, D4), `<root>/<slot>/{backups,logs}`; also creates the `vault/` mount-point directory under each owner scope with `mkdir -p` + `chmod 700`: `<root>/<slot>/{owner-private,general}/vault/` (Decision D4: this is the APFS encrypted-volume mount point; it is an empty dir on disk until the M2 broker mounts the volume here; the script creates it so `hdiutil attach` / `diskutil` has a valid mount target); writes a `.artemis-scope` marker file in each scope dir containing the scope name; writes `<root>/<slot>/LAYOUT.md` documenting the tree (generated, not hand-edited). Idempotent: re-running changes nothing and exits 0. Does NOT create any guest scope dir (guests are provisioned at runtime in a later milestone). Prints the created tree. — done when: running it twice for `--slot dev` produces an identical tree with `700` perms and exits 0 both times; `<root>/dev/owner-private/vault/` exists as an empty directory with `700` perms (asserted in Acceptance).

- [ ] Task 6: Write config + path tests — files: `/Users/artemis-build/artemis/tests/test_config.py`, `/Users/artemis-build/artemis/tests/test_paths.py` — test_config: writes a temp `.env` + temp `roles.toml`, sets `ARTEMIS_ENV_FILE`/`ARTEMIS_ROLES_FILE`, asserts all 5 roles load with adapter values from the enum, asserts the `teacher` role adapter is `claude-cli` and `responder` is `openai`; test_paths: asserts `scope_dir` for `owner-private` and a `guest-<id>` resolve correctly, asserts unknown scope raises `ValueError`, asserts `vault_dir(s, "owner-private")` == `scope_dir(s, "owner-private") / "vault"` (D4: the encrypted-volume mount point is always `scope_dir/vault/`). NOTE: do NOT assert a `vectors/` subdir — that subdir is no longer created (D4; LanceDB lives at `vault/` on the encrypted volume, not at a plain `vectors/` dir). — done when: `uv run pytest -q` passes.

- [ ] Task 7: Write the example env files — files: `/Users/artemis-build/artemis/config/.env.dev.example`, `/Users/artemis-build/artemis/config/.env.uat.example`, `/Users/artemis-build/artemis/config/.env.prod.example` — each sets `ARTEMIS_SLOT`, `ARTEMIS_DATA_ROOT`, and distinct ports per slot. Port plan (so the three slots never collide): dev brain `8030`/mlx `8040`/ntfy `8050`/audio `8060`; uat brain `8031`/mlx `8041`/ntfy `8051`/audio `8061`; prod brain `8032`/mlx `8042`/ntfy `8052`/audio `8062`. Also add `ARTEMIS_WORKTREE_ROOT` (path to the slot's own git worktree, Decision D5 — each slot runs from its own pinned worktree, e.g. `/Users/artemis-build/artemis-dev`, `/Users/artemis-build/artemis-uat`, `/Users/artemis-build/artemis-prod`; the primary clone at `/Users/artemis-build/artemis` is dev's worktree and also the bare clone origin for adding UAT/PROD worktrees via `git worktree add`). Add a `worktree_root: Path` field to `Settings` with env `ARTEMIS_WORKTREE_ROOT`, defaulting to the repo root (so off-hardware dev needs no change). — done when: all three files exist and `cp config/.env.dev.example config/.env.dev` then `ARTEMIS_ENV_FILE=config/.env.dev uv run python -c "from artemis.config import get_settings; print(get_settings().slot)"` prints `dev`.

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | /Users/artemis-build/artemis/pyproject.toml, /Users/artemis-build/artemis/.python-version, /Users/artemis-build/artemis/.gitignore, /Users/artemis-build/artemis/src/artemis/__init__.py, /Users/artemis-build/artemis/src/artemis/config.py, /Users/artemis-build/artemis/src/artemis/paths.py, /Users/artemis-build/artemis/config/roles.toml, /Users/artemis-build/artemis/config/.env.{dev,uat,prod}.example, /Users/artemis-build/artemis/scripts/setup_data_dir.sh, /Users/artemis-build/artemis/tests/test_config.py, /Users/artemis-build/artemis/tests/test_paths.py |
| Modify | (none) |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv sync` | Install deps + dev group |
| `uv run mypy --strict src` | Type gate |
| `uv run ruff check . ; uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q` | Test gate |
| `bash scripts/setup_data_dir.sh --slot dev --data-root <tmp>` | Build the per-scope data tree |
| `chmod 700 <dirs>` | Restrict data-dir perms (inside the script) |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | pyproject.toml, .python-version, .gitignore, src/artemis/**, config/**, scripts/**, tests/** |
| `git commit` | "feat: M0-a foundation layout — repo skeleton, per-scope data dir, typed config, slots" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_ENV_FILE` | Selects which slot `.env` Settings loads |
| `ARTEMIS_DATA_ROOT` | Root of the per-slot/per-scope data tree |
| `ARTEMIS_ROLES_FILE` | Path to roles.toml (test override) |

### Network
| Action | Purpose |
|--------|---------|
| `uv sync` | Package installation (PyPI) |

## Specialist Context
### Security
The data-dir layout is the physical form of the crypto wall (data-model.md scope-partition map). M0-a creates the *directories* with `700` perms only; it writes NO keys and NO data and does NOT initialise any SQLCipher file (that is M2/M4, owner-runtime-user only). The build-agent user must not be the owner of the runtime data root (enforced in M0-e). [FLAG for apex-security at M2: confirm directory ownership/ACLs so the build-agent user cannot read `owner-private/`.]

### Performance
(none)

### Accessibility
(none — no frontend)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | src/artemis/config.py, src/artemis/paths.py | Type + docstring all exports |
| Generated | <data-root>/<slot>/LAYOUT.md | Setup script writes the tree doc |

## Acceptance Criteria
- [ ] Run `uv sync` → verify: exit 0 and `.venv` populated with fastapi + dev tools.
- [ ] Run `uv run mypy --strict src` → verify: exit 0, no errors.
- [ ] Run `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.
- [ ] Run `uv run pytest -q` → verify: all tests pass.
- [ ] Run `bash scripts/setup_data_dir.sh --slot dev --data-root /tmp/artemis-test` twice → verify: `/tmp/artemis-test/dev/owner-private/memory` exists, perms `700` (`stat -f '%Lp'` returns `700`), `.artemis-scope` files present, `/tmp/artemis-test/dev/owner-private/vault/` exists as an empty dir with `700` perms (D4 mount-point), second run exits 0 with no diff.
- [ ] Run `ARTEMIS_ENV_FILE=config/.env.dev uv run python -c "from artemis.config import get_settings; s=get_settings(); print(s.slot, s.roles['teacher'].adapter, s.roles['responder'].endpoint)"` → verify: prints `dev claude-cli <a base URL>`.

## Progress
_(Coding mode writes here — do not edit manually)_
