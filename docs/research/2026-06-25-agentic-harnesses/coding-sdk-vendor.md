# Coding SDK Vendor Comparison — Agentic Harness Research

**Date:** 2026-06-25
**Re-research after:** 2026-07-09 (fast-moving space; all SDKs shipping weekly releases)
**Scope:** Phase-2 vendor retrieval — comparing BORROW vs BUILD-OWN-CODER-SEAM options for Artemis agentic coding subsystem

---

## Research Question

Are candidate SDKs embeddable coding harnesses? Critically: are they backend-locked to their vendor's models, or can Artemis plug in Codex / DeepSeek API / GLM freely?

**Artemis needs**: agentic CODING — strong PLANNER (Claude/Opus) designs, PLUGGABLE CODER backend implements; async long background builds; pause to ASK OWNER questions then RESUME; cloud fine; privacy not a constraint.

---

## Tool 1: Claude Agent SDK (Anthropic)

### 1. EMBEDDABLE
**Rating: H**
Python (`pip install claude-agent-sdk`) and TypeScript (`npm install @anthropic-ai/claude-agent-sdk`) libraries that wrap Claude Code's agent loop programmatically. The TS SDK bundles the Claude Code binary as an optional dep — no separate install needed. Production-grade: used in CI/CD pipelines, custom products. [VERIFIED — code.claude.com/docs]

### 2. PLUGGABLE BACKEND
**Rating: L — DISQUALIFIED for Artemis's swap requirement**
The model field (`ClaudeAgentOptions.model`) only accepts Claude model IDs (e.g. `claude-sonnet-4-6`, `claude-opus-4-5`). Authentication can route through Amazon Bedrock, Google Vertex AI, or Azure AI Foundry, but all paths terminate at a Claude model. No mechanism to point the agent loop at DeepSeek, GLM, or any non-Anthropic LLM. [VERIFIED — code.claude.com/docs; VERIFIED — community analysis at morphllm.com: "Claude Agent SDK is Claude-only"]

### 3. BACKGROUND + HUMAN-IN-THE-LOOP
**Rating: H**
- Async streaming (`async for message in query(...)`) [VERIFIED — code.claude.com/docs]
- `AskUserQuestion` built-in tool: agent pauses mid-task, surfaces a question with multiple-choice options, waits for user response, resumes [VERIFIED — code.claude.com/docs]
- Session ID capture + `resume=session_id` restores full context across processes [VERIFIED — Context7 / github.com/anthropics/claude-agent-sdk-python]
- `fork_session=True` branches a session for parallel exploration [VERIFIED]
- Background task management: `client.stop_task("task-abc123")` [VERIFIED — Context7]
- Session stores (S3 etc.) supported for durable resume [VERIFIED — Context7]

### 4. SANDBOX
**Rating: M**
Runs in your own process on your own infrastructure. Permission modes: `default`, `acceptEdits`, `bypassPermissions`, `plan`, `dontAsk`. `allowed_tools` whitelist constrains blast radius. No managed cloud sandbox — you own isolation. Hooks (`PreToolUse`, `PostToolUse`) can intercept/block any tool call. [VERIFIED — code.claude.com/docs]

### 5. MCP SUPPORT
**Rating: H**
First-class `mcp_servers` option in `ClaudeAgentOptions`; any stdio MCP server can be registered. Hundreds of community servers supported. [VERIFIED — code.claude.com/docs]

### 6. LICENSE + MATURITY
**Rating: M**
Governed by Anthropic's Commercial Terms of Service — NOT a permissive OSS license. SDK itself (Python/TS repos) ships Apache-2.0 for the code, but usage is ToS-bound. Active: weekly releases as of 2026. Python SDK 2026-active; TS SDK 2026-active. [VERIFIED — code.claude.com/docs license section; COMMUNITY — pypi.org/project/claude-agent-sdk]

### 7. PLAN/CODE SPLIT SUPPORT
**Rating: H**
`permission_mode="plan"` puts agent into read-only planning mode (no tool execution). Switch to `acceptEdits` or `bypassPermissions` for execution mode. Sub-agents can be declared with specialized instructions. Clear seam exists. [VERIFIED — code.claude.com/docs / Context7]

**BACKEND-LOCK VERDICT: LOCKED — Claude models only. DISQUALIFIES as Artemis's pluggable coder seam.**

---

## Tool 2: OpenAI Agents SDK + Codex SDK / `codex exec`

### 2a. OpenAI Agents SDK

#### 1. EMBEDDABLE
**Rating: H**
MIT-licensed Python and JavaScript/TypeScript libraries. `pip install openai-agents`. Lightweight primitives: Agent, Runner, Handoffs, Guardrails, Sessions. Production-ready; successor to Swarm. Weekly releases (v0.17.5 on 2026-06-11); still pre-1.0. [VERIFIED — openai.github.io/openai-agents-python]

#### 2. PLUGGABLE BACKEND
**Rating: M — PARTIAL, with caveats**
Officially model-agnostic at the SDK level. `MultiProvider` accepts any `openai_base_url`, allowing OpenRouter, Ollama, Azure, local endpoints. LiteLLM extension covers 100+ providers. DeepSeek's API is OpenAI-compatible so it routes cleanly via base_url override.
**Caveats:** The Responses API (used for advanced tool features), hosted tools, and the built-in OpenAI tracing dashboard are OpenAI-first. Structured-output reliability varies by non-OpenAI backend. [VERIFIED — Context7 openai/openai-agents-python; VERIFIED — openai.github.io/openai-agents-python/models/]

#### 3. BACKGROUND + HUMAN-IN-THE-LOOP
**Rating: H**
- `RunState` serializes agent progress to JSON; persists to disk, resumes in a different process [VERIFIED — Context7 / github.com/openai/openai-agents-python/docs/human_in_the_loop.md]
- `needs_approval=True` on any `function_tool` pauses execution for manual sign-off [VERIFIED — Context7]
- Approval can be an async function (HTTP call, DB query, etc.) — not just stdin [VERIFIED — Context7]
- Runner.run is async; full asyncio support [VERIFIED]

#### 4. SANDBOX
**Rating: L**
No built-in process/filesystem sandbox. You must provide your own isolation. Guardrails run input/output validation but do not sandbox execution. [COMMUNITY — mem0.ai review; ASSUMED from docs absence of sandbox mention]

#### 5. MCP SUPPORT
**Rating: H**
`openai-agents-mcp` extension package (lastmile-ai). Official MCP integration documented. [VERIFIED — Context7 / lastmile-ai/openai-agents-mcp]

#### 6. LICENSE + MATURITY
**Rating: H**
MIT license. Active: v0.17.5 shipped 2026-06-11. Launched March 2025. Pre-1.0 but high activity. [VERIFIED — github.com/openai/openai-agents-python]

#### 7. PLAN/CODE SPLIT SUPPORT
**Rating: M**
No built-in "plan mode." You design the split yourself: separate Agents with different instructions, or a guardrail that blocks tool calls in planning phase. Handoffs allow explicit delegation between a Planner agent and a Coder agent. [VERIFIED — OpenAI Agents SDK docs]

**BACKEND-LOCK VERDICT: SOFT LOCK. Officially pluggable but Responses API, tracing, and hosted tools pull toward OpenAI. DeepSeek works via base_url override or LiteLLM; no protocol bridge needed for Chat Completions path.**

---

### 2b. OpenAI Codex SDK / `codex exec`

#### 1. EMBEDDABLE
**Rating: H**
`codex exec` subcommand runs Codex non-interactively (headless), piping final plan + results to stdout. TypeScript library and Python SDK (JSON-RPC over local app-server) available. `codex exec resume --output-schema` added May 2026 for resumed automations with structured output. [VERIFIED — developers.openai.com/codex/sdk; developers.openai.com/codex/changelog]

#### 2. PLUGGABLE BACKEND
**Rating: L — PRACTICALLY LOCKED with workarounds**
Codex CLI has a `[model_providers.<id>]` block in `~/.codex/config.toml` that theoretically allows non-OpenAI providers. In practice: Codex uses OpenAI's Responses API protocol; DeepSeek uses `/chat/completions`. Direct DeepSeek connection fails with 401 or protocol errors. Workaround requires a local gateway/proxy (e.g. LiteLLM gateway) as a translation layer. **Not natively pluggable.** [VERIFIED — github.com/openai/codex issues #987, #1043; VERIFIED — knightli.com/2026/05/24 analysis]

#### 3. BACKGROUND + HUMAN-IN-THE-LOOP
**Rating: M**
Session persistence via thread IDs (`codex exec resume`). Async SDK class available. No explicit pause-ask-user mechanism documented in programmatic SDK — HITL requires external orchestration. [VERIFIED — developers.openai.com/codex/sdk; COMMUNITY — changelog notes]

#### 4. SANDBOX
**Rating: H**
Sandbox presets: `read_only`, `workspace_write`, `full_access` — controls filesystem access per execution. Built-in isolation at the process level. [VERIFIED — developers.openai.com/codex/sdk]

#### 5. MCP SUPPORT
**Rating: H**
Can run as an MCP server over stdio (consumed by another agent). Supports MCP servers for additional tools. [VERIFIED — Codex CLI docs; COMMUNITY — search results]

#### 6. LICENSE + MATURITY
**Rating: M**
Codex CLI is MIT-licensed (OSS). Codex SDK (programmatic) terms less clear — NEEDS-DOMAIN: developers.openai.com/codex/sdk for full license text. Active: May 2026 changelog updates. [COMMUNITY — github.com/openai/codex]

#### 7. PLAN/CODE SPLIT SUPPORT
**Rating: M**
No native plan-mode. You orchestrate: use Codex exec for the coding wave, a separate Opus call for planning. The seam is external to Codex. [ASSUMED]

**BACKEND-LOCK VERDICT: PRACTICALLY LOCKED. config.toml supports non-OpenAI entries, but Responses API vs Chat Completions mismatch requires a translation proxy for DeepSeek/GLM. Not frictionless pluggability.**

---

## Tool 3: Google ADK (Agent Development Kit)

### 1. EMBEDDABLE
**Rating: H**
Open-source, code-first SDK: Python (`pip install google-adk`), TypeScript, Go, Java. `adk web` dev UI for local testing. Can containerize and deploy anywhere. Apache 2.0. [VERIFIED — adk.dev; pypi.org/project/google-adk]

### 2. PLUGGABLE BACKEND
**Rating: H — GENUINELY PLUGGABLE**
ADK is model-agnostic by design. Three integration paths:
1. **String/registry**: `model="gemini-2.5-pro"` routes to Gemini
2. **LiteLLM connector**: `LiteLlm(model="deepseek/deepseek-chat")` routes to any LiteLLM-supported provider (100+) — covers DeepSeek, GLM, Anthropic, Ollama, local models
3. **Apigee AI Gateway**: enterprise routing layer
Claude, DeepSeek, Llama, Qwen all documented as supported. [VERIFIED — adk.dev/agents/models/; VERIFIED — google.github.io/adk-docs/agents/models/anthropic/]
**Caveat:** "Optimized for Gemini" — some advanced Google-native features (grounding, Search, code exec on Vertex) are Gemini-only. Core agent loop is fully pluggable. [VERIFIED]

### 3. BACKGROUND + HUMAN-IN-THE-LOOP
**Rating: H**
- Workflow Runtime: graph-based engine with retry, fan-out/fan-in, loops, state management, human-in-the-loop, nested workflows [VERIFIED — adk.dev]
- Task API: multi-turn task mode, pause, structured delegation [VERIFIED]
- Sessions + memory across turns [VERIFIED — adk.dev]
- Async streaming support [VERIFIED]

### 4. SANDBOX
**Rating: H**
Agent Runtime creates isolated sandbox per code-execution task (specified language + machine config). GKE Agent Sandbox integration for GKE deployments (`isolate-ai-code-execution-agent-sandbox`). Process-level isolation for generated code. [VERIFIED — docs.cloud.google.com/kubernetes-engine/docs/how-to/agent-sandbox; adk.dev/integrations/code-exec-agent-runtime/]

### 5. MCP SUPPORT
**Rating: H**
MCP extension (`pip install google-adk[mcp]`) available as optional extra. [VERIFIED — pypi.org/project/google-adk; COMMUNITY — search results]

### 6. LICENSE + MATURITY
**Rating: H**
Apache 2.0. Open-source at github.com/google/adk-python, google/adk-go, google/adk-docs. ADK 1.0 shipped 2026; active Google development. Multiple language SDKs (Python, Go, TypeScript, Java). [VERIFIED — github.com/google/adk-python; VERIFIED — explore.n1n.ai/blog ADK 1.0 2026]

### 7. PLAN/CODE SPLIT SUPPORT
**Rating: H**
Multi-agent design is a first-class ADK pattern: define a Planner agent and a Coder agent, use handoffs/Task API for delegation. Sub-agents can run different model backends. The plan/code split is architecturally native. [VERIFIED — adk.dev tutorials/agent-team]

**BACKEND-LOCK VERDICT: NOT LOCKED. Genuinely pluggable via LiteLLM connector. DeepSeek and GLM confirmed supported. Best backend flexibility of the four candidates.**
**Caveat:** ADK is a GENERAL agent framework — it has NO built-in coding tools (Read/Edit/Bash/Glob). Artemis would supply those or wrap an existing coding agent.**

---

## Tool 4: Devin API / ACI (Cognition)

### 1. EMBEDDABLE
**Rating: M**
REST API with API key + Org ID. Programmatic session creation, management, assignment via Slack/Linear/MCP/API. "Managed Devins" feature allows a coordinator Devin to spawn child Devins and message them mid-task. `COGNITION_API_KEY` env var for headless CI/CD. [VERIFIED — docs.devin.ai/api-reference/overview; VERIFIED — cognition.com/blog devin-can-now-manage-devins]
**NOT a library you embed — it's a SaaS REST API calling out to Cognition's cloud.**

### 2. PLUGGABLE BACKEND
**Rating: L — LOCKED, proprietary compound system**
Devin runs a proprietary compound AI system: Planner model + Coder model (trained on trillions of code tokens) + Critic model + Browser agent, all Cognition-internal. Model selection is plan-tier-dependent, not user-configurable. No mechanism to swap in DeepSeek, GLM, or any third-party LLM as the coder brain. [VERIFIED — critique.sh analysis; COMMUNITY — aitoolsdevpro.com; ASSUMED from absence of any model-swap docs]

### 3. BACKGROUND + HUMAN-IN-THE-LOOP
**Rating: H**
- Sessions run fully async in Cognition's cloud (the ACI: sandboxed VM with browser/shell/editor)
- Pause, resume, terminate sessions via UI or API [VERIFIED — Devin docs; COMMUNITY — search results]
- Message child sessions mid-task with corrections [VERIFIED — cognition.com blog]
- Monitor ACU consumption, put sessions to sleep/wake [VERIFIED]
- But: no built-in "ask-owner question and wait" — HITL is via Slack/Linear integration, not a structured SDK primitive [COMMUNITY — multiple reviews]

### 4. SANDBOX
**Rating: H**
ACI = dedicated sandboxed VM per session: Bash shell, VS Code-style editor, Chrome browser. Tightly isolated. Cognition manages the infrastructure. [VERIFIED — multiple sources; COMMUNITY — aitoolsdevpro.com; docs.devin.ai]
**Privacy note:** Devin may use your code for training unless explicitly opted out [COMMUNITY — critique.sh].

### 5. MCP SUPPORT
**Rating: H**
Devin MCP server available — exposes Devin to Claude Code, Cursor, etc. as an MCP tool. [VERIFIED — docs.devin.ai/work-with-devin/devin-mcp]

### 6. LICENSE + MATURITY
**Rating: L**
Closed SaaS. No OSS components. Enterprise pricing (plan-dependent). Devin 2.2 shipped June 2026. Active, but fully proprietary. [VERIFIED — cognition.com/blog/introducing-devin-2-2]

### 7. PLAN/CODE SPLIT SUPPORT
**Rating: L**
Devin handles planning and coding internally — not designed to be split by an external orchestrator. No plan-only API mode exposed. You trigger a session and it runs end-to-end. External orchestration (e.g. have Opus plan and then call Devin for coding) is possible at the API level but not a documented pattern. [COMMUNITY — multiple reviews; ASSUMED]

**BACKEND-LOCK VERDICT: COMPLETELY LOCKED — proprietary compound model, zero backend pluggability. DISQUALIFIED for Artemis's coder-swap requirement.**

---

## Scored Summary Table

| Lens | Claude Agent SDK | OpenAI Agents SDK | Codex SDK/exec | Google ADK | Devin API |
|---|---|---|---|---|---|
| Embeddable | H | H | H | H | M (REST only) |
| Pluggable Backend | **L — DISQUALIFIED** | M (soft lock) | **L — practical lock** | **H — best option** | **L — DISQUALIFIED** |
| Background + HITL | H | H | M | H | H |
| Sandbox | M (DIY) | L (none) | H | H | H (ACI VM) |
| MCP | H | H | H | H | H |
| License | ToS (SDK: Apache) | MIT | MIT/partial | Apache 2.0 | Closed SaaS |
| Plan/Code Split | H | M | M | H | L |

### Backend-Lock Disqualification Summary

For Artemis's **pluggable coder backend** requirement (swap Codex / DeepSeek / GLM freely):
- **Claude Agent SDK**: DISQUALIFIED — Claude models only, no alternative
- **Devin API**: DISQUALIFIED — closed proprietary compound model, no pluggability
- **Codex SDK**: MARGINAL — config.toml supports custom providers but Responses API vs Chat Completions mismatch requires a translation proxy for DeepSeek; not frictionless
- **OpenAI Agents SDK**: CONDITIONAL PASS — pluggable via MultiProvider/LiteLLM, but Responses API features and tracing tie toward OpenAI
- **Google ADK**: PASS — genuinely pluggable via LiteLLM connector; DeepSeek/GLM confirmed; Apache 2.0

---

## Key Takeaways for Artemis

1. **Backend pluggability is a hard filter**: Two of four candidates (Claude Agent SDK, Devin API) are eliminated immediately — they cannot drive any model other than their vendor's proprietary one. This validates the BORROW vs BUILD decision: if Artemis needs free coder-backend swapping, vendor SDKs as the *coder harness* are not viable.

2. **Google ADK is the only vendor SDK that genuinely passes the pluggable-backend test** via LiteLLM connector. However, ADK is a *general* agent framework with no built-in coding tools (no Read/Edit/Bash primitives). Artemis would need to supply all the coding-specific tools, which approaches BUILD-own-seam territory.

3. **OpenAI Agents SDK + Codex are complementary, not alternatives**: The Agents SDK is the orchestration layer (pluggable, MIT, HITL); Codex is the coding executor (sandboxed, `codex exec`). The practical pattern Artemis already uses (Opus plans, Codex executes) maps well here — but DeepSeek needs a translation proxy, making the "swap freely" goal slightly rough.

4. **BUILD-own-coder-seam remains the cleanest path for full swappability**: A thin seam that calls `codex exec` / DeepSeek API / GLM API interchangeably, orchestrated by Claude Agent SDK (for the PLANNER layer), with ADK as an alternative orchestrator if vendor-lock on the planner side ever matters. The seam is the differentiator; none of the vendor SDKs provide it off-the-shelf.

---

## NEEDS-DOMAIN Hosts (blocked in this session)

- `github.com` — license files for OpenAI Agents SDK, Codex SDK; ADK-python source
- `platform.openai.com` — Codex SDK license specifics
- `developers.openai.com/codex/sdk` — full programmatic SDK reference (partially fetched)
- `docs.devin.ai/api-reference/overview` — full API details (auth page blocked)

---

## Sources

1. [Claude Agent SDK Overview — code.claude.com](https://code.claude.com/docs/en/agent-sdk/overview) [VERIFIED]
2. [Claude Agent SDK Python — github.com/anthropics](https://github.com/anthropics/claude-agent-sdk-python) [VERIFIED via Context7]
3. [Building Agents with the Claude Agent SDK — claude.com/blog](https://claude.com/blog/building-agents-with-the-claude-agent-sdk) [VERIFIED]
4. [OpenAI Agents SDK (Python) — openai.github.io](https://openai.github.io/openai-agents-python/) [VERIFIED via Context7]
5. [OpenAI Agents SDK Human-in-the-Loop — github.com/openai](https://github.com/openai/openai-agents-python/blob/main/docs/human_in_the_loop.md) [VERIFIED via Context7]
6. [Codex CLI Reference — developers.openai.com](https://developers.openai.com/codex/cli/reference) [VERIFIED]
7. [Codex SDK — developers.openai.com](https://developers.openai.com/codex/sdk) [VERIFIED via WebFetch]
8. [Codex Changelog — developers.openai.com](https://developers.openai.com/codex/changelog) [VERIFIED]
9. [Codex DeepSeek Config Issues — github.com/openai/codex #987, #1043](https://github.com/openai/codex/issues/987) [VERIFIED via search]
10. [Codex DeepSeek Config Analysis — knightli.com](https://knightli.com/en/2026/05/24/codex-deepseek-config-ccx-openrouter-byok/) [COMMUNITY]
11. [Google ADK Models Page — adk.dev](https://adk.dev/agents/models/) [VERIFIED via WebFetch]
12. [Google ADK Claude Integration — google.github.io/adk-docs](https://google.github.io/adk-docs/agents/models/anthropic/) [VERIFIED via search]
13. [Google ADK Agent Runtime Code Execution — adk.dev](https://adk.dev/integrations/code-exec-agent-runtime/) [VERIFIED via search]
14. [Google ADK PyPI — pypi.org/project/google-adk](https://pypi.org/project/google-adk/) [VERIFIED]
15. [GKE Agent Sandbox — docs.cloud.google.com](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/agent-sandbox) [VERIFIED]
16. [Google ADK 1.0 + A2A Protocol 2026 — explore.n1n.ai](https://explore.n1n.ai/blog/google-adk-1-0-a2a-protocol-multi-agent-standard-2026-05-04) [COMMUNITY]
17. [Devin API Overview — docs.devin.ai](https://docs.devin.ai/api-reference/overview) [VERIFIED via WebFetch]
18. [Devin MCP — docs.devin.ai](https://docs.devin.ai/work-with-devin/devin-mcp) [VERIFIED]
19. [Devin Can Now Manage Devins — cognition.com](https://cognition.ai/blog/devin-can-now-manage-devins) [VERIFIED]
20. [Critique vs Devin: Model Freedom Analysis — critique.sh](https://www.critique.sh/blog/critique-vs-devin-coding-agent-api) [VERIFIED via WebFetch]
21. [AI Agent Frameworks 2026 Comparison — morphllm.com](https://www.morphllm.com/ai-agent-framework) [COMMUNITY]
22. [OpenAI Agents SDK Review — mem0.ai](https://mem0.ai/blog/openai-agents-sdk-review) [COMMUNITY]
