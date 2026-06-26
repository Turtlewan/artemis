# ADR-031 — Agentic runtime & host computer-use: unified executor, capability ladder, authority model, coding subsystem, privacy concessions

- **Status:** **Accepted** — 2026-06-25 (owner + planning).
- **Date:** 2026-06-25
- **Deciders:** owner + planning
- **Refines:** ADR-024 (M9 Task Executor — extended scope to host computer-use, capability ladder, coding subsystem) · ADR-022 (model/runtime — two explicit exceptions to the privacy wall: Fork 2 + Fork 3 below). Does **NOT** supersede either; all decisions in ADR-024 and ADR-022 remain in force.
- **Research basis:** `docs/research/2026-06-25-agentic-harnesses/` (broad survey: README, orchestration-core, orchestration-alt, host-computer-use, reliability-spine; coding-SDK deep-dive: autonomous-coding, coding-sdk-oss, coding-sdk-openhands, coding-sdk-vendor, coding-harness-recommendation).
- **Relates:** ADR-021 (cross-module reactions — distinct event-triggered path; reactions fire executor tasks) · ADR-012 (GATE — reused as the external-effect interrupt) · ADR-029 (sensitivity gate — the local classifier used by the sensitive-screen pre-filter) · ADR-028 (spatial navigation — agentic UI folds into the locked travel-zoom map).

---

## Context

ADR-024 specified a general `plan→act→verify` Task Executor (M9), model-agnostic, post-spoke-wave. ADR-022 established the sensitivity-routed model runtime, the Pydantic AI + checkpoint harness composition, and the GEPA self-improvement borrowing from Hermes. Neither addressed:

- **Host computer-use** — Artemis reaching out to the desktop/OS beyond Artemis's own tool stack (screen capture, app control, command execution, autonomous host-watch);
- the **graduated capability ladder** that governs which powers are available and when;
- the **authority / sandbox model** for those powers;
- the **coding subsystem** as a concrete, embedded-harness first class capability;
- the **privacy status** of two specific subsystems that deliberately relax the ADR-022 privacy wall.

A dedicated design session (owner-led, 2026-06-25) resolved all of the above. This ADR records those decisions.

---

## Decision

### A — Architecture shape: one unified runtime

The M9 executor (ADR-024) is **the single engine** for all agentic activity. Host computer-use is not a separate subsystem; it is **a capability the executor reaches via the gated tool stack**. The architecture is:

- **Recipes** = saved executor plans (ADR-024 atomic composable primitives).
- **Reactions** (ADR-021) = events that fire executor tasks.
- **"Autonomous agent"** = the executor running in unattended mode (ADR-024 supervised/unattended flag).

Reliability, GATE, task-memory, and the agent-inbox are built once on the executor and shared by all front-doors. No parallel agentic runtime is introduced.

---

### B — Capability ladder: Rung 0–4 (end-state), built bottom-up

| Rung | Power | Risk |
|---|---|---|
| 0 | Read-only host introspection | ~none |
| 1 | Reversible file ops (workspace-confined, trash-not-delete) | Low |
| 2 | Command/script execution (sandboxed) | Medium |
| 3 | App/desktop control (vision-action loop) | High |
| 4 | Autonomous host-watch (unattended) | Highest |

Built bottom-up: each rung's gate and sandbox model is proved before the next rung's power is enabled. Rung 0/1 come first (dev-box-safe); Rungs 3–4 are Mac-gated (see G).

---

### C — Authority & sandbox model: blast-radius-based (LOCKED)

**Rule: bounded blast-radius → automatic execution; crossing into the real host → graduated allowlist.**

- **In-sandbox** (no network; workspace-confined; disposable environment) — commands run **automatically**.
- **Boundary-crossing** (network; writes outside the workspace root; any external/real-world effect) — **graduated allowlist**: a novel crossing asks the owner once; once approved, that *specific* command or script graduates to automatic. A new crossing by an already-approved script re-asks. The allowlist is specific, not a blank cheque.
- Rung 3 (app/desktop control) is inherently boundary-crossing → always GATE-intercepted.
- Rung 4 (autonomous host-watch) runs automatic **only** for already-graduated crossers; novel crossers still ask.
- **Sandbox model:** file ops confined to declared workspace roots; code execution in a Lima/microVM (Apple Containerization, macOS 26, Mac-gated) or `sandbox-exec`/Seatbelt interim (deprecated seam, swap-able). This reuses the existing internal-reversible-auto / external-effect-gated boundary from ADR-012.

---

### D — Engine + coding subsystem

#### Engine (confirms ADR-022 §4)

Pydantic AI primitive + borrowed checkpoint/interrupt pattern (thread-keyed SQLite: `task → step + last-verified-output`) + the ADR-024 reliability spine. Local-first, thin. No framework runtime dependency.

#### Coding subsystem (Fork 1 — researched, locked)

**Plan/code split = locked design principle.** A strong planner (Claude/Opus) designs the approach; a separate coder implements. Matches the current Opus-plans / Codex-codes working cadence.

**Pluggable coder backend.** Codex (gpt-5.5) / DeepSeek API / GLM (Z.ai) / others, routed per-task by cost and capability via LiteLLM. Coding is **not** privacy-constrained (cloud backends are acceptable for code).

**Harness = BORROW OpenHands SDK** as the embedded coder. Selection rationale: the only candidate that is embeddable (not server-only), pluggable (provider-agnostic), coding-native, sandboxed, ships as an MCP package, and reaches tier-1 SWE-bench. Artemis owns the layers above OpenHands:

| Layer | Owner |
|---|---|
| Planner (Claude/Opus) | Artemis |
| `AskOwnerTool` + agent-inbox (pause-to-ask seam) | Artemis — **not present in any evaluated harness; built once, shared with host-action gate** |
| GATE (OpenHands' `WAITING_FOR_CONFIRMATION` defers to Artemis's single approval surface) | Artemis |
| Backend router (LiteLLM) | Artemis |
| Sandboxed code executor | OpenHands |

**Absorb RA.Aid's topology** (Research → Plan → Implement + per-stage model routing) as a pattern, not a dependency.

**Persistence: two layers, not merged.**
- OpenHands `conversation_id` / file-store = in-build state (per coding session).
- Artemis SQLite checkpoint = task-level plan-of-builds (durable, resumable across sessions).

---

### E — Models, budget, and privacy forks

**Driving model:** sensitivity-routed per ADR-022 — sensitive reasoning stays local; non-sensitive routes to cloud. Planner = strong (Claude/Opus); coder = pluggable.

**Budget:** per-task token and step ceilings checked pre-call; intra-model tiering for the coder backend (cheap tier for routine steps); circuit-breaker trips → agent-inbox. Primary scarce resource on the dev box is compute/RAM/GPU-residency, not dollars.

#### Fork 2 — Vision loop (Rung 3): cloud — Anthropic Computer Use ⚠️

**Decision (owner):** Rung 3 app/desktop control uses **Anthropic Computer Use** (cloud) for the vision-action loop.

**Privacy concession — explicit ADR-022 exception:** desktop screenshots egress to the Anthropic cloud. This is **the one place screen content leaves the box**. The ADR-022 local-first / sensitive-stays-local privacy wall is relaxed here by owner choice.

**Rationale:** no local vision-action model at Rung-3 quality is available on the dev box; the owner accepted the trade-off knowingly.

**Mitigations (mandatory, not optional):**
1. **Sensitive-screen pre-filter** — a local detector (reuses ADR-029 `SensitivityClassifier`) inspects each frame before it is sent. Known-sensitive apps (banking, health, password manager) skip cloud vision entirely when focused; high-grade items are redacted or the frame is withheld.
2. **Rung 3 actions still gate per C** — the vision loop produces an action proposal; the GATE intercepts all boundary-crossing actions regardless of the model used.

#### Fork 3 — GEPA self-improvement reflection: raw traces → cloud frontier ⚠️

**Decision (owner):** the GEPA self-improvement path (ADR-022 §4, Hermes borrow) sends **raw task traces — including potentially sensitive content — to a cloud frontier model** for reflection and recipe quality improvement.

**Privacy concession — explicit ADR-022 exception (flagged twice, owner approved):** sensitive task-trace content may egress passively via this path. The owner was offered a sanitized-traces option and declined.

**Rationale:** reflection quality degrades sharply on sanitized traces; the owner accepted the trade-off knowingly.

**Mitigations:**
1. **`cloud_reasoning_enabled` kill-switch** — the entire GEPA reflection path is gated behind this flag. Setting it to `false` disables all cloud egress on this path.
2. **Offline / async** — reflection never runs in the hot path; it runs background and asynchronous.
3. The kill-switch is the owner's documented escape hatch; the flag ships in user-facing config.

---

### F — Reliability gates

Settles from the research and reaffirms ADR-024:

- **External verification only.** The executor never self-judges. Each host action is followed by a deterministic read-back (file exists / exit 0 / expected output). "The model says it worked" is never accepted as verification.
- **Bounded blast-radius** = the C sandbox + graduated-allowlist gate (primary blast-radius control).
- **Phase-boundary context reset.** Failed-attempt context is not carried across the `plan → act → verify` phase boundaries. This is the highest-leverage anti-context-decay measure in the research.
- **Pre-call budgets + circuit-breaker.** Token and step ceilings are checked pre-call; a no-progress detector trips the circuit-breaker; escalate to agent-inbox on trip — never silent abort.

---

### G — Hardware-gating + build order

| Phase | What | Where |
|---|---|---|
| 1 | Executor spine: Pydantic AI + checkpoint + reliability spine + agent-inbox + GATE | Dev (now) |
| 2 | Rung 0/1 — read-only introspection + reversible file ops (workspace-confined) | Dev (now) |
| **3 ∥ 4** | **Coding subsystem** (embed OpenHands + router + planner/inbox/gate) **in parallel with** **Rung 2** command exec + `sandbox-exec`/Seatbelt interim | Dev (now); macOS-native Lima/Containerization sandbox is Mac-gated |
| 5 | Rung 3 — app/desktop control + Anthropic Computer Use vision loop + sensitive-screen pre-filter | **Mac-gated** |
| 6 | Rung 4 — autonomous host-watch | **Mac-gated tail** |
| 7 | GEPA self-improvement (full path) | End-state (requires recipes first) |

Phases 3 and 4 run in parallel (owner decision). Mac-gating means the feature can be developed and integration-tested on the dev box behind a flag, but the full runtime is validated on the Mac.

---

## Consequences

- **One engine for all agentic capability.** No second executor is introduced; host computer-use, coding tasks, and reaction-triggered tasks all flow through the ADR-024 executor. Reliability and gating infrastructure is built once.
- **Spec series is post-spoke-wave (ADR-024 § Consequences unchanged).** Executor spine · capability-ladder rungs · coding subsystem (OpenHands embed + router + AskOwnerTool) · sandbox/gate integration specs are written **after the spoke-wave completes**. They are not authored as part of this ADR.
- **Two explicit privacy-wall relaxations are on record.** Fork 2 (Rung 3 screenshots to Anthropic) and Fork 3 (GEPA raw traces to cloud frontier) are the only approved exceptions to ADR-022's local-first sensitive wall. Any future egress path requires a new explicit exception.
- **`AskOwnerTool` / agent-inbox is a shared primitive.** Built once in the coding subsystem; host-action gate reuses it. Not duplicated.
- **Agentic UI design is deferred.** Four new surfaces are needed against the locked travel-zoom map (ADR-028): (1) background-task monitor (status / progress / pause-resume-cancel); (2) plan-preview (ADR-024 trigger); (3) pause-to-ask-you answer surface (visual half of `AskOwnerTool` / agent-inbox — the novel load-bearing one); (4) build/task review (diffs / files / tests / commit). Design is a distinct apex-ui-ux-design discussion; it is downstream — design when the agentic build nears. Tracked in BACKLOG.
- **OpenHands as the embedded coder is a dependency introduction.** It is adopted as the coding engine behind Artemis-owned layers. A swap requires replacing only the sandboxed executor layer (the `AskOwnerTool`, planner, GATE, and router layers are Artemis-owned and unaffected).
- **`sandbox-exec`/Seatbelt is interim.** The Seatbelt API is deprecated (macOS). The sandbox seam is built as swap-able from day one; Lima/Apple Containerization replaces it on macOS 26 (Mac-gated).

---

## Alternatives considered

- **Separate host-computer-use runtime** — *rejected*: two executors means reliability, GATE, and task-memory built twice; the unified shape (decision A) avoids that.
- **Build a custom coding sandbox from scratch** — *rejected*: OpenHands is the only embeddable + pluggable + coding-native + sandboxed candidate at tier-1 SWE-bench; building a comparable sandbox in-house is out-of-scope.
- **Use OpenHands as the top-level harness (not embedded)** — *rejected*: Artemis needs to own the planner, agent-inbox, and GATE layers (none are present in OpenHands); embedding it under Artemis-owned layers keeps those seams clean.
- **Local vision model for Rung 3** — *not available at required quality on the dev box*. Deferred to Mac-gated phase where it could be revisited; Anthropic Computer Use accepted as the interim.
- **Sanitized-trace GEPA reflection** — *offered and declined by the owner*. Sanitization degrades reflection quality; the kill-switch is the accepted mitigation.
- **Adopting LangGraph runtime** — *rejected* (ADR-022): borrow checkpoint/interrupt patterns only, not the runtime.

---

## Refinement 2026-06-26 — coding subsystem, research-grounded (resolves §D parked items)

Spec-time research (`docs/research/2026-06-26-openhands-windows/README.md`) pins the OpenHands embed for the **Windows 8GB dev box** (Mac = parity host). Decision D ("BORROW OpenHands SDK") is unchanged; these are the concrete bindings:

1. **Bind to the V1 `openhands-sdk` (Software Agent SDK), NOT the legacy `openhands-ai` web app.** Packages `openhands-sdk` / `openhands-tools` / `openhands-agent-server` / `openhands-workspace` (v1.29.x, Python ≥3.12 — Artemis is on 3.12.10 ✓). It is built to embed in-process: `from openhands.sdk import LLM, Agent, Conversation, Tool` → `Conversation(agent, workspace).send_message(...).run()`. The legacy app is Docker/WSL2-first = wrong target.
2. **Local runtime, NOT Docker, on the dev box.** The Docker runtime wants ~12GB RAM + a WSL2 VM + multi-GB images; with a resident Ollama 7B (~5–6GB) the two are mutually exclusive on 8GB. The **local runtime** (agent-server as a host process, few-hundred-MB) is the only one that coexists with Ollama — but it provides **zero isolation by itself**.
3. **Sandbox = Artemis' existing Windows restricted-token + Job Object wrap around the local runtime** (the same isolation the Codex coder already uses — `apex-coder` profile). This is the Windows analogue of ADR-031's macOS `sandbox-exec` interim, and carries the **same Windows-only-parity caveat**: full sandbox parity is validated on the Mac.
4. **Spec against OpenHands' workspace abstraction (the parity escape hatch).** Same agent code runs `LocalWorkspace` (Windows dev, no native isolation → Artemis wraps it) vs `DockerWorkspace`/remote (Mac prod). Windows-dev and Mac-prod differ **only by workspace config** — the coding-subsystem spec binds to the workspace interface, not a concrete runtime.
5. **HITL mechanism = OpenHands `ConfirmationPolicy` + `SecurityAnalyzer` → Artemis GATE.** The agent enters `WAITING_FOR_CONFIRMATION`; a `SecurityAnalyzer` rates risk (low/med/high) and a custom `ConfirmationPolicy` (deferring to Artemis' single approval surface, decision C) decides when approval is required — risk-assessment is separated from enforcement, so the policy plugs in without touching tool executors. This is how the coding subsystem reuses the shared `AskOwnerTool`/agent-inbox + GATE seam (decision D's "WAITING_FOR_CONFIRMATION defers to Artemis").
6. **Backend router = LiteLLM** (built into the SDK: `LLM(model=, api_key=, base_url=)`), per-task Codex/DeepSeek/GLM/Ollama swap is trivial — confirms decision D's pluggable backend.

**⚠ Risk (FLAG, not blocker):** native-Windows OpenHands is **experimental** (PowerShell 7 + .NET Core + pythonnet; Python 3.12/3.13 only; browser tool unsupported; CLI runtime bash-based — upstream issues #9210, #86). Mitigation: the workspace-parity seam (4) means the dev box validates the embed + Artemis-owned layers behind the local runtime, and the full sandboxed runtime is validated on the Mac (Docker/remote workspace) — consistent with the existing Mac-gating posture.

## Parked / next

- Exact `AskOwnerTool` protocol (message schema, timeout behaviour, partial-result surface on timeout) — parked to coding-subsystem spec.
- ~~OpenHands embed bindings + Windows sandbox~~ — **RESOLVED 2026-06-26** (§ Refinement above).
- Sensitive-screen pre-filter detector list (which apps / which classifier signals trigger a skip) — parked to Rung 3 spec (Mac-gated).
- `cloud_reasoning_enabled` config surface (where the kill-switch lives in user config, default value) — parked to GEPA spec (end-state).
- Agentic UI design (4 surfaces above) — downstream, in BACKLOG.
- Spec series authoring — **IN PROGRESS 2026-06-26** (dev-buildable Phases 1–4; owner chose full-engine plan).
