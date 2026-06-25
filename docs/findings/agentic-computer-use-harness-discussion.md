# Discussion brief — Artemis agentic capability: executor + harness + host computer-use

_Captured 2026-06-25 (coding session, for the next PLANNING session). This is a **framing/agenda doc, not a design or spec** — it folds the scattered existing pieces into one place and lists the questions for planning to work through. No options are recommended here; that's the planning discussion's job (prefer-discussion-over-specs)._

## The ask (owner, 2026-06-25)

"Fold in and look at the agentic part of Artemis — **doing things across the system and the computer it is on**, and **harnesses**." Owner's steer on scope: capture neutrally for planning, but the **true agenticness is likely (host computer-use) + (M9 executor + harness) combined** — i.e. the executor/harness *engine* extended to actually operate the machine Artemis lives on. **Needs discussion.**

## What already exists (fold these in — planning does not start cold)

- **ADR-024 — Task Executor (= M9).** General multi-step **plan→act→verify** agent, background-default, separate durable **task-memory**, reuses tools + GATE, graduates→recipes. Refinement 2026-06-23 already locked: supervised long-horizon, owner per-task unattended/supervised flag, plan-preview trigger, deterministic read-back verification (never self-judged), linear plans + reserved parallel-groups, plan-fresh + compose **atomic recipe primitives**, two-tier task-memory w/ sensitivity-defer, risk/milestone agent-inbox check-ins, per-task deadline+token budgets + intra-GPT model tiering + token-bucket retries + circuit-breaker, GPU residency priority. **Status: DESIGNED, post-spoke-wave.** This is the executor half.
- **ADR-022 — harness layer.** "Own thin spine + **Pydantic AI** + **MCP** + **OTel** + borrowed **LangGraph** checkpoint/interrupt patterns + Hermes's **GEPA**." Sensitivity routing (local vs cloud reasoner) + always-on local heartbeat that fires the cloud on-demand. This is the harness half.
- **`docs/research/2026-06-16-agent-loop-reliability.md`** — the reliability spine: a loop is safe ⇔ **idempotent · bounded · clean-state · externally-verified** (independence = master variable). Carries a per-loop Artemis audit + a 6-point guardrail checklist. Any agentic loop here must satisfy this.
- **BACKLOG line ~72 — "Autonomous agents on internal/local LLM tokens (Mini-resident)."** General autonomous agency as a runtime capability on free local inference, distinct from the teacher/distill pipeline and from M7 recipes. Already lists design tensions: authority vs the **locked internal-reversible-autonomy boundary + GATE**, reliability guardrails, which model serves them, token/compute budgeting, ACI-lane vs first-class subsystem. Its **triage step 0: define what an autonomous agent *does* (a concrete first use-case) before designing the harness.**
- **ADR-012 GATE + the locked "internal-reversible autonomy boundary"** (owner-rules): internal/reversible actions auto; external-effect actions gated. This is the existing authority model any host-action agent must extend, not bypass.
- **ADR-014 desk-vision HUD / guided-build assistant** — a sibling "agent acts in the world" capability (vision input); shares the capability-ladder framing.
- **Live reference: the APEX harness running this very session.** APEX (`apex-code` mechanic A) is already an agentic harness operating *this* computer — plan → dispatch `codex exec` subprocesses → run the verify recipe → fix-loop → commit, with a GATE-like permission model and per-task isolation/worktrees. The plan→dispatch→verify→commit loop, the reliability discipline, and the sandbox/permission model are a concrete, working pattern to borrow from (or even host the Artemis executor on).

## The genuinely-new surface: "the computer it is on"

M9/ADR-024 as written acts across **Artemis's own tools/spokes**. The new emphasis is **host/OS-level agency** — running shell commands, manipulating files, driving apps/the desktop on the Mac Mini (and the Windows dev box) Artemis lives on. That is a **much larger trust + sandbox surface** than calling a spoke tool, and it's the part that is *not* yet designed. The owner's "combined 1+2" thesis = make the M9 executor + harness the engine, and let it reach the host computer through a bounded computer-use capability.

## Questions for the planning discussion (not answered here)

1. **Concrete first use-case (triage step 0).** What is the first real host-action job? (e.g. "organise/rename downloaded files into the corpus", "run a local script + read back results", "drive a desktop app to do X".) Everything below is shaped by this.
2. **Scope of "computer-use."** Shell/process? Filesystem? App automation / desktop control (AppleScript/Accessibility on Mac; UI automation on Windows)? Full computer-use (screenshot→act) vs a curated host-action tool surface? A **capability ladder** (read-only host introspection → reversible file ops → command exec → app control → autonomous host-watch) mirroring the ADR-014 vision ladder?
3. **Authority & sandbox model.** How does host computer-use extend the locked internal-reversible-autonomy boundary + GATE? What's reversible-auto vs gated for *host* actions (rm, overwrite, network, app side-effects)? Sandbox/blast-radius (workspace-confined like APEX's `workspace-write`, vs broader)? This is the load-bearing safety question.
4. **Executor vs autonomous-agent vs reactions — one subsystem or several?** Does this consolidate M9 (ADR-024) + the BACKLOG autonomous-agents item into one "agentic runtime", and how does it relate to M7 recipes (declarative automations) and ADR-021 reactions (event→action)? Where's the boundary?
5. **Harness: build vs borrow vs host-on-APEX.** Confirm/refine ADR-022's thin-spine + Pydantic AI + MCP + LangGraph-patterns + GEPA. Should the Artemis executor *reuse the APEX harness pattern* (or even run as an apex-style loop) for host actions, given APEX already solves plan→dispatch→verify→commit + permissions + isolation on this machine?
6. **Which model drives it, and budget.** Local (MLX responder / DeepSeek-coding / expansion-box big-context) vs Codex/cloud, gated by sensitivity (ADR-022). "Tokens free but compute/RAM isn't" budgeting. Intra-GPT tiering (ADR-024) for sub-steps.
7. **Reliability gates.** Apply the `agent-loop-reliability` checklist to a host-acting loop specifically (idempotent host ops, bounded blast radius, clean-state between steps, **external** verification via deterministic read-back — never self-judged).
8. **HW-gating.** Which of this is dev-box-buildable now (logic, fakes, sandbox model) vs Mini-gated (real local models, macOS app/desktop control)?

## Suggested next step for planning

Run this as a **functional-design discussion** (apex-plan, not spec-drafting): start at Q1 (concrete first use-case), then the authority/sandbox model (Q3) and the consolidation question (Q4), since those gate everything. Likely outputs: an ADR refining/superseding the M9+harness scope to include host computer-use + a capability ladder, before any specs. Pull `2026-06-16-agent-loop-reliability.md` and ADR-024/022 into the session.
