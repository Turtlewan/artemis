# HERMES Agent — Architecture Analysis & Artemis Fit Assessment

**Date:** 2026-07-03
**Subject:** [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) — "The agent that grows with you"
**Method:** Direct source inspection of the `main` branch (module docstrings + SECURITY.md) via GitHub API, plus docs site and press coverage. All quotes below are from repo source.

---

## 1. Identification

**Hermes Agent** is Nous Research's open-source, self-hosted personal AI agent, released 2026-02-25 (v0.1.0), now at ~208k GitHub stars, MIT-licensed, Python (~82%). It is a long-lived single-tenant agent runtime: model-agnostic (any provider), reachable over 20+ messaging platforms via a gateway, with persistent memory, autonomous skill creation, built-in cron, and six pluggable terminal backends (local, Docker, SSH, Singularity, Modal, Daytona).

**Disambiguation:** Searches for other prominent "HERMES" agent projects (arXiv, GitHub) returned nothing of comparable prominence — older "Hermes" papers exist but are obscure and unrelated. Confidence is high that this is *the* HERMES agent: it is the same project covered by [Forbes](https://www.forbes.com/sites/sandycarter/2026/05/25/hermes-agentic-ai-overtakes-openclaw-10-shifts-leaders-need-to-know/) and [Turing Post](https://www.turingpost.com/p/hermes), with official docs at [hermes-agent.nousresearch.com](https://hermes-agent.nousresearch.com/).

Notably, Hermes and Artemis occupy the *same niche* (self-hosted personal agent, local-first, subscription/provider-agnostic), which makes its design decisions unusually transferable — and its mistakes unusually instructive.

---

## 2. Agentic Architecture

### 2.1 Core loop: single-agent ReAct-style turn loop, not a graph

There is no planner/executor split and no graph engine. The heart is [`agent/conversation_loop.py`](https://github.com/NousResearch/hermes-agent/blob/main/agent/conversation_loop.py) — a self-described "roughly 3,900-line `run_conversation` body that drives one user turn through the agent (model call, tool dispatch, retries, fallbacks, compression, post-turn hooks, background memory/skill review nudges)". It is a classic tool-calling loop wrapped in heavy production armor: error classification + provider failover (`error_classifier.py`, `turn_retry_state.py`), context compression (`context_compressor.py`, `conversation_compression.py`), prompt-cache preservation as a hard invariant ("never mutate past context"), and post-turn hooks.

Iteration control is a thread-safe **`IterationBudget`** ([`agent/iteration_budget.py`](https://github.com/NousResearch/hermes-agent/blob/main/agent/iteration_budget.py)): parent capped at 90 iterations, each subagent independently at 50; programmatic-tool-calling turns are *refunded* so script-driven work doesn't eat the budget.

### 2.2 Parallelism: three distinct mechanisms

1. **Subagent delegation** ([`tools/delegate_tool.py`](https://github.com/NousResearch/hermes-agent/blob/main/tools/delegate_tool.py)): `delegate_task` "spawns child AIAgent instances with isolated context, restricted toolsets, and their own terminal sessions. Supports single-task and batch (parallel) modes." Children get a fresh conversation, a focused system prompt, and a hard blocklist: no recursive delegation, no user interaction (`clarify`), no shared-memory writes, no `send_message`, no `execute_code`, no cron. "The parent's context only sees the delegation call and the summary result, never the child's intermediate tool calls."

2. **Async/background delegation** ([`tools/async_delegation.py`](https://github.com/NousResearch/hermes-agent/blob/main/tools/async_delegation.py)): `delegate_task(background=true)` returns a handle immediately; on completion an event is pushed to a shared `completion_queue` and "completions surface as a NEW turn when the agent is idle, never spliced between a tool result and an assistant message. That keeps strict message-role alternation legal and the prompt cache intact." The completion payload carries "a RICH, self-contained task-source block (the original goal, the context the parent supplied, toolsets, model, dispatch time, status, and the full result summary)" — because "the parent may be deep in unrelated context and won't remember why the subagent existed; the block lets it either use the result or re-dispatch if the world has moved on."

3. **Mixture-of-Agents (`/moa`)** ([`agent/moa_loop.py`](https://github.com/NousResearch/hermes-agent/blob/main/agent/moa_loop.py)): per-turn fan-out of up to 8 parallel *advisory* reference-model calls (no tools) whose outputs are gathered as context before each main-model iteration; "the normal Hermes agent loop still owns tool calling and turn termination." Per-advisor cost is priced at each advisor's own model rate.

Plus **Programmatic Tool Calling** ([`tools/code_execution_tool.py`](https://github.com/NousResearch/hermes-agent/blob/main/tools/code_execution_tool.py)): "Lets the LLM write a Python script that calls Hermes tools via RPC, collapsing multi-step tool chains into a single inference turn." Local transport is a Unix domain socket to a child process; remote backends use file-based RPC shipped into the sandbox. "Only the script's stdout is returned to the LLM; intermediate tool results never enter the context window." (Disabled on Windows — UDS.)

### 2.3 Self-correction & verification: an evidence ledger + a stop guard

This is Hermes' most original piece. Two deliberately decoupled modules:

- [`agent/verification_evidence.py`](https://github.com/NousResearch/hermes-agent/blob/main/agent/verification_evidence.py) — "records what the agent actually proved while working in a code workspace. It is deliberately passive: it never decides to run a suite, never blocks completion, and never upgrades targeted checks into 'repo green'." Classified command results (command, kind, scope, status, exit code, cwd, session) are persisted to a SQLite ledger with retention limits.
- [`agent/verification_stop.py`](https://github.com/NousResearch/hermes-agent/blob/main/agent/verification_stop.py) — "policy-only. It never runs checks itself; it turns the passive verification ledger into a bounded follow-up when the model tries to finish immediately after editing code without fresh evidence." Doc/prose-only edits are exempted (a curated non-code extension list) so a README edit "must never demand a /tmp verification script."

Beyond that: turn-level `/retry` and `/undo`, `TurnRetryState` + `classify_api_error` for provider failover, and message sanitization/repair of malformed tool-call arguments.

### 2.4 Tool & capability model: registry + composable toolsets + progressive disclosure + skills

- **Registry** ([`tools/registry.py`](https://github.com/NousResearch/hermes-agent/blob/main/tools/registry.py)): every tool file self-registers at module level, declaring "schema, handler, toolset membership, and availability check."
- **Toolsets** ([`toolsets.py`](https://github.com/NousResearch/hermes-agent/blob/main/toolsets.py)): named, composable groups of tools ("compose toolsets from other toolsets") used to scope subagents and platform surfaces.
- **Progressive tool disclosure** ([`tools/tool_search.py`](https://github.com/NousResearch/hermes-agent/blob/main/tools/tool_search.py)): when deferrable (MCP/plugin) tools would exceed 10% of the context window, they're replaced by three bridge tools — `tool_search`, `tool_describe`, `tool_call`. Two hard rules: core tools "never defer," and "the catalog is stateless across turns... rebuilt from the current tool-defs list every time" — a lesson from a competitor's regression where "a session-keyed catalog that drifts out of sync with the live tool registry produces silent tool dropouts."
- **Skills** = procedural memory: `SKILL.md` packages with YAML frontmatter (agentskills.io standard), progressive-disclosure support dirs (`references/`, `templates/`, `assets/`, `scripts/`), stored in `~/.hermes/skills/`. Skills may ship arbitrary Python that loads *into the agent process* (see §2.6).

### 2.5 Memory & self-improvement: post-turn review fork + curator

- **MemoryManager** ([`agent/memory_manager.py`](https://github.com/NousResearch/hermes-agent/blob/main/agent/memory_manager.py)): one orchestration point over pluggable providers (only one external provider allowed, "prevents tool schema bloat"); pre-turn `prefetch_all`, post-turn `sync_all`. Agent-curated `MEMORY.md`/`USER.md`, FTS5 full-text session search with LLM summarization, and a "learning graph" linking skills to memory chunks for the desktop UI.
- **Background review fork** ([`agent/background_review.py`](https://github.com/NousResearch/hermes-agent/blob/main/agent/background_review.py)): "After every turn... a daemon thread... replays the conversation snapshot in a forked AIAgent and asks itself 'should any skill/memory be saved or updated?'" The fork inherits the live runtime "so it hits the same prefix cache," runs with a tool whitelist limited to memory + skill tools, and — cleverly — when routed to a *cheaper different* model it replays "a compact DIGEST to minimise cold-written tokens. Same model → full replay; different model → digest."
- **Provenance** ([`tools/skill_provenance.py`](https://github.com/NousResearch/hermes-agent/blob/main/tools/skill_provenance.py)): a ContextVar distinguishes "agent-sediment skill writes from foreground user-directed writes... Skills a user asks a foreground agent to write belong to the user and must never be auto-curated."
- **Curator** ([`agent/curator.py`](https://github.com/NousResearch/hermes-agent/blob/main/agent/curator.py)): inactivity-triggered background maintenance agent that can "pin / archive / consolidate / patch agent-created skills." Strict invariants: "Only touches agent-created skills... Never auto-deletes — only archives... Pinned skills bypass all auto-transitions."

### 2.6 Safety doctrine: one honest boundary

[`SECURITY.md`](https://github.com/NousResearch/hermes-agent/blob/main/SECURITY.md) is the clearest-eyed agent security document I've seen shipped with a popular framework:

> "**The only security boundary against an adversarial LLM is the operating system.** Nothing inside the agent process constitutes containment — not the approval gate, not output redaction, not any pattern scanner, not any tool allowlist."

- Two supported postures: **terminal-backend isolation** (shell + file tools confined to a container/remote — but code-execution, MCP subprocesses, plugin/skill loading are NOT) vs **whole-process wrapping** (Docker Compose or NVIDIA OpenShell) — the latter required "when the agent ingests content from surfaces the operator does not control."
- **In-process heuristics are explicitly labeled non-boundaries** (§2.4): approval gate = "catches cooperative-mode mistakes, not adversarial output"; Skills Guard = "a review aid."
- **Skills Guard** ([`tools/skills_guard.py`](https://github.com/NousResearch/hermes-agent/blob/main/tools/skills_guard.py)): external skills land in a quarantine dir, get regex-scanned for exfiltration/injection/destructive patterns, then pass a **trust-tier × verdict install matrix** — `builtin` (allow all) / `trusted` (openai, anthropics, huggingface, NVIDIA repos; block only "dangerous") / `community` (block anything flagged unless `--force`). An opt-in AST-level deep audit ([`tools/skills_ast_audit.py`](https://github.com/NousResearch/hermes-agent/blob/main/tools/skills_ast_audit.py)) flags dynamic import/getattr patterns for human review.
- **Credential scoping** (§2.3): provider keys/gateway tokens stripped from the env of shell/MCP/cron/code-exec children by default — framed honestly as "reduces casual exfiltration. It is not containment."
- **External surfaces** (§2.6): every network-exposed adapter must refuse work "until an allowlist is set. Code paths that fail open when no allowlist is configured are code bugs in scope"; "session identifiers are routing handles, not authorization boundaries."

---

## 3. Fit Assessment for Artemis

Artemis and Hermes agree on the fundamentals (local-first, self-hosted, provider-agnostic, skill/capability accretion) but diverge on one axis that matters: **Hermes lets learned capabilities run inside the trusted agent process; Artemis forges capabilities as sandboxed, test-verified modules invoked behind confirm + quarantine.** Artemis's model is strictly stronger. Borrow Hermes's operational machinery, not its trust model.

### 3.1 Ideas to COPY / adapt

1. **Verification-evidence ledger + verify-on-stop guard** (`verification_evidence.py` + `verification_stop.py`). A passive SQLite record of what checks *actually ran* (command, scope, exit code, freshness), plus a separate policy module that challenges "done" claims lacking fresh evidence.
   *Maps onto:* the Spine's verify step — instead of trusting the actor-LLM's claim of success, the verify gate reads a ledger of real sandbox exit codes; the forge's 3-retry loop already produces this evidence, it just isn't persisted or consulted across steps. The passive-ledger/active-policy split keeps it cheap and non-invasive.

2. **Background results re-enter as a NEW turn, carrying a self-contained task-source block** (`async_delegation.py`). Never splice background-job output mid-turn; deliver it as a fresh turn when idle, with the original goal + dispatch context + result bundled so the consumer can act without remembering why the job existed.
   *Maps onto:* Spine proactive jobs and ADR-046 background sync fetchers delivering into the chat loop — the "rich task-source block" is exactly what a briefing/alert payload needs so the phrasing call has full context in one place, and the never-splice rule protects any future prompt-cache use on the subscription CLIs.

3. **Provenance tagging + a Curator for the capability library** (`skill_provenance.py`, `curator.py`). Tag every capability with its write origin (forge-authored vs user-directed); run an inactivity-triggered maintenance agent that may consolidate/archive/patch *only* forge-authored capabilities, never deletes (archive is recoverable), and honors user pins.
   *Maps onto:* the promoted-capability library — as build-by-chat accretes recipes, a periodic curator pass (one cheap model call, off the Spine's schedule) keeps the library from silting up, with Hermes's invariants preventing it from ever eating something the owner wrote or pinned.

4. **Trust-tier × scan-verdict install matrix for imported capabilities** (`skills_guard.py`). Quarantine dir → static scan → policy table keyed by (source trust, verdict).
   *Maps onto:* the forge promotion gate, if/when Artemis ever imports recipes from outside (community recipes, another machine): forge-authored+test-verified = one tier, user-pasted = another, external = quarantine+scan+explicit approve. The matrix formalizes what Artemis currently does ad hoc; the AST-audit-as-hint (not gate) pattern also fits Artemis's confirm-first UX.

5. **Progressive tool disclosure with a threshold gate and a stateless catalog** (`tool_search.py`). When the library outgrows the context budget, expose `search/describe/invoke` bridges instead of the full tool array — but rebuild the catalog from the live registry every turn (never session-keyed) and never defer core tools.
   *Maps onto:* the invoke path's match-first selector — today's library is small, but this is the documented scaling path, and the "stateless catalog, core never defers" pair of rules pre-empts the silent-dropout bug Hermes cites from a competitor.

6. **Programmatic tool calling for multi-step Spine jobs** (`code_execution_tool.py`). Let the model emit one script that RPCs capabilities, returning only stdout — intermediate results never enter context.
   *Maps onto:* the Spine's act step for chained jobs (fetch→transform→store), philosophically identical to the forge's single-structured-call doctrine. Caveat: Hermes's local transport is UDS ("Disabled on Windows"); Artemis would run the script inside the WSL2 sandbox with file-based RPC — which Hermes also ships for remote backends, so the pattern transfers.

### 3.2 Things NOT to copy

1. **In-process skill loading (skills as arbitrary Python imported into the agent).** Hermes's own SECURITY.md concedes "skills execute arbitrary Python at import time" and that terminal-backend sandboxing does NOT confine skill loading, plugins, MCP, or code-exec — only whole-process wrapping does. Artemis's capabilities-run-in-sandbox + dual-LLM quarantine model is architecturally stronger; adopting Hermes-style in-process skills for speed would be a regression on Artemis's core security bet. (Do, however, copy the *honesty* of the doctrine: write down which Artemis layers are boundaries — WSL2 isolate, quarantine — and which are heuristics — selector confirm, output redaction.)

2. **The monolithic God-object loop.** `conversation_loop.py` is a single ~3,900-line function extracted from an even larger `run_agent.py`, accessing parent state "via attribute lookup," with patch-forwarding shims to keep tests working, thread-locks throughout, and back-compat aliases everywhere. It's the scar tissue of viral growth. Artemis's typed, module-per-concern v2 structure (mypy-clean, small surfaces) is worth defending precisely when features accrete fastest.

3. **Always-on post-every-turn self-modification.** Hermes forks a background review agent after *every* turn to autonomously write memory and skills. That conflicts with Artemis's locked agency scope (suggest/ask, never auto), costs an extra model call per turn (real money on quota-routed subscription CLIs, real load on the 8GB dev box), and is the mechanism most likely to sediment junk — which is why Hermes then needs a Curator to clean up after it. If Artemis wants learning-from-usage, take the *curator-cadence* version (periodic, idle-triggered, provenance-scoped, propose-don't-write) and skip the per-turn fork.

### 3.3 Out of scope

The 20+ platform messaging gateway, voice/TTS stack, and Kanban/desktop plugins solve distribution problems Artemis doesn't have (client UI is locked to the Tauri travel-zoom map). The Atropos RL/trajectory-generation pipeline serves Nous's model-training agenda, not a personal harness.

---

## 4. Sources

- Repo: https://github.com/NousResearch/hermes-agent (main branch, inspected 2026-07-03)
- Key modules quoted: `agent/conversation_loop.py`, `agent/iteration_budget.py`, `agent/moa_loop.py`, `agent/verification_evidence.py`, `agent/verification_stop.py`, `agent/background_review.py`, `agent/curator.py`, `agent/memory_manager.py`, `tools/delegate_tool.py`, `tools/async_delegation.py`, `tools/code_execution_tool.py`, `tools/tool_search.py`, `tools/registry.py`, `tools/skills_guard.py`, `tools/skills_ast_audit.py`, `tools/skill_provenance.py`, `toolsets.py`, `SECURITY.md`
- Docs: https://hermes-agent.nousresearch.com/docs/ · https://hermes-agent.nousresearch.com/
- Press/context: https://www.forbes.com/sites/sandycarter/2026/05/25/hermes-agentic-ai-overtakes-openclaw-10-shifts-leaders-need-to-know/ · https://www.turingpost.com/p/hermes · https://www.i-scoop.eu/hermes-agent-from-nous-research/
