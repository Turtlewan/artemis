---
spec: m0-c-mlx-server
status: ready
token_profile: balanced
autonomy_level: L2
---

# Spec: M0-c — mlx-openai-server install + configure (the OpenAI-compatible model seam)

**Identity:** Installs and configures `mlx-openai-server` (model directory, ports, the OpenAI-compatible base-URL seam) and wires one config entry per logical model role into M0-a's roles.toml so the brain reaches models by role, not by physical endpoint.
→ why: see docs/technical/architecture/brain.md § "Inference + models" (mlx-openai-server, the OpenAI-compatible swap seam) · docs/technical/adr/ADR-001-stack.md (MLX runtime).

<!-- Split rule: single logical phase (provision the local inference runtime + its config seam), 3 files. Within the rule. -->

## Assumptions
- M0-a is complete: `config/roles.toml` exists with the 5 logical roles; the dev/uat/prod `mlx_port` values are 8040/8041/8042. → impact: Stop (this spec edits roles.toml + points adapters at the mlx base URL).
- M0-b is complete: `com.artemis.mlx.plist.template` exists with a `{MLX_LAUNCH_CMD}` placeholder this spec fills. → impact: Stop (the mlx daemon is launched by that plist using the command this spec defines).
- The runtime is **mlx-openai-server 1.8.1** (PyPI package `mlx-openai-server`; install via `uv`). It uses a **multi-model YAML config** (per-model `on_demand` + `on_demand_idle_timeout` for lazy/idle-unload), tool-calling via `--tool-call-parser qwen3`, and OpenAI `response_format` JSON-schema + Outlines for structured output. **Do NOT enable standard mlx-lm speculative decoding on Qwen3** (skipped-token bug #846) — Qwen3.6-27B uses native MTP (on-hardware). → impact: Caution. Live serve + throughput/RAM-fit on 48GB are confirmed on-hardware (GATED Tasks 4–5); the package/CLI/config facts above are pinned at 1.8.1.
- Model weights are downloaded to a per-slot-shared model cache, NOT committed to git, NOT inside any scope data dir (models are not owner data). → impact: Stop (models must live outside `owner-private/`).
- Actually downloading + serving models and confirming throughput/RAM fit on 48GB is an on-hardware step. → impact: Caution (M0-c writes config + install + a launch command deterministically; model pulls + a live `/v1/models` probe are GATED build-time tasks).

Simplicity check: considered running one mlx-openai-server per model — rejected; brain.md locks "one process, multiple resident models, on-demand load + idle-unload". A single server instance per slot serving multiple models by id is the decided, simpler design.

## Prerequisites
- Specs that must be complete first: M0-a (roles.toml, ports), M0-b (mlx plist template).
- Environment setup required: Apple Silicon mac with MLX support (the Mini). Install + config are deterministic; **pulling weights and a live serve probe are on-hardware (Tasks 4–5 GATED).**

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| /Users/artemis-build/artemis/scripts/install_mlx.sh | create | installs mlx-openai-server into the project venv + creates the model dir |
| /Users/artemis-build/artemis/config/mlx-models.yaml | create | mlx-openai-server 1.8.1 multi-model YAML config: model dir, host/port (from slot), served model list (logical-role models) with per-model `on_demand` + `on_demand_idle_timeout`; `tool_call_parser: qwen3` |
| /Users/artemis-build/artemis/config/roles.toml | modify | set the `endpoint` of `openai`-adapter roles to the slot mlx base URL `http://127.0.0.1:{mlx_port}/v1` |
| /Users/artemis-build/artemis/deploy/launchd/com.artemis.mlx.plist.template | modify | fill `{MLX_LAUNCH_CMD}` with the resolved mlx-openai-server launch command |
| /Users/artemis-build/artemis/src/artemis/model_client.py | create | thin typed helper returning an OpenAI-compatible base URL for a logical role from Settings (no SDK calls) |
| /Users/artemis-build/artemis/tests/test_model_client.py | create | tests role→base-URL resolution + adapter routing |

## Tasks
- [ ] Task 1: Write the mlx install script — files: `/Users/artemis-build/artemis/scripts/install_mlx.sh` — bash `set -euo pipefail`; `uv add "mlx-openai-server==1.8.1" pyyaml`; also install the ntfy binary via Homebrew (`brew install ntfy`; M0-b's ntfy plist consumes `/opt/homebrew/bin/ntfy` — confirm path on-hardware); create the model cache dir at `${ARTEMIS_MODEL_DIR:-/opt/artemis/models}` with `mkdir -p` + `chmod 755`; print the installed version (`uv run mlx-openai-server --version`). Does NOT download weights (that is Task 4, gated). — done when: `uv run python -c "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('mlx_openai_server') else 1)"` (or the confirmed module name) exits 0 on Apple Silicon.

- [ ] Task 2: Write the mlx-openai-server multi-model YAML config — files: `/Users/artemis-build/artemis/config/mlx-models.yaml` — keys: `model_dir: "${ARTEMIS_MODEL_DIR}"`, `host: "127.0.0.1"`, `port` (commented: rendered per-slot by the plist, not hard-coded here), `tool_call_parser: qwen3`, and a `models:` list — one entry per served logical-role model with `model_id` + `model_path` matching the model_ids in roles.toml (`Qwen3-4B-Instruct-2507`, `Qwen3-Embedding-0.6B`, `Qwen3-Reranker-0.6B`, `Qwen3.6-27B`; NOT the teacher — teacher is `claude-cli`, not mlx). Set `Qwen3-4B-Instruct-2507` `on_demand: false` (always-resident) and the rest `on_demand: true` + `on_demand_idle_timeout: <seconds>` (lazy/idle-unload) per brain.md. — done when: `yaml.safe_load` parses mlx-models.yaml and yields 4 model entries, exactly one with `on_demand: false`.

- [ ] Task 3: Wire the roles.toml endpoints + fill the mlx plist launch command — files: `/Users/artemis-build/artemis/config/roles.toml`, `/Users/artemis-build/artemis/deploy/launchd/com.artemis.mlx.plist.template` — in roles.toml set every `adapter = "openai"` role's `endpoint` to `http://127.0.0.1:{MLX_PORT}/v1` (keep `{MLX_PORT}` as a render placeholder so render_plists/Settings substitute per slot; if Settings needs a concrete value, resolve via the slot's `mlx_port`). In the mlx plist template replace `{MLX_LAUNCH_CMD}` with the absolute launch invocation: `{UV_BIN}` `run mlx-openai-server --config {REPO_DIR}/config/mlx-models.yaml --host 127.0.0.1 --port {MLX_PORT}` (mlx-openai-server 1.8.1 flags). — done when: `render_plists.py --slot dev` emits the mlx plist with a concrete port and no remaining `{MLX_LAUNCH_CMD}`.

- [ ] Task 4 (GATED — on-hardware): Download the responder + embedder weights — files: (no repo files; populates `${ARTEMIS_MODEL_DIR}`) — on the Mini: pull `Qwen3-4B-Instruct-2507` (MLX 4-bit) and `Qwen3-Embedding-0.6B` into the model dir (via the mlx-openai-server / huggingface mechanism the runtime expects). Build-time empirical (network + disk + Apple Silicon). — done when: the two model directories exist under `${ARTEMIS_MODEL_DIR}` and are loadable by the server.

- [ ] Task 5 (GATED — on-hardware): Serve + probe the OpenAI-compatible endpoint — files: (none) — on the Mini, start the mlx daemon (via the M0-b plist or directly), then `curl http://127.0.0.1:8040/v1/models` and a minimal `POST /v1/chat/completions` against the responder model. Build-time empirical. — done when: `/v1/models` lists the responder and a chat completion returns a non-empty response.

- [ ] Task 6: Write the model-client seam helper — files: `/Users/artemis-build/artemis/src/artemis/model_client.py` — typed pure helper `base_url_for_role(role: str, s: Settings) -> str` returning `s.roles[role].endpoint` for `openai` adapters and raising `NotImplementedError("teacher uses the claude-cli adapter; see M3")` for `claude-cli` adapters (the actual Claude-CLI adapter is a later milestone). Also `model_id_for_role(role, s) -> str`. NO network calls, NO OpenAI SDK dependency in M0 — this only resolves the seam. — done when: `uv run mypy --strict src` passes.

- [ ] Task 7: Write the seam tests — files: `/Users/artemis-build/artemis/tests/test_model_client.py` — assert `base_url_for_role("responder", s)` ends with `/v1`, `model_id_for_role("responder", s) == "Qwen3-4B-Instruct-2507"`, and `base_url_for_role("teacher", s)` raises `NotImplementedError`. — done when: `uv run pytest -q` passes.

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | /Users/artemis-build/artemis/scripts/install_mlx.sh, /Users/artemis-build/artemis/config/mlx-models.yaml, /Users/artemis-build/artemis/src/artemis/model_client.py, /Users/artemis-build/artemis/tests/test_model_client.py |
| Modify | /Users/artemis-build/artemis/config/roles.toml, /Users/artemis-build/artemis/deploy/launchd/com.artemis.mlx.plist.template |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv add "mlx-openai-server==1.8.1" pyyaml` | Install the local inference runtime (pinned) |
| `uv run mypy --strict src` | Type gate |
| `uv run pytest -q` | Test gate |
| `uv run python scripts/render_plists.py --slot dev` | Confirm mlx plist renders |
| `curl http://127.0.0.1:8040/v1/models` (GATED, on-Mini) | Probe the OpenAI-compatible endpoint |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | scripts/install_mlx.sh, config/mlx-models.yaml, config/roles.toml, deploy/launchd/com.artemis.mlx.plist.template, src/artemis/model_client.py, tests/test_model_client.py |
| `git commit` | "feat: M0-c mlx-openai-server install + config + role→endpoint seam" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_MODEL_DIR` | Where model weights are cached (outside scope data dirs) |

### Network
| Action | Purpose |
|--------|---------|
| `uv add mlx-openai-server` | Package install (PyPI) |
| model weight download (GATED) | Pull MLX model weights on the Mini |

## Specialist Context
### Security
Model weights are not owner data → live outside `owner-private/`. The mlx server binds `127.0.0.1` only. The teacher role deliberately is NOT served by mlx (it routes to the Claude CLI adapter) — keeping sensitive-vs-cloud routing a config concern, not an mlx concern.

### Performance
brain.md: keep the responder (`Qwen3-4B`) resident/warm; lazy-load the rest. Encoded as `resident` flags in mlx.toml. RAM-fit on 48GB is a GATED on-hardware verification (Task 5).

### Accessibility
(none — no frontend)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | src/artemis/model_client.py | Type + docstring all exports |
| Config comments | config/mlx-models.yaml | Document resident vs lazy + that teacher is not served here |

## Acceptance Criteria
- [ ] Run `bash scripts/install_mlx.sh` (on Apple Silicon) → verify: the mlx-openai-server module imports and `${ARTEMIS_MODEL_DIR}` exists.
- [ ] Run `uv run python -c "import yaml; d=yaml.safe_load(open('config/mlx-models.yaml')); print(sum(1 for m in d['models'] if not m.get('on_demand', True)))"` → verify: prints `1`.
- [ ] Run `uv run python scripts/render_plists.py --slot dev --out-dir /tmp/plists` → verify: the mlx plist contains the concrete launch command and port `8040`, no `{` remaining.
- [ ] Run `uv run mypy --strict src && uv run pytest -q` → verify: both exit 0; teacher-role test asserts `NotImplementedError`.
- [ ] (GATED, on Mini) Start the mlx daemon, `curl http://127.0.0.1:8040/v1/models` → verify: responder model id listed; a chat completion returns non-empty.

## Progress
_(Coding mode writes here — do not edit manually)_
