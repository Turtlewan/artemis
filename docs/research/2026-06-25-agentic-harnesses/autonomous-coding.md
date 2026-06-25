# Agentic Harnesses: Autonomous Coding Cluster

**Date:** 2026-06-25
**Re-research after:** 2026-07-09
**Cluster:** Autonomous one-shot build execution
**Purpose:** Evaluate 8 harnesses for Artemis's agentic engine — ability to take a settled design and drive a complete build (plan → implement → verify → commit) in one unattended pass, local-first, privacy-walled, Mac Mini final host + Windows dev box.

---

## Tool 1: OpenHands (formerly OpenDevin)

### What it is
Open-source autonomous software engineering platform and Agent SDK built on the CodeAct paradigm. Agents take actions (bash, edit, browse) that run in a sandboxed runtime; observations feed back into the agent loop.

**Maintainer:** All Hands AI (company) + open-source community
**License:** MIT [VERIFIED — GitHub]
**Language:** Python (backend), TypeScript (UI)
**Status (2026):** v1.7.0 (May 2026); 74,400+ GitHub stars, 9,400+ forks; most-adopted open agent framework by stars [VERIFIED — search results]

### Architecture
Event-stream architecture: `User Message → Agent → LLM → Action → Runtime (sandbox) → Observation → Agent`. November 2025 SDK v1 overhaul split into four packages: SDK (agent definitions), Tools (action handlers), Workspace (execution environments), Server (hosting). Docker sandbox is the default runtime; can also route to Modal/AWS/Fargate via SWE-ReX integration. Plan → edit → test loop is driven by CodeAct (Python-in-shell actions), not a fixed planner.

Sandbox: Docker container with repo checkout. File edits, shell commands, browser automation all run inside the container. Host isolation is enforced by Docker.

### Benchmark Standing
- OpenHands (Claude 3.5 Sonnet Thinking, own harness): **77.6% SWE-bench Verified** [COMMUNITY — search results; methodology note: own harness, may differ from third-party]
- OpenHands LM 32B (open model, Hugging Face): **37.2% SWE-bench Verified** [COMMUNITY — search results]

### Local / Subscription Model Support
Uses LiteLLM under the hood — supports 100+ providers: Claude, GPT, Gemini, Bedrock, Vertex, Azure, OpenRouter, **Ollama, vLLM, llama.cpp** [VERIFIED — docs.openhands.dev]. Running with Ollama backend eliminates code egress entirely [COMMUNITY — dev.to article]. OpenHands LM (32B) runs on a single 3090 GPU.

### MCP Support
Yes — native MCP integration in SDK v1. Agents can be configured with MCP servers; tools are auto-discovered. Integration tests cover MCP end-to-end [VERIFIED — docs.openhands.dev/sdk/guides/mcp].

### Lens Scores
- **L1 Host computer-use + sandbox safety:** H — Docker-sandboxed by default; agent never touches host directly; SWE-ReX routes to remote backends for full isolation.
- **L2 Local-first + privacy fit:** H — Ollama backend fully air-gaps the stack; no code egress; self-hostable with zero cloud dependency.
- **L3 Reliability + resumability:** M — Event-sourced architecture supports replay; no built-in checkpoint/resume across sessions documented; verify loop is LLM-judged (CodeAct can run tests but pass/fail judgment is model-side) [COMMUNITY].
- **L4 Build-vs-borrow / thin-spine fit:** H — SDK v1 is explicitly designed as a composable library; can be embedded as Artemis's executor module.
- **L5 One-shot end-to-end build execution:** H — Strongest open-source candidate; 77.6% SWE-bench Verified; CodeAct loop handles plan→edit→test→commit autonomously when given a spec.

### Known Limitations / Failure Modes
- Performance degrades significantly with local models below ~70B; recommended model is Claude 3.5 Sonnet or equivalent frontier [COMMUNITY].
- No built-in cross-session checkpoint; long builds that fail mid-way restart from scratch.
- Self-judge problem: model determines its own test pass/fail — external verification hook is possible but not default.
- Docker requirement on Windows requires WSL2 or Docker Desktop (adds friction on dev box) [ASSUMED].

---

## Tool 2: SWE-agent

### What it is
Open-source autonomous software engineering agent from Princeton + Stanford, designed around an Agent-Computer Interface (ACI) that gives the LLM specialised file/shell primitives optimised for code navigation.

**Maintainer:** Princeton NLP / Stanford researchers (open community)
**License:** MIT [VERIFIED — GitHub page in search results]
**Language:** Python
**Status (2026):** Active; NeurIPS 2024 paper; SWE-agent 2.0 released; SWE-ReX parallel sandbox layer added Feb 2025 [VERIFIED — search results].

### Architecture
Input: GitHub issue URL + model API key. Agent loop: read issue → explore repo via ACI commands (bounded file views, linter-checked edits) → reproduce bug → edit → run test suite → submit patch. Parallel runs via SWE-ReX (Docker, AWS, Modal, Fargate backends). No interactive planner; single-agent loop.

Sandbox: Docker container by default (SWE-ReX). Can run without Docker on local filesystem (less safe).

### Benchmark Standing
- SWE-agent (Claude 3.5 Sonnet): **~45-55% SWE-bench Verified** [ASSUMED — no fresh 2026 number found; 2024 paper showed ~12-18%; community sources suggest significant improvement with newer models; exact 2026 number NEEDS-DOMAIN: github.com for leaderboard].
- Mini-SWE-Agent (100-line Python): **>74% SWE-bench Verified** with frontier model [COMMUNITY — search results].

### Local / Subscription Model Support
Uses LiteLLM — supports OpenAI-compatible endpoints, Ollama, local models [VERIFIED — swe-agent.com/latest/config/models/]. Custom model registry via config file for cost tracking.

### MCP Support
No direct evidence of native MCP integration in SWE-agent itself [COMMUNITY — MCP results point to Sweep (different tool) and SWE-agent docs show no MCP section]. NEEDS-DOMAIN: github.com/swe-agent/swe-agent to confirm.

### Lens Scores
- **L1 Host computer-use + sandbox safety:** H — SWE-ReX enforces Docker/cloud sandbox; bounded ACI commands limit blast radius.
- **L2 Local-first + privacy fit:** M — Supports local models via LiteLLM; Docker-based sandbox keeps code local; but primary design assumes cloud API keys.
- **L3 Reliability + resumability:** M — ACI reduces context overflow (bounded file views); linter auto-reverts broken syntax. No checkpoint/resume across full build sessions [ASSUMED].
- **L4 Build-vs-borrow / thin-spine fit:** M — Usable as reference pattern; less SDK-like than OpenHands v1; tighter coupling to issue-resolution workflow rather than general spec execution.
- **L5 One-shot end-to-end build execution:** M — Strong at single bug-fix issues; less validated on multi-file spec-driven builds. Research tool more than production executor.

### Known Limitations / Failure Modes
- Designed for single-issue resolution, not multi-task spec execution.
- No built-in commit step (produces patch file, not commit).
- MCP integration unconfirmed.
- Best results require frontier API models; local model performance unvalidated at scale.

---

## Tool 3: Devin (Cognition AI)

### What it is
Proprietary closed-source autonomous AI software engineer from Cognition AI. Cloud SaaS product, not self-hostable.

**Maintainer:** Cognition AI
**License:** Proprietary / closed source
**Language:** Undisclosed (cloud service)
**Status (2026):** Devin 2.2 released; GA since Aug 2025; SWE-1.5 model powering it [VERIFIED — search results].

### Architecture
Multi-agent cloud pipeline: Planning Agent (Gemini/proprietary, understands requirements, decomposes tasks) → Execution Agent (file edits, dependency management) → Critique Agent (peer review, introduced Aug 2025) → Testing Agent (test runs, visual feedback). Runs in dedicated cloud VMs per task. "Devin Local Bridge" CLI is a thin client; inference stays in cloud. Interactive Planning mode: Devin proactively researches your codebase and returns a plan in seconds before execution.

Sandbox: Google Cloud VMs managed by Cognition; user has no control over sandbox config.

### Benchmark Standing
- Original Devin (2024): **13.86% SWE-bench** [VERIFIED — original paper].
- Devin 2.0 (spring 2026): **~45.8% SWE-bench Verified** ("standard" evaluation by Cognition) [COMMUNITY — search results; note: self-reported].
- SWE-1.5 on SWE-bench Pro: **40.08%** (second after Claude Sonnet 4.5 at 43.60%) [COMMUNITY].

### Local / Subscription Model Support
**No local model support.** Cloud-only; uses Cognition's proprietary SWE-1.5 model. Pro/Enterprise: zero-retention policy (no training on your code) [VERIFIED — search results]. Code is processed via Cognition cloud regardless.

### MCP Support
Yes — 48+ engineering MCP connectors available (Miro, Mixpanel, Honeycomb, Postman, monday.com, etc.); enterprise admin MCP management page [VERIFIED — docs.devin.ai search results].

### Lens Scores
- **L1 Host computer-use + sandbox safety:** H — Cloud VMs, fully isolated from user host; no host access at all.
- **L2 Local-first + privacy fit:** L — Mandatory cloud egress; no local model option; code leaves premises to Cognition infrastructure. Blocks Artemis's privacy-wall requirement.
- **L3 Reliability + resumability:** M — Interactive Planning + Critique Agent are reliability levers; cloud VM isolation prevents partial-state corruption. No external checkpoint mechanism documented.
- **L4 Build-vs-borrow / thin-spine fit:** L — Closed API; cannot embed as an SDK component in Artemis. Black-box SaaS.
- **L5 One-shot end-to-end build execution:** M — Multi-agent pipeline with critique step is purpose-built for end-to-end; but self-reported benchmarks, cloud-only, and no subscription control over model.

### Known Limitations / Failure Modes
- **Hard blocker for Artemis:** mandatory cloud egress violates local-first/privacy requirement.
- No local model support; metered SaaS pricing.
- Self-reported SWE-bench numbers; independent verification limited.
- Cannot be embedded or white-boxed.

---

## Tool 4: Aider

### What it is
CLI-based AI pair programmer that treats git as the source of truth. Auto-commits every successful edit with an AI-written message. Linter + test runner hooks enable a verify-and-loop pattern.

**Maintainer:** Paul Gauthier (original author) + community
**License:** Apache 2.0 [VERIFIED — search results]
**Language:** Python
**Status (2026):** 40,000–45,900 GitHub stars; active; v3.x series; development pace described as slower than Cline/OpenCode as of May 2026 [COMMUNITY].

### Architecture
CLI tool: user runs `aider` in repo directory with files in context. Agent sends files to LLM, receives edits (diff format), applies them, runs linter + optional test command after each edit, loops back to LLM on failure. Architect mode: separate planning step before coding. Git integration: auto-commit per successful change cycle.

No built-in sandbox — runs directly on the user's working tree. No container isolation.

### Benchmark Standing
- Was SoTA on SWE-bench Lite + Full as of June 2024 [COMMUNITY].
- Current standing (mid-2026): surpassed by Claude Code, Codex CLI, and others on leaderboards [COMMUNITY — search results]. Exact current number not found; NEEDS-DOMAIN: aider.chat/leaderboard.

### Local / Subscription Model Support
Yes — supports Ollama, LM Studio, any OpenAI-compatible endpoint, plus Claude/GPT/Gemini APIs [VERIFIED — search results]. Full local operation possible with Ollama.

### MCP Support
No confirmed MCP support found [COMMUNITY — search results note Codex CLI lacks MCP and Aider not mentioned as having it]. NEEDS-DOMAIN: aider.chat to confirm.

### Lens Scores
- **L1 Host computer-use + sandbox safety:** L — No sandbox; edits directly on working tree; terminal commands run on host without isolation.
- **L2 Local-first + privacy fit:** H — Full Ollama/local model support; no code egress required; self-contained CLI.
- **L3 Reliability + resumability:** M — Auto-commit per cycle provides git-as-checkpoint; linter/test loop is automated; but test failure recovery is model-judged, not externally verified. Long multi-file builds may drift.
- **L4 Build-vs-borrow / thin-spine fit:** M — Can be scripted/automated; no formal SDK; thin enough to wrap in Artemis pipeline via subprocess.
- **L5 One-shot end-to-end build execution:** M — Good for sequential multi-file edits with verify loop; less suited for full spec-driven orchestration unattended. Requires explicit file listing (not autonomous discovery).

### Known Limitations / Failure Modes
- No sandbox — risky for autonomous builds on production trees.
- No MCP (unconfirmed).
- Development pace trailing competitors in 2026.
- Context window management requires manual file selection; less autonomous than OpenHands for large codebases.
- No built-in commit-after-all-tasks workflow; commits per-edit, not per-spec.

---

## Tool 5: Cline

### What it is
Open-source autonomous coding agent available as VS Code extension, SDK, JetBrains plugin, and preview CLI. YOLO mode enables fully autonomous execution (no per-step approval). MCP-first architecture.

**Maintainer:** Cline (cline.bot) + open-source community
**License:** Apache 2.0 [VERIFIED — GitHub search results]
**Language:** TypeScript
**Status (2026):** v3.81; 61,200+ GitHub stars; 5M+ VS Code installs; shipping as SDK + CLI in addition to IDE extension [VERIFIED — search results].

### Architecture
Core Extension coordinates IDE integration + agent loop. Agent reads files, edits code, runs terminal commands, browses web, uses MCP tools. Plan/Act mode: structured planning step before execution. Checkpoint system tracks changes and enables rollback. YOLO mode: auto-approves all actions (file edits, terminal commands, browser actions, mode transitions) without per-step confirmation.

No built-in container sandbox — runs on host filesystem/terminal. "Computer Use" mode can drive a browser.

### Benchmark Standing
No SWE-bench Verified score found for Cline itself [COMMUNITY — cline.bot/blog/llm-benchmarks focuses on LLM benchmarks rather than Cline's own score]. NEEDS-DOMAIN: cline.bot for self-reported benchmark.

### Local / Subscription Model Support
Yes — supports Ollama, LM Studio, DeepSeek, Qwen, Llama, Claude, GPT, Gemini via OpenRouter and direct APIs [VERIFIED — search results]. Full local operation with Ollama.

### MCP Support
Yes — MCP is a first-class feature; Cline can connect to any MCP server to extend capabilities (databases, API docs, custom enterprise tools) [VERIFIED — search results and cline.bot docs].

### Lens Scores
- **L1 Host computer-use + sandbox safety:** L — No built-in container sandbox; YOLO mode runs commands directly on host. Risk mitigated by checkpoint/rollback but no isolation.
- **L2 Local-first + privacy fit:** H — Full local model support via Ollama; no mandatory cloud egress; self-hostable.
- **L3 Reliability + resumability:** M — Checkpoint system enables rollback; Plan/Act provides structured loop; but verify step is model-judged. YOLO mode removes human checkpoints entirely.
- **L4 Build-vs-borrow / thin-spine fit:** H — Now ships as SDK; can be embedded. CLI preview allows scripted invocation.
- **L5 One-shot end-to-end build execution:** M-H — YOLO mode enables true unattended execution; plan→implement→test→commit loop supported; but no container isolation means host risk on complex builds.

### Known Limitations / Failure Modes
- No container sandbox — YOLO mode on host is risky for destructive operations.
- No self-contained SWE-bench score to judge autonomous coding reliability.
- IDE-first design; CLI is still preview (macOS/Linux only as of search results, Windows unclear).
- MCP-heavy setup may add complexity for Artemis integration.

---

## Tool 6: OpenAI Codex CLI

### What it is
Terminal-first coding agent from OpenAI. Runs locally, reads repo, edits files, runs commands, reviews diffs. `codex exec` subcommand enables non-interactive/scripted automation.

**Maintainer:** OpenAI
**License:** Apache 2.0 (CLI is open-source) [VERIFIED — developers.openai.com]
**Language:** Rust (binary) + TypeScript
**Status (2026):** Active; bubblewrap sandbox on Linux; Docker devcontainer support; Bazel hermetic builds for CI [VERIFIED — search results].

### Architecture
CLI agent loop: observe context (file tree, git history, test results) → reason/plan → act (file edits, shell commands) → verify (check errors/test failures) → iterate. `codex exec` runs non-interactively, outputs plan+results to stdout — ideal for CI/CD, git hooks, scripted automation. Approval modes: Read Only, Auto (default), `--full-auto` (fully autonomous). Auto-commit available.

Sandbox: bubblewrap on Linux (kernel-level isolation); Docker devcontainer on cross-platform; Windows sandbox status unclear [ASSUMED — CI covers macOS/Linux/Windows but bubblewrap is Linux-only].

### Benchmark Standing
No specific SWE-bench Verified score for Codex CLI found in search results [COMMUNITY]. The underlying model (GPT-5.5/codex) scores 88.7% on SWE-bench Verified per OpenAI [COMMUNITY — from SWE-bench leaderboard search]. CLI score as an agent system not independently published [ASSUMED].

### MCP Support
Yes — native MCP support in both CLI and IDE extension; supports parallel MCP tool calls (halves wall time); configured via project files [VERIFIED — developers.openai.com/codex/mcp].

### Lens Scores
- **L1 Host computer-use + sandbox safety:** H on Linux (bubblewrap); M on Windows/Mac (Docker devcontainer; more setup) — sandbox is real on Linux, conditional elsewhere.
- **L2 Local-first + privacy fit:** M — CLI runs locally; BUT requires OpenAI API (cloud model); no local/Ollama model support for the primary agent model [ASSUMED — Codex model is OpenAI-only; no evidence of Ollama support]. Code context is sent to OpenAI. Blocks pure local-first requirement.
- **L3 Reliability + resumability:** M-H — `codex exec` + `--full-auto` is purpose-built for scripted loops; plan→exec→verify→fix stated as core workflow; auto-commit prevents lost work. External verification (AGENTS.md test gates) documented [VERIFIED — search results].
- **L4 Build-vs-borrow / thin-spine fit:** H — `codex exec` is exactly the APEX pattern; already used in Artemis's existing pipeline. Thin binary, scriptable, no IDE required.
- **L5 One-shot end-to-end build execution:** H — `codex exec` with `--full-auto` is explicitly the one-shot non-interactive build primitive. Current APEX implementation already uses this. Strong candidate for "borrow not build."

### Known Limitations / Failure Modes
- **Model lock-in:** requires OpenAI API; no local/Ollama fallback — privacy concern for Artemis.
- bubblewrap sandbox is Linux-only; Windows dev box needs Docker (adds friction).
- No self-reported agent-level SWE-bench score distinct from model score.
- Metered API cost (no subscription cap).

---

## Tool 7: Cursor Agent / Background Agents

### What it is
IDE-integrated autonomous coding agent (Cursor IDE). Standard Agent runs inline in editor; Background Agents (Cloud Agents) run in isolated Ubuntu cloud VMs asynchronously, producing merge-ready PRs.

**Maintainer:** Anysphere (Cursor)
**License:** Proprietary / closed source (IDE is commercial)
**Language:** TypeScript / Electron
**Status (2026):** Cloud Agents launched Feb 24, 2026; computer-use capability added; 200+ community MCP servers in registry [VERIFIED — search results].

### Architecture
Standard Agent: Cursor Composer (inline editor agent); autonomous loop with configurable iteration cap (default 8); reads stderr, runs tests, edits files. Background Agent: cloud Ubuntu VM with ephemeral repo checkout; async task queue; produces PR on completion; full desktop + browser via Computer Use. MCP configured via `.cursor/mcp.json`.

Sandbox: Background Agent → cloud VM (strong isolation); Standard Agent → local editor (no sandbox).

### Benchmark Standing
- Cursor Agent Loop (GPT-5.2-codex): **67.4% SWE-bench Verified** [COMMUNITY — search results, Cursor-reported].
- Claude Code 2.1 (Opus 4.7) in Cursor context: **80.8% SWE-bench Verified** (April 2026) [COMMUNITY].

### Local / Subscription Model Support
- Standard Agent: supports local Ollama/LM Studio models BUT telemetry still phones home by default; Privacy Mode opt-out required [VERIFIED — cursor.com/help/security-and-privacy/privacy].
- Background Agent: **requires cloud VM** — Privacy Mode blocks Background Agents entirely. Code sent to remote environment [VERIFIED — search results].
- No local-only path for Background Agents.

### MCP Support
Yes — MCP via `.cursor/mcp.json`; 200+ community MCP servers registered as of May 2026 [VERIFIED — search results].

### Lens Scores
- **L1 Host computer-use + sandbox safety:** H for Background Agents (cloud VM); M for Standard Agent (local editor, no isolation).
- **L2 Local-first + privacy fit:** L for Background Agents (mandatory cloud VM, blocked by Privacy Mode); M for Standard Agent (local model possible but telemetry concern).
- **L3 Reliability + resumability:** M — Async PR delivery is reliable end-state; iteration cap (default 8) limits runaway loops; no published checkpoint/resume mechanism for long builds [COMMUNITY].
- **L4 Build-vs-borrow / thin-spine fit:** L — IDE-centric; no SDK for embedding in Artemis pipeline; Background Agent is a SaaS API, not a library.
- **L5 One-shot end-to-end build execution:** M-H — Background Agents are designed for async one-shot builds producing PRs; strong for this use case. BUT cloud-only and metered.

### Known Limitations / Failure Modes
- Background Agents require cloud; Privacy Mode users cannot use them.
- Metered billing (separate from subscription credits) for Background Agents.
- IDE lock-in; difficult to embed in Artemis's pipeline architecture.
- Prompt injection risk via web browsing during Computer Use [VERIFIED — cursor.com privacy docs].
- Iteration cap (default 8) may terminate complex builds prematurely.

---

## Tool 8: Google Jules

### What it is
Google's async-first autonomous coding agent. Queue-based: describe task → walk away → PR arrives. Cloud-managed Gemini-powered multi-agent system.

**Maintainer:** Google (Google Labs / Google Cloud)
**License:** Proprietary / closed source
**Language:** Undisclosed (cloud service)
**Status (2026):** GA since Aug 6, 2025; Gemini 3.1 Pro as default since March 9, 2026; paid plans active [VERIFIED — search results].

### Architecture
Multi-agent: Planning Agent (Gemini 3.1 Pro, decomposes requirements) → Execution Agent (multi-file edits, dependency management) → Critique Agent (code quality/security peer review, Aug 2025) → Testing Agent (runs tests, visual feedback for web apps). Async queue — not live chat. Each task: isolated Google Cloud VM, ephemeral repo checkout, pre-loaded runtimes (Node, Python, Go, Java, Rust). PR output.

Sandbox: Google-managed cloud VMs; user has no control over VM configuration.

### Benchmark Standing
- Jules: **~51.8% SWE-bench Verified** [COMMUNITY — search results].
- Generated 140,000+ public code contributions during beta [COMMUNITY].

### Local / Subscription Model Support
**No local model support.** Cloud-only; uses Gemini family (3.1 Pro for hard tasks, Flash for lighter work). Pricing bundled with Google AI subscription tiers; free tier with usage limits [VERIFIED — search results]. Code processed in Google Cloud.

### MCP Support
No MCP support found in search results [COMMUNITY]. Jules is queue/webhook-based; has a GitHub Action integration (`jules-action`) [VERIFIED — github.com/google-labs-code/jules-action]. NEEDS-DOMAIN: jules.google/docs for MCP confirmation.

### Lens Scores
- **L1 Host computer-use + sandbox safety:** H — Google Cloud VMs, fully managed; strong isolation. No host access to user machine.
- **L2 Local-first + privacy fit:** L — Mandatory Google Cloud egress; no local model option; private repos protected from training but still processed in cloud. Blocks Artemis privacy wall.
- **L3 Reliability + resumability:** M-H — Critique Agent is a strong reliability lever (internal peer review before output); async architecture prevents blocking. No user-visible checkpoint.
- **L4 Build-vs-borrow / thin-spine fit:** L — Queue-based SaaS API; cannot embed as Artemis executor module. GitHub Action only.
- **L5 One-shot end-to-end build execution:** M-H — Async-first design is PURPOSE-BUILT for one-shot builds. Multi-agent pipeline with critique improves output quality. 51.8% SWE-bench is mid-tier. Cloud-only limits control.

### Known Limitations / Failure Modes
- **Hard blocker for Artemis:** mandatory cloud egress.
- No local model; Gemini-only.
- No MCP (unconfirmed).
- No checkpoint/resume visibility.
- Async-only; no live feedback loop for debugging.
- GitHub-centric integration; less flexible for non-GitHub workflows.

---

## Sources

- [OpenHands Review 2026 — Pickuma](https://pickuma.com/for-dev/openhands-review-open-source-autonomous-coding-agent-2026/)
- [OpenHands vs SWE-Agent: AI Coding Agents Compared — Local AI Master](https://localaimaster.com/blog/openhands-vs-swe-agent)
- [The OpenHands Software Agent SDK (arXiv Nov 2025)](https://arxiv.org/html/2511.03690v1)
- [OpenHands MCP Docs](https://docs.openhands.dev/sdk/guides/mcp)
- [OpenHands Local Setup Docs](https://docs.openhands.dev/openhands/usage/run-openhands/local-setup)
- [OpenHands Local LLM Coding Agent (freshlab.es)](https://www.freshlab.es/blog/openhands-local-llm-coding-agent)
- [SWE-agent Documentation — Models](https://swe-agent.com/latest/config/models/)
- [SWE-agent 2.0 Overview (yuv.ai)](https://yuv.ai/blog/swe-agent-v2)
- [Mini-SWE-Agent Local Models](https://mini-swe-agent.com/latest/models/local_models/)
- [Devin AI Guide 2026 — Singularity Moments](https://singularitymoments.com/devin-ai-coding-agent-guide/)
- [Devin 2.2 — Cognition](https://cognition.com/blog/introducing-devin-2-2)
- [Devin AI Review 2026 — AIToolRanked](https://aitoolranked.com/blog/devin-ai-review)
- [Aider Tutorial 2026 — NxCode](https://www.nxcode.io/resources/news/aider-complete-tutorial-guide-install-setup-2026)
- [Aider AI Pair Programming](https://aider.chat/)
- [Aider Deep Dive 2026 — DigitalApplied](https://www.digitalapplied.com/blog/aider-deep-dive-cli-agentic-coding-tutorial-2026)
- [Cline YOLO Mode Docs](https://docs.cline.bot/enterprise-solutions/configuration/infrastructure-configuration/control-other-cline-features/yolo-mode)
- [Cline v3.31 Release](https://cline.bot/blog/cline-v3-31)
- [Cline 2026 Setup Guide — DeployHQ](https://www.deployhq.com/guides/cline)
- [Codex CLI Official Docs](https://developers.openai.com/codex/cli)
- [Codex MCP Support](https://developers.openai.com/codex/mcp)
- [Codex CLI Features](https://developers.openai.com/codex/cli/features)
- [Codex CLI TDD Blog](https://codex.danielvaughan.com/2026/04/10/codex-cli-test-driven-development-workflow/)
- [Cursor 2026 Full Breakdown](https://chatgptaihub.com/what-s-new-in-cursor-2026-full-breakdown-for-developers/)
- [Cursor Background Agents 2026 — Morph](https://www.morphllm.com/cursor-background-agents)
- [Cursor Privacy Docs](https://cursor.com/help/security-and-privacy/privacy)
- [Cursor Background Agent Guide — AITechfy](https://aitechfy.com/blog/cursor-background-agents/)
- [Jules Google Blog](https://blog.google/innovation-and-ai/models-and-research/google-labs/jules/)
- [Jules Async Coding Agent Guide 2026 — DigitalApplied](https://www.digitalapplied.com/blog/google-jules-gemini-async-coding-agent-guide)
- [Jules Pricing and Features — MorphLLM](https://www.morphllm.com/comparisons/jules-google-coding-agent)
- [Best AI Coding Agents June 2026 — MorphLLM](https://www.morphllm.com/best-ai-coding-agents-2026)
- [SWE-bench Leaderboard 2026 — CodeAnt](https://www.codeant.ai/blogs/swe-bench-scores)
- [Best AI Coding Agents Benchmark-Driven — MarkTechPost](https://www.marktechpost.com/2026/05/15/best-ai-agents-for-software-development-ranked-a-benchmark-driven-look-at-the-current-field/)

---

## NEEDS-DOMAIN Hosts

- `github.com` — SWE-agent official leaderboard; Cline repo for MCP confirmation; Aider leaderboard
- `aider.chat` — Aider MCP support confirmation; current SWE-bench leaderboard position
- `jules.google` — Jules MCP support confirmation; full pricing tiers
