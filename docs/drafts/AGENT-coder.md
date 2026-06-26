---
spec: AGENT-coder
status: draft
cross_model_review: true
token_profile: balanced
autonomy_level: L2
---

# Spec: AGENT-coder — embedded OpenHands coding subsystem (workspace seam + planner + GATE handoff)

**Identity:** Embeds the V1 `openhands-sdk` as Artemis's sandboxed coder behind Artemis-owned layers
(ADR-031 D + Refinement 2026-06-26): the workspace-abstraction seam (LocalWorkspace on Windows-dev /
DockerWorkspace on Mac), the planner/coder split, and a custom `ConfirmationPolicy` that defers
`WAITING_FOR_CONFIRMATION` to the Artemis `AuthorityGate`/inbox.
<!-- → why: docs/technical/adr/ADR-031-...md (D coding subsystem + Refinement 2026-06-26) + docs/research/2026-06-26-openhands-windows/README.md + docs/drafts/AGENT-engine-design.md (seam #5). -->

## Assumptions
<!-- Coding mode verifies each item against the codebase before executing. -->
- Bind to V1 `openhands-sdk` (+ `openhands-tools`), embeddable in-process: `from openhands.sdk import LLM, Agent, Conversation, Tool` → `Conversation(agent, workspace).send_message(...).run()` (research README §1). NOT the legacy `openhands-ai` app. Verify the exact current import surface + version at build (it is young/moving — the build MUST confirm the API against the installed version, not assume). → impact: Stop (wrong package/API).
- `openhands-sdk` is a NEW heavy dependency in the `[agentic]` optional group (Python ≥3.12 — satisfied at 3.12.10). Verify name/maintenance at the gate. → impact: Stop.
- **Windows path = local runtime + LocalWorkspace, NOT Docker** (research README §2/§3: Docker needs ~12GB + WSL2, mutually exclusive with Ollama on 8GB). The actual command isolation is delegated to AGENT-rung2's sandbox (restricted-token/Job-Object) — this spec binds to the workspace ABSTRACTION so Windows-dev (LocalWorkspace) vs Mac (DockerWorkspace/remote) is a config-only swap. → impact: Stop (hardwiring Docker breaks the dev box; hardwiring local-no-isolation breaks the security model — go through the workspace seam + rung2 sandbox).
- ⚠️ Native-Windows OpenHands is EXPERIMENTAL (research README §6: PowerShell 7 + .NET + pythonnet; browser tool unsupported; CLI runtime bash-based). The build validates the embed + Artemis layers on the dev box (LocalWorkspace) and defers full sandboxed-runtime parity to the Mac (DockerWorkspace) — consistent with ADR-031 G Mac-gating. Tests run against a FAKE OpenHands conversation (no live coding run on the dev box in this spec). → impact: Caution (acceptance is fake-driven; live embed is an exercise/Mac step).
- HITL = a custom OpenHands `ConfirmationPolicy` + `SecurityAnalyzer` (research README §4): the agent's `WAITING_FOR_CONFIRMATION` defers to the Artemis `AuthorityGate.authorize` + `OwnerInbox.ask` — no change to OpenHands tool executors. → impact: Stop (bypassing the policy = ungated coder actions).
- The coder backend comes from `CoderRouter.select(...)` (AGENT-coder-router) → an OpenHands `LLM`. The planner (Claude/Opus) is the Artemis-side strong model that produces the plan; OpenHands implements. Plan/code split is a locked design principle. → impact: Caution.
- Two persistence layers stay separate (ADR-031 D): OpenHands `conversation_id`/file-store = in-build state; the Artemis `CheckpointStore` (AGENT-checkpoint) = task-level plan-of-builds. The coder reports build results back to the spine; it does not write the Artemis checkpoint itself. → impact: Caution.

Simplicity check: considered using OpenHands as the top-level harness — rejected (ADR-031 alternatives): Artemis owns planner/inbox/GATE/router; OpenHands is embedded as only the sandboxed executor behind those layers, swap-able by replacing this module.

## Prerequisites
- Specs that must be complete first: **AGENT-types**, **AGENT-spine** (the executor that invokes the coder as a capability), **AGENT-inbox** + **AGENT-authority** (the GATE/ask seam the ConfirmationPolicy defers to), **AGENT-coder-router** (backend selection). (AGENT-rung2 provides the Windows sandbox the LocalWorkspace runs inside — declared as a runtime companion; this spec binds the workspace seam, rung2 wraps it.)
- Environment setup required: `openhands-sdk` (+ `openhands-tools`) in the `[agentic]` optional group.

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| `pyproject.toml` | modify | Add `openhands-sdk` (+ tools) to `[project.optional-dependencies] agentic`. |
| `src/artemis/agentic/coder/workspace.py` | create | Workspace-abstraction seam: `build_workspace(config)` → LocalWorkspace (Windows) / DockerWorkspace|remote (Mac), config-only swap. |
| `src/artemis/agentic/coder/subsystem.py` | create | `CodingSubsystem`: builds the OpenHands `Agent`/`Conversation` from router+workspace, plugs the Artemis `ConfirmationPolicy` (→ AuthorityGate/inbox), runs a coding task, returns a build result. |
| `tests/test_agent_coder.py` | create | fake-OpenHands: confirmation defers to the gate; workspace seam selects by config; backend from router; result surfaced; NO live run. |

## Exact changes
- `workspace.py`: `WorkspaceConfig` (kind = `local`|`docker`|`remote`, `root`/connection); `build_workspace(cfg)` returns the matching OpenHands workspace object. Windows default = `local` (rung2 sandbox wraps it); Mac default = `docker`. The ONLY platform divergence is here.
- `subsystem.py`: `ArtemisConfirmationPolicy` (subclasses/implements the OpenHands `ConfirmationPolicy` interface) whose decision calls `AuthorityGate.authorize(...)`; on `needs_approval` it raises/holds via `OwnerInbox.ask` (deferring to the single Artemis approval surface). `CodingSubsystem.run(task_spec) -> BuildResult` builds `Agent` with `LLM` from `CoderRouter.select(...)`, the `SecurityAnalyzer`, the `ArtemisConfirmationPolicy`, and `build_workspace(...)`, drives the conversation, and returns a structured result (files changed / status). All OpenHands calls behind a thin adapter so the test can inject a fake conversation.

## Tasks
- [ ] Task 1: Add `openhands-sdk`(+tools) to the `[agentic]` extra; pin the workspace seam (`workspace.py`) with config-only local/docker/remote selection. — files: `pyproject.toml`, `src/artemis/agentic/coder/workspace.py` — done when: `uv sync --extra agentic` resolves; `build_workspace` returns a LocalWorkspace for `kind="local"` and the Docker/remote variant for the others (the latter may be import-guarded/Mac-gated); the API is confirmed against the installed `openhands-sdk` version (not assumed); `uv run mypy` clean.
- [ ] Task 2: Implement `ArtemisConfirmationPolicy` + `CodingSubsystem.run` behind a fake-able adapter; wire router + workspace + gate/inbox. — files: `src/artemis/agentic/coder/subsystem.py` — done when: a coding run with a fake OpenHands conversation defers every `WAITING_FOR_CONFIRMATION` to `AuthorityGate.authorize` (and `OwnerInbox.ask` on needs_approval); the backend `LLM` comes from `CoderRouter.select`; a `BuildResult` (status + files) is returned; NO live OpenHands/network call in the test.
- [ ] Task 3: Tests. — files: `tests/test_agent_coder.py` — done when: confirmation-defers-to-gate, workspace-selected-by-config, backend-from-router, result-surfaced, and no-live-run assertions pass under `uv run pytest -q`.

## Wave plan
Wave 1: [Task 1] | Wave 2: [Task 2] | Wave 3: [Task 3]

## Permissions
The following actions will run autonomously during build. Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | `src/artemis/agentic/coder/workspace.py`, `src/artemis/agentic/coder/subsystem.py`, `tests/test_agent_coder.py` |
| Modify | `pyproject.toml` |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv add --optional agentic openhands-sdk openhands-tools` (or pyproject edit + `uv lock`) | Add the embedded coder to the optional group. |
| `uv sync --extra agentic` | Install the extra for build/test. |
| `uv run mypy` | Full-project type check. |
| `uv run ruff check . && uv run ruff format --check .` | Lint + format gate. |
| `uv run pytest -q` | Full test suite (fake OpenHands; no live run). |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | The four files above, by name (incl. `uv.lock`). |
| `git commit` | "feat: AGENT-coder embedded OpenHands coding subsystem + workspace seam + GATE handoff (ADR-031 D)" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| (coder backend keys, via router) | Supplied through `CoderRouter`/LiteLLM env-refs; this spec does not read keys directly. |

### Network
| Action | Purpose |
|--------|---------|
| Package index | `uv` resolves `openhands-sdk` (heavy) into the `[agentic]` extra (one-time). No live coding run on the dev box in this spec. |

## Specialist Context
### Security
`cross_model_review: true` — embeds an external agent SDK that runs code. Reviewer confirms: (1) every OpenHands `WAITING_FOR_CONFIRMATION` defers to the Artemis `AuthorityGate`/inbox (no ungated coder action; the ConfirmationPolicy is the only decision path); (2) on Windows the coder runs in the local runtime that AGENT-rung2's restricted-token/Job-Object sandbox confines — never an unsandboxed local run in prod use; (3) the workspace seam is the sole platform divergence (Mac parity via DockerWorkspace); (4) coder backends are non-sensitive/cloud-allowed by design (ADR-031 D) and keys are env-refs; (5) tests use a fake conversation — no live egress on the dev box. **Note the experimental-Windows risk (ADR-031 Refinement) — full sandbox parity is a Mac-gated validation.**

### Performance
(none in-spec — footprint managed by using the local runtime, not Docker, on the 8GB box.)

### Accessibility
(none — UI-building tasks' visual-review modality is a downstream concern, ADR-031 Refinement (b).)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | `src/artemis/agentic/coder/{workspace,subsystem}.py` | Docstrings: V1 SDK embed, workspace-parity seam, ConfirmationPolicy→GATE, plan/code split. |
| Overview | docs/technical/architecture/overview.md | Add the embedded coding subsystem to Capabilities on archive. |
| Product | docs (runbook) | A short note: the dev box validates the embed (fake/local); full sandboxed coder runs on the Mac (or via Docker workspace). |
| ADR | (none) | ADR-031 D + Refinement 2026-06-26 record the decision. |

## Acceptance Criteria
- [ ] Confirmation defers to the gate → verify: every fake `WAITING_FOR_CONFIRMATION` routes through `AuthorityGate.authorize` (+ `OwnerInbox.ask` on needs_approval); no coder action runs ungated.
- [ ] Workspace parity seam → verify: `build_workspace(kind="local")` → LocalWorkspace; `kind="docker"/"remote"` → the Mac variant (import-guarded ok); platform divergence lives only here.
- [ ] Backend from router → verify: the OpenHands `LLM` is configured from `CoderRouter.select(...)`.
- [ ] Result surfaced + no live run → verify: a fake coding run returns a `BuildResult`; no network/live OpenHands call occurs in tests.
- [ ] API confirmed against installed version → verify: the import surface matches the installed `openhands-sdk` (build confirms, does not assume).
- [ ] Whole project clean → verify: `uv run mypy`, `uv run ruff check . && uv run ruff format --check .`, `uv run pytest -q` all pass.

## Progress
_(Coding mode writes here — do not edit manually)_
