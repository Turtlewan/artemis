# Agentic runtime — design decisions (A–G)

_Decided 2026-06-25 (planning discussion, owner-led). Functional design, not a spec. Feeds a new **ADR-031 (agentic runtime / host computer-use)** that refines **ADR-024** (M9 Task Executor) + **ADR-022** (harness). Grounded by `docs/research/2026-06-25-agentic-harnesses/` (broad survey + coding-SDK deep-dive). Source brief: `docs/findings/agentic-computer-use-harness-discussion.md`._

## A — Architecture shape: ONE unified runtime
The M9 executor is the single engine (plan→act→verify, durable task-memory, reliability spine). Host computer-use is **a capability the executor reaches via the gated tool stack**, not a separate subsystem. "Autonomous agent" = the executor running unattended (ADR-024 supervised/unattended flag). **Recipes = saved executor plans; reactions (ADR-021) = events that fire executor tasks.** One engine, many front doors. Reliability/GATE/task-memory built once.

## B — Capability ladder: full Rung 0→4 (end-state), built bottom-up
| Rung | Power | Risk |
|---|---|---|
| 0 | read-only host introspection | ~none |
| 1 | reversible file ops (workspace-confined, trash-not-delete) | low |
| 2 | command/script exec (sandboxed) | medium |
| 3 | app/desktop control (vision-action loop) | high |
| 4 | autonomous host-watch (unattended) | highest |
Bottom-up so safe rungs prove the gate/sandbox model before high rungs run.

## C — Authority & sandbox: blast-radius-based (LOCKED)
**Rule:** bounded blast-radius → auto; crossing into the real host → graduated allowlist.
- **In-sandbox** (no network, workspace-confined, disposable) → commands run **auto**.
- **Boundary-crossing** (network, write outside workspace, any external/real effect) → **graduated allowlist**: novel crossing asks once; once approved, that *specific* command/script graduates to auto. Allowlist is specific, not a blank cheque (a new crossing by an approved script re-asks).
- Subsumes **Rung 3** (inherently boundary-crossing → always gate) and **Rung 4** (unattended runs auto only the already-graduated crossers).
- **Sandbox model:** file ops confined to declared workspace roots; code-exec in Lima/microVM (Apple Containerization on macOS 26; `sandbox-exec`/Seatbelt interim — a swap-able seam, Seatbelt is deprecated). GATE = reversibility governor for external-effect actions. Reuses the locked internal-reversible-auto / external-effect-gated boundary.

## D — Engine + coding subsystem
**Engine (confirms ADR-022):** Pydantic AI primitive + borrowed checkpoint/interrupt pattern (thread-keyed SQLite: `task → step + last-verified-output`) + reliability spine. Local-first, thin.

**Coding subsystem (Fork 1 — researched):**
- **Plan/code split = locked design principle** — strong planner (Claude/Opus) designs; separate coder implements. (Owner likes the current Opus-plans / Codex-codes flow.)
- **Pluggable coder backend** — Codex (gpt-5.5) / DeepSeek API / GLM (Z.ai) / others, per-task by cost/capability (LiteLLM). Coding is **NOT** privacy-constrained (cloud backends fine).
- **Harness = BORROW OpenHands SDK** as the embedded coder (only embeddable + pluggable + coding-native + sandboxed + MCP package; tier-1 SWE-bench). Artemis **owns the layers above**: planner (Claude/Opus), **AskOwnerTool + agent-inbox** (the pause-to-ask seam — missing in *every* candidate, so Artemis builds it once and shares it with host-actions), the **GATE** (OpenHands' own `WAITING_FOR_CONFIRMATION` configured to defer → single approval surface), and the **backend router**.
- **Absorb RA.Aid's topology** (Research→Plan→Implement + per-stage model routing) as pattern, not dependency.
- **Persistence: two layers** — OpenHands `conversation_id`/file-store = in-build state; Artemis SQLite checkpoint = task-level (plan-of-builds). Layer, don't merge.

## E — Models, budget, privacy forks
- **Driving model:** sensitivity-routed (ADR-022) — sensitive→local, non-sensitive→cloud. Planner strong; coder pluggable.
- **Budget:** per-task token + step ceilings checked pre-call, intra-model tiering, circuit-breaker → agent-inbox. "Compute/RAM/GPU-residency is the scarce resource, not dollars."
- **Fork 2 — vision loop (Rung 3): CLOUD (Anthropic Computer Use)** (owner). ⚠️ Knowing concession: desktop screenshots egress to Anthropic — the one place screen content leaves the box. **Guardrail (folded in): sensitive-screen pre-filter** — local detectors redact high-grade items / skip cloud vision when a known-sensitive app (banking/health/password-manager) is focused. Rung-3 actions still gate per C.
- **Fork 3 — GEPA reflection: RAW traces → CLOUD frontier** (owner, flagged twice). ⚠️ **Deliberate, owner-approved ADR-022 exception** — sensitive task-trace content egresses passively via the self-improvement path. Behind the `cloud_reasoning_enabled` kill-switch. Runs offline/async. (Sanitized-traces option offered and declined.)

## F — Reliability gates (research-settled; recorded)
- **External verification only** — executor never self-judges; deterministic read-back after each host action (file exists / exit 0 / expected output), never "model says it worked" (ADR-024 reaffirmed).
- **Bounded blast-radius** = the C sandbox + graduated gate.
- **Phase-boundary context reset** — don't carry failed-attempt context across plan→act→verify (highest-leverage anti-decay).
- **Pre-call budgets + circuit-breaker** → escalate to agent-inbox, never silent abort.

## G — HW-gating + build order
| Phase | What | Where |
|---|---|---|
| 1 | Executor spine (Pydantic AI + checkpoint + reliability + agent-inbox + gate) | dev now |
| 2 | Rung 0/1 — read + reversible file ops (workspace-confined) | dev now |
| **3 ∥ 4** | **Coding subsystem (embed OpenHands + router + planner/inbox/gate)** ∥ **Rung 2 command exec + sandbox** — IN PARALLEL (owner) | dev now; macOS-native sandbox Mac-gated |
| 5 | Rung 3 — app control + cloud vision + sensitive-screen pre-filter | **Mac-gated** |
| 6 | Rung 4 — autonomous host-watch | **Mac-gated tail** |
| 7 | GEPA self-improvement | end-state (needs recipes first) |

## Deferred — agentic UI (flagged 2026-06-25, future UI/UX discussion)
The agentic coding system needs UI, but mostly **reuses** existing/planned client surfaces (Ask-Artemis pop-up = kick-off · ntfy + M6-c = notifications · GATE-b pending-actions = approvals, extend for graduated-allowlist). **4 genuinely-new surfaces** to design against the **locked travel-zoom map** (not a new app): (1) background-task monitor (status/progress/pause-resume-cancel) · (2) plan-preview (ADR-024 trigger) · (3) **pause-to-ask-you answer surface** (visual half of `AskOwnerTool`/agent-inbox — the load-bearing novel one) · (4) build/task review (diffs/files/tests/commit). Distinct discussion (apex-ui-ux-design × locked client direction); downstream — design when the agentic build nears. Add to BACKLOG.

## Refinements (2026-06-25, post-design clarifications)

**(a) Headless-first — the UI is NOT a build dependency.** Distinguish the functional *seams* (`AskOwnerTool`/agent-inbox, GATE, task API) — which are part of the agentic build itself — from the *visual surface* (the 4 deferred panels). The engine is built and tested **headless-first**: every interaction has an existing channel — kick-off via dev CLI, pause-to-ask-you via **ntfy** (M6-c) → answer via CLI/API, approvals via CLI/API, progress via a CLI `list`, build review via `git diff`. This fits the **dev-machine-first** lens: the whole engine (spine, file rungs, coding subsystem) is buildable + testable on the Windows dev box before any client UI exists. The graphical UI is an **additive presentation layer**, layered on when the higher rungs justify it — not a prerequisite. Build order unchanged.

**(b) UI-building tasks need a VISUAL-review modality.** The coding subsystem is a general coder, so it plans and builds UIs (planner does the UX/visual planning — `apex-ui-ux-design`-style; coder implements). But UI **cannot be reviewed from a diff** — it must be *seen*. So UI tasks get **two visual touchpoints** on the same ask-you/build-review seam, with an **image/preview payload** (not a diff): (1) **mockup-preview before coding** (approve the look first — UI equivalent of plan-preview); (2) **rendered review after coding** (screenshot or live-preview of the real thing). Machinery to borrow (APEX already does this): **Playwright** (render→screenshot), **imagegen-frontend** skills (mockups), **run/verify** skills (live app), and the CLAUDE.md §0 cheap-mockup-in-editor + external-browser pattern. Even headless, visual review works via a rendered screenshot → ntfy-image / dev-box file. **Implications:** the deferred build-review UI surface (#4) must handle *visual* review (embedded screenshots / live preview) + a mockup-preview step — strengthening the case for that surface once UI-building tasks run; and the headless image channel (ntfy-image or rendered file) is a small addition to the engine, not the full UI.

## To author at session end
- **ADR-031 (agentic runtime / host computer-use)** — refines ADR-024 + ADR-022; folds A–G; records the two privacy concessions (Fork 2, Fork 3) as explicit ADR-022 exceptions with rationale.
- Spec series (later, post-spoke-wave per ADR-024) — executor spine · capability-ladder rungs · coding subsystem (OpenHands embed + router + AskOwnerTool) · sandbox/gate integration. Not now.
- Update BACKLOG pointer + status.md.
